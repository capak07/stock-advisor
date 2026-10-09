from pathlib import Path

import httpx

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
