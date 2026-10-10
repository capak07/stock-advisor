from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime

import httpx
import pytest

from advisor.collectors.base import CollectorResult, CollectorStatus
from advisor.collectors.cache import DiskCache
from advisor.collectors.runner import SourceState
from advisor.collectors.tracker import SourceTracker, merge_results
from fakes import FakeCollector, bar

NOW = datetime(2026, 10, 14, 12, 15, tzinfo=UTC)
S = CollectorStatus


def result(status: CollectorStatus, n: int = 0, error: str | None = None) -> CollectorResult:
    return CollectorResult("src", status, [bar("AAA", date(2026, 10, 13), 1.0)] * n, 5, error)


@pytest.mark.parametrize(
    ("statuses", "merged"),
    [
        ([S.OK, S.OK], S.OK),
        ([S.FAILED, S.FAILED], S.FAILED),
        ([S.SKIPPED, S.SKIPPED], S.SKIPPED),
        ([S.PARTIAL], S.PARTIAL),
        ([S.OK, S.FAILED], S.PARTIAL),
        ([S.OK, S.STALE], S.PARTIAL),
        ([S.STALE, S.FAILED], S.STALE),
    ],
)
def test_merge_status_rules(statuses, merged):
    assert merge_results([result(s) for s in statuses]).status is merged


def test_merge_sums_records_and_latency_and_keeps_first_error():
    merged = merge_results([result(S.OK, 2), result(S.FAILED, 0, "down"), result(S.OK, 1)])
    assert len(merged.records) == 3
    assert merged.latency_ms == 15
    assert merged.error == "down"


def tracker_with(collectors: dict, tmp_path, states=None) -> SourceTracker:
    return SourceTracker(collectors, DiskCache(tmp_path), NOW, states or {})


def test_two_calls_to_one_source_become_one_partial_row(tmp_path):
    flaky = FakeCollector("prices", records_for=lambda syms: [bar(s, date(2026, 10, 13), 1.0) for s in syms])
    tracker = tracker_with({"prices": flaky}, tmp_path, {"prices": SourceState(2)})
    tracker.run("prices", ["OTCX"])
    flaky.error = httpx.ConnectError("down")
    tracker.run("prices", ["AAA", "BBB"])
    [(merged, failures)] = tracker.health_rows()
    assert merged.status is S.PARTIAL
    assert failures == 0  # a partial answer resets the breaker count
    assert flaky.calls == [["OTCX"], ["AAA", "BBB"]]


def test_count_healthy_counts_unneeded_sources_as_healthy(tmp_path):
    collectors = {
        "ok": FakeCollector("ok"),
        "broken": FakeCollector("broken", error=httpx.ConnectError("down")),
        "unused": FakeCollector("unused"),
    }
    tracker = tracker_with(collectors, tmp_path)
    tracker.run("ok", ["AAA"])
    tracker.run("broken", ["AAA"])
    assert tracker.count_healthy() == 2
    assert [r.name for r in tracker.merged()] == ["ok", "broken"]


def test_concurrent_runs_of_many_sources_are_all_recorded(tmp_path):
    collectors = {f"s{i}": FakeCollector(f"s{i}") for i in range(20)}
    tracker = tracker_with(collectors, tmp_path)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda name: tracker.run(name, ["AAA"]), collectors))
    assert sorted(r.name for r in tracker.merged()) == sorted(collectors)


def test_tracker_contains_unexpected_errors(tmp_path, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("advisor.collectors.tracker.run_collector", boom)
    tracker = tracker_with({"x": FakeCollector("x")}, tmp_path)
    got = tracker.run("x", ["AAA"])
    assert got.status is S.FAILED and got.error == "RuntimeError: boom"
    assert [r.error for r in tracker.merged()] == ["RuntimeError: boom"]
    with pytest.raises(KeyError):
        tracker.run("unknown", [])
