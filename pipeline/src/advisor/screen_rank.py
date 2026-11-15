"""Low model rank (spec 2026-11-15): a stock in the bottom tenth of a run's screener scores.

The bottom of the screener's ranking trailed the average US stock reliably in testing; the top did
not beat it, so only the bottom is flagged. TSX's bottom tenth did not trail reliably: US only.
"""

from collections.abc import Mapping
from dataclasses import dataclass

import pandas as pd

from advisor.models import Market

LOW_SHARE = 0.10
MIN_SCORED = 100  # fewer scored stocks make a "bottom tenth" of a handful
MARKETS = frozenset({Market.US})


@dataclass(frozen=True)
class ScreenRank:
    symbol: str
    pct: float  # (0, 1]: the share of scored stocks at or below this score
    low: bool


def screen_ranks(scores: Mapping[str, float]) -> list[ScreenRank]:
    """Each scored symbol's percentile and flag; empty when too few were scored. Ties share a rank."""
    if len(scores) < MIN_SCORED:
        return []
    pct = pd.Series(scores, dtype=float).rank(method="average", pct=True)
    return [ScreenRank(str(s), float(p), bool(p <= LOW_SHARE)) for s, p in sorted(pct.items())]
