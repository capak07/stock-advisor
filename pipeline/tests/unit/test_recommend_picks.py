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


def test_the_hold_is_chosen_by_ratio_not_by_return_or_probability():
    # the 20-day row has the higher q50 and P but a lower ratio (0.2 vs 0.267)
    rows = [row(63, 0.62, -0.05, 0.04, 0.10), row(20, 0.70, -0.10, 0.06, 0.20)]
    assert choose(rows, cost=0.001, sane=True).horizon == 63


def test_a_nan_probability_never_qualifies():
    assert choose([row(20, float("nan"), -0.02, 0.03, 0.06)], cost=0.001, sane=True) is None


def test_a_position_stop_is_never_more_than_fifteen_percent_below_entry():
    assert stop_price("swing", 100.0, 0.02) == pytest.approx(96.0)
    assert stop_price("position", 100.0, 0.02) == pytest.approx(94.0)
    assert stop_price("position", 100.0, 0.08) == pytest.approx(85.0)  # 3 × 8% = 24%, capped at 15%


def _pick(h, q50, symbol):
    return choose([row(h, 0.65, -0.02, q50, 0.06, symbol)], 0.001, True)


def test_each_list_keeps_ten_with_three_per_sector():
    choices = [_pick(20, 0.02 + i / 1000, f"E{i}") for i in range(5)]
    choices += [_pick(20, 0.01, f"T{i}") for i in range(12)]
    sectors = {f"E{i}": "Energy" for i in range(5)} | {f"T{i}": f"Sector{i}" for i in range(12)}
    ranked = rank_picks(choices, sectors)
    assert [c.symbol for c, _ in ranked] == ["E4", "E3", "E2"] + sorted(f"T{i}" for i in range(12))[:7]  # ties by symbol (string order)
    assert [r for _, r in ranked] == list(range(1, 11))


def test_stocks_without_a_sector_each_count_alone():
    choices = [_pick(20, 0.02 + i / 1000, f"N{i}") for i in range(5)]
    choices += [_pick(20, 0.02 + i / 1000, f"M{i}") for i in range(5)]
    sectors = {f"N{i}": None for i in range(5)} | {f"M{i}": float("nan") for i in range(5)}
    assert len(rank_picks(choices, sectors)) == 10  # none is capped as a shared group


def test_an_empty_string_is_a_sector_like_any_other():
    choices = [_pick(20, 0.02 + i / 1000, f"B{i}") for i in range(5)]
    ranked = rank_picks(choices, {f"B{i}": "" for i in range(5)})
    assert [c.symbol for c, _ in ranked] == ["B4", "B3", "B2"]


def test_each_style_has_its_own_ranks_limits_and_sector_caps():
    swing = [_pick(20, 0.02 + i / 1000, f"S{i}") for i in range(5)]
    position = [_pick(63, 0.02 + i / 1000, f"P{i}") for i in range(5)]
    sectors = {c.symbol: "Energy" for c in swing + position}
    ranked = rank_picks(swing + position, sectors)
    assert [(c.symbol, r) for c, r in ranked] == [
        ("S4", 1), ("S3", 2), ("S2", 3), ("P4", 1), ("P3", 2), ("P2", 3)]
    many = [_pick(20, 0.01, f"A{i}") for i in range(12)] + [_pick(63, 0.01, f"B{i}") for i in range(12)]
    ranked = rank_picks(many, {c.symbol: c.symbol for c in many})
    assert [r for c, r in ranked if c.style == "swing"] == list(range(1, 11))
    assert [r for c, r in ranked if c.style == "position"] == list(range(1, 11))


def test_held_stocks_and_jump_days_are_never_picked():
    rows = [row(20, 0.70, -0.02, 0.03, 0.06)]
    assert choose(rows, cost=0.001, sane=False) is None
