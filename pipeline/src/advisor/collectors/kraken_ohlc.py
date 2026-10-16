"""Daily crypto candles in USD from Kraken's public API, to cross-check Coinbase (spec source 6).

Kraken names Bitcoin XBT and Dogecoin XDG. Rows are [time, open, high, low, close, vwap, volume,
count] with prices as strings, oldest first; `last` is the start of the last finished candle,
and later rows are still moving. Errors come back as HTTP 200 with an `error` list; an unknown
pair means Kraken doesn't list the coin.
"""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from advisor.collectors.base import (
    Cadence,
    Category,
    RateLimiter,
    Scope,
    collect_per_symbol,
    get_with_retries,
)
from advisor.collectors.coins import ExchangeThrottled, listed_as, throttled
from advisor.models import AssetType, DailyBar, Market

OHLC_URL = "https://api.kraken.com/0/public/OHLC"
KRAKEN_PER_MINUTE = 40  # Kraken asks for at most one public call per second
KRAKEN_NAMES = {"BTC": "XBT", "DOGE": "XDG"}
UNKNOWN_PAIR = "EQuery:Unknown asset pair"
THROTTLED = ("EAPI:Rate limit exceeded", "EGeneral:Temporary lockout")
ATTEMPTS = 2  # a throttled exchange must not stall the holdings phase
CHECK_DAYS = 35


def kraken_pair(symbol: str) -> str:
    base = listed_as(symbol)
    return f"{KRAKEN_NAMES.get(base, base)}USD"


def parse_ohlc(symbol: str, payload: Mapping[str, Any], as_of: datetime) -> list[DailyBar]:
    """Finished days before `as_of`'s UTC day, oldest first."""
    errors = payload.get("error") or []
    if errors:
        raise ValueError(f"Kraken: {', '.join(errors)}")
    result = payload["result"]
    last = int(result["last"])
    rows = next(value for key, value in result.items() if key != "last")
    today = as_of.astimezone(UTC).date()
    bars: list[DailyBar] = []
    for start, open_, high, low, close, _vwap, volume, _count in rows:
        day = datetime.fromtimestamp(start, UTC).date()
        if start <= last and day < today:
            bars.append(DailyBar(
                symbol=symbol, day=day, open=float(open_), high=float(high), low=float(low),
                close=float(close), volume=float(volume), source="kraken",
            ))
    return bars


class KrakenOhlc:
    name = "kraken_ohlc"
    category = Category.PRICES
    core = False
    best_effort = False
    cadence = Cadence.DAILY
    asset_types = frozenset({AssetType.CRYPTO})
    markets: frozenset[Market] = frozenset()
    record_type = DailyBar
    freshness = timedelta(days=3)
    scope = Scope.SYMBOLS
    canary = ("BTC",)
    canary_requires_records = True
    max_symbols = None

    def __init__(self, client: httpx.Client, limiter: RateLimiter | None = None) -> None:
        self._client = client
        self._limiter = limiter

    def fetch(self, symbols: Sequence[str], as_of: datetime) -> list[DailyBar]:
        since = int((as_of - timedelta(days=CHECK_DAYS)).timestamp())

        def one(symbol: str) -> list[DailyBar]:
            response = get_with_retries(
                self._client,
                OHLC_URL,
                params={"pair": kraken_pair(symbol), "interval": 1440, "since": since},
                limiter=self._limiter,
                attempts=ATTEMPTS,
            )
            payload = response.json()
            if UNKNOWN_PAIR in (payload.get("error") or []):
                return []  # not listed on Kraken
            errors = payload.get("error") or []
            if any(error.startswith(THROTTLED) for error in errors):
                raise ExchangeThrottled(f"Kraken: {', '.join(errors)}")
            return parse_ohlc(symbol, payload, as_of)

        return collect_per_symbol(symbols, one, is_fatal=throttled)
