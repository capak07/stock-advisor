"""Earnings-estimate features from Yahoo's earnings dates, as wide day x symbol frames.

A report is known on its Eastern report date, and a day reads only reports with `report_day` strictly
before it (a report on day K is first read on the session after K). Only the past is read: the date of a
future report is never used. `days_to_next_report` is estimated from the same quarter's report a year
earlier plus NEXT_REPORT_DAYS (364 days, 52 weeks, which keeps the weekday), never from a scheduled date.

`reports` is the long frame `yahoo_history.estimates_history` writes (and live builds from
`yfinance_earnings.parse_earnings`): `symbol`, `report_day` (ET date), `timing`, `eps_estimate` and
`eps_actual`, one row per report, scheduled future rows included (they have no actual).
"""

from collections.abc import Sequence

import numpy as np
import pandas as pd

from advisor.model.fundamentals import _ns
from advisor.models import ET

ESTIMATES_FEATURES = ["eps_surprise_last", "eps_beat_streak", "days_to_next_report"]
SURPRISE_CLIP = 1.0  # a surprise is clipped to +-100% of the consensus
STREAK_REPORTS = 4
NEXT_REPORT_DAYS = 364
ESTIMATE_STALE_DAYS = 200  # a surprise older than this is no longer news

_OPEN = pd.Timedelta(hours=9, minutes=30)
_CLOSE = pd.Timedelta(hours=16)


def report_timing(report_at: pd.Series) -> pd.Series:
    """"before-open" (before 09:30), "after-close" (16:00 or later) or None (exactly 00:00, when Yahoo
    gave no time, or in between), for report times in Eastern time (a naive time is read as Eastern).
    The one place report timing is decided; live calls it too."""
    stamps = pd.to_datetime(report_at)
    if stamps.dt.tz is not None:
        stamps = stamps.dt.tz_convert(ET).dt.tz_localize(None)
    into_day = stamps - stamps.dt.normalize()
    before = (into_day > pd.Timedelta(0)) & (into_day < _OPEN)
    label = np.where(before, "before-open", np.where(into_day >= _CLOSE, "after-close", None))
    return pd.Series(label, index=report_at.index, dtype=object)


def _one_per_day(reports: pd.DataFrame, symbols: Sequence[str]) -> pd.DataFrame:
    """The wanted symbols' reports, one row per symbol and day (the reported row beats a scheduled
    one), oldest first, with `report_day` at one resolution."""
    rows = reports[["symbol", "report_day", "eps_estimate", "eps_actual"]].dropna(subset=["symbol", "report_day"])
    rows = rows[rows["symbol"].isin(symbols)].copy()
    rows["report_day"] = _ns(rows["report_day"]).dt.normalize()
    for column in ("eps_estimate", "eps_actual"):
        rows[column] = pd.to_numeric(rows[column], errors="coerce").replace([np.inf, -np.inf], np.nan)
    rows = rows.sort_values(["report_day", "eps_actual"], kind="stable", na_position="first")  # actual last
    return rows.drop_duplicates(["symbol", "report_day"], keep="last")


def estimates_features(reports: pd.DataFrame | None, days: pd.DatetimeIndex,
                       symbols: Sequence[str]) -> dict[str, pd.DataFrame]:
    """Wide frames (days x `symbols`) of ESTIMATES_FEATURES, from reports with `report_day < D` only.

    - `eps_surprise_last`: (actual - estimate) / |estimate| of the latest report that has both numbers,
      clipped to +-SURPRISE_CLIP; NaN when that estimate is 0 or the report is more than
      ESTIMATE_STALE_DAYS old.
    - `eps_beat_streak`: how many of the last STREAK_REPORTS reports with both numbers had actual >
      estimate; NaN with fewer.
    - `days_to_next_report`: the least `(r + NEXT_REPORT_DAYS days - D).days` over past reports r with
      `r + NEXT_REPORT_DAYS days >= D`; NaN when there is none.

    All NaN without `reports` (None) and for a symbol without reports.
    """
    symbols = list(symbols)
    out = {name: pd.DataFrame(np.nan, index=days, columns=symbols) for name in ESTIMATES_FEATURES}
    if reports is None:
        return out
    day_ns = _ns(days).to_numpy("datetime64[ns]")
    year = np.timedelta64(NEXT_REPORT_DAYS, "D")
    for symbol, rows in _one_per_day(reports, symbols).groupby("symbol", sort=False):
        report_ns = rows["report_day"].to_numpy("datetime64[ns]")
        # the next report: the earliest past report no more than a year back, plus a year
        first = np.searchsorted(report_ns, day_ns - year, side="left")
        past = np.minimum(first, len(report_ns) - 1)
        due = (first < len(report_ns)) & (report_ns[past] < day_ns)
        wait = (report_ns[past] + year - day_ns) / np.timedelta64(1, "D")
        out["days_to_next_report"][symbol] = np.where(due, wait, np.nan)

        both = rows.dropna(subset=["eps_estimate", "eps_actual"])
        if both.empty:
            continue
        both_ns = both["report_day"].to_numpy("datetime64[ns]")
        estimate, actual = both["eps_estimate"].to_numpy(float), both["eps_actual"].to_numpy(float)
        count = np.searchsorted(both_ns, day_ns, side="left")  # reports with report_day < D
        last = np.maximum(count - 1, 0)
        with np.errstate(divide="ignore", invalid="ignore"):
            surprise = np.clip((actual - estimate) / np.abs(estimate), -SURPRISE_CLIP, SURPRISE_CLIP)
        surprise[estimate == 0] = np.nan
        age = (day_ns - both_ns[last]) / np.timedelta64(1, "D")
        fresh = (count >= 1) & (age <= ESTIMATE_STALE_DAYS)
        out["eps_surprise_last"][symbol] = np.where(fresh, surprise[last], np.nan)

        beats = np.concatenate([[0.0], (actual > estimate).cumsum()])
        enough = count >= STREAK_REPORTS
        out["eps_beat_streak"][symbol] = np.where(
            enough, beats[count] - beats[np.maximum(count - STREAK_REPORTS, 0)], np.nan)
    return out
