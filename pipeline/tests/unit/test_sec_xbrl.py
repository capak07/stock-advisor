import json
from datetime import UTC, date, datetime

import httpx
import pytest

from advisor.collectors.base import MissingCredential
from advisor.collectors.sec_xbrl import SecXbrl, extract_facts
from advisor.models import Market
from fakes import fake_sec, sec_routes

AS_OF = datetime(2026, 10, 14, 12, 15, tzinfo=UTC)
TODAY = date(2026, 10, 14)


def companyfacts(fixtures_dir, name: str) -> dict:
    return json.loads((fixtures_dir / "sec" / f"companyfacts_{name}_trimmed.json").read_text())


def test_extract_keeps_10k_and_10q_facts_of_the_last_three_years(fixtures_dir):
    facts = extract_facts("AAPL", companyfacts(fixtures_dir, "AAPL"), TODAY)
    assert len(facts) == 148
    assert {f.metric for f in facts} == {
        "revenue", "gross_profit", "operating_income", "net_income", "eps_diluted",
        "operating_cash_flow", "capex", "long_term_debt", "long_term_debt_noncurrent",
        "commercial_paper", "equity", "diluted_shares", "shares_outstanding",
    }
    assert {f.form for f in facts} <= {"10-K", "10-K/A", "10-Q", "10-Q/A", "10-KT"}
    [quarter] = [
        f for f in facts
        if f.metric == "revenue" and (f.start, f.end) == (date(2026, 3, 29), date(2026, 6, 27))
    ]
    assert quarter.concept == "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
    assert (quarter.value, quarter.filed, quarter.form) == (109417000000.0, date(2026, 7, 31), "10-Q")
    latest_shares = max((f for f in facts if f.metric == "shares_outstanding"), key=lambda f: f.end)
    assert latest_shares.concept == "dei:EntityCommonStockSharesOutstanding"
    assert (latest_shares.start, latest_shares.end, latest_shares.value) == (
        None, date(2026, 7, 17), 14594180000.0,
    )


def test_facts_filed_after_as_of_are_left_out(fixtures_dir):
    facts = extract_facts("AAPL", companyfacts(fixtures_dir, "AAPL"), date(2026, 7, 30))
    assert len(facts) == 108
    assert max(f.filed for f in facts) == date(2026, 5, 1)


def test_fallback_concepts_cover_banks_and_multi_class_issuers(fixtures_dir):
    jpm = {(f.metric, f.concept) for f in extract_facts("JPM", companyfacts(fixtures_dir, "JPM"), TODAY)}
    assert ("revenue", "us-gaap:RevenuesNetOfInterestExpense") in jpm
    googl = extract_facts("GOOGL", companyfacts(fixtures_dir, "GOOGL"), TODAY)
    assert {f.concept for f in googl if f.metric == "shares_outstanding"} == {
        "us-gaap:CommonStockSharesOutstanding"
    }
    brk = extract_facts("BRK.B", companyfacts(fixtures_dir, "BRK_B"), TODAY)
    assert "eps_diluted" not in {f.metric for f in brk}


def test_share_classes_share_one_download(fixtures_dir):
    seen: list[httpx.Request] = []
    facts = SecXbrl(fake_sec(sec_routes(fixtures_dir), seen=seen)).fetch(["GOOG", "GOOGL", "AAPL"], AS_OF)
    assert sum("companyfacts" in str(r.url) for r in seen) == 2
    counts = {symbol: sum(f.symbol == symbol for f in facts) for symbol in ("GOOG", "GOOGL", "AAPL")}
    assert counts == {"GOOG": 15, "GOOGL": 15, "AAPL": 148}


def test_symbols_without_a_cik_or_any_xbrl_yield_no_facts(fixtures_dir):
    # NOPE has no CIK; BRK.B's company facts answer 404 in the fake.
    assert SecXbrl(fake_sec(sec_routes(fixtures_dir))).fetch(["NOPE", "BRK.B"], AS_OF) == []


def test_xbrl_is_the_core_us_fundamentals_source():
    assert SecXbrl.core is True
    assert SecXbrl.markets == frozenset({Market.US})


def test_a_missing_contact_fails_the_source():
    with pytest.raises(MissingCredential):
        SecXbrl(fake_sec({}, user_agent=None)).fetch(["AAPL"], AS_OF)
