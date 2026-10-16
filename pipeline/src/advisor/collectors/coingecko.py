"""Crypto quotes in CAD from CoinGecko's keyless public API (spec source 4; core for crypto).

One request per run prices every held and watched coin: `/coins/markets` with `symbols=` returns
the top-ranked coin for each ticker. Many tokens share a ticker (12 coins call themselves "btc"),
and the top-ranked one is the real one. The keyless limit is small, unpublished and shared per
IP, and failed calls count toward it too, so the request is tried at most twice, the retry
honouring Retry-After. A quote not updated for a day is a dead listing and counts as missing.
"""

import time
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from advisor.collectors.base import (
    Cadence,
    Category,
    PartialFetch,
    RateLimiter,
    Scope,
    get_with_retries,
)
from advisor.collectors.coins import listed_as
from advisor.models import AssetType, Market

MARKETS_URL = "https://api.coingecko.com/api/v3/coins/markets"
COINGECKO_PER_MINUTE = 5
ATTEMPTS = 2
MAX_QUOTE_AGE = timedelta(days=1)


class CryptoQuote(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    coin_id: str
    price_cad: float = Field(gt=0)
    market_cap_cad: float | None = None
    volume_24h_cad: float | None = None
    change_24h_pct: float | None = None
    market_cap_rank: int | None = None
    updated_at: datetime


def _rank(row: dict[str, Any]) -> tuple[bool, int, float]:
    """Sort key: ranked coins first, best rank first, then the biggest market cap."""
    rank = row.get("market_cap_rank")
    return rank is None, rank or 0, -(row.get("market_cap") or 0.0)


def parse_quotes(
    symbols: Sequence[str], rows: Sequence[dict[str, Any]], as_of: datetime
) -> list[CryptoQuote]:
    """A current quote for each requested symbol CoinGecko prices, in the requested order."""
    best: dict[str, dict[str, Any]] = {}
    for row in rows:
        ticker = str(row.get("symbol") or "").upper()
        if ticker not in best or _rank(row) < _rank(best[ticker]):
            best[ticker] = row
    quotes: list[CryptoQuote] = []
    for symbol in symbols:
        row = best.get(listed_as(symbol))
        if row is None or not row.get("current_price") or not row.get("last_updated"):
            continue
        updated = datetime.fromisoformat(row["last_updated"].replace("Z", "+00:00"))
        if as_of - updated > MAX_QUOTE_AGE:
            continue  # a dead listing keeps its last price forever
        quotes.append(CryptoQuote(
            symbol=symbol,
            coin_id=row["id"],
            price_cad=row["current_price"],
            market_cap_cad=row.get("market_cap"),
            volume_24h_cad=row.get("total_volume"),
            change_24h_pct=row.get("price_change_percentage_24h"),
            market_cap_rank=row.get("market_cap_rank"),
            updated_at=updated,
        ))
    return quotes


class CoinGecko:
    name = "coingecko"
    category = Category.PRICES
    core = True  # spec §4.2: core for crypto; it only runs when crypto is held or watched
    best_effort = True
    cadence = Cadence.PER_RUN
    asset_types = frozenset({AssetType.CRYPTO})
    markets: frozenset[Market] = frozenset()
    record_type = CryptoQuote
    freshness = timedelta(days=2)
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

    def fetch(self, symbols: Sequence[str], as_of: datetime) -> list[CryptoQuote]:
        wanted = list(dict.fromkeys(symbols))
        tickers = sorted({listed_as(symbol).lower() for symbol in wanted})
        response = get_with_retries(
            self._client,
            MARKETS_URL,
            params={"vs_currency": "cad", "symbols": ",".join(tickers)},
            limiter=self._limiter,
            attempts=ATTEMPTS,
            sleep=self._sleep,
        )
        quotes = parse_quotes(wanted, response.json(), as_of)
        priced = {quote.symbol for quote in quotes}
        missing = [symbol for symbol in wanted if symbol not in priced]
        if missing:
            raise PartialFetch(quotes, f"CoinGecko has no current CAD quote for {', '.join(missing)}")
        return quotes
