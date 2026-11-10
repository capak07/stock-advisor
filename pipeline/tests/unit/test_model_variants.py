import pandas as pd
import pytest

from advisor.model.dataset import load_market
from advisor.model.features import EXTRA_FEATURES
from advisor.model.train import PARAMS, TrainConfig, make_folds, walk_forward
from advisor.model.variants import BASELINE, ModelConfig, run_variant, unbuilt
from advisor.models import Market
from advisor.policy import Policy
from model_data import write_market

FAST = TrainConfig(horizons=(5, 63), rounds=40, params={**PARAMS, "min_data_in_leaf": 50, "num_threads": 2})


def test_configs_name_themselves_and_round_trip():
    assert BASELINE.name == "baseline"
    assert ModelConfig(factors=True, garch=True).name == "factors+garch"
    assert ModelConfig(policy={"p_buy": 0.6}).name == "baseline+policy"
    assert ModelConfig(ranker=True).name == "ranker"
    assert ModelConfig(factors=True, ranker=True).name == "factors+ranker"
    assert ModelConfig(ranker=True, extras=True, bagged=True).name == "ranker+extras+bagged"
    assert ModelConfig(extras=True).name == "extras"
    assert BASELINE.to_json() == {
        "version": 4, "factors": False, "garch": False, "ranker": False, "extras": False, "bagged": False,
        "earnings": False, "policy": None,
    }
    assert ModelConfig(ranker=True, earnings=True).name == "ranker+earnings"
    assert ModelConfig(ranker=True, extras=True, earnings=True, bagged=True).name == "ranker+extras+earnings+bagged"
    earn = ModelConfig(ranker=True, earnings=True)
    assert ModelConfig.from_json(earn.to_json()) == earn
    full = ModelConfig(ranker=True, extras=True, bagged=True)
    assert ModelConfig.from_json(full.to_json()) == full
    assert ModelConfig.from_json(ModelConfig(ranker=True).to_json()) == ModelConfig(ranker=True)
    assert ModelConfig.from_json(BASELINE.to_json()) == BASELINE


@pytest.mark.parametrize("stored, match", [
    ({"version": 5, "factors": False, "garch": False, "ranker": False, "extras": False, "bagged": False,
      "earnings": False, "policy": None}, "version"),
    ({"version": 4, "factors": False, "garch": False, "ranker": False, "extras": False, "bagged": False,
      "policy": None}, "earnings"),
    ({"version": 3, "factors": False, "garch": False, "ranker": False, "extras": False, "policy": None}, "bagged"),
    ({"version": 3, "factors": False, "garch": False, "ranker": False, "extras": False, "bagged": False,
      "policy": None, "extra": 1}, "extra"),
    ({"version": 2, "factors": False, "garch": False, "policy": None}, "ranker"),
    ({"version": 1, "factors": False, "garch": False, "ranker": True, "policy": None}, "ranker"),
    ({"version": 1, "factors": False, "garch": False, "policy": None, "extra": 1}, "extra"),
    ([], "mapping"),
])
def test_a_stored_config_this_code_cannot_run_is_refused(stored, match):
    with pytest.raises(ValueError, match=match):
        ModelConfig.from_json(stored)


def test_a_version_1_config_loads_with_the_ranker_off():
    # every config accepted before Plan 6f was stored as version 1
    stored = {"version": 1, "factors": True, "garch": False, "policy": None}
    assert ModelConfig.from_json(stored) == ModelConfig(factors=True)


def test_a_version_2_config_loads_with_extras_and_bagging_off():
    stored = {"version": 2, "factors": False, "garch": False, "ranker": True, "policy": None}
    assert ModelConfig.from_json(stored) == ModelConfig(ranker=True)


def test_a_config_carries_a_policy_through_json():
    policy = Policy(0.60, 0.40, 2.0, 3.0, 2.5, "ratio", (21, 63, 126))
    config = ModelConfig(policy=policy)
    assert config.name == "baseline+policy"
    assert ModelConfig.from_json(config.to_json()) == config


def test_a_stored_policy_missing_keys_is_refused():
    with pytest.raises(ValueError):
        ModelConfig.from_json(
            {"version": 1, "factors": False, "garch": False, "policy": {"p_buy": 0.5}}
        )


def test_a_factors_config_can_be_stored_and_run():
    config = ModelConfig(factors=True)
    assert unbuilt(config) is None
    assert ModelConfig.from_json(config.to_json()) == config


def test_a_garch_variant_needs_the_daily_returns(tmp_path):
    write_market(tmp_path, Market.TSX, stocks=20, days=1100)
    with pytest.raises(ValueError, match="with_garch=True"):
        run_variant(load_market(tmp_path, Market.TSX), ModelConfig(garch=True), FAST)


def test_the_baseline_runs_todays_walk_forward_unchanged(tmp_path):
    write_market(tmp_path, Market.TSX, stocks=20, days=1100)
    data = load_market(tmp_path, Market.TSX)
    pd.testing.assert_frame_equal(run_variant(data, BASELINE, FAST).predictions, walk_forward(data, FAST).predictions)


def test_a_ranker_config_runs_the_ranking_walk_forward(tmp_path):
    write_market(tmp_path, Market.TSX, stocks=20, days=1100)
    data = load_market(tmp_path, Market.TSX)
    pd.testing.assert_frame_equal(
        run_variant(data, ModelConfig(ranker=True), FAST).predictions,
        walk_forward(data, FAST, ranker=True).predictions,
    )


def test_an_extras_config_trains_on_the_extra_features(tmp_path):
    write_market(tmp_path, Market.TSX, stocks=20, days=1100)
    data = load_market(tmp_path, Market.TSX)
    pd.testing.assert_frame_equal(
        run_variant(data, ModelConfig(extras=True), FAST).predictions,
        walk_forward(data, FAST, extra_features=EXTRA_FEATURES).predictions,
    )


def test_walk_forward_scores_only_targets_known_before_a_cutoff(tmp_path):
    write_market(tmp_path, Market.TSX, stocks=20, days=1100)
    data = load_market(tmp_path, Market.TSX)
    folds = make_folds(pd.DatetimeIndex(data.rows["day"].unique()), TrainConfig())
    cutoff = folds[2].start
    pred = walk_forward(data, FAST, folds=folds[:2], known_before=cutoff).predictions
    assert not pred.empty
    position = data.calendar.searchsorted(pd.DatetimeIndex(pred["day"]))
    assert (position + pred["horizon"].to_numpy() < data.calendar.searchsorted(cutoff)).all()


def test_a_version_3_config_loads_with_earnings_off():
    stored = {"version": 3, "factors": False, "garch": False, "ranker": True, "extras": True, "bagged": True,
              "policy": None}
    assert ModelConfig.from_json(stored) == ModelConfig(ranker=True, extras=True, bagged=True)


def test_extras_and_earnings_configs_each_train_on_only_their_own_columns(tmp_path):
    from advisor.model.earnings import EARNINGS_FEATURES
    from advisor.model.features import EXTRA_FEATURES
    from advisor.model.variants import extra_features

    write_market(tmp_path, Market.US, stocks=2, days=400)
    data = load_market(tmp_path, Market.US)
    assert extra_features(data, BASELINE) == ()
    assert extra_features(data, ModelConfig(extras=True)) == tuple(EXTRA_FEATURES)
    assert extra_features(data, ModelConfig(ranker=True, earnings=True)) == tuple(EARNINGS_FEATURES)
    assert extra_features(data, ModelConfig(extras=True, earnings=True)) == (*EXTRA_FEATURES, *EARNINGS_FEATURES)


def test_an_earnings_config_stores_the_earnings_columns_in_its_model(tmp_path):
    from advisor.model.earnings import EARNINGS_FEATURES
    from advisor.model.variants import fit_variant

    write_market(tmp_path, Market.US, stocks=6, days=900)
    data = load_market(tmp_path, Market.US)
    config = ModelConfig(ranker=True, earnings=True)
    fast = TrainConfig(horizons=(5,), rounds=10, params=FAST.params)
    model = fit_variant(data, run_variant(data, config, fast), config, fast)
    assert set(EARNINGS_FEATURES) <= set(model.features)
    assert list(model.features[: len(data.features)]) == list(data.features)
    plain = ModelConfig(ranker=True)
    other = fit_variant(data, run_variant(data, plain, fast), plain, fast)
    assert not set(EARNINGS_FEATURES) & set(other.features)
