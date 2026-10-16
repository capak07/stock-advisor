"""Coin tickers as exchanges list them today, shared by the crypto price collectors."""

RENAMED = {"MATIC": "POL"}  # Polygon's MATIC became POL in 2024; exchanges price only POL


def listed_as(symbol: str) -> str:
    """The ticker a coin trades under now ("MATIC" -> "POL"); others are unchanged."""
    return RENAMED.get(symbol, symbol)
