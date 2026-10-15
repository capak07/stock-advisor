from datetime import UTC, date, datetime

import httpx
import pytest

from advisor.collectors.sec import DocumentBudgetExhausted, Filing, archive_url
from advisor.collectors.sec_holders import SecHolders, parse_schedule
from fakes import fake_sec, sec_routes

AS_OF = datetime(2026, 10, 14, 12, 15, tzinfo=UTC)


def filing(form: str) -> Filing:
    return Filing(
        accession="0000102909-26-000630", form=form, filing_date=date(2026, 3, 26), accepted_at=None,
        report_date=None, items=(), file_number="005-33632", primary_document="primary_doc.xml",
    )


def document(fixtures_dir, name: str) -> bytes:
    return (fixtures_dir / "sec" / name).read_bytes()


def test_a_passive_13g_amendment(fixtures_dir):
    holding = parse_schedule(
        "AAPL", filing("SCHEDULE 13G/A"), document(fixtures_dir, "schedule13g_A_sample_primary_doc.xml"), 320193
    )
    assert (holding.activist, holding.amendment, holding.event_date) == (False, True, date(2026, 3, 13))
    assert [(p.name, p.shares, p.percent) for p in holding.reporting_persons] == [
        ("The Vanguard Group", 0.0, 0.0),  # a realignment: the successor entity reports separately
    ]


def test_an_activist_13d_amendment(fixtures_dir):
    holding = parse_schedule(
        "ALLO", filing("SCHEDULE 13D/A"), document(fixtures_dir, "schedule13d_A_sample_primary_doc.xml"), 1737287
    )
    assert (holding.activist, holding.amendment, holding.event_date) == (True, True, date(2025, 11, 6))
    assert [(p.name, p.shares, p.percent) for p in holding.reporting_persons] == [
        ("Pfizer Inc.", 22032040.0, 9.0),
    ]


def test_a_document_about_another_issuer_is_ignored(fixtures_dir):
    vanguard_on_apple = document(fixtures_dir, "schedule13g_A_sample_primary_doc.xml")
    assert parse_schedule("PFE", filing("SCHEDULE 13G/A"), vanguard_on_apple, 78003) is None


def test_only_filings_about_the_company_are_read(fixtures_dir):
    seen: list[httpx.Request] = []
    holdings = SecHolders(fake_sec(sec_routes(fixtures_dir), seen=seen)).fetch(["AAPL", "PFE"], AS_OF)
    assert [(h.symbol, h.accession, h.form) for h in holdings] == [
        ("AAPL", "0002100119-26-000139", "SCHEDULE 13G"),
        ("AAPL", "0000102909-26-000630", "SCHEDULE 13G/A"),
    ]  # PFE's two subject documents name Apple as issuer, so they're dropped
    assert all(h.accepted_at is not None for h in holdings)
    documents = [str(r.url) for r in seen if "Archives" in str(r.url)]
    assert len(documents) == 4
    assert not any("/0000078003" in url for url in documents)  # Pfizer's own 13D/Gs on others


def test_legacy_filings_are_kept_as_metadata_only(fixtures_dir):
    seen: list[httpx.Request] = []
    holdings = SecHolders(fake_sec(sec_routes(fixtures_dir), seen=seen)).fetch(
        ["AAPL"], datetime(2024, 6, 1, 12, 0, tzinfo=UTC)
    )
    assert [(h.accession, h.form, h.reporting_persons) for h in holdings] == [
        ("0001193125-24-036431", "SC 13G/A", []),
        ("0001104659-24-020009", "SC 13G/A", []),
    ]
    assert not any("Archives" in str(r.url) for r in seen)


def test_the_document_budget_stops_the_run(fixtures_dir):
    with pytest.raises(DocumentBudgetExhausted, match="fetched 1 Schedule 13D/G documents this run"):
        SecHolders(fake_sec(sec_routes(fixtures_dir)), max_documents=1).fetch(["AAPL"], AS_OF)


def test_a_malformed_document_skips_only_that_filing(fixtures_dir):
    routes = sec_routes(fixtures_dir)
    routes[archive_url(320193, "0000102909-26-000630", "primary_doc.xml")] = b"<schedule><unclosed"
    holdings = SecHolders(fake_sec(routes)).fetch(["AAPL"], AS_OF)
    assert [h.accession for h in holdings] == ["0002100119-26-000139"]
