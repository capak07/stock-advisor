"""One day trade cycle (scan, replay, score, rank, track, record) and the job that loops it.

Ties the ported day-trader skill pieces together (MIT, github.com/Jakeschincariol/day-trader-skill):
the scan (scan.py), the Time Machine (timemachine.py) and the news (news.py), as the skill's
workflow runs them by hand: scan, check the news, plan, replay, rank, then follow the trade.
"""

import json
from collections.abc import Callable, Sequence
from dataclasses import asdict
from datetime import date, datetime, time, timedelta
from typing import Any

import psycopg

from advisor.collectors.yfinance_bars import to_yahoo
from advisor.daytrade.bars import BAR_MIN, Bar, YahooClient, YahooError
from advisor.daytrade.news import headlines
from advisor.daytrade.replay import replay, rule_history, seed_for
from advisor.daytrade.rule import Plan, Session, Trigger, session_for
from advisor.daytrade.scan import MAX_FAILED_CHARTS, Charted, Found, Listing, ScanResult, scan
from advisor.daytrade.score import Scored, cost_pct, cost_r, rank, score
from advisor.daytrade.track import Outcome, track
from advisor.models import ET, Market
from advisor.store import repo

REPLAYS = 10_000
MAX_CONFIRM = 200  # stage-2 charts per cycle at most, a safety net (the skill's default)
STEP = timedelta(minutes=BAR_MIN)
CYCLE_DELAY = timedelta(seconds=30)  # Yahoo's bars lag the close a little
FULL_EVERY = timedelta(minutes=15)
FIRST_CLOSE = time(9, 50)  # the first bar after the opening range closes
WINDOWS: dict[str, tuple[time, time]] = {
    "morning": (time(9, 35), time(12, 40)),
    "afternoon": (time(12, 35), time(15, 59)),
}

Clock = Callable[[], datetime]
Sleep = Callable[[float], None]
Get = Callable[[str], str]
Log = Callable[[str], None]
LATE = "finished late: the afternoon job did not run"


def open_sessions(day: date) -> dict[Market, Session]:
    """Each market's own session on `day`; a market closed that day is left out."""
    return {m: s for m in Market if (s := session_for(day, m)) is not None}


def last_close(job: str, day: date, sessions: dict[Market, Session]) -> datetime:
    """The last 5-minute bar close this job runs a cycle for: its window's end, or the latest
    flat-by among the open markets when that comes first (13:00 closes on both markets)."""
    end = datetime.combine(day, WINDOWS[job][1], tzinfo=ET) - CYCLE_DELAY
    grid = end.replace(minute=end.minute - end.minute % BAR_MIN, second=0, microsecond=0)
    return min(grid, max(s.flat_by for s in sessions.values()))


def _next_close(now: datetime, first: datetime, prev: datetime | None) -> datetime:
    """The first bar close whose cycle time (close + 30 s) is not already past. Missed ones are skipped."""
    t = now - CYCLE_DELAY
    c = t.replace(minute=t.minute - t.minute % BAR_MIN, second=0, microsecond=0)
    if c < t:
        c += STEP
    c = max(c, first)
    if prev is not None:
        c = max(c, prev + STEP)
    return c


def _plan_of(row: dict, flat_by: datetime) -> tuple[Plan, Trigger]:
    """The stored signal's plan and trigger. track() only reads the trigger's time and entry."""
    entry, stop = float(row["entry"]), float(row["stop"])
    at = row["trigger_at"].astimezone(ET)
    plan = Plan(entry, stop, float(row["target"]), float(row["entry"] - row["stop"]), flat_by)
    bar = Bar(at - STEP, entry, entry, entry, entry, 0.0)
    return plan, Trigger(bar=bar, at=at, entry=entry, volume_x=float(row["volume_x"]))


def _net(outcome: Outcome, row: dict) -> float | None:
    if outcome.status == "open" or outcome.gross_r is None:
        return None
    return outcome.gross_r - float(row["cost_r"])


def _flat(plan: Plan, price: float, last_at: datetime) -> Outcome:
    """Flat at flat-by. Gross R as track() computes its own flat exit (unrounded)."""
    return Outcome("flat", plan.flat_by, price, (price - plan.entry) / plan.risk, price, last_at)


def _last_seen(row: dict, plan: Plan, trig: Trigger) -> tuple[float, datetime]:
    """The last stored price and its time, else the entry at the trigger."""
    if row["last_price"] is not None:
        return float(row["last_price"]), row["last_at"] or trig.at
    return plan.entry, trig.at


def _new_signal(
    client: YahooClient,
    f: Found,
    s: Session,
    now: datetime,
    fee: float,
    spread: float,
    news_get: Get,
    replays: int,
) -> tuple[dict[str, Any], int]:
    """The row for a signal new this cycle, and how many of its steps failed (0-2)."""
    lst, day = f.listing, s.day
    errors = 0
    rep: dict[str, Any] = {}
    hist: dict[str, Any] = {}
    stats = None
    rep_stats = None
    client.wait()
    try:
        history = client.chart(to_yahoo(lst.symbol), "60d", "5m")
    except YahooError as e:
        errors += 1
        rep = hist = {"skipped": f"no 60-day history: {e}"}
    else:
        try:
            stats = rule_history(history, day, lst.market)
            hist = asdict(stats)
        except ValueError as e:
            errors += 1
            hist = {"skipped": str(e)}
        try:
            rep_stats = replay(history, f.plan, f.trigger, s, replays=replays, seed=seed_for(day, lst.symbol))
            rep = asdict(rep_stats)
        except ValueError as e:
            errors += 1
            rep = {"skipped": str(e)}
    pct = cost_pct(lst.market, fee, spread)
    c_r = cost_r(pct, f.plan)
    net_history: float | None = None
    net_replay: float | None = None
    eligible = False
    if stats is not None and rep_stats is not None:
        net_history, net_replay, eligible = score(stats, rep_stats, c_r)
    row = {
        "day": day,
        "symbol": lst.symbol,
        "market": lst.market.value,
        "name": lst.name,
        "trigger_at": f.trigger.at,
        "entry": f.plan.entry,
        "or_high": f.rng.high,
        "or_low": f.rng.low,
        "stop": f.plan.stop,
        "target": f.plan.target,
        "flat_by": f.plan.flat_by,
        "volume_x": f.trigger.volume_x,
        "cost_pct": pct,
        "cost_r": c_r,
        "replay": rep,
        "history": hist,
        "net_replay_r": net_replay,
        "net_history_r": net_history,
        "eligible": eligible,
        "headlines": headlines(news_get, lst.symbol, now),
    }
    return row, errors


def _rerank(conn: psycopg.Connection, day: date) -> None:
    rows = repo.daytrade_signals_for(conn, day)
    items = [
        Scored((r["symbol"], r["market"]), float(r["net_history_r"]), float(r["net_replay_r"]), True)
        for r in rows
        if r["eligible"] and r["net_history_r"] is not None and r["net_replay_r"] is not None
    ]
    ids = {(r["symbol"], r["market"]): r["id"] for r in rows}
    repo.set_daytrade_ranks(conn, day, {ids[k]: n for k, n in rank(items).items()})


def _cycles_so_far(conn: psycopg.Connection, day: date) -> int:
    row = repo.daytrade_day(conn, day)
    if row is None:
        repo.start_daytrade_day(conn, day, "waiting")
        return 0
    return row["cycles"]


def run_cycle(
    conn: psycopg.Connection,
    client: YahooClient,
    listings: Sequence[Listing],
    now: datetime,
    *,
    full: bool,
    news_get: Get,
    candidates: Sequence[Listing] | None = None,
    charted: Charted | None = None,
    replays: int = REPLAYS,
    log: Log = print,
) -> dict[str, Any]:
    """One cycle at `now`. `full` scans `listings`; otherwise only `candidates` (the job's last
    full scan's stage-1 candidates). `charted` is the job's stage-2 memory (see scan.py); the
    updated one is returned as "charted". Stocks that already have a signal today are tracked, not
    scanned. Per-symbol errors of any kind are counted and logged. A cycle whose scan got no
    data, or whose every stage-2 chart failed (or, with no scan, whose every tracking chart
    failed) still tracks, then is recorded as failed with the reason; its scan counts are not
    written. Tracking stops after 5 failed charts in a row and counts the rest as errors."""
    now_et = now.astimezone(ET)
    day = now_et.date()
    cycles = _cycles_so_far(conn, day) + 1
    sessions = open_sessions(day)
    fee, spread, _ = repo.daytrade_settings(conn)
    cutoff = now_et.replace(second=0, microsecond=0)
    stored = {(r["symbol"], r["market"]) for r in repo.daytrade_signals_for(conn, day)}
    pool = listings if full else (candidates or [])
    # A market past its no-new-signals time is not scanned (a 13:00 close stops at 12:30).
    todo = [
        x for x in pool
        if x.market in sessions
        and cutoff <= sessions[x.market].no_entries_after
        and (x.symbol, x.market.value) not in stored
    ]
    out: dict[str, Any] = {
        "ok": True, "full": full, "candidates": [], "new": 0, "tracked": 0, "errors": 0,
        "charted": dict(charted or {}),
    }

    failure: str | None = None
    result = ScanResult(0, 0, [], [], 0)
    if todo:
        try:
            result = scan(client, todo, now_et, max_confirm=MAX_CONFIRM, charted=charted)
        except Exception as e:  # noqa: BLE001 - an unexpected answer must not end the job
            failure = f"the scan failed: {e}"
        else:
            out["errors"] += result.errors
            out["charted"] = result.charted
            # A scan that bailed out (5 failed batches in a row) also reports scanned == 0.
            if result.scanned == 0 and result.errors:
                failure = f"Yahoo gave no data this cycle ({result.errors} of {len(todo)} symbols failed)"
            elif result.confirm and result.confirm_failed == result.confirm:
                failure = (
                    f"Yahoo gave no charts this cycle ({result.confirm_failed} of {result.confirm} charts failed)"
                )
    if failure is None:
        out["candidates"] = result.candidates
        for f in result.found:
            key = (f.listing.symbol, f.listing.market.value)
            if key in stored:
                continue  # one signal per stock per day: never replayed again
            try:
                row, errors = _new_signal(
                    client, f, sessions[f.listing.market], now, fee, spread, news_get, replays
                )
                repo.upsert_daytrade_signal(conn, row)
            except Exception as e:  # noqa: BLE001 - one odd signal must not stop the others
                out["errors"] += 1
                log(f"{f.listing.symbol}: signal not stored: {type(e).__name__}: {e}")
                continue
            stored.add(key)
            out["new"] += 1
            out["errors"] += errors
        _rerank(conn, day)

    # Target, stop and flat are final: only open signals are tracked.
    rows = [r for r in repo.daytrade_signals_for(conn, day) if r["status"] == "open"]
    asked, failed, streak = len(rows), 0, 0
    for k, row in enumerate(rows):
        if streak >= MAX_FAILED_CHARTS:
            failed += asked - k  # Yahoo is down: the rest wait for the next cycle
            break
        try:
            plan, trig = _plan_of(row, sessions[Market(row["market"])].flat_by)
            client.wait()
            bars = client.chart(to_yahoo(row["symbol"]), "1d", "5m")
            o = track(plan, trig, bars, now_et)
            repo.update_daytrade_outcome(conn, row["id"], o, _net(o, row))
        except YahooError:
            failed += 1
            streak += 1
            continue
        except Exception as e:  # noqa: BLE001 - one odd signal must not stop the others
            failed += 1
            log(f"{row['symbol']}: not tracked: {type(e).__name__}: {e}")
            continue
        streak = 0
        out["tracked"] += 1
    out["errors"] += failed
    if failure is None and not todo and asked and failed == asked:
        failure = f"Yahoo gave no data this cycle ({failed} of {asked} charts failed)"

    if failure is not None:
        repo.update_daytrade_day(conn, day, status="failed", cycles=cycles, error=failure)
        return {**out, "ok": False, "error": failure}
    fields: dict[str, Any] = {"status": "scanning", "cycles": cycles, "last_update": now, "error": None}
    if full and todo:
        fields.update(scanned=result.scanned, usable=result.usable, candidates=len(result.candidates))
    repo.update_daytrade_day(conn, day, **fields)
    return out


def finalize(conn: psycopg.Connection, client: YahooClient, now: datetime, log: Log = print) -> int:
    """Close every still-open signal of the day as flat at its flat-by time: at the last completed
    bar's close up to flat-by, or the last stored price when there are no bars. Returns how many."""
    now_et = now.astimezone(ET)
    day = now_et.date()
    sessions = open_sessions(day)
    n = 0
    for row in repo.daytrade_signals_for(conn, day):
        if row["status"] != "open":
            continue
        try:
            plan, trig = _plan_of(row, sessions[Market(row["market"])].flat_by)
            o: Outcome | None = None
            client.wait()
            try:
                o = track(plan, trig, client.chart(to_yahoo(row["symbol"]), "1d", "5m"), now_et)
            except YahooError:
                o = None
            if o is None or o.status == "open":
                if o is not None and o.last_at > trig.at:
                    o = _flat(plan, o.last_price, o.last_at)
                else:
                    o = _flat(plan, *_last_seen(row, plan, trig))
            repo.update_daytrade_outcome(conn, row["id"], o, _net(o, row))
        except Exception as e:  # noqa: BLE001 - close the others; the next job closes this one
            log(f"{row['symbol']}: not finalized: {type(e).__name__}: {e}")
            continue
        n += 1
    return n


def close_earlier_days(conn: psycopg.Connection, today: date, log: Log = print) -> int:
    """Days before `today` left unfinished (the afternoon job never ran or died, or a signal
    could not be finalized): their open signals go flat at their last stored price (else the
    entry), exit at that day's flat-by; no charts (Yahoo's 1-day chart would be today's). A day
    not yet done is marked done with a "finished late" note. Returns days closed."""
    n = 0
    for d in repo.daytrade_unfinished_days(conn, today):
        day = d["day"]
        try:
            for row in repo.daytrade_signals_for(conn, day):
                if row["status"] != "open":
                    continue
                s = session_for(day, Market(row["market"]))
                flat_by = s.flat_by if s is not None else datetime.combine(day, time(15, 55), tzinfo=ET)
                plan, trig = _plan_of(row, flat_by)
                o = _flat(plan, *_last_seen(row, plan, trig))
                repo.update_daytrade_outcome(conn, row["id"], o, _net(o, row))
            if d["status"] != "done":
                error = LATE if not d["error"] else f"{d['error']}; {LATE}"
                repo.update_daytrade_day(conn, day, status="done", error=error)
        except Exception as e:  # noqa: BLE001 - today's job matters more
            log(f"{day.isoformat()}: not closed: {type(e).__name__}: {e}")
            continue
        n += 1
    return n


def _record_failure(conn: psycopg.Connection, day: date, reason: str, log: Log) -> None:
    """Best effort: the database may be what failed."""
    try:
        row = repo.daytrade_day(conn, day)
        cycles = (row["cycles"] if row else 0) + 1
        repo.update_daytrade_day(conn, day, status="failed", cycles=cycles, error=reason)
    except Exception as e:  # noqa: BLE001
        log(f"could not record the failed cycle: {type(e).__name__}: {e}")


def run_job(
    conn: psycopg.Connection,
    client: YahooClient,
    listings: Sequence[Listing],
    job: str,
    *,
    clock: Clock,
    sleep: Sleep,
    news_get: Get,
    log: Log = print,
) -> dict[str, Any]:
    """Loop cycles 30 s after each 5-minute bar close until the job's last bar. Each job's first
    cycle is a full scan, then one every 15 minutes (and again after a failed one); the cycles
    between re-check the last full scan's candidates. A cycle that raises is recorded as failed
    and the loop goes on. The job first closes any earlier unfinished day; the afternoon job
    finalizes today."""
    start = clock().astimezone(ET)
    day = start.date()
    sessions = open_sessions(day)
    if not sessions:
        repo.start_daytrade_day(conn, day, "closed")
        return {"day": day.isoformat(), "cycles": [], "closed": True}
    repo.prune_daytrade(conn, start)
    close_earlier_days(conn, day, log)
    if repo.daytrade_day(conn, day) is None:
        repo.start_daytrade_day(conn, day, "waiting")
    first = datetime.combine(day, FIRST_CLOSE, tzinfo=ET)
    last = last_close(job, day, sessions)
    cycles: list[dict[str, Any]] = []
    candidates: list[Listing] | None = None
    charted: dict[str, tuple[float, datetime]] = {}  # stage 2's memory, for this job only
    last_full: datetime | None = None
    prev: datetime | None = None
    while True:
        now = clock().astimezone(ET)
        close = _next_close(now, first, prev)
        if close > last:
            break
        at = close + CYCLE_DELAY
        if at > now:
            sleep((at - now).total_seconds())
        # A failed full scan leaves last_full >= 15 minutes back, so the next cycle is full again.
        full = candidates is None or last_full is None or close - last_full >= FULL_EVERY
        try:
            res = run_cycle(
                conn, client, listings, clock(), full=full, news_get=news_get, candidates=candidates,
                charted=charted, log=log,
            )
            charted = res["charted"]
        except Exception as e:  # noqa: BLE001 - record it and wait for the next bar
            reason = f"the cycle failed: {type(e).__name__}: {e}"
            _record_failure(conn, day, reason, log)
            res = {"ok": False, "candidates": [], "new": 0, "tracked": 0, "errors": 0, "error": reason}
        if res["ok"] and full:
            candidates, last_full = list(res["candidates"]), close
        prev = close
        summary = {
            "at": at, "full": full, "ok": res["ok"], "candidates": len(res["candidates"]),
            "new": res["new"], "tracked": res["tracked"], "errors": res["errors"],
        }
        cycles.append(summary)
        log(json.dumps({**summary, "at": at.isoformat(), "error": res.get("error")}))
    finalized = None
    if job == "afternoon":
        now = clock()
        finalized = finalize(conn, client, now, log)
        repo.update_daytrade_day(conn, day, status="done", last_update=now)
    return {"day": day.isoformat(), "cycles": cycles, "finalized": finalized}
