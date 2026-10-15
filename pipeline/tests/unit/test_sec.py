import json
from datetime import UTC, date, datetime

import httpx
import pytest

from advisor.collectors.base import MissingCredential
from advisor.collectors.sec import (
    SUBMISSIONS_URL,
    TICKERS_URL,
    DocumentBudget,
    DocumentBudgetExhausted,
    archive_url,
    parse_filings,
    parse_tickers,
    sec_stop,
    sec_ticker,
    true_acceptance,
)
from fakes import SEC_CONTACT, fake_sec, sec_routes


def aapl_filings(fixtures_dir):
    return parse_filings(json.loads((fixtures_dir / "sec" / "submissions_AAPL_trimmed.json").read_text()))


def test_sec_tickers_use_a_hyphen_for_share_classes():
    assert sec_ticker("BRK.B") == "BRK-B"
    assert sec_ticker("aapl") == "AAPL"


def test_parse_tickers_maps_every_listed_ticker_to_its_cik(fixtures_dir):
    ciks = parse_tickers(json.loads((fixtures_dir / "sec" / "company_tickers.json").read_text()))
    assert len(ciks) == 19
    assert ciks["AAPL"] == 320193
    assert ciks["BRK-B"] == ciks["BRK-A"] == 1067983
    assert ciks["GOOG"] == ciks["GOOGL"] == 1652044


def test_true_acceptance_undoes_secs_double_eastern_shift():
    assert true_acceptance("2026-10-09T02:30:32.000Z") == datetime(2026, 10, 8, 22, 30, 32, tzinfo=UTC)
    assert true_acceptance("2026-01-30T02:30:33.000Z") == datetime(2026, 1, 29, 21, 30, 33, tzinfo=UTC)
    assert true_acceptance("") is None


def test_parse_filings_turns_secs_parallel_arrays_into_filings(fixtures_dir):
    filings = aapl_filings(fixtures_dir)
    assert len(filings) == 30
    first = filings[0]
    assert (first.accession, first.form, first.filing_date) == (
        "0001140361-26-039158", "4", date(2026, 10, 8),
    )
    assert first.accepted_at == datetime(2026, 10, 8, 22, 30, 32, tzinfo=UTC)
    assert first.report_date == date(2026, 10, 6)
    assert (first.items, first.primary_document) == ((), "xslF345X06/form4.xml")
    earnings = next(f for f in filings if f.form == "8-K")
    assert earnings.items == ("2.02", "9.01")
    assert earnings.file_number == "001-36743"


def test_requests_carry_the_contact_user_agent(fixtures_dir):
    seen: list[httpx.Request] = []
    fake_sec(sec_routes(fixtures_dir), seen=seen).cik_for("AAPL")
    assert [r.headers["User-Agent"] for r in seen] == [SEC_CONTACT]


@pytest.mark.parametrize("user_agent", [None, "", "stock-advisor"])
def test_a_missing_or_emailless_contact_fails_before_any_request(user_agent):
    seen: list[httpx.Request] = []
    with pytest.raises(MissingCredential, match="SEC_USER_AGENT must name you and give a contact email"):
        fake_sec({}, seen=seen, user_agent=user_agent).cik_for("AAPL")
    assert seen == []


def test_the_ticker_map_and_each_companys_filings_are_fetched_once(fixtures_dir):
    seen: list[httpx.Request] = []
    sec = fake_sec(sec_routes(fixtures_dir), seen=seen)
    assert [sec.cik_for(s) for s in ("AAPL", "BRK.B", "NOPE")] == [320193, 1067983, None]
    assert len(sec.filings(320193)) == 30
    assert sec.filings(320193) is sec.filings(320193)
    assert [str(r.url) for r in seen] == [TICKERS_URL, SUBMISSIONS_URL.format(cik=320193)]


def test_documents_are_fetched_once_and_kept_on_disk(fixtures_dir, tmp_path):
    filing = aapl_filings(fixtures_dir)[0]
    first_seen: list[httpx.Request] = []
    first = fake_sec(sec_routes(fixtures_dir), documents=tmp_path, seen=first_seen)
    assert not first.has_document(filing)
    body = first.document(320193, filing)
    assert body.startswith(b"<?xml")
    assert first.has_document(filing)
    assert str(first_seen[0].url) == archive_url(320193, "0001140361-26-039158", "form4.xml")
    second_seen: list[httpx.Request] = []
    second = fake_sec(sec_routes(fixtures_dir), documents=tmp_path, seen=second_seen)
    assert second.document(320193, filing) == body
    assert second_seen == []


def test_a_document_budget_counts_only_downloads(fixtures_dir, tmp_path):
    filings = [f for f in aapl_filings(fixtures_dir) if f.form == "4"]
    sec = fake_sec(sec_routes(fixtures_dir), documents=tmp_path)
    sec.document(320193, filings[0])  # already on disk: free
    budget = DocumentBudget(sec, 1, "Form 4")
    budget.fetch(320193, filings[0])
    budget.fetch(320193, filings[1])
    with pytest.raises(DocumentBudgetExhausted, match="fetched 1 Form 4 documents this run"):
        budget.fetch(320193, filings[2])


def test_sec_stop_recognises_a_missing_contact_a_block_and_a_spent_budget():
    request = httpx.Request("GET", "https://www.sec.gov/x")
    assert sec_stop(MissingCredential("x"))
    assert sec_stop(DocumentBudgetExhausted("x"))
    assert sec_stop(httpx.HTTPStatusError("x", request=request, response=httpx.Response(403)))
    assert not sec_stop(httpx.HTTPStatusError("x", request=request, response=httpx.Response(404)))
    assert not sec_stop(ValueError("x"))
