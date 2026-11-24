from dataclasses import replace
from datetime import date

import pytest

from advisor.runners.plan import gapped, plan_for, settle
from advisor.runners.rule import STARTING, Bar
from runner_data import AKAN_AFTER

HOLD = date(2026, 11, 30)


def test_akans_plan_from_the_real_open():
    plan = plan_for(1.92, 0.726, HOLD, STARTING)
    assert (plan.stop, plan.target, plan.r) == (1.44, 2.88, pytest.approx(0.48))


def test_the_signal_days_low_is_the_stop_when_it_is_closer():
    assert plan_for(0.60, 0.55, HOLD, STARTING).stop == 0.55            # 25% under would be 0.45


def test_an_open_under_the_signal_days_low_uses_the_floor_alone():      # Review Focus 1
    assert plan_for(0.70, 0.726, HOLD, STARTING).stop == 0.52           # 0.525 floored to the cent
    assert plan_for(0.70, 0.726, HOLD, replace(STARTING, stop_floor=None)) is None


def test_gap_rule_is_off_by_default():
    assert gapped(1.36, 1.92, STARTING) is False                        # +41%
    assert gapped(1.36, 1.92, replace(STARTING, gap_skip=0.15)) is True
    assert gapped(1.36, 1.50, replace(STARTING, gap_skip=0.15)) is False


def test_akan_reaches_its_target_on_the_third_day():
    out = settle(AKAN_AFTER, plan_for(1.92, 0.726, HOLD, STARTING))
    assert (out.status, out.exit_day, out.exit_price) == ("target", date(2026, 11, 18), 2.88)
    assert out.gross_r == pytest.approx(2.0)


def test_still_open_before_anything_is_hit():
    out = settle(AKAN_AFTER[:2], plan_for(1.92, 0.726, HOLD, STARTING))
    assert (out.status, out.exit_day, out.last_day, out.last_close) == ("open", None, date(2026, 11, 17), 2.05)


def test_a_bar_touching_both_counts_as_the_stop():
    out = settle([Bar(date(2026, 11, 16), 1.92, 3.00, 1.40, 2.50, 1)], plan_for(1.92, 0.726, HOLD, STARTING))
    assert (out.status, out.exit_price, out.gross_r) == ("stop", 1.44, pytest.approx(-1.0))


def test_a_gap_through_the_stop_fills_at_the_open_and_loses_more_than_1r():
    bars = [AKAN_AFTER[0], Bar(date(2026, 11, 17), 1.20, 1.30, 1.10, 1.25, 1)]
    out = settle(bars, plan_for(1.92, 0.726, HOLD, STARTING))
    assert (out.status, out.exit_price, out.gross_r) == ("stop", 1.20, pytest.approx(-1.5))


def test_a_gap_over_the_target_fills_at_the_open():
    bars = [AKAN_AFTER[0], Bar(date(2026, 11, 17), 3.20, 3.50, 3.10, 3.30, 1)]
    assert settle(bars, plan_for(1.92, 0.726, HOLD, STARTING)).exit_price == 3.20


def test_held_to_the_hold_by_date_sells_at_that_close():
    bars = [Bar(date(2026, 11, 16), 1.92, 2.00, 1.80, 1.95, 1), Bar(HOLD, 1.95, 2.10, 1.90, 2.04, 1)]
    out = settle(bars, plan_for(1.92, 0.726, HOLD, STARTING))
    assert (out.status, out.exit_day, out.exit_price, out.gross_r) == ("held", HOLD, 2.04, pytest.approx(0.25))
