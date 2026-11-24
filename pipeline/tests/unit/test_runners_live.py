from datetime import date

import pandas as pd

from advisor.run import runner_splits
from advisor.runners.live import _add_warnings
from fakes import FakeSec
from runner_data import filing

AS_OF = date(2026, 11, 16)
SPLIT = (date(2026, 10, 20), 0.2)


def rows(*symbols):
    return [{"symbol": symbol} for symbol in symbols]


def test_a_failed_split_fetch_leaves_the_signals_unchecked_and_says_why():
    def throttled(symbols):
        raise RuntimeError("throttled " + "x" * 300)

    got = rows("AKAN")
    error = _add_warnings(got, AS_OF, FakeSec(cik=1888014), throttled)
    assert error == ("RuntimeError: throttled " + "x" * 300)[:200]
    assert got[0]["warnings_checked"] is False


def test_a_split_fetch_with_no_signal_symbol_in_it_leaves_them_unchecked():
    got = rows("AKAN", "MULN")
    assert _add_warnings(got, AS_OF, FakeSec(cik=1888014), lambda symbols: {}) is None
    assert [r["warnings_checked"] for r in got] == [False, False]
    got = rows("AKAN", "MULN")
    assert _add_warnings(got, AS_OF, FakeSec(cik=1888014), lambda symbols: {"MULN": []}) is None
    assert [r["warnings_checked"] for r in got] == [True, True]


def test_signals_reached_after_60_seconds_keep_only_the_split_warning_unchecked():
    ticks = iter([0.0, 10.0, 60.5])  # the start, then before each signal
    sec = FakeSec(cik=1888014, filings=[filing("F-1/A", date(2026, 11, 13))])
    got = rows("AKAN", "MULN")
    _add_warnings(got, AS_OF, sec, lambda symbols: {"AKAN": [SPLIT], "MULN": [SPLIT]}, clock=lambda: next(ticks))
    assert ([w["kind"] for w in got[0]["warnings"]], got[0]["warnings_checked"]) == (["share_sale", "reverse_split"], True)
    assert ([w["kind"] for w in got[1]["warnings"]], got[1]["warnings_checked"]) == (["reverse_split"], False)


def test_runner_splits_reads_yahoos_split_ratios_and_names_every_symbol_it_priced():
    days = pd.to_datetime(["2026-10-15", "2026-10-16"])
    fields = ["Open", "High", "Low", "Close", "Volume", "Dividends", "Stock Splits"]
    prices = {
        "AKAN": [[1, 1, 1, 1, 100, 0, 0], [10, 10, 10, 10, 10, 0, 0.1]],  # a 1-for-10 reverse split
        "MULN": [[4, 4, 4, 4, 100, 0, 2.0], [2, 2, 2, 2, 200, 0, 0]],     # a 2-for-1 split
        "QUIET": [[1, 1, 1, 1, 100, 0, 0], [1, 1, 1, 1, 100, 0, 0]],      # no splits: zero rows only
    }
    columns = pd.MultiIndex.from_product([list(prices), fields], names=["Ticker", "Price"])
    frame = pd.DataFrame([sum((prices[t][i] for t in prices), []) for i in range(2)],
                         index=pd.Index(days, name="Date"), columns=columns)
    asked = []

    def download(tickers, start, end):
        asked.append(sorted(tickers))
        return frame

    got = runner_splits(download, AS_OF)(["AKAN", "MULN", "QUIET", "GONE"])
    assert asked == [["AKAN", "GONE", "MULN", "QUIET"]]
    assert got == {"AKAN": [(date(2026, 10, 16), 0.1)], "MULN": [(date(2026, 10, 15), 2.0)], "QUIET": []}
    assert runner_splits(None, AS_OF) is None
