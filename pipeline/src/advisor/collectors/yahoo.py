"""Helpers shared by the Yahoo (yfinance) per-symbol collectors."""

from collections.abc import Callable, Sequence

from pydantic import BaseModel

from advisor.collectors.base import PartialFetch, RateLimiter, collect_per_symbol

# One shared budget for Yahoo's per-symbol calls (analyst, earnings). It counts symbols: one
# token per symbol, although the analyst source makes up to 3 requests per symbol.
YAHOO_PER_MINUTE = 120

MIN_SYMBOLS_FOR_COVERAGE_CHECK = 20
MAX_EMPTY_SHARE = 0.5  # shortlisted stocks are almost all covered; more empties means Yahoo failed
MAX_CONSECUTIVE_EMPTY = 25  # high enough that a run of held ETFs (never covered) doesn't trip it


class SilentFailure(Exception):
    """Many empty Yahoo answers in a row: an outage that yfinance reported as "no data"."""


def rate_limited(exc: Exception) -> bool:
    """yfinance's YFRateLimitError: stop asking Yahoo for the rest of this run."""
    return type(exc).__name__ == "YFRateLimitError"


def collect_yahoo(
    symbols: Sequence[str],
    fetch_one: Callable[[str], list[BaseModel]],
    *,
    limiter: RateLimiter | None,
) -> list[BaseModel]:
    """collect_per_symbol for Yahoo's per-symbol endpoints, which turn errors into empty answers.

    One limiter token per symbol. Stops after MAX_CONSECUTIVE_EMPTY empty answers in a row, and
    never reports a call where most symbols came back empty as OK: the runner would otherwise
    remember those symbols as having no data for the rest of the day.
    """
    streak = 0
    empty = 0

    def one(symbol: str) -> list[BaseModel]:
        nonlocal streak, empty
        if limiter is not None:
            limiter.acquire()
        records = fetch_one(symbol)
        if records:
            streak = 0
            return records
        streak += 1
        empty += 1
        if streak >= MAX_CONSECUTIVE_EMPTY:
            raise SilentFailure(f"{streak} empty Yahoo answers in a row (blocked or rate-limited?)")
        return records

    records = collect_per_symbol(
        symbols, one, is_fatal=lambda exc: rate_limited(exc) or isinstance(exc, SilentFailure)
    )
    asked = len(dict.fromkeys(symbols))
    if asked >= MIN_SYMBOLS_FOR_COVERAGE_CHECK and empty > MAX_EMPTY_SHARE * asked:
        message = f"Yahoo returned nothing for {empty} of {asked} symbols (blocked or rate-limited?)"
        if records:
            raise PartialFetch(records, message)
        raise RuntimeError(message)
    return records
