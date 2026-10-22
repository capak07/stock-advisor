import numpy as np
import pandas as pd
import pytest

from advisor.model.features import (
    PRICE_FEATURES,
    Wide,
    as_traded,
    eligible,
    forward_excess,
    jump_days,
    price_features,
    relative_strength,
    to_wide,
)

DAYS = pd.bdate_range("2025-01-06", periods=320, name="day")


def wide(closes: dict[str, list[float]], volume: float = 1_000_000.0) -> Wide:
    n = len(next(iter(closes.values())))
    frame = pd.DataFrame(closes, index=DAYS[:n], dtype=float)
    return Wide(open=frame, high=frame, low=frame, close=frame, volume=frame * 0 + volume)


def inputs(closes: np.ndarray) -> tuple[Wide, pd.DataFrame, pd.DataFrame]:
    w = wide({"X": list(closes)})
    return w, w.close * w.volume, jump_days(w.close)


def test_the_long_frame_becomes_wide_frames_by_day_and_symbol():
    prices = pd.DataFrame({
        "symbol": ["A", "B", "A"], "day": [DAYS[0].date(), DAYS[0].date(), DAYS[1].date()],
        "open": [1.0, 2.0, 1.1], "high": [1.2, 2.2, 1.3], "low": [0.9, 1.9, 1.0], "close": [1.1, 2.1, 1.2],
        "volume": [100.0, 200.0, 300.0],
    })
    w = to_wide(prices)
    assert list(w.close.columns) == ["A", "B"] and w.close.index.name == "day"
    assert w.close.loc[DAYS[1], "A"] == 1.2 and np.isnan(w.close.loc[DAYS[1], "B"])


def test_as_traded_undoes_yahoos_split_and_dividend_adjustment():
    # Traded: 100, 100, then a 2:1 split (50), then a 1.00 dividend goes ex (49).
    # Yahoo's auto-adjusted closes are all 49.
    w = wide({"X": [49.0, 49.0, 49.0, 49.0]})
    events = pd.DataFrame({
        "symbol": ["X", "X"], "day": [DAYS[2].date(), DAYS[3].date()], "dividend": [0.0, 1.0], "split": [2.0, 0.0],
    })
    split_adjusted, traded = as_traded(w, events)
    assert split_adjusted["X"].round(6).tolist() == [50.0, 50.0, 50.0, 49.0]
    assert traded["X"].round(6).tolist() == [100.0, 100.0, 50.0, 49.0]


def test_jump_days_follow_the_live_rule():
    w = wide({"X": [10, 10.2, 30, 10.3, 10.1, 25, 26, 27]})
    # 30 is a bad print (back to 10.3 next day); 25 starts a new level, so only its first day flags
    assert jump_days(w.close)["X"].tolist() == [False, False, True, False, False, True, False, False]


def test_price_features_on_a_steady_climb():
    climb = 50 * 1.01 ** np.arange(300)
    f = price_features(*inputs(climb))
    t = DAYS[299]
    assert f["ret_5"].loc[t, "X"] == pytest.approx(1.01**5 - 1)
    assert f["mom_12_1"].loc[t, "X"] == pytest.approx(1.01**231 - 1)
    assert f["rsi_14"].loc[t, "X"] == pytest.approx(100.0)
    assert f["vol_20"].loc[t, "X"] == pytest.approx(0.0, abs=1e-9)
    assert f["dist_52w_high"].loc[t, "X"] == pytest.approx(0.0)
    assert f["dist_52w_low"].loc[t, "X"] == pytest.approx(1.01**251 - 1)
    assert f["jump_5d"].loc[t, "X"] == 0.0
    assert f["log_adv20"].loc[t, "X"] == pytest.approx(np.log1p((climb[280:300] * 1e6).mean()))
    assert set(f) == set(PRICE_FEATURES)


def test_features_on_a_day_ignore_everything_after_it():
    rng = np.random.default_rng(3)
    base = 50 * np.exp(np.cumsum(rng.normal(0, 0.02, 320)))
    changed = base.copy()
    changed[300:] *= 3  # whatever happens later
    a, b = price_features(*inputs(base)), price_features(*inputs(changed))
    for name in PRICE_FEATURES:
        pd.testing.assert_series_equal(a[name]["X"].iloc[:300], b[name]["X"].iloc[:300], check_names=False)


def test_relative_strength_is_measured_against_the_benchmark_and_the_sector_etf():
    day = DAYS[:1]
    returns = {"X": [0.10], "Y": [0.02], "B": [0.03], "E": [0.05], "F": [0.01]}
    feats = {"ret_21": pd.DataFrame(returns, index=day), "ret_63": pd.DataFrame(returns, index=day)}
    rs = relative_strength(feats, "B", {"X": "E"}, ["E", "F"])  # Y has no sector ETF: its benchmark
    assert rs["ex_bench_21"].loc[day[0], "X"] == pytest.approx(0.07)
    assert rs["ex_sector_21"].loc[day[0], "X"] == pytest.approx(0.05)
    assert rs["ex_sector_21"].loc[day[0], "Y"] == pytest.approx(-0.01)
    assert rs["sector_rank_63"].loc[day[0], "X"] == 1.0  # E led the market's sector ETFs
    assert np.isnan(rs["sector_rank_63"].loc[day[0], "Y"])  # the benchmark isn't ranked


def test_the_target_is_the_forward_return_over_the_benchmarks():
    w = wide({"X": [10.0, 11.0, 12.0], "B": [100.0, 100.0, 110.0]})
    y = forward_excess(w.close, "B", (1,))[1]
    assert y["X"].iloc[0] == pytest.approx(0.1)
    assert y["X"].iloc[1] == pytest.approx(12 / 11 - 1 - 0.1)
    assert np.isnan(y["X"].iloc[2])
    assert (y["B"].dropna() == 0).all()


def test_eligibility_needs_a_dollar_a_million_a_day_and_sixty_sessions():
    w = wide({"OK": [5.0] * 80, "CHEAP": [0.9] * 80, "THIN": [5.0] * 80})
    dollar_volume = w.close * w.volume
    dollar_volume["THIN"] = 500_000.0
    ok = eligible(w.close, dollar_volume)
    assert ok["OK"].tolist() == [False] * 59 + [True] * 21
    assert not ok["CHEAP"].any() and not ok["THIN"].any()
