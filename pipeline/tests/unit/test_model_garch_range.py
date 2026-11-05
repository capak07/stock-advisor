from dataclasses import replace

import numpy as np
import pandas as pd
import pytest
from scipy.stats import norm

from advisor.model.dataset import load_market
from advisor.model.train import (
    PARAMS,
    Fold,
    TrainConfig,
    blend_edges,
    blend_ranges,
    fit_final,
    from_files,
    to_files,
    walk_forward,
)
from advisor.models import Market
from model_data import write_market

FAST = TrainConfig(horizons=(5, 63), rounds=20, params={**PARAMS, "min_data_in_leaf": 50, "num_threads": 2})
CAL = pd.bdate_range("2022-01-03", periods=400)
FOLDS = [Fold(CAL[0], CAL[200]), Fold(CAL[200], CAL[399] + pd.Timedelta(days=1))]


def _pred(width: float) -> pd.DataFrame:
    """Fifty rows a day whose outcomes sit exactly on a normal's 50 quantiles, scale g; the model's
    range is q50 ± width · g, so ±1.2816 · g covers exactly 80%."""
    g = 0.02
    y = g * norm.ppf((np.arange(50) + 0.5) / 50)
    frames = [
        pd.DataFrame({"day": day, "fold": int(i >= 200), "y": y, "q50": 0.0, "q10": -width * g, "q90": width * g,
                      "garch_vol": g})
        for i, day in enumerate(CAL)
    ]
    return pd.concat(frames, ignore_index=True)


def _coverage(frame):
    return float(((frame["y"] >= frame["q10"]) & (frame["y"] <= frame["q90"])).mean())


def test_the_blend_averages_the_models_edges_with_the_garch_range():
    lo, hi = blend_edges(np.array([-0.02]), np.array([0.01]), np.array([0.04]), np.array([0.03]), 2.0)
    assert lo[0] == pytest.approx(0.5 * (-0.02 + 0.01 - 0.06)) and hi[0] == pytest.approx(0.5 * (0.04 + 0.01 + 0.06))


def test_a_too_narrow_range_is_blended_toward_80_percent():
    pred = _pred(width=0.2)
    out, info = blend_ranges(pred, CAL, 5, FOLDS)
    assert info["s"][0] is None and not info["used"][0]  # nothing known before the first period
    assert info["used"][1] and info["adopted"] and info["scale"] == info["s"][1]
    first, later = out["fold"] == 0, out["fold"] == 1
    pd.testing.assert_frame_equal(out[first], pred[first])
    assert abs(_coverage(out[later]) - 0.8) < abs(_coverage(pred[later]) - 0.8)
    assert abs(_coverage(out[later]) - 0.8) <= 0.05
    pd.testing.assert_series_equal(out["q50"], pred["q50"])


def test_a_range_already_at_80_percent_is_left_alone():
    pred = _pred(width=float(norm.ppf(0.9)))
    out, info = blend_ranges(pred, CAL, 5, FOLDS)
    assert not info["used"][1] and not info["adopted"] and info["scale"] is None
    pd.testing.assert_frame_equal(out, pred)


def test_a_row_without_garch_volatility_keeps_its_range():
    pred = _pred(width=0.2)
    pred.loc[pred.index[-1], "garch_vol"] = np.nan
    out, _ = blend_ranges(pred, CAL, 5, FOLDS)
    pd.testing.assert_series_equal(out.iloc[-1], pred.iloc[-1])


@pytest.fixture(scope="module")
def data(tmp_path_factory):
    path = tmp_path_factory.mktemp("garch-range")
    write_market(path, Market.TSX, stocks=20, days=1100)
    return load_market(path, Market.TSX, with_garch=True)


def test_only_a_garch_run_blends(data):
    assert all("garch_range" not in m for m in walk_forward(data, FAST).metrics.values())
    wf = walk_forward(data, FAST, garch=True)
    assert all({"s", "used", "adopted", "scale"} <= set(m["garch_range"]) for m in wf.metrics.values())


def test_a_final_model_applies_and_stores_its_adopted_scale(data):
    wf = walk_forward(data, FAST, garch=True)
    metrics = {h: dict(m) for h, m in wf.metrics.items()}
    metrics[5]["garch_range"] = {**metrics[5]["garch_range"], "adopted": True, "scale": 1.5}
    metrics[63]["garch_range"] = {**metrics[63]["garch_range"], "adopted": False, "scale": None}
    model = fit_final(data, replace(wf, metrics=metrics), FAST, garch=True)
    assert model.garch_scale == {5: 1.5}
    back = from_files(to_files(model))
    assert back.garch_scale == {5: 1.5} and back.garch == model.garch
    last = data.rows[data.rows["day"] == data.rows["day"].max()].set_index("symbol")
    x = last[data.features].assign(garch_vol_5=0.03, garch_vol_63=0.08)
    plain = replace(model, garch_scale={}).predict(x)
    blended = model.predict(x)
    five = plain["horizon"] == 5
    lo, hi = blend_edges(plain["q10"], plain["q50"], plain["q90"], 0.03, 1.5)
    np.testing.assert_allclose(blended.loc[five.to_numpy(), "q10"], lo[five], rtol=1e-12)
    np.testing.assert_allclose(blended.loc[five.to_numpy(), "q90"], hi[five], rtol=1e-12)
    pd.testing.assert_frame_equal(blended[~five.to_numpy()], plain[~five.to_numpy()])
