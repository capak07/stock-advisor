from datetime import UTC, date, datetime, time

import pytest

from advisor.models import RunKind
from advisor.schedule import (
    expected_last_session,
    freshness_floor,
    market_close_et,
    missed_run_kind,
    previous_sessions,
    resolve_run_kind,
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
        ("2026-11-26T13:15:00", None),                 # Thanksgiving: market closed
        ("2026-10-17T12:15:00", None),                 # Saturday
        ("2026-11-27T13:15:00", RunKind.PRE_OPEN),     # early-close day still has pre-open
        ("2026-11-27T17:15:00", RunKind.EARLY_CLOSE),  # 12:15 ET before the 13:00 close
        ("2026-11-27T20:15:00", None),                 # 15:15 ET: market already closed
    ],
)
def test_resolve_run_kind(now, expected):
    assert resolve_run_kind(utc(now)) == expected


def test_market_close_et_reports_normal_early_and_closed_days():
    assert market_close_et(date(2026, 10, 14)) == time(16, 0)
    assert market_close_et(date(2026, 11, 27)) == time(13, 0)
    assert market_close_et(date(2026, 11, 26)) is None


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
        ("2026-11-27T20:15:00", None, None),              # 15:15 ET on an early-close day
    ],
)
def test_missed_run_kind_flags_only_a_slots_own_late_cron(now, resolved, missed):
    assert resolve_run_kind(utc(now)) == resolved
    assert missed_run_kind(utc(now)) == missed


def test_missed_run_kind_is_none_on_closed_days():
    assert missed_run_kind(utc("2026-10-17T12:46:00")) is None  # Saturday


def test_previous_sessions_skips_holidays_and_is_ascending():
    assert previous_sessions(date(2026, 11, 27), 3) == [
        date(2026, 11, 24), date(2026, 11, 25), date(2026, 11, 27),
    ]


@pytest.mark.parametrize(
    ("kind", "now", "last_session", "floor"),
    [
        (RunKind.PRE_OPEN, "2026-10-14T12:15:00", date(2026, 10, 13), date(2026, 10, 12)),
        (RunKind.PRE_CLOSE, "2026-10-14T19:15:00", date(2026, 10, 14), date(2026, 10, 13)),
        (RunKind.PRE_OPEN, "2026-10-19T12:15:00", date(2026, 10, 16), date(2026, 10, 15)),
        (RunKind.PRE_OPEN, "2026-11-27T13:15:00", date(2026, 11, 25), date(2026, 11, 24)),
    ],
)
def test_expected_last_session_and_freshness_floor(kind, now, last_session, floor):
    assert expected_last_session(kind, utc(now)) == last_session
    assert freshness_floor(kind, utc(now)) == floor
