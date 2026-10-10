from datetime import UTC, datetime, timedelta

from advisor.collectors.cache import DiskCache
from advisor.models import SymbolInfo
from fakes import info

T0 = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)


def test_put_then_get_round_trips_records(tmp_path):
    cache = DiskCache(tmp_path, clock=lambda: T0)
    cache.put("nasdaq_symbols", "", [info("AAPL"), info("MSFT")])
    got = cache.get("nasdaq_symbols", "", SymbolInfo, timedelta(days=1))
    assert [r.symbol for r in got] == ["AAPL", "MSFT"]


def test_get_returns_none_when_older_than_max_age(tmp_path):
    now = [T0]
    cache = DiskCache(tmp_path, clock=lambda: now[0])
    cache.put("s", "k", [info("AAPL")])
    now[0] = T0 + timedelta(days=2)
    assert cache.get("s", "k", SymbolInfo, timedelta(days=1)) is None


def test_get_returns_none_for_missing_or_corrupt_entries(tmp_path):
    cache = DiskCache(tmp_path, clock=lambda: T0)
    assert cache.get("s", "k", SymbolInfo, timedelta(days=1)) is None
    cache.put("s", "k", [info("AAPL")])
    for path in tmp_path.rglob("*.json"):
        path.write_text("{not json", encoding="utf-8")
    assert cache.get("s", "k", SymbolInfo, timedelta(days=1)) is None


def test_get_returns_none_for_valid_json_of_the_wrong_shape(tmp_path):
    cache = DiskCache(tmp_path, clock=lambda: T0)
    cache.put("s", "k", [info("AAPL")])
    for path in tmp_path.rglob("*.json"):
        path.write_text("[]", encoding="utf-8")
    assert cache.get("s", "k", SymbolInfo, timedelta(days=1)) is None
