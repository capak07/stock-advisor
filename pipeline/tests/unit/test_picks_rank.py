from dataclasses import replace

import pytest

from advisor.models import PredictionRow
from advisor.policy import DEFAULT_POLICY, Policy
from advisor.recommend.picks import choose, top_by_horizon

RANK = replace(DEFAULT_POLICY, top_n=2)


UNSET = object()


def row(symbol, p, q50=0.03, h=21, score=UNSET):
    # the raw score follows P unless a test says otherwise, as it does for a real model
    return PredictionRow(symbol, h, q50 - 0.05, q50, q50 + 0.05, p, "XIU.TO", "v1", p if score is UNSET else score)


def test_a_policy_without_top_n_loads_as_today():
    stored = DEFAULT_POLICY.to_json()
    assert "top_n" not in stored  # today's stored policies have no such key
    assert Policy.from_json(stored) == DEFAULT_POLICY and DEFAULT_POLICY.top_n is None


def test_top_n_round_trips_and_refuses_zero():
    assert Policy.from_json(RANK.to_json()) == RANK and RANK.to_json()["top_n"] == 2
    for bad in (0, -1, 2.5, True, "3"):
        with pytest.raises(ValueError, match="top_n"):
            Policy.from_json({**DEFAULT_POLICY.to_json(), "top_n": bad})
    assert Policy.from_json({**DEFAULT_POLICY.to_json(), "top_n": None}) == DEFAULT_POLICY


def test_only_forecast_stocks_are_ranked():
    rows = [row("A.TO", 0.49), row("B.TO", 0.48), row("C.TO", 0.47), row("D.TO", 0.40, h=63)]
    top = top_by_horizon(rows, 2)
    assert top == {21: {"A.TO": (1, 3), "B.TO": (2, 3)}, 63: {"D.TO": (1, 1)}}


def test_ties_rank_by_symbol():
    top = top_by_horizon([row("B.TO", 0.45), row("A.TO", 0.45), row("C.TO", 0.45)], 2)
    assert top[21] == {"A.TO": (1, 3), "B.TO": (2, 3)}  # the same raw score too: only then the alphabet


def test_tied_p_is_ranked_by_the_raw_score():
    rows = [row("A.TO", 0.53, score=0.01), row("B.TO", 0.53, score=0.03), row("C.TO", 0.53, score=0.02)]
    assert top_by_horizon(rows, 2) == {21: {"B.TO": (1, 3), "C.TO": (2, 3)}}


def test_a_row_without_a_score_never_takes_a_place():
    rows = [row("A.TO", 0.60, score=None), row("B.TO", 0.50, score=float("nan")), row("C.TO", 0.40, score=0.01)]
    assert top_by_horizon(rows, 2) == {21: {"C.TO": (1, 1)}}
    assert PredictionRow("A.TO", 21, -0.02, 0.03, 0.08, 0.6, "XIU.TO", "v1").score is None  # older callers


def test_rank_mode_takes_the_top_n_that_clear_costs():
    rows = [row("A.TO", 0.49), row("B.TO", 0.48, q50=0.001), row("C.TO", 0.47)]
    top = top_by_horizon(rows, 2)
    a = choose([rows[0]], 0.002, True, RANK, top)
    assert a is not None and (a.score_rank, a.score_of) == (1, 3)  # P 0.49 < 0.58, still a pick
    assert choose([rows[1]], 0.002, True, RANK, top) is None  # in the top 2, but q50 under cost
    assert choose([rows[2]], 0.002, True, RANK, top) is None  # third: not in the top 2
    assert choose([rows[0]], 0.002, True, DEFAULT_POLICY) is None  # P mode: under 0.58
    p_pick = choose([row("A.TO", 0.60)], 0.002, True, DEFAULT_POLICY)
    assert p_pick is not None and p_pick.score_rank is None and p_pick.score_of is None


def test_verdicts_and_holding_actions_keep_the_p_rule_under_a_rank_policy():
    from advisor.recommend.picks import p_rule
    assert p_rule(RANK) == DEFAULT_POLICY and p_rule(DEFAULT_POLICY) is DEFAULT_POLICY


def test_a_stock_that_failed_its_sanity_checks_never_takes_a_place():
    from advisor.recommend.picks import rankable
    population = {"A.TO": [row("A.TO", 0.60)], "B.TO": [row("B.TO", 0.49)], "C.TO": [row("C.TO", 0.48)]}
    top = top_by_horizon(rankable(population, {"A.TO": False, "B.TO": True, "C.TO": True}), 2)
    assert top[21] == {"B.TO": (1, 2), "C.TO": (2, 2)}
