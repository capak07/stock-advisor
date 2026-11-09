"""Decides whether 'now' falls in a run window on a trading day of either market (spec §3).

GitHub cron is UTC-only, so each run has one cron for EDT and one for EST. This guard
accepts exactly one of them, and only on days a market calendar says are right. The NYSE
and the TSX both keep Eastern time, so one set of ET targets serves both markets.
"""

from datetime import date, datetime, time, timedelta
from functools import cache

import pandas_market_calendars as mcal

from advisor.markets import MARKETS
from advisor.models import ET, Market, RunKind

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
def _calendar(market: Market) -> mcal.MarketCalendar:
    return mcal.get_calendar(MARKETS[market].calendar)


def market_close_et(day: date, market: Market = Market.US) -> time | None:
    """Closing time in ET for `day`, or None when `market` is closed."""
    schedule = _calendar(market).schedule(start_date=day.isoformat(), end_date=day.isoformat())
    if schedule.empty:
        return None
    return schedule.iloc[0]["market_close"].tz_convert("America/New_York").time()


def _todays_slots(now_et: datetime) -> list[tuple[RunKind, datetime]]:
    """Run slots on `now_et`'s date: pre-open when any market is open, early-close for a market
    closing before 16:00, pre-close for one closing at 16:00. A split day has both."""
    closes = [market_close_et(now_et.date(), market) for market in Market]
    open_closes = [close for close in closes if close is not None]
    if not open_closes:
        return []
    kinds = [RunKind.PRE_OPEN]
    if any(close < NORMAL_CLOSE for close in open_closes):
        kinds.append(RunKind.EARLY_CLOSE)
    if any(close >= NORMAL_CLOSE for close in open_closes):
        kinds.append(RunKind.PRE_CLOSE)
    return [(kind, datetime.combine(now_et.date(), TARGETS[kind], tzinfo=ET)) for kind in kinds]


def resolve_run_kind(now_utc: datetime) -> RunKind | None:
    now_et = now_utc.astimezone(ET)
    for kind, scheduled in _todays_slots(now_et):
        if scheduled - EARLY_TOLERANCE <= now_et <= scheduled + LATE_TOLERANCE:
            return kind
    return None


def overdue_kinds(now_utc: datetime) -> list[RunKind]:
    """Today's slots whose run window has closed (past LATE_TOLERANCE), however long ago.
    GitHub has created scheduled runs hours late, so a trigger checks every closed slot."""
    now_et = now_utc.astimezone(ET)
    return [kind for kind, scheduled in _todays_slots(now_et) if now_et > scheduled + LATE_TOLERANCE]


def missed_run_kind(now_utc: datetime) -> RunKind | None:
    """The slot whose own trigger arrived too late to run (past LATE_TOLERANCE), if any."""
    now_et = now_utc.astimezone(ET)
    for kind, scheduled in _todays_slots(now_et):
        if scheduled + LATE_TOLERANCE < now_et < scheduled + MISSED_HORIZON:
            return kind
    return None


def previous_sessions(end: date, count: int, market: Market = Market.US) -> list[date]:
    """The `count` most recent `market` session dates on or before `end`, ascending."""
    schedule = _calendar(market).schedule(
        start_date=(end - timedelta(days=count * 2 + 10)).isoformat(), end_date=end.isoformat()
    )
    return [stamp.date() for stamp in schedule.index][-count:]


def sessions_after(market: Market, day: date, n: int) -> date:
    """The `n`-th `market` trading session after `day`, on that market's own calendar."""
    if n < 1:
        raise ValueError(f"n must be at least 1, got {n}")
    days = _calendar(market).valid_days(
        start_date=(day + timedelta(days=1)).isoformat(),
        end_date=(day + timedelta(days=n * 2 + 10)).isoformat(),
    )
    return days[n - 1].date()


def expected_last_session(kind: RunKind, now_utc: datetime, market: Market = Market.US) -> date:
    """Latest `market` session whose daily bar should exist: the latest one on or before today
    for pre-close and early-close runs, before today for pre-open runs."""
    today = now_utc.astimezone(ET).date()
    end = today if kind in (RunKind.PRE_CLOSE, RunKind.EARLY_CLOSE) else today - timedelta(days=1)
    return previous_sessions(end, 1, market)[0]


def freshness_floor(
    kind: RunKind,
    now_utc: datetime,
    allowed_lag_sessions: int = 1,
    *,
    market: Market = Market.US,
) -> date:
    """Oldest acceptable last-bar date in `market`: its expected session, allowing
    `allowed_lag_sessions` behind (spec §10)."""
    last = expected_last_session(kind, now_utc, market)
    return previous_sessions(last, allowed_lag_sessions + 1, market)[0]
