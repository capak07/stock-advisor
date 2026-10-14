"""Analyst price targets, recommendation counts and rating changes via yfinance (source 16).

yfinance has no batch API for these, so the collector goes symbol by symbol through the shared
Yahoo limiter. A symbol Yahoo doesn't cover comes back empty and yields no record. The source
is capped per call (spec §7.2): holdings come first and the rest wait for a later run.
"""

import logging
import math
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd
from pydantic import BaseModel, ConfigDict

from advisor.collectors.base import Cadence, Category, RateLimiter, Scope, collect_per_symbol
from advisor.collectors.yahoo import rate_limited
from advisor.collectors.yfinance_bars import to_yahoo
from advisor.models import AssetType, Market

TickerData = tuple[dict, pd.DataFrame, pd.DataFrame]  # price targets, recommendations, rating changes
Loader = Callable[[str], TickerData]


class AnalystView(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    target_mean: float | None = None
    target_low: float | None = None
    target_high: float | None = None
    target_median: float | None = None
    rec_strong_buy: int | None = None
    rec_buy: int | None = None
    rec_hold: int | None = None
    rec_sell: int | None = None
    rec_strong_sell: int | None = None
    upgrades_30d: int = 0
    downgrades_30d: int = 0
    upgrades_90d: int = 0
    downgrades_90d: int = 0
    target_raises_30d: int = 0
    target_lowers_30d: int = 0


def _yahoo_load(yahoo_symbol: str) -> TickerData:
    import yfinance as yf  # imported lazily: slow import, and tests inject a fake

    logging.getLogger("yfinance").setLevel(logging.CRITICAL)  # it logs an ERROR line per 404
    ticker = yf.Ticker(yahoo_symbol)
    return ticker.analyst_price_targets or {}, ticker.recommendations, ticker.upgrades_downgrades


def _price(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _graded(upgrades: pd.DataFrame | None, now: pd.Timestamp, days: int) -> tuple[int, int, int, int]:
    """(upgrades, downgrades, target raises, target lowers) graded in the last `days` days."""
    if upgrades is None or upgrades.empty:
        return 0, 0, 0, 0
    recent = upgrades[(upgrades.index >= now - pd.Timedelta(days=days)) & (upgrades.index <= now)]
    action = recent["Action"] if "Action" in recent else pd.Series(dtype=str)
    target = recent["priceTargetAction"] if "priceTargetAction" in recent else pd.Series(dtype=str)
    return (
        int((action == "up").sum()),
        int((action == "down").sum()),
        int((target == "Raises").sum()),
        int((target == "Lowers").sum()),
    )


def analyst_view(
    symbol: str,
    targets: dict | None,
    recommendations: pd.DataFrame | None,
    upgrades: pd.DataFrame | None,
    as_of: datetime,
) -> AnalystView | None:
    targets = targets or {}
    latest = None
    if recommendations is not None and not recommendations.empty and "period" in recommendations:
        current = recommendations[recommendations["period"] == "0m"]
        if not current.empty:
            latest = current.iloc[0]
    has_upgrades = upgrades is not None and not upgrades.empty
    if not targets and latest is None and not has_upgrades:
        return None

    def count(column: str) -> int | None:
        if latest is None or column not in latest or pd.isna(latest[column]):
            return None
        return int(latest[column])

    now = pd.Timestamp(as_of.astimezone(UTC).replace(tzinfo=None))  # grade dates are naive UTC
    up_30, down_30, raises_30, lowers_30 = _graded(upgrades, now, 30)
    up_90, down_90, _, _ = _graded(upgrades, now, 90)
    return AnalystView(
        symbol=symbol,
        target_mean=_price(targets.get("mean")),
        target_low=_price(targets.get("low")),
        target_high=_price(targets.get("high")),
        target_median=_price(targets.get("median")),
        rec_strong_buy=count("strongBuy"),
        rec_buy=count("buy"),
        rec_hold=count("hold"),
        rec_sell=count("sell"),
        rec_strong_sell=count("strongSell"),
        upgrades_30d=up_30,
        downgrades_30d=down_30,
        upgrades_90d=up_90,
        downgrades_90d=down_90,
        target_raises_30d=raises_30,
        target_lowers_30d=lowers_30,
    )


class YFinanceAnalyst:
    name = "yfinance_analyst"
    category = Category.FUNDAMENTALS
    core = False
    best_effort = True
    cadence = Cadence.DAILY
    asset_types = frozenset({AssetType.STOCK})
    markets = frozenset({Market.US, Market.TSX})
    record_type = AnalystView
    freshness = timedelta(days=3)
    scope = Scope.SYMBOLS
    canary = ("AAPL", "RY.TO")
    canary_requires_records = True
    max_symbols = 200  # about 400 a day over two runs; older views are served from cache

    def __init__(self, load: Loader | None = None, limiter: RateLimiter | None = None) -> None:
        self._load = load or _yahoo_load
        self._limiter = limiter

    def fetch(self, symbols: Sequence[str], as_of: datetime) -> list[AnalystView]:
        def one(symbol: str) -> list[AnalystView]:
            if self._limiter is not None:
                self._limiter.acquire()
            view = analyst_view(symbol, *self._load(to_yahoo(symbol)), as_of)
            return [view] if view else []

        return collect_per_symbol(symbols, one, is_fatal=rate_limited)
