from datetime import UTC, datetime

from advisor.daytrade.news import headlines

FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/"><channel>
<title>Yahoo! Finance: SHOP.TO News</title>
<item><title>Shopify jumps on earnings</title><description>d</description>
<link>https://finance.yahoo.com/news/a.html</link><guid isPermaLink="false">a</guid>
<pubDate>Tue, 10 Nov 2026 14:00:00 +0000</pubDate><source url="https://x">Reuters</source></item>
<item><title>Older but inside the window</title><link>https://finance.yahoo.com/news/b.html</link>
<guid>b</guid><pubDate>Mon, 09 Nov 2026 20:00:00 GMT</pubDate></item>
<item><title>Shopify jumps on earnings</title><link>https://finance.yahoo.com/news/dup.html</link>
<guid>dup</guid><pubDate>Tue, 10 Nov 2026 13:00:00 +0000</pubDate></item>
<item><title>Too old</title><link>https://x/c</link><guid>c</guid><pubDate>Sat, 07 Nov 2026 10:00:00 +0000</pubDate></item>
<item><title>No date</title><link>https://x/d</link><guid>d</guid></item>
<item><title>Newest</title><link>https://x/e</link><guid>e</guid><pubDate>Tue, 10 Nov 2026 15:00:00 +0000</pubDate></item>
</channel></rss>"""
NOW = datetime(2026, 11, 10, 16, tzinfo=UTC)


def test_headlines_newest_first_deduped_and_windowed():
    urls = []
    out = headlines(lambda u: urls.append(u) or FEED, "SHOP.TO", NOW)
    assert urls == ["https://feeds.finance.yahoo.com/rss/2.0/headline?s=SHOP.TO&region=US&lang=en-US"]
    assert [h["title"] for h in out] == ["Newest", "Shopify jumps on earnings", "Older but inside the window"]
    assert out[0] == {"title": "Newest", "url": "https://x/e",
                      "published_at": "2026-11-10T15:00:00+00:00", "outlet": "Yahoo Finance"}
    assert out[1]["outlet"] == "Reuters"


def test_headlines_limit_and_us_class_share_symbol():
    urls = []
    out = headlines(lambda u: urls.append(u) or FEED, "BRK.B", NOW, limit=1)
    assert len(out) == 1 and "s=BRK-B&" in urls[0]


def test_headlines_failures_give_empty_list():
    def boom(_):
        raise OSError("down")

    assert headlines(boom, "AAPL", NOW) == []
    assert headlines(lambda u: "<not xml", "AAPL", NOW) == []
