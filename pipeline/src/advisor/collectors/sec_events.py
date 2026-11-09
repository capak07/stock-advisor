"""8-K material events from each company's SEC filing list (spec source 9; US only).

The item codes say what happened: 2.02 earnings, 5.02 an officer or director change, 1.01 a
material agreement, 4.02 a restatement, and so on. Every run reads the shared submissions list;
8-K bodies are not downloaded.
"""

from collections.abc import Sequence
from datetime import date, datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field

from advisor.collectors.base import Cadence, Category, Scope, collect_per_symbol
from advisor.collectors.sec import Filing, SecEdgar, archive_url, public_by, sec_stop
from advisor.models import ET, AssetType, Market

EVENT_FORMS = frozenset({"8-K", "8-K/A"})
LOOKBACK = timedelta(days=120)


class MaterialEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    accession: str
    form: str
    filing_date: date
    accepted_at: datetime | None = None  # true UTC acceptance time
    report_date: date | None = None
    items: list[str] = Field(default_factory=list)  # e.g. ["2.02", "9.01"]
    cik: int | None = None  # None on records cached before the link was kept
    primary_document: str | None = None


def filing_url(event: MaterialEvent) -> str | None:
    """The 8-K's main document on sec.gov, or None when the CIK or document name is unknown."""
    if event.cik is None or not event.primary_document:
        return None
    return archive_url(event.cik, event.accession, event.primary_document)


def material_events(
    symbol: str, filings: Sequence[Filing], as_of: date, cik: int | None = None
) -> list[MaterialEvent]:
    cutoff = as_of - LOOKBACK
    return [
        MaterialEvent(
            symbol=symbol,
            accession=filing.accession,
            form=filing.form,
            filing_date=filing.filing_date,
            accepted_at=filing.accepted_at,
            report_date=filing.report_date,
            items=list(filing.items),
            cik=cik,
            primary_document=filing.primary_document or None,
        )
        for filing in filings
        if filing.form in EVENT_FORMS and cutoff <= filing.filing_date <= as_of
    ]


class SecEvents:
    name = "sec_8k"
    category = Category.FUNDAMENTALS
    core = False
    best_effort = False
    cadence = Cadence.PER_RUN  # 8-Ks cluster around the close; read the list every run
    asset_types = frozenset({AssetType.STOCK})
    markets = frozenset({Market.US})
    record_type = MaterialEvent
    freshness = timedelta(days=3)
    scope = Scope.SYMBOLS
    canary = ("AAPL",)
    canary_requires_records = True
    max_symbols = None

    def __init__(self, sec: SecEdgar) -> None:
        self._sec = sec

    def fetch(self, symbols: Sequence[str], as_of: datetime) -> list[MaterialEvent]:
        self._sec.require_contact()
        today = as_of.astimezone(ET).date()

        def one(symbol: str) -> list[MaterialEvent]:
            cik = self._sec.cik_for(symbol)
            if cik is None:
                return []
            public = [f for f in self._sec.filings(cik) if public_by(f, as_of)]
            return material_events(symbol, public, today, cik)

        return collect_per_symbol(symbols, one, is_fatal=sec_stop)
