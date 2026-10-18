"""Daily live check of every source (spec §11): fetch each collector's canary and record it.

Usage: python -m advisor.health
Exit 1 when a core source fails, so the GitHub job fails and the owner gets an email.
This check is also the daily retry for sources whose circuit breaker is open: a passing check
resets a source's breaker, and a failing check never adds to its failure count.
Sources are checked concurrently, each within its own time budget, and rows are written as they finish.
"""

import json
import sys
import time
from collections.abc import Iterator, Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from datetime import UTC, datetime

from advisor.collectors.base import (
    Collector,
    CollectorResult,
    CollectorStatus,
    deadline,
    make_client,
)
from advisor.collectors.cache import DiskCache
from advisor.collectors.registry import build_registry
from advisor.collectors.runner import SourceState, next_failures, run_collector
from advisor.config import Settings
from advisor.store import repo
from advisor.store.db import connect

HEALTH_WORKERS = 8
SOURCE_BUDGET_SECONDS = 120.0


def check_source(
    collector: Collector,
    cache: DiskCache,
    state: SourceState,
    now: datetime,
    *,
    budget: float = SOURCE_BUDGET_SECONDS,
) -> tuple[CollectorResult, int]:
    """One live canary fetch, bypassing the breaker and the cadence cache, within `budget` seconds.

    An empty answer fails only for collectors that must return records. A failed check never
    adds to the failure count (spec §4.1 counts failing runs); a passing one resets it.
    """
    try:
        with deadline(time.monotonic() + budget):
            result = run_collector(
                collector, list(collector.canary), now, cache=cache, state=SourceState(),
                use_window=False,
            )
    except Exception as exc:  # a broken collector must not stop the other checks
        result = CollectorResult(
            collector.name, CollectorStatus.FAILED, [], 0, f"{type(exc).__name__}: {exc}"[:500]
        )
    if (
        collector.canary_requires_records
        and result.status is CollectorStatus.OK
        and not result.records
    ):
        result = replace(result, status=CollectorStatus.FAILED, error="canary returned no records")
    failures = (
        next_failures(state, result)
        if result.status in (CollectorStatus.OK, CollectorStatus.PARTIAL)
        else state.consecutive_failures
    )
    return result, failures


def iter_checks(
    collectors: Mapping[str, Collector],
    cache: DiskCache,
    states: Mapping[str, SourceState],
    now: datetime,
    *,
    workers: int = HEALTH_WORKERS,
    budget: float = SOURCE_BUDGET_SECONDS,
) -> Iterator[tuple[CollectorResult, int]]:
    """Check every source concurrently; yield each (result, failures) as soon as it finishes."""
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(
                check_source, collector, cache, states.get(name, SourceState()), now, budget=budget
            )
            for name, collector in collectors.items()
        ]
        for future in as_completed(futures):
            yield future.result()


def check_sources(
    collectors: Mapping[str, Collector],
    cache: DiskCache,
    states: Mapping[str, SourceState],
    now: datetime,
    *,
    workers: int = HEALTH_WORKERS,
    budget: float = SOURCE_BUDGET_SECONDS,
) -> list[tuple[CollectorResult, int]]:
    return list(iter_checks(collectors, cache, states, now, workers=workers, budget=budget))


def main(argv: list[str] | None = None) -> int:
    now = datetime.now(UTC)
    settings = Settings.from_env()
    rows: list[tuple[CollectorResult, int]] = []
    with connect(settings.database_url) as conn, make_client() as client:
        collectors = build_registry(settings, client)
        try:
            repo.write_sources(conn, collectors)  # what the dashboard's Source health page lists
        except Exception as exc:  # the registry only feeds the dashboard; the check carries on
            print(f"sources not written: {type(exc).__name__}: {exc}", file=sys.stderr)
        states = repo.load_source_states(conn, collectors)
        for result, failures in iter_checks(collectors, DiskCache(settings.cache_dir), states, now):
            repo.record_source_health(conn, None, result, failures, now, context="health")
            rows.append((result, failures))
    print(json.dumps({result.name: result.status.value for result, _ in rows}))
    core_failing = [
        result.name
        for result, _ in rows
        if collectors[result.name].core and result.status is not CollectorStatus.OK
    ]
    if core_failing:
        print(f"core sources failing: {', '.join(core_failing)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
