"""Helpers shared by the Yahoo (yfinance) per-symbol collectors."""

YAHOO_PER_MINUTE = 120  # one shared budget for Yahoo's per-symbol calls (analyst, earnings)


def rate_limited(exc: Exception) -> bool:
    """yfinance's YFRateLimitError: stop asking Yahoo for the rest of this run."""
    return type(exc).__name__ == "YFRateLimitError"
