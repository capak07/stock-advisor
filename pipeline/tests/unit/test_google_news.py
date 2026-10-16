from datetime import UTC, datetime

import httpx
import pytest

from advisor.collectors.base import PartialFetch
from advisor.collectors.feeds import parse_feed
from advisor.collectors.google_news import GoogleBlocked, GoogleNews, headline, query_for
from advisor.company_names import CompanyNames

AS_OF = datetime(2026, 10, 16, 12, 15, tzinfo=UTC)
NAMES = CompanyNames({"AAPL": "Apple Inc. - Common Stock", "RY.TO": "Royal Bank of Canada"})


def serving(fixtures_dir, seen: list, answer=None) -> GoogleNews:
    files = {
        '"Apple Inc" when:2d': "google_news_us_apple.xml",
        '"Royal Bank of Canada" when:2d': "google_news_ca_royal_bank.xml",
        "AAPL stock when:2d": "google_news_us_aapl_stock.xml",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        seen.append((params["q"], params["hl"], params["gl"], params["ceid"]))
        if answer is not None:
            return answer
        return httpx.Response(200, content=(fixtures_dir / "news" / files[params["q"]]).read_bytes())

    return GoogleNews(httpx.Client(transport=httpx.MockTransport(handler)), names=NAMES)


def test_stocks_are_searched_by_company_name_in_their_markets_edition(fixtures_dir):
    seen: list = []
    items = serving(fixtures_dir, seen).fetch(["AAPL", "RY.TO"], AS_OF)
    assert seen == [
        ('"Apple Inc" when:2d', "en-US", "US", "US:en"),
        ('"Royal Bank of Canada" when:2d', "en-CA", "CA", "CA:en"),
    ]
    apple = [item for item in items if item.symbol == "AAPL"]
    assert len(apple) == 10
    first = apple[0]
    assert (first.source, first.outlet, first.title) == (
        "google_news", "Reuters", "COMMENTARY: Apple 'faceprints' case tests reach of biometric privacy law"
    )  # " - Reuters" is dropped from the title
    assert {item.symbol for item in items} == {"AAPL", "RY.TO"}


def test_items_older_than_two_days_are_left_out(fixtures_dir):
    items = serving(fixtures_dir, []).fetch(["RY.TO"], AS_OF)
    assert len(items) == 7  # this answer was recorded without when:2d and reaches back to August
    assert min(item.published_at for item in items) >= datetime(2026, 10, 14, 12, 15, tzinfo=UTC)


def test_items_after_as_of_are_left_out(fixtures_dir):
    # The Apple fixture's newest item is 11:18:12 GMT; the run is taken as of 11:00 GMT.
    as_of = datetime(2026, 10, 16, 11, 0, tzinfo=UTC)
    raw = parse_feed((fixtures_dir / "news" / "google_news_us_apple.xml").read_bytes())
    newest = max(raw, key=lambda entry: entry.published_at)
    assert newest.published_at > as_of  # so the test can't pass vacuously
    items = serving(fixtures_dir, []).fetch(["AAPL"], as_of)
    assert items
    assert all(item.published_at <= as_of for item in items)
    assert newest.url not in {item.url for item in items}


def test_a_stock_without_a_name_is_searched_by_ticker():
    assert query_for("AAPL", None) == "AAPL stock when:2d"
    assert query_for("RY.TO", None) == "RY stock when:2d"
    assert query_for("BRK.B", "Berkshire Hathaway Inc. Class B Common Stock") == '"Berkshire Hathaway Inc" when:2d'
    assert query_for("XYZ", "(Holding Company)") == "XYZ stock when:2d"  # nothing left to quote


@pytest.mark.parametrize(
    ("title", "outlet", "expected"),
    [
        ("Apple sues Masimo - Reuters", "Reuters", "Apple sues Masimo"),
        ("Fed holds - rates steady - CNBC", "CNBC", "Fed holds - rates steady"),
        ("Apple sues Masimo - Reuters", None, "Apple sues Masimo - Reuters"),
        ("Apple sues Masimo", "Reuters", "Apple sues Masimo"),
    ],
)
def test_the_outlet_suffix_is_dropped_from_titles(title, outlet, expected):
    assert headline(title, outlet) == expected


@pytest.mark.parametrize(
    "answer",
    [
        httpx.Response(200, text="<html><body>Our systems have detected unusual traffic</body></html>"),
        httpx.Response(429),
    ],
)
def test_a_bot_check_stops_the_source_for_the_run(fixtures_dir, answer):
    seen: list = []
    with pytest.raises((GoogleBlocked, httpx.HTTPStatusError)):
        serving(fixtures_dir, seen, answer).fetch(["AAPL", "RY.TO", "SHOP.TO"], AS_OF)
    assert len({query for query, *_ in seen}) == 1  # nothing after the first stock is asked


def test_a_block_after_some_stocks_keeps_what_came_back(fixtures_dir):
    blocked = httpx.Response(200, text="<html>sorry</html>")
    files = {'"Apple Inc" when:2d': (fixtures_dir / "news" / "google_news_us_apple.xml").read_bytes()}

    def handler(request: httpx.Request) -> httpx.Response:
        body = files.get(request.url.params["q"])
        return httpx.Response(200, content=body) if body else blocked

    collector = GoogleNews(httpx.Client(transport=httpx.MockTransport(handler)), names=NAMES)
    with pytest.raises(PartialFetch, match="stopped after 1 of 2 symbols; RY.TO: GoogleBlocked") as caught:
        collector.fetch(["AAPL", "RY.TO"], AS_OF)
    assert {item.symbol for item in caught.value.records} == {"AAPL"}
