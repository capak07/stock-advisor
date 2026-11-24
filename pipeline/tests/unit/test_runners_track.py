from datetime import date, timedelta

import pytest

from advisor.runners.rule import STARTING, Bar, series_of
from advisor.runners.track import NO_PRICES_HELD, NO_PRICES_SIGNAL, track
from runner_data import AKAN, AKAN_AFTER, akan, daily, more_flat_days

SIGNAL_DAY = date(2026, 11, 13)
SIGNAL = (AKAN["close"], AKAN["low"])


def weekdays_through(end: date) -> list[date]:
    """Every weekday from 2026-08-03 to `end`: the sessions, with no holidays."""
    day, out = date(2026, 8, 3), []
    while day <= end:
        if day.weekday() < 5:
            out.append(day)
        day += timedelta(days=1)
    return out


SESSIONS = weekdays_through(date(2027, 3, 31))


def unadjusted(bar: Bar, ratio: int = 10) -> Bar:
    """The bar as it traded after a 1-for-`ratio` reverse split Yahoo has not yet applied to the history."""
    return bar._replace(open=bar.open * ratio, high=bar.high * ratio, low=bar.low * ratio, close=bar.close * ratio,
                        volume=bar.volume / ratio)


def run(bars, through):
    return track(series_of(bars), SIGNAL_DAY, *SIGNAL, SESSIONS, STARTING, through)


def test_akan_enters_and_reaches_its_target():
    got = run([*akan(), *(daily("AKAN", b) for b in AKAN_AFTER)], date(2026, 11, 18))
    assert (got.status, got.entry_day, got.reason, got.split_wait) == ("target", date(2026, 11, 16), None, False)
    assert (got.plan.entry, got.plan.stop, got.plan.target, got.plan.hold_by) == (1.92, 1.44, 2.88, date(2026, 11, 27))
    assert (got.outcome.exit_price, got.outcome.gross_r) == (2.88, pytest.approx(2.0))


def test_an_unadjusted_reverse_split_bar_is_not_settled_on():  # the probe: it booked a 35.79R target at 19.10
    bars = [*akan(), daily("AKAN", AKAN_AFTER[0]), daily("AKAN", unadjusted(AKAN_AFTER[1]))]
    got = run(bars, date(2026, 11, 17))
    assert (got.status, got.split_wait, got.outcome.exit_price) == ("open", True, None)
    assert (got.outcome.last_day, got.outcome.last_close) == (date(2026, 11, 16), 2.21)


def test_a_trade_held_back_by_a_split_closes_at_its_last_trusted_close_5_sessions_past_its_hold_by():
    bars = [*akan(), daily("AKAN", AKAN_AFTER[0]), daily("AKAN", unadjusted(AKAN_AFTER[1]))]
    bars = more_flat_days(bars, 20)  # Yahoo never adjusts the history
    assert run(bars, date(2026, 12, 3)).status == "open"  # the hold-by (11-27) + 4 sessions
    got = run(bars, date(2026, 12, 4))
    assert (got.status, got.reason, got.outcome.exit_day, got.outcome.exit_price) == ("held", NO_PRICES_HELD, date(2026, 11, 16), 2.21)
    assert got.split_wait is False


def test_a_split_suspect_entry_bar_keeps_the_signal_waiting_then_the_no_prices_rule_skips_it():
    quiet_split = Bar(date(2026, 11, 16), 19.20, 20.00, 18.00, 19.00, 1_000_000.0)  # 14x D's close on light volume
    bars = [*akan(), daily("AKAN", quiet_split)]
    got = run(bars, date(2026, 11, 16))
    assert (got.status, got.entry_day, got.split_wait) == ("waiting", None, True)
    got = run(bars, date(2026, 11, 20))
    assert (got.status, got.reason, got.split_wait) == ("skipped", NO_PRICES_SIGNAL, False)


def test_the_entry_bar_must_come_within_5_sessions_of_the_signal():
    late = Bar(date(2026, 11, 23), 1.92, 2.38, 1.70, 2.21, 99_663_300.0)  # 6 sessions after Fri 11-13
    got = run([*akan(), daily("AKAN", late)], date(2026, 11, 23))
    assert (got.status, got.reason, got.entry_day) == ("skipped", NO_PRICES_SIGNAL, None)
    fifth = late._replace(day=date(2026, 11, 20))
    assert run([*akan(), daily("AKAN", fifth)], date(2026, 11, 20)).status == "open"


def test_a_halt_across_the_hold_by_closes_at_the_last_close_before_it():
    # entered Mon 11-16, then no bar until 6 sessions after the hold-by (Fri 11-27)
    back = Bar(date(2026, 12, 7), 2.10, 2.20, 2.00, 2.05, 1_000_000.0)
    bars = [*akan(), daily("AKAN", AKAN_AFTER[0]), daily("AKAN", back)]
    got = run(bars, date(2026, 12, 7))
    assert (got.status, got.reason, got.outcome.exit_day, got.outcome.exit_price) == ("held", NO_PRICES_HELD, date(2026, 11, 16), 2.21)
    # a bar within 5 sessions after the hold-by still settles it at that bar
    soon = back._replace(day=date(2026, 12, 4))
    got = run([*akan(), daily("AKAN", AKAN_AFTER[0]), daily("AKAN", soon)], date(2026, 12, 4))
    assert (got.status, got.reason, got.outcome.exit_day, got.outcome.exit_price) == ("held", None, date(2026, 12, 4), 2.05)


def test_no_bars_after_the_signal_waits_5_sessions_then_skips():
    assert run(akan(), date(2026, 11, 19)).status == "waiting"
    assert track(None, SIGNAL_DAY, *SIGNAL, SESSIONS, STARTING, date(2026, 11, 20)).reason == NO_PRICES_SIGNAL


def test_a_hold_by_past_the_known_sessions_is_still_waiting():
    got = track(series_of([*akan(), daily("AKAN", AKAN_AFTER[0])]), SIGNAL_DAY, *SIGNAL,
                weekdays_through(date(2026, 11, 20)), STARTING, date(2026, 11, 20))
    assert (got.status, got.entry_day, got.outcome) == ("waiting", date(2026, 11, 16), None)
