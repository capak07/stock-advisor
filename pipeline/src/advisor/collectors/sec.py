"""Shared SEC EDGAR access for the SEC collectors (spec sources 8, 9, 10 and 12).

SEC asks every client to name itself and give a contact email in the User-Agent, and to stay
under 10 requests per second per IP (fair-access policy). One SecEdgar per process is shared by
every SEC collector: one rate limiter, one ticker -> CIK map, one submissions fetch per company per
run, and an on-disk cache of filing documents, which never change once filed.
"""

import math
import os
import threading
import time
from collections.abc import Callable, Hashable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, TypeVar

import httpx

from advisor.collectors.base import (
    RETRY_STATUS,
    MissingCredential,
    RateLimiter,
    check_deadline,
    get_with_retries,
)
from advisor.models import ET

SEC_PER_MINUTE = 300  # half of SEC's 10-per-second cap, shared by every SEC collector
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
CONTACT_EXAMPLE = "stock-advisor you@example.com"
SEC_FAILURES_TO_STOP = 5  # requests in a row that failed even after retries: SEC is down for this run

T = TypeVar("T")


def sec_ticker(symbol: str) -> str:
    """SEC's ticker form: share classes use a hyphen (BRK.B -> BRK-B)."""
    return symbol.upper().replace(".", "-")


def archive_url(cik: int, accession: str, name: str) -> str:
    """A filing document's URL; the folder is the accession number without dashes."""
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/{name}"


def true_acceptance(raw: str) -> datetime | None:
    """SEC's acceptanceDateTime converts Eastern wall time to UTC twice; undo the second shift."""
    if not raw:
        return None
    reported = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    return reported + reported.astimezone(ET).utcoffset()


def parse_tickers(payload: Mapping[str, Any]) -> dict[str, int]:
    """SEC's company_tickers.json (an object keyed by row number) as ticker -> CIK."""
    ciks: dict[str, int] = {}
    for row in payload.values():
        ciks.setdefault(str(row["ticker"]).upper(), int(row["cik_str"]))
    return ciks


@dataclass(frozen=True)
class Filing:
    accession: str
    form: str
    filing_date: date
    accepted_at: datetime | None  # true UTC acceptance time
    report_date: date | None
    items: tuple[str, ...]  # 8-K item codes, e.g. ("2.02", "9.01")
    file_number: str  # "005-..." marks a 13D/G about this company
    primary_document: str


def parse_filings(payload: Mapping[str, Any]) -> list[Filing]:
    """The most recent filings (newest first) from a submissions document's parallel arrays."""
    recent = payload["filings"]["recent"]
    filings: list[Filing] = []
    for values in zip(*recent.values(), strict=True):
        row = dict(zip(recent, values, strict=True))
        filings.append(Filing(
            accession=row["accessionNumber"],
            form=row["form"],
            filing_date=date.fromisoformat(row["filingDate"]),
            accepted_at=true_acceptance(row.get("acceptanceDateTime") or ""),
            report_date=date.fromisoformat(row["reportDate"]) if row.get("reportDate") else None,
            items=tuple(item for item in (row.get("items") or "").split(",") if item),
            file_number=row.get("fileNumber") or "",
            primary_document=row.get("primaryDocument") or "",
        ))
    return filings


def public_by(filing: Filing, as_of: datetime) -> bool:
    """Whether SEC had accepted the filing by `as_of` (filings without an acceptance time count as public)."""
    return filing.accepted_at is None or filing.accepted_at <= as_of


def number(text: str | None) -> float | None:
    try:
        value = float(text)  # None raises TypeError
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


class DocumentBudgetExhausted(Exception):
    """A collector downloaded its share of filing documents this run; the rest wait."""


class SecUnavailable(Exception):
    """SEC kept failing (server errors, rate limiting or timeouts), so this run stops asking it."""


def sec_stop(exc: Exception) -> bool:
    """Errors that end an SEC collector's loop: no contact, SEC blocking us (403) or down, budget spent."""
    if isinstance(exc, MissingCredential | DocumentBudgetExhausted | SecUnavailable):
        return True
    return isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 403


class _Flight:
    """A fetch in progress that other threads wait on instead of repeating it."""

    def __init__(self) -> None:
        self.done = threading.Event()
        self.value: Any = None
        self.error: BaseException | None = None


class SecEdgar:
    """SEC access shared by every SEC collector in one process; safe to use from several threads.

    The ticker map and each company's submissions are fetched once: threads asking for one that is
    being fetched wait for it. Errors are not remembered; a later call tries again.
    """

    def __init__(
        self,
        client: httpx.Client,
        user_agent: str | None,
        limiter: RateLimiter | None = None,
        *,
        documents: Path | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = client
        self._user_agent = user_agent
        self._limiter = limiter
        self._documents = documents
        self._sleep = sleep
        self._failures = 0
        self._lock = threading.Lock()
        self._values: dict[Hashable, Any] = {}
        self._flights: dict[Hashable, _Flight] = {}

    def require_contact(self) -> str:
        if not self._user_agent or "@" not in self._user_agent:
            raise MissingCredential(
                f"SEC_USER_AGENT must name you and give a contact email, e.g. '{CONTACT_EXAMPLE}'"
            )
        return self._user_agent

    def get(self, url: str) -> httpx.Response:
        user_agent = self.require_contact()
        with self._lock:
            if self._failures >= SEC_FAILURES_TO_STOP:
                raise SecUnavailable(
                    f"SEC failed {SEC_FAILURES_TO_STOP} requests in a row; no more SEC requests this run"
                )
        try:
            response = get_with_retries(
                self._client, url, headers={"User-Agent": user_agent}, limiter=self._limiter,
                sleep=self._sleep,
            )
        except httpx.TransportError:
            self._count_failure()
            raise
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in RETRY_STATUS:
                self._count_failure()
            else:  # SEC answered (a 404, a 403): it is up
                self._reset_failures()
            raise
        else:
            self._reset_failures()
            return response

    def _count_failure(self) -> None:
        with self._lock:
            self._failures += 1

    def _reset_failures(self) -> None:
        with self._lock:
            self._failures = 0

    def _shared(self, key: Hashable, load: Callable[[], T]) -> T:
        """load() once per key; threads asking meanwhile wait and share its answer or its error."""
        with self._lock:
            if key in self._values:
                return self._values[key]
            flight = self._flights.get(key)
            leader = flight is None
            if leader:
                flight = self._flights[key] = _Flight()
        if not leader:
            flight.done.wait()
            if flight.error is not None:
                raise flight.error
            return flight.value
        try:
            flight.value = load()
        except BaseException as exc:
            flight.error = exc
            raise
        finally:
            with self._lock:
                if flight.error is None:
                    self._values[key] = flight.value
                del self._flights[key]
            flight.done.set()
        return flight.value

    def cik_for(self, symbol: str) -> int | None:
        ciks = self._shared("tickers", lambda: parse_tickers(self.get(TICKERS_URL).json()))
        return ciks.get(sec_ticker(symbol))

    def filings(self, cik: int) -> list[Filing]:
        """A company's recent filings, fetched once per process and shared by every collector."""
        return self._shared(
            ("submissions", cik), lambda: parse_filings(self.get(SUBMISSIONS_URL.format(cik=cik)).json())
        )

    def _document_path(self, filing: Filing) -> Path | None:
        return None if self._documents is None else self._documents / f"{filing.accession}.xml"

    def has_document(self, filing: Filing) -> bool:
        path = self._document_path(filing)
        return path is not None and path.exists()

    def document(self, cik: int, filing: Filing) -> bytes:
        """The filing's raw XML document, read from disk when it was fetched before."""
        path = self._document_path(filing)
        if path is not None and path.exists():
            return path.read_bytes()
        name = filing.primary_document.rsplit("/", 1)[-1]  # drop the xsl... rendering folder
        body = self.get(archive_url(cik, filing.accession, name)).content
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_bytes(body)
            os.replace(temporary, path)
        return body


class DocumentBudget:
    """At most `limit` document downloads per collector call; documents on disk are free."""

    def __init__(self, sec: SecEdgar, limit: int, kind: str) -> None:
        self._sec = sec
        self._limit = limit
        self._left = limit
        self._kind = kind

    def fetch(self, cik: int, filing: Filing) -> bytes:
        check_deadline()
        if not self._sec.has_document(filing):
            if self._left <= 0:
                raise DocumentBudgetExhausted(
                    f"fetched {self._limit} {self._kind} documents this run; the rest wait for the next run"
                )
            self._left -= 1
        return self._sec.document(cik, filing)
