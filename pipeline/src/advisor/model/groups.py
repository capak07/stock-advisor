"""Shared point-in-time helpers for the data groups, as wide day x symbol frames.

Every record has a `known` date K, and a row on day D reads it only when K < D (strictly before), as
`fundamentals._asof` does. A window of N days is `D - N days <= K < D`. Live and training compute each
feature through the same function, with the same known dates.
"""

from collections.abc import Iterator, Sequence

import numpy as np
import pandas as pd

from advisor.model.fundamentals import _ns
from advisor.models import ET, Market
from advisor.schedule import sessions_after

# Each data group's history files (written by `training.history`, read by the dataset), in the spec's
# priority order. `earnings` needs only fundamentals.parquet, so it is not a key.
GROUP_FILES: dict[str, tuple[str, ...]] = {
    "short": ("short_interest.parquet", "short_volume.parquet"),
    "analyst": ("analyst_events.parquet",),
    "insider": ("insider_trades.parquet",),
    "events": ("material_events.parquet", "large_holders.parquet"),
    "holders": ("holders.parquet",),
    "estimates": ("earnings_estimates.parquet",),
    "catalysts": ("fda_events.parquet",),
}


def sec_known(accepted_at: pd.Series, filing_date: pd.Series) -> pd.Series:
    """The date an SEC filing becomes known (datetime64[ns] days, the index of `accepted_at`).

    The Eastern date of its true acceptance time (a naive time is read as UTC); when that is missing,
    the first session after its filing date, on the NYSE calendar. NaT when both are missing.
    """
    accepted = pd.to_datetime(accepted_at, utc=True)
    known = accepted.dt.tz_convert(ET).dt.tz_localize(None).dt.normalize().astype("datetime64[ns]")
    filed = pd.to_datetime(filing_date).astype("datetime64[ns]")
    need = known.isna() & filed.notna()
    if need.any():
        after = {day: pd.Timestamp(sessions_after(Market.US, day.date(), 1)) for day in filed[need].unique()}
        known = known.mask(need, filed.map(after)).astype("datetime64[ns]")
    return known


def _by_symbol(
    events: pd.DataFrame, symbols: Sequence[str], weight: str | None
) -> Iterator[tuple[str, np.ndarray, np.ndarray | None]]:
    """Per wanted symbol: its sorted known dates and, with a weight, the leading-zero cumulative weights."""
    cols = ["symbol", "known", *([weight] if weight else [])]
    e = events[cols].dropna(subset=["symbol", "known"]).copy()
    e["known"] = _ns(e["known"])
    e = e[e["symbol"].isin(symbols)].sort_values("known", kind="stable")
    for symbol, rows in e.groupby("symbol", sort=False):
        known = rows["known"].to_numpy("datetime64[ns]")
        cum = None
        if weight:
            cum = np.concatenate([[0.0], rows[weight].fillna(0.0).to_numpy(float).cumsum()])
        yield symbol, known, cum


def window_count(events: pd.DataFrame, days: pd.DatetimeIndex, symbols: Sequence[str], window_days: int,
                 weight: str | None = None) -> pd.DataFrame:
    """For each day and symbol, the number of `events` rows (`symbol`, `known`) with
    `D - window_days <= known < D`, or the sum of column `weight` over them (a missing weight adds 0).
    0 where there are none, including for symbols without events."""
    symbols = list(symbols)
    day_ns = _ns(days).to_numpy("datetime64[ns]")
    start = day_ns - np.timedelta64(window_days, "D")
    out = pd.DataFrame(0.0, index=days, columns=symbols)
    for symbol, known, cum in _by_symbol(events, symbols, weight):
        end = np.searchsorted(known, day_ns, side="left")  # rows with known < D
        begin = np.searchsorted(known, start, side="left")  # rows with known < D - window_days
        out[symbol] = (cum[end] - cum[begin]) if cum is not None else (end - begin).astype(float)
    return out


def days_since(events: pd.DataFrame, days: pd.DatetimeIndex, symbols: Sequence[str], cap: int) -> pd.DataFrame:
    """For each day and symbol, the days from the latest `known < D` to D, at most `cap`.
    NaN where the symbol has no such row."""
    symbols = list(symbols)
    day_ns = _ns(days).to_numpy("datetime64[ns]")
    out = pd.DataFrame(np.nan, index=days, columns=symbols)
    for symbol, known, _ in _by_symbol(events, symbols, None):
        last = np.searchsorted(known, day_ns, side="left") - 1  # latest row with known < D
        gap = (day_ns - known[np.maximum(last, 0)]) / np.timedelta64(1, "D")
        out[symbol] = np.where(last >= 0, np.minimum(gap, cap), np.nan)
    return out


def covered_symbols(facts: pd.DataFrame, tickers: pd.DataFrame) -> set[str]:
    """The symbols whose CIK has at least one SEC fact."""
    ciks = set(pd.to_numeric(facts["cik"], errors="coerce").dropna().astype("int64"))
    tick = tickers.assign(cik=pd.to_numeric(tickers["cik"], errors="coerce")).dropna(subset=["cik"])
    return set(tick.loc[tick["cik"].astype("int64").isin(ciks), "symbol"])
