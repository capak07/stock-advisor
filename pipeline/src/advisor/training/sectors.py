"""Yahoo's sector and industry for every stock, and the sector ETF each one is compared with.

yfinance's screener lists the stocks of one industry per query, so labelling the universe takes
about 300 requests (one or more pages per industry and market, roughly 3 minutes at the polite
pace). It covers about 99% of US stocks and 96% of TSX stocks. A stock the screener doesn't list
stays unclassified (`None`) and is compared with its market's benchmark instead of a sector ETF,
as are the TSX sectors that have no iShares fund.
"""

import time
from collections.abc import Callable, Sequence
from typing import Any

import pandas as pd

from advisor.collectors.base import check_deadline
from advisor.collectors.yfinance_bars import to_yahoo
from advisor.markets import MARKETS
from advisor.models import Market

PAGE = 250  # the screener's largest page
PAUSE_SECONDS = 0.4
US_EXCHANGES = ("NMS", "NYQ", "NGM", "NCM", "ASE", "PCX", "BTS")
TSX_EXCHANGE = "TOR"
MAX_FAILED_SHARE = 0.1  # more failed queries than this means Yahoo is refusing the screener
SECTOR_ETFS: dict[Market, dict[str, str]] = {
    Market.US: {
        "Technology": "XLK", "Financial Services": "XLF", "Healthcare": "XLV",
        "Consumer Cyclical": "XLY", "Industrials": "XLI", "Communication Services": "XLC",
        "Consumer Defensive": "XLP", "Energy": "XLE", "Real Estate": "XLRE",
        "Basic Materials": "XLB", "Utilities": "XLU",
    },
    Market.TSX: {
        "Energy": "XEG.TO", "Financial Services": "XFN.TO", "Technology": "XIT.TO",
        "Basic Materials": "XMA.TO", "Real Estate": "XRE.TO", "Utilities": "XUT.TO",
        "Consumer Defensive": "XST.TO",
    },
}

Screen = Callable[[Any, int], Sequence[str]]


class ScreenerRefused(Exception):
    """Yahoo refused too many screener queries to trust the labels."""


def sector_etf(market: Market, sector: str | None) -> str:
    """The market's ETF for the sector, or its benchmark when it has none (or the sector is unknown)."""
    if sector is None:
        return MARKETS[market].benchmark
    return SECTOR_ETFS[market].get(sector, MARKETS[market].benchmark)


def all_sector_etfs() -> dict[Market, list[str]]:
    return {market: sorted(etfs.values()) for market, etfs in SECTOR_ETFS.items()}


def industries() -> dict[str, str]:
    """Every industry yfinance knows, mapped to its sector."""
    from yfinance.const import EQUITY_SCREENER_EQ_MAP  # imported lazily: slow import

    return {
        industry: sector
        for sector, names in EQUITY_SCREENER_EQ_MAP["industry"].items()
        for industry in names
    }


def _yahoo_query(industry: str, market: Market) -> Any:
    from yfinance import EquityQuery

    if market is Market.US:
        exchange = EquityQuery("is-in", ["exchange", *US_EXCHANGES])
    else:
        exchange = EquityQuery("eq", ["exchange", TSX_EXCHANGE])
    return EquityQuery("and", [EquityQuery("eq", ["industry", industry]), exchange])


def _yahoo_screen(query: Any, offset: int) -> Sequence[str]:
    import yfinance as yf

    result = yf.screen(query, offset=offset, size=PAGE, sortField="intradaymarketcap", sortAsc=False)
    return [quote["symbol"] for quote in result.get("quotes", [])]


def screen_industries(
    industry_sectors: dict[str, str],
    *,
    screen: Screen = _yahoo_screen,
    query: Callable[[str, Market], Any] = _yahoo_query,
    sleep: Callable[[float], None] = time.sleep,
    pause: float = PAUSE_SECONDS,
) -> dict[str, tuple[str, str]]:
    """Yahoo symbol -> (sector, industry), paging each industry's stocks in each market."""
    found: dict[str, tuple[str, str]] = {}
    asked = failed = 0
    for industry, sector in industry_sectors.items():
        for market in Market:
            q = query(industry, market)
            offset = 0
            while True:
                check_deadline()
                sleep(pause)
                asked += 1
                try:
                    symbols = screen(q, offset)
                except Exception:
                    failed += 1
                    break
                for symbol in symbols:
                    found.setdefault(symbol, (sector, industry))
                if len(symbols) < PAGE:
                    break
                offset += PAGE
    if asked and failed / asked > MAX_FAILED_SHARE:
        raise ScreenerRefused(f"{failed} of {asked} Yahoo screener queries failed")
    return found


def classify(symbols: Sequence[str], found: dict[str, tuple[str, str]]) -> pd.DataFrame:
    """One row per symbol with its sector and industry, or None where Yahoo didn't list it."""
    rows = [(symbol, *found.get(to_yahoo(symbol), (None, None))) for symbol in symbols]
    return pd.DataFrame(rows, columns=["symbol", "sector", "industry"], dtype=object)
