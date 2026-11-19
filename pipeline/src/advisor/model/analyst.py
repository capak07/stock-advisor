"""Analyst rating-change features from Yahoo's `upgrades_downgrades`, as wide day x symbol frames.

A rating change is known on the Eastern date of its grade time (Yahoo stamps it in naive UTC), and a
day reads only changes known strictly before it. Yahoo keeps a capped number of rows per symbol, so a
symbol whose history reached `ANALYST_CAP_ROWS` may have lost older changes: its counts read missing
until their window is covered by what survives, and its days-since-downgrade until `DOWNGRADE_CAP`
days after the oldest survivor (an older downgrade would otherwise be invisible).

`events` has `symbol`, `graded_at` (naive UTC), `action` ("up", "down", ...) and `price_target_action`
("Raises", "Lowers", ...). `coverage` has `symbol`, `oldest` (the Eastern date of the symbol's oldest
event, the first day it can be known) and `rows`.
"""

from collections.abc import Sequence

import numpy as np
import pandas as pd

from advisor.model.fundamentals import _ns
from advisor.model.groups import days_since, window_count
from advisor.models import ET

ANALYST_FEATURES = ["net_upgrades_30d", "net_upgrades_90d", "net_target_raises_90d", "days_since_downgrade"]
ANALYST_CAP_ROWS = 1000  # Task 0: no exact cap seen (AAPL 971 rows, MSFT 955); at or over this, rows may be lost
DOWNGRADE_CAP = 365
COUNT_WINDOW_DAYS = 90  # the longest count window


def _known(graded_at: pd.Series) -> pd.Series:
    """The Eastern date of each naive-UTC grade time (datetime64[ns] days)."""
    stamp = pd.to_datetime(graded_at).dt.tz_localize("UTC").dt.tz_convert(ET).dt.tz_localize(None)
    return stamp.dt.normalize().astype("datetime64[ns]")


def coverage_from(oldest: pd.Series, rows: pd.Series) -> pd.DataFrame:
    """`symbol`, `oldest` and `rows` from two Series indexed by symbol: each symbol's oldest grade time
    (naive UTC) and its event count. `oldest` becomes that time's Eastern date, the known day.
    The one place coverage is converted to Eastern time."""
    symbols = list(oldest.index)
    return pd.DataFrame({
        "symbol": symbols,
        "oldest": _known(oldest.reset_index(drop=True)),
        "rows": rows.reindex(symbols).to_numpy().astype("int64"),
    })


def coverage(events: pd.DataFrame) -> pd.DataFrame:
    """`coverage_from` over each symbol's oldest `graded_at` and row count."""
    grouped = events.dropna(subset=["symbol", "graded_at"]).groupby("symbol")["graded_at"]
    return coverage_from(grouped.min(), grouped.size())


_coverage_of = coverage  # `analyst_features` has a parameter of the same name


def _is(column: pd.Series, value: str) -> pd.Series:
    return (column == value).fillna(False).astype(bool)


def analyst_features(events: pd.DataFrame | None, coverage: pd.DataFrame | None, days: pd.DatetimeIndex,
                     symbols: Sequence[str]) -> dict[str, pd.DataFrame]:
    """Wide frames (days x `symbols`) of ANALYST_FEATURES.

    All four are NaN on days up to and including the symbol's `oldest`, for a symbol `coverage` does not
    list, and without `events` (None). A capped symbol (`rows` >= ANALYST_CAP_ROWS) is also NaN for its
    three counts until 90 days after `oldest` and for days-since-downgrade until DOWNGRADE_CAP days after.
    Without `coverage` it is taken from `events`.
    """
    symbols = list(symbols)
    if events is None:
        return {name: pd.DataFrame(np.nan, index=days, columns=symbols) for name in ANALYST_FEATURES}
    cover = (_coverage_of(events) if coverage is None else coverage).drop_duplicates("symbol", keep="last")
    cover = cover.set_index("symbol").reindex(symbols)

    rows = events[events["symbol"].isin(symbols)].dropna(subset=["symbol", "graded_at"]).copy()
    rows["known"] = _known(rows["graded_at"])
    action, target = rows["action"], rows["price_target_action"]
    up, down = rows[_is(action, "up")], rows[_is(action, "down")]
    raises, lowers = rows[_is(target, "Raises")], rows[_is(target, "Lowers")]
    out = {
        "net_upgrades_30d": window_count(up, days, symbols, 30) - window_count(down, days, symbols, 30),
        "net_upgrades_90d": window_count(up, days, symbols, 90) - window_count(down, days, symbols, 90),
        "net_target_raises_90d": window_count(raises, days, symbols, 90) - window_count(lowers, days, symbols, 90),
        "days_since_downgrade": days_since(down, days, symbols, DOWNGRADE_CAP),
    }

    capped = (cover["rows"].fillna(0).to_numpy(float) >= ANALYST_CAP_ROWS)[None, :]
    first = _ns(cover["oldest"]).to_numpy("datetime64[ns]")[None, :]  # NaT for a symbol without events
    day_ns = _ns(days).to_numpy("datetime64[ns]")[:, None]

    def readable_after(capped_days: int) -> np.ndarray:
        """Days past the oldest known day (plus `capped_days` for a capped symbol)."""
        extra = np.where(capped, np.timedelta64(capped_days, "D"), np.timedelta64(0, "D"))
        return day_ns > first + extra

    counts_ok, since_ok = readable_after(COUNT_WINDOW_DAYS), readable_after(DOWNGRADE_CAP)
    for name in ANALYST_FEATURES:
        out[name] = out[name].where(since_ok if name == "days_since_downgrade" else counts_ok)
    return out
