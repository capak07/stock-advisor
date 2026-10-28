from datetime import UTC, date, datetime

import httpx

from advisor.training.crypto import fetch_history, list_products

END = date(2026, 10, 24)


def _ts(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp())


def _candle(day: date, close: float = 10.0) -> list[float]:
    return [_ts(day), 9.0, 11.0, 10.0, close, 5.0]


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_products_keep_usd_bases_including_delisted_ones():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/products"
        return httpx.Response(200, json=[
            {"id": "BTC-USD", "base_currency": "BTC", "quote_currency": "USD", "status": "online"},
            {"id": "OLD-USD", "base_currency": "OLD", "quote_currency": "USD", "status": "delisted"},
            {"id": "ETH-EUR", "base_currency": "ETH", "quote_currency": "EUR", "status": "online"},
            {"id": "BTC-USD", "base_currency": "BTC", "quote_currency": "USD", "status": "online"},
        ])

    with _client(handler) as client:
        assert list_products(client) == ["BTC", "OLD"]


def test_paging_joins_two_pages_and_stops_on_an_empty_page():
    asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/products/ETH-USD/candles"
        end = request.url.params["end"][:10]
        asked.append(end)
        if end == "2026-10-24":
            return httpx.Response(200, json=[_candle(date(2026, 10, 23), 20.0), _candle(date(2026, 8, 1), 15.0)])
        if end == "2025-12-28":
            return httpx.Response(200, json=[_candle(date(2025, 6, 1), 8.0)])
        return httpx.Response(200, json=[])

    with _client(handler) as client:
        frame = fetch_history(client, "ETH", END, None)
    assert asked == ["2026-10-24", "2025-12-28", "2025-03-03"]
    assert frame["day"].tolist() == [date(2025, 6, 1), date(2026, 8, 1), date(2026, 10, 23)]
    assert frame["close"].tolist() == [8.0, 15.0, 20.0]
    assert list(frame.columns) == ["symbol", "day", "open", "high", "low", "close", "volume"]


def test_a_404_gives_an_empty_frame():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "NotFound"})

    with _client(handler) as client:
        frame = fetch_history(client, "GONE", END, None)
    assert frame.empty
    assert list(frame.columns) == ["symbol", "day", "open", "high", "low", "close", "volume"]


def test_todays_candle_is_dropped():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params["end"][:10] == "2026-10-24":
            return httpx.Response(200, json=[_candle(END, 30.0), _candle(date(2026, 10, 23), 20.0)])
        return httpx.Response(200, json=[])

    with _client(handler) as client:
        frame = fetch_history(client, "BTC", END, None)
    assert frame["day"].tolist() == [date(2026, 10, 23)]
