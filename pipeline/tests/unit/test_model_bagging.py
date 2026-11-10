import gzip
import json

import lightgbm as lgb
import numpy as np
import pytest

from advisor.model.dataset import load_market
from advisor.model.features import EXTRA_FEATURES
from advisor.model.train import (
    BAG_SEEDS,
    PARAMS,
    Bag,
    TrainConfig,
    _fit_horizon,
    fit_final,
    from_files,
    to_files,
    walk_forward,
)
from advisor.models import Market
from model_data import write_market

FAST = TrainConfig(horizons=(5, 63), rounds=20, params={**PARAMS, "min_data_in_leaf": 50, "num_threads": 2})


@pytest.fixture(scope="module")
def market(tmp_path_factory):
    path = tmp_path_factory.mktemp("bagging")
    write_market(path, Market.TSX, stocks=20, days=1100)
    return load_market(path, Market.TSX)


@pytest.fixture(scope="module")
def wf(market):
    return walk_forward(market, FAST)


@pytest.fixture(scope="module")
def bagged(market, wf):
    return fit_final(market, wf, FAST, bag=True)


@pytest.fixture(scope="module")
def baseline(market, wf):
    return fit_final(market, wf, FAST)


def _x(market, model, n=50):
    return market.rows[model.features].head(n)


def test_a_bag_predicts_the_mean_of_its_seeds(market):
    train = market.rows[market.rows["y_5"].notna()]
    x = train[market.features].head(300)
    parts = _fit_horizon(train[market.features], train["y_5"], FAST, seeds=BAG_SEEDS)
    assert BAG_SEEDS == (7, 8, 9)
    for part in ("q10", "q50", "q90", "beat"):
        bag = parts[part]
        assert isinstance(bag, Bag)
        assert len(bag.boosters) == 3
        each = [b.predict(x) for b in bag.boosters]
        np.testing.assert_allclose(bag.predict(x), np.mean(each, axis=0))
    each = [b.predict(x) for b in parts["q50"].boosters]
    assert not (np.array_equal(each[0], each[1]) and np.array_equal(each[1], each[2]))


def test_the_baseline_trains_one_booster_per_part(market):
    train = market.rows[market.rows["y_5"].notna()]
    parts = _fit_horizon(train[market.features], train["y_5"], FAST)
    assert all(isinstance(b, lgb.Booster) for b in parts.values())


def test_extra_features_join_the_feature_list_only_when_asked(market, wf, baseline):
    assert "amihud_20" not in baseline.features
    full = fit_final(market, wf, FAST, extra_features=EXTRA_FEATURES)  # what an extras config trains on
    assert full.features == list(market.features) + EXTRA_FEATURES
    assert full.features[-3:] == ["sector_mom_12_1", "sector_dist_52w_high", "amihud_20"]
    with pytest.raises(ValueError, match="not_a_feature"):
        fit_final(market, wf, FAST, extra_features=("amihud_20", "not_a_feature"))
    with pytest.raises(ValueError, match="not_a_feature"):
        walk_forward(market, FAST, extra_features=("not_a_feature",))


def test_a_bagged_model_round_trips_with_three_seeds_per_part(market, bagged):
    files = to_files(bagged)
    assert {"h5_q50", "h5_q50_s1", "h5_q50_s2"} <= set(files)
    assert json.loads(gzip.decompress(files["meta"]))["bag"] == 3
    loaded = from_files(files)
    x = _x(market, bagged)
    np.testing.assert_allclose(loaded.predict(x).to_numpy(), bagged.predict(x).to_numpy())


def test_a_model_saved_before_bagging_loads_with_one_booster_per_part(market, baseline):
    files = to_files(baseline)
    assert "h5_q50_s1" not in files
    assert "bag" not in json.loads(gzip.decompress(files["meta"]))
    loaded = from_files(files)
    assert all(isinstance(b, lgb.Booster) for b in loaded.boosters[5].values())
    x = _x(market, baseline)
    np.testing.assert_allclose(loaded.predict(x).to_numpy(), baseline.predict(x).to_numpy())


def test_a_bagged_explanation_and_importance_average_the_seeds(market, bagged):
    x = _x(market, bagged, 1)
    seeds = bagged.boosters[5]["q50"].boosters
    mean = np.mean([b.predict(x[bagged.features], pred_contrib=True) for b in seeds], axis=0)[0, :-1]
    top = [bagged.features[i] for i in np.argsort(-np.abs(mean), kind="stable")[:3]]
    got = bagged.contributions(x, 5)[x.index[0]]
    assert [c["feature"] for c in got] == top
    gain = bagged.boosters[5]["q50"].feature_importance("gain")
    np.testing.assert_allclose(gain, np.mean([b.feature_importance("gain") for b in seeds], axis=0))
