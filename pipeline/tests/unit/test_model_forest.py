"""The forest ranking booster (`forest`) and the forest screener (spec 2026-11-15)."""

import gzip
import json

import numpy as np
import pytest

from advisor.model import train as train_module
from advisor.model.dataset import load_market
from advisor.model.train import (
    PARAMS,
    TrainConfig,
    fit_final,
    forest_params,
    from_files,
    rank_ic,
    to_files,
    walk_forward,
)
from advisor.models import Market
from model_data import write_market

FAST = TrainConfig(horizons=(5, 63), rounds=20, params={**PARAMS, "min_data_in_leaf": 50, "num_threads": 2})


@pytest.fixture(scope="module")
def data(tmp_path_factory):
    path = tmp_path_factory.mktemp("forest")
    write_market(path, Market.TSX, stocks=30, days=1100)
    return load_market(path, Market.TSX)


@pytest.fixture(scope="module")
def garch_data(tmp_path_factory):
    path = tmp_path_factory.mktemp("forest_garch")
    write_market(path, Market.TSX, stocks=20, days=1100)
    return load_market(path, Market.TSX, with_garch=True)


def test_the_forest_settings_scale_the_smallest_leaf_with_the_data():
    small, large = forest_params({"num_threads": 2}, 1_000), forest_params({"num_threads": 2}, 1_000_000)
    assert small["boosting"] == "rf" and small["objective"] == "regression"
    assert small["feature_fraction"] == 0.3 and small["num_leaves"] == 63 and small["bagging_fraction"] == 0.6
    assert small["min_data_in_leaf"] == 200  # the floor
    assert large["min_data_in_leaf"] == 10_000  # 1% of the rows
    assert small["num_threads"] == 2  # the train config's own settings carry through


def test_a_forest_walk_forward_ranks_with_a_random_forest(data, monkeypatch):
    seen = []
    real = train_module._train

    def spy(params, *a, **k):
        seen.append(params)
        return real(params, *a, **k)

    monkeypatch.setattr(train_module, "_train", spy)
    wf = walk_forward(data, FAST, ranker=True, forest=True)
    assert any(p.get("boosting") == "rf" for p in seen)
    assert all(p.get("boosting") != "rf" for p in seen if p.get("objective") == "quantile")  # ranges unchanged
    assert wf.metrics[63]["rank_ic"] > 0.05
    assert wf.predictions["p"].dropna().between(0, 1).all()


def test_a_forest_without_the_ranker_is_refused(data):
    with pytest.raises(ValueError, match="ranker"):
        walk_forward(data, FAST, forest=True)


def test_the_screener_is_a_forest_ranker_that_ranks_and_round_trips(data):
    model = fit_final(data, walk_forward(data, FAST), FAST)
    files = to_files(model)
    meta = json.loads(gzip.decompress(files["meta"]).decode())
    assert meta["screener_kind"] == "forest_rank" and meta["screener_horizon"] == 21  # the rows carry y_21
    back = from_files(files)
    rows = data.rows.dropna(subset=["y_21"])
    np.testing.assert_allclose(back.screen(rows), model.screen(rows))
    scored = rows.assign(s=model.screen(rows))
    assert rank_ic(scored, "s", "y_21") > 0.05


def test_a_model_saved_before_the_forest_screener_still_screens(data):
    model = fit_final(data, walk_forward(data, FAST), FAST)
    files = to_files(model)
    meta = json.loads(gzip.decompress(files["meta"]).decode())
    del meta["screener_kind"], meta["screener_horizon"]
    files["meta"] = gzip.compress(json.dumps(meta).encode())
    x = data.rows.head(30)
    np.testing.assert_allclose(from_files(files).screen(x), model.screen(x))


def test_a_garch_models_screener_reads_the_garch_volatility_of_the_horizon_nearest_21(garch_data):
    wf = walk_forward(garch_data, FAST, ranker=True, garch=True)
    model = fit_final(garch_data, wf, FAST, garch=True)
    assert "garch_vol" in model.screener_features
    x = garch_data.rows.head(30)
    with pytest.raises(ValueError, match="garch_vol_5"):  # the model's horizon nearest 21
        model.screen(x)
    with_vol = x.assign(garch_vol_5=0.3, garch_vol_63=0.3, garch_vol_21=np.linspace(0.1, 2.0, 30))
    expected = model.screener.predict(with_vol.assign(garch_vol=with_vol["garch_vol_5"])[model.screener_features])
    np.testing.assert_allclose(model.screen(with_vol), expected)  # (5, 63): 5 is the horizon nearest 21
    np.testing.assert_allclose(model.screen(with_vol.assign(garch_vol_63=9.0)), expected)
    back = from_files(to_files(model))
    np.testing.assert_allclose(back.screen(with_vol), expected)
