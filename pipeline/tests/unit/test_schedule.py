from datetime import UTC, date, datetime, time

import pytest

from advisor.models import Market, RunKind
from advisor.schedule import (
    expected_last_session,
    freshness_floor,
    market_close_et,
    missed_run_kind,
    previous_sessions,
    resolve_run_kind,
    sessions_after,
)


def utc(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        ("2026-10-14T12:15:00", RunKind.PRE_OPEN),     # EDT 08:15 ET
        ("2026-10-14T13:15:00", None),                 # EDT 09:15 ET (the EST cron)
        ("2026-10-14T12:40:00", RunKind.PRE_OPEN),     # 25 min late: still inside window
        ("2026-10-14T12:50:00", None),                 # 35 min late: outside window
        ("2026-10-14T19:15:00", RunKind.PRE_CLOSE),    # EDT 15:15 ET
        ("2026-10-14T16:15:00", None),                 # early-close cron on a normal day
        ("2026-12-02T13:15:00", RunKind.PRE_OPEN),     # EST 08:15 ET
        ("2026-12-02T12:15:00", None),                 # EST 07:15 ET (the EDT cron)
        ("2026-12-02T20:15:00", RunKind.PRE_CLOSE),    # EST 15:15 ET
        ("2026-10-17T12:15:00", None),                 # Saturday
        ("2026-10-12T12:15:00", RunKind.PRE_OPEN),     # Canadian Thanksgiving: the NYSE trades
        ("2026-10-12T19:15:00", RunKind.PRE_CLOSE),
        ("2026-11-26T13:15:00", RunKind.PRE_OPEN),     # US Thanksgiving: the TSX trades
        ("2026-11-26T17:15:00", None),                 # no market closes early that day
        ("2026-11-26T20:15:00", RunKind.PRE_CLOSE),    # the TSX closes at 16:00
        ("2026-11-27T13:15:00", RunKind.PRE_OPEN),
        ("2026-11-27T17:15:00", RunKind.EARLY_CLOSE),  # the NYSE closes at 13:00
        ("2026-11-27T20:15:00", RunKind.PRE_CLOSE),    # the TSX still closes at 16:00
        ("2026-12-24T17:15:00", RunKind.EARLY_CLOSE),  # both close at 13:00
        ("2026-12-24T20:15:00", None),                 # both already closed
        ("2026-12-25T13:15:00", None),                 # Christmas: both closed
    ],
)
def test_resolve_run_kind(now, expected):
    assert resolve_run_kind(utc(now)) == expected


def test_market_close_et_reports_each_markets_own_calendar():
    assert market_close_et(date(2026, 10, 14)) == time(16, 0)
    assert market_close_et(date(2026, 11, 27)) == time(13, 0)
    assert market_close_et(date(2026, 11, 26)) is None
    assert market_close_et(date(2026, 11, 26), Market.TSX) == time(16, 0)
    assert market_close_et(date(2026, 11, 27), Market.TSX) == time(16, 0)
    assert market_close_et(date(2026, 10, 12), Market.TSX) is None
    assert market_close_et(date(2026, 12, 24), Market.TSX) == time(13, 0)


@pytest.mark.parametrize(
    ("now", "resolved", "missed"),
    [
        ("2026-10-14T12:05:00", RunKind.PRE_OPEN, None),  # 08:05 ET: earliest accepted
        ("2026-10-14T12:04:00", None, None),              # 08:04 ET: too early, not missed
        ("2026-10-14T12:45:00", RunKind.PRE_OPEN, None),  # 08:45 ET: latest accepted
        ("2026-10-14T12:46:00", None, RunKind.PRE_OPEN),  # 08:46 ET: own cron running late
        ("2026-10-14T13:14:00", None, RunKind.PRE_OPEN),  # 09:14 ET: still own cron, late
        ("2026-10-14T13:15:00", None, None),              # 09:15 ET: the EST decoy cron
        ("2026-12-02T12:15:00", None, None),              # 07:15 EST: the EDT decoy cron
        ("2026-12-24T20:15:00", None, None),              # 15:15 ET when both closed at 13:00
        ("2026-11-26T13:46:00", None, RunKind.PRE_OPEN),  # US holiday: the TSX slot was missed
    ],
)
def test_missed_run_kind_flags_only_a_slots_own_late_cron(now, resolved, missed):
    assert resolve_run_kind(utc(now)) == resolved
    assert missed_run_kind(utc(now)) == missed


def test_missed_run_kind_is_none_on_closed_days():
    assert missed_run_kind(utc("2026-10-17T12:46:00")) is None  # Saturday
    assert missed_run_kind(utc("2026-12-25T13:46:00")) is None  # Christmas


def test_previous_sessions_skips_each_markets_holidays_and_is_ascending():
    assert previous_sessions(date(2026, 11, 27), 3) == [
        date(2026, 11, 24), date(2026, 11, 25), date(2026, 11, 27),
    ]
    assert previous_sessions(date(2026, 10, 13), 3, Market.TSX) == [
        date(2026, 10, 8), date(2026, 10, 9), date(2026, 10, 13),
    ]


@pytest.mark.parametrize(
    ("kind", "now", "market", "last_session", "floor"),
    [
        (RunKind.PRE_OPEN, "2026-10-14T12:15:00", Market.US, date(2026, 10, 13), date(2026, 10, 12)),
        (RunKind.PRE_CLOSE, "2026-10-14T19:15:00", Market.US, date(2026, 10, 14), date(2026, 10, 13)),
        (RunKind.PRE_OPEN, "2026-10-19T12:15:00", Market.US, date(2026, 10, 16), date(2026, 10, 15)),
        (RunKind.PRE_OPEN, "2026-11-27T13:15:00", Market.US, date(2026, 11, 25), date(2026, 11, 24)),
        # The day after Canadian Thanksgiving: the NYSE traded on 10-12, the TSX did not.
        (RunKind.PRE_OPEN, "2026-10-13T12:15:00", Market.US, date(2026, 10, 12), date(2026, 10, 9)),
        (RunKind.PRE_OPEN, "2026-10-13T12:15:00", Market.TSX, date(2026, 10, 9), date(2026, 10, 8)),
        (RunKind.PRE_OPEN, "2026-10-14T12:15:00", Market.TSX, date(2026, 10, 13), date(2026, 10, 9)),
        # A pre-close run on US Thanksgiving: only the TSX has a session today.
        (RunKind.PRE_CLOSE, "2026-11-26T20:15:00", Market.US, date(2026, 11, 25), date(2026, 11, 24)),
        (RunKind.PRE_CLOSE, "2026-11-26T20:15:00", Market.TSX, date(2026, 11, 26), date(2026, 11, 25)),
    ],
)
def test_expected_last_session_and_freshness_floor(kind, now, market, last_session, floor):
    assert expected_last_session(kind, utc(now), market) == last_session
    assert freshness_floor(kind, utc(now), market=market) == floor


def test_market_defaults_to_us():
    now = utc("2026-10-13T12:15:00")
    assert freshness_floor(RunKind.PRE_OPEN, now) == freshness_floor(
        RunKind.PRE_OPEN, now, market=Market.US
    )


def test_exit_by_counts_the_markets_own_trading_days():
    # US: Wed 2026-11-25, then Thanksgiving (26th), Fri 27th, Mon 30th
    assert sessions_after(Market.US, date(2026, 11, 25), 2) == date(2026, 11, 30)
    # TSX trades on US Thanksgiving but not on Boxing Day
    assert sessions_after(Market.TSX, date(2026, 11, 25), 1) == date(2026, 11, 26)
    assert sessions_after(Market.TSX, date(2026, 12, 24), 1) == date(2026, 12, 29)
