"""Stories: one per news event, however many feeds and queries carried it (spec §4.3 stage 5).

**Grouping.** Two items are one story when they share a link, or when their titles' word sets have a
Jaccard similarity of at least 0.8 within 48 hours.

**Why exact Jaccard.** It replaces the spec's MinHash estimate. At a few thousand headlines exact
Jaccard costs about two seconds, while MinHash on ten-word titles is too noisy at 0.8 (Plan 2f
research).

**Keys.**
- An item's key is a hash of its outlet and normalized title. Google's links differ by query, so a
  link can't be the key, and the key is stable from run to run.
- A story's id is the key of its earliest item.
"""

import hashlib
import re
from collections import defaultdict
from collections.abc import Sequence
from datetime import timedelta

from advisor.collectors.feeds import NewsItem

SIMILAR = 0.8
WINDOW = timedelta(hours=48)
TOKEN = re.compile(r"[a-z0-9$%.]+")


def title_words(title: str) -> frozenset[str]:
    return frozenset(TOKEN.findall(title.lower()))


def story_key(item: NewsItem) -> str:
    """Stable across runs: the outlet and the title's words, lower-cased."""
    normalized = " ".join(re.findall(r"[a-z0-9]+", item.title.lower()))
    return hashlib.sha1(f"{item.outlet.casefold()}|{normalized}".encode()).hexdigest()[:16]


def similar(a: frozenset[str], b: frozenset[str]) -> bool:
    if not a or not b or min(len(a), len(b)) < SIMILAR * max(len(a), len(b)):
        return False  # sizes alone rule out a Jaccard of 0.8
    return len(a & b) >= SIMILAR * len(a | b)


def cluster(items: Sequence[NewsItem]) -> dict[str, str]:
    """Story id by item key, oldest items first; each item joins the first story it matches."""
    ids: dict[str, str] = {}
    by_url: dict[str, str] = {}
    stories: list[tuple[frozenset[str], NewsItem, str]] = []  # (words, first item, story id)
    index: dict[str, list[int]] = defaultdict(list)  # word -> stories whose first title has it
    for item in sorted(items, key=lambda i: (i.published_at, story_key(i))):
        key = story_key(item)
        if key in ids:
            continue
        found = by_url.get(item.url)
        if found is None:
            item_words = title_words(item.title)
            candidates = sorted({n for word in item_words for n in index[word]})
            for n in candidates:
                first_words, first, story_id = stories[n]
                if item.published_at - first.published_at <= WINDOW and similar(
                    item_words, first_words
                ):
                    found = story_id
                    break
            if found is None:
                found = key
                for word in item_words:
                    index[word].append(len(stories))
                stories.append((item_words, item, key))
        ids[key] = found
        by_url.setdefault(item.url, found)
    return ids
