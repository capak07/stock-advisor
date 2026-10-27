"""The macro series' history, as one long table for the stock model to train on.

The series are the live collectors' own (`fred.SERIES`, `boc_valet.SERIES`), fetched from the same
URLs and read by the same parsers, so training and prediction see identical names. Dates are
observation dates, not release dates: the features apply the release lags. FRED's high-yield
spread reaches back only to 2023, so earlier rows have none. A series that comes back without
values fails the build: a model trained without it would differ from the live one.
A whole history is a much bigger answer than the live collectors' recent rows, and FRED is
sometimes slow to send it, so these requests wait longer and retry more patiently. The whole
step still gets at most BUDGET_SECONDS, so a FRED that is slow on every series cannot outlast
the job. A source not answering in time fails with `MacroUnavailable`, naming the series.
"""

import logging
import time
from collections.abc import Callable, Mapping
from datetime import date
from typing import Any

import httpx
import pandas as pd

from advisor.collectors import boc_valet, fred
from advisor.collectors.base import (
    RETRY_STATUS,
    DeadlineExceeded,
    RateLimiter,
    deadline,
    get_with_retries,
    time_left,
)
from advisor.collectors.series import SeriesObservation

COLUMNS = ["series", "day", "value"]
ATTEMPTS = 6
BASE_DELAY = 10.0  # waits 10, 20, 40, 80 and 160 s between tries (longer if Retry-After says so)
TIMEOUT = httpx.Timeout(120.0, connect=15.0)
BUDGET_SECONDS = 20 * 60  # for every macro request together; a healthy FRED needs about a minute

log = logging.getLogger(__name__)


class MacroUnavailable(RuntimeError):
    """FRED or the Bank of Canada did not answer after every try."""


def _fetch(
    client: httpx.Client,
    source: str,
    what: str,
    url: str,
    params: Mapping[str, Any],
    limiter: RateLimiter | None,
    sleep: Callable[[float], None],
    clock: Callable[[], float],
) -> httpx.Response:
    try:
        return get_with_retries(
            client, url, params=params, limiter=limiter, attempts=ATTEMPTS, base_delay=BASE_DELAY,
            sleep=sleep, clock=clock, timeout=TIMEOUT,
        )
    except DeadlineExceeded as exc:
        raise MacroUnavailable(
            f"{source} did not answer for {what} within the macro step's {BUDGET_SECONDS // 60} minutes"
        ) from exc
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in RETRY_STATUS:
            raise MacroUnavailable(
                f"{source} did not answer for {what} after {ATTEMPTS} tries ({exc})"
            ) from exc
        raise MacroUnavailable(
            f"{source} refused {what} (HTTP {exc.response.status_code}): "
            f"{exc.response.text[:200]}"
        ) from exc
    except httpx.HTTPError as exc:
        raise MacroUnavailable(
            f"{source} did not answer for {what} after {ATTEMPTS} tries ({type(exc).__name__}: {exc})"
        ) from exc


def macro_history(
    client: httpx.Client,
    start: date,
    end: date,
    limiter: RateLimiter | None = None,
    *,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> pd.DataFrame:
    """Every FRED and Bank of Canada series from `start` to `end`, sorted by series then day."""
    at = clock() + BUDGET_SECONDS
    outer = time_left(clock)  # an earlier deadline set by the caller still applies
    with deadline(at if outer is None else min(at, clock() + outer)):
        return _macro_history(client, start, end, limiter, sleep, clock)


def _macro_history(
    client: httpx.Client,
    start: date,
    end: date,
    limiter: RateLimiter | None,
    sleep: Callable[[float], None],
    clock: Callable[[], float],
) -> pd.DataFrame:
    records: list[SeriesObservation] = []
    for series in fred.SERIES:
        log.info("macro: FRED %s", series)
        response = _fetch(
            client, "FRED", series, fred.FRED_URL, {"id": series, "cosd": start.isoformat()},
            limiter, sleep, clock,
        )
        rows = fred.parse_csv(series, response.text, start, end)
        if not rows:
            raise ValueError(f"FRED sent no values for {series}")
        records.extend(rows)
    wanted = ", ".join(boc_valet.SERIES)
    log.info("macro: Bank of Canada %s", wanted)
    response = _fetch(
        client,
        "Bank of Canada",
        wanted,
        boc_valet.VALET_URL.format(series=",".join(boc_valet.SERIES)),
        {"start_date": start.isoformat(), "end_date": end.isoformat()},
        limiter,
        sleep,
        clock,
    )
    observations = boc_valet.parse_observations(response.json(), list(boc_valet.SERIES))
    missing = sorted(set(boc_valet.SERIES) - {row.series for row in observations})
    if missing:
        raise ValueError(f"Bank of Canada sent no values for {', '.join(missing)}")
    records.extend(observations)
    frame = pd.DataFrame(
        {
            "series": [r.series for r in records],
            "day": [r.day for r in records],
            "value": [r.value for r in records],
        }
    )
    return frame.sort_values(["series", "day"], ignore_index=True)[COLUMNS]
