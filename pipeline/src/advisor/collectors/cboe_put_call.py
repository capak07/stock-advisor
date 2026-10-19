"""Cboe's daily put/call ratios: total, equity, index and exchange-traded products (source 19).

Cboe posts one small JSON file per trading day on its CDN, in the evening (about 21:00-23:00
ET). It has volume and open interest per product group. A day without a file answers HTTP 403,
not 404: a weekend, a holiday, or today before it's posted. So each fetch asks for the weekdays
of the last LOOKBACK_DAYS and keeps the days that have a file. If none has one, Cboe has moved
or blocked the files, and the fetch fails.

The ratios are computed from the put and call volumes, which are exact; the file's own ratio
strings are rounded to two places. "Total" covers every product listed on Cboe's exchanges,
not the whole US options market.

Cboe's terms limit storing copies of its site's materials, so only these few numbers are kept.
"""

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from typing import Any

import httpx

from advisor.collectors.base import Cadence, Category, RateLimiter, Scope, get_with_retries
from advisor.collectors.series import SeriesObservation
from advisor.models import ET, AssetType, Market

DAILY_URL = "https://cdn.cboe.com/data/us/options/market_statistics/daily/{day}_daily_options"
LOOKBACK_DAYS = 10
CBOE_PER_MINUTE = 60
GROUPS = {  # series name: Cboe's product group
    "cboe_total_put_call": "SUM OF ALL PRODUCTS",
    "cboe_equity_put_call": "EQUITY OPTIONS",
    "cboe_index_put_call": "INDEX OPTIONS",
    "cboe_etp_put_call": "EXCHANGE TRADED PRODUCTS",
}


def parse_day(payload: Mapping[str, Any], day: date) -> list[SeriesObservation]:
    """Each group's put volume over its call volume. Groups are found by name, never position."""
    rows: list[SeriesObservation] = []
    for series, group in GROUPS.items():
        volume = next(
            (entry for entry in payload.get(group) or [] if entry.get("name") == "VOLUME"), None
        )
        if volume is None:
            continue
        calls, puts = int(volume["call"]), int(volume["put"])
        if calls > 0:
            rows.append(SeriesObservation(series=series, day=day, value=puts / calls))
    if not rows:
        raise ValueError(f"Cboe's file for {day} has none of its put/call groups")
    return rows


def weekdays(as_of: datetime, days: int = LOOKBACK_DAYS) -> list[date]:
    """The weekdays of the last `days` ET days, today included, oldest first."""
    today = as_of.astimezone(ET).date()
    span = (today - timedelta(days=back) for back in range(days - 1, -1, -1))
    return [day for day in span if day.weekday() < 5]


class CboePutCall:
    name = "cboe_put_call"
    category = Category.OPTIONS
    core = False
    best_effort = True
    cadence = Cadence.DAILY
    asset_types = frozenset({AssetType.STOCK})
    markets = frozenset({Market.US})
    record_type = SeriesObservation
    freshness = timedelta(days=5)
    scope = Scope.MARKET
    canary: tuple[str, ...] = ()
    canary_requires_records = True
    max_symbols = None

    def __init__(self, client: httpx.Client, limiter: RateLimiter | None = None) -> None:
        self._client = client
        self._limiter = limiter

    def fetch(self, symbols: Sequence[str], as_of: datetime) -> list[SeriesObservation]:
        rows: list[SeriesObservation] = []
        for day in weekdays(as_of):
            try:
                response = get_with_retries(
                    self._client, DAILY_URL.format(day=day.isoformat()), limiter=self._limiter
                )
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 403:  # no file for that day
                    continue
                raise
            rows.extend(parse_day(response.json(), day))
        if not rows:
            raise RuntimeError(f"Cboe has no put/call file for the last {LOOKBACK_DAYS} days")
        return rows
