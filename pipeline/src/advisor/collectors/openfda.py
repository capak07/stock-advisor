"""Drug approvals and recalls per stock from openFDA (source 48).

openFDA can't be asked about a company; its records name sponsors and recalling firms in free
text. So each fetch makes two market-wide requests over the last WINDOW_DAYS:
- NDA and BLA applications with an approval in the window;
- drug recalls reported in the window.

WINDOW_DAYS is the model's longest window plus its lag (`model.catalysts` counts approvals dated up
to APPROVAL_WINDOW_DAYS + FDA_LAG_DAYS days back; Ruling R3, F4). The names are matched with
`advisor.sponsors` against every US name in the directory, as the training history matches them, so a
name two companies share matches neither in both; records are kept for the requested stocks only.
openFDA refreshes both data sets about weekly.

Approvals counted for a stock:
- an original approval (a new drug, formulation or biologic);
- a new molecular entity (an original "TYPE 1" NDA, or an original BLA);
- a new indication (an "EFFICACY" supplement).
Labeling and manufacturing supplements are left out.

openFDA matches array fields independently. An application approved years ago with a recent
supplement matches the query, so every submission is checked here again.

A recall is one event (`event_id`) however many products it lists. An empty window answers HTTP
404 with error code NOT_FOUND. An empty
approvals window is allowed, but 90 days always hold recalls (about 200), so no recalls means a
broken search (a renamed field also answers 404) and fails the fetch.

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
from advisor.markets import market_of
from advisor.models import ET, AssetType, Market
from advisor.sponsors import SponsorMatcher

APPROVALS_URL = "https://api.fda.gov/drug/drugsfda.json"
RECALLS_URL = "https://api.fda.gov/drug/enforcement.json"
# The model's windows (`model.catalysts`): a record is read a week after its date, as openFDA publishes
# about weekly, in training and live alike.
FDA_LAG_DAYS = 7
APPROVAL_WINDOW_DAYS = 180
RECALL_WINDOW_DAYS = 90
WINDOW_DAYS = APPROVAL_WINDOW_DAYS + FDA_LAG_DAYS
COUNT_DAYS = 90  # the `*_90d` fields' window
COUNTED_APPROVALS = ("original", "new_indication")  # the model's approvals (`new_molecule` is an original)
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
    # The model's rows over the whole WINDOW_DAYS: one date per counted approval (an original or a new
    # indication), and each recall event's earliest report date. A record cached before these fields
    # existed has none, so the stock reads no events until the next fetch.
    approval_days: list[date] = []
    recall_days: dict[str, date] = {}


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
    symbols: Sequence[str] | None = None,
) -> list[DrugEvents]:
    """One record per stock with an approval or recall in the window (only `symbols`, when given).

    The `*_90d` fields and the latest dates count the last COUNT_DAYS days; `approval_days` and
    `recall_days` cover the whole WINDOW_DAYS."""
    start, end = window(as_of)
    recent = end - timedelta(days=COUNT_DAYS)
    wanted = None if symbols is None else set(symbols)
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    latest_approval: dict[str, date] = {}
    approval_days: dict[str, list[date]] = defaultdict(list)
    for sponsor, kind, day in approvals(applications, start, end):
        for symbol in matcher.symbols_for(sponsor):
            if wanted is not None and symbol not in wanted:
                continue
            if kind in COUNTED_APPROVALS:
                approval_days[symbol].append(day)
            if day >= recent:
                counts[symbol][kind] += 1
                latest_approval[symbol] = max(day, latest_approval.get(symbol, day))
    events: dict[str, set[str]] = defaultdict(set)
    serious: dict[str, set[str]] = defaultdict(set)
    latest_recall: dict[str, date] = {}
    recall_days: dict[str, dict[str, date]] = defaultdict(dict)
    for recall in recalls:
        day = fda_date(recall.get("report_date"))
        if day is None or not start <= day <= end:
            continue
        for symbol in matcher.symbols_for(recall.get("recalling_firm") or ""):
            if wanted is not None and symbol not in wanted:
                continue
            event = str(recall.get("event_id") or recall.get("recall_number"))
            # an event listed on several dates is dated by its earliest (Ruling R12)
            recall_days[symbol][event] = min(day, recall_days[symbol].get(event, day))
            if day < recent:
                continue
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
            approval_days=sorted(approval_days[symbol]),
            recall_days=dict(sorted(recall_days[symbol].items())),
        )
        for symbol in sorted(set(approval_days) | set(recall_days) | set(latest_approval))
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
        if not recalls:
            raise RuntimeError(
                f"openFDA reported no drug recalls in {WINDOW_DAYS} days: the search is probably broken"
            )
        # every US name, as the training history matches them; the TSX names are not in its directory
        us_names = {symbol: name for symbol, name in self._names.items() if market_of(symbol) is Market.US}
        updated = meta.get("last_updated")
        return drug_events(
            SponsorMatcher(us_names),
            applications,
            recalls,
            as_of,
            date.fromisoformat(updated) if updated else None,
            symbols,
        )
