"""Market-wide news feeds (spec §4.2 sources 27–42): one collector per publisher, all alike.

Each publisher is a row in FEEDS, with:
- its RSS URLs;
- the markets its news is about;
- how old the newest item of each URL may be. A frozen feed still answers 200 (WSJ's old URL, two
  MarketWatch feeds), so a URL whose newest item is older than that counts as failed.

Items are matched to tickers later, in the news stage (`advisor.news`): by the tickers a feed
names, exchange tags such as "(NYSE: CNC)", cashtags and company names. The sources dropped in
Plan 2f (for their terms, a bot wall, or a dead feed) are listed in `docs/superpowers/deferred.md`.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

import httpx

from advisor.collectors.base import (
    BUDGET_EXHAUSTED,
    Cadence,
    Category,
    DeadlineExceeded,
    PartialFetch,
    RateLimiter,
    Scope,
    check_deadline,
    get_with_retries,
)
from advisor.collectors.feeds import NewsItem, parse_feed
from advisor.models import AssetType, Market

FEED_PER_MINUTE = 30
LOOKBACK = timedelta(days=4)  # covers a weekend before Monday's pre-open run
US = frozenset({Market.US})
TSX = frozenset({Market.TSX})
NO_MARKET: frozenset[Market] = frozenset()  # crypto belongs to no stock market
STOCKS = frozenset({AssetType.STOCK})
CRYPTO = frozenset({AssetType.CRYPTO})


@dataclass(frozen=True)
class Feed:
    name: str  # the collector's name, and its source_health row
    outlet: str
    urls: tuple[str, ...]
    markets: frozenset[Market]
    asset_types: frozenset[AssetType] = STOCKS
    best_effort: bool = False
    max_age: timedelta = timedelta(days=4)  # a URL whose newest item is older is dead
    clock_is_utc: bool = False  # the stated offset is wrong: read the clock time as UTC


def _cnbc(feed_id: int) -> str:
    return f"https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id={feed_id}"


FEEDS: tuple[Feed, ...] = (
    Feed(
        "nasdaq_news", "Nasdaq",
        tuple(
            f"https://www.nasdaq.com/feed/rssoutbound?category={category}"
            for category in ("Markets", "Stocks", "Earnings")
        ),
        US,
    ),
    Feed(
        "cnbc_news", "CNBC",
        tuple(_cnbc(feed_id) for feed_id in (100003114, 15839069, 10000664, 15839135)),
        US,
    ),
    Feed(
        "marketwatch_news", "MarketWatch",
        (
            "https://feeds.content.dowjones.io/public/rss/mw_topstories",
            "https://feeds.content.dowjones.io/public/rss/mw_bulletins",
        ),
        US, best_effort=True,
    ),
    Feed(
        "wsj_markets", "The Wall Street Journal",
        ("https://feeds.content.dowjones.io/public/rss/RSSMarketsMain",),  # about 2 items a day
        US, best_effort=True, max_age=timedelta(days=7),
    ),
    Feed(
        "prnewswire", "PR Newswire",
        (
            "https://www.prnewswire.com/rss/news-releases-list.rss",
            "https://www.prnewswire.com/rss/financial-services-latest-news/"
            "financial-services-latest-news-list.rss",
        ),
        US,
    ),
    Feed(
        "globe_news", "The Globe and Mail",
        (
            "https://www.theglobeandmail.com/arc/outboundfeeds/rss/category/business/",
            "https://www.theglobeandmail.com/arc/outboundfeeds/rss/category/investing/",
        ),
        TSX, best_effort=True,
    ),
    Feed(
        "bnn_news", "BNN Bloomberg", ("https://www.bnnbloomberg.ca/arc/outboundfeeds/rss/",), TSX,
        clock_is_utc=True,  # it stamps UTC times with -0400
    ),
    Feed(
        "newsfile", "Newsfile",
        tuple(
            f"https://feeds.newsfilecorp.com/industry/{industry}"
            for industry in (
                "banking-financial-services", "precious-metals", "oil-gas", "technology",
                "real-estate",
            )
        ),
        TSX, best_effort=True, max_age=timedelta(days=7),  # 10 items per industry, some slow
    ),
    Feed(
        "decrypt_news", "Decrypt", ("https://decrypt.co/feed",), NO_MARKET,
        asset_types=CRYPTO, best_effort=True,
    ),
    Feed(
        "protos_news", "Protos", ("https://protos.com/feed/",), NO_MARKET,
        asset_types=CRYPTO, best_effort=True, max_age=timedelta(days=7),
    ),
)


class FeedNews:
    category = Category.NEWS
    core = False
    cadence = Cadence.PER_RUN
    record_type = NewsItem
    freshness = timedelta(days=1)
    scope = Scope.MARKET
    canary: tuple[str, ...] = ()
    canary_requires_records = True
    max_symbols = None

    def __init__(
        self, feed: Feed, client: httpx.Client, limiter: RateLimiter | None = None
    ) -> None:
        self.feed = feed
        self.name = feed.name
        self.best_effort = feed.best_effort
        self.asset_types = feed.asset_types
        self.markets = feed.markets
        self._client = client
        self._limiter = limiter

    def fetch(self, symbols: Sequence[str], as_of: datetime) -> list[NewsItem]:
        start = as_of - LOOKBACK
        records: dict[str, NewsItem] = {}  # by link: a story in two of the publisher's feeds
        failures: list[str] = []
        for url in self.feed.urls:
            try:
                check_deadline()
                response = get_with_retries(self._client, url, limiter=self._limiter)
                entries = [
                    e
                    for e in parse_feed(response.content, clock_is_utc=self.feed.clock_is_utc)
                    if e.published_at <= as_of
                ]
            except DeadlineExceeded:
                if not records:
                    raise
                raise PartialFetch(list(records.values()), BUDGET_EXHAUSTED) from None
            except (httpx.HTTPError, ValueError) as exc:
                failures.append(f"{url}: {type(exc).__name__}: {exc}"[:200])
                continue
            newest = max((e.published_at for e in entries), default=None)
            if newest is None or as_of - newest > self.feed.max_age:
                when = "no items" if newest is None else f"newest item from {newest:%Y-%m-%d}"
                failures.append(f"{url}: {when}, so the feed looks dead")
                continue
            for entry in entries:
                if entry.published_at >= start:
                    records.setdefault(entry.url, NewsItem(
                        source=self.name,
                        outlet=self.feed.outlet,
                        title=entry.title,
                        url=entry.url,
                        published_at=entry.published_at,
                        summary=entry.summary,
                        tags=entry.tags,
                    ))
        items = sorted(records.values(), key=lambda item: item.published_at)
        if failures:
            raise PartialFetch(
                items,
                f"{len(failures)} of {len(self.feed.urls)} {self.feed.outlet} feeds failed;"
                f" first: {failures[0]}",
            )
        return items
