import math

import numpy as np
import pandas as pd
import pytest

from advisor.benchmark.metrics import (
    model_metrics,
    pinball_loss,
    policy_metrics,
    summary,
    top_slice,
)
from advisor.model.train import calibration_error
from advisor.models import Market


def rows(fold, day, ys, q50s, p=np.nan, horizon=5, scores=None):
    n = len(ys)
    q50 = np.asarray(q50s, float)
    return pd.DataFrame({
        "day": pd.Timestamp(day), "symbol": [f"S{i}" for i in range(n)], "sector": "Tech",
        "dollar_volume_20": 2e7, "horizon": horizon, "fold": fold, "y": ys,
        "q10": q50 - 0.1, "q50": q50, "q90": q50 + 0.1, "p_raw": 0.5, "p": p,
        "score": q50 if scores is None else np.asarray(scores, float),
    })


def test_pinball_loss_weights_misses_by_the_quantile():
    assert pinball_loss(np.array([0.2, -0.1]), np.zeros(2), 0.1) == pytest.approx(0.055)
    assert pinball_loss(np.array([0.2, -0.1]), np.zeros(2), 0.9) == pytest.approx(0.095)


def test_each_outer_fold_and_the_pool_are_scored_and_fold_0_has_no_calibration():
    pred = pd.concat([
        rows(0, "2024-01-02", [.01, .02, .03], [.01, .02, .03]),
        rows(0, "2024-01-16", [.03, .01, .02], [.03, .01, .02]),
        rows(1, "2024-02-01", [.01, .02, .03], [.03, .02, .01], p=[.4, .5, .6]),
        rows(1, "2024-02-15", [.01, .02, .03], [.03, .02, .01], p=[.4, .5, .6]),
    ], ignore_index=True)
    m = model_metrics(pred)
    assert set(m) == {"0", "1", "pooled"}
    assert m["0"][5]["rank_ic"] == pytest.approx(1.0) and m["1"][5]["rank_ic"] == pytest.approx(-1.0)
    assert m["pooled"][5]["rank_ic"] == pytest.approx(0.0)
    assert math.isnan(m["0"][5]["calibration_pts"])
    fold1 = pred[pred["fold"] == 1]
    assert m["pooled"][5]["calibration_pts"] == pytest.approx(calibration_error(fold1["p"], fold1["y"] > 0))
    assert m["1"][5]["rows"] == 6 and m["pooled"][5]["coverage_10_90"] == 1.0
    assert summary(m, (5,))["1"] == {"rank_ic": pytest.approx(-1.0), "pinball": m["1"][5]["pinball"]}


def test_rank_ic_is_taken_on_the_variants_ranking_score():
    # a ranker variant ranks by its ranking booster's score, not by q50 (spec §8)
    pred = rows(1, "2024-02-01", [.01, .02, .03], [.03, .02, .01], scores=[.1, .2, .3])
    assert model_metrics(pred)["1"][5]["rank_ic"] == pytest.approx(1.0)


def test_combined_pinball_is_nan_if_any_quantile_cannot_be_scored():
    pred = rows(1, "2024-02-01", [.01, .02, .03], [.01, .02, .03], p=[.4, .5, .6])
    pred.loc[0, "q10"] = np.nan
    assert math.isnan(model_metrics(pred)["1"][5]["pinball"])


def test_the_default_policy_is_scored_per_calibrated_fold():
    pred = pd.concat([
        rows(0, "2024-02-01", [.03], [.05]),  # no p: never picked
        rows(1, "2024-03-01", [.03], [.05], p=.7).assign(symbol="S1"),
        rows(1, "2024-04-01", [.04], [.05], p=.7).assign(symbol="S2"),
        rows(2, "2024-05-01", [-.02], [.05], p=.7).assign(symbol="S3"),
    ], ignore_index=True)
    m = policy_metrics(pred, Market.TSX, 1.5)
    assert set(m) == {"1", "2", "pooled"}
    assert m["1"]["trades"] == 2 and m["1"]["trades_per_month"] == pytest.approx(1.0)
    assert m["2"]["hit_rate_net"] == 0.0 and m["pooled"]["trades"] == 3
    assert m["pooled"]["claimed_gap_pts"] == pytest.approx(abs(0.7 - 2 / 3) * 100)


def _slice_frame(scores, ys, day="2026-01-05", horizon=21, fold=1):
    n = len(scores)
    return pd.DataFrame({
        "day": pd.Timestamp(day), "symbol": [f"S{i:03d}" for i in range(n)], "horizon": horizon, "fold": fold,
        "p_raw": scores, "y": ys, "dollar_volume_20": 5e7,
    })


def test_the_top_slice_is_the_highest_scores_against_the_whole_day():
    frame = _slice_frame(list(range(40)), [0.0] * 38 + [0.10, 0.20])  # 5% of 40: the two best scores
    leaf = top_slice(frame, Market.TSX, 0.0)["pooled"][21]
    assert leaf["days"] == 1
    assert leaf["top_excess"] == pytest.approx(0.15 - 0.30 / 40)
    assert leaf["top_net"] == pytest.approx(0.15 - 0.001)  # the spread at this volume; no currency fee on TSX
    assert leaf["bottom_excess"] == pytest.approx(0.0 - 0.30 / 40)


def test_the_top_slice_follows_the_raw_score_not_the_walk_forward_score():
    # a model without a ranker has score = q50 in its walk-forward frame; picks rank by p_raw
    frame = _slice_frame(list(range(40)), [0.0] * 38 + [0.10, 0.20]).assign(score=list(range(40, 0, -1)))
    assert top_slice(frame, Market.TSX, 0.0)["pooled"][21]["top_excess"] == pytest.approx(0.15 - 0.30 / 40)


def test_a_flagged_jump_never_takes_a_place_in_the_top_slice():
    frame = _slice_frame(list(range(41)), [0.0] * 38 + [0.10, 0.20, 0.90]).assign(jump_5d=[0.0] * 40 + [1.0])
    leaf = top_slice(frame, Market.TSX, 0.0)["pooled"][21]
    assert leaf["top_excess"] == pytest.approx(0.15 - 0.30 / 40)  # S040's jump row is out of the day too


def test_a_us_top_slice_pays_the_currency_fee_both_ways():
    frame = _slice_frame(list(range(40)), [0.0] * 38 + [0.10, 0.20])
    assert top_slice(frame, Market.US, 1.5)["pooled"][21]["top_net"] == pytest.approx(0.15 - 0.001 - 0.03)


def test_a_thin_day_and_unknown_outcomes_are_skipped():
    thin = _slice_frame(list(range(19)), [0.01] * 19)
    unknown = _slice_frame(list(range(40)), [np.nan] * 40, day="2026-01-19")
    unscored = _slice_frame([np.nan] * 40, [0.01] * 40, day="2026-02-02")
    assert top_slice(pd.concat([thin, unknown, unscored]), Market.TSX, 0.0) == {}


def test_equal_scores_break_ties_by_symbol():
    frame = _slice_frame([1.0] * 40, [0.40, 0.20] + [0.0] * 38)  # S000 and S001 take the top
    leaf = top_slice(frame, Market.TSX, 0.0)["pooled"][21]
    assert leaf["top_excess"] == pytest.approx(0.30 - 0.60 / 40)
    assert leaf["bottom_excess"] == pytest.approx(0.0 - 0.60 / 40)  # S039 and S038, not the top again


def test_each_fold_and_horizon_gets_its_own_block_and_days_average():
    up = _slice_frame(list(range(40)), [0.0] * 38 + [0.10, 0.10], fold=0)
    flat = _slice_frame(list(range(40)), [0.0] * 40, day="2026-03-02", fold=1)
    other = _slice_frame(list(range(40)), [0.0] * 40, day="2026-03-02", horizon=63, fold=1)
    out = top_slice(pd.concat([up, flat, other]), Market.TSX, 0.0)
    assert set(out) == {"0", "1", "pooled"} and set(out["pooled"]) == {21, 63} and set(out["0"]) == {21}
    assert out["pooled"][21]["days"] == 2
    assert out["pooled"][21]["top_excess"] == pytest.approx((0.10 - 0.20 / 40) / 2)
