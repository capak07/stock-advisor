from datetime import datetime

import pytest

from advisor.daytrade.replay import HistoryStats, ReplayStats
from advisor.daytrade.rule import Plan
from advisor.daytrade.score import Scored, cost_pct, cost_r, rank, score
from advisor.models import ET, Market


def _hist(fired: int, avg_r: float) -> HistoryStats:
    return HistoryStats(sessions=59, fired=fired, target=0, stop=0, neither=0, avg_r=avg_r)


def _rep(avg_r: float) -> ReplayStats:
    return ReplayStats(10_000, 0.3, 0.3, 0.4, 0.5, avg_r, 1.0, 1.0, 1.0, 59)


def test_cost_pct() -> None:
    assert cost_pct(Market.US, 1.5, 0.10) == pytest.approx(3.10)
    assert cost_pct(Market.TSX, 1.5, 0.10) == pytest.approx(0.10)


def test_cost_r() -> None:
    plan = Plan(67.65, 63.77, 75.41, 3.88, datetime(2026, 10, 19, 15, 55, tzinfo=ET))
    assert cost_r(3.10, plan) == pytest.approx(0.5405, abs=1e-4)


def test_score_eligible_and_not() -> None:
    assert score(_hist(20, 0.8), _rep(0.7), 0.5) == (pytest.approx(0.3), pytest.approx(0.2), True)
    nh, nr, ok = score(_hist(19, 0.8), _rep(0.7), 0.5)
    assert nh is None and nr == pytest.approx(0.2) and not ok
    assert score(_hist(30, 0.4), _rep(0.7), 0.5)[2] is False
    assert score(_hist(30, 0.8), _rep(0.4), 0.5)[2] is False


def test_rank_top3_with_ties() -> None:
    items = [
        Scored(("A", "US"), 0.5, 0.1, True),
        Scored(("B", "US"), 0.5, 0.3, True),
        Scored(("C", "US"), 0.9, 0.1, True),
        Scored(("D", "US"), 0.2, 0.1, True),
        Scored(("E", "US"), 2.0, 2.0, False),
        Scored(("F", "US"), None, 1.0, False),
    ]
    assert rank(items) == {("C", "US"): 1, ("B", "US"): 2, ("A", "US"): 3}
