from pathlib import Path

import httpx

from advisor.collectors.base import Scope
from advisor.collectors.registry import build_registry
from advisor.config import Settings
from advisor.models import Market

US = frozenset({Market.US})
TSX = frozenset({Market.TSX})
BOTH = frozenset({Market.US, Market.TSX})
NONE: frozenset[Market] = frozenset()  # crypto belongs to no stock market

# name: (core, scope, canary_requires_records, markets). Every new source adds a row.
EXPECTED = {
    "nasdaq_symbols": (True, Scope.UNIVERSE, True, US),
    "tmx_symbols": (True, Scope.UNIVERSE, True, TSX),
    "yfinance_bars": (True, Scope.SYMBOLS, True, BOTH),
    "finra_short_volume": (False, Scope.SYMBOLS, True, US),
    "finra_short_interest": (False, Scope.SYMBOLS, True, US),
    "yfinance_analyst": (False, Scope.SYMBOLS, True, BOTH),
    "yfinance_earnings": (True, Scope.SYMBOLS, True, BOTH),
    "boc_valet": (False, Scope.MARKET, True, BOTH),
    "sec_xbrl": (True, Scope.SYMBOLS, True, US),
    "sec_8k": (False, Scope.SYMBOLS, True, US),
    "sec_form4": (False, Scope.SYMBOLS, True, US),
    "sec_13dg": (False, Scope.SYMBOLS, True, US),
    "fred": (True, Scope.MARKET, True, BOTH),
    "fomc": (False, Scope.MARKET, True, BOTH),
    "cnn_fear_greed": (False, Scope.MARKET, True, US),
    "crypto_fear_greed": (False, Scope.MARKET, True, NONE),
    "blockchain_stats": (False, Scope.MARKET, True, NONE),
    "defillama_tvl": (False, Scope.SYMBOLS, True, NONE),
    "coingecko": (True, Scope.SYMBOLS, True, NONE),
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
