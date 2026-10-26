"""Risk score, level and suggested max position (spec §6.4)."""

import math

import numpy as np
import pandas as pd

WEIGHTS = {"vol_60": 0.30, "width": 0.20, "disagreement": 0.15, "illiquidity": 0.15,
           "event": 0.10, "size": 0.10}
# (level, score-percentile limit below which it applies, max position in percent)
LEVELS = (("low", 30, 5.0), ("medium", 65, 3.0), ("high", 90, 1.5), ("very_high", 101, 0.5))
SMALL_CAP = 300_000_000
_ORDER = [name for name, _, _ in LEVELS]


def disagreement(technical: float, fundamental: float, sentiment: float) -> float:
    """0 when every available signal points the same way, 1 when they split evenly; NaN
    with fewer than two signals, since one direction cannot disagree with itself."""
    signs = [np.sign(x) for x in (technical, fundamental, sentiment) if not math.isnan(x)]
    if len(signs) < 2:
        return float("nan")
    return 1.0 - abs(signs.count(1.0) - signs.count(-1.0)) / len(signs)


def _level_for(percentile: float) -> int:
    return next(i for i, (_, limit, _) in enumerate(LEVELS) if percentile < limit)


def _at_least(index: int, floor: str) -> int:
    return max(index, _ORDER.index(floor))


def risk_levels(frame: pd.DataFrame) -> pd.DataFrame:
    """Adds risk_score (0-100), risk_level and max_position_pct. Components are percentile
    ranks within the frame; a missing one drops out and the weights renormalise per stock."""
    parts = pd.DataFrame({
        "vol_60": frame["vol_60"],
        "width": frame["width"],
        "disagreement": frame["disagreement"],
        "illiquidity": -frame["log_adv20"],
        "event": frame["event"],
        "size": -frame["log_mcap"],
    }).rank(pct=True, method="average") * 100
    weights = pd.Series(WEIGHTS)[parts.columns]
    available = parts.notna() * weights
    score = (parts.fillna(0) * weights).sum(axis=1) / available.sum(axis=1)
    percentile = score.rank(pct=True, method="average") * 100

    indices = percentile.map(_level_for)
    small = frame["log_mcap"] < math.log(SMALL_CAP)
    sparse = frame["groups_missing_share"] > 0.5
    indices = indices.where(~small, indices.map(lambda i: _at_least(i, "high")))
    indices = indices.where(~sparse, indices.map(lambda i: _at_least(i, "medium")))

    out = frame.copy()
    out["risk_score"] = score
    out["risk_level"] = indices.map(lambda i: LEVELS[i][0])
    out["max_position_pct"] = indices.map(lambda i: LEVELS[i][2])
    return out
