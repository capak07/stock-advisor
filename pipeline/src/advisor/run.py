"""Run orchestrator: one pre-open, pre-close, or early-close pass of the pipeline.

Usage: python -m advisor.run [--force-kind pre_open|pre_close|early_close] [--now ISO-8601]
"""

import argparse
import contextlib
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
from advisor.collectors.tracker import SourceTracker
from advisor.config import Settings
from advisor.enrich import EnrichTargets, ranked_shortlist, run_enrichment
from advisor.models import ET, AssetRef, AssetType, Market, RunKind, RunStatus, SymbolInfo
from advisor.prices import PriceFetch, fetch_daily_bars
from advisor.schedule import freshness_floor, missed_run_kind, resolve_run_kind
from advisor.store import repo
from advisor.store.db import connect

MIN_UNIVERSE = 1000  # fewer listed stocks than this means the symbol files were truncated
MIN_PRICED_FRACTION = 0.5
UNIVERSE_SOURCE = "nasdaq_symbols"
PRICES = "yfinance_bars"
PRICE_STAGE = frozenset({UNIVERSE_SOURCE, PRICES})


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


def priority_order(held: set[AssetRef], watch: set[AssetRef], asset_type: AssetType) -> list[str]:
    """Holdings first, then watchlist-only symbols, each alphabetical (spec §7.2)."""
    held_symbols = sorted(ref.symbol for ref in held if ref.asset_type is asset_type)
    watch_only = sorted(
        {ref.symbol for ref in watch if ref.asset_type is asset_type} - set(held_symbols)
    )
    return held_symbols + watch_only


def execute_run(
    deps: RunDeps, kind: RunKind, now_utc: datetime, *, min_universe: int = MIN_UNIVERSE
) -> RunOutcome:
    conn = deps.conn
    floor = freshness_floor(kind, now_utc)  # spec §10: older last bars count as missing
    repo.sweep_abandoned_runs(conn, now_utc)
    run_id = repo.create_run(conn, kind, now_utc.astimezone(ET).date())
    tracker = SourceTracker(
        deps.collectors, deps.cache, now_utc, repo.load_source_states(conn, deps.collectors)
    )

    def fetch_prices(symbols: Sequence[str]) -> PriceFetch:
        return fetch_daily_bars(symbols, run=lambda s: tracker.run(PRICES, s))

    def record_health() -> None:
        for result, failures in tracker.health_rows():
            repo.record_source_health(conn, run_id, result, failures, now_utc)

    try:
        held, watch = repo.load_held_symbols(conn), repo.load_watchlist(conn)
        priority = priority_order(held, watch, AssetType.STOCK)
        crypto = priority_order(held, watch, AssetType.CRYPTO)

        # Phase 1: holdings and watchlist are priced and saved before anything else can fail.
        first = fetch_prices(priority) if priority else PriceFetch({}, {})
        bars, flagged = dict(first.bars), dict(first.flagged)
        priority_rows = [screener.price_stats(s, bars[s]) for s in priority if s in bars]
        repo.write_features_live(
            conn,
            run_id,
            [
                (
                    AssetRef(r.symbol, AssetType.STOCK),
                    {
                        **r.as_features(),
                        "stale": not r.is_fresh(floor),
                        "unconfirmed_jump": r.last_day in flagged.get(r.symbol, ()),
                    },
                )
                for r in priority_rows
            ],
            now_utc,
        )

        # Phase 2: the rest of the market.
        universe: list[SymbolInfo] = list(tracker.run(UNIVERSE_SOURCE, []).records)
        universe_ok = len(universe) >= min_universe
        if universe_ok:
            repo.upsert_symbols(conn, Market.US, universe)
        rest = sorted({record.symbol for record in universe} - set(priority))
        if rest:
            second = fetch_prices(rest)
            bars = {**second.bars, **bars}
            flagged = {**second.flagged, **flagged}
        symbols = sorted(set(priority) | set(rest))

        passed = screener.hard_filter(bars, fresh_since=floor)
        fresh = sum(1 for history in bars.values() if history[-1].day >= floor)
        prices_ok = bool(symbols) and fresh >= MIN_PRICED_FRACTION * len(symbols)

        # Phase 3: enrichment, only for a run that can still publish.
        targets = EnrichTargets(
            priority_stocks=priority, crypto=crypto, ranked_stocks=ranked_shortlist(passed, priority)
        )
        enriched = universe_ok and prices_ok
        if enriched:
            run_enrichment(
                tracker,
                deps.collectors,
                [name for name in deps.collectors if name not in PRICE_STAGE],
                targets,
            )

        summary = {
            "universe": len(universe),
            "priced": len(bars),
            "passed_filters": len(passed),
            "priority": len(priority),
            "priority_unpriced": sorted(set(priority) - bars.keys()),
            "fresh": fresh,
            "fresh_since": floor.isoformat(),
            "shortlist": len(targets.stocks) if enriched else 0,
            "unconfirmed_jumps": len(flagged),
        }
        status = decide_status(
            tracker.merged(), deps.collectors, universe_ok=universe_ok, prices_ok=prices_ok
        )
        if status is RunStatus.FAILED:
            reasons = []
            if not universe_ok:
                reasons.append(f"universe too small ({len(universe)} < {min_universe})")
            if not prices_ok:
                reasons.append(f"too few fresh priced symbols ({fresh} of {len(symbols)})")
            summary["failed_reason"] = reasons
    except Exception as exc:
        with contextlib.suppress(Exception):  # never let bookkeeping hide the real error
            record_health()
        repo.finish_run(
            conn, run_id, RunStatus.FAILED,
            sources_ok=tracker.count_healthy(),
            sources_total=len(deps.collectors),
            summary={"error": f"{type(exc).__name__}: {exc}"[:500]},
        )
        raise

    record_health()
    repo.finish_run(
        conn, run_id, status,
        sources_ok=tracker.count_healthy(),
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
        missed = missed_run_kind(now)
        if missed is not None:  # exit 1 fails the GitHub job, so the owner gets an email
            print(
                f"{now.isoformat()}: {missed.value} run window missed"
                " (trigger arrived too late); no run."
            )
            return 1
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
