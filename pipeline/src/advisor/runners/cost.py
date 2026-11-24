"""The estimated bid-ask spread and what it costs in R."""

import math

import numpy as np

from advisor.runners.rule import Series

FLOOR, CAP = 1.0, 10.0  # percent
SPREAD_SESSIONS = 20  # the sessions before the signal that measure the spread

_K = 3 - 2 * math.sqrt(2)


def two_day_spread(h1: float, l1: float, h2: float, l2: float) -> float:
    """The Corwin-Schultz spread from two days' highs and lows, in percent. Never negative."""
    beta = math.log(h1 / l1) ** 2 + math.log(h2 / l2) ** 2
    gamma = math.log(max(h1, h2) / min(l1, l2)) ** 2
    alpha = (math.sqrt(2 * beta) - math.sqrt(beta)) / _K - math.sqrt(gamma / _K)
    return max(0.0, 2 * (math.exp(alpha) - 1) / (1 + math.exp(alpha))) * 100


def spread_pct(s: Series, i: int) -> float:
    """The median two-day spread over the sessions before i, between FLOOR and CAP.

    Day i itself is left out: one huge range swamps the estimate.
    """
    start = max(0, i - SPREAD_SESSIONS)
    spreads = [
        two_day_spread(float(s.high[j - 1]), float(s.low[j - 1]), float(s.high[j]), float(s.low[j]))
        for j in range(start + 1, i)
    ]
    if not spreads:
        return FLOOR
    return min(CAP, max(FLOOR, float(np.median(spreads))))


def cost_r(spread: float, entry: float, stop: float) -> float:
    """The spread's cost as a share of the risk per share."""
    return spread * entry / (entry - stop) / 100
