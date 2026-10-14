"""Per-market rules (spec §3 Markets): calendar, universe source, and shortlist size.

Hard-filter thresholds are the same numbers in each market's own currency, so they stay in
`advisor.screener`.
"""

from dataclasses import dataclass

from advisor.models import Market

TSX_SUFFIX = ".TO"


@dataclass(frozen=True)
class MarketSpec:
    market: Market
    calendar: str  # pandas_market_calendars name
    universe_source: str  # collector that lists the market's stocks
    min_universe: int  # fewer listed stocks than this means the directory was truncated
    shortlist_size: int


MARKETS: dict[Market, MarketSpec] = {
    Market.US: MarketSpec(Market.US, "NYSE", "nasdaq_symbols", 1000, 300),
    Market.TSX: MarketSpec(Market.TSX, "TSX", "tmx_symbols", 300, 100),
}


def market_of(symbol: str) -> Market:
    """The market a stock symbol trades on: Yahoo's `.TO` suffix marks the TSX."""
    return Market.TSX if symbol.endswith(TSX_SUFFIX) else Market.US
