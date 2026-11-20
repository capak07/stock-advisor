import math
from datetime import date, timedelta

import numpy as np
import pytest

from advisor.portfolio import exit_plan
from advisor.portfolio.exit_plan import (
    LOOKBACK,
    NO_FORECAST_HORIZON,
    PLAN_VERSION,
    NoPlan,
    build_plan,
    median_drift,
    read_plan,
    seed_of,
    simulate,
    touch_share,
)

DAY = date(2026, 11, 20)
KEYS = {
    "low", "mid", "high", "sell_at", "p_touch", "p_stop_first", "p_up", "breakeven",
    "p_breakeven", "version", "basis", "drift", "horizon", "cost_price", "recheck_by", "status",
}


def _paths(rows):  # cumulative log returns, one row per path
    return np.log(np.array(rows, dtype=float))


def test_the_range_is_the_10th_50th_and_90th_percentile_of_the_end_prices():
    paths = _paths([[1.0, r] for r in np.linspace(0.5, 1.5, 101)])  # indexes 10, 50, 90 -> 0.6, 1.0, 1.4
    plan = read_plan(paths, 10.0, stop=None, breakeven=None, cost=0.0)
    assert (plan["low"], plan["mid"], plan["high"]) == pytest.approx((6.0, 10.0, 14.0))
    assert plan["p_up"] == pytest.approx(50 / 101)  # r = 1.0 ends at 0, not above


def test_touch_share_counts_the_paths_whose_highest_close_reaches_the_level():
    paths = _paths([[1.3, 1.0], [1.0, 1.2], [1.1, 1.0], [1.0, 1.0], [0.9, 1.0], [0.8, 0.9]])
    assert touch_share(paths, np.log(1.15)) == pytest.approx(2 / 6)  # maxima 1.3, 1.2
    assert touch_share(paths, np.log(0.95)) == pytest.approx(5 / 6)  # all but 0.9


def test_sell_at_is_the_level_a_third_of_the_paths_close_at_or_above():
    # maxima 1.3, 1.2, 1.1, 1.0, 1.0, 0.9: k = ceil(6 / 3) = 2, the 2nd highest is 1.2
    paths = _paths([[1.3, 1.0], [1.0, 1.2], [1.1, 1.0], [1.0, 1.0], [0.9, 1.0], [0.8, 0.9]])
    plan = read_plan(paths, 100.0, stop=None, breakeven=None, cost=0.0)
    assert plan["sell_at"] == pytest.approx(120.0) and plan["p_touch"] == pytest.approx(2 / 6)
    assert plan["p_stop_first"] is None


def test_the_stop_first_chance_counts_paths_that_reach_the_stop_before_the_sell_at_price():
    # maxima 1.3, 1.3, 1.25, 0.9, 1.0, 1.0: sell_at 130; paths 2 and 4 close at or under 90 first
    paths = _paths([[1.3, 1.0], [0.8, 1.3], [1.0, 1.25], [0.85, 0.9], [1.0, 1.0], [1.0, 1.0]])
    plan = read_plan(paths, 100.0, stop=90.0, breakeven=None, cost=0.0)
    assert plan["sell_at"] == pytest.approx(130.0)
    assert plan["p_stop_first"] == pytest.approx(2 / 6)


def test_a_sell_at_price_inside_the_cost_or_under_the_stop_is_not_given():
    paths = _paths([[1.01, 1.0]] * 2 + [[1.0, 1.0]] * 4)  # sell_at 101 <= 100 * 1.032 = 103.2
    plan = read_plan(paths, 100.0, stop=None, breakeven=None, cost=0.032)
    assert plan["sell_at"] is None and plan["p_touch"] is None and plan["low"] is not None
    plan = read_plan(paths, 100.0, stop=101.0, breakeven=None, cost=0.0)  # sell_at 101 <= stop 101
    assert plan["sell_at"] is None and plan["p_touch"] is None and plan["p_stop_first"] is None


def test_the_break_even_chance_is_the_share_of_paths_that_reach_it():
    paths = _paths([[1.3, 1.0], [1.0, 1.2], [1.1, 1.0], [1.0, 1.0], [0.9, 1.0], [0.8, 0.9]])
    plan = read_plan(paths, 100.0, stop=None, breakeven=115.0, cost=0.0)
    assert plan["breakeven"] == 115.0 and plan["p_breakeven"] == pytest.approx(2 / 6)


# --- build_plan --------------------------------------------------------------------------


def _days(n, end=DAY):
    return [end - timedelta(days=n - 1 - i) for i in range(n)]


def _walk(n, seed, start=100.0, sd=0.02):
    return start * np.exp(np.cumsum(np.random.default_rng(seed).normal(0.0, sd, n)))


def _closes(n=300, seed=1, start=100.0, end=DAY):
    return dict(zip(_days(n, end), map(float, _walk(n, seed, start)), strict=True))


def _bench(n=300, seed=2, end=DAY):
    return _closes(n, seed, 50.0, end)


def _plan(**kw):
    args = dict(
        symbol="AAPL", day=DAY, closes=_closes(), price=4.0, horizon=None, forecast=None,
        bench_closes=None, stop=None, cost_cad=1000.0, value_cad=800.0, cost=0.0,
    )
    args.update(kw)
    return build_plan(**args)


def test_the_plan_has_exactly_the_stored_keys():
    plan = _plan()
    assert set(plan) == KEYS
    assert plan["version"] == PLAN_VERSION and plan["status"] is None


def test_break_even_is_given_only_under_water():
    plan = _plan(cost_cad=1000.0, value_cad=800.0)
    assert plan["breakeven"] == pytest.approx(5.0)
    assert plan["p_breakeven"] is not None and 0 <= plan["p_breakeven"] <= 1
    plan = _plan(cost_cad=1000.0, value_cad=1200.0)
    assert plan["breakeven"] is None and plan["p_breakeven"] is None


def test_cost_price_is_the_native_cost_per_unit():
    assert _plan(cost_cad=1000.0, value_cad=800.0)["cost_price"] == pytest.approx(5.0)
    assert _plan(cost_cad=1000.0, value_cad=1200.0)["cost_price"] == pytest.approx(10 / 3)
    plan = _plan(cost_cad=1000.0, value_cad=0.0)
    assert plan["cost_price"] is None and plan["breakeven"] is None


FORECAST = (-0.08, 0.02, 0.15)


def test_a_forecast_plan_names_its_basis_drift_and_horizon():
    bench = _bench()
    plan = _plan(forecast=FORECAST, horizon=10, bench_closes=bench)
    assert plan["basis"] == "forecast" and plan["horizon"] == 10
    last = [bench[d] for d in sorted(bench)][-LOOKBACK:]
    assert plan["drift"] == pytest.approx(median_drift(last, 10))


def test_the_drift_reads_only_the_last_252_benchmark_closes():
    # the first 400 closes rise 2% a day, the last 252 1% a day
    values = [100.0 * 1.02 ** min(i, 399) * 1.01 ** max(i - 399, 0) for i in range(652)]
    bench = dict(zip(_days(652), values, strict=True))
    closes = {d: c * (1.0 + 0.01 * math.sin(i)) for i, (d, c) in enumerate(bench.items())}
    plan = _plan(closes=closes, forecast=FORECAST, horizon=10, bench_closes=bench)
    assert plan["drift"] == pytest.approx(1.01 ** 10 - 1)  # the whole history's median is 2%-based


def test_without_a_forecast_the_plan_is_from_volatility_over_21_steps():
    plan = _plan()
    assert plan["basis"] == "volatility" and plan["drift"] is None
    assert plan["horizon"] == NO_FORECAST_HORIZON == 21


def test_the_recheck_date_comes_from_the_plans_own_horizon():
    def recheck(n):
        return DAY + timedelta(days=n)

    plan = _plan(forecast=FORECAST, horizon=10, bench_closes=_bench(), recheck=recheck)
    assert plan["recheck_by"] == "2026-11-30"
    plan = _plan(forecast=FORECAST, horizon=63, bench_closes=None, recheck=recheck)
    assert plan["basis"] == "volatility" and plan["recheck_by"] == "2026-12-11"
    assert _plan(forecast=FORECAST, horizon=10, bench_closes=_bench())["recheck_by"] is None


@pytest.mark.parametrize("price", [None, math.nan, math.inf, 0.0, -1.0])
def test_a_missing_or_non_finite_price_is_refused(price):
    with pytest.raises(NoPlan, match="no price"):
        _plan(price=price)


def test_a_plan_with_a_non_finite_number_is_refused(monkeypatch):
    real = exit_plan.read_plan

    def nan_mid(*args, **kwargs):
        return {**real(*args, **kwargs), "mid": math.nan}

    monkeypatch.setattr(exit_plan, "read_plan", nan_mid)
    with pytest.raises(NoPlan, match="plan is not finite"):
        _plan()


def test_a_non_finite_cost_is_refused():
    with pytest.raises(NoPlan, match="plan is not finite"):
        _plan(cost_cad=math.nan)


def test_a_nan_drift_never_reaches_the_plan(monkeypatch):
    monkeypatch.setattr(exit_plan, "median_drift", lambda closes, horizon: math.nan)
    with pytest.raises(NoPlan, match="plan is not finite"):
        _plan(forecast=FORECAST, horizon=10, bench_closes=_bench())


@pytest.mark.parametrize("error", [ValueError("math domain error"), IndexError("index -1"), ZeroDivisionError()])
def test_a_failed_simulation_is_a_plan_that_cannot_be_built(monkeypatch, error):
    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(exit_plan, "simulate", fail)
    with pytest.raises(NoPlan, match="plan could not be built") as caught:
        _plan()
    assert type(caught.value) is NoPlan


def test_a_benchmark_drift_at_or_under_minus_one_is_a_plan_that_cannot_be_built(monkeypatch):
    monkeypatch.setattr(exit_plan, "median_drift", lambda closes, horizon: -1.0)  # log1p(-1) fails
    with pytest.raises(NoPlan, match="plan could not be built"):
        _plan(forecast=FORECAST, horizon=10, bench_closes=_bench())


def test_a_horizon_under_one_is_refused():
    with pytest.raises(NoPlan):
        _plan(forecast=FORECAST, horizon=0, bench_closes=_bench())


def test_too_little_history_is_refused():
    with pytest.raises(NoPlan, match="too little price history"):
        _plan(closes=_closes(n=59))
    assert _plan(closes=_closes(n=60))["basis"] == "volatility"


def test_closes_after_the_feature_day_are_not_read():
    later_end = DAY + timedelta(days=40)
    closes = {**_closes(), **{d: c for d, c in _closes(seed=5, end=later_end).items() if d > DAY}}
    bench = {**_bench(), **{d: c for d, c in _bench(seed=6, end=later_end).items() if d > DAY}}
    for kw in ({}, {"forecast": FORECAST, "horizon": 10}):
        before = _plan(bench_closes=_bench(), **kw)
        after = _plan(closes=closes, bench_closes=bench, **kw)
        assert after == before


def test_closes_after_the_feature_day_never_enter_the_lookback_window(monkeypatch):
    seen = {}
    real = exit_plan.simulate

    def spy(moves, horizon, seed, **kwargs):
        seen["moves"] = np.asarray(moves)
        return real(moves, horizon, seed, **kwargs)

    monkeypatch.setattr(exit_plan, "simulate", spy)
    later = {DAY + timedelta(days=i): 1000.0 * (i % 2 + 1) for i in range(1, 300)}
    _plan(closes={**_closes(), **later})
    assert len(seen["moves"]) == LOOKBACK - 1
    assert np.abs(seen["moves"]).max() < 0.5  # no wild jump from the later closes


def test_a_higher_level_is_touched_no_more_often():
    moves = np.random.default_rng(1).normal(0.0, 0.02, 252)
    paths = simulate(moves, 21, seed_of("AAPL", DAY))
    shares = [touch_share(paths, level) for level in np.linspace(0.0, 0.3, 31)]
    assert np.all(np.diff(shares) <= 0)


def test_the_same_holding_and_day_give_the_same_plan():
    kw = dict(forecast=FORECAST, horizon=10, bench_closes=_bench(), stop=3.5)
    assert _plan(**kw) == _plan(**kw)
    assert _plan() == _plan()


def test_every_number_in_a_plan_is_a_finite_float():
    plan = _plan(forecast=FORECAST, horizon=10, bench_closes=_bench(), stop=3.5)
    for key, value in plan.items():
        if key in ("basis", "recheck_by", "status", "version", "horizon") or value is None:
            continue
        assert type(value) is float and math.isfinite(value), key
