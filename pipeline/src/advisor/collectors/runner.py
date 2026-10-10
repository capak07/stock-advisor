"""Runs one collector safely: circuit breaker, timing, error capture, cache fallback."""

import time
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime

from pydantic import BaseModel

from advisor.collectors.base import (
    Collector,
    CollectorResult,
    CollectorStatus,
    PartialFetch,
    Scope,
)
from advisor.collectors.cache import DiskCache
from advisor.models import ET

BREAKER_THRESHOLD = 3
WHOLE = ""  # cache key for UNIVERSE and MARKET collectors, which return one list per call


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
    if result.status in (CollectorStatus.OK, CollectorStatus.PARTIAL):
        return 0  # the source answered; gaps in a partial result don't trip the breaker
    return state.consecutive_failures + 1


def _cache_keys(collector: Collector, symbols: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(symbols)) if collector.scope is Scope.SYMBOLS else [WHOLE]


def _cached(
    collector: Collector, symbols: Sequence[str], cache: DiskCache
) -> list[BaseModel] | None:
    """Fresh cached records for this request (per symbol for SYMBOLS scope), or None."""
    if collector.freshness is None:
        return None
    found: list[BaseModel] = []
    for key in _cache_keys(collector, symbols):
        found.extend(
            cache.get(collector.name, key, collector.record_type, collector.freshness) or []
        )
    return found or None


def _store(collector: Collector, records: Sequence[BaseModel], cache: DiskCache) -> None:
    """Cache non-empty results only, so an empty answer never replaces good data."""
    if collector.freshness is None or not records:
        return
    groups: dict[str, list[BaseModel]] = defaultdict(list)
    for record in records:
        groups[record.symbol if collector.scope is Scope.SYMBOLS else WHOLE].append(record)
    for key, group in groups.items():
        try:
            cache.put(collector.name, key, group)
        except (OSError, TypeError, ValueError):
            pass  # cache is a fallback; a failed write must not lose a good fetch


def run_collector(
    collector: Collector,
    symbols: Sequence[str],
    as_of: datetime,
    *,
    cache: DiskCache,
    state: SourceState,
) -> CollectorResult:
    if breaker_open(state, as_of.astimezone(ET).date()):
        return CollectorResult(
            collector.name,
            CollectorStatus.SKIPPED,
            _cached(collector, symbols, cache) or [],
            0,
            "circuit breaker open",
        )

    started = time.perf_counter()
    status, error = CollectorStatus.OK, None
    try:
        try:
            records = list(collector.fetch(symbols, as_of))
        except PartialFetch as exc:
            if not exc.records:
                raise  # nothing usable came back: a plain failure
            records = exc.records
            status, error = CollectorStatus.PARTIAL, f"PartialFetch: {exc}"[:500]
    except Exception as exc:  # any source failure is contained here
        latency = int((time.perf_counter() - started) * 1000)
        error = f"{type(exc).__name__}: {exc}"[:500]
        cached = _cached(collector, symbols, cache)
        if cached is not None:
            return CollectorResult(collector.name, CollectorStatus.STALE, cached, latency, error)
        return CollectorResult(collector.name, CollectorStatus.FAILED, [], latency, error)

    latency = int((time.perf_counter() - started) * 1000)
    _store(collector, records, cache)
    return CollectorResult(collector.name, status, records, latency, error)
