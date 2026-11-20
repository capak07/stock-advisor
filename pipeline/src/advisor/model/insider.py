"""Insider trading features from Form 4 open-market trades, as wide day x symbol frames.

A trade is known with its filing: the Eastern date of the true acceptance time, or one session after the
filing date when SEC gives none (`groups.sec_known`), and a day reads only trades known strictly before
it. Training reads them from SEC's quarterly Insider Transactions Data Sets (`training.sec_history`), live
from `sec_insiders`; both keep codes P (open-market purchase) and S (sale) alike, with no filter on the
security (Ruling R8). Rule 10b5-1 plan trades are not separated: SEC flags them only from 2023.

`trades` has `symbol`, `filing_date`, `accepted_at`, `code`, `shares`, `price`, `owners` (the reporting
owners' names, a list) and `officer`. A symbol not in `covered` (no SEC facts) reads NaN for every
feature; a covered one without trades reads 0, and `trades` given as None (live: its collector did not run
cleanly) reads NaN.

SEC publishes the data sets by filing quarter, so training's trades end at the newest data set's quarter end
(`coverage_end`, stored with the history). A training row on day D reads every filing known before D only
while D <= coverage_end + 1 day; a later row would count the unpublished months as no trades, so it reads
NaN. Live has no coverage end: its records are current.
"""

from collections.abc import Sequence
from datetime import date

import numpy as np
import pandas as pd

from advisor.model.fundamentals import _ns
from advisor.model.pit import sec_known, window_count

INSIDER_FEATURES = ["insider_net_buy_90d", "insider_buyers_90d", "officer_buy_180d"]
BUY, SELL = "P", "S"
NET_BUY_WINDOW_DAYS = 90
BUYERS_WINDOW_DAYS = 90
OFFICER_WINDOW_DAYS = 180


def _names(owners: object) -> list[str]:
    """A row's owner names: a list, or an array once read back from parquet; none when missing."""
    if not isinstance(owners, list | tuple | np.ndarray):
        return []
    return [name.strip() for name in owners if isinstance(name, str) and name.strip()]


def _net_buy(rows: pd.DataFrame, market_value: pd.DataFrame, days: pd.DatetimeIndex,
             symbols: list[str]) -> pd.DataFrame:
    """(P dollars - S dollars) known in the window, over the day's market value. A trade without a price
    adds 0 dollars; no net dollars read 0, and net dollars without a positive market value read NaN."""
    dollars = (rows["shares"].astype(float) * rows["price"].astype(float)).fillna(0.0)
    signed = rows.assign(net=dollars.where(rows["code"].eq(BUY), -dollars))
    net = window_count(signed, days, symbols, NET_BUY_WINDOW_DAYS, weight="net")
    value = market_value.reindex(index=days, columns=symbols).astype(float)
    return (net / value.where(value > 0)).mask(net == 0, 0.0)


def _buyers(buys: pd.DataFrame, days: pd.DatetimeIndex, symbols: list[str]) -> pd.DataFrame:
    """The distinct owner names among the P trades known in the window (`window_count` counts rows)."""
    out = pd.DataFrame(0.0, index=days, columns=symbols)
    named = buys.assign(owner=buys["owners"].map(_names))[["symbol", "known", "owner"]].explode("owner")
    named = named.dropna(subset=["owner", "known"])
    if named.empty:
        return out
    named["known"] = _ns(named["known"])
    day_ns = _ns(days).to_numpy("datetime64[ns]")
    start = day_ns - np.timedelta64(BUYERS_WINDOW_DAYS, "D")
    for symbol, rows in named.groupby("symbol", sort=False):
        total = np.zeros(len(days))
        for _, owner in rows.groupby("owner", sort=False):
            known = np.sort(owner["known"].to_numpy("datetime64[ns]"))
            inside = np.searchsorted(known, day_ns, side="left") - np.searchsorted(known, start, side="left")
            total += inside > 0
        out[symbol] = total
    return out


def insider_features(trades: pd.DataFrame | None, market_value: pd.DataFrame, covered: set[str],
                     days: pd.DatetimeIndex, symbols: Sequence[str],
                     coverage_end: date | pd.Timestamp | None = None) -> dict[str, pd.DataFrame]:
    """Wide frames (days x `symbols`) of INSIDER_FEATURES.

    `insider_net_buy_90d` is (P dollars - S dollars) known within 90 days before the day, dollars being
    shares x price, over `market_value` (split-adjusted close x shares outstanding, wide);
    `insider_buyers_90d` counts the distinct owners in the P trades of those 90 days; `officer_buy_180d`
    is 1 when a P trade by an officer is known within 180 days, else 0. Every feature is NaN on a day
    after `coverage_end` + 1 day (training only; see the module docstring).
    """
    symbols = list(symbols)
    out = {name: pd.DataFrame(np.nan, index=days, columns=symbols) for name in INSIDER_FEATURES}
    if trades is not None:
        rows = trades[trades["symbol"].isin(symbols) & trades["code"].isin((BUY, SELL))].copy()
        rows["known"] = sec_known(rows["accepted_at"], rows["filing_date"])
        buys = rows[rows["code"].eq(BUY)]
        officer_buys = buys[buys["officer"].eq(True)]
        out["insider_net_buy_90d"] = _net_buy(rows, market_value, days, symbols)
        out["insider_buyers_90d"] = _buyers(buys, days, symbols)
        out["officer_buy_180d"] = (window_count(officer_buys, days, symbols, OFFICER_WINDOW_DAYS) > 0).astype(float)
    seen = np.broadcast_to(np.array([symbol in covered for symbol in symbols], dtype=bool), (len(days), len(symbols)))
    if coverage_end is not None:  # a day whose windows reach past the newest data set reads missing
        within = _ns(days) <= pd.Timestamp(coverage_end) + pd.Timedelta(days=1)
        seen = seen & np.asarray(within, dtype=bool)[:, None]
    return {name: out[name].where(seen) for name in INSIDER_FEATURES}
