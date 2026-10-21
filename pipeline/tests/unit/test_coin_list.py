import httpx
import pytest

from advisor.coin_list import COIN_LIST_SIZE, coinbase_usd_coins, fetch_top_coins, top_coins


def coin(symbol: str, name: str, rank: int | None, cap: float | None = None) -> dict:
    """A row of CoinGecko's /coins/markets answer, with the fields the list uses."""
    row = {"id": name.lower().replace(" ", "-"), "symbol": symbol, "name": name, "market_cap_rank": rank}
    return row | ({"market_cap": cap} if cap is not None else {})


def test_the_best_ranked_coin_of_each_ticker_is_kept_in_rank_order():
    rows = [
        coin("eth", "Ethereum", 2, 4.1e11),
        coin("btc", "Bitcoin", 1, 2.2e12),
        coin("btc", "Bitcoin Bridged", 900),  # another token calling itself btc
        coin("usdt", "Tether", 3),
        coin("x", "Too Short", 4),  # not a valid crypto symbol in this app
        coin("wbtc.e", "Wrapped", 5),
        coin("sol", "", 6),  # no name
        coin("new", "Unranked Coin", None),
    ]
    assert top_coins(rows) == [
        ("BTC", "Bitcoin", 2.2e12), ("ETH", "Ethereum", 4.1e11), ("USDT", "Tether", None),
        ("NEW", "Unranked Coin", None),
    ]
    assert top_coins(rows, size=2) == [("BTC", "Bitcoin", 2.2e12), ("ETH", "Ethereum", 4.1e11)]


def test_only_coins_coinbase_trades_are_listed_and_renamed_coins_count_under_their_new_ticker():
    rows = [coin("btc", "Bitcoin", 1), coin("bnb", "BNB", 2), coin("matic", "Polygon", 3), coin("eth", "Ethereum", 4)]
    assert top_coins(rows, size=2, tradable={"BTC", "ETH", "POL"}) == [("BTC", "Bitcoin", None), ("MATIC", "Polygon", None)]


def test_coinbase_usd_coins_are_its_online_usd_products():
    products = [
        {"id": "BTC-USD", "base_currency": "BTC", "quote_currency": "USD", "status": "online", "trading_disabled": False},
        {"id": "ETH-EUR", "base_currency": "ETH", "quote_currency": "EUR", "status": "online", "trading_disabled": False},
        {"id": "OLD-USD", "base_currency": "OLD", "quote_currency": "USD", "status": "delisted", "trading_disabled": True},
        {"id": "HALT-USD", "base_currency": "HALT", "quote_currency": "USD", "status": "online", "trading_disabled": True},
    ] + [
        {"id": f"C{i}-USD", "base_currency": f"C{i}", "quote_currency": "USD", "status": "online", "trading_disabled": False}
        for i in range(60)
    ]
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=products))) as client:
        coins = coinbase_usd_coins(client)
    assert "BTC" in coins and len(coins) == 61
    assert not {"ETH", "OLD", "HALT"} & coins


def test_a_short_coinbase_product_list_is_an_error():
    products = [{"id": "BTC-USD", "base_currency": "BTC", "quote_currency": "USD", "status": "online", "trading_disabled": False}]
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=products))) as client:
        with pytest.raises(ValueError, match="only 1 USD coins"):
            coinbase_usd_coins(client)


def test_two_pages_of_markets_are_asked_for_by_market_cap():
    asked = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(dict(request.url.params))
        page = int(request.url.params["page"])
        return httpx.Response(200, json=[coin(f"c{page}{i:03d}", f"Coin {page} {i}", (page - 1) * 250 + i + 1) for i in range(250)])

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        coins = fetch_top_coins(client)
    assert [a["page"] for a in asked] == ["1", "2"]
    assert {(a["vs_currency"], a["order"], a["per_page"]) for a in asked} == {("usd", "market_cap_desc", "250")}
    assert len(coins) == COIN_LIST_SIZE == 300
    assert coins[0] == ("C1000", "Coin 1 0", None)


def test_a_short_answer_is_an_error_so_yesterdays_list_stays():
    page = [coin(f"c{i:03d}", f"Coin {i}", i + 1) for i in range(250)]
    answers = {"1": page, "2": page[:10]}
    handler = lambda r: httpx.Response(200, json=answers[r.url.params["page"]])  # noqa: E731
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError, match="only 260 coins"):
            fetch_top_coins(client)
