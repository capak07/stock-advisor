"""Yahoo's analyst rating changes for the whole universe, as a history table for the stock model.

One `Ticker.upgrades_downgrades` request per symbol, through the shared Yahoo limiter. Not
`collect_yahoo`: its empty-share and empty-streak rules are tuned for a shortlist, and a whole-universe
history has many symbols Yahoo does not cover. Here a symbol Yahoo has nothing for just adds no rows
(and is counted as empty). Any other failure (a timeout, a reset connection, a parse error) is tried
once more; a symbol that fails twice is logged and counted as failed, apart from empty, and the run
raises SilentFailure when more than MAX_FAILED_SHARE of the symbols asked failed. It also stops at
once on a rate limit, or when a canary symbol comes back empty or fails (Yahoo blocked, not "no data").

Columns: `symbol`, `graded_at` (naive UTC), `firm`, `action`, `from_grade`, `to_grade`,
`price_target_action`.
"""

import logging
from collections.abc import Callable, Sequence

import pandas as pd

from advisor.collectors.base import RateLimiter
from advisor.collectors.yahoo import SilentFailure, rate_limited
from advisor.collectors.yfinance_analyst import _quietly
from advisor.collectors.yfinance_bars import to_yahoo

YAHOO_CANARIES = ("AAPL", "MSFT")
MAX_FAILED_SHARE = 0.02  # more symbols than this share failing (not "empty") means the run is unreliable
EVENT_COLUMNS = ["symbol", "graded_at", "firm", "action", "from_grade", "to_grade", "price_target_action"]
_SOURCE = {
    "Firm": "firm", "Action": "action", "FromGrade": "from_grade", "ToGrade": "to_grade",
    "priceTargetAction": "price_target_action",
}


def yahoo_grades(symbol: str) -> pd.DataFrame:
    """A symbol's `upgrades_downgrades` from Yahoo (empty when Yahoo lacks it): the only request made."""
    import yfinance as yf  # imported lazily: slow import, and tests inject a fake

    logging.getLogger("yfinance").setLevel(logging.CRITICAL)  # it logs an ERROR line per 404
    return _quietly(lambda: yf.Ticker(to_yahoo(symbol)).upgrades_downgrades, pd.DataFrame())


def _events(symbol: str, grades: pd.DataFrame | None) -> pd.DataFrame:
    """One symbol's rows in EVENT_COLUMNS, oldest first; no rows for no data."""
    if grades is None or grades.empty:
        return pd.DataFrame(columns=EVENT_COLUMNS)
    graded = pd.to_datetime(grades.index, utc=True).tz_localize(None)  # naive UTC
    frame = pd.DataFrame({"symbol": symbol, "graded_at": graded.astype("datetime64[ns]")})
    for source, name in _SOURCE.items():
        frame[name] = grades[source].to_numpy() if source in grades else None
    return frame.dropna(subset=["graded_at"]).sort_values("graded_at", kind="stable")


def analyst_history(symbols: Sequence[str], load: Callable[[str], pd.DataFrame],
                    limiter: RateLimiter | None) -> tuple[pd.DataFrame, int]:
    """(the rating changes of `symbols`, how many symbols Yahoo had nothing for).

    `load(symbol)` returns Yahoo's `upgrades_downgrades` frame (GradeDate index; Firm, ToGrade, FromGrade,
    Action and priceTargetAction columns). One call and one limiter token per symbol (two of each after
    a failure). A rate-limit error (`yahoo.rate_limited`) is re-raised at once. Any other error is retried
    once, then logged and counted as failed (not empty). Raises SilentFailure when a canary among `symbols`
    has no rows or fails, or when failed symbols exceed MAX_FAILED_SHARE of those asked.
    """
    parts: list[pd.DataFrame] = []
    asked = list(dict.fromkeys(symbols))
    empty = failed = 0
    for symbol in asked:
        frame = None
        for attempt in (1, 2):  # a failure other than a rate limit gets one retry, through the limiter
            if limiter is not None:
                limiter.acquire()
            try:
                frame = _events(symbol, load(symbol))
                break
            except Exception as exc:
                if rate_limited(exc):
                    raise
                if attempt == 2:
                    logging.getLogger(__name__).warning(
                        "Yahoo analyst history failed for %s: %s", symbol, type(exc).__name__)
        if frame is None:
            failed += 1
            if symbol in YAHOO_CANARIES:
                raise SilentFailure(f"Yahoo analyst history failed for canary {symbol}")
            if failed > MAX_FAILED_SHARE * len(asked):
                raise SilentFailure(f"Yahoo analyst history failed for {failed} of {len(asked)} symbols")
            continue
        if frame.empty:
            empty += 1
            if symbol in YAHOO_CANARIES:
                raise SilentFailure(f"Yahoo returned no rating changes for {symbol} (blocked or rate-limited?)")
            continue
        parts.append(frame)
    events = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=EVENT_COLUMNS)
    events["graded_at"] = events["graded_at"].astype("datetime64[ns]")
    return events[EVENT_COLUMNS], empty
