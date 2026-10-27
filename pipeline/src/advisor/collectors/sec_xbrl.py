"""Point-in-time financials from SEC XBRL company facts (spec source 8, core; US only).

One companyfacts download per company covers every share class. Every listed concept and every
duplicate (a value re-reported in later filings, restatements) is kept with its `filed` date, so
Plan 3 can pick a concept per period by priority and the latest value knowable on any day.
"""

from collections.abc import Iterator, Mapping, Sequence
from datetime import date, datetime, timedelta
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict

from advisor.collectors.base import Cadence, Category, Scope, collect_per_symbol
from advisor.collectors.sec import COMPANYFACTS_URL, SecEdgar, sec_stop
from advisor.models import ET, AssetType, Market

FORMS = frozenset({"10-K", "10-K/A", "10-Q", "10-Q/A", "10-KT"})  # 8-K XBRL is often partial
LOOKBACK = timedelta(days=3 * 365)  # 12 quarters: growth, margins and their trend
# a period dated outside these years was mistyped by its filer (0202 for 2022, 2201 for 2015);
# periods since a company's founding do start in the 1920s, and pandas holds no year before 1677
YEARS = range(1900, 2100)
USD, PER_SHARE, SHARES = "USD", "USD/shares", "shares"
# metric -> (taxonomy, concept, unit) in priority order; companies switch concepts over time
METRICS: dict[str, tuple[tuple[str, str, str], ...]] = {
    "revenue": (
        ("us-gaap", "Revenues", USD),
        ("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax", USD),
        ("us-gaap", "RevenueFromContractWithCustomerIncludingAssessedTax", USD),
        ("us-gaap", "SalesRevenueNet", USD),
        ("us-gaap", "SalesRevenueGoodsNet", USD),
        ("us-gaap", "RevenuesNetOfInterestExpense", USD),  # banks
    ),
    "cost_of_revenue": (
        ("us-gaap", "CostOfRevenue", USD),
        ("us-gaap", "CostOfGoodsAndServicesSold", USD),
    ),
    "gross_profit": (("us-gaap", "GrossProfit", USD),),
    "operating_income": (("us-gaap", "OperatingIncomeLoss", USD),),
    "net_income": (
        ("us-gaap", "NetIncomeLoss", USD),
        ("us-gaap", "ProfitLoss", USD),
        ("us-gaap", "NetIncomeLossAvailableToCommonStockholdersBasic", USD),
    ),
    "eps_diluted": (
        ("us-gaap", "EarningsPerShareDiluted", PER_SHARE),
        ("us-gaap", "EarningsPerShareBasicAndDiluted", PER_SHARE),
    ),
    "operating_cash_flow": (  # year-to-date durations only
        ("us-gaap", "NetCashProvidedByUsedInOperatingActivities", USD),
        ("us-gaap", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations", USD),
    ),
    "capex": (
        ("us-gaap", "PaymentsToAcquirePropertyPlantAndEquipment", USD),
        ("us-gaap", "PaymentsToAcquireProductiveAssets", USD),
        ("us-gaap", "PaymentsForCapitalImprovements", USD),
    ),
    "long_term_debt": (("us-gaap", "LongTermDebt", USD),),  # total, including the current part
    "long_term_debt_noncurrent": (
        ("us-gaap", "LongTermDebtNoncurrent", USD),
        ("us-gaap", "LongTermDebtAndCapitalLeaseObligations", USD),
    ),
    "debt_current": (
        ("us-gaap", "LongTermDebtCurrent", USD),
        ("us-gaap", "DebtCurrent", USD),
    ),
    "commercial_paper": (("us-gaap", "CommercialPaper", USD),),
    "short_term_borrowings": (("us-gaap", "ShortTermBorrowings", USD),),
    "equity": (
        ("us-gaap", "StockholdersEquity", USD),
        ("us-gaap", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest", USD),
    ),
    "cash": (("us-gaap", "CashAndCashEquivalentsAtCarryingValue", USD),),
    "diluted_shares": (("us-gaap", "WeightedAverageNumberOfDilutedSharesOutstanding", SHARES),),
    "shares_outstanding": (  # multi-class issuers lack the dei cover-page count
        ("dei", "EntityCommonStockSharesOutstanding", SHARES),
        ("us-gaap", "CommonStockSharesOutstanding", SHARES),
    ),
}


class FinancialFact(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    metric: str
    concept: str  # "taxonomy:Concept", e.g. "us-gaap:Revenues"
    unit: str
    start: date | None = None  # None for balance-sheet (instant) facts
    end: date
    value: float
    filed: date  # not knowable before this day
    form: str
    accession: str


def metric_facts(payload: Mapping[str, Any]) -> Iterator[tuple[str, str, str, Mapping[str, Any]]]:
    """Every METRICS concept's raw fact from 10-K/10-Q filings, as (metric, "taxonomy:Concept", unit, fact).

    Facts whose period is dated outside YEARS are left out.
    """
    facts = payload.get("facts", {})
    for metric, concepts in METRICS.items():
        for taxonomy, concept, unit in concepts:
            for fact in facts.get(taxonomy, {}).get(concept, {}).get("units", {}).get(unit, []):
                if fact.get("form") in FORMS and all(
                    int(fact[key][:4]) in YEARS for key in ("start", "end") if key in fact
                ):
                    yield metric, f"{taxonomy}:{concept}", unit, fact


def extract_facts(symbol: str, payload: Mapping[str, Any], as_of: date) -> list[FinancialFact]:
    """Facts for METRICS from 10-K/10-Q filings, periods ending within LOOKBACK, filed by `as_of`."""
    cutoff = as_of - LOOKBACK
    rows: list[FinancialFact] = []
    for metric, concept, unit, fact in metric_facts(payload):
        end, filed = date.fromisoformat(fact["end"]), date.fromisoformat(fact["filed"])
        if end < cutoff or filed > as_of:
            continue
        rows.append(FinancialFact(
            symbol=symbol,
            metric=metric,
            concept=concept,
            unit=unit,
            start=date.fromisoformat(fact["start"]) if "start" in fact else None,
            end=end,
            value=float(fact["val"]),
            filed=filed,
            form=fact["form"],
            accession=fact["accn"],
        ))
    return rows


class SecXbrl:
    name = "sec_xbrl"
    category = Category.FUNDAMENTALS
    core = True
    best_effort = False
    cadence = Cadence.DAILY
    asset_types = frozenset({AssetType.STOCK})
    markets = frozenset({Market.US})
    record_type = FinancialFact
    freshness = timedelta(days=14)
    scope = Scope.SYMBOLS
    canary = ("AAPL",)
    canary_requires_records = True
    max_symbols = None

    def __init__(self, sec: SecEdgar) -> None:
        self._sec = sec

    def _companyfacts(self, cik: int) -> Mapping[str, Any] | None:
        try:
            return self._sec.get(COMPANYFACTS_URL.format(cik=cik)).json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:  # a registrant with no XBRL financials
                return None
            raise

    def fetch(self, symbols: Sequence[str], as_of: datetime) -> list[FinancialFact]:
        self._sec.require_contact()
        today = as_of.astimezone(ET).date()
        by_company: dict[int, list[FinancialFact]] = {}

        def one(symbol: str) -> list[FinancialFact]:
            cik = self._sec.cik_for(symbol)
            if cik is None:
                return []
            if cik not in by_company:  # share classes (GOOG, GOOGL) are one company
                payload = self._companyfacts(cik)
                by_company[cik] = extract_facts(symbol, payload, today) if payload else []
            return [fact.model_copy(update={"symbol": symbol}) for fact in by_company[cik]]

        return collect_per_symbol(symbols, one, is_fatal=sec_stop)
