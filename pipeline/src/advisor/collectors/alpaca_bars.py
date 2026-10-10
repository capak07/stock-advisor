"""Daily OHLCV bars for US stocks from Alpaca's free market-data API (source 2)."""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import httpx

from advisor.collectors.base import Cadence, Category, RateLimiter, Scope, get_with_retries
from advisor.models import ET, AssetType, DailyBar

ALPACA_BARS_URL = "https://data.alpaca.markets/v2/stocks/bars"
SYMBOLS_PER_REQUEST = 200
PAGE_LIMIT = 10_000
SIP_DELAY = timedelta(minutes=16)  # free plan: SIP data must be at least 15 minutes old
LOOKBACK = timedelta(days=100)  # about 68 trading days, enough for the 60-day history filter


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _to_bar(symbol: str, raw: dict) -> DailyBar | None:
    try:
        return DailyBar(
            symbol=symbol,
            day=datetime.fromisoformat(raw["t"]).astimezone(ET).date(),
            open=raw["o"],
            high=raw["h"],
            low=raw["l"],
            close=raw["c"],
            volume=raw["v"],
            source="alpaca",
        )
    except (KeyError, TypeError, ValueError):  # pydantic ValidationError is a ValueError
        return None


class AlpacaBars:
    name = "alpaca_bars"
    category = Category.PRICES
    core = True
    best_effort = False
    cadence = Cadence.PER_RUN
    asset_types = frozenset({AssetType.STOCK})
    record_type = DailyBar
    freshness = None
    scope = Scope.SYMBOLS
    canary = ("AAPL", "MSFT")

    def __init__(
        self,
        client: httpx.Client,
        key_id: str,
        secret_key: str,
        limiter: RateLimiter | None = None,
    ) -> None:
        self._client = client
        self._headers = {"APCA-API-KEY-ID": key_id, "APCA-API-SECRET-KEY": secret_key}
        self._limiter = limiter or RateLimiter(per_minute=180, burst=5)

    def fetch(self, symbols: Sequence[str], as_of: datetime) -> list[DailyBar]:
        unique = sorted(set(symbols))
        base_params = {
            "timeframe": "1Day",
            "start": _iso(as_of - LOOKBACK),
            "end": _iso(as_of - SIP_DELAY),
            "limit": PAGE_LIMIT,
            "adjustment": "all",
            "feed": "sip",
        }
        bars: list[DailyBar] = []
        for i in range(0, len(unique), SYMBOLS_PER_REQUEST):
            chunk = unique[i : i + SYMBOLS_PER_REQUEST]
            page_token: str | None = None
            while True:
                params = {**base_params, "symbols": ",".join(chunk)}
                if page_token:
                    params["page_token"] = page_token
                payload = get_with_retries(
                    self._client, ALPACA_BARS_URL, params=params, headers=self._headers,
                    limiter=self._limiter,
                ).json()
                for symbol, rows in (payload.get("bars") or {}).items():
                    parsed = (_to_bar(symbol, r) for r in rows or [])
                    bars.extend(b for b in parsed if b is not None)
                page_token = payload.get("next_page_token")
                if not page_token:
                    break
        return bars
