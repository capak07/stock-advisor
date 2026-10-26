"""TSX-listed common shares and REIT units from the TMX company directory (source 2).

One JSON call lists every TSX company with its instruments. Kept: common shares and share
classes (RCI.B), plus .UN units of REITs. Dropped: ETFs, CDRs, funds, split-share and notes
issuers, preferreds (two-dot symbols such as RY.PR.S), warrants, debentures, rights, and
USD-traded lines (.U). Symbols are stored in Yahoo's form: RCI.B becomes RCI-B.TO.
"""

import re
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

import httpx

from advisor.collectors.base import Cadence, Category, RateLimiter, Scope, get_with_retries
from advisor.markets import TSX_SUFFIX
from advisor.models import AssetType, Market, SymbolInfo

DIRECTORY_URL = "https://www.tsx.com/json/company-directory/search/tsx/%5E*"
# The live directory keeps about 675; far fewer means a truncated or changed answer.
MIN_KEPT = 300
INSTRUMENT = re.compile(r"^[A-Z]{1,5}(\.[A-Z]{1,2})?$")
EXCLUDED_SUFFIXES = frozenset({"U", "F", "T", "WT", "DB", "NT", "RT", "W", "R"})
NON_EQUITY = re.compile(r"\b(ETFs?|CDRs?|Funds?|Split|Portfolio|Pool|Notes?)\b")
# Bullion trusts, ActivETFs, split-share income classes and closed-end investment vehicles.
NON_OPERATING = re.compile(
    r"\bPhysical\b.*\bTrust\b|\bActivETF\b|\bIncome (Plus )?Class\b"
    r"|\bPremium Income Corporation\b|\bInvestment Trust Limited\b"
)
REIT = re.compile(r"\b(REIT|Real Estate Investment Trust)\b")


def canonical_symbol(tmx_symbol: str) -> str:
    return tmx_symbol.replace(".", "-") + TSX_SUFFIX


def keep_instrument(symbol: str, instrument_name: str, company_name: str) -> bool:
    match = INSTRUMENT.match(symbol)
    if match is None:
        return False
    suffix = (match.group(1) or ".")[1:]
    if suffix in EXCLUDED_SUFFIXES:
        return False
    if NON_EQUITY.search(company_name) or NON_EQUITY.search(instrument_name):
        return False
    if NON_OPERATING.search(company_name):
        return False
    return suffix != "UN" or REIT.search(company_name) is not None


def parse_directory(payload: dict[str, Any]) -> list[SymbolInfo]:
    records: dict[str, SymbolInfo] = {}
    for company in payload["results"]:
        for instrument in company["instruments"]:
            if not keep_instrument(instrument["symbol"], instrument["name"], company["name"]):
                continue
            symbol = canonical_symbol(instrument["symbol"])
            records.setdefault(
                symbol,
                SymbolInfo(symbol=symbol, market=Market.TSX, name=company["name"], exchange="TSX"),
            )
    return sorted(records.values(), key=lambda record: record.symbol)


class TmxSymbols:
    name = "tmx_symbols"
    category = Category.PRICES
    core = True
    best_effort = True
    cadence = Cadence.DAILY
    asset_types = frozenset({AssetType.STOCK})
    markets = frozenset({Market.TSX})
    record_type = SymbolInfo
    freshness = timedelta(days=3)
    scope = Scope.UNIVERSE
    canary: tuple[str, ...] = ()
    canary_requires_records = True
    max_symbols = None

    def __init__(
        self, client: httpx.Client, limiter: RateLimiter | None = None, *, min_kept: int = MIN_KEPT
    ) -> None:
        self._client = client
        self._limiter = limiter
        self._min_kept = min_kept

    def fetch(self, symbols: Sequence[str], as_of: datetime) -> list[SymbolInfo]:
        response = get_with_retries(self._client, DIRECTORY_URL, limiter=self._limiter)
        records = parse_directory(response.json())
        if len(records) < self._min_kept:  # raising keeps the cached universe in use
            raise ValueError(
                f"TMX directory: only {len(records)} symbols kept,"
                f" expected at least {self._min_kept}"
            )
        return records
