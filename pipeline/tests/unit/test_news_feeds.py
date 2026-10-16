from datetime import UTC, datetime

import httpx
import pytest

from advisor.collectors.base import PartialFetch
from advisor.collectors.news_feeds import FEEDS, Feed, FeedNews
from advisor.models import AssetType, Market

AS_OF = datetime(2026, 10, 16, 12, 15, tzinfo=UTC)
FEED = {feed.name: feed for feed in FEEDS}


def serving(fixtures_dir, feed: Feed, routes: dict[str, str | int], seen: list | None = None) -> FeedNews:
    """Each of the feed's URLs answers the named fixture file, or the given HTTP status."""

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(str(request.url))
        answer = routes.get(str(request.url), 404)
        if isinstance(answer, int):
            return httpx.Response(answer)
        return httpx.Response(200, content=(fixtures_dir / "news" / answer).read_bytes())

    return FeedNews(feed, httpx.Client(transport=httpx.MockTransport(handler)))


def test_every_publisher_is_its_own_source():
    assert [feed.name for feed in FEEDS] == [
        "nasdaq_news", "cnbc_news", "marketwatch_news", "wsj_markets", "prnewswire",
        "globe_news", "bnn_news", "newsfile", "decrypt_news", "protos_news",
    ]
    crypto = [feed.name for feed in FEEDS if feed.asset_types == frozenset({AssetType.CRYPTO})]
    assert crypto == ["decrypt_news", "protos_news"]
    assert {feed.name for feed in FEEDS if feed.markets == frozenset({Market.TSX})} == {
        "globe_news", "bnn_news", "newsfile",
    }


def test_a_publishers_feeds_are_read_and_merged(fixtures_dir):
    feed = FEED["nasdaq_news"]
    seen: list = []
    files = dict(zip(feed.urls, ["nasdaq_markets.xml", "nasdaq_stocks.xml", "nasdaq_earnings.xml"], strict=True))
    items = serving(fixtures_dir, feed, files, seen).fetch([], AS_OF)
    assert seen == list(feed.urls)
    assert len(items) == 30
    assert {item.source for item in items} == {"nasdaq_news"}
    assert {item.outlet for item in items} == {"Nasdaq"}
    assert items == sorted(items, key=lambda item: item.published_at)  # oldest first
    assert any(item.tags == ["CTSH"] for item in items)


def test_one_story_in_two_of_a_publishers_feeds_counts_once(fixtures_dir):
    feed = FEED["cnbc_news"]
    routes = {url: "cnbc_top.xml" for url in feed.urls}  # the same 10 items four times
    assert len(serving(fixtures_dir, feed, routes).fetch([], AS_OF)) == 10


def test_items_outside_the_last_four_days_or_after_as_of_are_left_out(fixtures_dir):
    feed = FEED["wsj_markets"]  # 10 items, 2026-10-13 09:30 to 2026-10-16 10:39 UTC
    collector = serving(fixtures_dir, feed, {feed.urls[0]: "wsj_dowjones_RSSMarketsMain.xml"})
    before = collector.fetch([], datetime(2026, 10, 16, 9, 0, tzinfo=UTC))
    assert (len(before), before[-1].published_at) == (8, datetime(2026, 10, 16, 8, 8, 29, tzinfo=UTC))
    later = collector.fetch([], datetime(2026, 10, 17, 10, 0, tzinfo=UTC))
    assert (len(later), later[0].published_at) == (9, datetime(2026, 10, 14, 9, 30, tzinfo=UTC))


def test_a_dead_feed_that_still_answers_is_a_failure(fixtures_dir):
    feed = FEED["marketwatch_news"]
    routes = dict(zip(feed.urls, ["marketwatch_topstories.xml", "marketwatch_marketpulse_stale.xml"], strict=True))
    with pytest.raises(PartialFetch, match="newest item from 2025-07-03, so the feed looks dead") as caught:
        serving(fixtures_dir, feed, routes).fetch([], AS_OF)
    assert len(caught.value.records) == 10  # the live feed's items are kept


def test_a_failing_url_is_a_partial_result(fixtures_dir):
    feed = FEED["prnewswire"]
    routes = {feed.urls[0]: 503, feed.urls[1]: "prnewswire_financial.xml"}
    with pytest.raises(PartialFetch, match="1 of 2 PR Newswire feeds failed") as caught:
        serving(fixtures_dir, feed, routes).fetch([], AS_OF)
    assert len(caught.value.records) == 10


def test_a_bot_check_page_is_a_failure(fixtures_dir):
    feed = FEED["decrypt_news"]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<!DOCTYPE html><html><title>Just a moment...</title></html>")

    collector = FeedNews(feed, httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(PartialFetch, match="not an RSS feed") as caught:
        collector.fetch([], AS_OF)
    assert caught.value.records == []  # an empty PartialFetch counts as a failure


def test_bnn_dates_are_read_as_utc(fixtures_dir):
    feed = FEED["bnn_news"]
    items = serving(fixtures_dir, feed, {feed.urls[0]: "bnnbloomberg-rss.xml"}).fetch([], AS_OF)
    newest = items[-1]
    assert (newest.published_at, newest.title[:28]) == (
        datetime(2026, 10, 16, 11, 59, 1, tzinfo=UTC), "Fed chair Warsh says U.S. pr"
    )  # stamped "11:59:01 -0400"; read with the offset, every new item would be after as_of
