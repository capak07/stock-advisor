"""FOMC statements, minutes and meeting dates from the Federal Reserve (spec source 21).

Two keyless requests per run:
- the monetary-policy press-release RSS feed, which holds the last 15 or so releases;
- the meeting calendar page, which has no feed; it is read by its stable `fomc-meeting__*`
  class names. A meeting's decision comes at 14:00 ET on its last day.

A statement is the release titled exactly "Federal Reserve issues FOMC statement"; "Minutes of
the Board's discount rate meetings" are not FOMC minutes.
"""

import re
import xml.etree.ElementTree as ElementTree
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict

from advisor.collectors.base import (
    Cadence,
    Category,
    PartialFetch,
    RateLimiter,
    Scope,
    get_with_retries,
)
from advisor.models import ET, AssetType, Market

RSS_URL = "https://www.federalreserve.gov/feeds/press_monetary.xml"
CALENDAR_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
STATEMENT = "Federal Reserve issues FOMC statement"
MINUTES = "Minutes of the Federal Open Market Committee"
RECENT = timedelta(days=60)  # past meetings kept, besides every upcoming one

YEAR = re.compile(r">(\d{4}) FOMC Meetings<")
MONTH_CELL = re.compile(r"fomc-meeting__month[^>]*>\s*<strong>([^<]+)</strong>")
DATE_CELL = re.compile(r"fomc-meeting__date[^>]*>([^<]+)<")
MONTHS = {
    name: number
    for number, name in enumerate(
        ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"),
        start=1,
    )
}

Kind = Literal["statement", "minutes", "projections", "other", "meeting"]


class FomcEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Kind
    day: date  # the release's ET date, or the meeting's decision day
    title: str
    url: str
    published_at: datetime | None = None  # releases only


def release_kind(title: str) -> Kind:
    if title == STATEMENT:
        return "statement"
    if title.startswith(MINUTES):
        return "minutes"
    if "economic projections" in title.lower():
        return "projections"
    return "other"


def parse_releases(xml: bytes, as_of: datetime) -> list[FomcEvent]:
    """Releases published by `as_of`, newest first as the feed lists them."""
    events: list[FomcEvent] = []
    for item in ElementTree.fromstring(xml).iter("item"):
        title = (item.findtext("title") or "").strip()
        published = parsedate_to_datetime((item.findtext("pubDate") or "").strip())
        if published > as_of:
            continue
        events.append(FomcEvent(
            kind=release_kind(title),
            day=published.astimezone(ET).date(),
            title=title,
            url=(item.findtext("link") or "").strip(),
            published_at=published,
        ))
    return events


def decision_day(year: int, month_cell: str, date_cell: str) -> date:
    """The meeting's last day: "27-28" in "October", "30-1" in "Apr/May", "22 (notation vote)"."""
    month = MONTHS[month_cell.split("/")[-1].strip()[:3].lower()]
    return date(year, month, int(re.findall(r"\d+", date_cell)[-1]))


def parse_calendar(html: str, as_of: datetime) -> list[FomcEvent]:
    """Upcoming meetings and those of the last 60 days, from each year's panel in page order."""
    cutoff = as_of.astimezone(ET).date() - RECENT
    years = list(YEAR.finditer(html))
    events: list[FomcEvent] = []
    for index, heading in enumerate(years):
        end = years[index + 1].start() if index + 1 < len(years) else len(html)
        panel = html[heading.end():end]
        year = int(heading.group(1))
        cells = zip(MONTH_CELL.findall(panel), DATE_CELL.findall(panel), strict=True)
        for month_cell, date_cell in cells:
            day = decision_day(year, month_cell, date_cell)
            if day >= cutoff:
                days = date_cell.replace("*", "").strip()  # * marks a meeting with projections
                events.append(FomcEvent(
                    kind="meeting",
                    day=day,
                    title=f"FOMC meeting, {month_cell.strip()} {days}, {year}",
                    url=CALENDAR_URL,
                ))
    return sorted(events, key=lambda event: event.day)


class Fomc:
    name = "fomc"
    category = Category.MACRO
    core = False
    best_effort = False
    cadence = Cadence.PER_RUN  # a statement lands at 14:00 ET, before the pre-close run
    asset_types = frozenset({AssetType.STOCK})
    markets = frozenset({Market.US, Market.TSX})
    record_type = FomcEvent
    freshness = timedelta(days=7)
    scope = Scope.MARKET
    canary: tuple[str, ...] = ()
    canary_requires_records = True
    max_symbols = None

    def __init__(self, client: httpx.Client, limiter: RateLimiter | None = None) -> None:
        self._client = client
        self._limiter = limiter

    def fetch(self, symbols: Sequence[str], as_of: datetime) -> list[FomcEvent]:
        feed = get_with_retries(self._client, RSS_URL, limiter=self._limiter)
        releases = parse_releases(feed.content, as_of)
        try:
            page = get_with_retries(self._client, CALENDAR_URL, limiter=self._limiter)
            meetings = parse_calendar(page.text, as_of)
        except (httpx.HTTPError, ValueError, KeyError, IndexError) as exc:
            raise PartialFetch(
                releases, f"FOMC calendar unreadable: {type(exc).__name__}: {exc}"[:300]
            ) from exc
        if not meetings:
            raise PartialFetch(releases, "the FOMC calendar lists no upcoming or recent meetings")
        return releases + meetings
