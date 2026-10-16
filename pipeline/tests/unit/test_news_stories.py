from datetime import UTC, datetime, timedelta

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
    first = item("Apple shares surge after record iPhone sales beat estimates", "Reuters")
    later = item("Apple shares surge after record iPhone sales beat estimates again", "CNBC", hours=3)
    other = item("Tesla plunges as deliveries miss estimates", "CNBC", hours=1)
    ids = cluster([later, other, first])
    assert ids[story_key(first)] == ids[story_key(later)] == story_key(first)  # the earliest names it
    assert ids[story_key(other)] == story_key(other)


def test_a_shared_link_is_one_story_whatever_the_titles():
    a = item("Fed holds rates", url="https://www.cnbc.com/fed")
    b = item("Powell speaks after the decision", "CNBC", url="https://www.cnbc.com/fed", hours=1)
    ids = cluster([a, b])
    assert ids[story_key(b)] == story_key(a)


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
