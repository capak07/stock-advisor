import httpx
import pytest

from advisor.coin_list import COIN_LIST_SIZE, fetch_top_coins, top_coins


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


def test_an_empty_answer_is_an_error():
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[]))) as client:
        with pytest.raises(ValueError, match="no coins"):
            fetch_top_coins(client)
