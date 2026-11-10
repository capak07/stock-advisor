"""Yahoo Finance headlines for a day trade signal.

RSS parsing ported from the day-trader skill (MIT, github.com/Jakeschincariol/day-trader-skill):
news.py (parse_rss, parse_time, _local, _text).
"""

import email.utils
import xml.etree.ElementTree as ET
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from advisor.collectors.yfinance_bars import to_yahoo

YAHOO_RSS = "https://feeds.finance.yahoo.com/rss/2.0/headline?s={}&region=US&lang=en-US"
DEFAULT_OUTLET = "Yahoo Finance"


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _text(el: ET.Element, name: str) -> str:
    for c in el.iter():
        if _local(c.tag) == name:
            return (c.text or "").strip()
    return ""


def parse_time(value: str) -> datetime | None:
    """RFC 822 (RSS) or ISO 8601 -> aware UTC datetime, or None."""
    value = (value or "").strip()
    if not value:
        return None
    try:
        d = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        try:
            d = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=UTC)
    return d.astimezone(UTC)


def headlines(
    get: Callable[[str], str], symbol: str, now: datetime, hours: int = 36, limit: int = 3
) -> list[dict]:
    """Newest-first headlines for an app symbol from the last `hours`; any failure gives []."""
    try:
        root = ET.fromstring(get(YAHOO_RSS.format(to_yahoo(symbol))))
        cutoff = now - timedelta(hours=hours)
        found: list[tuple[datetime, dict]] = []
        for it in root.iter("item"):
            title = _text(it, "title")
            when = parse_time(_text(it, "pubDate"))
            if not title or when is None or when < cutoff:
                continue
            found.append((when, {
                "title": title,
                "url": _text(it, "link"),
                "published_at": when.isoformat(),
                "outlet": _text(it, "source") or DEFAULT_OUTLET,
            }))
        found.sort(key=lambda p: p[0], reverse=True)
        out: list[dict] = []
        seen: set[str] = set()
        for _, item in found:
            if item["title"] in seen:
                continue
            seen.add(item["title"])
            out.append(item)
        return out[:limit]
    except Exception:  # noqa: BLE001 - headlines are decoration; never fail a signal over them
        return []
