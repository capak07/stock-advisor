from datetime import UTC, date, datetime, timedelta

import httpx
from pydantic import BaseModel

from advisor.collectors.base import Cadence, CollectorResult, CollectorStatus, PartialFetch, Scope
from advisor.collectors.cache import DiskCache
from advisor.collectors.runner import (
    SourceState,
    breaker_open,
    in_window,
    next_failures,
    run_collector,
)
from advisor.models import SymbolInfo
from fakes import FakeCollector, bar, info

NOW = datetime(2026, 10, 14, 12, 15, tzinfo=UTC)  # 08:15 ET
TODAY = date(2026, 10, 14)


def universe_collector(**kwargs) -> FakeCollector:
    defaults = dict(
        name="universe",
        records_for=lambda symbols: [info("AAPL")],
        record_type=SymbolInfo,
        cadence=Cadence.PER_RUN,
        freshness=timedelta(days=3),
        scope=Scope.UNIVERSE,
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
    assert next_failures(state, result(CollectorStatus.PARTIAL)) == 0
    assert next_failures(state, result(CollectorStatus.SKIPPED)) == 2


def test_cache_write_failure_still_returns_ok(tmp_path):
    class FailingCache(DiskCache):
        def put(self, source: str, key: str, records) -> None:
            raise OSError("disk full")

    cache = FailingCache(tmp_path, clock=lambda: NOW)
    result = run_collector(universe_collector(), [], NOW, cache=cache, state=SourceState())
    assert result.status is CollectorStatus.OK
    assert [r.symbol for r in result.records] == ["AAPL"]


def test_open_breaker_serves_fresh_cache_without_fetching(tmp_path):
    cache = DiskCache(tmp_path, clock=lambda: NOW)
    cache.put("universe", "", [info("MSFT")])
    collector = universe_collector()
    state = SourceState(consecutive_failures=3, last_attempt_et_date=TODAY)
    result = run_collector(collector, [], NOW, cache=cache, state=state)
    assert result.status is CollectorStatus.SKIPPED
    assert [r.symbol for r in result.records] == ["MSFT"]
    assert result.error == "circuit breaker open"
    assert collector.calls == []


def bars_collector(**kwargs) -> FakeCollector:
    defaults = dict(
        name="bars",
        records_for=lambda symbols: [bar(s, TODAY, 10.0) for s in symbols],
        freshness=timedelta(days=1),
    )
    return FakeCollector(**{**defaults, **kwargs})


def test_symbols_scope_caches_per_symbol_and_serves_requested_symbols_on_failure(tmp_path):
    cache = DiskCache(tmp_path, clock=lambda: NOW)
    run_collector(bars_collector(), ["AAA", "BBB"], NOW, cache=cache, state=SourceState())
    failing = bars_collector(error=httpx.ConnectError("down"))
    result = run_collector(failing, ["BBB", "CCC"], NOW, cache=cache, state=SourceState())
    assert result.status is CollectorStatus.STALE
    assert [r.symbol for r in result.records] == ["BBB"]


def test_empty_results_never_overwrite_a_good_cache_entry(tmp_path):
    cache = DiskCache(tmp_path, clock=lambda: NOW)
    run_collector(universe_collector(), [], NOW, cache=cache, state=SourceState())
    empty = universe_collector(records_for=lambda symbols: [])
    assert run_collector(empty, [], NOW, cache=cache, state=SourceState()).records == []
    failing = universe_collector(error=httpx.ConnectError("down"))
    result = run_collector(failing, [], NOW, cache=cache, state=SourceState())
    assert result.status is CollectorStatus.STALE
    assert [r.symbol for r in result.records] == ["AAPL"]


def test_partial_fetch_keeps_records_and_caches_them(tmp_path):
    cache = DiskCache(tmp_path, clock=lambda: NOW)
    partial = bars_collector(error=PartialFetch([bar("AAA", TODAY, 10.0)], "1 of 2 requests failed"))
    result = run_collector(partial, ["AAA", "BBB"], NOW, cache=cache, state=SourceState())
    assert result.status is CollectorStatus.PARTIAL
    assert [r.symbol for r in result.records] == ["AAA"]
    assert result.error == "PartialFetch: 1 of 2 requests failed"
    failing = bars_collector(error=httpx.ConnectError("down"))
    stale = run_collector(failing, ["AAA"], NOW, cache=cache, state=SourceState())
    assert [r.symbol for r in stale.records] == ["AAA"]


def test_empty_partial_fetch_is_a_failure(tmp_path):
    cache = DiskCache(tmp_path, clock=lambda: NOW)
    empty = bars_collector(error=PartialFetch([], "all 2 requests failed"))
    result = run_collector(empty, ["AAA", "BBB"], NOW, cache=cache, state=SourceState())
    assert result.status is CollectorStatus.FAILED
    assert result.error == "PartialFetch: all 2 requests failed"
    assert next_failures(SourceState(1), result) == 2
    run_collector(bars_collector(), ["AAA"], NOW, cache=cache, state=SourceState())
    stale = run_collector(empty, ["AAA"], NOW, cache=cache, state=SourceState())
    assert stale.status is CollectorStatus.STALE
    assert [r.symbol for r in stale.records] == ["AAA"]


class Loose(BaseModel):
    symbol: str | None = None


def test_records_without_a_symbol_are_returned_but_not_cached(tmp_path):
    cache = DiskCache(tmp_path, clock=lambda: NOW)
    loose = FakeCollector(
        "loose",
        records_for=lambda symbols: [Loose(symbol=None), Loose(symbol="AAA")],
        record_type=Loose,
        freshness=timedelta(days=1),
    )
    result = run_collector(loose, ["AAA"], NOW, cache=cache, state=SourceState())
    assert result.status is CollectorStatus.OK and len(result.records) == 2
    loose.error = httpx.ConnectError("down")
    stale = run_collector(loose, ["AAA"], NOW, cache=cache, state=SourceState())
    assert stale.status is CollectorStatus.STALE
    assert [r.symbol for r in stale.records] == ["AAA"]


def test_partial_market_result_does_not_replace_cache(tmp_path):
    cache = DiskCache(tmp_path, clock=lambda: NOW)
    market = FakeCollector(
        "market",
        records_for=lambda symbols: [info("A"), info("B")],
        record_type=SymbolInfo,
        freshness=timedelta(days=1),
        scope=Scope.MARKET,
    )
    run_collector(market, [], NOW, cache=cache, state=SourceState())
    market.error = PartialFetch([info("A")], "1 of 2")
    partial = run_collector(market, [], NOW, cache=cache, state=SourceState())
    assert partial.status is CollectorStatus.PARTIAL and len(partial.records) == 1
    market.error = httpx.ConnectError("down")
    stale = run_collector(market, [], NOW, cache=cache, state=SourceState())
    assert stale.status is CollectorStatus.STALE
    assert [r.symbol for r in stale.records] == ["A", "B"]


def windowed(cadence=Cadence.DAILY, **kwargs) -> FakeCollector:
    defaults = dict(
        name="win",
        records_for=lambda syms: [bar(s, TODAY, 1.0) for s in syms if s != "NONE"],
        cadence=cadence,
        freshness=timedelta(days=10),
    )
    return FakeCollector(**{**defaults, **kwargs})


def clocked_cache(tmp_path, start):
    now = [start]
    return DiskCache(tmp_path, clock=lambda: now[0]), now


def test_in_window_uses_et_days_and_iso_weeks():
    late_monday_et = datetime(2026, 10, 13, 3, 30, tzinfo=UTC)  # 23:30 ET on Monday 12 Oct
    assert in_window(Cadence.DAILY, late_monday_et, datetime(2026, 10, 12, 14, 0, tzinfo=UTC))
    assert not in_window(Cadence.DAILY, late_monday_et, datetime(2026, 10, 13, 14, 0, tzinfo=UTC))
    monday = datetime(2026, 10, 12, 14, 0, tzinfo=UTC)
    assert in_window(Cadence.WEEKLY, monday, datetime(2026, 10, 18, 14, 0, tzinfo=UTC))
    assert not in_window(Cadence.WEEKLY, monday, datetime(2026, 10, 19, 14, 0, tzinfo=UTC))
    assert not in_window(Cadence.PER_RUN, monday, monday)


def test_daily_collector_fetches_only_symbols_missing_from_todays_window(tmp_path):
    cache, now = clocked_cache(tmp_path, NOW)
    collector = windowed()
    run_collector(collector, ["AAA", "BBB"], NOW, cache=cache, state=SourceState())
    later = NOW + timedelta(hours=3)
    now[0] = later
    result = run_collector(collector, ["BBB", "CCC"], later, cache=cache, state=SourceState())
    assert collector.calls == [["AAA", "BBB"], ["CCC"]]
    assert result.status is CollectorStatus.OK
    assert sorted(r.symbol for r in result.records) == ["BBB", "CCC"]


def test_a_fully_cached_request_does_not_fetch(tmp_path):
    cache, _ = clocked_cache(tmp_path, NOW)
    collector = windowed()
    run_collector(collector, ["AAA"], NOW, cache=cache, state=SourceState())
    result = run_collector(collector, ["AAA"], NOW, cache=cache, state=SourceState())
    assert collector.calls == [["AAA"]]
    assert (result.status, result.latency_ms) == (CollectorStatus.OK, 0)
    assert [r.symbol for r in result.records] == ["AAA"]


def test_a_new_day_fetches_again(tmp_path):
    cache, now = clocked_cache(tmp_path, NOW)
    collector = windowed()
    run_collector(collector, ["AAA"], NOW, cache=cache, state=SourceState())
    tomorrow = NOW + timedelta(days=1)
    now[0] = tomorrow
    run_collector(collector, ["AAA"], tomorrow, cache=cache, state=SourceState())
    assert collector.calls == [["AAA"], ["AAA"]]


def test_weekly_collectors_reuse_the_whole_iso_week(tmp_path):
    monday = datetime(2026, 10, 12, 13, 0, tzinfo=UTC)
    cache, now = clocked_cache(tmp_path, monday)
    collector = windowed(Cadence.WEEKLY)
    for moment in (monday, monday + timedelta(days=4), monday + timedelta(days=7)):
        now[0] = moment
        run_collector(collector, ["AAA"], moment, cache=cache, state=SourceState())
    assert collector.calls == [["AAA"], ["AAA"]]


def test_symbols_without_records_are_remembered_for_the_window(tmp_path):
    cache, _ = clocked_cache(tmp_path, NOW)
    collector = windowed()
    run_collector(collector, ["AAA", "NONE"], NOW, cache=cache, state=SourceState())
    result = run_collector(collector, ["NONE"], NOW, cache=cache, state=SourceState())
    assert collector.calls == [["AAA", "NONE"]]
    assert (result.status, result.records) == (CollectorStatus.OK, [])


def test_whole_list_collectors_skip_the_fetch_within_the_window(tmp_path):
    cache, _ = clocked_cache(tmp_path, NOW)
    collector = FakeCollector(
        "macro", scope=Scope.MARKET, record_type=SymbolInfo, records_for=lambda s: [info("X")],
        cadence=Cadence.DAILY, freshness=timedelta(days=2),
    )
    run_collector(collector, [], NOW, cache=cache, state=SourceState())
    result = run_collector(collector, [], NOW, cache=cache, state=SourceState())
    assert collector.calls == [[]]
    assert [r.symbol for r in result.records] == ["X"]


def test_use_window_false_always_fetches(tmp_path):
    cache, _ = clocked_cache(tmp_path, NOW)
    collector = windowed()
    run_collector(collector, ["AAA"], NOW, cache=cache, state=SourceState())
    run_collector(collector, ["AAA"], NOW, cache=cache, state=SourceState(), use_window=False)
    assert collector.calls == [["AAA"], ["AAA"]]


def test_max_symbols_caps_a_call_and_leaves_the_rest_for_later(tmp_path):
    cache, _ = clocked_cache(tmp_path, NOW)
    collector = windowed(Cadence.WEEKLY, max_symbols=2)
    first = run_collector(collector, ["AAA", "BBB", "CCC"], NOW, cache=cache, state=SourceState())
    second = run_collector(collector, ["AAA", "BBB", "CCC"], NOW, cache=cache, state=SourceState())
    assert collector.calls == [["AAA", "BBB"], ["CCC"]]
    assert sorted(r.symbol for r in first.records) == ["AAA", "BBB"]
    assert sorted(r.symbol for r in second.records) == ["AAA", "BBB", "CCC"]


def test_capped_out_symbols_are_served_from_older_cache(tmp_path):
    cache, now = clocked_cache(tmp_path, NOW)
    collector = windowed(max_symbols=1)
    run_collector(collector, ["AAA"], NOW, cache=cache, state=SourceState())
    run_collector(collector, ["BBB"], NOW, cache=cache, state=SourceState())
    tomorrow = NOW + timedelta(days=1)
    now[0] = tomorrow
    result = run_collector(collector, ["AAA", "BBB"], tomorrow, cache=cache, state=SourceState())
    assert collector.calls[-1] == ["AAA"]
    assert sorted(r.symbol for r in result.records) == ["AAA", "BBB"]


def test_a_partial_answer_is_backfilled_from_cache(tmp_path):
    cache = DiskCache(tmp_path, clock=lambda: NOW)
    collector = bars_collector()
    run_collector(collector, ["AAA", "BBB"], NOW, cache=cache, state=SourceState())
    collector.error = PartialFetch([bar("AAA", TODAY, 2.0)], "1 of 2 requests failed")
    result = run_collector(collector, ["AAA", "BBB"], NOW, cache=cache, state=SourceState())
    assert result.status is CollectorStatus.PARTIAL
    assert sorted((r.symbol, r.close) for r in result.records) == [("AAA", 2.0), ("BBB", 10.0)]
