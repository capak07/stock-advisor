from pathlib import Path

import httpx

from advisor.collectors.base import Scope
from advisor.collectors.registry import build_registry
from advisor.config import Settings
from advisor.models import Market

US = frozenset({Market.US})
TSX = frozenset({Market.TSX})
BOTH = frozenset({Market.US, Market.TSX})

# name: (core, scope, canary_requires_records, markets). Every new source adds a row.
EXPECTED = {
    "nasdaq_symbols": (True, Scope.UNIVERSE, True, US),
    "tmx_symbols": (True, Scope.UNIVERSE, True, TSX),
    "yfinance_bars": (True, Scope.SYMBOLS, True, BOTH),
    "finra_short_volume": (False, Scope.SYMBOLS, True, US),
}


def build() -> dict:
    with httpx.Client() as client:
        return build_registry(Settings("postgresql://x", Path(".cache")), client)


def test_registry_matches_the_expected_sources():
    registry = build()
    assert {
        name: (c.core, c.scope, c.canary_requires_records, c.markets)
        for name, c in registry.items()
    } == EXPECTED
    assert all(registry[name].name == name for name in registry)


def test_symbols_collectors_have_canaries_and_symbol_records():
    for collector in build().values():
        assert bool(collector.canary) == (collector.scope is Scope.SYMBOLS)
        if collector.scope is Scope.SYMBOLS:
            field = collector.record_type.model_fields["symbol"]
            assert field.annotation is str
            assert field.is_required()
