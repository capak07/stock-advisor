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
from advisor.daytrade.scan import Found, Listing, ScanResult, scan
from advisor.daytrade.score import Scored, cost_pct, cost_r, rank, score
from advisor.daytrade.track import Outcome, track
from advisor.models import ET, Market
from advisor.store import repo

REPLAYS = 10_000
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


def _plan_of(row: dict, s: Session) -> tuple[Plan, Trigger]:
    """The stored signal's plan and trigger. track() only reads the trigger's time and entry."""
    entry, stop = float(row["entry"]), float(row["stop"])
    at = row["trigger_at"].astimezone(ET)
    plan = Plan(entry, stop, float(row["target"]), float(row["entry"] - row["stop"]), s.flat_by)
    bar = Bar(at - STEP, entry, entry, entry, entry, 0.0)
    return plan, Trigger(bar=bar, at=at, entry=entry, volume_x=float(row["volume_x"]))


def _net(outcome: Outcome, row: dict) -> float | None:
    if outcome.status == "open" or outcome.gross_r is None:
        return None
    return outcome.gross_r - float(row["cost_r"])


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
    replays: int = REPLAYS,
) -> dict[str, Any]:
    """One cycle at `now`. `full` scans `listings`; otherwise only `candidates` (the job's last
    full scan's stage-1 candidates). Per-symbol errors are counted; a cycle whose every Yahoo
    request failed is recorded as failed (the day's error) and returns early."""
    now_et = now.astimezone(ET)
    day = now_et.date()
    cycles = _cycles_so_far(conn, day) + 1
    sessions = open_sessions(day)
    fee, spread, _ = repo.daytrade_settings(conn)
    cutoff = now_et.replace(second=0, microsecond=0)
    pool = listings if full else (candidates or [])
    # A market past its no-new-signals time is not scanned (a 13:00 close stops at 12:30).
    todo = [x for x in pool if x.market in sessions and cutoff <= sessions[x.market].no_entries_after]
    out: dict[str, Any] = {"ok": True, "full": full, "candidates": [], "new": 0, "tracked": 0, "errors": 0}

    def fail(reason: str) -> dict[str, Any]:
        repo.update_daytrade_day(conn, day, status="failed", cycles=cycles, error=reason)
        return {**out, "ok": False, "error": reason}

    result = ScanResult(0, 0, [], [], 0)
    if todo:
        try:
            result = scan(client, todo, now_et)
        except Exception as e:  # noqa: BLE001 - an unexpected answer must not end the job
            return fail(f"the scan failed: {e}")
        out["errors"] += result.errors
        if result.scanned == 0 and result.errors:
            return fail(f"Yahoo gave no data this cycle ({result.errors} of {len(todo)} symbols failed)")
    out["candidates"] = result.candidates

    stored = {(r["symbol"], r["market"]) for r in repo.daytrade_signals_for(conn, day)}
    for f in result.found:
        if (f.listing.symbol, f.listing.market.value) in stored:
            continue  # one signal per stock per day: never replayed again
        row, errors = _new_signal(client, f, sessions[f.listing.market], now, fee, spread, news_get, replays)
        repo.upsert_daytrade_signal(conn, row)
        out["new"] += 1
        out["errors"] += errors
    _rerank(conn, day)

    asked = failed = 0
    for row in repo.daytrade_signals_for(conn, day):
        if row["status"] != "open":
            continue  # target, stop and flat are final
        plan, trig = _plan_of(row, sessions[Market(row["market"])])
        client.wait()
        asked += 1
        try:
            bars = client.chart(to_yahoo(row["symbol"]), "1d", "5m")
        except YahooError:
            failed += 1
            continue
        o = track(plan, trig, bars, now_et)
        repo.update_daytrade_outcome(conn, row["id"], o, _net(o, row))
        out["tracked"] += 1
    out["errors"] += failed
    if not todo and asked and failed == asked:
        return fail(f"Yahoo gave no data this cycle ({failed} of {asked} charts failed)")

    fields: dict[str, Any] = {"status": "scanning", "cycles": cycles, "last_update": now, "error": None}
    if full and todo:
        fields.update(scanned=result.scanned, usable=result.usable, candidates=len(result.candidates))
    repo.update_daytrade_day(conn, day, **fields)
    return out


def finalize(conn: psycopg.Connection, client: YahooClient, now: datetime) -> int:
    """Close every still-open signal of the day as flat at its flat-by time: at the last completed
    bar's close up to flat-by, or the last stored price when there are no bars. Returns how many."""
    now_et = now.astimezone(ET)
    day = now_et.date()
    sessions = open_sessions(day)
    n = 0
    for row in repo.daytrade_signals_for(conn, day):
        if row["status"] != "open":
            continue
        s = sessions[Market(row["market"])]
        plan, trig = _plan_of(row, s)
        o: Outcome | None = None
        client.wait()
        try:
            o = track(plan, trig, client.chart(to_yahoo(row["symbol"]), "1d", "5m"), now_et)
        except YahooError:
            o = None
        if o is None or o.status == "open":
            if o is not None and o.last_at > trig.at:
                price, at = o.last_price, o.last_at
            elif row["last_price"] is not None:
                price, at = float(row["last_price"]), row["last_at"]
            else:
                price, at = plan.entry, trig.at
            o = Outcome("flat", s.flat_by, price, (price - plan.entry) / plan.risk, price, at)
        repo.update_daytrade_outcome(conn, row["id"], o, _net(o, row))
        n += 1
    return n


def run_job(
    conn: psycopg.Connection,
    client: YahooClient,
    listings: Sequence[Listing],
    job: str,
    *,
    clock: Clock,
    sleep: Sleep,
    news_get: Get,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Loop cycles 30 s after each 5-minute bar close until the job's last bar. Each job's first
    cycle is a full scan, then one every 15 minutes (and again after a failed one); the cycles
    between re-check the last full scan's candidates. The afternoon job finalizes the day."""
    start = clock().astimezone(ET)
    day = start.date()
    sessions = open_sessions(day)
    if not sessions:
        repo.start_daytrade_day(conn, day, "closed")
        return {"day": day.isoformat(), "cycles": [], "closed": True}
    repo.prune_daytrade(conn, start)
    if repo.daytrade_day(conn, day) is None:
        repo.start_daytrade_day(conn, day, "waiting")
    first = datetime.combine(day, FIRST_CLOSE, tzinfo=ET)
    last = last_close(job, day, sessions)
    cycles: list[dict[str, Any]] = []
    candidates: list[Listing] | None = None
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
        full = candidates is None or last_full is None or close - last_full >= FULL_EVERY
        res = run_cycle(conn, client, listings, clock(), full=full, news_get=news_get, candidates=candidates)
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
        finalized = finalize(conn, client, now)
        repo.update_daytrade_day(conn, day, status="done", last_update=now)
    return {"day": day.isoformat(), "cycles": cycles, "finalized": finalized}
