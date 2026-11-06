from dataclasses import replace

import numpy as np
import pandas as pd

from advisor.benchmark.policy_search import failures, inner_periods, score, tune, tune_for_outer
from advisor.benchmark.simulate import DailyPanel, daily_panel
from advisor.model.dataset import load_market
from advisor.model.train import PARAMS, Fold, TrainConfig, make_folds
from advisor.model.variants import BASELINE
from advisor.models import Market
from advisor.policy import DEFAULT_POLICY
from model_data import write_market

START = pd.Timestamp("2024-01-01")
FAST = TrainConfig(horizons=(5, 63), rounds=40, params={**PARAMS, "min_data_in_leaf": 50, "num_threads": 2})


def market(samples=5, every=15):
    """Eight good names (p 0.61: five rise 2%/day, three fall 1%/day) and ten bad ones (p 0.59, all
    fall, with a better ratio): only a buy line of 0.60 keeps the bad ones out and the claim honest,
    whichever way the day's ten places are ranked."""
    days = pd.bdate_range(START, periods=samples * every)
    steps = np.arange(len(days))
    paths = {f"G{i}": 100 * (1.02 if i < 5 else 0.99) ** steps for i in range(8)}
    paths |= {f"L{i}": 100 * 0.99 ** steps for i in range(10)}
    close = pd.DataFrame(paths, index=days)
    close["SPY"] = 100.0
    pnl = DailyPanel(close, pd.DataFrame(0.02, index=days, columns=close.columns), "SPY")
    rows = []
    for day in days[::every]:
        for s in paths:
            good = s.startswith("G")
            q50 = 0.05 if good else 0.08
            rows.append({"day": day, "symbol": s, "sector": s, "dollar_volume_20": 2e7, "horizon": 5, "fold": 1,
                         "y": 0.0, "q10": q50 - 0.1, "q50": q50, "q90": q50 + 0.1, "p_raw": 0.6,
                         "p": 0.61 if good else 0.59})
    return pd.DataFrame(rows), pnl, [Fold(days[0], days[-1] + pd.Timedelta(days=1))]


def test_the_search_is_staged_and_deterministic():
    pred, pnl, periods = market()
    tuned = tune(pred, pnl, Market.TSX, 1.5, periods)
    assert tuned.policy is not None and tuned.policy.p_buy == 0.60
    assert tuned.tried == (42 + 3 * 6) + 80 + 5  # stage 1 also tries top_n 3, 5, 10 once each (spec §11)
    assert tuned.objective > 0
    assert tune(pred, pnl, Market.TSX, 1.5, periods) == tuned


def test_nothing_feasible_returns_no_policy_and_says_why():
    pred, pnl, periods = market(samples=2)
    tuned = tune(pred, pnl, Market.TSX, 1.5, periods)
    assert tuned.policy is None and tuned.objective is None
    assert "no stage-1 combination met the limits" in tuned.reason and "needs 30" in tuned.reason


def ok(**kw):
    return {"trades": 12, "trades_per_month": 10.0, "max_drawdown": 0.1, "sharpe": 1.0, "claimed_gap_pts": 2.0} | kw


def test_each_hard_limit_rejects():
    assert failures([ok(), ok()], ok(trades=40)) == []
    assert failures([ok()], ok(trades=12)) == ["only 12 trades (needs 30)"]
    assert failures([ok(), ok(max_drawdown=0.31)], ok(trades=40)) == ["period 2 drew down 31% (limit 25%)"]
    assert failures([ok(trades_per_month=24.0)], ok(trades=40)) == ["period 1 made 24 trades a month (limit 20)"]
    claimed = ok(trades=40, claimed_gap_pts=9.0, mean_p=0.64, beat_rate=0.55)
    assert failures([ok()], claimed) == ["picks claimed 64% but beat 55% (limit 5 points)"]


def test_a_nan_never_passes_a_limit():
    nan = float("nan")
    assert failures([ok()], ok(trades=40, sharpe=nan)) == ["net Sharpe couldn't be measured"]
    assert failures([ok(max_drawdown=nan)], ok(trades=40)) == ["period 1 drawdown couldn't be measured"]
    assert failures([ok()], ok(trades=40, claimed_gap_pts=None)) == ["picks' claimed P couldn't be checked"]


def test_score_pools_the_periods():
    pred, pnl, (period,) = market()
    half = period.start + (period.end - period.start) / 2
    s = score(pred, pnl, replace(DEFAULT_POLICY, p_buy=0.60), Market.TSX, 1.5,
              [Fold(period.start, half), Fold(half, period.end)])
    assert len(s["per_period"]) == 2
    assert s["pooled"]["trades"] == sum(p["trades"] for p in s["per_period"]) == 40
    assert s["feasible"] and s["objective"] == s["pooled"]["sharpe"]


def test_tuning_never_reads_the_outer_period(tmp_path):
    write_market(tmp_path, Market.TSX, stocks=40, days=1100)
    data, pnl = load_market(tmp_path, Market.TSX), daily_panel(tmp_path, Market.TSX)
    outer = make_folds(pd.DatetimeIndex(data.rows["day"].unique()), TrainConfig())[2]
    before = tune_for_outer(data, BASELINE, FAST, pnl, Market.TSX, 1.5, outer)
    # a policy that trades on everything, so the check isn't vacuous
    anything = replace(DEFAULT_POLICY, p_buy=0.0, p_sell=-1.0)
    pred, periods = inner_periods(data, BASELINE, FAST, outer)
    trades = score(pred, pnl, anything, Market.TSX, 1.5, periods)["pooled"]["trades"]
    assert trades > 30 and periods[-1].end == outer.start

    rows, rng = data.rows.copy(), np.random.default_rng(0)
    start = data.calendar.searchsorted(outer.start)
    position = data.calendar.searchsorted(pd.DatetimeIndex(rows["day"]))
    for h in FAST.horizons:
        late = position + h >= start
        rows.loc[late, f"y_{h}"] = rng.normal(size=late.sum())
    later = rows["day"] >= outer.start
    rows.loc[later, data.features] = rng.normal(size=(later.sum(), len(data.features)))
    close = pnl.close.copy()
    close.loc[close.index >= outer.start] = rng.uniform(1, 200, size=close.loc[close.index >= outer.start].shape)
    noisy_data, noisy_pnl = replace(data, rows=rows), replace(pnl, close=close)

    assert tune_for_outer(noisy_data, BASELINE, FAST, noisy_pnl, Market.TSX, 1.5, outer) == before
    pred2, periods2 = inner_periods(noisy_data, BASELINE, FAST, outer)
    again = score(pred2, noisy_pnl, anything, Market.TSX, 1.5, periods2)
    first = score(pred, pnl, anything, Market.TSX, 1.5, periods)
    assert again["pooled"] == first["pooled"]
