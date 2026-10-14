from datetime import UTC, date, datetime, timedelta

import httpx

from advisor.collectors.base import Cadence, CollectorStatus, check_deadline
from advisor.collectors.cache import DiskCache
from advisor.collectors.runner import SourceState
from advisor.health import check_sources
from fakes import FakeCollector, bar

NOW = datetime(2026, 10, 10, 10, 30, tzinfo=UTC)


def test_check_sources_fetches_canaries_ignoring_the_breaker(tmp_path):
    good = FakeCollector(
        "good", canary=("AAPL",), records_for=lambda syms: [bar(s, date(2026, 10, 9), 1.0) for s in syms]
    )
    empty = FakeCollector("empty", canary=("AAPL",), canary_requires_records=True)
    event = FakeCollector("event", canary=("AAPL",))
    broken = FakeCollector("broken", canary=("AAPL",), error=httpx.ConnectError("down"))
    states = {
        "good": SourceState(5, date(2026, 10, 10)),
        "empty": SourceState(1),
        "event": SourceState(2),
    }
    rows = dict(
        (r.name, (r, failures))
        for r, failures in check_sources(
            {"good": good, "empty": empty, "broken": broken, "event": event}, DiskCache(tmp_path), states, NOW
        )
    )
    assert good.calls == [["AAPL"]]  # fetched although its breaker was open today
    assert rows["good"][0].status is CollectorStatus.OK and rows["good"][1] == 0
    assert rows["empty"][0].status is CollectorStatus.FAILED
    assert rows["empty"][0].error == "canary returned no records"
    assert rows["empty"][1] == 1  # a failed check records the attempt but never adds to the count
    assert rows["broken"][0].status is CollectorStatus.FAILED and rows["broken"][1] == 0
    assert rows["event"][0].status is CollectorStatus.OK  # event sources may answer nothing
    assert rows["event"][1] == 0


def test_a_source_over_its_budget_fails_without_stopping_the_others(tmp_path):
    slow = FakeCollector("slow", canary=("AAPL",), records_for=lambda syms: (check_deadline(), [])[1])
    good = FakeCollector(
        "good", canary=("AAPL",), records_for=lambda syms: [bar(s, date(2026, 10, 9), 1.0) for s in syms]
    )
    rows = {
        result.name: result
        for result, _ in check_sources({"slow": slow, "good": good}, DiskCache(tmp_path), {}, NOW, budget=0)
    }
    assert rows["slow"].status is CollectorStatus.FAILED
    assert rows["slow"].error.startswith("DeadlineExceeded")
    assert rows["good"].status is CollectorStatus.OK


def test_health_checks_bypass_the_cadence_cache(tmp_path):
    daily = FakeCollector(
        "daily", canary=("AAPL",), cadence=Cadence.DAILY, freshness=timedelta(days=1),
        records_for=lambda syms: [bar(s, date(2026, 10, 9), 1.0) for s in syms],
    )
    cache = DiskCache(tmp_path, clock=lambda: NOW)
    check_sources({"daily": daily}, cache, {}, NOW)
    check_sources({"daily": daily}, cache, {}, NOW)
    assert daily.calls == [["AAPL"], ["AAPL"]]
