"""Runs one collector safely: circuit breaker, cadence-window cache, timing, error capture.

Cache use (spec §4.1):
- DAILY and WEEKLY collectors with `freshness` are served from entries saved in the current
  window (ET day or ISO week); only symbols missing from the window are fetched.
- `max_symbols` caps one call; capped-out symbols are served from older cache and fetched later.
- Any collector with `freshness` falls back to entries younger than `freshness` when it fails,
  and a partial per-symbol answer is backfilled the same way.
- An empty answer never replaces a cached whole list; per symbol, an OK empty answer is
  remembered for the window so the symbol isn't refetched.
"""

import time
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime

from pydantic import BaseModel

from advisor.collectors.base import (
    Cadence,
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


def in_window(cadence: Cadence, saved_at: datetime, as_of: datetime) -> bool:
    """True when `saved_at` falls in the same cadence window (ET day / ISO week) as `as_of`."""
    saved, now = saved_at.astimezone(ET), as_of.astimezone(ET)
    if cadence is Cadence.DAILY:
        return saved.date() == now.date()
    if cadence is Cadence.WEEKLY:
        return saved.isocalendar()[:2] == now.isocalendar()[:2]
    return False


def _cache_keys(collector: Collector, symbols: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(symbols)) if collector.scope is Scope.SYMBOLS else [WHOLE]


def _symbol_of(record: BaseModel) -> str | None:
    symbol = getattr(record, "symbol", None)
    return symbol if isinstance(symbol, str) and symbol else None


def _cached(
    collector: Collector, keys: Sequence[str], cache: DiskCache
) -> list[BaseModel] | None:
    """Cached records younger than `freshness` for these keys, or None if there are none."""
    if collector.freshness is None:
        return None
    found: list[BaseModel] = []
    for key in keys:
        found.extend(
            cache.get(collector.name, key, collector.record_type, collector.freshness) or []
        )
    return found or None


def _window_hits(
    collector: Collector, keys: Sequence[str], cache: DiskCache, as_of: datetime
) -> tuple[list[BaseModel], list[str]]:
    """Records saved in this cadence window, and the keys that still need a fetch."""
    if collector.freshness is None or collector.cadence is Cadence.PER_RUN:
        return [], list(keys)
    hits: list[BaseModel] = []
    missing: list[str] = []
    for key in keys:
        entry = cache.get_entry(collector.name, key, collector.record_type)
        if entry is not None and in_window(collector.cadence, entry[0], as_of):
            hits.extend(entry[1])
        else:
            missing.append(key)
    return hits, missing


def _store(
    collector: Collector,
    records: Sequence[BaseModel],
    cache: DiskCache,
    *,
    empty_symbols: Sequence[str] = (),
) -> None:
    """Cache what came back (per symbol for SYMBOLS scope); best-effort, never raises."""
    if collector.freshness is None or (not records and not empty_symbols):
        return
    groups: dict[str, list[BaseModel]] = defaultdict(list)
    for record in records:
        if collector.scope is Scope.SYMBOLS:
            key = _symbol_of(record)
            if key is None:
                continue  # unkeyable records are returned to the caller but never cached
        else:
            key = WHOLE
        groups[key].append(record)
    for symbol in empty_symbols:
        groups.setdefault(symbol, [])  # "nothing for this symbol", remembered for the window
    for key, group in groups.items():
        try:
            cache.put(collector.name, key, group)
        except Exception:
            pass  # cache is a fallback; a failed write must not lose a good fetch


def run_collector(
    collector: Collector,
    symbols: Sequence[str],
    as_of: datetime,
    *,
    cache: DiskCache,
    state: SourceState,
    use_window: bool = True,
) -> CollectorResult:
    keys = _cache_keys(collector, symbols)
    if breaker_open(state, as_of.astimezone(ET).date()):
        return CollectorResult(
            collector.name,
            CollectorStatus.SKIPPED,
            _cached(collector, keys, cache) or [],
            0,
            "circuit breaker open",
        )

    hits, missing = _window_hits(collector, keys, cache, as_of) if use_window else ([], keys)
    if keys and not missing:
        return CollectorResult(collector.name, CollectorStatus.OK, hits, 0, None)
    deferred: list[BaseModel] = []
    if collector.scope is Scope.SYMBOLS:
        fetch_symbols = missing[: collector.max_symbols] if collector.max_symbols else missing
        later = missing[len(fetch_symbols):]
        deferred = (_cached(collector, later, cache) or []) if later else []
    else:
        fetch_symbols = list(symbols)

    started = time.perf_counter()
    status, error = CollectorStatus.OK, None
    try:
        try:
            records = list(collector.fetch(fetch_symbols, as_of))
        except PartialFetch as exc:
            if not exc.records:
                raise  # nothing usable came back: a plain failure
            records = exc.records
            status, error = CollectorStatus.PARTIAL, f"PartialFetch: {exc}"[:500]
    except Exception as exc:  # any source failure is contained here
        latency = int((time.perf_counter() - started) * 1000)
        error = f"{type(exc).__name__}: {exc}"[:500]
        fallback_keys = fetch_symbols if collector.scope is Scope.SYMBOLS else keys
        served = hits + (_cached(collector, fallback_keys, cache) or []) + deferred
        if served:
            return CollectorResult(collector.name, CollectorStatus.STALE, served, latency, error)
        return CollectorResult(collector.name, CollectorStatus.FAILED, [], latency, error)

    latency = int((time.perf_counter() - started) * 1000)
    if status is CollectorStatus.OK:
        empty: list[str] = []
        if collector.scope is Scope.SYMBOLS and collector.cadence is not Cadence.PER_RUN:
            got = {_symbol_of(r) for r in records}
            empty = [s for s in fetch_symbols if s not in got]
        _store(collector, records, cache, empty_symbols=empty)
    elif collector.scope is Scope.SYMBOLS:  # partial: keep what came, backfill the rest
        _store(collector, records, cache)
        got = {_symbol_of(r) for r in records}
        records = records + (
            _cached(collector, [s for s in fetch_symbols if s not in got], cache) or []
        )
    return CollectorResult(collector.name, status, hits + records + deferred, latency, error)
