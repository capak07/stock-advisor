from datetime import date

import numpy as np
import pandas as pd
import pytest

from advisor.training.prices import (
    COLUMNS,
    YahooThrottled,
    bars_frame,
    download_history,
    history_start,
)

FIELDS = ["Open", "High", "Low", "Close", "Volume"]
DAYS = pd.to_datetime(["2026-10-15", "2026-10-16"])


def yahoo_frame(tickers: dict[str, list[list[float]]]) -> pd.DataFrame:
    """yf.download's wide frame: one (ticker, field) column per pair, one row per trading day."""
    columns = pd.MultiIndex.from_product([list(tickers), FIELDS], names=["Ticker", "Price"])
    rows = [sum((tickers[t][i] for t in tickers), []) for i in range(len(DAYS))]
    return pd.DataFrame(rows, index=pd.Index(DAYS, name="Date"), columns=columns)


def test_eight_years_back_from_today():
    assert history_start(date(2026, 10, 20)) == date(2018, 10, 20)


def test_a_wide_download_becomes_one_row_per_symbol_and_day():
    frame = yahoo_frame({
        "BRK-B": [[500, 505, 498, 503.5, 3_000_000], [503, 510, 501, 509, 2_500_000]],
        "AAPL": [[340, 345, 338, 343, 50_000_000], [np.nan, np.nan, np.nan, np.nan, np.nan]],
    })
    bars = bars_frame(frame, {"BRK-B": "BRK.B", "AAPL": "AAPL"})
    assert list(bars.columns) == COLUMNS
    assert list(bars.itertuples(index=False, name=None)) == [
        ("AAPL", date(2026, 10, 15), 340.0, 345.0, 338.0, 343.0, 50_000_000),
        ("BRK.B", date(2026, 10, 15), 500.0, 505.0, 498.0, 503.5, 3_000_000),
        ("BRK.B", date(2026, 10, 16), 503.0, 510.0, 501.0, 509.0, 2_500_000),
    ]  # AAPL's empty day is dropped, and BRK-B is the pipeline's BRK.B
    assert {str(bars[c].dtype) for c in ("open", "high", "low", "close")} == {"float32"}


def test_bars_with_a_non_positive_price_are_dropped():
    frame = yahoo_frame({"X": [[1.0, 1.1, 0.0, 1.05, 100], [1.0, 1.2, 0.9, 1.1, 200]]})
    assert list(bars_frame(frame, {"X": "X"})["day"]) == [date(2026, 10, 16)]


def test_a_single_ticker_download_has_flat_columns():
    flat = yahoo_frame({"RY.TO": [[150, 151, 149, 150.5, 1e6], [150.5, 152, 150, 151, 1.2e6]]})["RY.TO"]
    assert list(bars_frame(flat, {"RY.TO": "RY.TO"})["symbol"]) == ["RY.TO", "RY.TO"]


def test_symbols_are_downloaded_a_hundred_at_a_time_with_a_pause_between():
    asked, pauses = [], []

    def download(tickers, start, end):
        asked.append((len(tickers), start, end))
        return yahoo_frame({t: [[1, 1, 1, 1, 10], [1, 1, 1, 1, 10]] for t in tickers[:1]})

    symbols = [f"S{i:03d}" for i in range(250)]
    history = download_history(
        symbols, date(2018, 10, 20), date(2026, 10, 19), download=download, sleep=pauses.append, pause=2.0
    )
    assert asked == [(100, date(2018, 10, 20), date(2026, 10, 20))] * 2 + [(50, date(2018, 10, 20), date(2026, 10, 20))]
    assert pauses == [2.0, 2.0]
    assert sorted(set(history.bars["symbol"])) == ["S000", "S100", "S200"]
    assert len(history.missing) == 247 and history.missing[0] == "S001"


def test_three_empty_downloads_in_a_row_mean_yahoo_is_throttling():
    calls = []

    def download(tickers, start, end):
        calls.append(tickers)
        return pd.DataFrame() if len(calls) > 1 else yahoo_frame({tickers[0]: [[1, 1, 1, 1, 1]] * 2})

    with pytest.raises(YahooThrottled, match="3 Yahoo downloads"):
        download_history([f"S{i:03d}" for i in range(500)], date(2018, 1, 1), date(2026, 1, 1),
                         download=download, sleep=lambda s: None)
    assert len(calls) == 4  # the 5th download is never sent


def test_the_long_frame_round_trips_through_parquet(tmp_path):
    frame = yahoo_frame({"AAPL": [[340, 345, 338, 343, 5e7], [343, 346, 341, 345, 4e7]]})
    bars = bars_frame(frame, {"AAPL": "AAPL"})
    bars.to_parquet(tmp_path / "prices.parquet", compression="zstd", index=False)
    back = pd.read_parquet(tmp_path / "prices.parquet")
    assert back["close"].tolist() == [343.0, 345.0]
    assert list(back.columns) == COLUMNS
