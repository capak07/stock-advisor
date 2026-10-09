"""Test doubles and builders shared by unit and integration tests."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from pydantic import BaseModel

from advisor.collectors.base import Cadence, Category
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
