from datetime import UTC, datetime

from advisor.collectors.feeds import NewsItem
from advisor.models import AssetRef, AssetType
from advisor.news.mapping import TickerMap, tsx_symbol, words

NAMES = {
    "AAPL": "Apple Inc. - Common Stock",
    "APLE": "Apple Hospitality REIT, Inc. Common Shares",
    "GOOG": "Alphabet Inc. - Class C Capital Stock",
    "GOOGL": "Alphabet Inc. - Class A Common Stock",
    "TGT": "Target Corporation Common Stock",
    "CNC": "Centene Corporation Common Stock",
    "CTSH": "Cognizant Technology Solutions Corporation - Class A Common Stock",
    "RY.TO": "Royal Bank of Canada",
    "BBD-B.TO": "Bombardier Inc.",
    "MSFT": "Microsoft Corporation - Common Stock",
    "NDAQ": "Nasdaq, Inc. - Common Stock",
    "MS": "Morgan Stanley Common Stock",
    "TSLA": "Tesla, Inc. - Common Stock",
    "WMT": "Walmart Inc. Common Stock",
    "COST": "Costco Wholesale Corporation - Common Stock",
    "GS": "Goldman Sachs Group, Inc. (The) Common Stock",
}
COINS = {"BTC": "Bitcoin", "ETH": "Ethereum", "XLM": "Stellar"}


def stock(symbol: str) -> AssetRef:
    return AssetRef(symbol, AssetType.STOCK)


def coin(symbol: str) -> AssetRef:
    return AssetRef(symbol, AssetType.CRYPTO)


TARGETS = [
    stock(s)
    for s in (
        "AAPL", "GOOG", "GOOGL", "TGT", "CNC", "CTSH", "RY.TO", "BBD-B.TO", "NDAQ", "MS", "TSLA",
        "WMT", "COST", "GS",
    )
]
TARGETS += [coin("BTC"), coin("ETH"), coin("XLM")]
MAP = TickerMap(NAMES, COINS, TARGETS)


def item(title: str, summary: str = "", tags: list[str] | None = None) -> NewsItem:
    return NewsItem(
        source="test", outlet="Test", title=title, url="https://example.com/x",
        published_at=datetime(2026, 10, 16, 12, tzinfo=UTC), summary=summary, tags=tags or [],
    )


def test_tickers_the_feed_names_count():
    assert MAP.assets_in(item("CTSH crosses above target", tags=["CTSH"])) == {stock("CTSH")}


def test_a_roundup_naming_many_tickers_counts_for_none():
    tags = ["AAPL", "MSFT", "CTSH", "CNC", "TGT", "RY", "IBM", "ORCL", "AMD"]
    assert MAP.assets_in(item("Stocks settle mixed", tags=tags)) == set()


def test_exchange_tags_in_the_text_count():
    release = item(
        "Centene Corporation Demonstrates Commitment",
        "ST. LOUIS /PRNewswire/ -- Centene Corporation (NYSE: CNC), a leading healthcare enterprise",
    )
    assert MAP.assets_in(release) == {stock("CNC")}
    assert MAP.assets_in(item("Bombardier lands order (TSX: BBD.B)")) == {stock("BBD-B.TO")}
    assert MAP.assets_in(item("Apple Inc. (NASDAQ:AAPL) shares sold")) == {stock("AAPL")}
    assert MAP.assets_in(item("Tiny miner drills (TSXV: THY.P)")) == set()  # outside the universe


def test_cashtags_count_for_stocks_and_coins():
    assert MAP.assets_in(item("Why $AAPL and $BTC moved")) == {stock("AAPL"), coin("BTC")}


def test_names_in_the_title_count_and_the_longest_name_wins():
    assert MAP.assets_in(item("Apple's foldable iPhone worth $2,000?")) == {stock("AAPL")}
    assert MAP.assets_in(item("Apple Hospitality REIT raises dividend")) == set()  # APLE isn't a target
    assert MAP.assets_in(item("Royal Bank of Canada beats estimates")) == {stock("RY.TO")}
    assert MAP.assets_in(item("Bitcoin slides as Ethereum holds")) == {coin("BTC"), coin("ETH")}


def test_share_classes_share_a_name():
    assert MAP.assets_in(item("Alphabet unveils new AI chips")) == {stock("GOOG"), stock("GOOGL")}


def test_an_everyday_word_name_needs_a_tag_or_cashtag():
    assert MAP.assets_in(item("Analysts raise price target on chipmakers")) == set()
    assert MAP.assets_in(item("Target cuts its outlook")) == set()
    assert MAP.assets_in(item("Target cuts its outlook (NYSE: TGT)")) == {stock("TGT")}


def test_only_targets_are_reported():
    assert MAP.assets_in(item("Microsoft raises guidance (Nasdaq: MSFT)")) == set()


def test_helpers():
    assert tsx_symbol("BBD.B") == "BBD-B.TO"
    assert tsx_symbol("RY") == "RY.TO"
    assert words("Apple's and Meta’s AT&T, Coca-Cola deal") == ["Apple", "and", "Meta", "AT&T", "Coca-Cola", "deal"]


def test_market_wraps_do_not_name_nasdaq_inc():
    assert MAP.assets_in(item("Nasdaq Falls as Yields Rise")) == set()


def test_everyday_word_coin_names_need_a_cashtag():
    assert MAP.assets_in(item("Stellar Quarter for Retailers")) == set()
    assert MAP.assets_in(item("$XLM jumps")) == {coin("XLM")}


def test_another_coin_named_after_bitcoin_is_not_bitcoin():
    assert MAP.assets_in(item("Bitcoin Cash Plunges 20%")) == set()
    assert MAP.assets_in(item("Bitcoin Rises Past $100,000")) == {coin("BTC")}


def test_the_broker_in_an_analyst_headline_is_not_the_subject():
    assert MAP.assets_in(item("Morgan Stanley Upgrades Tesla to Overweight")) == {stock("TSLA")}
    assert MAP.assets_in(item("Morgan Stanley Raises Its Dividend")) == {stock("MS")}
    assert MAP.assets_in(item("Tesla Cuts Prices as Analysts Say Buy")) == {stock("TSLA")}
    assert MAP.assets_in(item("Goldman Sachs Raises Apple Price Target to $250")) == {stock("AAPL")}


def test_companies_acting_in_one_headline_keep_their_news():
    headline = "Walmart Raises Full-Year Target, Costco Wholesale Lifts Outlook"
    assert MAP.assets_in(item(headline)) == {stock("WMT"), stock("COST")}


def test_a_held_coin_named_like_a_lookalike_is_still_found():
    held = TickerMap(NAMES, {**COINS, "BCH": "Bitcoin Cash"}, [*TARGETS, coin("BCH")])
    assert held.assets_in(item("Bitcoin Cash Surges")) == {coin("BCH")}
