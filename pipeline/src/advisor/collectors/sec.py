"""Shared SEC EDGAR access for the SEC collectors (spec sources 8, 9, 10 and 12).

SEC asks every client to name itself and give a contact email in the User-Agent, and to stay
under 10 requests per second per IP (fair-access policy). One SecEdgar per process is shared by
every SEC collector: one rate limiter, one ticker -> CIK map, one submissions fetch per company per
run, and an on-disk cache of filing documents, which never change once filed.
"""

import math
import os
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import httpx

from advisor.collectors.base import MissingCredential, RateLimiter, check_deadline, get_with_retries
from advisor.models import ET

SEC_PER_MINUTE = 300  # half of SEC's 10-per-second cap, shared by every SEC collector
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
CONTACT_EXAMPLE = "stock-advisor you@example.com"


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


def number(text: str | None) -> float | None:
    try:
        value = float(text)  # None raises TypeError
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


class DocumentBudgetExhausted(Exception):
    """A collector downloaded its share of filing documents this run; the rest wait."""


def sec_stop(exc: Exception) -> bool:
    """Errors that end an SEC collector's loop: no contact, SEC blocking us (403), budget spent."""
    if isinstance(exc, MissingCredential | DocumentBudgetExhausted):
        return True
    return isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 403


class SecEdgar:
    """SEC access shared by every SEC collector in one process; safe to use from several threads."""

    def __init__(
        self,
        client: httpx.Client,
        user_agent: str | None,
        limiter: RateLimiter | None = None,
        *,
        documents: Path | None = None,
    ) -> None:
        self._client = client
        self._user_agent = user_agent
        self._limiter = limiter
        self._documents = documents
        self._lock = threading.Lock()
        self._ciks: dict[str, int] | None = None
        self._filings: dict[int, list[Filing]] = {}

    def require_contact(self) -> str:
        if not self._user_agent or "@" not in self._user_agent:
            raise MissingCredential(
                f"SEC_USER_AGENT must name you and give a contact email, e.g. '{CONTACT_EXAMPLE}'"
            )
        return self._user_agent

    def get(self, url: str) -> httpx.Response:
        return get_with_retries(
            self._client, url, headers={"User-Agent": self.require_contact()}, limiter=self._limiter
        )

    def cik_for(self, symbol: str) -> int | None:
        with self._lock:
            ciks = self._ciks
        if ciks is None:
            ciks = parse_tickers(self.get(TICKERS_URL).json())
            with self._lock:
                self._ciks = ciks
        return ciks.get(sec_ticker(symbol))

    def filings(self, cik: int) -> list[Filing]:
        """A company's recent filings, fetched once per process and shared by every collector."""
        with self._lock:
            known = self._filings.get(cik)
        if known is None:
            known = parse_filings(self.get(SUBMISSIONS_URL.format(cik=cik)).json())
            with self._lock:
                known = self._filings.setdefault(cik, known)
        return known

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
