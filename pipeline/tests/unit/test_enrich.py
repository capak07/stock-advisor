from datetime import UTC, date, datetime

from advisor.collectors.base import Scope
from advisor.collectors.cache import DiskCache
from advisor.collectors.tracker import SourceTracker
from advisor.enrich import EnrichTargets, ranked_shortlist, run_enrichment, shortlist, symbols_for
from advisor.models import AssetType
from advisor.screener import ScreenRow
from fakes import FakeCollector

NOW = datetime(2026, 10, 14, 12, 15, tzinfo=UTC)
DAY = date(2026, 10, 13)


def row(symbol: str, adv20: float) -> ScreenRow:
    return ScreenRow(symbol, 10.0, adv20, 70, DAY)


def test_shortlist_puts_priority_first_then_ranks_by_dollar_volume():
    passed = [row("LOW", 2e6), row("HIGH", 9e6), row("MID", 5e6), row("OTCX", 8e6), row("TIE", 5e6)]
    assert shortlist(passed, ["OTCX", "AAPL"], size=3) == ["OTCX", "AAPL", "HIGH", "MID", "TIE"]


def test_shortlist_with_no_priority_and_a_small_size():
    assert shortlist([row("A", 1e6), row("B", 2e6)], [], size=1) == ["B"]


def test_ranked_shortlist_excludes_priority_respects_size_and_breaks_ties_by_symbol():
    passed = [row("LOW", 2e6), row("HIGH", 9e6), row("MID", 5e6), row("OTCX", 8e6), row("TIE", 5e6)]
    assert ranked_shortlist(passed, ["OTCX"], size=3) == ["HIGH", "MID", "TIE"]
    assert ranked_shortlist(passed, ["OTCX"], size=2) == ["HIGH", "MID"]


TARGETS = EnrichTargets(priority_stocks=["OTCX"], crypto=["BTC"], ranked_stocks=["AAA"])


def test_symbols_for_routes_by_scope_and_asset_type():
    stock = FakeCollector("stock")
    crypto = FakeCollector("crypto", asset_types=frozenset({AssetType.CRYPTO}))
    both = FakeCollector("both", asset_types=frozenset({AssetType.STOCK, AssetType.CRYPTO}))
    market = FakeCollector("market", scope=Scope.MARKET)
    assert symbols_for(stock, TARGETS) == ["OTCX", "AAA"]
    assert symbols_for(crypto, TARGETS) == ["BTC"]
    assert symbols_for(both, TARGETS) == ["OTCX", "BTC", "AAA"]
    assert symbols_for(market, TARGETS) == []


def test_run_enrichment_runs_each_collector_once_and_skips_ones_with_no_targets(tmp_path):
    collectors = {
        "stock": FakeCollector("stock"),
        "market": FakeCollector("market", scope=Scope.MARKET),
        "crypto": FakeCollector("crypto", asset_types=frozenset({AssetType.CRYPTO})),
    }
    tracker = SourceTracker(collectors, DiskCache(tmp_path), NOW, {})
    targets = EnrichTargets(priority_stocks=["OTCX"], crypto=[], ranked_stocks=["AAA"])
    results = run_enrichment(tracker, collectors, list(collectors), targets)
    assert sorted(results) == ["market", "stock"]
    assert collectors["stock"].calls == [["OTCX", "AAA"]]
    assert collectors["market"].calls == [[]]
    assert collectors["crypto"].calls == []


def test_run_enrichment_with_nothing_to_do_returns_empty(tmp_path):
    tracker = SourceTracker({}, DiskCache(tmp_path), NOW, {})
    assert run_enrichment(tracker, {}, [], TARGETS) == {}
