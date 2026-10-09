"""Run orchestrator: one pre-open, pre-close, or early-close pass of the pipeline.

Usage: python -m advisor.run [--force-kind pre_open|pre_close|early_close] [--now ISO-8601]
"""

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

import psycopg

from advisor import screener
from advisor.collectors.base import Collector, CollectorResult, CollectorStatus, make_client
from advisor.collectors.cache import DiskCache
from advisor.collectors.registry import build_registry
from advisor.collectors.runner import next_failures, run_collector
from advisor.config import Settings
from advisor.models import ET, AssetRef, AssetType, RunKind, RunStatus, SymbolInfo
from advisor.prices import fetch_daily_bars
from advisor.schedule import resolve_run_kind
from advisor.store import repo
from advisor.store.db import connect

MIN_UNIVERSE = 1000  # fewer listed stocks than this means the symbol files were truncated
MIN_PRICED_FRACTION = 0.5
UNHEALTHY = frozenset({CollectorStatus.FAILED, CollectorStatus.STALE, CollectorStatus.SKIPPED})


@dataclass(frozen=True)
class RunDeps:
    conn: psycopg.Connection
    cache: DiskCache
    collectors: Mapping[str, Collector]


@dataclass(frozen=True)
class RunOutcome:
    run_id: int
    status: RunStatus
    summary: dict


def decide_status(
    results: Sequence[CollectorResult],
    collectors: Mapping[str, Collector],
    *,
    universe_ok: bool,
    prices_ok: bool,
) -> RunStatus:
    if not (universe_ok and prices_ok):
        return RunStatus.FAILED
    if any(collectors[r.name].core and r.status is not CollectorStatus.OK for r in results):
        return RunStatus.DEGRADED
    return RunStatus.SUCCESS


def count_healthy(results: Sequence[CollectorResult], collectors: Mapping[str, Collector]) -> int:
    unhealthy = {r.name for r in results if r.status in UNHEALTHY}
    return len(collectors) - len(unhealthy)


def execute_run(
    deps: RunDeps, kind: RunKind, now_utc: datetime, *, min_universe: int = MIN_UNIVERSE
) -> RunOutcome:
    conn = deps.conn
    run_id = repo.create_run(conn, kind, now_utc.astimezone(ET).date())
    results: list[CollectorResult] = []

    def run(name: str, symbols: Sequence[str]) -> CollectorResult:
        state = repo.load_source_state(conn, name)
        result = run_collector(
            deps.collectors[name], symbols, now_utc, cache=deps.cache, state=state
        )
        repo.record_source_health(conn, run_id, result, next_failures(state, result), now_utc)
        results.append(result)
        return result

    try:
        priority_refs = repo.load_held_symbols(conn) | repo.load_watchlist(conn)
        priority = {ref.symbol for ref in priority_refs if ref.asset_type is AssetType.STOCK}

        universe: list[SymbolInfo] = list(run("nasdaq_symbols", []).records)
        if len(universe) >= min_universe:
            repo.upsert_symbols(conn, universe)
        symbols = sorted({record.symbol for record in universe} | priority)

        prices = fetch_daily_bars(
            symbols,
            primary_run=lambda s: run("alpaca_bars", s),
            fallback_run=lambda s: run("yfinance_bars", s),
        )

        # Holdings and watchlist first, so their data is saved before anything else can fail.
        priority_rows = [
            screener.price_stats(s, prices.bars[s]) for s in sorted(priority) if s in prices.bars
        ]
        repo.write_features_live(
            conn,
            run_id,
            [(AssetRef(r.symbol, AssetType.STOCK), r.as_features()) for r in priority_rows],
            now_utc,
        )

        passed = screener.hard_filter(prices.bars)
        summary = {
            "universe": len(universe),
            "priced": len(prices.bars),
            "passed_filters": len(passed),
            "priority": len(priority),
            "priority_unpriced": sorted(priority - prices.bars.keys()),
        }
        status = decide_status(
            results,
            deps.collectors,
            universe_ok=len(universe) >= min_universe,
            prices_ok=bool(symbols) and len(prices.bars) >= MIN_PRICED_FRACTION * len(symbols),
        )
    except Exception as exc:
        repo.finish_run(
            conn, run_id, RunStatus.FAILED,
            sources_ok=count_healthy(results, deps.collectors),
            sources_total=len(deps.collectors),
            summary={"error": f"{type(exc).__name__}: {exc}"[:500]},
        )
        raise

    repo.finish_run(
        conn, run_id, status,
        sources_ok=count_healthy(results, deps.collectors),
        sources_total=len(deps.collectors),
        summary=summary,
    )
    return RunOutcome(run_id, status, summary)


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="advisor.run")
    parser.add_argument("--force-kind", choices=[kind.value for kind in RunKind])
    parser.add_argument("--now", help="ISO-8601 timestamp to use instead of the current time")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    now = datetime.fromisoformat(args.now) if args.now else datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)

    kind = RunKind(args.force_kind) if args.force_kind else resolve_run_kind(now)
    if kind is None:
        print(f"{now.isoformat()}: outside every run window or market closed; nothing to do.")
        return 0

    settings = Settings.from_env()
    with connect(settings.database_url) as conn:
        if not args.force_kind and repo.has_published_run(conn, kind, now.astimezone(ET).date()):
            print(f"{kind.value} already published today; nothing to do.")
            return 0
        with make_client() as client:
            deps = RunDeps(conn, DiskCache(settings.cache_dir), build_registry(settings, client))
            outcome = execute_run(deps, kind, now)

    print(json.dumps({"run_id": outcome.run_id, "status": outcome.status.value, **outcome.summary}))
    return 1 if outcome.status is RunStatus.FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
