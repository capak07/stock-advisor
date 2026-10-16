import itertools
from datetime import UTC, datetime, timedelta

import pytest

from advisor.collectors.feeds import NewsItem, TickerNewsItem
from advisor.models import AssetRef, AssetType
from advisor.news.mapping import TickerMap
from advisor.news.stage import outlet_key, process_news, volume_z
from advisor.news.stories import story_key

AS_OF = datetime(2026, 10, 16, 12, 15, tzinfo=UTC)
AAPL = AssetRef("AAPL", AssetType.STOCK)
RY = AssetRef("RY.TO", AssetType.STOCK)
BTC = AssetRef("BTC", AssetType.CRYPTO)
TARGETS = [AAPL, RY, BTC]
MAP = TickerMap(
    {"AAPL": "Apple Inc. - Common Stock", "RY.TO": "Royal Bank of Canada"}, {"BTC": "Bitcoin"}, TARGETS
)


def ticker_item(symbol: str, title: str, outlet: str, hours_ago: float) -> TickerNewsItem:
    return TickerNewsItem(
        symbol=symbol, source="google_news", outlet=outlet, title=title,
        url=f"https://news.google.com/rss/articles/{abs(hash((title, outlet)))}",
        published_at=AS_OF - timedelta(hours=hours_ago),
    )


def feed_item(title: str, outlet: str, hours_ago: float, summary: str = "") -> NewsItem:
    return NewsItem(
        source="cnbc_news", outlet=outlet, title=title, summary=summary,
        url=f"https://www.example.com/{abs(hash(title))}", published_at=AS_OF - timedelta(hours=hours_ago),
    )


def fake_scorer(calls: list):
    def score(titles):
        calls.append(list(titles))
        return [0.5 if "surge" in t else -0.5 if "plunge" in t else 0.0 for t in titles]

    return score


def test_items_become_stored_rows_with_one_score_per_story():
    calls: list = []
    items = [
        ticker_item("AAPL", "Apple shares surge on record iPhone sales", "Reuters", 2),
        ticker_item("AAPL", "Apple shares surge on record iPhone sales", "Reuters", 2),  # Yahoo too
        feed_item("Apple shares surge again on record iPhone sales", "CNBC", 1),  # same story: 7/8
        feed_item("Bitcoin plunges below $60,000", "CNBC", 30),
        feed_item("Fed holds rates steady", "CNBC", 3),  # names no target
        ticker_item("RY.TO", "RBC raises dividend", "Globe", 60),  # older than 48 hours
    ]
    outcome = process_news(items, MAP, TARGETS, AS_OF, scorer=fake_scorer(calls), history={})

    assert [(row.ref.symbol, row.outlet, row.sentiment) for row in outcome.rows] == [
        ("AAPL", "Reuters", 0.5), ("BTC", "CNBC", -0.5),
    ]  # AAPL keeps the story's earliest item (Reuters) once
    assert len(calls) == 1 and sorted(calls[0]) == [
        "Apple shares surge on record iPhone sales", "Bitcoin plunges below $60,000",
    ]  # one headline per story
    first = outcome.rows[0]
    assert first.story_key == story_key(items[0]) and first.cluster_id == story_key(items[0])
    assert outcome.summary == {
        "items": 5, "stories": 3, "rows": 2, "assets": 2, "sentiment": "finbert",
    }


def test_each_asset_keeps_at_most_three_stories_per_outlet():
    items = [ticker_item("AAPL", f"Apple story number {n} about something else {n}", "MarketBeat", n) for n in range(1, 6)]
    items.append(ticker_item("AAPL", "Apple wins court ruling", "Reuters", 7))
    outcome = process_news(items, MAP, TARGETS, AS_OF, scorer=None, history={})
    assert [(row.outlet, round((AS_OF - row.published_at).total_seconds() / 3600)) for row in outcome.rows] == [
        ("Reuters", 7), ("MarketBeat", 3), ("MarketBeat", 2), ("MarketBeat", 1),
    ]  # the newest three MarketBeat stories, oldest row first
    assert outcome.summary["sentiment"] == "unavailable"
    assert {row.sentiment for row in outcome.rows} == {None}


def test_features_for_every_target():
    items = [
        ticker_item("AAPL", "Apple shares surge on record iPhone sales", "Reuters", 2),
        ticker_item("AAPL", "Apple stock plunges on antitrust ruling", "CNBC", 30),
        ticker_item("AAPL", "Apple holds its developer conference", "Bloomberg", 40),
    ]
    outcome = process_news(
        items, MAP, TARGETS, AS_OF, scorer=fake_scorer([]), history={AAPL: [1, 2, 1, 2, 1, 2]}
    )
    features = dict(outcome.features)
    assert features[AAPL] == {
        "news_stories_48h": 3,
        "news_outlets_48h": 3,
        "news_sentiment_mean": pytest.approx(0.0),  # 0.5, -0.5 and 0.0
        "news_sentiment_trend": pytest.approx(0.75),  # 0.5 in the last day, -0.25 the day before
        "news_volume_z": pytest.approx(-1.0),  # 1 story in the last day against 1.5 +- 0.5
    }
    assert features[RY] == {
        "news_stories_48h": 0, "news_outlets_48h": 0, "news_sentiment_mean": None,
        "news_sentiment_trend": None, "news_volume_z": None,
    }
    assert [ref for ref, _ in outcome.features] == TARGETS


@pytest.mark.parametrize(
    ("recent", "history", "z"),
    [
        (4, [1, 2, 1, 2, 1, 2], 5.0),
        (1, [1, 2, 1, 2], None),  # fewer than 5 days of history
        (3, [2, 2, 2, 2, 2], None),  # no spread
    ],
)
def test_volume_z(recent, history, z):
    assert volume_z(recent, history) == (pytest.approx(z) if z is not None else None)


def test_outlet_key():
    assert outlet_key("MarketBeat") == outlet_key("marketbeat.com") == outlet_key("www.MarketBeat.com") == "marketbeat"
    assert outlet_key("The Globe and Mail") == outlet_key("theglobeandmail.com")


def test_one_publisher_spelled_two_ways_shares_the_cap():
    titles = [
        "Apple reports record services revenue",
        "Apple opens new flagship store in Tokyo",
        "Apple faces fresh antitrust probe in Europe",
        "Apple announces battery recycling program",
        "Apple names new chief for retail division",
        "Apple expands satellite messaging service",
    ]
    outlets = ["MarketBeat", "marketbeat.com"] * 3
    items = [ticker_item("AAPL", title, outlet, n) for n, (title, outlet) in enumerate(zip(titles, outlets, strict=True), start=1)]
    outcome = process_news(items, MAP, TARGETS, AS_OF, scorer=None, history={})
    assert len([row for row in outcome.rows if row.ref == AAPL]) == 3
    assert dict(outcome.features)[AAPL]["news_outlets_48h"] == 1


def test_window_edges():
    titles = [
        "Apple reports record services revenue",
        "Apple opens new flagship store in Tokyo",
        "Apple faces fresh antitrust probe in Europe",
        "Apple announces battery recycling program",
    ]
    hours = [-1 / 60, 0, 48, 48 + 1 / 60]  # after as_of, at as_of, at the 48 h edge, just past it
    items = [ticker_item("AAPL", title, "Reuters", h) for title, h in zip(titles, hours, strict=True)]
    outcome = process_news(items, MAP, TARGETS, AS_OF, scorer=None, history={})
    assert dict(outcome.features)[AAPL]["news_stories_48h"] == 2
    assert all(row.published_at <= AS_OF for row in outcome.rows)


def test_the_trend_splits_at_24_hours():
    items = [
        ticker_item("AAPL", "Apple reports record services revenue", "Reuters", 24),
        ticker_item("AAPL", "Apple faces fresh antitrust probe in Europe", "CNBC", 24 + 1 / 60),
    ]
    scores = {items[0].title: 1.0, items[1].title: -1.0}
    outcome = process_news(
        items, MAP, TARGETS, AS_OF, scorer=lambda titles: [scores[t] for t in titles], history={}
    )
    features = dict(outcome.features)[AAPL]
    assert features["news_sentiment_trend"] == pytest.approx(2.0)
    assert features["news_sentiment_mean"] == pytest.approx(0.0)


def test_the_trend_needs_both_days():
    items = [
        ticker_item("AAPL", "Apple reports record services revenue", "Reuters", 2),
        ticker_item("AAPL", "Apple faces fresh antitrust probe in Europe", "CNBC", 5),
    ]
    scored = process_news(items, MAP, TARGETS, AS_OF, scorer=lambda titles: [0.5] * len(titles), history={})
    features = dict(scored.features)[AAPL]
    assert features["news_sentiment_mean"] == pytest.approx(0.5)
    assert features["news_sentiment_trend"] is None

    unscored = process_news(items, MAP, TARGETS, AS_OF, scorer=None, history={})
    features = dict(unscored.features)[AAPL]
    assert features["news_sentiment_mean"] is None
    assert features["news_sentiment_trend"] is None
    assert features["news_stories_48h"] == 2


def test_selection_does_not_depend_on_input_order():
    items = [
        ticker_item("AAPL", "Apple reports record services revenue", "MarketBeat", 3),
        ticker_item("AAPL", "Apple reports record services revenue", "marketbeat.com", 3),  # same story
    ]
    items += [
        ticker_item("AAPL", title, "MarketBeat", 3)
        for title in (
            "Apple faces fresh antitrust probe in Europe",
            "Apple opens new flagship store in Tokyo",
            "Apple announces battery recycling program",
            "Apple names new chief for retail division",
        )
    ]  # five MarketBeat stories at the same time: the cap must cut two, the same way every time
    baseline = process_news(items, MAP, TARGETS, AS_OF, scorer=fake_scorer([]), history={})
    assert len([row for row in baseline.rows if row.ref == AAPL]) == 3
    for order in itertools.permutations(items):
        outcome = process_news(list(order), MAP, TARGETS, AS_OF, scorer=fake_scorer([]), history={})
        assert outcome.rows == baseline.rows
        assert outcome.features == baseline.features
