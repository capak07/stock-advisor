from datetime import UTC, date, datetime

import httpx

from advisor.collectors.base import CollectorStatus
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
