import math

import numpy as np
import pandas as pd
import pytest

from advisor.benchmark.metrics import model_metrics, pinball_loss, policy_metrics, summary
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
