import pandas as pd
import pytest

from advisor.model.dataset import load_market
from advisor.model.garch import GarchParams
from advisor.model.train import PARAMS, TrainConfig, fit_final, from_files, to_files, walk_forward
from advisor.model.variants import ModelConfig, run_variant, unbuilt
from advisor.models import Market
from model_data import write_market

FAST = TrainConfig(horizons=(5, 63), rounds=20, params={**PARAMS, "min_data_in_leaf": 50, "num_threads": 2})


@pytest.fixture(scope="module")
def data(tmp_path_factory):
    path = tmp_path_factory.mktemp("final-garch")
    write_market(path, Market.TSX, stocks=20, days=1100)
    return load_market(path, Market.TSX, with_garch=True)


def _live_frame(data, model):
    last = data.rows[data.rows["day"] == data.rows["day"].max()].set_index("symbol")
    x = last[data.features].copy()
    for h in model.horizons:
        x[f"garch_vol_{h}"] = 0.02 * (h ** 0.5)
    return x


def test_a_garch_model_round_trips_through_its_files(data):
    model = fit_final(data, walk_forward(data, FAST, garch=True), FAST, garch=True)
    assert model.features[-1] == "garch_vol"
    assert set(model.garch) == set(data.returns.columns)
    assert any(isinstance(p, GarchParams) for p in model.garch.values())
    files = to_files(model)
    back = from_files(files)
    assert back.garch == model.garch
    x = _live_frame(data, model)
    pd.testing.assert_frame_equal(back.predict(x), model.predict(x))
    assert back.contributions(x, 5).keys() == set(x.index)


def test_a_garch_model_needs_each_horizons_volatility(data):
    model = fit_final(data, walk_forward(data, FAST, garch=True), FAST, garch=True)
    x = _live_frame(data, model).drop(columns="garch_vol_63")
    with pytest.raises(ValueError, match="garch_vol_63"):
        model.predict(x)


def test_a_model_without_garch_has_no_garch_file(data):
    model = fit_final(data, walk_forward(data, FAST), FAST)
    files = to_files(model)
    assert "garch" not in files and model.garch is None and from_files(files).garch is None


def test_a_garch_config_is_built_stored_and_run(data):
    config = ModelConfig(factors=False, garch=True)
    assert unbuilt(config) is None and unbuilt(ModelConfig(factors=True, garch=True)) is None
    assert ModelConfig.from_json(config.to_json()) == config
    v1 = ModelConfig.from_json({"version": 1, "factors": False, "garch": True, "policy": None})
    assert v1 == config
    pd.testing.assert_frame_equal(
        run_variant(data, config, FAST).predictions, walk_forward(data, FAST, garch=True).predictions
    )
