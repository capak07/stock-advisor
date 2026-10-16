from datetime import UTC, datetime

import pytest

from advisor.collectors.feeds import canonical_url, parse_date, parse_feed, plain_text


def feed(fixtures_dir, name: str) -> bytes:
    return (fixtures_dir / "news" / name).read_bytes()


def test_an_rss_feed_gives_dated_items_in_utc(fixtures_dir):
    entries = parse_feed(feed(fixtures_dir, "prnewswire_financial.xml"))
    assert len(entries) == 10
    first = entries[0]
    assert first.title.startswith("Centene Corporation Demonstrates Commitment")
    assert first.published_at == datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
    assert "(NYSE: CNC)" in first.summary  # the description's HTML is reduced to text
    assert first.url.startswith("https://www.prnewswire.com/news-releases/centene-corporation")


def test_offsets_are_converted_unless_the_feed_states_them_wrongly(fixtures_dir):
    body = feed(fixtures_dir, "bnnbloomberg-rss.xml")  # "Fri, 16 Oct 2026 11:59:01 -0400"
    assert parse_feed(body)[0].published_at == datetime(2026, 10, 16, 15, 59, 1, tzinfo=UTC)
    # BNN built this feed at 12:01:46 UTC: the clock time is UTC and the offset is wrong
    assert parse_feed(body, clock_is_utc=True)[0].published_at == datetime(
        2026, 10, 16, 11, 59, 1, tzinfo=UTC
    )


def test_google_news_names_the_outlet(fixtures_dir):
    first = parse_feed(feed(fixtures_dir, "google_news_us_apple.xml"))[0]
    assert first.outlet == "Reuters"
    assert first.title == "COMMENTARY: Apple 'faceprints' case tests reach of biometric privacy law - Reuters"
    assert first.url.startswith("https://news.google.com/rss/articles/CBMi")
    assert "?" not in first.url  # Google's ?oc=5 tracker is dropped


def test_nasdaq_names_tickers(fixtures_dir):
    entries = parse_feed(feed(fixtures_dir, "nasdaq_stocks.xml"))
    assert len(entries[0].tags) == 45  # a roundup
    assert entries[1].tags == ["CTSH"]
    assert parse_feed(feed(fixtures_dir, "cnbc_top.xml"))[0].tags == []


@pytest.mark.parametrize(
    ("url", "canonical"),
    [
        (
            "https://www.marketwatch.com/story/apple-c9066b13?mod=mw_rss_topstories",
            "https://www.marketwatch.com/story/apple-c9066b13",
        ),
        ("https://247wallst.com/a/apple/?.tsrc=rss", "https://247wallst.com/a/apple/"),
        ("HTTPS://Cointelegraph.com/news/x?utm_source=rss&utm_medium=rss", "https://cointelegraph.com/news/x"),
        (  # bulletins differ only in ?g=, which must stay
            "https://www.marketwatch.com/bulletins/redirect/go?g=3a54&mod=mw_rss_bulletins",
            "https://www.marketwatch.com/bulletins/redirect/go?g=3a54",
        ),
        ("https://example.com/x?model=7#top", "https://example.com/x?model=7"),
    ],
)
def test_canonical_links_drop_only_trackers(url, canonical):
    assert canonical_url(url) == canonical


def test_marketwatch_bulletins_stay_apart(fixtures_dir):
    entries = parse_feed(feed(fixtures_dir, "marketwatch_bulletins.xml"))
    assert len({entry.url for entry in entries}) == 10  # one /bulletins/redirect/go?g=... each


def test_plain_text_decodes_entities_and_drops_tags():
    raw = '<a href="https://x">Apple &amp; Meta</a>&nbsp;&nbsp;<font color="#6f6f6f">Reuters</font>'
    assert plain_text(raw) == "Apple & Meta Reuters"


@pytest.mark.parametrize("text", [None, "", "yesterday", "Fri, 32 Oct 2026 99:00:00 +0000"])
def test_unreadable_dates_are_none(text):
    assert parse_date(text) is None


def test_an_item_without_a_date_title_or_link_is_skipped():
    body = (
        b"<rss version='2.0'><channel>"
        b"<item><title>No date</title><link>https://x/1</link></item>"
        b"<item><title></title><link>https://x/2</link><pubDate>Fri, 16 Oct 2026 12:00:00 GMT</pubDate></item>"
        b"<item><title>Kept</title><link>https://x/3</link><pubDate>Fri, 16 Oct 2026 12:00:00 GMT</pubDate></item>"
        b"</channel></rss>"
    )
    assert [entry.title for entry in parse_feed(body)] == ["Kept"]


def test_only_web_links_are_kept():
    """A link is stored and later shown as a link, so only http and https get through."""
    item = "<item><title>{}</title><link>{}</link><pubDate>Fri, 16 Oct 2026 12:00:00 GMT</pubDate></item>"
    links = ["javascript:alert(1)", "data:text/html,hi", "ftp://x/1", "/relative/2", "HTTPS://x/3", "http://x/4"]
    body = "<rss version='2.0'><channel>{}</channel></rss>".format(
        "".join(item.format(f"T{n}", link) for n, link in enumerate(links))
    ).encode()
    assert [entry.title for entry in parse_feed(body)] == ["T4", "T5"]


@pytest.mark.parametrize(
    "body",
    [
        b"<!DOCTYPE html><html><body>Our systems have detected unusual traffic</body></html>",
        b"<html><body>sorry</body></html>",
        b"No data could be found.",
        b"",
    ],
)
def test_anything_but_an_rss_document_is_an_error(body):
    with pytest.raises(ValueError, match="not an RSS feed"):
        parse_feed(body)
