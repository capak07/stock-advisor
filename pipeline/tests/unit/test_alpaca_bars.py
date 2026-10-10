from datetime import UTC, date, datetime

import httpx
import pytest

from advisor.collectors.alpaca_bars import ALPACA_BARS_URL, AlpacaBars
from advisor.collectors.base import PartialFetch, RateLimiter

AS_OF = datetime(2026, 10, 14, 19, 15, tzinfo=UTC)  # 15:15 ET
FAST = RateLimiter(per_minute=60_000, burst=1_000)


def raw(t: str, close: float) -> dict:
    return {"t": t, "o": close, "h": close, "l": close, "c": close, "v": 1000, "n": 10, "vw": close}


def test_fetch_follows_pages_and_drops_invalid_bars():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert str(request.url).startswith(ALPACA_BARS_URL)
        assert request.headers["APCA-API-KEY-ID"] == "key"
        assert request.headers["APCA-API-SECRET-KEY"] == "secret"
        if request.url.params.get("page_token") is None:
            return httpx.Response(200, json={
                "bars": {"AAPL": [raw("2026-10-12T04:00:00Z", 1.5)]},
                "next_page_token": "p2",
            })
        return httpx.Response(200, json={
            "bars": {
                "AAPL": [raw("2026-10-13T04:00:00Z", 1.6)],
                "MSFT": [raw("2026-10-13T04:00:00Z", 0)],  # invalid: close must be > 0
            },
            "next_page_token": None,
        })

    collector = AlpacaBars(
        httpx.Client(transport=httpx.MockTransport(handler)), "key", "secret", limiter=FAST
    )
    bars = collector.fetch(["MSFT", "AAPL", "AAPL"], AS_OF)

    assert [(b.symbol, b.day, b.close, b.source) for b in bars] == [
        ("AAPL", date(2026, 10, 12), 1.5, "alpaca"),
        ("AAPL", date(2026, 10, 13), 1.6, "alpaca"),
    ]
    params = seen[0].url.params
    assert params["symbols"] == "AAPL,MSFT"
    assert params["timeframe"] == "1Day"
    assert params["feed"] == "sip"
    assert params["adjustment"] == "all"
    assert params["start"] == "2026-07-06T19:15:00Z"
    assert params["end"] == "2026-10-14T18:59:00Z"
    assert seen[1].url.params["page_token"] == "p2"


def test_fetch_chunks_symbols_two_hundred_per_request():
    sizes: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sizes.append(len(request.url.params["symbols"].split(",")))
        return httpx.Response(200, json={"bars": {}, "next_page_token": None})

    collector = AlpacaBars(
        httpx.Client(transport=httpx.MockTransport(handler)), "key", "secret", limiter=FAST
    )
    symbols = [f"S{i:03d}" for i in range(250)]
    assert collector.fetch(symbols, AS_OF) == []
    assert sizes == [200, 50]


def test_fetch_with_no_symbols_makes_no_requests():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request expected")

    collector = AlpacaBars(
        httpx.Client(transport=httpx.MockTransport(handler)), "key", "secret", limiter=FAST
    )
    assert collector.fetch([], AS_OF) == []


def test_fetch_drops_rows_with_null_fields_and_symbols_with_null_rows():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "bars": {
                "AAPL": [
                    {**raw("2026-10-12T04:00:00Z", 1.5), "t": None},
                    raw("2026-10-13T04:00:00Z", 1.6),
                ],
                "MSFT": None,
            },
            "next_page_token": None,
        })

    collector = AlpacaBars(
        httpx.Client(transport=httpx.MockTransport(handler)), "key", "secret", limiter=FAST
    )
    bars = collector.fetch(["AAPL", "MSFT"], AS_OF)
    assert [(b.symbol, b.day, b.close) for b in bars] == [("AAPL", date(2026, 10, 13), 1.6)]


def test_a_rejected_chunk_is_a_partial_result_and_other_chunks_are_kept():
    def handler(request: httpx.Request) -> httpx.Response:
        symbols = request.url.params["symbols"].split(",")
        if "S210" in symbols:  # second chunk contains a symbol Alpaca rejects
            return httpx.Response(400, json={"message": "invalid symbol: S210"})
        return httpx.Response(200, json={
            "bars": {"S000": [raw("2026-10-13T04:00:00Z", 5.0)]}, "next_page_token": None,
        })

    collector = AlpacaBars(
        httpx.Client(transport=httpx.MockTransport(handler)), "key", "secret", limiter=FAST
    )
    with pytest.raises(PartialFetch, match="1 of 2 Alpaca requests failed") as caught:
        collector.fetch([f"S{i:03d}" for i in range(250)], AS_OF)
    assert [b.symbol for b in caught.value.records] == ["S000"]


def test_every_chunk_failing_raises_with_the_first_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "unauthorized"})

    collector = AlpacaBars(
        httpx.Client(transport=httpx.MockTransport(handler)), "key", "secret", limiter=FAST
    )
    with pytest.raises(RuntimeError, match="all 2 Alpaca requests failed"):
        collector.fetch([f"S{i:03d}" for i in range(250)], AS_OF)


def test_a_chunk_failing_on_a_later_page_contributes_no_bars():
    def handler(request: httpx.Request) -> httpx.Response:
        symbols = request.url.params["symbols"].split(",")
        first_chunk = "S000" in symbols
        if first_chunk and request.url.params.get("page_token") == "p2":
            return httpx.Response(400, json={"message": "bad page"})
        rows = {"S000": [raw("2026-10-12T04:00:00Z", 5.0)]} if first_chunk else {
            "S200": [raw("2026-10-12T04:00:00Z", 6.0)]
        }
        return httpx.Response(200, json={
            "bars": rows, "next_page_token": "p2" if first_chunk else None,
        })

    collector = AlpacaBars(
        httpx.Client(transport=httpx.MockTransport(handler)), "key", "secret", limiter=FAST
    )
    with pytest.raises(PartialFetch) as caught:
        collector.fetch([f"S{i:03d}" for i in range(250)], AS_OF)
    assert [b.symbol for b in caught.value.records] == ["S200"]
