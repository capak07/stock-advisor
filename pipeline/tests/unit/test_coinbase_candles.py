import json
from datetime import UTC, date, datetime

import httpx
import pytest

from advisor.collectors.base import PartialFetch
from advisor.collectors.coinbase_candles import CoinbaseCandles, parse_candles

AS_OF = datetime(2026, 10, 15, 19, 25, tzinfo=UTC)


def candles(fixtures_dir) -> list[list[float]]:
    path = fixtures_dir / "coinbase" / "coinbase_candles_BTC-USD_daily.json"
    return json.loads(path.read_text(encoding="utf-8"))  # newest first, today's candle included


def serving(answer, seen: list) -> CoinbaseCandles:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url)
        return answer(request)

    return CoinbaseCandles(httpx.Client(transport=httpx.MockTransport(handler)))


def test_finished_days_come_oldest_first(fixtures_dir):
    bars = parse_candles("BTC", candles(fixtures_dir), AS_OF)
    assert (len(bars), bars[0].day) == (119, date(2026, 6, 18))  # 120 rows less today's
    last = bars[-1]
    assert (last.day, last.open, last.high, last.low, last.close, last.volume, last.source) == (
        date(2026, 10, 14), 83101.99, 84062.11, 81332.15, 81566.29, 6527.90385989, "coinbase"
    )


def test_fetch_asks_for_290_days_of_the_usd_product(fixtures_dir):
    seen: list = []
    bars = serving(lambda r: httpx.Response(200, json=candles(fixtures_dir)), seen).fetch(["BTC"], AS_OF)
    [url] = seen
    assert url.path == "/products/BTC-USD/candles"
    assert dict(url.params) == {
        "granularity": "86400", "start": "2025-12-29T00:00:00Z", "end": "2026-10-15T00:00:00Z"
    }
    assert len(bars) == 119


def test_matic_is_asked_for_as_pol(fixtures_dir):
    seen: list = []
    serving(lambda r: httpx.Response(200, json=candles(fixtures_dir)), seen).fetch(["MATIC"], AS_OF)
    assert seen[0].path == "/products/POL-USD/candles"


def test_a_coin_coinbase_does_not_list_has_no_candles():
    seen: list = []
    answer = serving(lambda r: httpx.Response(404, json={"message": "NotFound"}), seen)
    assert answer.fetch(["WSCOIN"], AS_OF) == []


def test_another_error_fails_only_that_coin(fixtures_dir):
    def answer(request: httpx.Request) -> httpx.Response:
        if "ETH-USD" in request.url.path:
            return httpx.Response(400, json={"message": "Unsupported granularity"})
        return httpx.Response(200, json=candles(fixtures_dir))

    with pytest.raises(PartialFetch, match="1 of 2 symbols failed; first: ETH: HTTPStatusError") as caught:
        serving(answer, []).fetch(["ETH", "BTC"], AS_OF)
    assert {bar.symbol for bar in caught.value.records} == {"BTC"}


def test_a_throttling_exchange_stops_the_loop_after_two_attempts():
    seen: list = []
    sleeps: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url)
        return httpx.Response(429, headers={"Retry-After": "60"}, json={"message": "rate limit"})

    collector = CoinbaseCandles(httpx.Client(transport=httpx.MockTransport(handler)), sleep=sleeps.append)
    with pytest.raises(httpx.HTTPStatusError, match="HTTP 429"):
        collector.fetch(["BTC", "ETH"], AS_OF)
    assert len(seen) == 2  # two attempts for BTC; ETH is never asked
    assert len(sleeps) == 1
