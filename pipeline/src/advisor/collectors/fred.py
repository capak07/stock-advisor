"""US macro series from FRED's public CSV download (spec source 20; core).

One keyless request per series. Several series in one request come back as a ZIP when their
dates differ, and a multi-series start date is silently ignored, so FRED is asked one series at
a time and rows outside the window are dropped here. Dates are observation dates, not release
dates (September's CPI is published in mid-October): Plan 3 applies the release lags. A day
without a value (a bond-market holiday) is an empty field.
"""

import math
from collections.abc import Sequence
from datetime import date, datetime, timedelta

import httpx

from advisor.collectors.base import (
    BUDGET_EXHAUSTED,
    Cadence,
    Category,
    DeadlineExceeded,
    PartialFetch,
    RateLimiter,
    Scope,
    check_deadline,
    get_with_retries,
)
from advisor.collectors.series import SeriesObservation
from advisor.models import ET, AssetType, Market

FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
FRED_PER_MINUTE = 30
SERIES = {
    "T10Y2Y": "10-year minus 2-year Treasury yield, percentage points",
    "T10Y3M": "10-year minus 3-month Treasury yield, percentage points",
    "DGS10": "10-year Treasury yield",
    "DGS2": "2-year Treasury yield",
    "VIXCLS": "VIX close",
    "BAMLH0A0HYM2": "ICE BofA US high-yield option-adjusted spread",
    "DFF": "effective federal funds rate, daily",
    "CPIAUCSL": "CPI for all urban consumers, monthly, seasonally adjusted",
    "UNRATE": "unemployment rate, monthly",
}
LOOKBACK = timedelta(days=450)  # 13 months of a monthly series plus its release lag, for YoY
HEADER = "observation_date"


def parse_csv(series: str, text: str, start: date, end: date) -> list[SeriesObservation]:
    """One series' values from `start` to `end`; anything but FRED's CSV is an error."""
    lines = text.lstrip("﻿").splitlines()
    if not lines or lines[0].split(",") != [HEADER, series]:
        raise ValueError(f"FRED sent no CSV for {series}")
    rows: list[SeriesObservation] = []
    for line in lines[1:]:
        day_text, _, raw = line.partition(",")
        day = date.fromisoformat(day_text)
        try:
            value = float(raw)
        except ValueError:  # "" (or ".") marks a day without a value
            continue
        if start <= day <= end and math.isfinite(value):
            rows.append(SeriesObservation(series=series, day=day, value=value))
    return rows


class Fred:
    name = "fred"
    category = Category.MACRO
    core = True
    best_effort = False
    cadence = Cadence.DAILY
    asset_types = frozenset({AssetType.STOCK})
    markets = frozenset({Market.US, Market.TSX})  # US rates and risk appetite move both markets
    record_type = SeriesObservation
    freshness = timedelta(days=7)
    scope = Scope.MARKET
    canary: tuple[str, ...] = ()
    canary_requires_records = True
    max_symbols = None

    def __init__(self, client: httpx.Client, limiter: RateLimiter | None = None) -> None:
        self._client = client
        self._limiter = limiter

    def fetch(self, symbols: Sequence[str], as_of: datetime) -> list[SeriesObservation]:
        end = as_of.astimezone(ET).date()
        start = end - LOOKBACK
        records: list[SeriesObservation] = []
        failures: list[str] = []
        for series in SERIES:
            try:
                check_deadline()
                response = get_with_retries(
                    self._client,
                    FRED_URL,
                    params={"id": series, "cosd": start.isoformat()},
                    limiter=self._limiter,
                )
                rows = parse_csv(series, response.text, start, end)
            except DeadlineExceeded:
                if not records:
                    raise
                raise PartialFetch(records, f"stopped at {series}: {BUDGET_EXHAUSTED}") from None
            except (httpx.HTTPError, ValueError) as exc:
                failures.append(f"{series}: {type(exc).__name__}: {exc}"[:200])
                continue
            if not rows:
                failures.append(f"{series}: no values since {start}")
            records.extend(rows)
        if failures:
            raise PartialFetch(
                records, f"{len(failures)} of {len(SERIES)} FRED series failed; first: {failures[0]}"
            )
        return records
