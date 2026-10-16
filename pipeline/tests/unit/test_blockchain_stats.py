import json
import time
from datetime import UTC, date, datetime

import httpx
import pytest

from advisor.collectors.base import PartialFetch, RateLimiter, deadline
from advisor.collectors.blockchain_stats import CHARTS, BlockchainStats, parse_chart
from fakes import FakeClock

AS_OF = datetime(2026, 10, 15, 12, 15, tzinfo=UTC)


def chart(fixtures_dir, name: str) -> dict:
    path = fixtures_dir / "blockchain" / f"blockchain_chart_{name}_90d.json"
    return json.loads(path.read_text(encoding="utf-8"))


def serving(fixtures_dir, seen: list, broken: str | None = None, limiter=None) -> BlockchainStats:
    def handler(request: httpx.Request) -> httpx.Response:
        name = request.url.path.removeprefix("/charts/")
        seen.append((name, request.url.params["timespan"]))
        if name == broken:
            return httpx.Response(404, json={"status": "not-found", "error": None})
        return httpx.Response(200, json=chart(fixtures_dir, name))

    return BlockchainStats(httpx.Client(transport=httpx.MockTransport(handler)), limiter)


def test_a_chart_is_read_as_finished_days(fixtures_dir):
    rows = parse_chart("hash-rate", chart(fixtures_dir, "hash-rate"), AS_OF)
    assert (len(rows), rows[0].day) == (90, date(2026, 7, 17))
    assert (rows[-1].series, rows[-1].day, rows[-1].value) == (
        "hash-rate", date(2026, 10, 14), 1062173070.0244452
    )


def test_a_day_not_finished_by_as_of_is_left_out(fixtures_dir):
    rows = parse_chart("hash-rate", chart(fixtures_dir, "hash-rate"), datetime(2026, 10, 14, 12, tzinfo=UTC))
    assert (len(rows), rows[-1].day) == (89, date(2026, 10, 13))


def test_a_not_found_answer_is_an_error():
    with pytest.raises(ValueError, match="chart nope answered 'not-found'"):
        parse_chart("nope", {"status": "not-found", "error": None}, AS_OF)


def test_fetch_asks_for_each_chart_ten_seconds_apart(fixtures_dir):
    seen: list = []
    clock = FakeClock()
    limiter = RateLimiter(per_minute=6, burst=1, clock=clock, sleep=clock.sleep)
    records = serving(fixtures_dir, seen, limiter=limiter).fetch([], AS_OF)
    assert seen == [(name, "60days") for name in CHARTS]
    assert clock.sleeps == [10.0] * 4
    assert len(records) == 450


def test_a_failing_chart_is_a_partial_result(fixtures_dir):
    failed = "1 of 5 blockchain.com charts failed; first: difficulty: HTTPStatusError"
    with pytest.raises(PartialFetch, match=failed) as caught:
        serving(fixtures_dir, [], broken="difficulty").fetch([], AS_OF)
    assert len(caught.value.records) == 360


def test_a_deadline_keeps_the_charts_already_fetched(fixtures_dir):
    def handler(request: httpx.Request) -> httpx.Response:
        time.sleep(0.2)  # the first answer arrives after the deadline
        return httpx.Response(200, json=chart(fixtures_dir, request.url.path.removeprefix("/charts/")))

    stats = BlockchainStats(httpx.Client(transport=httpx.MockTransport(handler)))
    with deadline(time.monotonic() + 0.1), pytest.raises(PartialFetch, match="stopped at difficulty") as caught:
        stats.fetch([], AS_OF)
    assert {r.series for r in caught.value.records} == {"hash-rate"}
