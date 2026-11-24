from datetime import date

import pytest

from advisor.models import DailyBar
from advisor.runners.cost import cost_r, spread_pct, two_day_spread
from advisor.runners.rule import series_of
from runner_data import SOURCE, weekdays


def bar(day: date, high: float, low: float) -> DailyBar:
    return DailyBar(symbol="AKAN", day=day, open=low, high=high, low=low, close=high, volume=100_000.0,
                    source=SOURCE)


def test_two_day_spread_matches_corwin_schultz():
    assert two_day_spread(1.04, 1.00, 1.05, 1.01) == pytest.approx(1.5469, abs=1e-4)
    assert two_day_spread(1.04, 1.00, 1.04, 1.00) == pytest.approx(3.9216, abs=1e-4)
    assert two_day_spread(0.73, 0.643, 1.70, 0.726) == 0.0              # AKAN's ignition day: why D is not used


def test_spread_is_the_median_of_the_sessions_before_with_a_floor_and_a_cap():
    steady = series_of([bar(d, high=1.04, low=1.00) for d in weekdays(30)])
    assert spread_pct(steady, 29) == pytest.approx(3.9216, abs=1e-4)
    assert spread_pct(series_of([bar(d, high=1.0, low=1.0) for d in weekdays(30)]), 29) == 1.0
    assert spread_pct(series_of([bar(d, high=2.0, low=1.0) for d in weekdays(30)]), 29) == 10.0
    assert spread_pct(steady, 0) == 1.0


A = (1.04, 1.00)  # a 4% day: two in a row read as 3.92%
B = (1.02, 1.00)  # a 2% day: two in a row read as 1.98%


def ranges(*days: tuple[float, float]):
    return series_of([bar(d, high=high, low=low) for d, (high, low) in zip(weekdays(len(days)), days, strict=True)])


def test_the_spread_is_a_median_so_one_outlier_pair_does_not_move_it():
    days = [A] * 30
    days[9] = (1.50, 1.00)  # session 9 is the window's first: only the pair (9, 10) sees it
    pairs = [two_day_spread(*days[j - 1], *days[j]) for j in range(10, 29)]
    assert spread_pct(ranges(*days), 29) == pytest.approx(two_day_spread(*A, *A))
    assert sum(pairs) / len(pairs) < two_day_spread(*A, *A) - 0.1  # the mean would have moved


def test_the_signal_day_itself_is_left_out():
    # with the pair (1, 2) the median would be the mean of two different spreads
    assert spread_pct(ranges(A, A, B), 2) == pytest.approx(two_day_spread(*A, *A))
    assert two_day_spread(*A, *B) != pytest.approx(two_day_spread(*A, *A))


def test_a_pair_older_than_20_sessions_is_ignored():
    # the window before session 21 holds the pairs (1, 2) to (19, 20): 9 of A, 1 mixed and 9 of B,
    # so its median is B; the pair (0, 1) would add a tenth A and move it halfway to A
    spread = spread_pct(ranges(*[A] * 11, *[B] * 11), 21)
    assert spread == pytest.approx(two_day_spread(*B, *B))
    assert two_day_spread(*A, *B) < two_day_spread(*B, *B) < two_day_spread(*A, *A)


def test_cost_in_r():
    assert cost_r(3.0, 1.92, 1.44) == pytest.approx(0.12)
