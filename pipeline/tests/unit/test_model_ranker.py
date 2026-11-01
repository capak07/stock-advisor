import gzip
import json
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from advisor.model.dataset import load_market
from advisor.model.train import (
    PARAMS,
    RANK_ROUNDS,
    RANK_SETTINGS,
    TrainConfig,
    daily_rank,
    fit_final,
    from_files,
    rank_ic,
    to_files,
    walk_forward,
)
from advisor.models import Market
from model_data import write_market

FAST = TrainConfig(horizons=(5, 63), rounds=20, params={**PARAMS, "min_data_in_leaf": 50, "num_threads": 2})
QUANTILES = ["q10", "q50", "q90"]


@pytest.fixture(scope="module")
def market(tmp_path_factory):
    path = tmp_path_factory.mktemp("ranker")
    write_market(path, Market.TSX, stocks=20, days=1100)
    return load_market(path, Market.TSX)


def test_the_ranking_booster_learns_slowly():
    assert RANK_SETTINGS == {"learning_rate": 0.03, "num_leaves": 15}
    assert RANK_ROUNDS == 400


def test_the_rank_target_is_each_days_percentile_rank_centred_on_zero():
    rows = pd.DataFrame({
        "day": ["d1", "d1", "d1", "d1", "d2", "d3", "d3"],
        "y_5": [0.1, 0.3, 0.2, np.nan, 0.5, 0.2, 0.2],
    }, index=[10, 11, 12, 13, 14, 15, 16])
    out = daily_rank(rows, "y_5")
    assert out.index.equals(rows.index)
    assert out.tolist()[:3] == pytest.approx([-1 / 3, 1 / 3, 0.0])
    assert np.isnan(out[13])
    # a lone coin on an early crypto day is the middle, not the top
    assert out[14] == pytest.approx(0.0)
    assert out[15] == out[16] == pytest.approx(0.0)  # a tie shares the average rank
    assert out.groupby(rows["day"]).mean().tolist() == pytest.approx([0.0, 0.0, 0.0])  # every day averages 0


def test_the_baseline_score_is_its_published_median(market):
    wf = walk_forward(market, FAST)
    pred = wf.predictions
    assert (pred["score"] == pred["q50"]).all()
    for h in FAST.horizons:
        scored = pred[(pred["horizon"] == h) & pred["p"].notna()]
        assert wf.metrics[h]["rank_ic"] == pytest.approx(rank_ic(scored, "q50", "y"))


def test_a_ranker_walk_forward_ranks_and_calibrates_by_its_ranking_booster(market):
    base = walk_forward(market, FAST).predictions
    wf = walk_forward(market, FAST, ranker=True)
    pred = wf.predictions
    assert (pred["score"] == pred["p_raw"]).all()
    assert pred.loc[pred["fold"] > 0, "p"].notna().all()
    pd.testing.assert_frame_equal(pred[QUANTILES], base[QUANTILES])  # the ranges don't change
    for h in FAST.horizons:
        scored = pred[(pred["horizon"] == h) & pred["p"].notna()]
        assert wf.metrics[h]["rank_ic"] == pytest.approx(rank_ic(scored, "score", "y"))


def test_a_rankers_period_never_sees_its_own_targets(market):
    before = walk_forward(market, FAST, ranker=True).predictions
    last_start = before.loc[before["fold"] == before["fold"].max(), "day"].min()
    rows = market.rows.copy()
    rows.loc[rows["day"] >= last_start, "y_5"] = rows.loc[rows["day"] >= last_start, "y_5"].where(
        rows["y_5"].isna(), 5.0
    )
    after = walk_forward(replace(market, rows=rows), FAST, ranker=True).predictions
    last = (before["fold"] == before["fold"].max()) & (before["horizon"] == 5)
    pd.testing.assert_series_equal(before.loc[last, "score"], after.loc[last, "score"])
    pd.testing.assert_series_equal(before.loc[last, "p"], after.loc[last, "p"])


def test_a_ranker_final_model_gives_p_from_its_ranking_booster_and_round_trips(market):
    model = fit_final(market, walk_forward(market, FAST, ranker=True), FAST)
    assert model.p_source == "rank"
    files = to_files(model)
    assert "h5_rank" in files and "h5_beat" not in files
    back = from_files(files)
    assert back.p_source == "rank"
    x = market.rows[market.features].head(20)
    pd.testing.assert_frame_equal(back.predict(x), model.predict(x))


def test_a_model_saved_before_the_ranker_still_gives_p_from_its_beat_booster(market):
    model = fit_final(market, walk_forward(market, FAST), FAST)
    files = to_files(model)
    meta = json.loads(gzip.decompress(files["meta"]).decode())
    meta.pop("p_source", None)
    files["meta"] = gzip.compress(json.dumps(meta).encode())
    back = from_files(files)
    assert back.p_source == "beat"
    x = market.rows[market.features].head(20)
    pd.testing.assert_frame_equal(back.predict(x), model.predict(x))
