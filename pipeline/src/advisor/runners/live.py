"""The runners stage of the pre-open run: store yesterday's ignitions and track every unsettled signal.

Display only: nothing here feeds the model, Picks, Invest or the holdings advice.
"""

import time
from bisect import bisect_right
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime, timedelta

import psycopg

from advisor.collectors.sec import SecEdgar
from advisor.models import ET, DailyBar, Market, SymbolInfo
from advisor.runners.cost import cost_r, spread_pct
from advisor.runners.plan import Outcome, Plan, plan_for
from advisor.runners.rule import STARTING, Rule, Series, ignitions, series_of, stats_at
from advisor.runners.track import NO_PRICES_HELD, held_at_last_close, track
from advisor.runners.warnings import warnings_for
from advisor.schedule import previous_sessions, sessions_after, sessions_between
from advisor.store import repo

KEPT = timedelta(days=730)
AHEAD = timedelta(days=366)  # the sessions after D a hold-by and the 5 sessions after it can need
CLOSED = {"target", "stop", "held"}
WARNINGS_BUDGET = 60.0  # seconds for the whole warnings step; later signals keep only the split warning

Splits = Callable[[Sequence[str]], Mapping[str, list[tuple[date, float]]]]


def _rule(version: int, settings: Mapping[int, Mapping]) -> Rule:
    return STARTING if version == 0 else Rule.from_settings(settings[version])


def _upto(bars: Mapping[str, Sequence[DailyBar]], day: date) -> dict[str, Series]:
    """Each symbol's bars dated on or before `day`; a later bar would be look-ahead."""
    kept = {symbol: [b for b in history if b.day <= day] for symbol, history in bars.items()}
    return {symbol: series_of(history) for symbol, history in kept.items() if history}


def _signals(
    series: Mapping[str, Series], universe: Sequence[SymbolInfo], d: date, version: int, rule: Rule
) -> tuple[list[dict], int]:
    """The ignitions on D, each with a preview plan from D's close, and the split-suspects counted."""
    hold_by = sessions_after(Market.US, d, rule.hold_sessions)
    rows, suspect = [], 0
    for info in universe:
        s = series.get(info.symbol)
        if s is None or s.days[-1] != d:
            continue
        found, i = ignitions(s, rule), len(s.days) - 1
        suspect += bool(found.split_suspect[i])
        if not found.signal[i]:
            continue
        close, low = float(s.close[i]), float(s.low[i])
        plan = plan_for(close, low, hold_by, rule)
        if plan is None:  # no stop under D's close: nothing to plan
            continue
        spread = spread_pct(s, i)
        rows.append({
            "signal_day": d, "symbol": info.symbol, "name": info.name, "rule_version": version,
            **stats_at(s, i, rule), "signal_close": close, "signal_low": low, "spread_pct": spread,
            "stop": plan.stop, "target": plan.target, "hold_by": plan.hold_by,
            "cost_r": cost_r(spread, close, plan.stop),
        })
    return rows, suspect


def _add_warnings(
    rows: list[dict], as_of: date, sec: SecEdgar | None, splits: Splits | None,
    clock: Callable[[], float] = time.monotonic,
) -> str | None:
    """Each signal's warnings, and the split fetch's error when it failed.

    Splits are fetched once for all of them. A failed fetch, or one that names no signal's symbol, leaves
    them unchecked. Signals reached after the time budget get only the split warning, unchecked.
    """
    if not rows:
        return None
    started = clock()
    recorded: Mapping[str, list[tuple[date, float]]] = {}
    error = None
    if splits is not None:
        try:
            recorded = splits([row["symbol"] for row in rows])
        except Exception as exc:  # noqa: BLE001 - Yahoo throttling must not lose the day's signals
            error = f"{type(exc).__name__}: {exc}"[:200]
    complete = splits is None or any(row["symbol"] in recorded for row in rows)
    for row in rows:
        late = clock() - started > WARNINGS_BUDGET
        warnings, checked = warnings_for(
            row["symbol"], as_of, sec=None if late else sec, splits=recorded.get(row["symbol"], [])
        )
        row["warnings"], row["warnings_checked"] = warnings, checked and complete
    return error


def _signal_bar(row: Mapping, s: Series | None) -> tuple[float, float]:
    """D's close and low on the same price scale as the entry.

    After a split Yahoo rescales every bar, so D's bar in this run's series is used; the stored
    as-traded prices only when that bar is missing.
    """
    i = bisect_right(s.days, row["signal_day"]) - 1 if s is not None else -1
    if s is not None and i >= 0 and s.days[i] == row["signal_day"]:
        return float(s.close[i]), float(s.low[i])
    return float(row["signal_close"]), float(row["signal_low"])


def _closed(outcome: Outcome, cost: float) -> dict:
    return {
        "exit_day": outcome.exit_day, "exit_price": outcome.exit_price, "gross_r": outcome.gross_r,
        "net_r": outcome.gross_r - cost,
    }


def _track(row: Mapping, s: Series | None, rule: Rule, sessions: Sequence[date], d: date) -> tuple[dict, bool]:
    """The fields to store for one unsettled signal, recomputed from its bars up to D.

    Also whether a split-suspect bar is holding it back.
    """
    got = track(s, row["signal_day"], *_signal_bar(row, s), sessions, rule, d)
    if got.entry_day is None and row["status"] == "open":  # no trusted bar this run: what was stored is all there is
        plan = Plan(float(row["entry"]), float(row["stop"]), float(row["target"]), row["hold_by"])
        held = held_at_last_close(plan, row["last_day"], float(row["last_close"]), sessions, d)
        if held is None:
            return {}, got.split_wait
        return {"status": "held", "skip_reason": NO_PRICES_HELD, **_closed(held, float(row["cost_r"]))}, False
    if got.outcome is None:
        return ({} if got.reason is None else {"status": "skipped", "skip_reason": got.reason}), got.split_wait
    plan, outcome = got.plan, got.outcome
    cost = cost_r(float(row["spread_pct"]), plan.entry, plan.stop)
    fields = {
        "status": outcome.status, "entry_day": got.entry_day, "entry": plan.entry, "stop": plan.stop,
        "target": plan.target, "hold_by": plan.hold_by, "cost_r": cost, "last_day": outcome.last_day,
        "last_close": outcome.last_close,
    }
    if outcome.status == "open":
        return fields, got.split_wait
    reason = {} if got.reason is None else {"skip_reason": got.reason}
    return fields | reason | _closed(outcome, cost), False


def runners_stage(
    conn: psycopg.Connection,
    bars: Mapping[str, Sequence[DailyBar]],
    universe: Sequence[SymbolInfo],
    now_utc: datetime,
    *,
    sec: SecEdgar | None = None,
    splits: Splits | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, int | str]:
    """Store D's ignitions, then track every unsettled signal by its own rule version.

    D is the last US session before the run's New York date; no bar after D is read. The filings and
    splits are fetched first; every write happens in one transaction, so a failure changes nothing.
    A failed split fetch is named under `splits_error`.
    """
    today = now_utc.astimezone(ET).date()
    d = previous_sessions(today - timedelta(days=1), 1)[0]
    series = _upto(bars, d)
    live = repo.live_runner_rule(conn)
    version, rule = (0, STARTING) if live is None else (live[0], Rule.from_settings(live[1]))
    found, suspect = _signals(series, universe, d, version, rule)
    splits_error = _add_warnings(found, today, sec, splits, clock)
    counts: dict[str, int | str] = {
        "signals": 0, "split_suspect": suspect, "entered": 0, "closed": 0, "open": 0, "unchecked": 0,
        "split_wait": 0,
    }
    with conn.transaction():
        for row in found:
            if repo.insert_runner_signal(conn, row):
                counts["signals"] += 1
                counts["unchecked"] += not row["warnings_checked"]
        settings = repo.runner_rule_settings(conn)
        unsettled = repo.unsettled_runner_signals(conn)
        sessions = sessions_between(min((row["signal_day"] for row in unsettled), default=d), d + AHEAD)
        for row in unsettled:
            fields, split_wait = _track(row, series.get(row["symbol"]), _rule(row["rule_version"], settings), sessions, d)
            repo.update_runner_signal(conn, row["id"], **fields)
            status = fields.get("status", row["status"])
            counts["entered"] += row["status"] == "waiting" and "entry" in fields
            counts["closed"] += status in CLOSED
            counts["open"] += status == "open"
            counts["split_wait"] += split_wait
        repo.prune_runner_signals(conn, today - KEPT)
    if splits_error is not None:
        counts["splits_error"] = splits_error
    return counts
