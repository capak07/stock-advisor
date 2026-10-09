from datetime import UTC, date, datetime

import pandas as pd

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
