"""Hard screener filters (spec §4.3 stage 3): price, dollar volume, and history length.

Plan 3 adds the screener model that ranks survivors down to the ~300-symbol shortlist.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from advisor.models import DailyBar

MIN_PRICE = 1.0
MIN_DOLLAR_VOLUME = 1_000_000.0
ADV_WINDOW = 20
MIN_HISTORY_DAYS = 60


@dataclass(frozen=True)
class ScreenRow:
    symbol: str
    last_close: float
    adv20: float
    history_days: int
    last_day: date

    def passes(self) -> bool:
        return (
            self.last_close >= MIN_PRICE
            and self.adv20 >= MIN_DOLLAR_VOLUME
            and self.history_days >= MIN_HISTORY_DAYS
        )

    def as_features(self) -> dict[str, float | int | str]:
        return {
            "last_close": self.last_close,
            "adv20": self.adv20,
            "history_days": self.history_days,
            "last_day": self.last_day.isoformat(),
        }


def price_stats(symbol: str, bars: Sequence[DailyBar]) -> ScreenRow:
    recent = bars[-ADV_WINDOW:]
    adv = sum(b.close * b.volume for b in recent) / len(recent)
    return ScreenRow(symbol, bars[-1].close, adv, len(bars), bars[-1].day)


def hard_filter(bars_by_symbol: Mapping[str, Sequence[DailyBar]]) -> list[ScreenRow]:
    rows = (price_stats(s, bars) for s, bars in bars_by_symbol.items() if bars)
    return sorted((row for row in rows if row.passes()), key=lambda row: row.symbol)
