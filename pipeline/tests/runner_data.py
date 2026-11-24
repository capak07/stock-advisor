"""Daily bars for the Runners tests: a quiet stock, then AKAN's real ignition day and the days after."""

from datetime import date, timedelta

from advisor.models import DailyBar
from advisor.runners.rule import Bar

LAST_QUIET_DAY = date(2026, 11, 12)  # a Thursday: the next weekday is AKAN's ignition day
FLAT_VOLUME = 100_000.0
SOURCE = "yfinance"

# AKAN's real bar on Fri 2026-11-13: it doubled on 892x its usual volume.
AKAN = dict(open=0.737, high=1.70, low=0.726, close=1.36, volume=89_211_000.0)

# AKAN's real bars on the three sessions after its ignition day.
AKAN_AFTER = [
    Bar(date(2026, 11, 16), 1.92, 2.38, 1.70, 2.21, 99_663_300.0),
    Bar(date(2026, 11, 17), 1.91, 2.09, 1.63, 2.05, 21_672_000.0),
    Bar(date(2026, 11, 18), 2.40, 4.67, 2.32, 4.03, 108_894_400.0),
]


def _next_weekday(day: date) -> date:
    day += timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


def weekdays(n: int) -> list[date]:
    """n consecutive weekdays ending 2026-11-12."""
    days = [LAST_QUIET_DAY]
    while len(days) < n:
        day = days[-1] - timedelta(days=1)
        while day.weekday() >= 5:
            day -= timedelta(days=1)
        days.append(day)
    return days[:n][::-1]


def quiet(
    n: int = 60, price: float = 0.70, volume: float = FLAT_VOLUME, symbol: str = "AKAN"
) -> list[DailyBar]:
    """n flat bars (open = high = low = close = price) on weekdays ending 2026-11-12."""
    return [
        DailyBar(symbol=symbol, day=d, open=price, high=price, low=price, close=price,
                 volume=volume, source=SOURCE)
        for d in weekdays(n)
    ]


def then(bars: list[DailyBar], **bar: float) -> list[DailyBar]:
    """The same bars plus one on the next weekday."""
    last = bars[-1]
    return [*bars, DailyBar(symbol=last.symbol, day=_next_weekday(last.day), source=SOURCE, **bar)]


def akan() -> list[DailyBar]:
    """60 quiet sessions at $0.672, then AKAN's ignition day."""
    return then(quiet(price=0.672), **AKAN)


def daily(symbol: str, bar: Bar) -> DailyBar:
    return DailyBar(symbol=symbol, day=bar.day, open=bar.open, high=bar.high, low=bar.low,
                    close=bar.close, volume=bar.volume, source=SOURCE)


def more_flat_days(bars: list[DailyBar], n: int) -> list[DailyBar]:
    """n more weekdays at the last close on 100,000 shares."""
    out = list(bars)
    for _ in range(n):
        price = out[-1].close
        out = then(out, open=price, high=price, low=price, close=price, volume=FLAT_VOLUME)
    return out
