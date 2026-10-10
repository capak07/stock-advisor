"""Daily live check of every source (spec §11): fetch each collector's canary and record it.

Usage: python -m advisor.health
Exit 1 when a core source fails, so the GitHub job fails and the owner gets an email.
This check is also the daily retry for sources whose circuit breaker is open: a passing check
resets a source's breaker, and a failing check never adds to its failure count.
"""

import json
import sys
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime

from advisor.collectors.base import Collector, CollectorResult, CollectorStatus, make_client
from advisor.collectors.cache import DiskCache
from advisor.collectors.registry import build_registry
from advisor.collectors.runner import SourceState, next_failures, run_collector
from advisor.config import Settings
from advisor.store import repo
from advisor.store.db import connect


def check_sources(
    collectors: Mapping[str, Collector],
    cache: DiskCache,
    states: Mapping[str, SourceState],
    now: datetime,
) -> list[tuple[CollectorResult, int]]:
    """Fetch every collector's canary once, ignoring the breaker.

    An empty answer fails the check only for collectors that must return records.
    """
    rows = []
    for name, collector in collectors.items():
        result = run_collector(
            collector, list(collector.canary), now, cache=cache, state=SourceState()
        )
        if (
            collector.canary_requires_records
            and result.status is CollectorStatus.OK
            and not result.records
        ):
            result = replace(
                result, status=CollectorStatus.FAILED, error="canary returned no records"
            )
        state = states.get(name, SourceState())
        failures = (
            next_failures(state, result)
            if result.status in (CollectorStatus.OK, CollectorStatus.PARTIAL)
            else state.consecutive_failures  # spec §4.1 counts failing runs; a failed check only records the attempt
        )
        rows.append((result, failures))
    return rows


def main(argv: list[str] | None = None) -> int:
    now = datetime.now(UTC)
    settings = Settings.from_env()
    with connect(settings.database_url) as conn, make_client() as client:
        collectors = build_registry(settings, client)
        states = repo.load_source_states(conn, collectors)
        rows = check_sources(collectors, DiskCache(settings.cache_dir), states, now)
        for result, failures in rows:
            repo.record_source_health(conn, None, result, failures, now, context="health")
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
