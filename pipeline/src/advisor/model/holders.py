"""Institutional ownership features from 13F quarter-on-quarter changes, as wide day x symbol frames.

SEC's 13F listing shows no publication date, so a quarter is known at the later of its period end + 45
days (the filing deadline) and its data set's window end + 30 days (Ruling R6); training and live use
the same rule (`quarter_known`) and this same feature function (Ruling R3, F5). On day D a symbol reads
its latest quarter known strictly before D and the quarter whose period ended 80 to 100 days before it,
also known before D. Without that pair both features are NaN. Share counts are compared on today's
basis: each quarter's shares are multiplied by the split factor at its period end.

`quarters` has `symbol`, `period`, `known`, `shares` and `holders` (`holders.parquet`, or live's three
data sets in the same shape). None (live: its collector did not run cleanly) reads NaN everywhere.
"""

from collections.abc import Sequence
from datetime import date, timedelta

import numpy as np
import pandas as pd

from advisor.model.fundamentals import _ns, _split_at

HOLDERS_FEATURES = ["holder_count_chg", "inst_shares_chg"]
FILING_DEADLINE_DAYS = 45  # a 13F is due 45 days after its quarter ends
PUBLICATION_LAG_DAYS = 30  # a data set is read from 30 days after its window closes
PREVIOUS_MIN_DAYS, PREVIOUS_MAX_DAYS = 80, 100  # the previous quarter's period end, before the latest's


def quarter_known(period: date, window_end: date) -> date:
    """The day a 13F quarter becomes known: the later of period + 45 days and window end + 30 days."""
    return max(period + timedelta(days=FILING_DEADLINE_DAYS), window_end + timedelta(days=PUBLICATION_LAG_DAYS))


def _previous(periods: np.ndarray) -> np.ndarray:
    """For each row, the row whose period ended 80 to 100 days before it (the latest such), or -1."""
    out = np.full(len(periods), -1)
    for i, period in enumerate(periods):
        gap = (period - periods) / np.timedelta64(1, "D")
        candidates = np.flatnonzero((gap >= PREVIOUS_MIN_DAYS) & (gap <= PREVIOUS_MAX_DAYS))
        if len(candidates):
            out[i] = candidates[np.argmax(periods[candidates])]
    return out


def holders_features(quarters: pd.DataFrame | None, shares: pd.DataFrame, splits: pd.DataFrame,
                     days: pd.DatetimeIndex, symbols: Sequence[str]) -> dict[str, pd.DataFrame]:
    """Wide frames (days x `symbols`) of HOLDERS_FEATURES.

    `holder_count_chg` = holders - previous holders; `inst_shares_chg` = (shares x split factor at the
    period - previous shares x split factor at its period) / shares outstanding on day D (`shares`, on
    today's basis; NaN when it is missing). A symbol without quarters (no CUSIP) reads NaN.
    """
    symbols = list(symbols)
    out = {name: pd.DataFrame(np.nan, index=days, columns=symbols) for name in HOLDERS_FEATURES}
    if quarters is None:
        return out
    rows = quarters[quarters["symbol"].isin(symbols)][["symbol", "period", "known", "shares", "holders"]].copy()
    rows["period"], rows["known"] = _ns(rows["period"]), _ns(rows["known"])
    rows = rows.dropna(subset=["period", "known"])
    if rows.empty:
        return out
    # One row per quarter: a period two data sets report is read from the first that published it.
    rows = rows.sort_values(["symbol", "known", "period"], kind="stable").drop_duplicates(["symbol", "period"])
    rows = rows.sort_values(["symbol", "period"], kind="stable").reset_index(drop=True)
    factor = 1.0 if splits.empty else _split_at(splits, rows["symbol"], rows["period"]).to_numpy()
    rows["today"] = rows["shares"].astype(float).to_numpy() * factor  # on today's share basis

    day_ns = _ns(days).to_numpy("datetime64[ns]")
    outstanding = shares.reindex(index=days, columns=symbols)
    for symbol, group in rows.groupby("symbol", sort=False):
        periods = group["period"].to_numpy("datetime64[ns]")  # ascending
        known = group["known"].to_numpy("datetime64[ns]")
        held = group["today"].to_numpy(float)
        count = group["holders"].to_numpy(float)
        previous = _previous(periods)
        # The latest quarter known before D: the largest period among the rows with known < D.
        by_known = np.argsort(known, kind="stable")
        seen = np.searchsorted(known[by_known], day_ns, side="left")  # rows with known < D
        newest = np.maximum.accumulate(by_known)  # periods ascend with the row, so the max row is the latest
        latest = np.where(seen > 0, newest[np.maximum(seen - 1, 0)], -1)
        before = np.where(latest >= 0, previous[np.maximum(latest, 0)], -1)
        pair = (latest >= 0) & (before >= 0)
        pair &= known[np.maximum(before, 0)] < day_ns  # the previous quarter must be known before D too
        now, then = np.maximum(latest, 0), np.maximum(before, 0)
        total = outstanding[symbol].to_numpy(float)
        total = np.where(total > 0, total, np.nan)
        out["holder_count_chg"][symbol] = np.where(pair, count[now] - count[then], np.nan)
        out["inst_shares_chg"][symbol] = np.where(pair, (held[now] - held[then]) / total, np.nan)
    return out
