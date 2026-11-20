"""Short-selling features from FINRA's short interest and daily short volume, as wide day x symbol frames.

Short interest is known `SHORT_KNOWN_SESSIONS` sessions after its settlement date (FINRA's true
publication dates of old files cannot be recovered, so training and live share this fixed rule); a day
reads the latest settlement known strictly before it and goes blind once that settlement is over
`SHORT_STALE_DAYS` old. Share counts are compared on today's basis. Daily short volume is known from
the session after its trade date: a day reads only file days strictly before it, and goes blind once the
oldest of the 20 file days it reads is over `VOLUME_STALE_DAYS` old (a history that stopped).
"""

from collections.abc import Sequence

import numpy as np
import pandas as pd

from advisor.model.fundamentals import _ns, _split_at
from advisor.models import Market
from advisor.schedule import sessions_after

SHORT_FEATURES = ["short_pct_shares", "days_to_cover", "short_chg", "short_vol_ratio_20d"]
SHORT_KNOWN_SESSIONS = 12
SHORT_STALE_DAYS = 45
VOLUME_SESSIONS = 20
VOLUME_MIN = 10
VOLUME_STALE_DAYS = 35  # 20 sessions span about 28 days; older file days mean the files stopped coming


def _known(settlement: pd.Series) -> pd.Series:
    """The date each settlement becomes known: its 12th session after it, on the NYSE calendar."""
    after = {
        day: pd.Timestamp(sessions_after(Market.US, day.date(), SHORT_KNOWN_SESSIONS))
        for day in settlement.unique()
    }
    return settlement.map(after).astype("datetime64[ns]")


def _interest_features(interest: pd.DataFrame, shares: pd.DataFrame, splits: pd.DataFrame,
                       days: pd.DatetimeIndex, symbols: list[str]) -> dict[str, pd.DataFrame]:
    out = {name: pd.DataFrame(np.nan, index=days, columns=symbols) for name in SHORT_FEATURES[:3]}
    rows = interest[interest["symbol"].isin(symbols)][
        ["symbol", "settlement", "short_interest", "days_to_cover"]].copy()
    rows["settlement"] = _ns(rows["settlement"])
    rows = rows.dropna(subset=["settlement"])
    if rows.empty:
        return out
    rows = rows.drop_duplicates(["symbol", "settlement"], keep="last").sort_values(
        ["symbol", "settlement"], kind="stable")
    factor = 1.0 if splits.empty else _split_at(splits, rows["symbol"], rows["settlement"]).to_numpy()
    rows["today"] = rows["short_interest"].astype(float).to_numpy() * factor  # on today's share basis
    rows["before"] = rows.groupby("symbol")["today"].shift()
    rows["known"] = _known(rows["settlement"])

    day_ns = _ns(days).to_numpy("datetime64[ns]")
    count = shares.reindex(index=days, columns=symbols)
    for symbol, group in rows.groupby("symbol", sort=False):
        known = group["known"].to_numpy("datetime64[ns]")  # ascending with the settlement
        last = np.searchsorted(known, day_ns, side="left") - 1  # latest settlement with known < D
        pick = np.maximum(last, 0)
        age = (day_ns - group["settlement"].to_numpy("datetime64[ns]")[pick]) / np.timedelta64(1, "D")
        fresh = (last >= 0) & (age <= SHORT_STALE_DAYS)
        held = group["today"].to_numpy()[pick]
        before = group["before"].to_numpy()[pick]
        total = count[symbol].to_numpy(float)
        total = np.where(total > 0, total, np.nan)
        out["short_pct_shares"][symbol] = np.where(fresh, held / total, np.nan)
        out["short_chg"][symbol] = np.where(fresh, (held - before) / total, np.nan)
        out["days_to_cover"][symbol] = np.where(fresh, group["days_to_cover"].to_numpy(float)[pick], np.nan)
    return out


def _volume_ratio(volume: pd.DataFrame, days: pd.DatetimeIndex, symbols: list[str]) -> pd.DataFrame:
    """Mean short share of volume over the symbol's rows among the last VOLUME_SESSIONS file days before D;
    NaN when the oldest of those file days is more than VOLUME_STALE_DAYS before D."""
    out = pd.DataFrame(np.nan, index=days, columns=symbols)
    file_day = _ns(volume["day"]).dropna().to_numpy("datetime64[ns]")
    file_days = np.unique(file_day)  # the days FINRA published a file, whatever the symbol
    if len(file_days) == 0:
        return out
    rows = volume[volume["symbol"].isin(symbols) & (volume["total_volume"] > 0)].copy()
    rows["day"] = _ns(rows["day"])
    rows["ratio"] = rows["short_volume"] / rows["total_volume"]
    rows = rows.dropna(subset=["day", "ratio"]).drop_duplicates(["symbol", "day"], keep="last")
    column = {symbol: i for i, symbol in enumerate(symbols)}
    at = np.searchsorted(file_days, rows["day"].to_numpy("datetime64[ns]")) + 1  # row 0 stays empty
    where = (at, rows["symbol"].map(column).to_numpy())
    total = np.zeros((len(file_days) + 1, len(symbols)))
    seen = np.zeros_like(total)
    np.add.at(total, where, rows["ratio"].to_numpy(float))
    np.add.at(seen, where, 1.0)
    total, seen = total.cumsum(axis=0), seen.cumsum(axis=0)

    day_ns = _ns(days).to_numpy("datetime64[ns]")
    end = np.searchsorted(file_days, day_ns, side="left")  # file days < D
    begin = np.maximum(end - VOLUME_SESSIONS, 0)
    n = seen[end] - seen[begin]
    mean = (total[end] - total[begin]) / np.maximum(n, 1.0)
    oldest = file_days[np.minimum(begin, len(file_days) - 1)]
    fresh = (end > begin) & (day_ns - oldest <= np.timedelta64(VOLUME_STALE_DAYS, "D"))
    out[:] = np.where((n >= VOLUME_MIN) & fresh[:, None], mean, np.nan)
    return out


def short_features(interest: pd.DataFrame | None, volume: pd.DataFrame | None, shares: pd.DataFrame,
                   splits: pd.DataFrame, days: pd.DatetimeIndex, symbols: Sequence[str]) -> dict[str, pd.DataFrame]:
    """Wide frames (days x `symbols`) of SHORT_FEATURES.

    `interest` has `symbol`, `settlement`, `short_interest`, `days_to_cover`; `volume` has `symbol`, `day`,
    `short_volume`, `total_volume`; `shares` is shares outstanding on today's basis (days x symbols).
    A missing source (None), or a symbol it does not list, reads NaN.
    """
    symbols = list(symbols)
    out = {name: pd.DataFrame(np.nan, index=days, columns=symbols) for name in SHORT_FEATURES}
    if interest is not None:
        out.update(_interest_features(interest, shares, splits, days, symbols))
    if volume is not None:
        out["short_vol_ratio_20d"] = _volume_ratio(volume, days, symbols)
    return {name: out[name] for name in SHORT_FEATURES}
