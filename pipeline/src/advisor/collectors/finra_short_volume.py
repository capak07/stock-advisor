"""Daily short-sale volume from FINRA's consolidated Reg SHO file (spec source 14, US only).

One static file per trading day covers every symbol, so a run downloads one file and keeps the
requested symbols. Missing files (weekend, holiday, not published yet) answer HTTP 403.
"""

from collections.abc import Mapping, Sequence
from datetime import date, datetime, time, timedelta

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
from advisor.symbols import requested_by_key, symbol_key

FINRA_SHORT_VOLUME_URL = "https://cdn.finra.org/equity/regsho/daily/CNMSshvol{day:%Y%m%d}.txt"
PUBLISHED_AFTER = time(18, 30)  # files appear around 17:15 ET; leave a margin
LOOKBACK_WEEKDAYS = 5
UNPUBLISHED = frozenset({403, 404})


class ShortVolume(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    trade_date: date
    short_volume: float = Field(ge=0)
    short_exempt_volume: float = Field(ge=0)
    total_volume: float = Field(ge=0)


def candidate_days(as_of: datetime, lookback: int = LOOKBACK_WEEKDAYS) -> list[date]:
    """Newest-first weekdays whose file may exist; today counts only after publication time."""
    now = as_of.astimezone(ET)
    day = now.date() if now.time() >= PUBLISHED_AFTER else now.date() - timedelta(days=1)
    days: list[date] = []
    while len(days) < lookback:
        if day.weekday() < 5:
            days.append(day)
        day -= timedelta(days=1)
    return days


def parse_short_volume(text: str, wanted: Mapping[str, str]) -> list[ShortVolume]:
    """Rows for the wanted symbols; the header and the row-count trailer are skipped."""
    rows: list[ShortVolume] = []
    seen: set[str] = set()
    for line in text.splitlines():
        parts = line.strip().split("|")
        if len(parts) != 6 or parts[0] == "Date":
            continue
        symbol = wanted.get(symbol_key(parts[1]))
        if symbol is None or symbol in seen:
            continue
        try:
            rows.append(ShortVolume(
                symbol=symbol,
                trade_date=datetime.strptime(parts[0], "%Y%m%d").date(),
                short_volume=float(parts[2]),
                short_exempt_volume=float(parts[3]),
                total_volume=float(parts[4]),
            ))
        except ValueError:
            continue
        seen.add(symbol)
    return rows


class FinraShortVolume:
    name = "finra_short_volume"
    category = Category.FUNDAMENTALS
    core = False
    best_effort = False
    cadence = Cadence.DAILY
    asset_types = frozenset({AssetType.STOCK})
    markets = frozenset({Market.US})
    record_type = ShortVolume
    freshness = timedelta(days=4)
    scope = Scope.SYMBOLS
    canary = ("AAPL",)
    canary_requires_records = True
    max_symbols = None

    def __init__(self, client: httpx.Client, limiter: RateLimiter | None = None) -> None:
        self._client = client
        self._limiter = limiter

    def fetch(self, symbols: Sequence[str], as_of: datetime) -> list[ShortVolume]:
        wanted = requested_by_key(symbols)
        for day in candidate_days(as_of):
            check_deadline()
            try:
                response = get_with_retries(
                    self._client, FINRA_SHORT_VOLUME_URL.format(day=day), limiter=self._limiter
                )
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in UNPUBLISHED:
                    continue
                raise
            return parse_short_volume(response.text, wanted)
        raise RuntimeError(f"no FINRA short volume file in the last {LOOKBACK_WEEKDAYS} weekdays")
