import json
from datetime import UTC, date, datetime

import httpx

from advisor.collectors.clinical_trials import (
    ClinicalTrials,
    StatusBook,
    Trial,
    trial_date,
)
from advisor.company_names import CompanyNames

AS_OF = datetime(2026, 10, 19, 15, 30, tzinfo=UTC)
NAMES = CompanyNames({
    "PFE": "Pfizer, Inc. Common Stock",
    "LLY": "Eli Lilly and Company Common Stock",
    "MRNA": "Moderna, Inc. - Common Stock",
    "NVS": "Novartis AG Common Stock",
    "AAPL": "Apple Inc. - Common Stock",
})


def answers(fixtures_dir) -> dict[str, dict]:
    """Real answers of 2026-10-19 to the three queries, trimmed to a few trials each."""
    base = fixtures_dir / "clinical_trials"
    return {name: json.loads((base / f"{name}.json").read_text(encoding="utf-8"))
            for name in ("results", "stopped", "completing")}


def which(request: httpx.Request) -> str:
    advanced = request.url.params["filter.advanced"]
    if "ResultsFirstPostDate" in advanced:
        return "results"
    return "stopped" if "LastUpdatePostDate" in advanced else "completing"


def clinicaltrials(pages: dict[str, dict], asked: list[httpx.Request]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(request)
        return httpx.Response(200, json=pages[which(request)])

    return httpx.Client(transport=httpx.MockTransport(handler))


def fetch(fixtures_dir, tmp_path, symbols, asked=None, pages=None):
    with clinicaltrials(pages or answers(fixtures_dir), asked if asked is not None else []) as client:
        collector = ClinicalTrials(client, StatusBook(tmp_path / "statuses.json"), names=NAMES)
        return {a.symbol: a for a in collector.fetch(symbols, AS_OF)}


def test_trial_dates_may_give_only_the_month():
    assert trial_date("2026-10-21") == (date(2026, 10, 21), True)
    assert trial_date("2026-11") == (date(2026, 11, 30), False)
    assert trial_date(None) == (None, True)
    assert trial_date("soon") == (None, True)


def test_activity_from_real_answers(fixtures_dir, tmp_path):
    activity = fetch(fixtures_dir, tmp_path, ["PFE", "LLY", "MRNA", "NVS", "AAPL"])
    assert set(activity) == {"PFE", "LLY", "MRNA"}
    pfizer, lilly, moderna = activity["PFE"], activity["LLY"], activity["MRNA"]
    assert (pfizer.results_posted_30d, pfizer.completions_90d, pfizer.phase3_completions_90d) == (2, 4, 3)
    assert (pfizer.next_completion, pfizer.next_completion_exact) == (date(2026, 10, 30), True)
    assert lilly.results_posted_30d == 3  # one by DICE, "a wholly owned subsidiary of Eli Lilly"
    assert (lilly.next_completion, lilly.next_completion_exact) == (date(2026, 11, 30), False)
    assert moderna.results_posted_30d == 1  # the sponsor is "ModernaTX, Inc."
    # Pfizer's and Novartis's stopped trials were never seen active: not counted as stops
    assert pfizer.stopped_10d == 0
    assert pfizer.as_of == date(2026, 10, 19)


def test_a_stop_counts_when_the_book_saw_the_trial_active(fixtures_dir, tmp_path):
    (tmp_path / "statuses.json").write_text(json.dumps({
        "NCT05070845": {"status": "ACTIVE_NOT_RECRUITING", "seen": "2026-10-12", "stopped": None},
    }))
    assert fetch(fixtures_dir, tmp_path, ["PFE"])["PFE"].stopped_10d == 1
    # The health check may find it first: the stop keeps the day it was found
    assert fetch(fixtures_dir, tmp_path, ["PFE"])["PFE"].stopped_10d == 1
    book = json.loads((tmp_path / "statuses.json").read_text())
    assert book["NCT05070845"] == {"status": "TERMINATED", "seen": "2026-10-19", "stopped": "2026-10-19"}


def test_stops_found_more_than_ten_days_ago_no_longer_count(tmp_path):
    book = StatusBook(tmp_path / "statuses.json")
    active = Trial("NCT1", "Pfizer", "RECRUITING", ("PHASE3",), date(2026, 11, 1), True)
    stopped = Trial("NCT1", "Pfizer", "TERMINATED", ("PHASE3",), date(2026, 11, 1), True)
    book.update([active], date(2026, 9, 1))
    assert book.update([stopped], date(2026, 9, 2)) == {"NCT1": date(2026, 9, 2)}
    assert book.update([stopped], date(2026, 9, 20)) == {"NCT1": date(2026, 9, 2)}


def test_a_damaged_book_starts_over(fixtures_dir, tmp_path):
    (tmp_path / "statuses.json").write_text("cut short {")
    assert fetch(fixtures_dir, tmp_path, ["PFE"])["PFE"].stopped_10d == 0
    assert "NCT05070845" in json.loads((tmp_path / "statuses.json").read_text())


def test_three_market_wide_queries_of_industry_trials(fixtures_dir, tmp_path):
    asked: list[httpx.Request] = []
    fetch(fixtures_dir, tmp_path, ["PFE"], asked)
    queries = [(r.url.params["filter.advanced"], r.url.params.get("filter.overallStatus")) for r in asked]
    assert queries == [
        ("AREA[LeadSponsorClass]INDUSTRY AND AREA[ResultsFirstPostDate]RANGE[2026-09-19,MAX]", None),
        ("AREA[LeadSponsorClass]INDUSTRY AND AREA[LastUpdatePostDate]RANGE[2026-10-09,MAX]",
         "TERMINATED|SUSPENDED|WITHDRAWN"),
        ("AREA[LeadSponsorClass]INDUSTRY AND AREA[PrimaryCompletionDate]RANGE[2026-10-19,2027-01-17]"
         " AND AREA[Phase](PHASE2 OR PHASE3)",
         "RECRUITING|ACTIVE_NOT_RECRUITING|ENROLLING_BY_INVITATION|NOT_YET_RECRUITING"),
    ]
    assert {r.url.params["pageSize"] for r in asked} == {"1000"}


def test_later_pages_follow_the_page_token(fixtures_dir, tmp_path):
    real = answers(fixtures_dir)
    asked: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(request)
        name = which(request)
        if name == "results" and "pageToken" not in request.url.params:
            return httpx.Response(200, json={"studies": real["results"]["studies"][:3], "nextPageToken": "abc"})
        if name == "results":
            return httpx.Response(200, json={"studies": real["results"]["studies"][3:]})
        return httpx.Response(200, json=real[name])

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        collector = ClinicalTrials(client, StatusBook(tmp_path / "statuses.json"), names=NAMES)
        activity = {a.symbol: a for a in collector.fetch(["PFE", "LLY"], AS_OF)}
    assert [r.url.params.get("pageToken") for r in asked[:2]] == [None, "abc"]
    assert activity["LLY"].results_posted_30d == 3
