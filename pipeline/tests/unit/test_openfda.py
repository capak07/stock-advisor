import json
from datetime import UTC, date, datetime

import httpx
import pytest

from advisor.collectors.openfda import APPROVALS_URL, RECALLS_URL, DrugEvents, OpenFda, fda_date
from advisor.company_names import CompanyNames

AS_OF = datetime(2026, 10, 19, 15, 30, tzinfo=UTC)
NAMES = CompanyNames({
    "ABBV": "AbbVie Inc. Common Stock",
    "LLY": "Eli Lilly and Company Common Stock",
    "MRK": "Merck & Company, Inc. Common Stock (new)",
    "PFE": "Pfizer, Inc. Common Stock",
    "BAX": "Baxter International Inc. Common Stock",
    "AIG": "American International Group, Inc. New Common Stock",
    "AAPL": "Apple Inc. - Common Stock",
})
NOT_FOUND = {"error": {"code": "NOT_FOUND", "message": "No matches found!"}}


def answer(fixtures_dir, name: str) -> dict:
    """Real openFDA answers from 2026-10-19 (90 days), trimmed to a few records and the fields used."""
    return json.loads((fixtures_dir / "openfda" / name).read_text(encoding="utf-8"))


def openfda(answers: dict[str, object], asked: list[httpx.Request]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(request)
        body = answers[str(request.url.copy_with(query=None))]
        return httpx.Response(404 if body is NOT_FOUND else 200, json=body)

    return httpx.Client(transport=httpx.MockTransport(handler))


def fetch(fixtures_dir, symbols, *, approvals=None, recalls=None, asked=None) -> list[DrugEvents]:
    answers = {
        APPROVALS_URL: approvals if approvals is not None else answer(fixtures_dir, "drugsfda.json"),
        RECALLS_URL: recalls if recalls is not None else answer(fixtures_dir, "enforcement.json"),
    }
    with openfda(answers, asked if asked is not None else []) as client:
        return OpenFda(client, names=NAMES).fetch(symbols, AS_OF)


def test_approvals_and_recalls_are_counted_for_the_runs_stocks(fixtures_dir):
    events = {e.symbol: e for e in fetch(fixtures_dir, ["ABBV", "LLY", "MRK", "PFE", "BAX", "AIG", "AAPL"])}
    assert set(events) == {"ABBV", "LLY", "MRK", "PFE", "BAX"}  # American Regent isn't AIG
    abbvie, lilly, merck, pfizer, baxter = (events[s] for s in ("ABBV", "LLY", "MRK", "PFE", "BAX"))
    assert (abbvie.original_approvals_90d, abbvie.new_molecules_90d) == (1, 1)
    assert abbvie.latest_approval == date(2026, 9, 25)
    assert (lilly.original_approvals_90d, lilly.new_molecules_90d, lilly.new_indications_90d) == (1, 1, 2)
    assert lilly.latest_approval == date(2026, 10, 9)
    assert (merck.original_approvals_90d, merck.new_indications_90d) == (0, 1)  # labeling left out
    assert merck.latest_approval == date(2026, 9, 24)
    # Pfizer's application was approved in 1970 and only relabeled now: no approval counted
    assert (pfizer.original_approvals_90d, pfizer.latest_approval) == (0, None)
    assert (pfizer.recalls_90d, pfizer.class1_recalls_90d, pfizer.latest_recall) == (1, 0, date(2026, 9, 23))
    # Baxter: two Class I events, and one Class II event listed as three products
    assert (baxter.recalls_90d, baxter.class1_recalls_90d) == (3, 2)
    assert baxter.latest_recall == date(2026, 9, 16)
    assert abbvie.data_updated == date(2026, 10, 16)
    assert abbvie.as_of == date(2026, 10, 19)


def test_both_searches_cover_the_last_ninety_days_in_one_page_each(fixtures_dir):
    asked: list[httpx.Request] = []
    fetch(fixtures_dir, ["PFE"], asked=asked)
    searches = [request.url.params["search"] for request in asked]
    assert searches == [
        "submissions.submission_status_date:[20260721 TO 20261019] AND submissions.submission_status:AP"
        " AND (application_number:NDA* application_number:BLA*)",
        "report_date:[20260721 TO 20261019]",
    ]
    assert {request.url.params["limit"] for request in asked} == {"1000"}


def test_a_window_with_nothing_answers_404_and_means_no_events(fixtures_dir):
    assert fetch(fixtures_dir, ["PFE", "BAX"], approvals=NOT_FOUND, recalls=NOT_FOUND) == []


def test_a_bad_request_fails_the_fetch(fixtures_dir):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"code": "BAD_REQUEST", "message": "Invalid parameter"}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client, pytest.raises(httpx.HTTPStatusError):
        OpenFda(client, names=NAMES).fetch(["PFE"], AS_OF)


def test_more_than_a_page_is_read_page_by_page(fixtures_dir):
    page = answer(fixtures_dir, "enforcement.json")
    skips: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url.copy_with(query=None)) == APPROVALS_URL:
            return httpx.Response(404, json=NOT_FOUND)
        skips.append(request.url.params["skip"])
        rows = page["results"] if request.url.params["skip"] == "0" else page["results"][:2]
        meta = {**page["meta"], "results": {"total": len(page["results"]) + 2}}
        return httpx.Response(200, json={"meta": meta, "results": rows})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        OpenFda(client, names=NAMES).fetch(["PFE"], AS_OF)
    assert skips == ["0", str(len(page["results"]))]


def test_fda_dates():
    assert fda_date("20260925") == date(2026, 9, 25)
    assert fda_date("") is None and fda_date(None) is None
