"""The ignition rule: a cheap US stock that jumps on a huge volume day.

A signal on day D uses only bars dated on or before D. The trade, if any, starts at D+1's open.
"""

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, fields
from datetime import date
from typing import Any, NamedTuple

import numpy as np

from advisor.models import DailyBar

SPLIT_GAP = 2.0  # an open at least twice the last close
SPLIT_VOLUME_SESSIONS = 50  # the volume a split day is measured against


class Bar(NamedTuple):
    day: date
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class Rule:
    # The ignition test reads the first eight fields only.
    volume_x: float = 10.0
    min_change: float = 0.20
    min_close_pos: float | None = 0.50  # None = no close-position test
    min_dollar_volume: float = 2_000_000.0
    price_min: float = 0.50
    price_max: float = 5.00
    quiet_sessions: int = 20
    history_sessions: int = 50
    # The trade plan.
    gap_skip: float | None = None  # 0.15 = skip an open more than 15% above D's close
    stop_floor: float | None = 0.25  # None = D's low alone
    target_r: float = 2.0
    hold_sessions: int = 10

    def settings(self) -> dict[str, float | int | None]:
        return asdict(self)

    @classmethod
    def from_settings(cls, settings: Mapping[str, Any]) -> "Rule":
        """Unknown keys are ignored and missing keys take the starting value."""
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in settings.items() if k in known})


STARTING = Rule()


@dataclass(frozen=True)
class Series:
    days: Sequence[date]
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    raw_close: np.ndarray  # the price as it traded that day; equals close in the live run

    def bars(self, start: int, stop: int | None = None) -> list[Bar]:
        stop = len(self.days) if stop is None else stop
        return [
            Bar(self.days[i], float(self.open[i]), float(self.high[i]), float(self.low[i]),
                float(self.close[i]), float(self.volume[i]))
            for i in range(start, stop)
        ]


def series_of(bars: Sequence[DailyBar]) -> Series:
    ordered = sorted(bars, key=lambda b: b.day)

    def column(name: str) -> np.ndarray:
        return np.array([getattr(b, name) for b in ordered], dtype=float)

    close = column("close")
    return Series(
        days=tuple(b.day for b in ordered), open=column("open"), high=column("high"),
        low=column("low"), close=close, volume=column("volume"), raw_close=close.copy(),
    )


@dataclass(frozen=True)
class Ignitions:
    signal: np.ndarray  # bool per session
    split_suspect: np.ndarray  # bool per session: met the rule but skipped as a suspected unrecorded split


def _close_pos(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> np.ndarray:
    """Where the close sits in the day's range: 0 at the low, 1 at the high, 1 when flat."""
    span = high - low
    return np.divide(close - low, span, out=np.ones_like(span), where=span > 0)


def _sums(x: np.ndarray) -> np.ndarray:
    """Running sums with a leading zero: x[a:b].sum() == sums[b] - sums[a]."""
    return np.concatenate(([0.0], np.cumsum(x, dtype=float)))


def split_days(s: Series) -> np.ndarray:
    """Sessions that open at twice the last close on less volume than usual.

    A reverse split shrinks the share count; a real spike multiplies volume.
    """
    n = len(s.days)
    out = np.zeros(n, dtype=bool)
    if n < 2:
        return out
    t = np.arange(1, n)
    start = np.maximum(0, t - SPLIT_VOLUME_SESSIONS)
    vol = _sums(s.volume)
    usual = (vol[t] - vol[start]) / (t - start)
    gapped = s.open[1:] >= SPLIT_GAP * s.close[:-1]
    out[1:] = gapped & (s.volume[1:] < usual)
    return out


def ignitions(s: Series, rule: Rule) -> Ignitions:
    n = len(s.days)
    h = rule.history_sessions
    if n <= h:
        none = np.zeros(n, dtype=bool)
        return Ignitions(signal=none, split_suspect=none.copy())

    i = np.arange(n)
    vol = _sums(s.volume)
    avg = np.zeros(n)
    avg[h:] = (vol[h:n] - vol[: n - h]) / h  # mean of volume[i-h:i]
    change = np.full(n, -np.inf)
    prev = s.close[:-1]
    change[1:] = np.divide(s.close[1:], prev, out=np.full(n - 1, -np.inf), where=prev > 0) - 1

    candidate = (
        (i >= h)
        & (avg > 0)
        & (s.volume >= rule.volume_x * avg)
        & (change >= rule.min_change)
        & (s.close * s.volume >= rule.min_dollar_volume)
        & (s.raw_close >= rule.price_min)
        & (s.raw_close <= rule.price_max)
    )
    if rule.min_close_pos is not None:
        candidate &= _close_pos(s.high, s.low, s.close) >= rule.min_close_pos

    splits = _sums(split_days(s))
    history_start = np.maximum(0, i - h)
    suspect = candidate & (splits[i] - splits[history_start] > 0)  # a split day in [i-h, i-1]

    earlier = _sums(candidate)
    quiet_start = np.maximum(0, i - rule.quiet_sessions)
    quiet = earlier[i] - earlier[quiet_start] == 0  # no candidate in [i-quiet, i-1]
    return Ignitions(signal=candidate & ~suspect & quiet, split_suspect=suspect)


def stats_at(s: Series, i: int, rule: Rule) -> dict[str, float]:
    """The numbers behind a signal on session i."""
    avg = float(s.volume[i - rule.history_sessions : i].mean())
    close, volume = float(s.close[i]), float(s.volume[i])
    pos = _close_pos(s.high[i : i + 1], s.low[i : i + 1], s.close[i : i + 1])
    return {
        "change_pct": (close / float(s.close[i - 1]) - 1) * 100,
        "volume_x": volume / avg,
        "dollar_volume": close * volume,
        "close_pos": float(pos[0]),
    }
