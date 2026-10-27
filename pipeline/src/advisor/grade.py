"""Grading picks and holding actions (spec §6.5): the early-exit check, and stage 9."""

from collections.abc import Mapping, Sequence
from datetime import date, datetime

import psycopg

from advisor.markets import MARKETS, market_of
from advisor.model.market_run import PARTIAL_KINDS, model_failure
from advisor.model.market_run import (
    feature_day as market_feature_day,  # grade() has a feature_day parameter
)
from advisor.models import (
    ET,
    AssetRef,
    AssetType,
    DailyBar,
    Market,
    Outcome,
    PredictionRow,
    RunKind,
)
from advisor.recommend.verdicts import AVOID_P
from advisor.store import repo
from advisor.store.repo import OpenPick


def exit_early(picks: Sequence[OpenPick], rows: Mapping[str, list[PredictionRow]]) -> list[int]:
    """Ids of the picks whose forecast at their own horizon has fallen to the avoid line.

    A pick the run has no forecast for at its horizon isn't flagged.
    """
    flagged = []
    for pick in picks:
        row = next((r for r in rows.get(pick.symbol, []) if r.horizon_days == pick.horizon_days), None)
        if row is not None and row.p_beat <= AVOID_P:
            flagged.append(pick.id)
    return flagged


def grade(
    entry: float,
    stop: float | None,
    feature_day: date,
    exit_by: date,
    closes: Mapping[date, float],
    bench_ref: float,
    bench_closes: Mapping[date, float],
    fee_pct: float,
    us: bool,
    exit_now: date | None = None,
) -> Outcome | None:
    """How a hold that started at `feature_day`'s close ended, or None while it hasn't.

    The closes after the feature day are walked in order up to exit-by (or `exit_now`, if
    sooner): the first at or under the stop exits there. Otherwise an early exit leaves at
    `exit_now`'s close, and the rest at exit-by's close, or the last one before it when exit-by
    had no session. Exit-by's exit waits for a close on or after it, so the close it takes is
    final. The benchmark exits on the same day; without its close that day nothing is graded.
    """
    end = exit_by if exit_now is None else min(exit_by, exit_now)
    held = sorted(d for d in closes if feature_day < d <= end)
    exit_day = next((d for d in held if stop is not None and closes[d] <= stop), None)
    reason = "stop"
    if exit_day is None:
        if exit_now is not None and exit_now <= exit_by:
            exit_day, reason = (exit_now if exit_now in closes else None), "exit_early"
        elif held and any(d >= exit_by for d in closes):
            exit_day, reason = held[-1], "exit_by"
    if exit_day is None or exit_day not in bench_closes:
        return None
    exit_price = closes[exit_day]
    ret = exit_price / entry - 1
    bench_ret = bench_closes[exit_day] / bench_ref - 1
    excess = ret - bench_ret
    return Outcome(
        exit_day=exit_day,
        exit_price=exit_price,
        exit_reason=reason,
        ret=ret,
        ret_net_of_fx=ret - 2 * fee_pct / 100 if us else ret,
        bench_ret=bench_ret,
        excess=excess,
        beat=excess > 0,
        hit_stop=reason == "stop",
    )


def grade_stage(
    conn: psycopg.Connection,
    run_id: int,
    bars: Mapping[str, Sequence[DailyBar]],
    rows: Mapping[str, list[PredictionRow]],
    kind: RunKind,
    now_utc: datetime,
) -> dict:
    """Stage 9: exits open picks early on a pre-close run, then grades the picks and stock
    holding actions whose time is up. Returns `summary["graded"]`; a failure is caught and
    returned as `model_failure`, never raised.

    Closes come from this run's bars, or the stored ones for a symbol it didn't price. On a
    pre-close run today's bar is partial (the 15:15 price), not a close: stops and exit-by dates
    are graded from final closes only. Only an early exit reads it, leaving at the run's own price:
    a pick whose P fell to the avoid line, or whose price is at or under its stop. One that can't
    be graded at that price stays open, and the next pre-close run tries again.
    """
    try:
        fee_pct = repo.fee_settings(conn)[0]
        today = now_utc.astimezone(ET).date()
        partial_run = kind in PARTIAL_KINDS
        days: dict[Market, tuple[date, bool]] = {}  # each market's feature day, and if it's partial
        for market in Market if partial_run else ():
            if bars.get(MARKETS[market].benchmark):
                day, partial = market_feature_day(market, bars, kind, now_utc)
                days[market] = (day.date(), partial)

        picks = repo.open_picks(conn)
        actions = repo.actions_to_grade(conn)
        starts = [p.feature_day for p in picks if p.feature_day is not None] + [a.feature_day for a in actions]
        symbols = {p.symbol for p in picks} | {a.symbol for a in actions}
        symbols |= {MARKETS[m].benchmark for m in Market}
        closes = {s: {b.day: b.close for b in bars[s]} for s in symbols if s in bars}
        missing = [AssetRef(s, AssetType.STOCK) for s in sorted(symbols - closes.keys())]
        if missing and starts:
            stored = repo.stored_closes(conn, missing, min(starts))
            closes |= {ref.symbol: found for ref, found in stored.items()}

        finals: dict[str, dict[date, float]] = {}

        def final(symbol: str) -> dict[date, float]:
            """The symbol's closes without today's partial bar."""
            if symbol not in finals:
                finals[symbol] = {
                    d: c for d, c in closes.get(symbol, {}).items() if not (partial_run and d == today)
                }
            return finals[symbol]

        def grade_pick(pick: OpenPick, exit_now: date | None) -> Outcome | None:
            if pick.feature_day is None or pick.bench_ref_price is None:
                return None  # made before migration 0009
            market = Market(pick.market)
            benchmark = MARKETS[market].benchmark
            stock, bench = (
                (closes.get(pick.symbol, {}), closes.get(benchmark, {}))
                if exit_now is not None
                else (final(pick.symbol), final(benchmark))
            )
            return grade(
                pick.entry_ref_price, pick.stop, pick.feature_day, pick.exit_by, stock,
                pick.bench_ref_price, bench, fee_pct, market is Market.US, exit_now,
            )

        flagged = set(exit_early(picks, rows)) if partial_run else set()
        graded: list[tuple[int, Outcome]] = []  # status 'graded'
        exited: list[tuple[int, Outcome]] = []  # status 'exited_early'
        for pick in picks:
            outcome = grade_pick(pick, None)  # a stop or exit-by, from final closes
            if outcome is not None:
                graded.append((pick.id, outcome))
                continue
            if Market(pick.market) not in days:
                continue
            day, partial = days[Market(pick.market)]
            price = closes.get(pick.symbol, {}).get(day)
            stopped = partial and price is not None and price <= pick.stop
            if pick.id in flagged or stopped:
                outcome = grade_pick(pick, day)
                if outcome is not None:
                    # a flagged pick whose hold had already ended leaves at exit-by: a normal grade
                    (graded if outcome.exit_reason == "exit_by" else exited).append((pick.id, outcome))

        graded_actions = []
        for action in actions:
            market = market_of(action.symbol)
            benchmark = MARKETS[market].benchmark
            outcome = grade(
                action.ref_price, action.trailing_stop, action.feature_day, action.exit_by, final(action.symbol),
                action.bench_ref_price, final(benchmark), fee_pct, market is Market.US,
            )
            if outcome is not None:
                graded_actions.append((action, outcome))

        with conn.transaction():  # every grade of the run lands together or not at all
            repo.write_pick_outcomes(conn, [*exited, *graded])
            repo.mark_exited_early(conn, [pick_id for pick_id, _ in exited])
            repo.set_pick_status(conn, [pick_id for pick_id, _ in graded], "graded")
            repo.write_action_outcomes(conn, graded_actions)
    except Exception as exc:
        return model_failure(exc)
    return {"picks": len(graded), "exited_early": len(exited), "actions": len(graded_actions)}
