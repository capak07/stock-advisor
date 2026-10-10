from pathlib import Path

import httpx

from advisor.collectors.base import Scope
from advisor.collectors.registry import build_registry
from advisor.config import Settings


def test_registry_lists_foundation_collectors_with_core_flags():
    settings = Settings("postgresql://x", "key", "secret", Path(".cache"))
    with httpx.Client() as client:
        registry = build_registry(settings, client)
    assert sorted(registry) == ["alpaca_bars", "nasdaq_symbols", "yfinance_bars"]
    assert {name: c.core for name, c in registry.items()} == {
        "alpaca_bars": True,
        "nasdaq_symbols": True,
        "yfinance_bars": False,
    }
    assert all(registry[name].name == name for name in registry)
    assert {name: c.scope for name, c in registry.items()} == {
        "alpaca_bars": Scope.SYMBOLS,
        "nasdaq_symbols": Scope.UNIVERSE,
        "yfinance_bars": Scope.SYMBOLS,
    }
    for collector in registry.values():  # SYMBOLS collectors need canaries for the health check
        assert bool(collector.canary) == (collector.scope is Scope.SYMBOLS)
    assert all(c.canary_requires_records is True for c in registry.values())
    for collector in registry.values():
        if collector.scope is Scope.SYMBOLS:
            field = collector.record_type.model_fields["symbol"]
            assert field.annotation is str
            assert field.is_required()
