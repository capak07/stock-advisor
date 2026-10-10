"""Test doubles and builders shared by unit and integration tests."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from pydantic import BaseModel

from advisor.collectors.base import Cadence, Category, Scope
from advisor.models import AssetType, DailyBar, SymbolInfo


class FakeClock:
    """Monotonic clock whose sleep() advances time instantly and records the duration."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@dataclass
class FakeCollector:
    name: str
    records_for: Callable[[Sequence[str]], list[BaseModel]] = lambda symbols: []
    error: Exception | None = None
    core: bool = True
    best_effort: bool = False
    category: Category = Category.PRICES
    cadence: Cadence = Cadence.PER_RUN
    asset_types: frozenset[AssetType] = frozenset({AssetType.STOCK})
    record_type: type[BaseModel] = DailyBar
    freshness: timedelta | None = None
    scope: Scope = Scope.SYMBOLS
    canary: tuple[str, ...] = ()
    canary_requires_records: bool = False
    calls: list[list[str]] = field(default_factory=list)

    def fetch(self, symbols: Sequence[str], as_of: datetime) -> list[BaseModel]:
        self.calls.append(list(symbols))
        if self.error is not None:
            raise self.error
        return list(self.records_for(symbols))


def info(symbol: str, exchange: str = "NYSE") -> SymbolInfo:
    return SymbolInfo(symbol=symbol, name=f"{symbol} Inc. Common Stock", exchange=exchange)


def bar(
    symbol: str, day: date, close: float, volume: float = 200_000.0, source: str = "alpaca"
) -> DailyBar:
    return DailyBar(
        symbol=symbol, day=day, open=close, high=close, low=close, close=close,
        volume=volume, source=source,
    )


def history(
    symbol: str,
    days: int,
    close: float = 10.0,
    volume: float = 200_000.0,
    source: str = "alpaca",
    start: date = date(2026, 6, 1),
) -> list[DailyBar]:
    return [bar(symbol, start + timedelta(days=i), close, volume, source) for i in range(days)]


FRESH_START = date(2026, 8, 5)  # 70 daily bars from here end 2026-10-13, fresh for a 2026-10-14 run


def fake_price_collectors(universe: Sequence[str] = ("AAA", "BBB", "CCC")) -> dict[str, FakeCollector]:
    """Universe, primary and fallback price fakes that return fresh 70-day histories."""
    return {
        "nasdaq_symbols": FakeCollector(
            "nasdaq_symbols",
            records_for=lambda _: [info(s) for s in universe],
            record_type=SymbolInfo,
            cadence=Cadence.DAILY,
            scope=Scope.UNIVERSE,
            freshness=timedelta(days=3),
        ),
        "alpaca_bars": FakeCollector(
            "alpaca_bars",
            records_for=lambda syms: [b for s in syms for b in history(s, 70, start=FRESH_START)],
        ),
        "yfinance_bars": FakeCollector(
            "yfinance_bars",
            core=False,
            best_effort=True,
            records_for=lambda syms: [
                b for s in syms for b in history(s, 70, source="yfinance", start=FRESH_START)
            ],
        ),
    }
