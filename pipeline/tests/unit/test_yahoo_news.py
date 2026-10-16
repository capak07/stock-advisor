from datetime import UTC, datetime

import httpx
import pytest

from advisor.collectors.base import PartialFetch
from advisor.collectors.yahoo_news import YahooNews, outlet_of

AS_OF = datetime(2026, 10, 16, 12, 15, tzinfo=UTC)
EMPTY = b"<rss version='2.0'><channel><title>Latest Financial News for </title></channel></rss>"


def serving(fixtures_dir, seen: list) -> YahooNews:
    files = {"AAPL": "yahoo_rss_AAPL.xml", "RY.TO": "yahoo_rss_RY.TO.xml"}

    def handler(request: httpx.Request) -> httpx.Response:
        symbol = request.url.params["s"]
        seen.append(symbol)
        if symbol == "BROKEN":
            return httpx.Response(500)
        name = files.get(symbol)
        body = (fixtures_dir / "news" / name).read_bytes() if name else EMPTY
        return httpx.Response(200, content=body)

    return YahooNews(httpx.Client(transport=httpx.MockTransport(handler)))


def test_each_stock_is_asked_for_alone_in_yahoos_form(fixtures_dir):
    seen: list = []
    items = serving(fixtures_dir, seen).fetch(["AAPL", "RY.TO", "BRK.B"], AS_OF)
    assert seen == ["AAPL", "RY.TO", "BRK-B"]
    assert [(symbol, len([i for i in items if i.symbol == symbol])) for symbol in ("AAPL", "RY.TO")] == [
        ("AAPL", 10), ("RY.TO", 10),
    ]  # BRK-B's empty feed is no error
    first = items[0]
    assert (first.symbol, first.source, first.outlet) == ("AAPL", "yahoo_news", "247wallst.com")
    assert first.url.startswith("https://247wallst.com/investing/2026/10/16/apple-and-meta")
    assert "?" not in first.url


def test_items_older_than_four_days_are_left_out(fixtures_dir):
    items = serving(fixtures_dir, []).fetch(["RY.TO"], datetime(2026, 10, 17, 22, 0, tzinfo=UTC))
    assert len(items) == 9  # the RBC feed's oldest item, 2026-10-13 21:43, is too old


def test_a_failing_stock_is_a_partial_result(fixtures_dir):
    with pytest.raises(PartialFetch, match="1 of 2 symbols failed; first: BROKEN") as caught:
        serving(fixtures_dir, []).fetch(["BROKEN", "AAPL"], AS_OF)
    assert {item.symbol for item in caught.value.records} == {"AAPL"}


@pytest.mark.parametrize(
    ("url", "outlet"),
    [
        ("https://www.reuters.com/markets/x", "reuters.com"),
        ("https://finance.yahoo.com/news/x.html", "finance.yahoo.com"),
    ],
)
def test_the_links_host_stands_in_for_the_outlet(url, outlet):
    assert outlet_of(url) == outlet
