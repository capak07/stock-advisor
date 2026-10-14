from datetime import UTC, date, datetime

import pandas as pd
import pytest

from advisor.collectors.base import PartialFetch
from advisor.collectors.yfinance_bars import YFinanceBars, parse_frame, to_yahoo

AS_OF = datetime(2026, 10, 14, 19, 15, tzinfo=UTC)
NAN = float("nan")
FIELDS = ["Open", "High", "Low", "Close", "Volume"]


def two_ticker_frame() -> pd.DataFrame:
    index = pd.DatetimeIndex([pd.Timestamp("2026-10-12"), pd.Timestamp("2026-10-13")])
    columns = pd.MultiIndex.from_product([["AAPL", "BRK-B"], FIELDS])
    values = [
        [10, 11, 9, 10.5, 1000, NAN, NAN, NAN, NAN, NAN],
        [10.5, 12, 10, 11.5, 2000, 400, 410, 395, 405, 3000],
    ]
    return pd.DataFrame(values, index=index, columns=columns)


def test_to_yahoo_converts_share_class_separator():
    assert to_yahoo("BRK.B") == "BRK-B"
    assert to_yahoo("AAPL") == "AAPL"


def test_fetch_round_trips_share_class_symbols_and_skips_empty_rows():
    calls = []

    def fake_download(tickers, start, end):
        calls.append((tickers, start, end))
        return two_ticker_frame()

    bars = YFinanceBars(download=fake_download).fetch(["BRK.B", "AAPL"], AS_OF)

    assert calls == [(["AAPL", "BRK-B"], date(2026, 7, 6), date(2026, 10, 15))]
    assert [(b.symbol, b.day, b.close, b.source) for b in bars] == [
        ("AAPL", date(2026, 10, 12), 10.5, "yfinance"),
        ("AAPL", date(2026, 10, 13), 11.5, "yfinance"),
        ("BRK.B", date(2026, 10, 13), 405.0, "yfinance"),
    ]


def test_parse_frame_accepts_single_level_columns_for_one_ticker():
    frame = pd.DataFrame(
        [[1.0, 1.2, 0.9, 1.1, 500]],
        index=pd.DatetimeIndex([pd.Timestamp("2026-10-13")]),
        columns=FIELDS,
    )
    bars = parse_frame(frame, {"AAPL": "AAPL"})
    assert [(b.symbol, b.close) for b in bars] == [("AAPL", 1.1)]


def test_parse_frame_handles_empty_frames():
    assert parse_frame(pd.DataFrame(), {"AAPL": "AAPL"}) == []


def test_fetch_raises_when_five_or_more_symbols_all_come_back_empty():
    collector = YFinanceBars(download=lambda tickers, start, end: pd.DataFrame())
    with pytest.raises(RuntimeError, match="yfinance returned no bars for 5 symbols"):
        collector.fetch(["A", "B", "C", "D", "E"], AS_OF)


def test_fetch_allows_empty_results_for_fewer_than_five_symbols():
    collector = YFinanceBars(download=lambda tickers, start, end: pd.DataFrame())
    assert collector.fetch(["A", "B"], AS_OF) == []


def test_to_yahoo_leaves_tsx_symbols_in_yahoos_form():
    assert to_yahoo("RY.TO") == "RY.TO"
    assert to_yahoo("RCI-B.TO") == "RCI-B.TO"


def test_yahoo_is_the_core_price_source_with_a_tsx_canary():
    collector = YFinanceBars()
    assert collector.core is True
    assert "RY.TO" in collector.canary


def test_fetch_reports_partial_when_a_whole_download_comes_back_empty(monkeypatch):
    monkeypatch.setattr("advisor.collectors.yfinance_bars.SYMBOLS_PER_DOWNLOAD", 5)

    def fake_download(tickers, start, end):  # Yahoo throttles the second download silently
        return two_ticker_frame() if "AAPL" in tickers else pd.DataFrame()

    symbols = ["AAPL", "BRK.B", "C", "D", "E", "F", "G", "H", "I", "J"]
    with pytest.raises(PartialFetch, match="1 of 2 Yahoo downloads returned no bars") as caught:
        YFinanceBars(download=fake_download).fetch(symbols, AS_OF)
    assert {b.symbol for b in caught.value.records} == {"AAPL", "BRK.B"}


def test_fetch_stops_after_three_consecutive_empty_downloads(monkeypatch):
    monkeypatch.setattr("advisor.collectors.yfinance_bars.SYMBOLS_PER_DOWNLOAD", 5)
    calls = []

    def fake_download(tickers, start, end):  # Yahoo answers the first download, then refuses
        calls.append(tickers)
        return two_ticker_frame() if len(calls) == 1 else pd.DataFrame()

    symbols = ["AAPL", "BRK.B"] + [f"S{i:02d}" for i in range(28)]
    with pytest.raises(PartialFetch, match="stopped after 3 consecutive empty Yahoo downloads; "
                       "2 of 6 not tried") as caught:
        YFinanceBars(download=fake_download).fetch(symbols, AS_OF)
    assert len(calls) == 4
    assert {b.symbol for b in caught.value.records} == {"AAPL", "BRK.B"}


def test_fetch_stopping_with_no_bars_at_all_raises_runtime_error(monkeypatch):
    monkeypatch.setattr("advisor.collectors.yfinance_bars.SYMBOLS_PER_DOWNLOAD", 5)
    calls = []

    def fake_download(tickers, start, end):
        calls.append(tickers)
        return pd.DataFrame()

    symbols = [f"S{i:02d}" for i in range(30)]
    with pytest.raises(RuntimeError, match="stopped after 3 consecutive empty Yahoo downloads; "
                       "3 of 6 not tried"):
        YFinanceBars(download=fake_download).fetch(symbols, AS_OF)
    assert len(calls) == 3
