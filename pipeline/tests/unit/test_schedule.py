from datetime import UTC, datetime, time

import pytest

from advisor.models import RunKind
from advisor.schedule import market_close_et, resolve_run_kind


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
    from datetime import date

    assert market_close_et(date(2026, 10, 14)) == time(16, 0)
    assert market_close_et(date(2026, 11, 27)) == time(13, 0)
    assert market_close_et(date(2026, 11, 26)) is None
