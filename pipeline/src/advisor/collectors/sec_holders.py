"""Large holders from Schedule 13D/13G filings about each company (spec source 12; US only).

Only filings about the company count: SEC files them under the company's "005-" file number. The
company's own 13D/Gs about other issuers (empty file number) are ignored. Structured SCHEDULE
13D/G documents (from December 2024) are parsed, and their issuer CIK must match; legacy SC 13D/G
filings are HTML only and kept as metadata. 13D signals possible activist or control intent.
"""

import xml.etree.ElementTree as ElementTree
from collections.abc import Sequence
from datetime import date, datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field

from advisor.collectors.base import Cadence, Category, Scope, collect_per_symbol
from advisor.collectors.sec import DocumentBudget, Filing, SecEdgar, number, public_by, sec_stop
from advisor.models import ET, AssetType, Market

HOLDER_FORMS = frozenset({
    "SCHEDULE 13D", "SCHEDULE 13D/A", "SCHEDULE 13G", "SCHEDULE 13G/A",
    "SC 13D", "SC 13D/A", "SC 13G", "SC 13G/A",  # legacy, before 2024-12-18
})
SUBJECT_FILE_NUMBER = "005-"
LOOKBACK = timedelta(days=365)
MAX_DOCUMENTS = 500  # per run; a first run over the whole shortlist finishes on later runs


class ReportingPerson(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    shares: float | None = None
    percent: float | None = None


class LargeHolding(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    accession: str
    form: str
    filing_date: date
    accepted_at: datetime | None = None  # true UTC acceptance time
    activist: bool  # Schedule 13D (possible control intent) rather than passive 13G
    amendment: bool
    event_date: date | None = None
    reporting_persons: list[ReportingPerson] = Field(default_factory=list)  # empty for legacy forms


def _text(root: ElementTree.Element, *names: str) -> str | None:
    """The first non-empty element with one of these names, in any namespace."""
    for name in names:
        node = root.find(f".//{{*}}{name}")
        if node is not None and (node.text or "").strip():
            return node.text.strip()
    return None


def _us_date(text: str | None) -> date | None:
    try:
        return datetime.strptime(text or "", "%m/%d/%Y").date()
    except ValueError:
        return None


def holding_header(symbol: str, filing: Filing) -> LargeHolding:
    return LargeHolding(
        symbol=symbol,
        accession=filing.accession,
        form=filing.form,
        filing_date=filing.filing_date,
        accepted_at=filing.accepted_at,
        activist="13D" in filing.form,
        amendment=filing.form.endswith("/A"),
    )


def parse_schedule(symbol: str, filing: Filing, xml: bytes, cik: int) -> LargeHolding | None:
    """A structured 13D/G about `cik`, or None when the document's issuer is someone else."""
    root = ElementTree.fromstring(xml)
    issuer = _text(root, "issuerCik", "issuerCIK")  # 13G and 13D spell it differently
    if issuer is None or not issuer.isdigit() or int(issuer) != cik:
        return None
    people = root.findall(".//{*}coverPageHeaderReportingPersonDetails")  # 13G
    people += root.findall(".//{*}reportingPersonInfo")  # 13D
    persons = [
        ReportingPerson(
            name=_text(node, "reportingPersonName") or "",
            shares=number(_text(
                node, "reportingPersonBeneficiallyOwnedAggregateNumberOfShares", "aggregateAmountOwned"
            )),
            percent=number(_text(node, "classPercent", "percentOfClass")),
        )
        for node in people
    ]
    return holding_header(symbol, filing).model_copy(update={
        "event_date": _us_date(_text(root, "eventDateRequiresFilingThisStatement", "dateOfEvent")),
        "reporting_persons": persons,
    })


class SecHolders:
    name = "sec_13dg"
    category = Category.FUNDAMENTALS
    core = False
    best_effort = False
    cadence = Cadence.DAILY
    asset_types = frozenset({AssetType.STOCK})
    markets = frozenset({Market.US})
    record_type = LargeHolding
    freshness = timedelta(days=7)
    scope = Scope.SYMBOLS
    canary = ("AAPL",)
    canary_requires_records = True
    max_symbols = None

    def __init__(self, sec: SecEdgar, *, max_documents: int = MAX_DOCUMENTS) -> None:
        self._sec = sec
        self._max_documents = max_documents

    def fetch(self, symbols: Sequence[str], as_of: datetime) -> list[LargeHolding]:
        self._sec.require_contact()
        today = as_of.astimezone(ET).date()
        cutoff = today - LOOKBACK
        budget = DocumentBudget(self._sec, self._max_documents, "Schedule 13D/G")

        def one(symbol: str) -> list[LargeHolding]:
            cik = self._sec.cik_for(symbol)
            if cik is None:
                return []
            holdings: list[LargeHolding] = []
            for filing in self._sec.filings(cik):
                if (
                    filing.form not in HOLDER_FORMS
                    or not filing.file_number.startswith(SUBJECT_FILE_NUMBER)
                    or not cutoff <= filing.filing_date <= today
                    or not public_by(filing, as_of)
                ):
                    continue
                if not filing.form.startswith("SCHEDULE"):  # legacy HTML: no structured data
                    holdings.append(holding_header(symbol, filing))
                    continue
                body = budget.fetch(cik, filing)
                try:  # skip only a malformed document, drop it from the cache; the symbol's other holdings stay
                    holding = parse_schedule(symbol, filing, body, cik)
                except (ElementTree.ParseError, ValueError):
                    self._sec.forget(filing)  # fetched again next run
                    continue
                if holding is not None:
                    holdings.append(holding)
            return holdings

        return collect_per_symbol(symbols, one, is_fatal=sec_stop)
