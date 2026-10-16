"""Coin tickers as exchanges list them today, shared by the crypto price collectors."""

import httpx

RENAMED = {"MATIC": "POL"}  # Polygon's MATIC became POL in 2024; exchanges price only POL


def listed_as(symbol: str) -> str:
    """The ticker a coin trades under now ("MATIC" -> "POL"); others are unchanged."""
    return RENAMED.get(symbol, symbol)


class ExchangeThrottled(Exception):
    """An exchange answered with its own rate-limit or lockout error."""


def throttled(exc: Exception) -> bool:
    """Rate limited even after a retry: stop asking that exchange for the rest of the run."""
    if isinstance(exc, ExchangeThrottled):
        return True
    return isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429
