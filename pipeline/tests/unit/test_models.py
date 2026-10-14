from datetime import date

import pytest
from pydantic import ValidationError

from advisor.models import AssetRef, AssetType, DailyBar, Market, SymbolInfo


def test_daily_bar_rejects_non_positive_prices():
    with pytest.raises(ValidationError):
        DailyBar(
            symbol="X", day=date(2026, 10, 14), open=1, high=1, low=1, close=0,
            volume=10, source="test",
        )


def test_asset_ref_is_hashable_and_compares_by_value():
    assert {AssetRef("AAPL", AssetType.STOCK)} == {AssetRef("AAPL", AssetType.STOCK)}


def test_symbol_info_needs_a_market_for_stocks_and_none_for_crypto():
    assert SymbolInfo(symbol="RY.TO", market=Market.TSX, name="Royal Bank", exchange="TSX").market is Market.TSX
    crypto = SymbolInfo(symbol="BTC", asset_type=AssetType.CRYPTO, name="Bitcoin", exchange="-")
    assert crypto.market is None
    with pytest.raises(ValidationError, match="stocks need a market and crypto has none"):
        SymbolInfo(symbol="AAPL", name="Apple", exchange="NASDAQ")
    with pytest.raises(ValidationError, match="stocks need a market and crypto has none"):
        SymbolInfo(
            symbol="BTC", asset_type=AssetType.CRYPTO, market=Market.US, name="Bitcoin", exchange="-"
        )
