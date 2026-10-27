"""Trailing stops: the highest close since purchase less a multiple of the ATR, only ever moving up."""

import math
from collections.abc import Sequence

import pandas as pd

from advisor.model.features import Wide, _wilder, true_range
from advisor.models import DailyBar

TRAIL_ATR = 2.5


def atr_pct(bars: Sequence[DailyBar], n: int = 14) -> float:
    """The last day's ATR as a fraction of its close, computed as the model's atr_14_pct is
    (Wilder smoothing). Used for coins, which have no model features. NaN when there are too
    few bars (fewer than n + 1) for a value."""
    if len(bars) < n + 1:
        return math.nan
    frame = pd.DataFrame(
        {
            "open": [b.open for b in bars],
            "high": [b.high for b in bars],
            "low": [b.low for b in bars],
            "close": [b.close for b in bars],
            "volume": [b.volume for b in bars],
        },
        dtype=float,
    )
    wide = Wide(**{k: frame[[k]].set_axis(["bars"], axis=1) for k in frame.columns})
    value = (_wilder(true_range(wide), n) / wide.close).iloc[-1, 0]
    return float(value)


def trailing_stop(
    closes: Sequence[float],
    last_close: float,
    atr_pct: float,
    previous: float | None,
    floor: float | None,
) -> float | None:
    """The highest close since purchase (the last close if there is none) less 2.5 ATR, but never
    below the previous stop or the original stop (floor). None when there is no ATR and nothing to
    fall back on."""
    candidates = [v for v in (previous, floor) if v is not None]
    if not math.isnan(atr_pct):
        high = max(closes) if closes else last_close
        candidates.append(high - TRAIL_ATR * atr_pct * last_close)
    return max(candidates) if candidates else None
