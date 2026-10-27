"""A market's model and forecasts within one run: what the run's model stages hand stage 8.

Kept apart from `advisor.run` so `advisor.recommend.stage` can use them without an import cycle.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import pandas as pd

from advisor.markets import MARKETS
from advisor.model.predict import ActiveModel
from advisor.models import ET, DailyBar, Market, PredictionRow, RunKind

PARTIAL_KINDS = frozenset({RunKind.PRE_CLOSE, RunKind.EARLY_CLOSE})  # runs during a session


@dataclass(frozen=True)
class MarketModel:
    """A market's active model, with the sector labels its relative-strength features compare by.

    `metrics` are the stored model's, which hold its backtest gate (`picks_enabled`, `picks_reason`).
    """

    active: ActiveModel
    sectors: pd.DataFrame
    metrics: Mapping[str, Any] = field(default_factory=dict)


def model_failure(exc: Exception) -> dict:
    return {"failed": f"{type(exc).__name__}: {exc}"[:200]}


def feature_day(
    market: Market, bars: Mapping[str, Sequence[DailyBar]], kind: RunKind, now_utc: datetime
) -> tuple[pd.Timestamp, bool]:
    """The market's last session (its benchmark's last bar), and whether that bar is still partial."""
    # On a 13:00 US early close the 15:15 TSX pre-close run calls a complete US bar partial: conservative.
    benchmark = MARKETS[market].benchmark
    if not bars.get(benchmark):
        raise ValueError(f"no {benchmark} bars")
    day = bars[benchmark][-1].day
    return pd.Timestamp(day), kind in PARTIAL_KINDS and day == now_utc.astimezone(ET).date()


@dataclass(frozen=True)
class Forecast:
    """A market's stage-7 output that stage 8 recommends from."""

    features: pd.DataFrame  # one row per priced symbol, forecast or not (`eligible` says which)
    rows: list[PredictionRow]
