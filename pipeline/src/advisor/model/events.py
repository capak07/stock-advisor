"""8-K item and Schedule 13D/13G features, as wide day x symbol frames.

A filing is known on the Eastern date of its true acceptance time, or one session after its filing date
when SEC gives none (`groups.sec_known`), and a day reads only filings known strictly before it. Training
reads them from SEC's bulk submissions (`training.sec_history`); live from `sec_events` and `sec_holders`.

`filings_8k` has `symbol`, `filing_date`, `accepted_at` and `items` (the 8-K item codes, a list).
`holders_13dg` has `symbol`, `filing_date`, `accepted_at` and `activist` (a 13D rather than a 13G); its
rows are already the filings about the company (the "005-" file number). A symbol not in `covered` (no
SEC facts) reads NaN for every feature; a covered one without filings reads 0, and a source given as None
(live: its collector did not run cleanly) reads NaN for its features.
"""

from collections.abc import Sequence

import numpy as np
import pandas as pd

from advisor.model.groups import days_since, sec_known, window_count

EVENT_ITEMS = ("5.02", "1.01", "2.01", "4.02", "3.01")
EVENTS_FEATURES = ["ev_502_90d", "ev_101_90d", "ev_201_90d", "ev_402_90d", "ev_301_90d",
                   "days_since_8k", "activist_13d_180d", "passive_13g_90d"]
DAYS_SINCE_8K_CAP = 120  # the live sec_events.LOOKBACK: live sees no 8-K older than this
ITEM_WINDOW_DAYS = 90
ACTIVIST_WINDOW_DAYS = 180
PASSIVE_WINDOW_DAYS = 90


def _item_name(code: str) -> str:
    return f"ev_{code.replace('.', '')}_{ITEM_WINDOW_DAYS}d"


def _known_rows(filings: pd.DataFrame, symbols: list[str]) -> pd.DataFrame:
    rows = filings[filings["symbol"].isin(symbols)].copy()
    rows["known"] = sec_known(rows["accepted_at"], rows["filing_date"])
    return rows


def _codes(items: object) -> tuple:
    """A row's item codes: a list, or an array once read back from parquet; nothing when missing."""
    return tuple(items) if isinstance(items, list | tuple | np.ndarray) else ()


def _eightk_features(filings: pd.DataFrame, days: pd.DatetimeIndex,
                     symbols: list[str]) -> dict[str, pd.DataFrame]:
    rows = _known_rows(filings, symbols)
    codes = rows["items"].map(_codes)
    out = {
        _item_name(code): window_count(rows[codes.map(lambda c, code=code: code in c).astype(bool)],
                                       days, symbols, ITEM_WINDOW_DAYS)
        for code in EVENT_ITEMS
    }
    out["days_since_8k"] = days_since(rows, days, symbols, DAYS_SINCE_8K_CAP).fillna(float(DAYS_SINCE_8K_CAP))
    return out


def _holder_features(holders: pd.DataFrame, days: pd.DatetimeIndex,
                     symbols: list[str]) -> dict[str, pd.DataFrame]:
    rows = _known_rows(holders, symbols)
    activist = rows["activist"].eq(True)
    return {
        "activist_13d_180d": (window_count(rows[activist], days, symbols, ACTIVIST_WINDOW_DAYS) > 0).astype(float),
        "passive_13g_90d": (window_count(rows[~activist], days, symbols, PASSIVE_WINDOW_DAYS) > 0).astype(float),
    }


def events_features(filings_8k: pd.DataFrame | None, holders_13dg: pd.DataFrame | None, covered: set[str],
                    days: pd.DatetimeIndex, symbols: Sequence[str]) -> dict[str, pd.DataFrame]:
    """Wide frames (days x `symbols`) of EVENTS_FEATURES.

    `ev_<item>_90d` counts the 8-Ks whose items include that code, known within 90 days before the day;
    `days_since_8k` is the days since the latest known 8-K, DAYS_SINCE_8K_CAP when there is none in that
    span. `activist_13d_180d` and `passive_13g_90d` are 1 when a 13D (180 days) or a 13G (90 days) is
    known in the window, else 0.
    """
    symbols = list(symbols)
    out = {name: pd.DataFrame(np.nan, index=days, columns=symbols) for name in EVENTS_FEATURES}
    if filings_8k is not None:
        out.update(_eightk_features(filings_8k, days, symbols))
    if holders_13dg is not None:
        out.update(_holder_features(holders_13dg, days, symbols))
    seen = np.broadcast_to(np.array([symbol in covered for symbol in symbols], dtype=bool), (len(days), len(symbols)))
    return {name: out[name].where(seen) for name in EVENTS_FEATURES}
