from datetime import UTC, datetime, timedelta
from itertools import permutations

from advisor.collectors.feeds import NewsItem
from advisor.news.stories import cluster, similar, story_key, title_words

T0 = datetime(2026, 10, 16, 12, tzinfo=UTC)


def item(title: str, outlet: str = "Reuters", url: str | None = None, hours: float = 0) -> NewsItem:
    return NewsItem(
        source="test", outlet=outlet, title=title, url=url or f"https://example.com/{title[:12]}",
        published_at=T0 + timedelta(hours=hours),
    )


def test_an_items_key_is_its_outlet_and_title_whatever_the_link():
    a = item("Apple sues Masimo over patents", url="https://news.google.com/rss/articles/A")
    b = item("Apple sues Masimo, over patents!", url="https://news.google.com/rss/articles/B")
    assert story_key(a) == story_key(b)
    assert story_key(a) != story_key(item("Apple sues Masimo over patents", outlet="CNBC"))
    assert len(story_key(a)) == 16


def test_near_identical_titles_from_different_outlets_are_one_story():
    first = item(
        "Apple shares surge after record iPhone sales beat estimates",
        "Reuters",
        url="https://www.reuters.com/apple-iphone",
    )
    later = item(
        "Apple shares surge after record iPhone sales beat estimates again",
        "CNBC",
        url="https://www.cnbc.com/apple-iphone",
        hours=3,
    )
    other = item("Tesla plunges as deliveries miss estimates", "CNBC", hours=1)
    ids = cluster([later, other, first])
    assert ids[story_key(first)] == ids[story_key(later)] == story_key(first)  # the earliest names it
    assert ids[story_key(other)] == story_key(other)


def test_a_shared_link_is_one_story_whatever_the_titles():
    a = item("Fed holds rates", url="https://www.cnbc.com/fed")
    b = item("Powell speaks after the decision", "CNBC", url="https://www.cnbc.com/fed", hours=1)
    ids = cluster([a, b])
    assert ids[story_key(b)] == story_key(a)


def test_a_repeated_item_still_links_its_url():
    x1 = item("Apple sues Masimo over patents", url="https://news.google.com/rss/articles/A")
    x2 = item("Apple sues Masimo over patents", url="https://news.google.com/rss/articles/B")
    y = item("Masimo responds to lawsuit", "CNBC", url="https://news.google.com/rss/articles/B", hours=1)
    for items in ([x1, x2, y], [x2, x1, y]):
        assert cluster(items)[story_key(y)] == story_key(x1)


def test_grouping_does_not_depend_on_input_order():
    a = item("Fed holds interest rates steady in October", "Reuters", url="https://www.reuters.com/fed")
    b = item(
        "Fed holds interest rates steady in October again",
        "CNBC",
        url="https://www.cnbc.com/fed-rates",
        hours=1,
    )
    c = item("Nvidia unveils new chip", "Reuters", url="https://www.reuters.com/shared", hours=2)
    d = item("Chipmaker shows off accelerator", "CNBC", url="https://www.reuters.com/shared", hours=3)
    e1 = item("Tesla recalls vehicles", "Reuters", url="https://news.google.com/rss/articles/E1", hours=4)
    e2 = item("Tesla recalls vehicles", "Reuters", url="https://news.google.com/rss/articles/E2", hours=4)
    # Links to the repeat's second URL, so the story depends on the repeat registering it.
    g = item("Gold climbs to a record", "Bloomberg", url="https://news.google.com/rss/articles/E2", hours=5)
    f = item("Oil prices drift lower", "Bloomberg", url="https://www.bloomberg.com/oil", hours=5)
    items = [a, b, c, d, e1, e2, g, f]
    expected = cluster(items)
    assert expected[story_key(b)] == story_key(a)
    assert expected[story_key(g)] == story_key(e1)
    for p in permutations(items):
        assert cluster(list(p)) == expected


def test_similar_titles_more_than_48_hours_apart_are_separate_stories():
    title = "Apple shares surge after record iPhone sales beat estimates"
    a = item(title, url="https://www.reuters.com/a")
    b = item(title, "CNBC", url="https://www.cnbc.com/b", hours=49)
    ids = cluster([a, b])
    assert ids[story_key(b)] == story_key(b)


def test_jaccard_needs_four_fifths_of_the_words():
    ten = title_words("one two three four five six seven eight nine ten")
    assert similar(ten, title_words("one two three four five six seven eight nine ten eleven"))  # 10/11
    assert similar(ten, title_words("one two three four five six seven eight nine"))  # 9/10
    assert similar(ten, title_words("one two three four five six seven eight"))  # 8/10, the edge
    assert not similar(ten, title_words("one two three four five six seven"))  # 7/10
    assert not similar(ten, title_words("one two three four five six seven eight x y"))  # 8/12
    assert not similar(frozenset(), ten)
