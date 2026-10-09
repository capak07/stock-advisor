from datetime import UTC, date, datetime, timedelta

import httpx

from advisor.collectors.base import Cadence, CollectorResult, CollectorStatus
from advisor.collectors.cache import DiskCache
from advisor.collectors.runner import SourceState, breaker_open, next_failures, run_collector
from advisor.models import SymbolInfo
from fakes import FakeCollector, info

NOW = datetime(2026, 10, 14, 12, 15, tzinfo=UTC)  # 08:15 ET
TODAY = date(2026, 10, 14)


def universe_collector(**kwargs) -> FakeCollector:
    defaults = dict(
        name="universe",
        records_for=lambda symbols: [info("AAPL")],
        record_type=SymbolInfo,
        cadence=Cadence.DAILY,
        freshness=timedelta(days=3),
    )
    return FakeCollector(**{**defaults, **kwargs})


def test_success_returns_ok_and_caches(tmp_path):
    cache = DiskCache(tmp_path, clock=lambda: NOW)
    result = run_collector(universe_collector(), [], NOW, cache=cache, state=SourceState())
    assert result.status is CollectorStatus.OK
    assert [r.symbol for r in result.records] == ["AAPL"]
    assert cache.get("universe", "", SymbolInfo, timedelta(days=1)) is not None


def test_failure_falls_back_to_fresh_cache_as_stale(tmp_path):
    cache = DiskCache(tmp_path, clock=lambda: NOW)
    cache.put("universe", "", [info("MSFT")])
    collector = universe_collector(error=httpx.ConnectError("down"))
    result = run_collector(collector, [], NOW, cache=cache, state=SourceState())
    assert result.status is CollectorStatus.STALE
    assert [r.symbol for r in result.records] == ["MSFT"]
    assert result.error == "ConnectError: down"


def test_failure_without_cache_is_failed(tmp_path):
    collector = universe_collector(error=ValueError("bad payload"), freshness=None)
    result = run_collector(
        collector, [], NOW, cache=DiskCache(tmp_path), state=SourceState()
    )
    assert result.status is CollectorStatus.FAILED
    assert result.records == []
    assert result.error == "ValueError: bad payload"


def test_open_breaker_skips_without_fetching(tmp_path):
    collector = universe_collector()
    state = SourceState(consecutive_failures=3, last_attempt_et_date=TODAY)
    result = run_collector(collector, [], NOW, cache=DiskCache(tmp_path), state=state)
    assert result.status is CollectorStatus.SKIPPED
    assert collector.calls == []


def test_breaker_is_half_open_on_a_new_day():
    yesterday = SourceState(consecutive_failures=5, last_attempt_et_date=date(2026, 10, 13))
    assert breaker_open(yesterday, TODAY) is False
    assert breaker_open(SourceState(2, TODAY), TODAY) is False
    assert breaker_open(SourceState(3, TODAY), TODAY) is True


def test_next_failures_counts_consecutive_failures():
    state = SourceState(consecutive_failures=2)

    def result(status: CollectorStatus) -> CollectorResult:
        return CollectorResult("s", status, [], 0)

    assert next_failures(state, result(CollectorStatus.OK)) == 0
    assert next_failures(state, result(CollectorStatus.FAILED)) == 3
    assert next_failures(state, result(CollectorStatus.STALE)) == 3
    assert next_failures(state, result(CollectorStatus.SKIPPED)) == 2
