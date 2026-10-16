"""Daily crypto candles in USD from Coinbase Exchange's public API (spec source 5).

Rows are [time, low, high, open, close, volume], newest first, one per UTC day starting 00:00
UTC. Today's candle is still moving and is dropped. One request may span at most 300 days.
Coinbase lists USD products only (its one CAD product is USDC-CAD); CAD values come from
CoinGecko. A coin Coinbase doesn't list (404) simply has no candles.
"""

import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta

import httpx

from advisor.collectors.base import (
    Cadence,
    Category,
    RateLimiter,
    Scope,
    collect_per_symbol,
    get_with_retries,
)
from advisor.collectors.coins import listed_as, throttled
from advisor.models import AssetType, DailyBar, Market

CANDLES_URL = "https://api.exchange.coinbase.com/products/{product}/candles"
COINBASE_PER_MINUTE = 300  # the documented public limit is 10 per second
HISTORY_DAYS = 290  # one request; Coinbase refuses more than 300 candles
ONE_DAY = 86400
ATTEMPTS = 2  # a throttled exchange must not stall the holdings phase


def parse_candles(symbol: str, rows: Sequence[Sequence[float]], as_of: datetime) -> list[DailyBar]:
    """Finished days before `as_of`'s UTC day, oldest first."""
    today = as_of.astimezone(UTC).date()
    bars: list[DailyBar] = []
    for start, low, high, open_, close, volume in rows:
        day = datetime.fromtimestamp(start, UTC).date()
        if day < today:
            bars.append(DailyBar(
                symbol=symbol, day=day, open=open_, high=high, low=low, close=close,
                volume=volume, source="coinbase",
            ))
    return sorted(bars, key=lambda bar: bar.day)


class CoinbaseCandles:
    name = "coinbase_candles"
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

    def __init__(
        self,
        client: httpx.Client,
        limiter: RateLimiter | None = None,
        *,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = client
        self._limiter = limiter
        self._sleep = sleep

    def fetch(self, symbols: Sequence[str], as_of: datetime) -> list[DailyBar]:
        today = as_of.astimezone(UTC).date()
        window = {
            "granularity": ONE_DAY,
            "start": f"{today - timedelta(days=HISTORY_DAYS)}T00:00:00Z",
            "end": f"{today}T00:00:00Z",
        }

        def one(symbol: str) -> list[DailyBar]:
            product = f"{listed_as(symbol)}-USD"
            try:
                response = get_with_retries(
                    self._client,
                    CANDLES_URL.format(product=product),
                    params=window,
                    limiter=self._limiter,
                    attempts=ATTEMPTS,
                    sleep=self._sleep,
                )
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    return []  # not listed on Coinbase
                raise
            return parse_candles(symbol, response.json(), as_of)

        return collect_per_symbol(symbols, one, is_fatal=throttled)
