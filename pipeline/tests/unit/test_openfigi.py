import json
from datetime import UTC, datetime

import httpx
import pytest

from advisor.collectors.openfigi import FigiBook, openfigi_ticker, parse_mapping

NOW = datetime(2026, 10, 19, 14, tzinfo=UTC)


def figi(n: int) -> str:
    return f"BBG{n:09d}"


def known(ticker: str) -> dict:
    """OpenFIGI's answer for a ticker it knows, with made-up FIGIs derived from the ticker."""
    n = sum(ord(ch) for ch in ticker)
    return {"data": [{
        "ticker": ticker, "figi": figi(n), "compositeFIGI": figi(n), "shareClassFIGI": figi(n + 1),
        "securityType": "Common Stock", "marketSector": "Equity",
    }]}


def openfigi(asked, *, unknown=(), fail=False):
    """A MockTransport playing OpenFIGI: it records each request's tickers."""

    def handler(request):
        jobs = json.loads(request.read())
        asked.append([job["idValue"] for job in jobs])
        if fail:
            return httpx.Response(400, text="bad request")
        return httpx.Response(200, json=[
            {"warning": "No identifier found."} if job["idValue"] in unknown else known(job["idValue"])
            for job in jobs
        ])

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_tickers_use_openfigis_class_form():
    assert [openfigi_ticker(s) for s in ("AAPL", "BRK.B", "BF.B")] == ["AAPL", "BRK/B", "BF/B"]


def test_a_mapping_gives_each_jobs_figis_once_and_none_for_unknown_tickers():
    payload = [known("AAPL"), {"warning": "No identifier found."}]
    n = sum(ord(ch) for ch in "AAPL")
    assert parse_mapping(payload, 2) == [[figi(n), figi(n + 1)], []]
    with pytest.raises(ValueError, match="for 3 jobs"):
        parse_mapping(payload, 3)
    with pytest.raises(ValueError, match="Invalid idType"):
        parse_mapping([{"error": "Invalid idType."}], 1)


def test_tickers_are_asked_for_ten_at_a_time_and_then_kept(tmp_path):
    asked = []
    symbols = [f"T{i:02d}" for i in range(23)] + ["BRK.B"]
    with openfigi(asked) as client:
        book = FigiBook(client, tmp_path / "figis.json")
        first = book.lookup(symbols, NOW)
        again = book.lookup(symbols, NOW)
    assert [len(batch) for batch in asked] == [10, 10, 4]  # nothing asked the second time
    assert "BRK/B" in asked[-1]
    assert first.figis == again.figis and len(first.figis) == 24 and first.failed == []


def test_known_tickers_are_asked_again_after_half_a_year_and_unknown_ones_after_a_month(tmp_path):
    asked = []
    with openfigi(asked, unknown={"GONE"}) as client:
        book = FigiBook(client, tmp_path / "figis.json")
        assert book.lookup(["AAPL", "GONE"], NOW).figis["GONE"] == []
        book.lookup(["AAPL", "GONE"], NOW.replace(month=11, day=17))  # 29 days later
        book.lookup(["AAPL", "GONE"], NOW.replace(month=11, day=18))  # 30 days later
        book.lookup(["AAPL", "GONE"], datetime(2027, 4, 17, 14, tzinfo=UTC))  # 180 days later
    assert asked == [["AAPL", "GONE"], ["GONE"], ["AAPL", "GONE"]]


def test_an_openfigi_failure_names_the_symbols_it_left_unknown_and_keeps_older_entries(tmp_path):
    with openfigi([]) as client:
        FigiBook(client, tmp_path / "figis.json").lookup(["AAPL"], NOW)
    asked = []
    with openfigi(asked, fail=True) as client:
        later = FigiBook(client, tmp_path / "figis.json").lookup(["AAPL", "MSFT"], datetime(2027, 6, 1, tzinfo=UTC))
    assert asked == [["AAPL", "MSFT"]]  # AAPL was due again, and both failed
    assert list(later.figis) == ["AAPL"]  # its older FIGIs still serve
    assert later.failed == ["MSFT"]
    assert later.error.startswith("HTTPStatusError: HTTP 400")
