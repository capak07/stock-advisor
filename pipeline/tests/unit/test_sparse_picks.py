from dataclasses import replace

import pandas as pd
import pytest

from advisor.benchmark import policy_search
from advisor.benchmark.simulate import _candidates
from advisor.models import Market, PredictionRow
from advisor.policy import DEFAULT_POLICY, Policy
from advisor.recommend.picks import choose, top_by_horizon

EDGE = replace(DEFAULT_POLICY, top_n=1, min_edge=0.02)


def test_min_edge_defaults_to_zero_and_is_stored_only_when_set():
    assert DEFAULT_POLICY.min_edge == 0.0 and "min_edge" not in DEFAULT_POLICY.to_json()
    assert Policy.from_json(EDGE.to_json()) == EDGE and EDGE.to_json()["min_edge"] == 0.02
    for bad in (-0.01, 1.0, True, "0.02"):
        with pytest.raises(ValueError, match="min_edge"):
            Policy.from_json({**DEFAULT_POLICY.to_json(), "min_edge": bad})


def test_a_pick_must_clear_its_costs_by_the_margin():
    near = PredictionRow("A.TO", 21, -0.05, 0.015, 0.08, 0.49, "XIU.TO", "v1")
    clear = PredictionRow("A.TO", 21, -0.05, 0.03, 0.08, 0.49, "XIU.TO", "v1")
    top = top_by_horizon([near], 1)
    assert choose([near], 0.002, True, EDGE, top) is None  # 1.5% doesn't clear 0.2% + 2%
    assert choose([clear], 0.002, True, EDGE, top) is not None


def test_the_search_book_uses_the_margin_too():
    rows = pd.DataFrame({
        "symbol": ["A", "B"], "horizon": [21, 21], "p": [0.49, 0.48],
        "q10": [-0.05, -0.05], "q50": [0.015, 0.05], "q90": [0.10, 0.10], "dollar_volume_20": [5e7, 5e7],
    })
    assert list(_candidates(rows, replace(EDGE, top_n=2), Market.TSX, 1.5)["symbol"]) == ["B"]


def test_rank_rules_are_not_held_to_p_accuracy_in_the_search():
    period = {"max_drawdown": 0.1, "trades_per_month": 3.0}
    pooled = {"trades": 40, "claimed_gap_pts": 12.0, "mean_p": 0.59, "beat_rate": 0.47, "sharpe": 0.8}
    assert any("claimed" in f for f in policy_search.failures([period], pooled))
    assert policy_search.failures([period], pooled, rank_mode=True) == []


def test_the_search_tries_sparse_and_margin_rules():
    assert policy_search.GRID["top_n"] == (None, 1, 2, 3, 5, 10)
    assert policy_search.GRID["min_edge"] == (0.0, 0.02)
    assert "min_edge" in policy_search.STAGES[0]
