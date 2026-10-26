import lightgbm as lgb
import numpy as np
import pandas as pd
import pytest

from advisor.model.dataset import load_market
from advisor.model.train import (
    PARAMS,
    Calibrator,
    TrainConfig,
    calibration_error,
    fit_final,
    from_files,
    make_folds,
    to_files,
    training_rows,
    walk_forward,
)
from advisor.models import Market
from model_data import write_market

FAST = TrainConfig(horizons=(5, 63), rounds=40, params={**PARAMS, "min_data_in_leaf": 50, "num_threads": 2})


def test_lightgbm_trains_in_this_environment():
    x = np.arange(200, dtype=float).reshape(-1, 1)
    booster = lgb.train({"objective": "binary", "verbose": -1, "min_data_in_leaf": 5},
                        lgb.Dataset(x, (x[:, 0] > 100).astype(int)), num_boost_round=5)
    low, high = booster.predict(np.array([[10.0], [190.0]]))
    assert low < 0.5 < high


def test_four_equal_test_periods_follow_two_years_of_training():
    days = pd.bdate_range("2018-01-01", "2025-12-31")
    folds = make_folds(days, TrainConfig())
    assert len(folds) == 4
    assert folds[0].start == pd.Timestamp("2020-01-01")
    assert folds[-1].end > days[-1]
    assert all(a.end == b.start for a, b in zip(folds, folds[1:], strict=False))


def test_training_rows_end_a_horizon_before_the_test_period():
    calendar = pd.bdate_range("2024-01-01", periods=100, name="day")
    rows = pd.DataFrame({"day": calendar[::5], "y_5": 0.01})
    rows.loc[1, "y_5"] = np.nan
    kept = training_rows(rows, calendar, 5, calendar[50])
    assert kept["day"].max() == calendar[40]  # day 45's 5-day target ends on the test period's first day
    assert calendar[5] not in set(kept["day"])  # no target, no training row


def test_calibration_never_claims_more_than_the_data_supports():
    rng = np.random.default_rng(1)
    p_raw = np.concatenate([rng.uniform(0.3, 0.6, 20_000), np.full(10, 0.95)])
    beat = np.concatenate([rng.random(20_000) < p_raw[:20_000], np.ones(10, dtype=bool)])
    cal = Calibrator.fit(p_raw, beat)
    assert cal(np.array([0.95]))[0] <= 0.65  # ten lucky rows don't make a 95% (or 100%) promise
    assert cal(np.array([0.45]))[0] == pytest.approx(0.45, abs=0.05)
    assert np.all(np.diff(cal(np.linspace(0, 1, 101))) >= 0)
    back = Calibrator.from_json(cal.to_json())
    assert back(np.array([0.5]))[0] == pytest.approx(cal(np.array([0.5]))[0])


def test_calibration_error_is_in_percentage_points():
    rng = np.random.default_rng(2)
    p = rng.uniform(0.2, 0.8, 50_000)
    assert calibration_error(p, rng.random(50_000) < p) < 1.0
    assert calibration_error(np.full(50_000, 0.8), rng.random(50_000) < 0.5) == pytest.approx(30, abs=1.5)


def test_walk_forward_finds_a_real_signal_and_calibrates_out_of_sample(tmp_path):
    write_market(tmp_path, Market.TSX, stocks=40)
    wf = walk_forward(load_market(tmp_path, Market.TSX), FAST)
    assert set(wf.metrics) == {5, 63}
    assert wf.metrics[63]["rank_ic"] > 0.1
    first = wf.predictions[wf.predictions["fold"] == 0]
    later = wf.predictions[wf.predictions["fold"] > 0]
    assert first["p"].isna().all()  # nothing earlier to calibrate the first period on
    assert later["p"].between(0, 1).all()
    assert (later["q10"] <= later["q50"]).all() and (later["q50"] <= later["q90"]).all()
    assert wf.metrics[63]["calibration_pts"] < 10
    assert wf.predictions["jump_5d"].isin([0.0, 1.0]).all()  # carried for the backtest's jump rule


def test_a_final_model_round_trips_through_its_files(tmp_path):
    write_market(tmp_path, Market.TSX, stocks=20, days=1100)
    data = load_market(tmp_path, Market.TSX)
    model = fit_final(data, walk_forward(data, FAST), FAST)
    files = to_files(model)
    assert set(files) == {"meta", "calibration", "screener"} | {
        f"h{h}_{part}" for h in (5, 63) for part in ("q10", "q50", "q90", "beat")
    }
    back = from_files(files)
    x = data.rows[data.features].head(50)
    pd.testing.assert_frame_equal(back.predict(x), model.predict(x))
    np.testing.assert_allclose(back.screen(x), model.screen(x))
    assert back.horizons == (5, 63) and back.features == data.features


def test_each_period_is_calibrated_only_on_outcomes_known_when_it_began(tmp_path, monkeypatch):
    write_market(tmp_path, Market.TSX, stocks=20, days=1100)
    data = load_market(tmp_path, Market.TSX)
    seen = []
    fit = Calibrator.fit

    def spy(cls, p_raw, beat, min_bin=500):
        seen.append(np.sort(p_raw))
        return fit(p_raw, beat, min_bin)

    monkeypatch.setattr(Calibrator, "fit", classmethod(spy))
    wf = walk_forward(data, TrainConfig(horizons=(63,), rounds=10, params=FAST.params))
    pred = wf.predictions
    position = data.calendar.searchsorted(pd.DatetimeIndex(pred["day"]))
    calibrated = sorted(pred.loc[pred["p"].notna(), "fold"].unique())
    assert calibrated and len(seen) == len(calibrated)
    for k, p_raw in zip(calibrated, seen, strict=True):
        known = position + 63 < data.calendar.searchsorted(wf.folds[k].start)
        assert known.sum() < (pred["fold"] < k).sum()  # the embargo drops the latest outcomes
        np.testing.assert_array_equal(p_raw, np.sort(pred.loc[known, "p_raw"].to_numpy()))
