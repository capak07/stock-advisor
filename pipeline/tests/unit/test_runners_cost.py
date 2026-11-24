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


def test_cost_in_r():
    assert cost_r(3.0, 1.92, 1.44) == pytest.approx(0.12)
