from datetime import UTC, date, datetime

import httpx
import pytest

from advisor.collectors.base import PartialFetch
from advisor.collectors.sec import DocumentBudgetExhausted, Filing, archive_url
from advisor.collectors.sec_insiders import SecInsiders, parse_form4
from fakes import fake_sec, sec_routes

AS_OF = datetime(2026, 10, 14, 12, 15, tzinfo=UTC)
FILING = Filing(
    accession="0001140361-26-039158", form="4", filing_date=date(2026, 10, 8), accepted_at=None,
    report_date=None, items=(), file_number="", primary_document="xslF345X06/form4.xml",
)


def document(fixtures_dir, name: str) -> bytes:
    return (fixtures_dir / "sec" / name).read_bytes()


def test_an_officer_sale_under_a_trading_plan(fixtures_dir):
    [trade] = parse_form4("AAPL", FILING, document(fixtures_dir, "form4_sample.xml"), 320193)
    assert (trade.code, trade.acquired, trade.shares, trade.price) == ("S", False, 2399.0, 332.01)
    assert (trade.owned_after, trade.direct, trade.derivative, trade.planned) == (39593.0, True, False, True)
    assert trade.owners == ["Newstead Jennifer"]
    assert (trade.officer, trade.director, trade.officer_title) == (True, False, "SVP, GC and Government Affairs")
    assert (trade.trade_date, trade.filing_date, trade.accession) == (
        date(2026, 10, 6), date(2026, 10, 8), "0001140361-26-039158",
    )


def test_a_director_open_market_buy_with_one_zero_flags(fixtures_dir):
    [trade] = parse_form4("BA", FILING, document(fixtures_dir, "form4_sample_director_open_market_buy_P.xml"), 12927)
    assert (trade.code, trade.acquired, trade.shares, trade.price) == ("P", True, 1370.0, 218.5)
    assert (trade.director, trade.officer, trade.planned) == (True, False, False)


def test_derivative_rows_are_kept_and_marked(fixtures_dir):
    trades = parse_form4("AAPL", FILING, document(fixtures_dir, "form4_sample_multi_MFSG_derivative.xml"), 320193)
    assert [t.code for t in trades] == ["M", "F", "S", "S", "S", "S", "G", "M"]
    assert [t.derivative for t in trades] == [False] * 7 + [True]
    assert trades[0].price is None  # an exercise has no price, only a footnote
    grants = parse_form4("AAPL", FILING, document(fixtures_dir, "form4_sample_rsu_grant_A_derivative.xml"), 320193)
    assert [(t.code, t.derivative, t.price) for t in grants] == [("A", True, 0.0), ("A", True, 0.0)]


def test_a_document_about_another_issuer_is_ignored(fixtures_dir):
    boeing = document(fixtures_dir, "form4_sample_director_open_market_buy_P.xml")
    assert parse_form4("AAPL", FILING, boeing, 320193) == []


def test_fetch_reads_the_last_90_days_of_form_4s(fixtures_dir):
    seen: list[httpx.Request] = []
    trades = SecInsiders(fake_sec(sec_routes(fixtures_dir), seen=seen)).fetch(["AAPL"], AS_OF)
    assert len(trades) == 11  # 1 + 8 + 2; the two Boeing documents are ignored
    assert sorted({t.code for t in trades}) == ["A", "F", "G", "M", "S"]
    assert sum("Archives" in str(r.url) for r in seen) == 5


def test_filings_dated_after_as_of_are_left_out(fixtures_dir):
    trades = SecInsiders(fake_sec(sec_routes(fixtures_dir))).fetch(
        ["AAPL"], datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
    )
    assert len(trades) == 10  # the 2026-10-08 sale isn't filed yet
    assert "0001140361-26-039158" not in {t.accession for t in trades}


def test_documents_on_disk_cost_nothing_on_later_runs(fixtures_dir, tmp_path):
    SecInsiders(fake_sec(sec_routes(fixtures_dir), documents=tmp_path)).fetch(["AAPL"], AS_OF)
    seen: list[httpx.Request] = []
    again = SecInsiders(fake_sec(sec_routes(fixtures_dir), documents=tmp_path, seen=seen), max_documents=0)
    assert len(again.fetch(["AAPL"], AS_OF)) == 11
    assert not any("Archives" in str(r.url) for r in seen)


def test_the_document_budget_stops_the_run(fixtures_dir):
    with pytest.raises(DocumentBudgetExhausted, match="fetched 2 Form 4 documents this run"):
        SecInsiders(fake_sec(sec_routes(fixtures_dir)), max_documents=2).fetch(["AAPL"], AS_OF)


def test_a_malformed_document_skips_only_that_filing(fixtures_dir):
    routes = sec_routes(fixtures_dir)
    routes[archive_url(320193, "0001140361-26-038674", "form4.xml")] = b"<ownershipDocument><unclosed"
    trades = SecInsiders(fake_sec(routes)).fetch(["AAPL"], AS_OF)
    assert len(trades) == 3  # the CEO's 8 trades are skipped; the other 3 are kept
    assert "0001140361-26-038674" not in {t.accession for t in trades}


def test_a_symbol_cut_off_by_the_budget_is_left_out_whole(fixtures_dir):
    with pytest.raises(PartialFetch, match="fetched 5 Form 4 documents this run") as caught:
        SecInsiders(fake_sec(sec_routes(fixtures_dir)), max_documents=5).fetch(["AAPL", "PFE"], AS_OF)
    assert len(caught.value.records) == 11  # AAPL only; PFE contributes nothing
    assert {t.symbol for t in caught.value.records} == {"AAPL"}
