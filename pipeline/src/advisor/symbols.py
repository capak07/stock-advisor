"""Canonical symbols ("BRK.B") and a provider-neutral key for matching other formats."""

from collections.abc import Sequence

_SEPARATORS = "./- "


def symbol_key(symbol: str) -> str:
    """Upper case with share-class separators removed: "BRK/B", "BRK-B", "BRKB" all -> "BRKB"."""
    return "".join(ch for ch in symbol.upper() if ch not in _SEPARATORS)


def requested_by_key(symbols: Sequence[str]) -> dict[str, str]:
    """Map provider-neutral keys back to the canonical symbols that were requested."""
    return {symbol_key(symbol): symbol for symbol in symbols}
