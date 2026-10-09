from datetime import date

import pytest
from pydantic import ValidationError

from advisor.models import AssetRef, AssetType, DailyBar


def test_daily_bar_rejects_non_positive_prices():
    with pytest.raises(ValidationError):
        DailyBar(
            symbol="X", day=date(2026, 10, 14), open=1, high=1, low=1, close=0,
            volume=10, source="test",
        )


def test_asset_ref_is_hashable_and_compares_by_value():
    assert {AssetRef("AAPL", AssetType.STOCK)} == {AssetRef("AAPL", AssetType.STOCK)}
