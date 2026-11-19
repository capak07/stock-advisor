"""Yahoo's analyst rating changes and earnings reports for the whole universe, as history tables for the stock model.

One `Ticker.upgrades_downgrades` (or `get_earnings_dates`) request per symbol, through the shared Yahoo limiter. Not
`collect_yahoo`: its empty-share and empty-streak rules are tuned for a shortlist, and a whole-universe
history has many symbols Yahoo does not cover. Here a symbol Yahoo has nothing for just adds no rows
(and is counted as empty). Any other failure (a timeout, a reset connection, a parse error) is tried
once more; a symbol that fails twice is logged and counted as failed, apart from empty, and the run
raises SilentFailure when more than MAX_FAILED_SHARE of the symbols asked failed. It also stops at
once on a rate limit, or when a canary symbol comes back empty or fails (Yahoo blocked, not "no data").

Columns: `symbol`, `graded_at` (naive UTC), `firm`, `action`, `from_grade`, `to_grade`,
`price_target_action`. Reports: `symbol`, `report_day` (ET date), `timing`, `eps_estimate`, `eps_actual`.
Both histories run through `_download`.
"""

import logging
from collections.abc import Callable, Sequence

import pandas as pd

from advisor.collectors.base import RateLimiter
from advisor.collectors.yahoo import SilentFailure, rate_limited
from advisor.collectors.yfinance_analyst import _quietly
from advisor.collectors.yfinance_bars import to_yahoo
from advisor.collectors.yfinance_earnings import parse_earnings
from advisor.model.estimates import report_timing

YAHOO_CANARIES = ("AAPL", "MSFT")
MAX_FAILED_SHARE = 0.02  # more symbols than this share failing (not "empty") means the run is unreliable
EARNINGS_LIMIT = 100  # Task 0: reaches back to 2002, well past 2018 (about 37 reports since 2018)
REPORT_COLUMNS = ["symbol", "report_day", "timing", "eps_estimate", "eps_actual"]
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


def _download(symbols: Sequence[str], load: Callable[[str], pd.DataFrame | None],
              limiter: RateLimiter | None, to_frame: Callable[[str, pd.DataFrame | None], pd.DataFrame],
              what: str, nothing: str) -> tuple[list[pd.DataFrame], int]:
    """The shared Yahoo history loop: (each symbol's non-empty frame, how many symbols had nothing).

    One `load(symbol)` call and one limiter token per symbol (two of each after a failure); `to_frame`
    turns the answer into rows, and no rows means Yahoo had nothing. A rate-limit error
    (`yahoo.rate_limited`) is re-raised at once. Any other error is retried once, then logged and counted
    as failed (not empty). Raises SilentFailure when a canary among `symbols` has no rows or fails, or when
    failed symbols exceed MAX_FAILED_SHARE of those asked. `what` and `nothing` word the messages.
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
                frame = to_frame(symbol, load(symbol))
                break
            except Exception as exc:
                if rate_limited(exc):
                    raise
                if attempt == 2:
                    logging.getLogger(__name__).warning(
                        "Yahoo %s failed for %s: %s", what, symbol, type(exc).__name__)
        if frame is None:
            failed += 1
            if symbol in YAHOO_CANARIES:
                raise SilentFailure(f"Yahoo {what} failed for canary {symbol}")
            if failed > MAX_FAILED_SHARE * len(asked):
                raise SilentFailure(f"Yahoo {what} failed for {failed} of {len(asked)} symbols")
            continue
        if frame.empty:
            empty += 1
            if symbol in YAHOO_CANARIES:
                raise SilentFailure(f"Yahoo returned no {nothing} for {symbol} (blocked or rate-limited?)")
            continue
        parts.append(frame)
    return parts, empty


def analyst_history(symbols: Sequence[str], load: Callable[[str], pd.DataFrame],
                    limiter: RateLimiter | None) -> tuple[pd.DataFrame, int]:
    """(the rating changes of `symbols`, how many symbols Yahoo had nothing for).

    `load(symbol)` returns Yahoo's `upgrades_downgrades` frame (GradeDate index; Firm, ToGrade, FromGrade,
    Action and priceTargetAction columns). The loop, retry and stop rules are `_download`'s.
    """
    parts, empty = _download(symbols, load, limiter, _events, "analyst history", "rating changes")
    events = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=EVENT_COLUMNS)
    events["graded_at"] = events["graded_at"].astype("datetime64[ns]")
    return events[EVENT_COLUMNS], empty


def yahoo_earnings(symbol: str) -> pd.DataFrame | None:
    """A symbol's `get_earnings_dates(limit=100)` from Yahoo (None or empty when Yahoo lacks it)."""
    import yfinance as yf  # imported lazily: slow import, and tests inject a fake

    logging.getLogger("yfinance").setLevel(logging.CRITICAL)  # it logs an ERROR line per 404
    return _quietly(lambda: yf.Ticker(to_yahoo(symbol)).get_earnings_dates(limit=EARNINGS_LIMIT), None)


def _reports(symbol: str, dates: pd.DataFrame | None) -> pd.DataFrame:
    """One symbol's reports in REPORT_COLUMNS, oldest first, one per ET day (a reported row beats a
    scheduled one, as `yfinance_earnings.parse_earnings` has it); no rows for no data."""
    parsed = parse_earnings(symbol, dates)
    if not parsed:
        return pd.DataFrame(columns=REPORT_COLUMNS)
    at = pd.Series([report.report_at for report in parsed])
    return pd.DataFrame({
        "symbol": symbol,
        "report_day": at.dt.tz_localize(None).dt.normalize().astype("datetime64[ns]"),
        "timing": report_timing(at),
        "eps_estimate": [report.eps_estimate for report in parsed],
        "eps_actual": [report.eps_actual for report in parsed],
    })


def estimates_history(symbols: Sequence[str], load: Callable[[str], pd.DataFrame | None],
                      limiter: RateLimiter | None) -> tuple[pd.DataFrame, int]:
    """(the earnings reports of `symbols`, how many symbols Yahoo had nothing for).

    `load(symbol)` returns Yahoo's `get_earnings_dates(limit=100)` frame (report-time index in ET; `EPS
    Estimate`, `Reported EPS` and `Surprise(%)` columns), scheduled future reports included. Columns:
    `symbol`, `report_day` (the ET date, datetime64[ns]), `timing` ("before-open", "after-close" or None),
    `eps_estimate`, `eps_actual`. The loop, retry and stop rules are `_download`'s, the same as
    `analyst_history`'s.
    """
    parts, empty = _download(symbols, load, limiter, _reports, "earnings history", "earnings dates")
    reports = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=REPORT_COLUMNS)
    reports["report_day"] = reports["report_day"].astype("datetime64[ns]")
    for column in ("eps_estimate", "eps_actual"):
        reports[column] = reports[column].astype("float64")
    return reports[REPORT_COLUMNS], empty
