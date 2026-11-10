import json
from datetime import date, datetime
from pathlib import Path

import pytest

from advisor.daytrade.bars import Bar, HttpError, YahooClient, YahooError, session_bars
from advisor.models import ET

FIX = Path(__file__).parent.parent / "fixtures" / "daytrade"


def _text(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def _client(get, sleeps=None):
    return YahooClient(get=get, sleep=(sleeps.append if sleeps is not None else (lambda s: None)))


def test_chart_parses_tsla_session():
    bars = _client(lambda url: _text("TSLA-2026-10-19-5m.json")).chart("TSLA", "1d", "5m")
    raw = json.loads(_text("TSLA-2026-10-19-5m.json"))["chart"]["result"][0]
    assert len(raw["timestamp"]) == 17  # the last one is the live tick
    assert len(bars) == 16
    first = bars[0]
    assert first.start == datetime(2026, 10, 19, 9, 30, tzinfo=ET)
    assert first.open == pytest.approx(357.4849853515625)
    assert first.close == pytest.approx(359.17999267578125)
    assert first.volume == 3080684


def test_live_tick_dropped():
    bars = _client(lambda url: _text("TSLA-5m-live-2026-10-20-1001.json")).chart("TSLA", "1d", "5m")
    assert len(bars) == 7
    assert all(b.start.second == 0 and b.start.minute % 5 == 0 for b in bars)


def test_spark_parse_20_symbols():
    got = _client(lambda url: _text("spark-5m-live-2026-10-20-1001.json")).spark_closes(
        ["AMZN"], "1d", "5m"
    )
    assert "AMZN" in got and len(got) == 20
    pairs = got["TSLA"]
    assert all(isinstance(c, float) and t.tzinfo is not None for t, c in pairs)


def test_session_bars_excludes_forming_bar():
    bars = _client(lambda url: _text("TSLA-2026-10-19-5m.json")).chart("TSLA", "1d", "5m")
    day = date(2026, 10, 19)
    out = session_bars(bars, day, datetime(2026, 10, 19, 9, 42, tzinfo=ET))
    assert [b.start.strftime("%H:%M") for b in out] == ["09:30", "09:35"]
    out = session_bars(bars, day, datetime(2026, 10, 19, 9, 45, tzinfo=ET))
    assert len(out) == 3
    assert session_bars(bars, date(2026, 10, 20), datetime(2026, 10, 20, 12, 0, tzinfo=ET)) == []


def test_falls_back_to_query1_after_429():
    urls: list[str] = []
    sleeps: list[float] = []

    def get(url: str) -> str:
        urls.append(url)
        if "query2" in url:
            raise HttpError(429)
        return _text("TSLA-2026-10-19-5m.json")

    bars = _client(get, sleeps).chart("TSLA", "1d", "5m")
    assert len(bars) == 16
    assert [("query2" in u) for u in urls] == [True, True, False]
    assert sleeps == [5]


def test_5xx_goes_straight_to_query1():
    urls: list[str] = []

    def get(url: str) -> str:
        urls.append(url)
        if "query2" in url:
            raise HttpError(503)
        return _text("TSLA-2026-10-19-5m.json")

    _client(get).chart("TSLA", "1d", "5m")
    assert len(urls) == 2 and "query1" in urls[1]


def test_both_hosts_fail_raises():
    def get(url: str) -> str:
        raise HttpError(500)

    with pytest.raises(YahooError):
        _client(get).chart("TSLA", "1d", "5m")


def test_spark_batches_of_20():
    urls: list[str] = []
    sleeps: list[float] = []

    def get(url: str) -> str:
        urls.append(url)
        return '{"spark":{"result":[],"error":null}}'

    syms = [f"S{i}" for i in range(45)]
    assert _client(get, sleeps).spark_closes(syms, "1d", "5m") == {}
    assert len(urls) == 3
    assert sleeps == [0.3, 0.3]
    assert urls[0].count(",") == 19 and urls[2].count(",") == 4


def test_tsx_symbol_kept_as_is():
    urls: list[str] = []

    def get(url: str) -> str:
        urls.append(url)
        return _text("TSLA-2026-10-19-5m.json")

    _client(get).chart("RY.TO", "1d", "5m")
    assert "/RY.TO?" in urls[0]


def test_null_rows_dropped():
    doc = {
        "chart": {
            "result": [
                {
                    "timestamp": [1792416600, 1792416900],
                    "indicators": {
                        "quote": [
                            {
                                "open": [1, None],
                                "high": [2, 2],
                                "low": [1, 1],
                                "close": [1.5, 1.5],
                                "volume": [10, 10],
                            }
                        ]
                    },
                }
            ]
        }
    }
    bars = _client(lambda url: json.dumps(doc)).chart("X", "1d", "5m")
    assert len(bars) == 1
    assert isinstance(bars[0], Bar)


@pytest.mark.parametrize("column", ["close", "volume"])
def test_spark_column_longer_than_its_timestamps_drops_only_that_symbol(column):
    def item(sym, n_close, n_vol):
        quote = {"close": [10.0 + k for k in range(n_close)], "volume": [5] * n_vol}
        return {"symbol": sym, "response": [{"timestamp": [1792416600, 1792416900], "indicators": {"quote": [quote]}}]}

    bad = item("BAD", 3, 2) if column == "close" else item("BAD", 2, 3)
    doc = {"spark": {"result": [item("OK", 2, 2), bad], "error": None}}
    got = _client(lambda url: json.dumps(doc)).spark_series(["OK", "BAD"], "1d", "5m")
    assert set(got) == {"OK"}
    assert [c for _, c in got["OK"].points] == [10.0, 11.0]
