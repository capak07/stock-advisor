"""Clinical-trial activity per stock from ClinicalTrials.gov's API (source 49).

Asking per company would take hundreds of requests, and search misses names such as
"ModernaTX, Inc.". So each fetch makes three market-wide queries over industry-sponsored trials,
about one request each:
- results posted in the last RESULTS_DAYS;
- stopped (terminated, suspended, withdrawn) and updated in the last STOPPED_DAYS;
- phase 2 or 3, still active, with the primary completion due in the next COMPLETION_DAYS. A
  readout is near.

Lead sponsors are matched to the run's stocks (`advisor.sponsors`). About 900 trials are always
completing in the window, so none means a broken query and fails the fetch.

The API holds only a trial's current status. "Stopped and recently updated" includes trials
stopped long ago that only had results posted. So a status book on disk remembers each active
trial's status, and a stop counts only when the book saw that trial active. The detection date
is kept, so the daily health check finding a stop first doesn't hide it from the weekly run.
Trials stopped before they neared completion aren't in the book, and aren't counted.

Dates are "YYYY-MM-DD" or month-only "YYYY-MM". A month-only completion date counts as the
month's last day, and the record says it isn't exact.

robots.txt disallows /api/, but the API is documented for programs; the owner accepted it. Its
`Crawl-delay: 1` is honoured: requests are at least 1.2 s apart.
"""

import calendar
import json
import os
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
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

STUDIES_URL = "https://clinicaltrials.gov/api/v2/studies"
CLINICAL_TRIALS_PER_MINUTE = 50  # Crawl-delay: 1
RESULTS_DAYS = 30
STOPPED_DAYS = 10
COMPLETION_DAYS = 90
FORGET_DAYS = 400  # book entries not seen for this long are dropped
FIELDS = "NCTId,OverallStatus,Phase,PrimaryCompletionDate,LastUpdatePostDate,ResultsFirstPostDate,LeadSponsorName"
INDUSTRY = "AREA[LeadSponsorClass]INDUSTRY"
ACTIVE = ("RECRUITING", "ACTIVE_NOT_RECRUITING", "ENROLLING_BY_INVITATION", "NOT_YET_RECRUITING")
STOPPED = ("TERMINATED", "SUSPENDED", "WITHDRAWN")


class TrialActivity(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    as_of: date  # ET date of the run
    results_posted_30d: int = 0
    stopped_10d: int = 0  # trials seen active that were found stopped in the last 10 days
    completions_90d: int = 0  # active phase 2/3 trials with primary completion due in 90 days
    phase3_completions_90d: int = 0
    next_completion: date | None = None
    next_completion_exact: bool = True  # False: only the month is known (the date is its last day)


@dataclass(frozen=True)
class Trial:
    nct_id: str
    sponsor: str
    status: str
    phases: tuple[str, ...]
    primary_completion: date | None
    completion_exact: bool


def trial_date(text: str | None) -> tuple[date | None, bool]:
    """('2026-10-21' -> that day, exact) or ('2026-10' -> the month's last day, not exact)."""
    if not text:
        return None, True
    try:
        if len(text) == 7:
            year, month = int(text[:4]), int(text[5:])
            return date(year, month, calendar.monthrange(year, month)[1]), False
        return date.fromisoformat(text), True
    except ValueError:
        return None, True


def trial(study: Mapping[str, Any]) -> Trial:
    protocol = study.get("protocolSection") or {}
    status = protocol.get("statusModule") or {}
    day, exact = trial_date((status.get("primaryCompletionDateStruct") or {}).get("date"))
    return Trial(
        nct_id=(protocol.get("identificationModule") or {}).get("nctId", ""),
        sponsor=((protocol.get("sponsorCollaboratorsModule") or {}).get("leadSponsor") or {}).get("name", ""),
        status=status.get("overallStatus", ""),
        phases=tuple((protocol.get("designModule") or {}).get("phases") or ()),
        primary_completion=day,
        completion_exact=exact,
    )


class StatusBook:
    """The last status seen per trial, and when each stop was found, in a JSON file."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def _load(self) -> dict[str, dict]:
        try:
            book = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return book if isinstance(book, dict) else {}

    def _save(self, book: dict[str, dict]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(".tmp")
        temporary.write_text(json.dumps(book, sort_keys=True), encoding="utf-8")
        os.replace(temporary, self._path)

    def update(self, trials: Sequence[Trial], today: date) -> dict[str, date]:
        """Record each trial's status; return every trial found stopped after being seen active,
        with the day the stop was found."""
        book = self._load()
        for t in trials:
            entry = book.get(t.nct_id) if isinstance(book.get(t.nct_id), dict) else None
            stopped = entry.get("stopped") if entry else None
            if t.status in STOPPED and entry and entry.get("status") in ACTIVE:
                stopped = today.isoformat()
            book[t.nct_id] = {"status": t.status, "seen": today.isoformat(), "stopped": stopped}
        forget = (today - timedelta(days=FORGET_DAYS)).isoformat()
        book = {k: v for k, v in book.items() if isinstance(v, dict) and v.get("seen", "") >= forget}
        self._save(book)
        found: dict[str, date] = {}
        for nct_id, entry in book.items():
            try:
                if entry.get("stopped"):
                    found[nct_id] = date.fromisoformat(entry["stopped"])
            except ValueError:
                continue
        return found


def trial_activity(
    matcher: SponsorMatcher,
    results: Sequence[Trial],
    stopped: Sequence[Trial],
    completing: Sequence[Trial],
    stops_found: Mapping[str, date],
    today: date,
) -> list[TrialActivity]:
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    nearest: dict[str, tuple[date, bool]] = {}
    for t in results:
        for symbol in matcher.symbols_for(t.sponsor):
            counts[symbol]["results"] += 1
    recent = today - timedelta(days=STOPPED_DAYS)
    for t in stopped:
        found = stops_found.get(t.nct_id)
        if found and found > recent:
            for symbol in matcher.symbols_for(t.sponsor):
                counts[symbol]["stopped"] += 1
    for t in completing:
        for symbol in matcher.symbols_for(t.sponsor):
            counts[symbol]["completions"] += 1
            if "PHASE3" in t.phases:
                counts[symbol]["phase3"] += 1
            if t.primary_completion and t.primary_completion >= today:
                current = nearest.get(symbol)
                if current is None or t.primary_completion < current[0]:
                    nearest[symbol] = (t.primary_completion, t.completion_exact)
    return [
        TrialActivity(
            symbol=symbol,
            as_of=today,
            results_posted_30d=c["results"],
            stopped_10d=c["stopped"],
            completions_90d=c["completions"],
            phase3_completions_90d=c["phase3"],
            next_completion=nearest[symbol][0] if symbol in nearest else None,
            next_completion_exact=nearest[symbol][1] if symbol in nearest else True,
        )
        for symbol, c in sorted(counts.items())
        if any(c.values())
    ]


class ClinicalTrials:
    name = "clinical_trials"
    category = Category.CATALYSTS
    core = False
    best_effort = False
    cadence = Cadence.WEEKLY
    asset_types = frozenset({AssetType.STOCK})
    markets = frozenset({Market.US, Market.TSX})
    record_type = TrialActivity
    freshness = timedelta(days=14)
    scope = Scope.SYMBOLS
    canary = ("PFE",)
    canary_requires_records = False  # the health check loads no names, so nothing matches
    max_symbols = None

    def __init__(
        self,
        client: httpx.Client,
        book: StatusBook,
        limiter: RateLimiter | None = None,
        *,
        names: CompanyNames | None = None,
    ) -> None:
        self._client = client
        self._book = book
        self._limiter = limiter
        self._names = names or CompanyNames()

    def _trials(self, advanced: str, statuses: Sequence[str] = ()) -> list[Trial]:
        params: dict[str, Any] = {"filter.advanced": advanced, "fields": FIELDS, "pageSize": 1000}
        if statuses:
            params["filter.overallStatus"] = "|".join(statuses)
        trials: list[Trial] = []
        while True:
            check_deadline()
            payload = get_with_retries(self._client, STUDIES_URL, params=params, limiter=self._limiter).json()
            trials.extend(trial(study) for study in payload.get("studies") or [])
            token = payload.get("nextPageToken")
            if not token:
                return trials
            params["pageToken"] = token

    def fetch(self, symbols: Sequence[str], as_of: datetime) -> list[TrialActivity]:
        today = as_of.astimezone(ET).date()

        def since(days: int) -> str:
            return f"RANGE[{today - timedelta(days=days)},MAX]"

        results = self._trials(f"{INDUSTRY} AND AREA[ResultsFirstPostDate]{since(RESULTS_DAYS)}")
        stopped = self._trials(f"{INDUSTRY} AND AREA[LastUpdatePostDate]{since(STOPPED_DAYS)}", STOPPED)
        due = f"RANGE[{today},{today + timedelta(days=COMPLETION_DAYS)}]"
        completing = self._trials(
            f"{INDUSTRY} AND AREA[PrimaryCompletionDate]{due} AND AREA[Phase](PHASE2 OR PHASE3)", ACTIVE
        )
        if not completing:
            raise RuntimeError(
                "ClinicalTrials.gov reported no trials completing in the next 90 days: the query is probably broken"
            )
        stops_found = self._book.update([*completing, *stopped], today)
        known = {symbol: name for symbol in symbols if (name := self._names.get(symbol))}
        return trial_activity(SponsorMatcher(known), results, stopped, completing, stops_found, today)
