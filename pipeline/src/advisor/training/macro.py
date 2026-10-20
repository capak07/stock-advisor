"""The macro series' history, as one long table for the stock model to train on.

The series are the live collectors' own (`fred.SERIES`, `boc_valet.SERIES`), fetched from the same
URLs and read by the same parsers, so training and prediction see identical names. Dates are
observation dates, not release dates: the features apply the release lags. FRED's high-yield
spread reaches back only to 2023, so earlier rows have none. A series that comes back without
values fails the build: a model trained without it would differ from the live one.
"""

from datetime import date

import httpx
import pandas as pd

from advisor.collectors import boc_valet, fred
from advisor.collectors.base import RateLimiter, check_deadline, get_with_retries
from advisor.collectors.series import SeriesObservation

COLUMNS = ["series", "day", "value"]


def macro_history(
    client: httpx.Client, start: date, end: date, limiter: RateLimiter | None = None
) -> pd.DataFrame:
    """Every FRED and Bank of Canada series from `start` to `end`, sorted by series then day."""
    records: list[SeriesObservation] = []
    for series in fred.SERIES:
        check_deadline()
        response = get_with_retries(
            client,
            fred.FRED_URL,
            params={"id": series, "cosd": start.isoformat()},
            limiter=limiter,
        )
        rows = fred.parse_csv(series, response.text, start, end)
        if not rows:
            raise ValueError(f"FRED sent no values for {series}")
        records.extend(rows)
    check_deadline()
    response = get_with_retries(
        client,
        boc_valet.VALET_URL.format(series=",".join(boc_valet.SERIES)),
        params={"start_date": start.isoformat(), "end_date": end.isoformat()},
        limiter=limiter,
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
