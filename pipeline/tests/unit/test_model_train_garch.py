from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from advisor.model import train as train_module
from advisor.model.dataset import load_market
from advisor.model.garch import garch_vol
from advisor.model.train import PARAMS, TrainConfig, walk_forward
from advisor.models import Market
from model_data import write_market

FAST = TrainConfig(horizons=(5, 63), rounds=20, params={**PARAMS, "min_data_in_leaf": 50, "num_threads": 2})


@pytest.fixture(scope="module")
def market(tmp_path_factory):
    path = tmp_path_factory.mktemp("garch")
    write_market(path, Market.TSX, stocks=20, days=1100)
    return path


def _spy(monkeypatch):
    """Record each `_fit_horizon` call's training frame."""
    calls = []
    real = train_module._fit_horizon

    def spy(x, y, config, *a, **k):
        calls.append(x.copy())
        return real(x, y, config, *a, **k)

    monkeypatch.setattr(train_module, "_fit_horizon", spy)
    return calls


def test_walk_forward_without_garch_is_unchanged(market):
    plain = walk_forward(load_market(market, Market.TSX), FAST)
    loaded = walk_forward(load_market(market, Market.TSX, with_garch=True), FAST)
    pd.testing.assert_frame_equal(plain.predictions, loaded.predictions)
    assert plain.metrics.keys() == loaded.metrics.keys() and loaded.garch_fallbacks == 0


def test_each_horizon_trains_on_its_own_forecast_volatility(market, monkeypatch):
    data = load_market(market, Market.TSX, with_garch=True)
    calls = _spy(monkeypatch)
    wf = walk_forward(data, FAST, garch=True)
    assert all(list(x.columns)[-1] == "garch_vol" for x in calls)
    fold = wf.folds[1]
    params, _ = data.garch_cache[(fold.start, FAST.horizons)]
    assert sum(p is not None for p in params.values()) >= 15  # the synthetic stocks fit
    # the second call is horizon 5, fold 1: its rows' garch_vol is that fold's 5-day forecast
    x = calls[1]
    rows = data.rows.loc[x.index]
    symbol = rows["symbol"].iloc[-1]
    expected = garch_vol(data.returns[symbol], params[symbol], (5,))["garch_vol_5"]
    mine = rows["symbol"] == symbol
    np.testing.assert_allclose(x.loc[mine, "garch_vol"], expected.reindex(rows.loc[mine, "day"]), rtol=1e-12)


def test_garch_parameters_ignore_the_folds_own_outcomes(market, monkeypatch):
    data = load_market(market, Market.TSX, with_garch=True)
    start = walk_forward(data, FAST, garch=True).folds[1].start
    calls = _spy(monkeypatch)
    walk_forward(data, FAST, garch=True)
    changed = data.returns.copy()
    changed.loc[changed.index >= start] = 0.3  # the period's own moves, and everything after
    other = replace(data, returns=changed, garch_cache={})
    walk_forward(other, FAST, garch=True)
    key = (start, FAST.horizons)
    assert other.garch_cache[key][0] == data.garch_cache[key][0]
    half = len(calls) // 2
    first, second = calls[:half], calls[half:]
    # fold 1's training rows (horizon 5) end before the period, so their volatility doesn't move
    pd.testing.assert_series_equal(first[1]["garch_vol"], second[1]["garch_vol"])


def test_a_symbol_without_enough_returns_is_counted_not_dropped(market):
    data = load_market(market, Market.TSX, with_garch=True)
    short = data.rows["symbol"].iloc[0]
    returns = data.returns.copy()
    returns[short] = np.nan
    other = replace(data, returns=returns, garch_cache={})
    wf = walk_forward(other, FAST, garch=True)
    folds_with_it = wf.predictions.loc[wf.predictions["symbol"] == short, "fold"].nunique()
    assert folds_with_it >= 1 and wf.garch_fallbacks >= folds_with_it


def test_garch_needs_the_daily_returns(market):
    with pytest.raises(ValueError, match="with_garch=True"):
        walk_forward(load_market(market, Market.TSX), FAST, garch=True)
