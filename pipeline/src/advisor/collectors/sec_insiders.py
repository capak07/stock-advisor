"""Insider trades from SEC Form 4 filings (spec source 10; US only).

The filing list comes from the shared submissions document; each Form 4's raw XML is downloaded
once ever (documents are cached on disk). A Form 4 in a company's list whose issuer is someone
else (the company as the reporting owner) is ignored. Codes: P open-market purchase, S sale,
A award, M exercise, F tax withholding, G gift; Plan 3 counts P and S as the signal.
"""

import xml.etree.ElementTree as ElementTree
from collections.abc import Sequence
from datetime import date, datetime, timedelta

from pydantic import BaseModel, ConfigDict

from advisor.collectors.base import Cadence, Category, Scope, collect_per_symbol
from advisor.collectors.sec import DocumentBudget, Filing, SecEdgar, number, sec_stop
from advisor.models import ET, AssetType, Market

INSIDER_FORMS = frozenset({"4", "4/A"})
LOOKBACK = timedelta(days=90)  # spec §5.1: insider net buys over 90 days
MAX_DOCUMENTS = 1000  # per run; a first run over the whole shortlist finishes on later runs


class InsiderTrade(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    accession: str
    filing_date: date
    trade_date: date
    owners: list[str]  # reporting owners ("LAST FIRST"); joint filings list several
    director: bool
    officer: bool
    ten_percent_owner: bool
    officer_title: str | None = None
    code: str
    acquired: bool  # A (acquired) vs D (disposed)
    shares: float
    price: float | None = None
    owned_after: float | None = None
    direct: bool
    derivative: bool  # options and RSUs, not common stock
    planned: bool  # filed under a Rule 10b5-1 trading plan


def _flag(node: ElementTree.Element | None) -> bool:
    return node is not None and (node.text or "").strip().lower() in {"1", "true"}


def _value(element: ElementTree.Element, path: str) -> str | None:
    node = element.find(f"{path}/value")
    text = (node.text or "").strip() if node is not None else ""
    return text or None


def parse_form4(symbol: str, filing: Filing, xml: bytes, cik: int) -> list[InsiderTrade]:
    """Transactions in a Form 4 about `cik`; a document about another issuer yields none."""
    root = ElementTree.fromstring(xml)
    issuer = (root.findtext("issuer/issuerCik") or "").strip()
    if not issuer.isdigit() or int(issuer) != cik:
        return []
    owners = root.findall("reportingOwner")
    roles = [role for o in owners if (role := o.find("reportingOwnerRelationship")) is not None]
    titles = [(role.findtext("officerTitle") or "").strip() for role in roles]
    shared = dict(
        symbol=symbol,
        accession=filing.accession,
        filing_date=filing.filing_date,
        owners=[(o.findtext("reportingOwnerId/rptOwnerName") or "").strip() for o in owners],
        director=any(_flag(role.find("isDirector")) for role in roles),
        officer=any(_flag(role.find("isOfficer")) for role in roles),
        ten_percent_owner=any(_flag(role.find("isTenPercentOwner")) for role in roles),
        officer_title=next((title for title in titles if title), None),
        planned=_flag(root.find("aff10b5One")),
    )
    trades: list[InsiderTrade] = []
    for path, derivative in (
        ("nonDerivativeTable/nonDerivativeTransaction", False),
        ("derivativeTable/derivativeTransaction", True),
    ):
        for row in root.findall(path):
            shares = number(_value(row, "transactionAmounts/transactionShares"))
            day = _value(row, "transactionDate")
            code = (row.findtext("transactionCoding/transactionCode") or "").strip()
            if shares is None or day is None or not code:
                continue
            trades.append(InsiderTrade(
                **shared,
                trade_date=date.fromisoformat(day[:10]),
                code=code,
                acquired=_value(row, "transactionAmounts/transactionAcquiredDisposedCode") == "A",
                shares=shares,
                price=number(_value(row, "transactionAmounts/transactionPricePerShare")),
                owned_after=number(_value(row, "postTransactionAmounts/sharesOwnedFollowingTransaction")),
                direct=_value(row, "ownershipNature/directOrIndirectOwnership") != "I",
                derivative=derivative,
            ))
    return trades


class SecInsiders:
    name = "sec_form4"
    category = Category.FUNDAMENTALS
    core = False
    best_effort = False
    cadence = Cadence.DAILY
    asset_types = frozenset({AssetType.STOCK})
    markets = frozenset({Market.US})
    record_type = InsiderTrade
    freshness = timedelta(days=3)
    scope = Scope.SYMBOLS
    canary = ("AAPL",)
    canary_requires_records = True
    max_symbols = None

    def __init__(self, sec: SecEdgar, *, max_documents: int = MAX_DOCUMENTS) -> None:
        self._sec = sec
        self._max_documents = max_documents

    def fetch(self, symbols: Sequence[str], as_of: datetime) -> list[InsiderTrade]:
        self._sec.require_contact()
        today = as_of.astimezone(ET).date()
        cutoff = today - LOOKBACK
        budget = DocumentBudget(self._sec, self._max_documents, "Form 4")

        def one(symbol: str) -> list[InsiderTrade]:
            cik = self._sec.cik_for(symbol)
            if cik is None:
                return []
            trades: list[InsiderTrade] = []
            for filing in self._sec.filings(cik):
                if filing.form in INSIDER_FORMS and cutoff <= filing.filing_date <= today:
                    body = budget.fetch(cik, filing)
                    try:  # a malformed document is cached, so skip only it; the symbol's other trades stay
                        trades.extend(parse_form4(symbol, filing, body, cik))
                    except (ElementTree.ParseError, ValueError):
                        pass
            return trades

        return collect_per_symbol(symbols, one, is_fatal=sec_stop)
