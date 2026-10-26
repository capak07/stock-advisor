import pytest

from advisor.models import PredictionRow
from advisor.recommend.picks import best_horizon, choose, rank_picks, stop_price


def row(h, p, q10, q50, q90, symbol="AAA"):
    return PredictionRow(symbol, h, q10, q50, q90, p, "SPY", "v1")


def test_the_best_ratio_qualifying_horizon_is_the_hold():
    rows = [row(10, 0.60, -0.02, 0.01, 0.03), row(63, 0.62, -0.05, 0.04, 0.10), row(126, 0.57, -0.1, 0.2, 0.3)]
    c = choose(rows, cost=0.001, sane=True)
    assert (c.horizon, c.style) == (63, "position")  # 126 has the best ratio but P is below 0.58
    assert choose(rows, cost=0.05, sane=True) is None  # q50 never clears a 5% cost
    assert choose(rows, cost=0.001, sane=False) is None  # failed sanity checks: never a pick
    assert best_horizon(rows).horizon_days == 126


def test_a_position_stop_is_never_more_than_fifteen_percent_below_entry():
    assert stop_price("swing", 100.0, 0.02) == pytest.approx(96.0)
    assert stop_price("position", 100.0, 0.02) == pytest.approx(94.0)
    assert stop_price("position", 100.0, 0.08) == pytest.approx(85.0)  # 3 × 8% = 24%, capped at 15%


def test_each_list_keeps_ten_with_three_per_sector():
    choices = [choose([row(20, 0.65, -0.02, 0.02 + i / 1000, 0.06, f"E{i}")], 0.001, True) for i in range(5)]
    choices += [choose([row(20, 0.65, -0.02, 0.01, 0.06, f"T{i}")], 0.001, True) for i in range(12)]
    sectors = {f"E{i}": "Energy" for i in range(5)} | {f"T{i}": f"Sector{i}" for i in range(12)}
    ranked = rank_picks(choices, sectors)
    assert len(ranked) == 10
    assert [c.symbol for c, _ in ranked[:3]] == ["E4", "E3", "E2"]
    assert [r for _, r in ranked] == list(range(1, 11))


def test_held_stocks_and_jump_days_are_never_picked():
    rows = [row(20, 0.70, -0.02, 0.03, 0.06)]
    assert choose(rows, cost=0.001, sane=False) is None
