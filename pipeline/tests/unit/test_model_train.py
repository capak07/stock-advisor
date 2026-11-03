import lightgbm as lgb
import numpy as np
import pandas as pd
import pytest

from advisor.model.dataset import MarketData, load_market
from advisor.model.train import (
    PARAMS,
    Calibrator,
    Fold,
    TrainConfig,
    _bin_gaps,
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


def test_a_score_that_ran_backwards_promises_no_stock_more_than_the_overall_rate():
    # the US 63- and 126-day pattern: the lowest scores beat most often, so the fit goes flat, and
    # two lucky top-scored rows must not inherit the bottom bin's hit rate as a 59% promise
    rng = np.random.default_rng(3)
    p_raw = np.concatenate([rng.uniform(0.0, 0.85, 30_000), [0.9, 0.91]])
    beat = np.concatenate([rng.random(30_000) < 0.6 - 0.25 * p_raw[:30_000], [True, True]])
    cal = Calibrator.fit(p_raw, beat)
    assert cal(np.array([0.95]))[0] <= beat.mean() + 0.005
    assert cal(np.linspace(0, 1, 101)).max() <= beat.mean() + 0.005


def test_calibration_error_is_in_percentage_points():
    rng = np.random.default_rng(2)
    p = rng.uniform(0.2, 0.8, 50_000)
    assert calibration_error(p, rng.random(50_000) < p) < 1.0
    assert calibration_error(np.full(50_000, 0.8), rng.random(50_000) < 0.5) == pytest.approx(30, abs=1.5)


def test_tied_probabilities_are_never_split_across_bins():
    p = np.full(10_000, 0.5)
    beat = np.arange(10_000) < 5_000  # the early rows beat, the later ones didn't
    assert calibration_error(p, beat) == pytest.approx(0.0)
    gaps, counts = _bin_gaps(p, beat, 10)
    assert counts.tolist() == [10_000] and gaps.tolist() == pytest.approx([0.0])


def test_calibration_error_does_not_depend_on_row_order():
    rng = np.random.default_rng(4)
    p = rng.choice([0.3, 0.45, 0.5, 0.62], 20_000)
    beat = rng.random(20_000) < 0.45
    perm = rng.permutation(20_000)
    assert calibration_error(p[perm], beat[perm]) == pytest.approx(calibration_error(p, beat), abs=1e-9)


def test_distinct_probabilities_still_get_equal_count_bins():
    p = np.random.default_rng(5).uniform(0.2, 0.8, 10_000)
    _, counts = _bin_gaps(p, p > 0.5, 10)
    assert counts.tolist() == [1_000] * 10


def test_the_floor_takes_every_row_tied_at_the_lowest_score():
    # a constant booster's rows tie at one score: the floor is their whole hit rate, not the rate
    # of whichever 1,000 of them came first (crypto's early folds, 2026-11-03)
    rng = np.random.default_rng(6)
    tied_beat = np.concatenate([np.arange(1_000) % 2 == 0, np.arange(9_000) < 2_500])  # 50% first, 30% overall
    p_raw = np.concatenate([np.full(10_000, 0.2), rng.uniform(0.5, 0.9, 10_000)])
    beat = np.concatenate([tied_beat, rng.random(10_000) < 0.7])
    cal = Calibrator.fit(p_raw, beat)
    assert cal.lo == pytest.approx(0.30)
    assert cal(np.array([0.2]))[0] == pytest.approx(0.30, abs=0.01)


def test_the_ceiling_never_rests_on_a_handful_above_a_tie():
    # a big tie just below the top left Task 1's top bin with only the 5 rows above it, so 5 lucky
    # rows set the ceiling (crypto's monthly fits, final review 2026-11-03)
    rng = np.random.default_rng(8)
    p_raw = np.concatenate([rng.uniform(0.1, 0.5, 15_000), np.full(4_995, 0.6), rng.uniform(0.7, 0.8, 5)])
    beat = np.concatenate([rng.random(15_000) < 0.3, np.arange(4_995) % 2 == 0, np.ones(5, dtype=bool)])
    cal = Calibrator.fit(p_raw, beat)
    assert cal.hi == pytest.approx(0.5, abs=0.01)
    assert cal(np.array([0.75]))[0] <= 0.51


def test_a_constant_score_gets_its_overall_hit_rate():
    p_raw = np.full(20_000, 0.37)
    beat = np.arange(20_000) >= 12_000  # 40%, all in the later rows
    cal = Calibrator.fit(p_raw, beat)
    assert cal.lo == pytest.approx(0.40) and cal.hi == pytest.approx(0.40)
    assert cal(np.array([0.1, 0.37, 0.9])).tolist() == pytest.approx([0.40] * 3)


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
    # a `ranges` file is written only for edges the data earned a correction for (test_model_ranges)
    assert set(files) - {"ranges"} == {"meta", "calibration", "screener"} | {
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


def test_contributions_name_the_features_that_moved_the_forecast(tmp_path):
    write_market(tmp_path, Market.TSX, stocks=20, days=1100)
    data = load_market(tmp_path, Market.TSX)
    model = fit_final(data, walk_forward(data, FAST), FAST)
    x = data.rows.drop_duplicates("symbol").set_index("symbol")[data.features].head(3)
    out = model.contributions(x, 63)
    assert set(out) == set(x.index)
    for parts in out.values():
        assert len(parts) == 3 and {p["feature"] for p in parts} <= set(data.features)
        assert abs(parts[0]["contribution"]) >= abs(parts[-1]["contribution"])
    booster = model.boosters[63]["q50"]
    raw = booster.predict(x[data.features], pred_contrib=True)
    assert raw.sum(axis=1) == pytest.approx(booster.predict(x[data.features]))  # features + bias = the forecast
    for key, vals in zip(x.index, raw, strict=True):
        by_name = dict(zip(data.features, vals[:-1], strict=True))
        for part in out[key]:
            assert part["contribution"] == pytest.approx(by_name[part["feature"]])


def _mom_book():
    """One stock whose excess return is exactly 1 × the momentum factor, so alpha is 0."""
    days = pd.bdate_range("2014-01-02", periods=400)
    premium = np.full(len(days), 0.02)
    rows = pd.DataFrame({
        "day": days, "symbol": "MOM", "sector": "X", "dollar_volume_20": 1_000_000.0,
        "y_5": premium, "x": 0.0, "beta_mom": 1.0, "f_mom_5": premium,
    })
    folds = [Fold(days[200], days[300]), Fold(days[300], days[-1] + pd.Timedelta(days=1))]
    config = TrainConfig(horizons=(5,), rounds=15, params={**PARAMS, "min_data_in_leaf": 5, "num_threads": 1})
    return MarketData("TSX", rows, ["x"], days), folds, config


def test_a_pure_factor_return_trains_near_zero_alpha_and_keeps_the_premium():
    data, folds, config = _mom_book()
    pred = walk_forward(data, config, folds=folds, factor_names=("mom",)).predictions
    assert pred["q50_alpha"].abs().max() < 0.02
    assert pred["q50"].mean() == pytest.approx(0.02, abs=0.02)


def test_a_fold_ignores_its_own_test_targets_and_forward_factors():
    data, folds, config = _mom_book()
    base = walk_forward(data, config, folds=folds, factor_names=("mom",))
    leaked = data.rows.copy()
    test = (leaked["day"] >= folds[1].start) & (leaked["day"] < folds[1].end)
    leaked.loc[test, "y_5"] = 0.9
    leaked.loc[test, "f_mom_5"] = -0.5
    alt = walk_forward(
        MarketData(data.market, leaked, data.features, data.calendar), config, folds=folds, factor_names=("mom",),
    )
    fold = base.predictions["fold"] == 1
    for col in ("q50", "q50_alpha", "p_raw", "p"):
        pd.testing.assert_series_equal(
            base.predictions.loc[fold, col].reset_index(drop=True),
            alt.predictions.loc[fold, col].reset_index(drop=True),
        )


def test_factor_files_round_trip_and_live_predict_shifts_only_a_known_symbol():
    data, folds, config = _mom_book()
    wf = walk_forward(data, config, folds=folds, factor_names=("mom",))
    model = fit_final(data, wf, config, factor_names=("mom",))
    restored = from_files(to_files(model))
    assert restored.factor_names == ("mom",)
    assert restored.mu[5]["mom"] == pytest.approx(model.mu[5]["mom"])
    assert restored.betas["MOM"]["mom"] == pytest.approx(1.0)
    out = restored.predict(pd.DataFrame({"x": [0.0, 0.0]}, index=["MOM", "NEW"]))
    mom = out[out.index == "MOM"].iloc[0]
    unknown = out[out.index == "NEW"].iloc[0]
    assert mom["q50"] == pytest.approx(0.02, abs=0.02)
    assert unknown["q50"] == pytest.approx(0.0, abs=0.02)


def test_explanations_never_name_a_factor_exposure():
    data, folds, config = _mom_book()
    model = fit_final(data, walk_forward(data, config, folds=folds, factor_names=("mom",)), config, factor_names=("mom",))
    out = model.contributions(pd.DataFrame({"x": [0.0]}, index=["MOM"]), 5, top=3)
    assert out["MOM"] and not any(p["feature"].startswith("beta_") for p in out["MOM"])


def test_the_alpha_diagnostic_ranks_within_each_horizon():
    from advisor.model.train import rank_ic_by_horizon
    day = pd.Timestamp("2024-01-02")
    frame = pd.DataFrame({
        "day": day, "horizon": [5, 5, 126, 126],
        "q50_alpha": [0.01, 0.02, 0.10, 0.20],
        "alpha": [0.01, 0.02, -0.10, -0.20],  # right at 5 days, backwards at 126: on average no skill
    })
    assert rank_ic_by_horizon(frame, "q50_alpha", "alpha") == pytest.approx(0.0)
