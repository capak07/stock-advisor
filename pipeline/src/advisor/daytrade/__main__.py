"""python -m advisor.daytrade --job morning|afternoon [--now ISO]: one day trade job.

pg_cron dispatches each job twice a day, once for EDT and once for EST; the guard here
lets a job start anywhere from 20 minutes before its window to the window's end, and refuses
(exit 0) a start outside that. In EST the wrong dispatch lands at 8:35 or 11:35 ET: too early.
In EDT it lands at 10:35 or 13:35 ET, while the right job runs in the same concurrency group,
so it waits and starts after the window ends: refused (or, if the first job died, a recovery run).
"""

import argparse
import json
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from advisor.config import Settings
from advisor.daytrade.bars import YahooClient, _http_get
from advisor.daytrade.cycle import CYCLE_DELAY, WINDOWS, last_close, open_sessions, run_job
from advisor.models import ET
from advisor.store import repo
from advisor.store.db import connect

START_TOLERANCE = timedelta(minutes=20)  # how early before its window a job may start


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m advisor.daytrade", description=__doc__)
    p.add_argument("--job", required=True, choices=sorted(WINDOWS))
    p.add_argument("--now", help="pretend the job starts at this ISO time (the clock runs on from it)")
    return p.parse_args(argv)


def check_start(job: str, now: datetime) -> str | None:
    """None when `now` is a fair start for `job`: from 20 minutes before its window starts to
    the window's end (a late start, e.g. queued behind a long job, runs what is left). Else the
    plain reason: too early is the other daylight-saving dispatch; a start after the job's last
    cycle has nothing left to do."""
    now_et = now.astimezone(ET)
    day = now_et.date()
    begin_t, end_t = WINDOWS[job]
    begin = datetime.combine(day, begin_t, tzinfo=ET)
    end = datetime.combine(day, end_t, tzinfo=ET)
    sessions = open_sessions(day)
    if sessions:
        end = min(end, last_close(job, day, sessions) + CYCLE_DELAY)
    if now_et > end:
        return f"The {job} job's window ended at {end:%H:%M} ET; it is {now_et:%H:%M} ET. Nothing to do."
    if now_et < begin - START_TOLERANCE:
        return (
            f"The {job} job's window starts at {begin:%H:%M} ET and it is {now_et:%H:%M} ET:"
            " too early, this is the other daylight-saving start. Nothing to do."
        )
    return None


def main(
    argv: list[str] | None = None,
    *,
    clock: Callable[[], datetime] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    client: YahooClient | None = None,
    news_get: Callable[[str], str] = _http_get,
) -> int:
    args = parse_args(argv)
    base = clock or (lambda: datetime.now(UTC))
    if args.now:
        start = datetime.fromisoformat(args.now)
        if start.tzinfo is None:
            start = start.replace(tzinfo=UTC)
        offset = start - base()

        def now_fn() -> datetime:
            return base() + offset
    else:
        now_fn = base
    now = now_fn()
    day = now.astimezone(ET).date()

    if not open_sessions(day):
        with connect(Settings.from_env().database_url) as conn:
            repo.start_daytrade_day(conn, day, "closed")
        print(f"The NYSE and the TSX are both closed on {day.isoformat()}. Nothing to do.")
        return 0
    refusal = check_start(args.job, now)
    if refusal:
        print(refusal)
        return 0

    with connect(Settings.from_env().database_url) as conn:
        listings = repo.daytrade_listings(conn)
        out = run_job(
            conn, client or YahooClient(), listings, args.job, clock=now_fn, sleep=sleep, news_get=news_get
        )
    print(json.dumps({"job": args.job, "day": out["day"], "cycles": len(out["cycles"]),
                      "finalized": out.get("finalized")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
