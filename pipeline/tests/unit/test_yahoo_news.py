from datetime import UTC, datetime
from functools import partial

import httpx
import pytest

import advisor.collectors.yahoo_news as yahoo_module
from advisor.collectors.base import PartialFetch
from advisor.collectors.feeds import parse_feed
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


def test_a_throttled_stock_stops_the_run_without_asking_for_the_rest(monkeypatch):
    seen: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.params["s"])
        return httpx.Response(429)

    # get_with_retries binds its sleep at definition time, so patching time.sleep would not reach it.
    real = yahoo_module.get_with_retries
    monkeypatch.setattr(yahoo_module, "get_with_retries", partial(real, sleep=lambda _: None))
    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(httpx.HTTPStatusError):
        YahooNews(client).fetch(["AAPL", "MSFT", "RY.TO"], AS_OF)
    assert set(seen) == {"AAPL"}


def test_items_after_as_of_are_left_out(fixtures_dir):
    as_of = datetime(2026, 10, 16, 11, 30, tzinfo=UTC)  # before the feed's 11:36:06 item
    body = (fixtures_dir / "news" / "yahoo_rss_AAPL.xml").read_bytes()
    newest = max(parse_feed(body), key=lambda entry: entry.published_at)
    assert newest.published_at > as_of

    items = serving(fixtures_dir, []).fetch(["AAPL"], as_of)
    assert items
    assert all(item.published_at <= as_of for item in items)
    assert newest.url not in {item.url for item in items}


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
