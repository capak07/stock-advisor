import numpy as np
import pandas as pd
import pytest

from advisor.model.dataset import load_market
from advisor.model.train import (
    PARAMS,
    Fold,
    RangeCalibrator,
    TrainConfig,
    calibrate_ranges,
    fit_final,
    from_files,
    to_files,
    walk_forward,
)
from advisor.models import Market
from model_data import write_market


def _biased(n: int, seed: int = 0) -> pd.DataFrame:
    """Outcomes centred on -1% while the raw range claims a +3% median: the KEEL.TO pattern."""
    rng = np.random.default_rng(seed)
    return pd.DataFrame({"y": rng.normal(-0.01, 0.05, n), "q10": -0.03, "q50": 0.03, "q90": 0.09})


def test_a_range_calibrator_puts_a_tenth_half_and_nine_tenths_of_outcomes_below_its_edges():
    calibrator = RangeCalibrator.fit(_biased(20_000))
    fresh = _biased(20_000, seed=1)
    fixed = calibrator(fresh[["q10", "q50", "q90"]])
    for name, share in (("q10", 0.1), ("q50", 0.5), ("q90", 0.9)):
        assert (fresh["y"] < fixed[name]).mean() == pytest.approx(share, abs=0.02)
    assert (fixed["q10"] <= fixed["q50"]).all() and (fixed["q50"] <= fixed["q90"]).all()
    assert RangeCalibrator.from_json(calibrator.to_json()).shifts == calibrator.shifts


def test_a_wider_range_moves_further():
    calibrator = RangeCalibrator({"q10": 0.0, "q50": -0.25, "q90": 0.0})
    out = calibrator(pd.DataFrame({"q10": [-0.1, -0.4], "q50": [0.0, 0.0], "q90": [0.1, 0.4]}))
    assert out["q50"].tolist() == pytest.approx([-0.05, -0.2])  # a quarter of each width


def _folds_frame(bias: float, seed: int = 0) -> tuple[pd.DataFrame, pd.DatetimeIndex, list[Fold]]:
    calendar = pd.bdate_range("2020-01-01", periods=300)
    rng = np.random.default_rng(seed)
    days = calendar[:280:2]
    frame = pd.DataFrame({"day": np.repeat(days, 60)})
    frame["fold"] = np.select([frame["day"] < calendar[100], frame["day"] < calendar[200]], [0, 1], 2)
    frame["y"] = rng.normal(-0.01, 0.05, len(frame))
    frame["q50"] = -0.01 + bias
    frame["q10"] = frame["q50"] - 0.064
    frame["q90"] = frame["q50"] + 0.064
    folds = [Fold(calendar[0], calendar[100]), Fold(calendar[100], calendar[200]), Fold(calendar[200], calendar[299])]
    return frame, calendar, folds


def test_a_period_uses_a_calibrated_range_only_once_earlier_periods_show_it_helps():
    biased, calendar, folds = _folds_frame(bias=0.04)
    out, info = calibrate_ranges(biased, calendar, 5, folds)
    assert info["adopted"] and info["pinball_calibrated"] < info["pinball_raw"]
    assert info["periods"] == {"1": False, "2": True}  # period 1 has no calibrated period before it
    last = out["fold"] == 2
    assert (out.loc[last, "q50"] < biased.loc[last, "q50"]).all()  # pulled down towards the outcomes
    pd.testing.assert_series_equal(out.loc[~last, "q50"], biased.loc[~last, "q50"])
    assert (out["q50_raw"] == biased["q50"]).all()


def test_a_period_is_calibrated_only_on_outcomes_known_before_it():
    frame, calendar, folds = _folds_frame(bias=0.04)
    before, _ = calibrate_ranges(frame, calendar, 5, folds)
    changed = frame.copy()
    changed.loc[changed["fold"] == 2, "y"] = 5.0  # wild outcomes in the last period
    after, _ = calibrate_ranges(changed, calendar, 5, folds)
    cols = ["q10", "q50", "q90"]
    pd.testing.assert_frame_equal(before[cols], after[cols])  # neither the shift nor the choice to use it


def test_the_final_model_stores_and_applies_its_range_calibration(tmp_path):
    write_market(tmp_path, Market.TSX, stocks=20, days=1100)
    data = load_market(tmp_path, Market.TSX)
    config = TrainConfig(horizons=(5, 63), rounds=20, params={**PARAMS, "min_data_in_leaf": 50, "num_threads": 2})
    wf = walk_forward(data, config)
    assert {"adopted", "pinball_raw", "pinball_calibrated", "below_median_raw"} <= set(wf.metrics[5]["range"])
    model = fit_final(data, wf, config)
    adopted = {h for h in config.horizons if wf.metrics[h]["range"]["adopted"]}
    assert set(model.ranges) == adopted
    back = from_files(to_files(model))
    assert set(back.ranges) == adopted
    x = data.rows[data.features].head(20)
    pd.testing.assert_frame_equal(back.predict(x), model.predict(x))


def test_a_model_saved_before_range_calibration_still_loads(tmp_path):
    write_market(tmp_path, Market.TSX, stocks=20, days=1100)
    data = load_market(tmp_path, Market.TSX)
    config = TrainConfig(horizons=(5,), rounds=10, params={**PARAMS, "min_data_in_leaf": 50, "num_threads": 2})
    files = to_files(fit_final(data, walk_forward(data, config), config))
    files.pop("ranges", None)
    assert from_files(files).ranges == {}
