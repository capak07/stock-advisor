"""US-listed common stocks from the NASDAQ Trader symbol directory (source 1)."""

import csv
import io
import re
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta

import httpx

from advisor.collectors.base import Cadence, Category, RateLimiter, get_with_retries
from advisor.models import AssetType, SymbolInfo

NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
OTHER_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"
FOOTER = "File Creation Time"
# Each real file keeps several thousand symbols; fewer means a truncated or empty download.
MIN_KEPT_PER_FILE = 1000
OTHER_EXCHANGES = {
    "A": "NYSE American",
    "N": "NYSE",
    "P": "NYSE Arca",
    "Z": "Cboe BZX",
    "V": "IEX",
}
# Plain tickers plus one-letter share classes (BRK.B). Excludes JPM$D, ABC.WS, etc.
SYMBOL_PATTERN = re.compile(r"^[A-Z]{1,5}(\.[A-Z])?$")
WARRANT = re.compile(r"\bwarrants?\b", re.IGNORECASE)
RIGHT = re.compile(r"\brights?\b", re.IGNORECASE)
UNITS = re.compile(r"\bunits?\b", re.IGNORECASE)
EQUITY_UNITS = re.compile(
    r"\bcommon units?\b|\bunits? representing\b|\bunits? of beneficial interest\b|\blimited partner",
    re.IGNORECASE,
)
PREFERRED = re.compile(r"\bpreferred (stock|shares?|securities)\b|\bpreference shares?\b", re.IGNORECASE)
FRACTIONAL_PREFERRED = re.compile(r"\binterest in a share\b.*\bpreferred\b", re.IGNORECASE)
DEBT = re.compile(r"\b(notes?|debentures?)\b|\bmortgage bonds?\b|\bbonds?\b.*\bdue\b", re.IGNORECASE)
BARE_DEPOSITARY = re.compile(r"\bdepositary shares?\s*$", re.IGNORECASE)
DEPOSITARY_PREFERRED = re.compile(r"\bdepositary shares?\b.*\bpreferred\b", re.IGNORECASE)
ADR = re.compile(r"\bamerican depositary\b", re.IGNORECASE)


def is_excluded_name(name: str) -> bool:
    """True for warrants, rights, SPAC units, preferreds, and debt; ADRs and LP/trust units stay."""
    if FRACTIONAL_PREFERRED.search(name) or WARRANT.search(name):
        return True
    if ADR.search(name):
        return False
    if RIGHT.search(name) or DEBT.search(name):
        return True
    if UNITS.search(name) and not EQUITY_UNITS.search(name):
        return True
    return any(p.search(name) for p in (PREFERRED, BARE_DEPOSITARY, DEPOSITARY_PREFERRED))


def _rows(text: str) -> list[dict[str, str]]:
    lines = [
        line for line in text.splitlines() if line and not line.startswith(FOOTER)
    ]
    return list(csv.DictReader(io.StringIO("\n".join(lines)), delimiter="|"))


def _keep(symbol: str, name: str, etf: str, test_issue: str) -> bool:
    return (
        etf == "N"
        and test_issue == "N"
        and SYMBOL_PATTERN.match(symbol) is not None
        and not is_excluded_name(name)
    )


def parse_nasdaq_listed(text: str) -> list[SymbolInfo]:
    return [
        SymbolInfo(symbol=row["Symbol"], name=row["Security Name"], exchange="NASDAQ")
        for row in _rows(text)
        if _keep(row["Symbol"], row["Security Name"], row["ETF"], row["Test Issue"])
    ]


def parse_other_listed(text: str) -> list[SymbolInfo]:
    return [
        SymbolInfo(
            symbol=row["ACT Symbol"],
            name=row["Security Name"],
            exchange=OTHER_EXCHANGES.get(row["Exchange"], row["Exchange"]),
        )
        for row in _rows(text)
        if _keep(row["ACT Symbol"], row["Security Name"], row["ETF"], row["Test Issue"])
    ]


class NasdaqSymbols:
    name = "nasdaq_symbols"
    category = Category.PRICES
    core = True
    best_effort = False
    cadence = Cadence.DAILY
    asset_types = frozenset({AssetType.STOCK})
    record_type = SymbolInfo
    freshness = timedelta(days=3)

    def __init__(
        self,
        client: httpx.Client,
        limiter: RateLimiter | None = None,
        *,
        min_per_file: int = MIN_KEPT_PER_FILE,
    ) -> None:
        self._client = client
        self._limiter = limiter
        self._min_per_file = min_per_file

    def _download(self, url: str, parse: Callable[[str], list[SymbolInfo]]) -> list[SymbolInfo]:
        """One file's kept symbols; raises on a truncated or shrunken file so it is never cached."""
        text = get_with_retries(self._client, url, limiter=self._limiter).text
        if FOOTER not in text:
            raise ValueError(f"{url}: missing 'File Creation Time' footer (truncated download?)")
        records = parse(text)
        if len(records) < self._min_per_file:
            raise ValueError(
                f"{url}: only {len(records)} symbols kept, expected at least {self._min_per_file}"
            )
        return records

    def fetch(self, symbols: Sequence[str], as_of: datetime) -> list[SymbolInfo]:
        nasdaq = self._download(NASDAQ_LISTED_URL, parse_nasdaq_listed)
        other = self._download(OTHER_LISTED_URL, parse_other_listed)
        merged: dict[str, SymbolInfo] = {}
        for record in nasdaq + other:
            merged.setdefault(record.symbol, record)
        return sorted(merged.values(), key=lambda record: record.symbol)
