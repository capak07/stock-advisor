"""Per-market rules (spec §3 Markets): calendar, universe source, shortlist size and benchmark.

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
    benchmark: str  # what the market's picks are graded against, and the dashboard compares to


MARKETS: dict[Market, MarketSpec] = {
    Market.US: MarketSpec(Market.US, "NYSE", "nasdaq_symbols", 1000, 300, "SPY"),
    Market.TSX: MarketSpec(Market.TSX, "TSX", "tmx_symbols", 300, 100, "XIU.TO"),
}
BENCHMARKS: tuple[str, ...] = tuple(spec.benchmark for spec in MARKETS.values())


def market_of(symbol: str) -> Market:
    """The market a stock symbol trades on: Yahoo's `.TO` suffix marks the TSX."""
    return Market.TSX if symbol.endswith(TSX_SUFFIX) else Market.US
