from datetime import UTC, date, datetime

import httpx
import pytest

from advisor.collectors.sec import TICKERS_URL
from advisor.collectors.sec_events import MaterialEvent, SecEvents, filing_url
from fakes import fake_sec, sec_routes

AS_OF = datetime(2026, 10, 14, 12, 15, tzinfo=UTC)


def test_8k_filings_of_the_last_120_days_with_their_items(fixtures_dir):
    events = SecEvents(fake_sec(sec_routes(fixtures_dir))).fetch(["AAPL"], AS_OF)
    assert [(e.form, e.filing_date, e.items) for e in events] == [
        ("8-K/A", date(2026, 9, 1), ["5.02"]),
        ("8-K", date(2026, 7, 30), ["2.02", "9.01"]),
    ]
    earnings = events[1]
    assert earnings.accepted_at == datetime(2026, 7, 30, 20, 30, 28, tzinfo=UTC)  # 16:30 ET
    assert {e.symbol for e in events} == {"AAPL"}


def test_filings_dated_after_as_of_are_left_out(fixtures_dir):
    events = SecEvents(fake_sec(sec_routes(fixtures_dir))).fetch(
        ["AAPL"], datetime(2026, 8, 15, 12, 0, tzinfo=UTC)
    )
    assert [(e.form, e.filing_date) for e in events] == [
        ("8-K", date(2026, 7, 30)), ("8-K", date(2026, 4, 30)), ("8-K", date(2026, 4, 20)),
    ]


def test_a_block_stops_after_the_first_refused_request():
    seen: list[httpx.Request] = []
    sec = fake_sec({TICKERS_URL: 403}, seen=seen)  # SEC's fair-access block answers 403
    with pytest.raises(httpx.HTTPStatusError, match="HTTP 403"):
        SecEvents(sec).fetch(["AAPL", "MSFT", "NVDA"], AS_OF)
    assert len(seen) == 1


def test_two_sec_collectors_in_one_run_share_the_submissions(fixtures_dir):
    seen: list[httpx.Request] = []
    sec = fake_sec(sec_routes(fixtures_dir), seen=seen)
    SecEvents(sec).fetch(["AAPL"], AS_OF)
    SecEvents(sec).fetch(["AAPL"], AS_OF)
    assert sum("submissions" in str(r.url) for r in seen) == 1


def test_an_8k_accepted_after_as_of_is_left_out(fixtures_dir):
    sec = fake_sec(sec_routes(fixtures_dir))
    before = SecEvents(sec).fetch(["AAPL"], datetime(2026, 7, 30, 19, 15, tzinfo=UTC))  # 15:15 ET
    assert date(2026, 7, 30) not in {e.filing_date for e in before}
    after = SecEvents(sec).fetch(["AAPL"], datetime(2026, 7, 30, 21, 0, tzinfo=UTC))
    assert ("8-K", date(2026, 7, 30)) in {(e.form, e.filing_date) for e in after}


def test_events_carry_the_cik_and_document_and_link_to_sec(fixtures_dir):
    events = SecEvents(fake_sec(sec_routes(fixtures_dir))).fetch(["AAPL"], AS_OF)
    earnings = events[1]
    assert (earnings.cik, earnings.primary_document) == (320193, "aapl-20260730.htm")
    assert filing_url(earnings) == (
        "https://www.sec.gov/Archives/edgar/data/320193/000032019326000018/aapl-20260730.htm"
    )


def test_filing_url_is_none_without_a_document_or_cik():
    base = dict(symbol="AAPL", accession="0000320193-26-000018", form="8-K", filing_date=date(2026, 7, 30))
    assert filing_url(MaterialEvent(**base, cik=320193)) is None
    assert filing_url(MaterialEvent(**base, primary_document="a.htm")) is None
