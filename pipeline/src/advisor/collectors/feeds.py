"""News items and the RSS 2.0 parsing every news collector shares (spec §4.2 sources 24–42).

Feeds are read the way a personal feed reader reads them (the owner's terms decision, 2026-10-16):
headline, link and time only, never the article pages.
- **Dates:** every date carries its own offset (GMT, +0000, -0400), and all are converted to UTC.
  An item without a parseable date, title or link is skipped.
- **Errors:** a body that is not an RSS document is an error. That covers a bot check or error page
  sent with HTTP 200.
"""

import html
import re
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field

SUMMARY_CHARS = 400
TAG = re.compile(r"<[^>]+>")
SPACE = re.compile(r"\s+")
TRACKER = re.compile(r"utm_\w+|mod|\.tsrc|oc|ref|cmpid|src|time", re.IGNORECASE)


class NewsItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    source: str  # the collector that fetched it
    outlet: str  # the publisher, e.g. "Reuters"
    title: str
    url: str  # without query string or fragment
    published_at: datetime  # UTC
    summary: str = ""  # plain text, at most 400 characters; read only to find tickers
    tags: list[str] = Field(default_factory=list)  # tickers the feed itself names (Nasdaq)


class TickerNewsItem(NewsItem):
    symbol: str  # the stock this item was fetched for


@dataclass(frozen=True)
class FeedEntry:
    title: str
    url: str
    published_at: datetime
    summary: str
    outlet: str | None  # from <source>, which only Google News sends
    tags: list[str]


def plain_text(raw: str | None) -> str:
    """A feed field as text: entities decoded, HTML tags removed, whitespace collapsed."""
    return SPACE.sub(" ", TAG.sub(" ", html.unescape(raw or ""))).strip()


def canonical_url(url: str) -> str:
    """The link without tracking parameters or fragment.

    Trackers such as `?.tsrc=rss` and `?mod=mw_rss_topstories` would otherwise make one story look
    like several. Other parameters stay: MarketWatch bulletins differ only in `?g=`.
    """
    parts = urlsplit(url.strip())
    query = parse_qsl(parts.query, keep_blank_values=True)
    kept = [(key, value) for key, value in query if not TRACKER.fullmatch(key)]
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), parts.path, urlencode(kept), "")
    )


def parse_date(text: str | None, *, clock_is_utc: bool = False) -> datetime | None:
    """An RFC 822 date in UTC, or None. A date with no zone ("-0000") is taken as UTC.

    `clock_is_utc` reads the clock time as UTC whatever offset the feed states. BNN Bloomberg
    stamps UTC times with -0400: its newest items would otherwise sit hours after its own
    build time.
    """
    if not text:
        return None
    try:
        moment = parsedate_to_datetime(text.strip())
    except (TypeError, ValueError):
        return None
    if moment.tzinfo is None or clock_is_utc:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)


def parse_feed(body: bytes, *, clock_is_utc: bool = False) -> list[FeedEntry]:
    """The dated items of an RSS 2.0 document, in the feed's order."""
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError as exc:
        raise ValueError(f"not an RSS feed: {exc}") from exc
    if root.tag != "rss":
        raise ValueError(f"not an RSS feed: the document is <{root.tag}>")
    entries: list[FeedEntry] = []
    for item in root.iter("item"):
        published = parse_date(item.findtext("pubDate"), clock_is_utc=clock_is_utc)
        title = plain_text(item.findtext("title"))
        link = (item.findtext("link") or "").strip()
        if published is None or not title or not link:
            continue
        tickers = item.findtext("{*}tickers") or ""
        entries.append(FeedEntry(
            title=title,
            url=canonical_url(link),
            published_at=published,
            summary=plain_text(item.findtext("description"))[:SUMMARY_CHARS],
            outlet=plain_text(item.findtext("source")) or None,
            tags=list(dict.fromkeys(t.strip().upper() for t in tickers.split(",") if t.strip())),
        ))
    return entries
