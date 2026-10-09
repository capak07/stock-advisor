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


def resolve_run_kind(now_utc: datetime) -> RunKind | None:
    now_et = now_utc.astimezone(ET)
    close = market_close_et(now_et.date())
    if close is None:
        return None
    early_close_day = close < NORMAL_CLOSE
    for kind, target in TARGETS.items():
        if kind is RunKind.PRE_CLOSE and early_close_day:
            continue
        if kind is RunKind.EARLY_CLOSE and not early_close_day:
            continue
        scheduled = datetime.combine(now_et.date(), target, tzinfo=ET)
        if scheduled - EARLY_TOLERANCE <= now_et <= scheduled + LATE_TOLERANCE:
            return kind
    return None
