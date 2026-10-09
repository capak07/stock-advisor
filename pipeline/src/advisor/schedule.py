"""Decides whether 'now' falls in a run window on an NYSE trading day.

GitHub cron is UTC-only, so each run has one cron for EDT and one for EST. This guard
accepts exactly one of them, and only on days the NYSE calendar says are right.
"""

from datetime import date, datetime, time, timedelta
from functools import cache

import pandas_market_calendars as mcal

from advisor.models import ET, RunKind

TARGETS: dict[RunKind, time] = {
    RunKind.PRE_OPEN: time(8, 15),
    RunKind.EARLY_CLOSE: time(12, 15),
    RunKind.PRE_CLOSE: time(15, 15),
}
EARLY_TOLERANCE = timedelta(minutes=10)
LATE_TOLERANCE = timedelta(minutes=30)
# A trigger 30-60 min after its target can only be that slot's own cron running late; the
# other-DST cron always lands 60 or more minutes off.
MISSED_HORIZON = timedelta(minutes=60)
NORMAL_CLOSE = time(16, 0)


@cache
def _nyse() -> mcal.MarketCalendar:
    return mcal.get_calendar("NYSE")


def market_close_et(day: date) -> time | None:
    """Closing time in ET for `day`, or None when the NYSE is closed."""
    schedule = _nyse().schedule(start_date=day.isoformat(), end_date=day.isoformat())
    if schedule.empty:
        return None
    return schedule.iloc[0]["market_close"].tz_convert("America/New_York").time()


def _todays_slots(now_et: datetime) -> list[tuple[RunKind, datetime]]:
    """Run slots that apply on `now_et`'s date: pre_close or early_close, never both."""
    close = market_close_et(now_et.date())
    if close is None:
        return []
    early_close_day = close < NORMAL_CLOSE
    slots = []
    for kind, target in TARGETS.items():
        if kind is RunKind.PRE_CLOSE and early_close_day:
            continue
        if kind is RunKind.EARLY_CLOSE and not early_close_day:
            continue
        slots.append((kind, datetime.combine(now_et.date(), target, tzinfo=ET)))
    return slots


def resolve_run_kind(now_utc: datetime) -> RunKind | None:
    now_et = now_utc.astimezone(ET)
    for kind, scheduled in _todays_slots(now_et):
        if scheduled - EARLY_TOLERANCE <= now_et <= scheduled + LATE_TOLERANCE:
            return kind
    return None


def missed_run_kind(now_utc: datetime) -> RunKind | None:
    """The slot whose own trigger arrived too late to run (past LATE_TOLERANCE), if any."""
    now_et = now_utc.astimezone(ET)
    for kind, scheduled in _todays_slots(now_et):
        if scheduled + LATE_TOLERANCE < now_et < scheduled + MISSED_HORIZON:
            return kind
    return None


def previous_sessions(end: date, count: int) -> list[date]:
    """The `count` most recent NYSE session dates on or before `end`, ascending."""
    schedule = _nyse().schedule(
        start_date=(end - timedelta(days=count * 2 + 10)).isoformat(), end_date=end.isoformat()
    )
    return [stamp.date() for stamp in schedule.index][-count:]


def expected_last_session(kind: RunKind, now_utc: datetime) -> date:
    """Latest session whose daily bar should exist: today for pre-close runs, else the prior session."""
    today = now_utc.astimezone(ET).date()
    if kind in (RunKind.PRE_CLOSE, RunKind.EARLY_CLOSE):
        return today
    return previous_sessions(today - timedelta(days=1), 1)[0]


def freshness_floor(kind: RunKind, now_utc: datetime, allowed_lag_sessions: int = 1) -> date:
    """Oldest acceptable last-bar date: the expected session, allowing `allowed_lag_sessions` behind."""
    return previous_sessions(expected_last_session(kind, now_utc), allowed_lag_sessions + 1)[0]
