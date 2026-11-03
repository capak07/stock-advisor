from dataclasses import replace

import numpy as np
import pandas as pd

from advisor.benchmark.folds import inner_folds, inner_walk_forward
from advisor.model.dataset import load_market
from advisor.model.train import PARAMS, Fold, TrainConfig, make_folds
from advisor.model.variants import BASELINE, run_variant
from advisor.models import Market
from model_data import write_market

FAST = TrainConfig(horizons=(5, 63), rounds=40, params={**PARAMS, "min_data_in_leaf": 50, "num_threads": 2})
DAYS = pd.bdate_range("2017-01-02", "2024-12-31")


def test_inner_folds_split_the_outer_training_span_after_a_year():
    outer = Fold(pd.Timestamp("2019-01-02"), pd.Timestamp("2020-06-01"))
    inner = inner_folds(DAYS, outer)
    assert len(inner) == 3
    assert inner[0].start == pd.Timestamp("2018-01-02") and inner[-1].end == outer.start
    assert all(a.end == b.start for a, b in zip(inner, inner[1:], strict=False))
    lengths = {(f.end - f.start).days for f in inner}
    assert max(lengths) - min(lengths) <= 1


def test_an_outer_fold_too_early_for_a_year_of_training_has_no_inner_folds():
    assert inner_folds(DAYS, Fold(pd.Timestamp("2017-10-02"), pd.Timestamp("2018-06-01"))) == []


def test_inner_predictions_never_see_the_outer_period(tmp_path):
    write_market(tmp_path, Market.TSX, stocks=20, days=1100)
    data = load_market(tmp_path, Market.TSX)
    outer = make_folds(pd.DatetimeIndex(data.rows["day"].unique()), TrainConfig())[2]
    before = inner_walk_forward(data, BASELINE, FAST, outer).predictions
    rows, rng = data.rows.copy(), np.random.default_rng(0)
    start = data.calendar.searchsorted(outer.start)
    position = data.calendar.searchsorted(pd.DatetimeIndex(rows["day"]))
    for h in FAST.horizons:  # every outcome not yet known when the outer period begins
        late = position + h >= start
        rows.loc[late, f"y_{h}"] = rng.normal(size=late.sum())
    later = rows["day"] >= outer.start
    rows.loc[later, data.features] = rng.normal(size=(later.sum(), len(data.features)))
    after = inner_walk_forward(replace(data, rows=rows), BASELINE, FAST, outer).predictions
    assert not before.empty and (before["day"] < outer.start).all()
    pd.testing.assert_frame_equal(before, after)


def test_an_outer_fold_is_predicted_without_its_own_outcomes(tmp_path):
    write_market(tmp_path, Market.TSX, stocks=20, days=1100)
    data = load_market(tmp_path, Market.TSX)
    wf, k = run_variant(data, BASELINE, FAST), 2
    fold = wf.folds[k]
    rows = data.rows.copy()
    inside = (rows["day"] >= fold.start) & (rows["day"] < fold.end)
    for h in FAST.horizons:
        rows.loc[inside, f"y_{h}"] = -rows.loc[inside, f"y_{h}"]
    again = run_variant(replace(data, rows=rows), BASELINE, FAST)
    cols = ["day", "symbol", "horizon", "fold", "q10", "q50", "q90", "p_raw"]

    def upto(p: pd.DataFrame) -> pd.DataFrame:
        return p.loc[p["fold"] <= k, cols].reset_index(drop=True)

    def p_known_without_the_fold(p: pd.DataFrame) -> pd.Series:
        """P of the earlier folds, and of the fold's first month: the later months learn from the
        outcomes that ended earlier in their own fold (spec §10), so flipping the fold moves them."""
        first = p.groupby(["horizon", "fold"])["day"].transform("min")
        month = p["day"].dt.to_period("M") == first.dt.to_period("M")
        return p.loc[(p["fold"] < k) | ((p["fold"] == k) & month), "p"].reset_index(drop=True)

    assert (wf.predictions["fold"] == k).any()
    pd.testing.assert_frame_equal(upto(wf.predictions), upto(again.predictions))
    pd.testing.assert_series_equal(
        p_known_without_the_fold(wf.predictions), p_known_without_the_fold(again.predictions)
    )
