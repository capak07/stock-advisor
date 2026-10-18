from datetime import UTC, date, datetime, timedelta

import httpx
import pandas as pd
import pytest

from advisor.collectors.series import SeriesObservation
from advisor.history import (
    BENCHMARK_REFS,
    backfill_starts,
    closes_from_bars,
    coin_backfill_starts,
    currency_of,
    download_closes,
    fetch_coin_closes,
    fetch_usd_cad,
    fx_backfill_start,
    rebase_factor,
    usd_cad,
)
from advisor.models import AssetRef, AssetType, DailyClose
from fakes import bar

TODAY = date(2026, 10, 14)
AAPL = AssetRef("AAPL", AssetType.STOCK)
RY = AssetRef("RY.TO", AssetType.STOCK)
PLTR = AssetRef("PLTR", AssetType.STOCK)
BTC = AssetRef("BTC", AssetType.CRYPTO)
SPY, XIU = BENCHMARK_REFS
FIELDS = ["Open", "High", "Low", "Close", "Volume"]


def test_closes_carry_their_markets_currency():
    assert [currency_of(ref) for ref in (AAPL, RY, BTC)] == ["USD", "CAD", "USD"]
    bars = {
        "AAPL": [bar("AAPL", date(2026, 10, 13), 228.0)],
        "RY.TO": [bar("RY.TO", date(2026, 10, 13), 184.0)],
    }
    assert closes_from_bars(bars, [AAPL, RY, BTC]) == [
        DailyClose(AAPL, date(2026, 10, 13), 228.0, "USD"),
        DailyClose(RY, date(2026, 10, 13), 184.0, "CAD"),
    ]  # BTC had no bars


def fresh(*closes: float, start: date = date(2026, 7, 1)) -> list[DailyClose]:
    return [DailyClose(AAPL, start + timedelta(days=i), c, "USD") for i, c in enumerate(closes)]


def stored(*closes: float, start: date = date(2026, 7, 1)) -> dict[date, float]:
    return {start + timedelta(days=i): c for i, c in enumerate(closes)}


def test_unchanged_history_needs_no_rescale():
    assert rebase_factor(stored(100, 101, 102), fresh(100, 101, 102, 103)) is None
    assert rebase_factor(stored(100, 101, 102), fresh(100.1, 101.1, 102.1)) is None  # within 0.2%
    assert rebase_factor({}, fresh(100, 101)) is None  # nothing stored yet


def test_a_split_halves_older_closes():
    assert rebase_factor(stored(200, 202, 204, 206, 208), fresh(100, 101, 102, 103, 104)) == 0.5


def test_a_dividend_rescales_by_its_factor():
    assert rebase_factor(stored(100, 100, 100, 100), fresh(99, 99, 99, 99)) == pytest.approx(0.99)


def test_an_ex_dividend_day_inside_the_window_uses_the_oldest_days():
    # Yahoo lowered the closes before the 4th day by 1%; the days after it are unchanged.
    factor = rebase_factor(stored(100, 100, 100, 100, 100, 100), fresh(99, 99, 99, 100, 100, 100))
    assert factor == pytest.approx(0.99)


def test_a_single_bad_quote_changes_nothing():
    assert rebase_factor(stored(100, 100, 100, 100, 100), fresh(100, 50, 100, 100, 100)) is None


def test_days_that_disagree_change_nothing():
    assert rebase_factor(stored(100, 100, 100, 100, 100), fresh(50, 80, 120, 90, 70)) is None


def test_backfill_reaches_a_year_or_the_first_buy():
    buys = {AAPL: date(2025, 5, 12), RY: date(2026, 9, 1)}
    starts = backfill_starts(TODAY, buys, [PLTR, BTC], {RY: date(2025, 10, 20)})
    assert starts == {
        AAPL: date(2025, 5, 12),  # bought more than a year ago: from the first buy
        PLTR: date(2025, 10, 14),  # watched: a year
        SPY: date(2025, 5, 12),  # the benchmarks reach the oldest buy
        XIU: date(2025, 5, 12),
    }  # RY.TO is stored from within a week of a year ago; coins need no backfill


def test_nothing_to_backfill_once_stored():
    earliest = {AAPL: date(2025, 5, 12), SPY: date(2025, 5, 13), XIU: date(2025, 5, 14)}
    assert backfill_starts(TODAY, {AAPL: date(2025, 5, 12)}, [], earliest) == {}


def test_the_backfill_downloads_each_batch_from_its_earliest_start():
    calls = []

    def download(tickers, start, end):
        calls.append((tickers, start, end))
        index = pd.DatetimeIndex([pd.Timestamp("2025-05-12"), pd.Timestamp("2025-05-13")])
        columns = pd.MultiIndex.from_product([tickers, FIELDS])
        rows = [[10, 11, 9, 10.5, 1000] * len(tickers), [10.5, 12, 10, 11.0, 2000] * len(tickers)]
        return pd.DataFrame(rows, index=index, columns=columns)

    brk = AssetRef("BRK.B", AssetType.STOCK)
    closes = download_closes({brk: date(2025, 5, 12), RY: date(2025, 10, 14)}, TODAY, download)
    assert calls == [(["BRK-B", "RY.TO"], date(2025, 5, 12), date(2026, 10, 15))]
    assert {(c.ref.symbol, c.day, c.close, c.currency) for c in closes} == {
        ("BRK.B", date(2025, 5, 12), 10.5, "USD"), ("BRK.B", date(2025, 5, 13), 11.0, "USD"),
        ("RY.TO", date(2025, 5, 12), 10.5, "CAD"), ("RY.TO", date(2025, 5, 13), 11.0, "CAD"),
    }


def test_usd_cad_comes_from_the_valet_series():
    records = [
        SeriesObservation(series="FXUSDCAD", day=date(2026, 10, 13), value=1.3712),
        SeriesObservation(series="V39079", day=date(2026, 10, 13), value=2.25),
        SeriesObservation(series="FXUSDCAD", day=date(2026, 10, 9), value=1.3698),
    ]
    assert usd_cad(records) == [(date(2026, 10, 9), 1.3698), (date(2026, 10, 13), 1.3712)]


def test_the_fx_backfill_asks_the_bank_of_canada_from_its_start(fixtures_dir):
    seen = []
    body = (fixtures_dir / "boc" / "valet_observations_recent10.json").read_bytes()

    def handler(request):
        seen.append(request)
        return httpx.Response(200, content=body)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        rates = fetch_usd_cad(client, date(2025, 5, 12))
    assert seen[0].url.params["start_date"] == "2025-05-12"
    assert "FXUSDCAD" in seen[0].url.path
    assert len(rates) == 10 and all(1.2 < rate < 1.5 for _, rate in rates)


def test_the_fx_backfill_starts_at_the_oldest_buy_or_a_year_back():
    assert fx_backfill_start(TODAY, {AAPL: date(2025, 5, 12)}, None) == date(2025, 5, 12)
    assert fx_backfill_start(TODAY, {}, date(2026, 6, 16)) == date(2025, 10, 14)  # 120 days stored
    assert fx_backfill_start(TODAY, {}, date(2025, 10, 16)) is None  # within a week of a year


def test_coins_ever_bought_reach_back_a_year_or_to_their_first_buy():
    eth = AssetRef("ETH", AssetType.CRYPTO)
    starts = coin_backfill_starts(
        TODAY,
        {BTC: date(2026, 9, 1), eth: date(2024, 3, 4), AAPL: date(2024, 1, 2)},
        {BTC: date(2025, 12, 28), eth: date(2024, 3, 6)},  # ETH's stored closes reach its first buy
    )
    assert starts == {BTC: date(2025, 10, 14)}  # stocks are Yahoo's backfill, not this one


def candle_rows(start: date, stop: date, close: float) -> list[list[float]]:
    """Coinbase's answer: [time, low, high, open, close, volume], newest first."""
    days = [start + timedelta(days=i) for i in range((stop - start).days)]
    stamp = lambda day: datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp()  # noqa: E731
    return [[stamp(d), close, close, close, close, 1.0] for d in reversed(days)]


def test_the_coin_backfill_asks_coinbase_300_days_at_a_time():
    asked = []

    def handler(request):
        start = date.fromisoformat(request.url.params["start"][:10])
        stop = date.fromisoformat(request.url.params["end"][:10])
        asked.append((request.url.path, start, stop))
        return httpx.Response(200, json=candle_rows(start, stop, 60000.0))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        closes = fetch_coin_closes(client, BTC, date(2025, 1, 1), date(2026, 1, 15))
    assert asked == [
        ("/products/BTC-USD/candles", date(2025, 1, 1), date(2025, 10, 28)),
        ("/products/BTC-USD/candles", date(2025, 10, 28), date(2026, 1, 15)),
    ]
    assert len(closes) == (date(2026, 1, 15) - date(2025, 1, 1)).days
    assert (closes[0].day, closes[-1].day) == (date(2025, 1, 1), date(2026, 1, 14))
    assert {(c.ref, c.currency) for c in closes} == {(BTC, "USD")}


def test_a_coin_coinbase_doesnt_list_has_no_backfill():
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(404))) as client:
        assert fetch_coin_closes(client, AssetRef("XYZ", AssetType.CRYPTO), date(2025, 1, 1), TODAY) == []
