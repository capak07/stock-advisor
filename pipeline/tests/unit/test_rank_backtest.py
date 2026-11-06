from dataclasses import replace

import numpy as np
import pandas as pd

from advisor.benchmark import policy_search
from advisor.model.backtest import gate, in_top_n
from advisor.policy import DEFAULT_POLICY

RANK = replace(DEFAULT_POLICY, top_n=2)


def _frame():
    day = pd.Timestamp("2026-01-05")
    return pd.DataFrame({
        "day": [day] * 5 + [day + pd.Timedelta(days=14)] * 2,
        "symbol": ["A", "B", "C", "D", "E", "A", "B"],
        "horizon": [21, 21, 21, 21, 63, 21, 21],
        "p": [0.47, 0.49, 0.48, np.nan, 0.40, 0.30, 0.31],
    })


def test_rank_mode_simulates_the_top_n():
    top = in_top_n(_frame(), 2)
    # day 1, horizon 21: B (0.49), C (0.48) — the NaN never ranks; horizon 63: E alone; day 2: B, A
    assert top.tolist() == [False, True, True, False, True, True, True]


def test_the_search_tries_each_top_n_once():
    stage = policy_search.STAGES[0]
    assert "top_n" in stage and policy_search.GRID["top_n"] == (None, 3, 5, 10)
    policies = policy_search.stage_policies(DEFAULT_POLICY, stage)
    ranked = [p for p in policies if p.top_n is not None]
    assert {p.p_buy for p in ranked} == {policy_search.GRID["p_buy"][0]}
    per_n = len(policy_search.GRID["rule"]) * len(policy_search.GRID["horizons"])
    assert len(ranked) == 3 * per_n
    assert len([p for p in policies if p.top_n is None]) == len(policy_search.GRID["p_buy"]) * per_n


def _metrics(n, net, claimed=0.59, beat=0.45):
    return {"all": {"picks": n, "mean_net_pct": net, "mean_p": claimed, "beat_rate": beat}}


def test_the_rank_gate_ignores_p_accuracy_but_needs_30_profitable_picks():
    ok, why = gate(_metrics(40, 1.6), 9.0, rank_mode=True)
    assert ok and why == "40 backtest picks gained 1.60% after costs"
    assert gate(_metrics(29, 1.6), 1.0, rank_mode=True) == (False, "only 29 backtest picks (needs 30)")
    assert not gate(_metrics(40, -0.2), 1.0, rank_mode=True)[0]
    assert not gate(_metrics(40, 1.6), 1.0)[0]  # P mode still checks the claimed P


def test_a_jump_day_never_takes_a_top_n_place_in_the_search():
    from advisor.benchmark.simulate import _candidates
    from advisor.models import Market
    rows = pd.DataFrame({
        "symbol": ["J", "A", "B"], "horizon": [21, 21, 21], "p": [0.60, 0.49, 0.48],
        "q10": [-0.05] * 3, "q50": [0.05] * 3, "q90": [0.10] * 3, "dollar_volume_20": [5e7] * 3,
        "jump_5d": [1.0, 0.0, 0.0],
    })
    picked = _candidates(rows, RANK, Market.TSX, 1.5)
    assert sorted(picked["symbol"]) == ["A", "B"]  # J's jump keeps it out of the ranking itself
