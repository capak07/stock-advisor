from advisor.models import AssetRef, AssetType
from advisor.run import priority_order


def test_priority_order_puts_holdings_before_watchlist_only_symbols():
    held = {AssetRef("AAPL", AssetType.STOCK), AssetRef("BTC", AssetType.CRYPTO)}
    watch = {
        AssetRef("AAPL", AssetType.STOCK),
        AssetRef("NVDA", AssetType.STOCK),
        AssetRef("ETH", AssetType.CRYPTO),
    }
    assert priority_order(held, watch, AssetType.STOCK) == ["AAPL", "NVDA"]
    assert priority_order(held, watch, AssetType.CRYPTO) == ["BTC", "ETH"]
