"""Drug approvals and recalls per stock from openFDA (source 48).

openFDA can't be asked about a company; its records name sponsors and recalling firms in free
text. So each fetch makes two market-wide requests over the last WINDOW_DAYS:
- NDA and BLA applications with an approval in the window;
- drug recalls reported in the window.

The names are then matched to the run's stocks (`advisor.sponsors`). openFDA refreshes both
data sets about weekly.

Approvals counted for a stock:
- an original approval (a new drug, formulation or biologic);
- a new molecular entity (an original "TYPE 1" NDA, or an original BLA);
- a new indication (an "EFFICACY" supplement).
Labeling and manufacturing supplements are left out.

openFDA matches array fields independently. An application approved years ago with a recent
supplement matches the query, so every submission is checked here again.

A recall is one event (`event_id`) however many products it lists. An empty window answers HTTP
404 with error code NOT_FOUND.

The data is public domain (CC0). Without a key, openFDA allows 1,000 requests a day per IP.
"""

from collections import defaultdict
from collections.abc import Iterator, Mapping, Sequence
from datetime import date, datetime, timedelta
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict

from advisor.collectors.base import (
    Cadence,
    Category,
    RateLimiter,
    Scope,
    check_deadline,
    get_with_retries,
)
from advisor.company_names import CompanyNames
from advisor.models import ET, AssetType, Market
from advisor.sponsors import SponsorMatcher

APPROVALS_URL = "https://api.fda.gov/drug/drugsfda.json"
RECALLS_URL = "https://api.fda.gov/drug/enforcement.json"
WINDOW_DAYS = 90
PAGE = 1000  # openFDA's largest page
OPENFDA_PER_MINUTE = 60


class DrugEvents(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    as_of: date  # ET date of the run
    original_approvals_90d: int = 0
    new_molecules_90d: int = 0
    new_indications_90d: int = 0
    latest_approval: date | None = None
    recalls_90d: int = 0  # distinct recall events
    class1_recalls_90d: int = 0  # the most serious class
    latest_recall: date | None = None
    data_updated: date | None = None  # openFDA's last refresh of the approvals data


def fda_date(text: str | None) -> date | None:
    """openFDA's YYYYMMDD dates."""
    try:
        return datetime.strptime(text or "", "%Y%m%d").date()
    except ValueError:
        return None


def _results(client: httpx.Client, url: str, search: str, limiter: RateLimiter | None) -> tuple[list[dict], dict]:
    """Every result of a search, page by page, and the first page's `meta`; none when nothing matches."""
    results: list[dict] = []
    meta: dict = {}
    skip = 0
    while True:
        check_deadline()
        try:
            response = get_with_retries(
                client, url, params={"search": search, "limit": PAGE, "skip": skip}, limiter=limiter
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404 and "NOT_FOUND" in exc.response.text:
                return results, meta
            raise
        payload = response.json()
        meta = meta or payload.get("meta") or {}
        page = payload.get("results") or []
        results.extend(page)
        skip += len(page)
        total = ((payload.get("meta") or {}).get("results") or {}).get("total", 0)
        if not page or skip >= total:
            return results, meta


def window(as_of: datetime) -> tuple[date, date]:
    today = as_of.astimezone(ET).date()
    return today - timedelta(days=WINDOW_DAYS), today


def approvals(applications: Sequence[Mapping[str, Any]], start: date, end: date) -> Iterator[tuple[str, str, date]]:
    """(sponsor, kind, date) for each counted approval in the window; kind is "original",
    "new_molecule" (also original) or "new_indication"."""
    for application in applications:
        sponsor = application.get("sponsor_name") or ""
        biologic = str(application.get("application_number", "")).startswith("BLA")
        for submission in application.get("submissions") or []:
            day = fda_date(submission.get("submission_status_date"))
            if submission.get("submission_status") != "AP" or day is None or not start <= day <= end:
                continue
            kind = submission.get("submission_type")
            category = submission.get("submission_class_code")
            if kind == "ORIG":
                yield sponsor, "original", day
                if biologic or category == "TYPE 1":
                    yield sponsor, "new_molecule", day
            elif kind == "SUPPL" and category == "EFFICACY":
                yield sponsor, "new_indication", day


def drug_events(
    matcher: SponsorMatcher,
    applications: Sequence[Mapping[str, Any]],
    recalls: Sequence[Mapping[str, Any]],
    as_of: datetime,
    data_updated: date | None,
) -> list[DrugEvents]:
    start, end = window(as_of)
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    latest_approval: dict[str, date] = {}
    for sponsor, kind, day in approvals(applications, start, end):
        for symbol in matcher.symbols_for(sponsor):
            counts[symbol][kind] += 1
            latest_approval[symbol] = max(day, latest_approval.get(symbol, day))
    events: dict[str, set[str]] = defaultdict(set)
    serious: dict[str, set[str]] = defaultdict(set)
    latest_recall: dict[str, date] = {}
    for recall in recalls:
        day = fda_date(recall.get("report_date"))
        if day is None or not start <= day <= end:
            continue
        for symbol in matcher.symbols_for(recall.get("recalling_firm") or ""):
            event = str(recall.get("event_id") or recall.get("recall_number"))
            events[symbol].add(event)
            if recall.get("classification") == "Class I":
                serious[symbol].add(event)
            latest_recall[symbol] = max(day, latest_recall.get(symbol, day))
    return [
        DrugEvents(
            symbol=symbol,
            as_of=end,
            original_approvals_90d=counts[symbol]["original"],
            new_molecules_90d=counts[symbol]["new_molecule"],
            new_indications_90d=counts[symbol]["new_indication"],
            latest_approval=latest_approval.get(symbol),
            recalls_90d=len(events[symbol]),
            class1_recalls_90d=len(serious[symbol]),
            latest_recall=latest_recall.get(symbol),
            data_updated=data_updated,
        )
        for symbol in sorted(set(latest_approval) | set(latest_recall))
    ]


class OpenFda:
    name = "openfda"
    category = Category.CATALYSTS
    core = False
    best_effort = False
    cadence = Cadence.DAILY
    asset_types = frozenset({AssetType.STOCK})
    markets = frozenset({Market.US})
    record_type = DrugEvents
    freshness = timedelta(days=10)
    scope = Scope.SYMBOLS
    canary = ("PFE",)
    canary_requires_records = False  # the health check loads no names, so nothing matches
    max_symbols = None

    def __init__(
        self,
        client: httpx.Client,
        limiter: RateLimiter | None = None,
        *,
        names: CompanyNames | None = None,
    ) -> None:
        self._client = client
        self._limiter = limiter
        self._names = names or CompanyNames()

    def fetch(self, symbols: Sequence[str], as_of: datetime) -> list[DrugEvents]:
        start, end = window(as_of)
        span = f"[{start:%Y%m%d} TO {end:%Y%m%d}]"
        applications, meta = _results(
            self._client,
            APPROVALS_URL,
            f"submissions.submission_status_date:{span} AND submissions.submission_status:AP"
            " AND (application_number:NDA* application_number:BLA*)",
            self._limiter,
        )
        recalls, _ = _results(self._client, RECALLS_URL, f"report_date:{span}", self._limiter)
        known = {symbol: name for symbol in symbols if (name := self._names.get(symbol))}
        updated = meta.get("last_updated")
        return drug_events(
            SponsorMatcher(known),
            applications,
            recalls,
            as_of,
            date.fromisoformat(updated) if updated else None,
        )
