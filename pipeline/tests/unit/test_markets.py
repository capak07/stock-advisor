import pytest

from advisor.markets import MARKETS, market_of
from advisor.models import Market


@pytest.mark.parametrize(
    ("symbol", "market"),
    [
        ("AAPL", Market.US),
        ("BRK.B", Market.US),
        ("RY.TO", Market.TSX),
        ("RCI-B.TO", Market.TSX),
        ("REI-UN.TO", Market.TSX),
    ],
)
def test_market_of_reads_yahoos_tsx_suffix(symbol, market):
    assert market_of(symbol) is market


def test_markets_table_matches_spec_section_3():
    assert list(MARKETS) == [Market.US, Market.TSX]
    us, tsx = MARKETS[Market.US], MARKETS[Market.TSX]
    assert (us.calendar, us.universe_source, us.min_universe, us.shortlist_size) == (
        "NYSE", "nasdaq_symbols", 1000, 300,
    )
    assert (tsx.calendar, tsx.universe_source, tsx.min_universe, tsx.shortlist_size) == (
        "TSX", "tmx_symbols", 300, 100,
    )
    assert all(spec.market is market for market, spec in MARKETS.items())
