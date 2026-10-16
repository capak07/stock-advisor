"""The news stage (spec §4.3 stage 5): from fetched headlines to stories, sentiment and features.

1. Keep the items published in the 48 hours before `as_of`.
2. Attribute each item. A per-stock item (Google News, Yahoo) goes to its stock. A market-wide item
   goes to the targets it names (`advisor.news.mapping`).
3. Group items into stories (`advisor.news.stories`). Each asset keeps one item per story, and at
   most 3 stories per outlet: MarketBeat alone filled 60 of Google's 100 results for Apple. A story
   an earlier run already stored for the asset, under another item's key, is not stored again.
4. Score each story's headline once (FinBERT).
5. Compute per-asset features: stories, outlets, mean sentiment, and the sentiment trend (the last
   24 h minus the 24 h before). The volume z-score compares the last 24 h's stories with the
   asset's daily story counts in news_items before them.
"""

import re
import statistics
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from advisor.collectors.feeds import NewsItem, TickerNewsItem
from advisor.models import AssetRef, AssetType
from advisor.news.mapping import TickerMap
from advisor.news.sentiment import Scorer
from advisor.news.stories import cluster, similar, story_key, title_words

WINDOW = timedelta(hours=48)
RECENT = timedelta(hours=24)
OUTLET_CAP = 3
MIN_HISTORY_DAYS = 5


@dataclass(frozen=True)
class NewsRow:
    ref: AssetRef
    published_at: datetime
    outlet: str
    url: str
    title: str
    sentiment: float | None
    cluster_id: str
    story_key: str


@dataclass(frozen=True)
class StoredNews:
    """A story row an earlier run stored for an asset."""

    url: str
    title: str
    published_at: datetime
    story_key: str


@dataclass(frozen=True)
class NewsOutcome:
    rows: list[NewsRow]
    features: list[tuple[AssetRef, dict]]
    summary: dict


def attribute(items: Sequence[NewsItem], ticker_map: TickerMap) -> list[tuple[AssetRef, NewsItem]]:
    pairs: list[tuple[AssetRef, NewsItem]] = []
    for item in items:
        if isinstance(item, TickerNewsItem):
            pairs.append((AssetRef(item.symbol, AssetType.STOCK), item))
        else:
            pairs.extend((ref, item) for ref in sorted(ticker_map.assets_in(item)))
    return pairs


def _mean(values: Sequence[float]) -> float | None:
    return statistics.fmean(values) if values else None


def volume_z(recent: int, history: Sequence[int]) -> float | None:
    """How unusual the last 24 h's story count is against the daily counts before it."""
    if len(history) < MIN_HISTORY_DAYS:
        return None
    spread = statistics.pstdev(history)
    return (recent - statistics.fmean(history)) / spread if spread > 0 else None


def outlet_key(outlet: str) -> str:
    """One publisher however a source spells it: "MarketBeat", "marketbeat.com", "www.MarketBeat.com"."""
    name = outlet.casefold().removeprefix("www.")
    if "." in name and " " not in name:
        name = name.rsplit(".", 1)[0]  # a host: drop the top-level domain
    return re.sub(r"[^a-z0-9]", "", name)


def _stored_under_another_key(
    story_items: Sequence[NewsItem], item: NewsItem, earlier: Sequence[StoredNews]
) -> bool:
    """Whether an earlier run stored this story for the asset under another item's key.

    That happens when the story's first item has left the 48-hour window since, or a source
    returned an older item late. Matching follows story grouping: a shared link, or a similar title
    within 48 hours. A row with this item's own key is the same row, and the upsert keeps it.
    """
    if any(row.story_key == story_key(item) for row in earlier):
        return False
    for row in earlier:
        row_words = title_words(row.title)
        for member in story_items:
            if row.url == member.url:
                return True
            if abs(member.published_at - row.published_at) <= WINDOW and similar(
                row_words, title_words(member.title)
            ):
                return True
    return False


def process_news(
    items: Sequence[NewsItem],
    ticker_map: TickerMap,
    targets: Sequence[AssetRef],
    as_of: datetime,
    *,
    scorer: Scorer | None,
    history: Mapping[AssetRef, Sequence[int]],
    stored: Mapping[AssetRef, Sequence[StoredNews]] | None = None,
) -> NewsOutcome:
    recent = [item for item in items if as_of - WINDOW <= item.published_at <= as_of]
    story_of = cluster(recent)
    members: dict[str, list[NewsItem]] = defaultdict(list)  # story -> its items in the window
    for item in recent:
        members[story_of[story_key(item)]].append(item)

    chosen: dict[AssetRef, dict[str, NewsItem]] = defaultdict(dict)  # asset -> story -> item
    attributed = sorted(
        attribute(recent, ticker_map),
        key=lambda p: (p[1].published_at, story_key(p[1]), p[1].url, p[0]),
    )
    for ref, item in attributed:
        chosen[ref].setdefault(story_of[story_key(item)], item)  # the story's earliest item
    kept: dict[AssetRef, list[tuple[str, NewsItem]]] = {}
    for ref, stories in chosen.items():
        per_outlet: dict[str, int] = defaultdict(int)
        kept[ref] = []
        for story, item in sorted(stories.items(), key=lambda s: (s[1].published_at, s[0]), reverse=True):
            if per_outlet[outlet_key(item.outlet)] < OUTLET_CAP:
                per_outlet[outlet_key(item.outlet)] += 1
                kept[ref].append((story, item))

    headlines: dict[str, str] = {}
    for stories in kept.values():
        for story, item in stories:
            headlines.setdefault(story, item.title)
    scores: dict[str, float] = {}
    if scorer is not None and headlines:
        ordered = sorted(headlines)
        scores = dict(zip(ordered, scorer([headlines[s] for s in ordered]), strict=True))

    rows = sorted(
        (
            NewsRow(
                ref=ref,
                published_at=item.published_at,
                outlet=item.outlet,
                url=item.url,
                title=item.title,
                sentiment=scores.get(story),
                cluster_id=story,
                story_key=story_key(item),
            )
            for ref, stories in kept.items()
            for story, item in stories
            if not _stored_under_another_key(members[story], item, (stored or {}).get(ref, ()))
        ),
        key=lambda row: (row.ref, row.published_at, row.story_key, row.url),
    )

    features: list[tuple[AssetRef, dict]] = []
    for ref in targets:
        stories = kept.get(ref, [])
        newer = [scores[s] for s, i in stories if s in scores and as_of - i.published_at <= RECENT]
        older = [scores[s] for s, i in stories if s in scores and as_of - i.published_at > RECENT]
        both = newer + older
        last_day = sum(1 for _, item in stories if as_of - item.published_at <= RECENT)
        features.append((ref, {
            "news_stories_48h": len(stories),
            "news_outlets_48h": len({outlet_key(item.outlet) for _, item in stories}),
            "news_sentiment_mean": _mean(both),
            "news_sentiment_trend": (
                _mean(newer) - _mean(older) if newer and older else None
            ),
            "news_volume_z": volume_z(last_day, history.get(ref, [])),
        }))

    return NewsOutcome(
        rows=rows,
        features=features,
        summary={
            "items": len(recent),
            "stories": len(set(story_of.values())),
            "rows": len(rows),
            "assets": len([ref for ref in targets if kept.get(ref)]),
            "sentiment": "finbert" if scorer is not None else "unavailable",
        },
    )
