"""Bi-monthly short interest from FINRA's settlement files (spec source 13, US only).

FINRA settles short interest on the 15th and the last business day of each month and publishes
about seven business days later, re-issuing files after first publication. The weekly run takes
the newest file that exists (unpublished files answer HTTP 403).
"""

import calendar
import csv
import io
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta

import httpx
from pydantic import BaseModel, ConfigDict, Field

from advisor.collectors.base import (
    Cadence,
    Category,
    RateLimiter,
    Scope,
    check_deadline,
    get_with_retries,
)
from advisor.models import ET, AssetType, Market
from advisor.schedule import previous_sessions
from advisor.symbols import requested_by_key, symbol_key

FINRA_SHORT_INTEREST_URL = "https://cdn.finra.org/equity/otcmarket/biweekly/shrt{day:%Y%m%d}.csv"
HEADER = [
    "accountingYearMonthNumber", "symbolCode", "issueName", "issuerServicesGroupExchangeCode",
    "marketClassCode", "currentShortPositionQuantity", "previousShortPositionQuantity",
    "stockSplitFlag", "averageDailyVolumeQuantity", "daysToCoverQuantity", "revisionFlag",
    "changePercent", "changePreviousNumber", "settlementDate",
]
NO_VOLUME_DAYS_TO_COVER = "999.99"  # FINRA's placeholder when average daily volume is zero
UNPUBLISHED = frozenset({403, 404})


class ShortInterest(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    settlement_date: date
    short_interest: int = Field(ge=0)
    previous_short_interest: int | None = Field(default=None, ge=0)
    avg_daily_volume: int | None = Field(default=None, ge=0)
    days_to_cover: float | None = None  # None when there was no volume to cover with


def settlement_dates(as_of: datetime, months: int = 2) -> list[date]:
    """Newest-first settlement dates up to today: the 15th and the month's last session."""
    today = as_of.astimezone(ET).date()
    found: set[date] = set()
    year, month = today.year, today.month
    for _ in range(months + 1):
        mid = previous_sessions(date(year, month, 15), 1)[0]
        month_end = previous_sessions(date(year, month, calendar.monthrange(year, month)[1]), 1)[0]
        found.update(day for day in (mid, month_end) if day <= today)
        year, month = (year, month - 1) if month > 1 else (year - 1, 12)
    return sorted(found, reverse=True)


def _optional_int(value: str) -> int | None:
    value = value.strip()
    return int(value) if value else None


def parse_short_interest(text: str, wanted: Mapping[str, str]) -> list[ShortInterest]:
    reader = csv.reader(io.StringIO(text), delimiter="|", quotechar='"')
    header = next(reader, None)
    if header != HEADER:
        raise ValueError(f"unexpected FINRA short interest header: {header}")
    column = {name: index for index, name in enumerate(HEADER)}
    rows: list[ShortInterest] = []
    seen: set[str] = set()
    for row in reader:
        if len(row) != len(HEADER):
            continue
        symbol = wanted.get(symbol_key(row[column["symbolCode"]]))
        if symbol is None or symbol in seen:
            continue
        try:
            volume = _optional_int(row[column["averageDailyVolumeQuantity"]])
            days = row[column["daysToCoverQuantity"]].strip()
            rows.append(ShortInterest(
                symbol=symbol,
                settlement_date=date.fromisoformat(row[column["settlementDate"]]),
                short_interest=int(row[column["currentShortPositionQuantity"]]),
                previous_short_interest=_optional_int(row[column["previousShortPositionQuantity"]]),
                avg_daily_volume=volume,
                days_to_cover=(
                    None if not days or days == NO_VOLUME_DAYS_TO_COVER or not volume else float(days)
                ),
            ))
        except ValueError:
            continue
        seen.add(symbol)
    return rows


class FinraShortInterest:
    name = "finra_short_interest"
    category = Category.FUNDAMENTALS
    core = False
    best_effort = False
    cadence = Cadence.WEEKLY
    asset_types = frozenset({AssetType.STOCK})
    markets = frozenset({Market.US})
    record_type = ShortInterest
    freshness = timedelta(days=20)
    scope = Scope.SYMBOLS
    canary = ("AAPL",)
    canary_requires_records = True
    max_symbols = None

    def __init__(self, client: httpx.Client, limiter: RateLimiter | None = None) -> None:
        self._client = client
        self._limiter = limiter

    def fetch(self, symbols: Sequence[str], as_of: datetime) -> list[ShortInterest]:
        wanted = requested_by_key(symbols)
        for day in settlement_dates(as_of):
            check_deadline()
            try:
                response = get_with_retries(
                    self._client, FINRA_SHORT_INTEREST_URL.format(day=day), limiter=self._limiter
                )
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in UNPUBLISHED:
                    continue
                raise
            return parse_short_interest(response.text, wanted)
        raise RuntimeError("no published FINRA short interest file in the last two months")
