"""Per-stock headlines from Yahoo Finance's RSS feed (spec source 24; undocumented, best-effort).

One request per stock: a request for several symbols returns a merged list that doesn't say which
item belongs to which stock. Links point at the publisher (their `?.tsrc=rss` tracker is dropped).
The feed names no outlet, so the link's host stands in for one. An unknown symbol gets an empty
feed, which is not an error.
"""

from collections.abc import Sequence
from datetime import datetime, timedelta
from urllib.parse import urlsplit

import httpx

from advisor.collectors.base import (
    Cadence,
    Category,
    RateLimiter,
    Scope,
    collect_per_symbol,
    get_with_retries,
)
from advisor.collectors.coins import throttled
from advisor.collectors.feeds import TickerNewsItem, parse_feed
from advisor.collectors.yfinance_bars import to_yahoo
from advisor.models import AssetType, Market

YAHOO_NEWS_URL = "https://feeds.finance.yahoo.com/rss/2.0/headline"
YAHOO_NEWS_PER_MINUTE = 120
LOOKBACK = timedelta(days=4)


def outlet_of(url: str) -> str:
    """The link's host as an outlet name: `https://www.reuters.com/...` -> `reuters.com`."""
    return urlsplit(url).netloc.lower().removeprefix("www.")


class YahooNews:
    name = "yahoo_news"
    category = Category.NEWS
    core = False
    best_effort = True
    cadence = Cadence.PER_RUN
    asset_types = frozenset({AssetType.STOCK})
    markets = frozenset({Market.US, Market.TSX})
    record_type = TickerNewsItem
    freshness = timedelta(days=1)
    scope = Scope.SYMBOLS
    canary = ("AAPL",)
    canary_requires_records = True
    max_symbols = None

    def __init__(self, client: httpx.Client, limiter: RateLimiter | None = None) -> None:
        self._client = client
        self._limiter = limiter

    def fetch(self, symbols: Sequence[str], as_of: datetime) -> list[TickerNewsItem]:
        start = as_of - LOOKBACK

        def one(symbol: str) -> list[TickerNewsItem]:
            response = get_with_retries(
                self._client,
                YAHOO_NEWS_URL,
                params={"s": to_yahoo(symbol), "region": "US", "lang": "en-US"},
                limiter=self._limiter,
            )
            return [
                TickerNewsItem(
                    symbol=symbol,
                    source=self.name,
                    outlet=outlet_of(entry.url),
                    title=entry.title,
                    url=entry.url,
                    published_at=entry.published_at,
                    summary=entry.summary,
                )
                for entry in parse_feed(response.content)
                if start <= entry.published_at <= as_of
            ]

        return collect_per_symbol(symbols, one, is_fatal=throttled)
