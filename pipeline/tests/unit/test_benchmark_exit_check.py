"""The benchmark's exit plan check: plans built as live builds them, judged on later closes."""

import math
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from advisor.benchmark.exit_check import (
    MIN_VALUE_DAYS,
    PAIRS_PER_FOLD,
    TOLERANCE,
    VALUE_T,
    Judged,
    judge_pairs,
    verdicts,
    walk_exits,
)
from advisor.benchmark.simulate import DailyPanel
from advisor.model.crypto import CRYPTO
from advisor.models import Market
from advisor.policy import DEFAULT_POLICY
from advisor.portfolio.exit_plan import TOUCH, build_plan

SESSIONS, SYMBOLS = 300, 100
BENCH = "XIU.TO"


def _panel(
    seed: int = 1, bench: str = BENCH, sessions: int = SESSIONS, symbols: int = SYMBOLS, martingale: bool = False,
) -> DailyPanel:
    """Driftless random walks, each symbol with a known daily volatility: driftless in log terms, or
    with `martingale` driftless in price terms (a log drift of -sigma^2 / 2 a day)."""
    rng = np.random.default_rng(seed)
    days = pd.bdate_range("2024-01-01", periods=sessions)
    sigma = np.linspace(0.01, 0.04, symbols)
    names = [f"S{k:03d}" for k in range(symbols)]
    drift = -sigma**2 / 2 if martingale else 0.0
    logs = np.cumsum(rng.normal(0.0, 1.0, (sessions, symbols)) * sigma + drift, axis=0)
    close = pd.DataFrame(50.0 * np.exp(logs), index=days, columns=names)
    close[bench] = 100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.01, sessions)))
    atr = pd.DataFrame(np.tile(1.25 * sigma, (sessions, 1)), index=days, columns=names)
    atr[bench] = 0.0125
    return DailyPanel(close, atr, bench)


def _rows(panel: DailyPanel, days: list[int], horizons=(21,), folds=None) -> pd.DataFrame:
    """Prediction rows for every symbol on the given session indexes; folds 1-3 by thirds of the days
    unless given."""
    symbols = [s for s in panel.close.columns if s != panel.benchmark]
    out = []
    for n, i in enumerate(days):
        fold = folds[n] if folds is not None else 1 + (3 * n) // len(days)
        for s in symbols:
            for h in horizons:
                width = 1.28 * 0.02 * math.sqrt(h)
                out.append({
                    "day": panel.close.index[i], "symbol": s, "horizon": h, "fold": fold,
                    "q10": -width, "q50": 0.0, "q90": width, "p": 0.5, "dollar_volume_20": 2e7,
                })
    return pd.DataFrame(out)


def test_a_plan_reads_nothing_after_its_sample_day():
    panel = _panel()
    d = 200
    rows = _rows(panel, [d], horizons=(5, 21), folds=[1])
    changed_close = panel.close.copy()
    changed_atr = panel.atr_pct.copy()
    rng = np.random.default_rng(99)
    changed_close.iloc[d + 1:] *= np.exp(rng.normal(0.0, 0.05, changed_close.iloc[d + 1:].shape))
    changed_atr.iloc[d + 1:] *= 2.0
    changed = DailyPanel(changed_close, changed_atr, panel.benchmark)  # the benchmark column too

    before = judge_pairs(rows, panel, Market.TSX, [5, 21], 0.0, DEFAULT_POLICY)
    after = judge_pairs(rows, changed, Market.TSX, [5, 21], 0.0, DEFAULT_POLICY)
    assert len(before) == len(after) > 0
    assert {j.cls for j in before} == {"forecast", "volatility"}
    assert [j.plan for j in before] == [j.plan for j in after]
    assert [j.end_price for j in before] != [j.end_price for j in after]


def test_a_pair_whose_horizon_runs_past_the_panel_is_skipped():
    panel = _panel(symbols=3)
    last = SESSIONS - 1
    # 5 sessions fit after this day, 21 do not: the forecast pair is judged, the volatility pair skipped
    fits = judge_pairs(_rows(panel, [last - 5], horizons=(5,), folds=[1]), panel, Market.TSX, [5], 0.0,
                       DEFAULT_POLICY)
    assert [j.cls for j in fits] == ["forecast"] * 3
    assert all(j.plan["horizon"] == 5 for j in fits)
    neither = judge_pairs(_rows(panel, [last - 4], horizons=(5,), folds=[1]), panel, Market.TSX, [5], 0.0,
                          DEFAULT_POLICY)
    assert neither == []


def test_only_usable_horizons_are_sampled():
    panel = _panel(symbols=10)
    rows = _rows(panel, [150, 160], horizons=(5, 10), folds=[1, 2])
    judged = judge_pairs(rows, panel, Market.TSX, [5], 0.0, DEFAULT_POLICY)
    forecast = [j for j in judged if j.cls == "forecast"]
    assert len(forecast) == 20  # the horizon-10 rows never give a plan
    assert all(j.plan["horizon"] == 5 for j in forecast)
    assert len([j for j in judged if j.cls == "volatility"]) == 20


def test_rows_without_a_calibrated_p_or_a_finite_quantile_are_not_sampled():
    panel = _panel(symbols=4)
    rows = _rows(panel, [150, 160, 170], horizons=(5,), folds=[0, 1, 2])
    rows.loc[rows["fold"] == 0, "p"] = math.nan
    rows.loc[(rows["fold"] == 2) & (rows["symbol"] == "S000"), "q90"] = math.inf
    judged = judge_pairs(rows, panel, Market.TSX, [5], 0.0, DEFAULT_POLICY)
    assert sorted({j.fold for j in judged}) == [1, 2]
    assert len([j for j in judged if j.cls == "forecast"]) == 4 + 3


@pytest.mark.parametrize("masked", ["nan", "unusable"])
def test_the_volatility_class_is_judged_whatever_the_models_calibration(masked):
    # R16: the volatility class reads no forecast, so rows with no P or quantiles, or at a horizon
    # that is not calibrated, still give it pairs; the forecast class gets none
    panel = _panel(symbols=10)
    rows = _rows(panel, [150, 160, 170], horizons=(5, 10), folds=[1, 2, 3])
    usable: tuple[int, ...] = (5, 10)
    if masked == "nan":
        rows[["q10", "q50", "q90", "p"]] = math.nan
    else:
        usable = ()
    judged = judge_pairs(rows, panel, Market.TSX, usable, 0.0, DEFAULT_POLICY)
    assert {j.cls for j in judged} == {"volatility"}
    assert len(judged) == 10 * 3  # one pair per symbol and day, whatever the number of horizons
    assert sorted({j.fold for j in judged}) == [1, 2, 3]
    assert all(j.plan["basis"] == "volatility" and j.plan["horizon"] == 21 for j in judged)


def test_fold_0_rows_are_never_sampled():
    panel = _panel(symbols=5)
    rows = _rows(panel, [150, 160], horizons=(5,), folds=[0, 1])  # fold 0 here even has a P
    for market, bench in ((Market.TSX, BENCH), (CRYPTO, "BTC")):
        p = panel if bench == BENCH else _panel(symbols=5, bench="BTC")
        judged = judge_pairs(rows, p, market, (5,), 0.0, DEFAULT_POLICY)
        assert judged and {j.fold for j in judged} == {1}


def test_sampling_takes_at_most_pairs_per_fold_rows_and_is_seeded():
    panel = _panel()
    rows = _rows(panel, list(range(100, 160, 2)), horizons=(5,))  # 10 days x 100 symbols per fold
    judged = judge_pairs(rows, panel, Market.TSX, [5], 0.0, DEFAULT_POLICY)
    per_fold = {f: sum(1 for j in judged if j.cls == "forecast" and j.fold == f) for f in (1, 2, 3)}
    assert per_fold == dict.fromkeys((1, 2, 3), PAIRS_PER_FOLD)
    again = judge_pairs(rows, panel, Market.TSX, [5], 0.0, DEFAULT_POLICY)
    assert [j.plan for j in again] == [j.plan for j in judged]


def test_a_coin_market_judges_its_rows_with_the_forecast_masked():
    panel = _panel(bench="BTC", symbols=10)
    rows = _rows(panel, [150, 170, 190], horizons=(7, 30), folds=[1, 2, 3])
    rows[["q10", "q50", "q90", "p"]] = math.nan  # R16: a coin plan needs neither, nor a usable horizon
    judged = judge_pairs(rows, panel, CRYPTO, (), 0.25, DEFAULT_POLICY)
    assert len(judged) == 10 * 3  # one pair per coin and day, at any horizon
    assert all(j.cls == "coin" for j in judged)
    assert all(j.plan["basis"] == "volatility" and j.plan["horizon"] == 21 for j in judged)
    assert sorted({j.fold for j in judged}) == [1, 2, 3]
    assert "forecast" not in verdicts(judged)


def test_the_plan_is_built_as_live_builds_it():
    # R6: the live builder, the live cost function, the trailing stop from the sample day's ATR, and a
    # break-even at the highest close of the 126 sessions up to the sample day
    panel = _panel(symbols=2)
    d = 200
    rows = _rows(panel, [d], horizons=(5,), folds=[1])
    found = judge_pairs(rows, panel, Market.US, [5], 1.5, DEFAULT_POLICY)
    judged = [j for s in ("S000", "S001") for c in ("forecast", "volatility") for j in found
              if j.cls == c and j.atr_pct == panel.atr_pct[s].iloc[d]]
    assert [j.cls for j in judged] == ["forecast", "volatility", "forecast", "volatility"]
    dates = [t.date() for t in panel.close.index]
    cost = 0.001 + 2 * 1.5 / 100  # a large company's spread and the currency fee both ways
    for n, symbol in enumerate(["S000", "S001"]):
        series = panel.close[symbol]
        price, atr = float(series.iloc[d]), float(panel.atr_pct[symbol].iloc[d])
        row = rows[rows["symbol"] == symbol].iloc[0]
        common = {
            "symbol": symbol, "day": dates[d], "closes": dict(zip(dates[:d + 1], series.iloc[:d + 1], strict=True)),
            "price": price, "stop": price * (1 - DEFAULT_POLICY.trail_atr * atr),
            "cost_cad": float(series.iloc[d - 125:d + 1].max()), "value_cad": price, "cost": cost,
            "atr_pct": atr, "trail_atr": DEFAULT_POLICY.trail_atr,  # R12: the stop trails as it is walked
        }
        bench = dict(zip(dates[:d + 1], panel.close[BENCH].iloc[:d + 1], strict=True))
        forecast = build_plan(**common, horizon=5, forecast=(row.q10, row.q50, row.q90), bench_closes=bench)
        volatility = build_plan(**common, horizon=None, forecast=None, bench_closes=None)
        assert judged[2 * n].plan == forecast and judged[2 * n + 1].plan == volatility
        assert judged[2 * n].atr_pct == atr
        for j in judged[2 * n: 2 * n + 2]:
            h = j.plan["horizon"]
            after = series.iloc[d + 1:d + 1 + h].to_numpy()
            walked = walk_exits(price, after, panel.atr_pct[symbol].iloc[d:d + 1 + h].to_numpy(),
                                sell_at=j.plan["sell_at"], trail_atr=DEFAULT_POLICY.trail_atr, cost=cost)
            assert j.end_price == after[-1] and j.max_close == after.max()
            if j.plan["sell_at"] is None:  # no order to judge
                assert j.without_order is None and j.with_order is None and j.stop_first is None
            else:
                assert (j.with_order, j.without_order) == (walked.with_order, walked.without_order)
                assert j.stop_first is walked.stop_first
    assert any(j.plan["sell_at"] is not None for j in judged)


def test_random_walk_plans_are_calibrated():
    panel = _panel()
    rows = _rows(panel, list(range(100, SESSIONS - 21, 3)), horizons=(21,))
    judged = judge_pairs(rows, panel, Market.TSX, [21], 0.0, DEFAULT_POLICY)
    volatility = verdicts(judged)["volatility"]
    assert volatility["pairs"] == 3 * PAIRS_PER_FOLD
    assert abs(volatility["touch_rate"] - TOUCH) * 100 <= TOLERANCE["touch"]
    assert abs(volatility["coverage"] - 0.80) * 100 <= TOLERANCE["coverage"]
    assert volatility["result"] != "fail"
    # R12: the simulated stop trails as `walk_exits` walks it, so the stated chance holds up
    assert volatility["stop_first_worst_bin"] * 100 <= TOLERANCE["bins"]
    assert volatility["checks"]["stop_first"] is True
    # R14: an order with no edge on a driftless walk is not measurably worse than holding
    assert volatility["order_days"] >= MIN_VALUE_DAYS
    assert volatility["checks"]["value"] is True


def test_on_a_driftless_walk_the_order_neither_gains_nor_loses():
    # R13: prices with no drift (a martingale) give an order that sells at a close no edge over holding
    # (optional stopping: both exits are bounded stopping times, and the cost comes off both). Sample
    # days 21 sessions apart give each symbol non-overlapping windows, so each pair's difference has
    # mean zero given everything before it and the differences are uncorrelated: the bound is 3
    # standard errors of the mean, std / sqrt(n), a 0.3% chance of failing by luck.
    panel = _panel(seed=3, martingale=True)
    rows = _rows(panel, list(range(100, SESSIONS - 21, 21)), horizons=(21,))
    judged = [j for j in judge_pairs(rows, panel, Market.TSX, [21], 0.0, DEFAULT_POLICY) if j.cls == "volatility"]
    gains = np.array([j.with_order - j.without_order for j in judged if j.with_order is not None])
    assert len(gains) >= 500
    bound = 3 * gains.std(ddof=1) / math.sqrt(len(gains))
    assert abs(gains.mean()) <= bound, (gains.mean(), bound)
    assert verdicts(judged)["volatility"]["order_gain"] == pytest.approx(gains.mean())


# ---- verdicts on hand-built pairs ----

def _judged(
    k: int,
    fold: int,
    *,
    cls: str = "forecast",
    in_range: bool | None = None,
    touched: bool | None = None,
    p_breakeven: float = 0.5,
    touched_breakeven: bool | None = None,
    p_stop_first: float = 0.4,
    stop_first: bool | None = None,
    gain: float = 0.01,
    breakeven: bool = True,
    day: date | None = None,
) -> Judged:
    """Pair k of 100 in a fold: 80% in range, 1 in 3 touches in every atr third, break-even and
    stop-first chances as stated, and an order that gains `gain`. Five pairs a sample day, so a
    fold of 100 pairs has 20 days."""
    plan = {
        "low": 90.0, "mid": 100.0, "high": 110.0, "sell_at": 108.0, "p_touch": TOUCH,
        "p_stop_first": p_stop_first, "breakeven": 120.0, "p_breakeven": p_breakeven,
        "basis": "forecast", "horizon": 21,
    }
    if not breakeven:
        plan["breakeven"] = plan["p_breakeven"] = None
    in_range = k % 5 != 0 if in_range is None else in_range
    end = 100.0 if in_range else 130.0
    return Judged(
        cls=cls, fold=fold, day=day or date(2024, 1, 1) + timedelta(days=100 * fold + k // 5),
        atr_pct=0.01 + k / 10_000, plan=plan, end_price=end, max_close=end,
        in_range=in_range,
        touched_sell_at=k % 3 == 0 if touched is None else touched,
        touched_breakeven=(
            None if not breakeven else k % 2 == 0 if touched_breakeven is None else touched_breakeven
        ),
        stop_first=(k % 5) < 2 if stop_first is None else stop_first,
        with_order=0.02 + gain, without_order=0.02,
    )


def _good(cls: str = "forecast", per_fold: int = 100, folds=(1, 2, 3), **kw) -> list[Judged]:
    return [_judged(k, f, cls=cls, **kw) for f in folds for k in range(per_fold)]


def test_all_checks_passing_is_a_pass():
    out = verdicts(_good())
    v = out["forecast"]
    assert v["pairs"] == 300 and v["folds"] == 3 and v["order_folds_not_worse"] == 3
    assert v["checks"] == {"range": True, "touch": True, "value": True, "breakeven": True, "stop_first": True}
    assert v["result"] == "pass"
    assert v["coverage"] == pytest.approx(0.8)
    assert len(v["touch_by_third"]) == 3
    assert v["order_gain"] == pytest.approx(0.01)
    assert v["breakeven_worst_bin"] == pytest.approx(0.0)
    assert set(out) == {"forecast"}


def test_a_class_with_too_few_pairs_has_no_verdict():
    out = verdicts(_good(cls="forecast") + _good(cls="volatility", per_fold=66))  # 198 pairs
    assert set(out) == {"forecast"}


def test_a_range_that_is_too_narrow_fails():
    judged = [_judged(k, f, in_range=k % 5 < 3) for f in (1, 2, 3) for k in range(100)]  # 60% in range
    v = verdicts(judged)["forecast"]
    assert v["coverage"] == pytest.approx(0.6)
    assert v["checks"]["range"] is False and v["result"] == "fail"


def test_a_touch_rate_off_in_one_third_gives_range_only():
    # 1 in 3 overall, but the middle third never touches and the stormy third 2 in 3 times
    judged = []
    for f in (1, 2, 3):
        for k in range(99):
            touched = (k % 3 == 0) if k < 33 else (False if k < 66 else k % 3 != 0)
            judged.append(_judged(k, f, touched=touched))
    v = verdicts(judged)["forecast"]
    assert v["touch_rate"] == pytest.approx(TOUCH)
    assert v["touch_by_third"][1] == 0.0
    assert v["checks"]["touch"] is False and v["result"] == "range_only"


def test_an_order_that_loses_money_gives_range_only():
    v = verdicts(_good(gain=-0.01))["forecast"]
    assert v["checks"]["range"] and v["checks"]["touch"]
    assert v["checks"]["value"] is False and v["result"] == "range_only"


def test_a_failed_break_even_or_stop_first_check_keeps_the_pass():
    off_breakeven = [_judged(k, f, touched_breakeven=k % 10 < 3) for f in (1, 2, 3) for k in range(100)]
    v = verdicts(off_breakeven)["forecast"]  # stated 50%, reached 30%
    assert v["breakeven_worst_bin"] == pytest.approx(0.2)
    assert v["checks"]["breakeven"] is False and v["result"] == "pass"

    off_stop = [_judged(k, f, stop_first=k % 10 < 2) for f in (1, 2, 3) for k in range(100)]
    v = verdicts(off_stop)["forecast"]  # stated 40%, happened 20%
    assert v["stop_first_worst_bin"] == pytest.approx(0.2)
    assert v["checks"]["stop_first"] is False and v["result"] == "pass"


def test_a_check_with_fewer_than_50_values_fails():
    judged = [_judged(k, f, breakeven=f == 1 and k < 49) for f in (1, 2, 3) for k in range(100)]
    v = verdicts(judged)["forecast"]  # only 49 pairs have a break-even
    assert v["checks"]["breakeven"] is False and v["breakeven_worst_bin"] is None
    assert v["result"] == "pass"


def _days(means: list[float], per_day: int = 10) -> list[Judged]:
    """`per_day` pairs on each sample day, the day's pairs spread +-0.005 around its mean `gain`."""
    out = []
    for n, mean in enumerate(means):
        day = date(2024, 1, 1) + timedelta(days=n)
        for k in range(per_day):
            out.append(_judged(k, 1 + n % 3, day=day, gain=mean + (0.005 if k % 2 else -0.005)))
    return out


SPREAD = [0.01 if n % 2 else -0.01 for n in range(30)]  # zero mean; sd 0.01 x sqrt(30 / 29)
SE = 0.01 * math.sqrt(30 / 29) / math.sqrt(30)  # its standard error over 30 days


@pytest.mark.parametrize(("means", "per_day", "t", "value"), [
    # about -1% a day with small noise: measurably worse than holding
    ([-0.01 + 0.0005 * ((7 * n) % 5 - 2) for n in range(30)], 10, -0.01 / (0.0005 * math.sqrt(2 * 30 / 29)) * math.sqrt(30), False),
    (SPREAD, 10, 0.0, True),  # zero-mean noise
    ([m - SE for m in SPREAD], 10, -1.0, True),  # mildly negative, inside the noise
    ([0.01 if n % 2 else 0.02 for n in range(10)], 26, None, False),  # 10 days cannot be judged
])
def test_the_value_check_fails_only_when_the_order_is_measurably_worse(means, per_day, t, value):
    v = verdicts(_days(means, per_day))["forecast"]
    assert v["order_days"] == len(means)
    assert v["order_gain"] == pytest.approx(float(np.mean(means)))
    if t is not None:
        assert v["order_t"] == pytest.approx(t, rel=1e-6)
    assert v["checks"]["value"] is value
    assert MIN_VALUE_DAYS == 20 and VALUE_T == -2.0


@pytest.mark.parametrize(("gain", "value"), [(0.0, True), (-0.001, False)])
def test_daily_means_with_no_spread_pass_only_at_or_above_zero(gain, value):
    judged = [_judged(k, 1 + n % 3, day=date(2024, 1, 1) + timedelta(days=n), gain=gain)
              for n in range(30) for k in range(10)]
    v = verdicts(judged)["forecast"]
    assert v["order_days"] == 30 and v["order_t"] is None
    assert v["checks"]["value"] is value


def test_the_fold_counts_are_kept_as_information():
    judged = _days([m - SE for m in SPREAD])
    v = verdicts(judged)["forecast"]
    assert v["folds"] == 3 and 0 <= v["order_folds_not_worse"] <= 3


# ---- the real exits ----

def test_the_order_sells_at_the_first_close_at_or_above_the_sell_at_price():
    # R13: the order exits at the close of the first day that closes at or above the sell-at price
    out = walk_exits(100.0, [104.0, 112.0, 95.0], [0.02] * 4, sell_at=110.0, trail_atr=2.5, cost=0.01)
    assert out.with_order == pytest.approx(0.11)  # the 112 close, not the 110 sell-at price
    assert out.without_order == pytest.approx(-0.06)  # the stop went 95 -> 98.8 -> 106.4, so 95 exits
    assert out.stop_first is False


def test_the_backtest_stop_trails_upward():
    out = walk_exits(100.0, [120.0, 113.0, 125.0], [0.02] * 4, sell_at=124.0, trail_atr=2.5, cost=0.0)
    # the stop rose to 114 after the 120 close, so 113 exits (a fixed stop at 95 would have reached 124)
    assert out.stop_first is True
    assert out.with_order == pytest.approx(0.13) and out.without_order == pytest.approx(0.13)


def test_without_a_sell_at_only_the_hold_is_walked():
    out = walk_exits(100.0, [101.0, 102.0, 103.0], [0.02] * 4, sell_at=None, trail_atr=2.5, cost=0.0)
    assert out.stop_first is None and out.with_order is None
    assert out.without_order == pytest.approx(0.03)  # no stop day: the re-check date's close


def test_a_sell_at_never_reached_and_no_stop_exits_at_the_last_close():
    out = walk_exits(100.0, [101.0, 99.0, 102.0], [0.02] * 4, sell_at=150.0, trail_atr=2.5, cost=0.0)
    assert out.stop_first is False
    assert out.with_order == pytest.approx(0.02) and out.without_order == pytest.approx(0.02)


def test_a_missing_close_after_the_sample_day_carries_the_last_one_forward():
    panel = _panel(symbols=1)
    d = 200
    close = panel.close.copy()
    close.iloc[d + 3, 0] = math.nan
    close.iloc[d + 5, 0] = math.nan  # the last close of a 5-session horizon
    judged = judge_pairs(_rows(panel, [d], horizons=(5,), folds=[1]), DailyPanel(close, panel.atr_pct, BENCH),
                         Market.TSX, [5], 0.0, DEFAULT_POLICY)
    assert judged[0].end_price == close.iloc[d + 4, 0]
    assert all(math.isfinite(j.end_price) and math.isfinite(j.max_close) for j in judged)
