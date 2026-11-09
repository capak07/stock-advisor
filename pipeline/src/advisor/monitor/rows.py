"""Pure row builders for the holding monitor tables, plus price-alert crossing."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, time

from advisor.collectors.sec_events import MaterialEvent, filing_url
from advisor.collectors.sec_insiders import InsiderTrade
from advisor.collectors.yfinance_earnings import EarningsReport
from advisor.models import ET

INSIDER_CODES = frozenset({"P", "S"})


@dataclass(frozen=True)
class FilingRow:
    accession: str
    symbol: str
    form: str
    filed_at: datetime
    report_date: date | None
    items: list[str]
    url: str


@dataclass(frozen=True)
class InsiderRow:
    accession: str
    line: int
    symbol: str
    filed_at: datetime
    trade_date: date
    owner: str
    role: str
    code: str
    shares: float
    price: float | None
    value: float | None
    planned: bool


@dataclass(frozen=True)
class EarningsRow:
    symbol: str
    report_date: date
    report_at: datetime
    eps_estimate: float | None
    eps_actual: float | None
    surprise_pct: float | None


@dataclass(frozen=True)
class PriceAlert:
    id: int
    symbol: str
    asset_type: str  # 'stock' or 'crypto'
    direction: str  # 'above' or 'below'
    level: float


def _filed_at(accepted_at: datetime | None, filing_date: date) -> datetime:
    return accepted_at or datetime.combine(filing_date, time(0), tzinfo=ET)


def filing_rows(events: Iterable[MaterialEvent]) -> list[FilingRow]:
    rows: dict[str, FilingRow] = {}
    for e in events:
        url = filing_url(e)
        if url is None:
            continue
        rows[e.accession] = FilingRow(
            e.accession,
            e.symbol,
            e.form,
            _filed_at(e.accepted_at, e.filing_date),
            e.report_date,
            list(e.items),
            url,
        )
    return list(rows.values())


def _role(t: InsiderTrade) -> str:
    if t.officer_title and t.officer_title.strip():
        return t.officer_title.strip()
    if t.director:
        return "Director"
    if t.ten_percent_owner:
        return "10% owner"
    if t.officer:
        return "Officer"
    return "Insider"


def insider_rows(trades: Iterable[InsiderTrade]) -> list[InsiderRow]:
    rows: list[InsiderRow] = []
    lines: dict[str, int] = {}
    for t in trades:
        if t.code not in INSIDER_CODES or t.derivative:
            continue
        line = lines.get(t.accession, 0)
        lines[t.accession] = line + 1
        rows.append(
            InsiderRow(
                t.accession,
                line,
                t.symbol,
                _filed_at(t.accepted_at, t.filing_date),
                t.trade_date,
                " & ".join(t.owners),
                _role(t),
                t.code,
                t.shares,
                t.price,
                t.shares * t.price if t.price is not None else None,
                t.planned,
            )
        )
    return rows


def earnings_rows(reports: Iterable[EarningsReport]) -> list[EarningsRow]:
    rows: dict[tuple[str, date], EarningsRow] = {}
    for r in reports:
        day = r.report_at.astimezone(ET).date()
        rows[(r.symbol, day)] = EarningsRow(
            r.symbol, day, r.report_at, r.eps_estimate, r.eps_actual, r.surprise_pct
        )
    return list(rows.values())


def alert_hits(
    alerts: Iterable[PriceAlert], prices: Mapping[tuple[str, str], float]
) -> list[tuple[int, float]]:
    hits: list[tuple[int, float]] = []
    for a in alerts:
        price = prices.get((a.symbol, a.asset_type))
        if price is None:
            continue
        if (a.direction == "above" and price >= a.level) or (
            a.direction == "below" and price <= a.level
        ):
            hits.append((a.id, price))
    return hits
