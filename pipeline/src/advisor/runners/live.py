"""The runners stage of the pre-open run: store yesterday's ignitions and track every unsettled signal.

Display only: nothing here feeds the model, Picks, Invest or the holdings advice.
"""

from bisect import bisect_right
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime, timedelta

import psycopg

from advisor.collectors.sec import SecEdgar
from advisor.models import ET, DailyBar, Market, SymbolInfo
from advisor.runners.cost import cost_r, spread_pct
from advisor.runners.plan import Plan, gapped, plan_for, settle
from advisor.runners.rule import STARTING, Rule, Series, ignitions, series_of, stats_at
from advisor.runners.warnings import warnings_for
from advisor.schedule import previous_sessions, sessions_after
from advisor.store import repo

KEPT = timedelta(days=730)
NO_PRICES = 5  # sessions without a bar before a signal is given up on
CLOSED = {"target", "stop", "held"}

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


def _add_warnings(rows: list[dict], as_of: date, sec: SecEdgar | None, splits: Splits | None) -> None:
    """Each signal's warnings. Splits are fetched once for all of them; a failed fetch leaves them unchecked."""
    if not rows:
        return
    recorded: Mapping[str, list[tuple[date, float]]] = {}
    complete = True
    if splits is not None:
        try:
            recorded = splits([row["symbol"] for row in rows])
        except Exception:  # noqa: BLE001 - Yahoo throttling must not lose the day's signals
            complete = False
    for row in rows:
        warnings, checked = warnings_for(row["symbol"], as_of, sec=sec, splits=recorded.get(row["symbol"], []))
        row["warnings"], row["warnings_checked"] = warnings, checked and complete


def _held_at_last_close(plan: Plan, cost: float, last_day: date, last_close: float, d: date) -> dict:
    """An open runner with no bar for 5 sessions, 5 sessions past its hold-by, closes at its last close."""
    if sessions_after(Market.US, last_day, NO_PRICES) > d or sessions_after(Market.US, plan.hold_by, NO_PRICES) > d:
        return {}
    gross = (last_close - plan.entry) / plan.r
    return {
        "status": "held", "skip_reason": "no prices: closed at the last close", "exit_day": last_day,
        "exit_price": last_close, "gross_r": gross, "net_r": gross - cost,
    }


def _signal_bar(row: Mapping, s: Series | None) -> tuple[float, float]:
    """D's close and low on the same price scale as the entry.

    After a split Yahoo rescales every bar, so D's bar in this run's series is used; the stored
    as-traded prices only when that bar is missing.
    """
    i = bisect_right(s.days, row["signal_day"]) - 1 if s is not None else -1
    if s is not None and i >= 0 and s.days[i] == row["signal_day"]:
        return float(s.close[i]), float(s.low[i])
    return float(row["signal_close"]), float(row["signal_low"])


def _hold_by(entry_day: date, rule: Rule) -> date:
    """The hold's last session, counting the entry day as day 1."""
    n = rule.hold_sessions
    return entry_day if n <= 1 else sessions_after(Market.US, entry_day, n - 1)


def _track(row: Mapping, s: Series | None, rule: Rule, d: date) -> dict:
    """The fields to store for one unsettled signal, recomputed from its bars up to D."""
    after = s.bars(bisect_right(s.days, row["signal_day"])) if s is not None else []
    if not after:
        if row["status"] == "open":  # no bars this run: what was stored is all there is
            plan = Plan(float(row["entry"]), float(row["stop"]), float(row["target"]), row["hold_by"])
            return _held_at_last_close(plan, float(row["cost_r"]), row["last_day"], float(row["last_close"]), d)
        if sessions_after(Market.US, row["signal_day"], NO_PRICES) <= d:
            return {"status": "skipped", "skip_reason": "no prices after the signal"}
        return {}
    entry_bar = after[0]
    entry = entry_bar.open
    signal_close, signal_low = _signal_bar(row, s)
    if gapped(signal_close, entry, rule):
        return {"status": "skipped", "skip_reason": "gapped up at the open"}
    plan = plan_for(entry, signal_low, _hold_by(entry_bar.day, rule), rule)
    if plan is None:
        return {"status": "skipped", "skip_reason": "opened under the stop"}
    outcome = settle(after, plan)
    cost = cost_r(float(row["spread_pct"]), entry, plan.stop)
    fields = {
        "status": outcome.status, "entry_day": entry_bar.day, "entry": entry, "stop": plan.stop,
        "target": plan.target, "hold_by": plan.hold_by, "cost_r": cost, "last_day": outcome.last_day, "last_close": outcome.last_close,
    }
    if outcome.status == "open":
        return fields | _held_at_last_close(plan, cost, outcome.last_day, outcome.last_close, d)
    return fields | {
        "exit_day": outcome.exit_day, "exit_price": outcome.exit_price, "gross_r": outcome.gross_r,
        "net_r": outcome.gross_r - cost,
    }


def runners_stage(
    conn: psycopg.Connection,
    bars: Mapping[str, Sequence[DailyBar]],
    universe: Sequence[SymbolInfo],
    now_utc: datetime,
    *,
    sec: SecEdgar | None = None,
    splits: Splits | None = None,
) -> dict[str, int]:
    """Store D's ignitions, then track every unsettled signal by its own rule version.

    D is the last US session before the run's New York date; no bar after D is read. The filings and
    splits are fetched first; every write happens in one transaction, so a failure changes nothing.
    """
    today = now_utc.astimezone(ET).date()
    d = previous_sessions(today - timedelta(days=1), 1)[0]
    series = _upto(bars, d)
    live = repo.live_runner_rule(conn)
    version, rule = (0, STARTING) if live is None else (live[0], Rule.from_settings(live[1]))
    found, suspect = _signals(series, universe, d, version, rule)
    _add_warnings(found, today, sec, splits)
    counts = {"signals": 0, "split_suspect": suspect, "entered": 0, "closed": 0, "open": 0, "unchecked": 0}
    with conn.transaction():
        for row in found:
            if repo.insert_runner_signal(conn, row):
                counts["signals"] += 1
                counts["unchecked"] += not row["warnings_checked"]
        settings = repo.runner_rule_settings(conn)
        for row in repo.unsettled_runner_signals(conn):
            fields = _track(row, series.get(row["symbol"]), _rule(row["rule_version"], settings), d)
            repo.update_runner_signal(conn, row["id"], **fields)
            status = fields.get("status", row["status"])
            counts["entered"] += row["status"] == "waiting" and "entry" in fields
            counts["closed"] += status in CLOSED
            counts["open"] += status == "open"
        repo.prune_runner_signals(conn, today - KEPT)
    return counts
