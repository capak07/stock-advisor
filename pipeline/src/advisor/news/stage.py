"""The news stage (spec §4.3 stage 5): from fetched headlines to stories, sentiment and features.

1. Keep the items published in the 48 hours before `as_of`.
2. Attribute each item. A per-stock item (Google News, Yahoo) goes to its stock. A market-wide item
   goes to the targets it names (`advisor.news.mapping`).
3. Group items into stories (`advisor.news.stories`). Each asset keeps one item per story, and at
   most 3 stories per outlet: MarketBeat alone filled 60 of Google's 100 results for Apple.
4. Score each story's headline once (FinBERT).
5. Compute per-asset features: stories, outlets, mean sentiment, and the sentiment trend (the last
   24 h minus the 24 h before). The volume z-score compares the last 24 h's stories with the
   asset's daily story counts in news_items before them.
"""

import statistics
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from advisor.collectors.feeds import NewsItem, TickerNewsItem
from advisor.models import AssetRef, AssetType
from advisor.news.mapping import TickerMap
from advisor.news.sentiment import Scorer
from advisor.news.stories import cluster, story_key

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


def process_news(
    items: Sequence[NewsItem],
    ticker_map: TickerMap,
    targets: Sequence[AssetRef],
    as_of: datetime,
    *,
    scorer: Scorer | None,
    history: Mapping[AssetRef, Sequence[int]],
) -> NewsOutcome:
    recent = [item for item in items if as_of - WINDOW <= item.published_at <= as_of]
    story_of = cluster(recent)

    chosen: dict[AssetRef, dict[str, NewsItem]] = defaultdict(dict)  # asset -> story -> item
    for ref, item in sorted(attribute(recent, ticker_map), key=lambda p: p[1].published_at):
        chosen[ref].setdefault(story_of[story_key(item)], item)  # the story's earliest item
    kept: dict[AssetRef, list[tuple[str, NewsItem]]] = {}
    for ref, stories in chosen.items():
        per_outlet: dict[str, int] = defaultdict(int)
        kept[ref] = []
        for story, item in sorted(stories.items(), key=lambda s: s[1].published_at, reverse=True):
            if per_outlet[item.outlet] < OUTLET_CAP:
                per_outlet[item.outlet] += 1
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
        ),
        key=lambda row: (row.ref, row.published_at),
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
            "news_outlets_48h": len({item.outlet for _, item in stories}),
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
