import json
from datetime import UTC, datetime

import httpx
import pytest

from advisor.collectors.coingecko import CoinGecko, parse_quotes

AS_OF = datetime(2026, 10, 15, 19, 25, tzinfo=UTC)


def rows(fixtures_dir) -> list[dict]:
    path = fixtures_dir / "coingecko" / "coingecko_markets_cad_symbols_top.json"
    return json.loads(path.read_text(encoding="utf-8"))


def serving(answer, seen: list | None = None, sleeps: list | None = None) -> CoinGecko:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request.url)
        return answer(request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    return CoinGecko(client, sleep=(sleeps.append if sleeps is not None else lambda s: None))


def test_each_ticker_is_priced_by_its_top_ranked_coin(fixtures_dir):
    quotes = parse_quotes(["BTC", "ETH", "SOL", "DOGE", "LINK", "POL"], rows(fixtures_dir), AS_OF)
    assert [(q.symbol, q.coin_id) for q in quotes] == [
        ("BTC", "bitcoin"), ("ETH", "ethereum"), ("SOL", "solana"),
        ("DOGE", "dogecoin"), ("LINK", "chainlink"), ("POL", "polygon-ecosystem-token"),
    ]
    btc = quotes[0]
    assert (btc.price_cad, btc.market_cap_rank, btc.change_24h_pct) == (117087, 1, 0.56002)
    assert btc.updated_at == datetime(2026, 10, 15, 19, 22, 52, tzinfo=UTC)


def test_matic_is_priced_as_pol(fixtures_dir):
    [quote] = parse_quotes(["MATIC"], rows(fixtures_dir), AS_OF)
    assert (quote.symbol, quote.coin_id, quote.price_cad) == ("MATIC", "polygon-ecosystem-token", 0.135977)


def test_a_bridged_token_sharing_the_ticker_loses_to_the_ranked_coin(fixtures_dir):
    bitcoin = next(row for row in rows(fixtures_dir) if row["id"] == "bitcoin")
    bridged = {**bitcoin, "id": "mezo-wrapped-btc", "market_cap_rank": None, "current_price": 116000}
    [quote] = parse_quotes(["BTC"], [bridged, bitcoin], AS_OF)
    assert quote.coin_id == "bitcoin"


def test_a_quote_not_updated_for_a_day_counts_as_missing(fixtures_dir):
    bitcoin = next(row for row in rows(fixtures_dir) if row["id"] == "bitcoin")
    assert parse_quotes(["BTC"], [{**bitcoin, "last_updated": "2026-10-14T19:00:00.000Z"}], AS_OF) == []


def test_fetch_asks_once_in_cad_for_every_ticker(fixtures_dir):
    seen: list = []
    quotes = serving(lambda r: httpx.Response(200, json=rows(fixtures_dir)), seen).fetch(
        ["ETH", "MATIC", "BTC"], AS_OF
    )
    [url] = seen
    assert (url.path, url.params["vs_currency"], url.params["symbols"]) == (
        "/api/v3/coins/markets", "cad", "btc,eth,pol"
    )
    assert [q.symbol for q in quotes] == ["ETH", "MATIC", "BTC"]


def test_a_coin_coingecko_does_not_price_is_left_out(fixtures_dir):
    quotes = serving(lambda r: httpx.Response(200, json=rows(fixtures_dir))).fetch(
        ["BTC", "NOTACOIN"], AS_OF
    )
    assert [q.symbol for q in quotes] == ["BTC"]


def test_a_rate_limited_call_is_retried_once_after_the_wait_coingecko_asks_for():
    seen: list = []
    sleeps: list = []
    limited = httpx.Response(429, headers={"Retry-After": "60"}, json={"status": {"error_code": 429}})
    with pytest.raises(httpx.HTTPStatusError, match="HTTP 429"):
        serving(lambda r: limited, seen, sleeps).fetch(["BTC"], AS_OF)
    assert (len(seen), sleeps) == (2, [60.0])


def test_matic_and_pol_held_together_are_both_priced_from_one_ticker(fixtures_dir):
    seen: list = []
    quotes = serving(lambda r: httpx.Response(200, json=rows(fixtures_dir)), seen).fetch(
        ["MATIC", "POL"], AS_OF
    )
    assert seen[0].params["symbols"] == "pol"
    assert [(q.symbol, q.coin_id) for q in quotes] == [
        ("MATIC", "polygon-ecosystem-token"), ("POL", "polygon-ecosystem-token")
    ]
