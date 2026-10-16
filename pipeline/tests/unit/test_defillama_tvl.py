import json
from datetime import UTC, date, datetime

import httpx
import pytest

from advisor.collectors.base import PartialFetch
from advisor.collectors.defillama_tvl import DefiLlamaTvl, parse_history

AS_OF = datetime(2026, 10, 15, 12, 15, tzinfo=UTC)


def points(fixtures_dir, chain: str) -> list[dict]:
    path = fixtures_dir / "defillama" / f"defillama_historical_{chain}_trimmed.json"
    return json.loads(path.read_text(encoding="utf-8"))


def serving(fixtures_dir, seen: list) -> DefiLlamaTvl:
    def handler(request: httpx.Request) -> httpx.Response:
        chain = request.url.path.removeprefix("/v2/historicalChainTvl/")
        seen.append(chain)
        if chain not in ("Ethereum", "Solana"):
            return httpx.Response(404, text="<html><center>404 Not Found</center></html>")
        return httpx.Response(200, json=points(fixtures_dir, chain))

    return DefiLlamaTvl(httpx.Client(transport=httpx.MockTransport(handler)))


def test_the_last_60_finished_days_are_kept(fixtures_dir):
    rows = parse_history("ETH", "Ethereum", points(fixtures_dir, "Ethereum"), AS_OF)
    assert (len(rows), rows[0].day) == (60, date(2026, 8, 16))
    assert (rows[-1].symbol, rows[-1].chain, rows[-1].day, rows[-1].tvl_usd) == (
        "ETH", "Ethereum", date(2026, 10, 14), 50917908224.0
    )  # 2026-10-15 is still moving


def test_days_without_tvl_are_dropped():
    zeros = [{"date": 1791849600, "tvl": 0}, {"date": 1791936000, "tvl": 0}]  # a chain with no TVL
    assert parse_history("DOT", "Polkadot", zeros, AS_OF) == []


def test_each_coin_with_a_chain_gets_one_request(fixtures_dir):
    seen: list = []
    rows = serving(fixtures_dir, seen).fetch(["SOL", "LINK", "ETH"], AS_OF)
    assert seen == ["Solana", "Ethereum"]  # LINK has no chain of its own: no request
    assert [(symbol, len([r for r in rows if r.symbol == symbol])) for symbol in ("SOL", "ETH")] == [
        ("SOL", 60), ("ETH", 60)
    ]


def test_a_failing_chain_is_a_partial_result(fixtures_dir):
    with pytest.raises(PartialFetch, match="1 of 2 symbols failed; first: AVAX: HTTPStatusError") as caught:
        serving(fixtures_dir, []).fetch(["AVAX", "ETH"], AS_OF)
    assert {r.symbol for r in caught.value.records} == {"ETH"}
