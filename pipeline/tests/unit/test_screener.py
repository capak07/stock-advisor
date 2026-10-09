from datetime import date

from advisor.screener import hard_filter, price_stats
from fakes import history


def test_price_stats_uses_last_twenty_bars_for_dollar_volume():
    bars = history("X", 50, close=10.0, volume=1_000_000) + history(
        "X", 20, close=10.0, volume=1_000, start=date(2026, 8, 1)
    )
    row = price_stats("X", bars)
    assert row.adv20 == 10_000.0
    assert row.history_days == 70
    assert row.last_close == 10.0
    assert row.last_day == date(2026, 8, 20)


def test_hard_filter_applies_price_volume_and_history_thresholds():
    universe = {
        "PASS": history("PASS", 60, close=10.0, volume=200_000),     # $2M ADV, 60 days
        "PENNY": history("PENNY", 60, close=0.9, volume=50_000_000),  # price < $1
        "THIN": history("THIN", 60, close=10.0, volume=99_999.9),     # ADV just under $1M
        "YOUNG": history("YOUNG", 59, close=10.0, volume=200_000),    # 59 days of history
        "EMPTY": [],
    }
    assert [row.symbol for row in hard_filter(universe)] == ["PASS"]


def test_as_features_is_json_friendly():
    row = price_stats("X", history("X", 60))
    assert row.as_features() == {
        "last_close": 10.0,
        "adv20": 2_000_000.0,
        "history_days": 60,
        "last_day": "2026-07-30",
    }


def test_hard_filter_excludes_rows_whose_last_bar_is_older_than_fresh_since():
    universe = {"STALE": history("STALE", 60)}  # last bar 2026-07-30
    assert hard_filter(universe, fresh_since=date(2026, 7, 31)) == []
    assert [row.symbol for row in hard_filter(universe, fresh_since=date(2026, 7, 30))] == [
        "STALE"
    ]
    assert [row.symbol for row in hard_filter(universe, fresh_since=None)] == ["STALE"]


def test_is_fresh_compares_last_day_with_floor():
    row = price_stats("X", history("X", 60))  # last bar 2026-07-30
    assert row.is_fresh(date(2026, 7, 30)) is True
    assert row.is_fresh(date(2026, 7, 31)) is False
