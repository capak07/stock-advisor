"""Runs one collector safely: circuit breaker, timing, error capture, cache fallback."""

import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime

from advisor.collectors.base import Collector, CollectorResult, CollectorStatus
from advisor.collectors.cache import DiskCache
from advisor.models import ET

BREAKER_THRESHOLD = 3


@dataclass(frozen=True)
class SourceState:
    consecutive_failures: int = 0
    last_attempt_et_date: date | None = None


def breaker_open(state: SourceState, today_et: date) -> bool:
    """Open after 3 straight failures, but allow one attempt on each new ET day (half-open)."""
    return (
        state.consecutive_failures >= BREAKER_THRESHOLD
        and state.last_attempt_et_date == today_et
    )


def next_failures(state: SourceState, result: CollectorResult) -> int:
    if result.status is CollectorStatus.SKIPPED:
        return state.consecutive_failures
    if result.status is CollectorStatus.OK:
        return 0
    return state.consecutive_failures + 1


def cache_key(symbols: Sequence[str]) -> str:
    return ",".join(sorted(symbols))


def run_collector(
    collector: Collector,
    symbols: Sequence[str],
    as_of: datetime,
    *,
    cache: DiskCache,
    state: SourceState,
) -> CollectorResult:
    key = cache_key(symbols)
    if breaker_open(state, as_of.astimezone(ET).date()):
        cached = None
        if collector.freshness is not None:
            cached = cache.get(collector.name, key, collector.record_type, collector.freshness)
        return CollectorResult(
            collector.name, CollectorStatus.SKIPPED, cached or [], 0, "circuit breaker open"
        )

    started = time.perf_counter()
    try:
        records = list(collector.fetch(symbols, as_of))
    except Exception as exc:  # any source failure is contained here
        latency = int((time.perf_counter() - started) * 1000)
        error = f"{type(exc).__name__}: {exc}"[:500]
        if collector.freshness is not None:
            cached = cache.get(collector.name, key, collector.record_type, collector.freshness)
            if cached is not None:
                return CollectorResult(collector.name, CollectorStatus.STALE, cached, latency, error)
        return CollectorResult(collector.name, CollectorStatus.FAILED, [], latency, error)

    latency = int((time.perf_counter() - started) * 1000)
    if collector.freshness is not None:
        try:
            cache.put(collector.name, key, records)
        except (OSError, TypeError, ValueError):
            # cache is a fallback; a failed write must not lose a good fetch
            pass
    return CollectorResult(collector.name, CollectorStatus.OK, records, latency)
