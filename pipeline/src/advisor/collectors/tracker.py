"""Runs collectors for one pipeline run and keeps one merged result per source.

A source can be called more than once per run (holdings phase, market phase); its health row
must still be a single row whose status tells the truth about the whole run.
"""

import threading
from collections.abc import Mapping, Sequence
from datetime import datetime

from advisor.collectors.base import Collector, CollectorResult, CollectorStatus
from advisor.collectors.cache import DiskCache
from advisor.collectors.runner import SourceState, next_failures, run_collector

UNHEALTHY = frozenset({
    CollectorStatus.PARTIAL,
    CollectorStatus.STALE,
    CollectorStatus.FAILED,
    CollectorStatus.SKIPPED,
})


def merge_results(results: Sequence[CollectorResult]) -> CollectorResult:
    """Combine several calls to one source into the single result its health row reports."""
    statuses = {r.status for r in results}
    if len(statuses) == 1:
        status = next(iter(statuses))
    elif statuses <= {CollectorStatus.STALE, CollectorStatus.FAILED}:
        status = CollectorStatus.STALE
    else:
        status = CollectorStatus.PARTIAL
    return CollectorResult(
        name=results[0].name,
        status=status,
        records=[record for r in results for record in r.records],
        latency_ms=sum(r.latency_ms for r in results),
        error=next((r.error for r in results if r.error), None),
    )


class SourceTracker:
    def __init__(
        self,
        collectors: Mapping[str, Collector],
        cache: DiskCache,
        as_of: datetime,
        states: Mapping[str, SourceState],
    ) -> None:
        self._collectors = collectors
        self._cache = cache
        self._as_of = as_of
        self._states = dict(states)
        self._calls: dict[str, list[CollectorResult]] = {}
        self._lock = threading.Lock()

    def _state(self, name: str) -> SourceState:
        return self._states.get(name, SourceState())

    def run(self, name: str, symbols: Sequence[str]) -> CollectorResult:
        collector = self._collectors[name]  # an unknown name is a caller bug: let it raise
        try:
            result = run_collector(
                collector, symbols, self._as_of, cache=self._cache, state=self._state(name)
            )
        except Exception as exc:  # one collector must never fail the whole run
            result = CollectorResult(
                name, CollectorStatus.FAILED, [], 0, f"{type(exc).__name__}: {exc}"[:500]
            )
        with self._lock:
            self._calls.setdefault(name, []).append(result)
        return result

    def merged(self) -> list[CollectorResult]:
        with self._lock:
            return [merge_results(calls) for calls in self._calls.values()]

    def health_rows(self) -> list[tuple[CollectorResult, int]]:
        return [(r, next_failures(self._state(r.name), r)) for r in self.merged()]

    def count_healthy(self) -> int:
        """Registered sources minus those unhealthy this run; a source this run didn't need counts as healthy."""
        unhealthy = {r.name for r in self.merged() if r.status in UNHEALTHY}
        return len(self._collectors) - len(unhealthy)
