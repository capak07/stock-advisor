import json
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest

from advisor.collectors.base import PartialFetch
from advisor.collectors.coins import ExchangeThrottled
from advisor.collectors.kraken_ohlc import KrakenOhlc, kraken_pair, parse_ohlc

AS_OF = datetime(2026, 10, 15, 19, 25, tzinfo=UTC)


def payload(fixtures_dir) -> dict:
    path = fixtures_dir / "kraken" / "kraken_ohlc_XBTUSD_daily_trimmed.json"
    return json.loads(path.read_text(encoding="utf-8"))  # oldest first; the last row is today


def serving(answer, seen: list) -> KrakenOhlc:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url)
        return answer(request)

    return KrakenOhlc(httpx.Client(transport=httpx.MockTransport(handler)))


@pytest.mark.parametrize(
    ("symbol", "pair"), [("BTC", "XBTUSD"), ("DOGE", "XDGUSD"), ("MATIC", "POLUSD"), ("SOL", "SOLUSD")]
)
def test_kraken_names_bitcoin_xbt_and_dogecoin_xdg(symbol, pair):
    assert kraken_pair(symbol) == pair


def test_finished_candles_are_read_from_strings(fixtures_dir):
    bars = parse_ohlc("BTC", payload(fixtures_dir), AS_OF)
    assert (len(bars), bars[0].day) == (119, date(2026, 6, 18))
    assert (bars[-1].day, bars[-1].close, bars[-1].volume, bars[-1].source) == (
        date(2026, 10, 14), 81576.4, 2598.87867869, "kraken"
    )


def test_candles_after_the_last_finished_one_are_still_moving(fixtures_dir):
    data = payload(fixtures_dir)
    data["result"]["last"] = 1791849600  # 2026-10-13
    assert parse_ohlc("BTC", data, AS_OF)[-1].day == date(2026, 10, 13)


def test_fetch_asks_for_the_last_35_days(fixtures_dir):
    seen: list = []
    bars = serving(lambda r: httpx.Response(200, json=payload(fixtures_dir)), seen).fetch(["BTC"], AS_OF)
    [url] = seen
    since = int((AS_OF - timedelta(days=35)).timestamp())
    assert dict(url.params) == {"pair": "XBTUSD", "interval": "1440", "since": str(since)}
    assert len(bars) == 119


def test_a_coin_kraken_does_not_list_has_no_candles():
    unknown = httpx.Response(200, json={"error": ["EQuery:Unknown asset pair"]})
    assert serving(lambda r: unknown, []).fetch(["WSCOIN"], AS_OF) == []


def test_another_kraken_error_fails_the_coin():
    invalid = httpx.Response(200, json={"error": ["EGeneral:Invalid arguments"]})
    with pytest.raises(PartialFetch, match="BTC: ValueError: Kraken: EGeneral:Invalid arguments"):
        serving(lambda r: invalid, []).fetch(["BTC"], AS_OF)


def test_a_kraken_rate_limit_answer_stops_the_loop():
    seen: list = []
    collector = serving(lambda r: httpx.Response(200, json={"error": ["EAPI:Rate limit exceeded"]}), seen)
    with pytest.raises(ExchangeThrottled, match="EAPI:Rate limit exceeded"):
        collector.fetch(["BTC", "ETH"], AS_OF)
    assert len(seen) == 1
