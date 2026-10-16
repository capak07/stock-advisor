"""Per-stock headlines from Google News search RSS (spec source 25; core).

It is the one source that finds TSX companies by name.

**Queries.** One query per stock, for the company's directory name in quotes over the last 2 days:
`"Apple Inc" when:2d`. TSX stocks are searched in Canada's edition. A stock without a known name is
searched as `<ticker> stock`.

**Results.** A query returns at most 100 items, newest first.
- Titles end in " - <outlet>". That suffix is dropped, and the outlet comes from `<source>`.
- Links are opaque Google tokens that differ by query, so the news stage tells stories apart by
  outlet and title.

**Terms.** The feed is licensed for a personal feed reader. The owner chose to keep it on that basis
(2026-10-16): one query per stock per run, headlines only.

**Blocking.** Google answers a bot check with an HTML page or a 429. Either one stops the source
for the run.
"""

from collections.abc import Sequence
from datetime import datetime, timedelta

import httpx

from advisor.collectors.base import (
    Cadence,
    Category,
    RateLimiter,
    Scope,
    collect_per_symbol,
    get_with_retries,
)
from advisor.collectors.feeds import TickerNewsItem, parse_feed
from advisor.company_names import CompanyNames, search_name
from advisor.markets import TSX_SUFFIX, market_of
from advisor.models import AssetType, Market

GOOGLE_NEWS_URL = "https://news.google.com/rss/search"
GOOGLE_NEWS_PER_MINUTE = 60
LOOKBACK = timedelta(days=2)
EDITIONS = {
    Market.US: {"hl": "en-US", "gl": "US", "ceid": "US:en"},
    Market.TSX: {"hl": "en-CA", "gl": "CA", "ceid": "CA:en"},
}


class GoogleBlocked(Exception):
    """Google News answered with a bot check instead of a feed."""


def blocked(exc: Exception) -> bool:
    """A bot check or a 429: stop asking Google News for the rest of the run."""
    if isinstance(exc, GoogleBlocked):
        return True
    return isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429


def query_for(symbol: str, name: str | None) -> str:
    if name:
        return f'"{search_name(name)}" when:2d'
    return f"{symbol.removesuffix(TSX_SUFFIX)} stock when:2d"


def headline(title: str, outlet: str | None) -> str:
    """'Apple sues Masimo - Reuters' -> 'Apple sues Masimo' when Reuters is the outlet."""
    suffix = f" - {outlet}"
    return title.removesuffix(suffix) if outlet and title.endswith(suffix) else title


class GoogleNews:
    name = "google_news"
    category = Category.NEWS
    core = True
    best_effort = False
    cadence = Cadence.PER_RUN
    asset_types = frozenset({AssetType.STOCK})
    markets = frozenset({Market.US, Market.TSX})
    record_type = TickerNewsItem
    freshness = timedelta(days=1)
    scope = Scope.SYMBOLS
    canary = ("AAPL", "RY.TO")
    canary_requires_records = True
    max_symbols = None

    def __init__(
        self,
        client: httpx.Client,
        limiter: RateLimiter | None = None,
        *,
        names: CompanyNames | None = None,
    ) -> None:
        self._client = client
        self._limiter = limiter
        self._names = names if names is not None else CompanyNames()

    def fetch(self, symbols: Sequence[str], as_of: datetime) -> list[TickerNewsItem]:
        start = as_of - LOOKBACK

        def one(symbol: str) -> list[TickerNewsItem]:
            response = get_with_retries(
                self._client,
                GOOGLE_NEWS_URL,
                params={
                    "q": query_for(symbol, self._names.get(symbol)),
                    **EDITIONS[market_of(symbol)],
                },
                limiter=self._limiter,
            )
            try:
                entries = parse_feed(response.content)
            except ValueError as exc:
                raise GoogleBlocked(f"Google News sent no feed (a bot check?): {exc}") from exc
            return [
                TickerNewsItem(
                    symbol=symbol,
                    source=self.name,
                    outlet=entry.outlet or "Google News",
                    title=headline(entry.title, entry.outlet),
                    url=entry.url,
                    published_at=entry.published_at,
                )
                for entry in entries
                if start <= entry.published_at <= as_of
            ]

        return collect_per_symbol(symbols, one, is_fatal=blocked)
