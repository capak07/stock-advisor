"""Inner walk-forward splits, for tuning inside one outer fold's training span.

Anything tuned for an outer fold (a range scale, policy values) is chosen on these splits only.
They end where the outer fold begins, and score only outcomes known by then, so the outer fold's
report stays untouched by the tuning.
"""

import pandas as pd

from advisor.model.dataset import MarketData
from advisor.model.train import Fold, TrainConfig, WalkForward
from advisor.model.variants import ModelConfig, run_variant

INNER_SPLITS = 3
INNER_MIN_TRAIN_YEARS = 1.0


def inner_folds(
    days: pd.DatetimeIndex,
    outer: Fold,
    splits: int = INNER_SPLITS,
    min_train_years: float = INNER_MIN_TRAIN_YEARS,
) -> list[Fold]:
    """Equal test periods after `min_train_years`, the last ending where `outer` begins."""
    first = days.min() + pd.DateOffset(months=round(min_train_years * 12))
    if first >= outer.start:
        return []
    edges = pd.date_range(first, outer.start, periods=splits + 1)
    return [Fold(a, b) for a, b in zip(edges[:-1], edges[1:], strict=True)]


def inner_walk_forward(data: MarketData, config: ModelConfig, train_config: TrainConfig, outer: Fold) -> WalkForward:
    """The variant's predictions on the inner splits of `outer`; empty when there are none."""
    folds = inner_folds(pd.DatetimeIndex(data.rows["day"].unique()), outer)
    return run_variant(data, config, train_config, folds=folds, known_before=outer.start)
