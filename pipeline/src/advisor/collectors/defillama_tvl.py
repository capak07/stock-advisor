"""Total value locked on a coin's own chain, from DefiLlama's free API (spec source 52).

One keyless request per held or watched coin that has a chain. The coin -> chain map is
hard-coded: `/v2/chains` symbols are unreliable (Polygon is POL, TON shows GRAM, and many
chains have none). Each point is 00:00 UTC of its day and the last one is a live partial day,
so only finished days are kept. A chain with no TVL answers zeros, which are dropped.
"""

import math
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict

from advisor.collectors.base import (
    Cadence,
    Category,
    RateLimiter,
    Scope,
    collect_per_symbol,
    get_with_retries,
)
from advisor.models import AssetType, Market

CHAIN_URL = "https://api.llama.fi/v2/historicalChainTvl/{chain}"
DEFILLAMA_PER_MINUTE = 60
CHAINS = {
    "ETH": "Ethereum",
    "SOL": "Solana",
    "AVAX": "Avalanche",
    "BNB": "BSC",
    "TRX": "Tron",
    "ADA": "Cardano",
    "POL": "Polygon",
    "MATIC": "Polygon",  # MATIC became POL
    "BTC": "Bitcoin",
}
LOOKBACK = timedelta(days=60)


class ChainTvl(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    chain: str
    day: date
    tvl_usd: float


def parse_history(
    symbol: str, chain: str, points: Sequence[dict[str, Any]], as_of: datetime
) -> list[ChainTvl]:
    """Finished days of the last 60, oldest first; days without TVL are dropped."""
    today = as_of.astimezone(UTC).date()
    start = today - LOOKBACK
    rows: list[ChainTvl] = []
    for point in points:
        day = datetime.fromtimestamp(point["date"], UTC).date()
        tvl = float(point["tvl"])
        if start <= day < today and tvl > 0 and math.isfinite(tvl):
            rows.append(ChainTvl(symbol=symbol, chain=chain, day=day, tvl_usd=tvl))
    return rows


class DefiLlamaTvl:
    name = "defillama_tvl"
    category = Category.ONCHAIN
    core = False
    best_effort = False
    cadence = Cadence.DAILY
    asset_types = frozenset({AssetType.CRYPTO})
    markets: frozenset[Market] = frozenset()
    record_type = ChainTvl
    freshness = timedelta(days=3)
    scope = Scope.SYMBOLS
    canary = ("ETH",)
    canary_requires_records = True
    max_symbols = None

    def __init__(self, client: httpx.Client, limiter: RateLimiter | None = None) -> None:
        self._client = client
        self._limiter = limiter

    def fetch(self, symbols: Sequence[str], as_of: datetime) -> list[ChainTvl]:
        def one(symbol: str) -> list[ChainTvl]:
            chain = CHAINS.get(symbol)
            if chain is None:
                return []  # a token without a chain of its own (LINK, DOGE, ...)
            response = get_with_retries(
                self._client, CHAIN_URL.format(chain=chain), limiter=self._limiter
            )
            return parse_history(symbol, chain, response.json(), as_of)

        return collect_per_symbol(symbols, one)
