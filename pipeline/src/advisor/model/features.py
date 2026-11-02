"""Point-in-time price/volume and relative-strength features for the stock model.

Everything works on wide frames (index `day`, one column per symbol) so one code path serves the
weekly training (years of history) and, later, a live run. Every feature on a day reads only that
day and earlier bars: rolling windows and shifts look backwards, and only `forward_excess` (the
target) looks ahead.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd

from advisor.prices import JUMP_LIMIT
from advisor.screener import ADV_WINDOW, MIN_DOLLAR_VOLUME, MIN_HISTORY_DAYS, MIN_PRICE

HORIZONS = (5, 10, 20, 21, 63, 126)
PRICE_FEATURES = [
    "ret_5", "ret_21", "ret_63", "ret_126", "mom_12_1", "rsi_14", "atr_14_pct", "vol_20", "vol_60",
    "dist_52w_high", "dist_52w_low", "volume_z", "gap", "jump_5d", "log_adv20",
]
# computed for every row and live frame, but only trained on once a model config names them
EXTRA_FEATURES = ["sector_mom_12_1", "sector_dist_52w_high", "amihud_20"]
RS_FEATURES = ["ex_bench_21", "ex_bench_63", "ex_sector_21", "ex_sector_63", "sector_rank_63"]


@dataclass(frozen=True)
class Wide:
    open: pd.DataFrame
    high: pd.DataFrame
    low: pd.DataFrame
    close: pd.DataFrame
    volume: pd.DataFrame


def to_wide(prices: pd.DataFrame) -> Wide:
    """Pivot the long `symbol, day, open, high, low, close, volume` frame."""
    prices = prices.assign(day=pd.to_datetime(prices["day"]))
    frames = {
        field: prices.pivot(index="day", columns="symbol", values=field).sort_index()
        for field in ("open", "high", "low", "close", "volume")
    }
    return Wide(**frames)


def _events_by_symbol(events: pd.DataFrame, columns: Sequence[str]) -> dict[str, pd.DataFrame]:
    if events is None or events.empty:
        return {}
    wanted = events[events["symbol"].isin(set(columns))]
    wanted = wanted.assign(day=pd.to_datetime(wanted["day"])).sort_values("day", ascending=False)
    return {symbol: group for symbol, group in wanted.groupby("symbol")}


def split_factor(index: pd.DatetimeIndex, columns: Sequence[str], events: pd.DataFrame) -> pd.DataFrame:
    """Product of the split ratios strictly after each day (1 where none)."""
    factor = np.ones((len(index), len(columns)))
    position = {symbol: i for i, symbol in enumerate(columns)}
    for symbol, group in _events_by_symbol(events, columns).items():
        for day, ratio in zip(group["day"], group["split"], strict=True):
            if pd.notna(ratio) and ratio > 0 and ratio != 1:
                factor[: index.searchsorted(day, side="left"), position[symbol]] *= ratio
    return pd.DataFrame(factor, index=index, columns=list(columns))


def as_traded(wide: Wide, events: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Undo Yahoo's adjustment: `(split_adjusted_close, traded_close)`.

    Yahoo's auto-adjusted close is split-adjusted, then scaled by `1 - dividend / previous close`
    for every later ex-date. Walking each symbol's dividends newest to oldest recovers that scale.
    """
    adj = wide.close
    index, columns = adj.index, list(adj.columns)
    scale = np.ones(adj.shape)
    filled = adj.ffill().to_numpy()
    position = {symbol: i for i, symbol in enumerate(columns)}
    for symbol, group in _events_by_symbol(events, columns).items():
        col = position[symbol]
        for day, dividend in zip(group["day"], group["dividend"], strict=True):
            end = index.searchsorted(day, side="left")
            if not (pd.notna(dividend) and dividend > 0 and end > 0):
                continue
            before = filled[end - 1, col]
            if not np.isfinite(before) or before <= 0:
                continue
            scale[:end, col] *= 1 / (1 + dividend * scale[end - 1, col] / before)
    split_adjusted = adj / pd.DataFrame(scale, index=index, columns=columns)
    traded = split_adjusted * split_factor(index, columns, events)
    return split_adjusted, traded


def jump_days(close: pd.DataFrame) -> pd.DataFrame:
    """`advisor.prices.find_jumps` per column: >50% from both the last unflagged and the previous close."""
    flags = np.zeros(close.shape, dtype=bool)
    values = close.to_numpy(dtype=float)
    for col in range(values.shape[1]):
        rows = np.flatnonzero(~np.isnan(values[:, col]))
        if len(rows) < 2:
            continue
        series = values[rows, col].tolist()
        last_accepted = series[0]
        for i in range(1, len(series)):
            cur, prev = series[i], series[i - 1]
            if abs(cur / last_accepted - 1) > JUMP_LIMIT and abs(cur / prev - 1) > JUMP_LIMIT:
                flags[rows[i], col] = True
            else:
                last_accepted = cur
    return pd.DataFrame(flags, index=close.index, columns=close.columns)


def _wilder(x: pd.DataFrame, n: int) -> pd.DataFrame:
    return x.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def true_range(wide: Wide) -> pd.DataFrame:
    prev = wide.close.shift(1)
    return np.maximum(np.maximum(wide.high - wide.low, (wide.high - prev).abs()), (wide.low - prev).abs())


def price_features(wide: Wide, dollar_volume: pd.DataFrame, jumps: pd.DataFrame) -> dict[str, pd.DataFrame]:
    c = wide.close
    prev = c.shift(1)
    f: dict[str, pd.DataFrame] = {}
    for k in (5, 21, 63, 126):
        f[f"ret_{k}"] = c / c.shift(k) - 1
    f["mom_12_1"] = c.shift(21) / c.shift(252) - 1
    delta = c.diff()
    up, down = _wilder(delta.clip(lower=0), 14), _wilder((-delta).clip(lower=0), 14)
    f["rsi_14"] = 100 * up / (up + down).replace(0, np.nan)
    f["atr_14_pct"] = _wilder(true_range(wide), 14) / c
    log_ret = np.log(c / prev)
    f["vol_20"] = log_ret.rolling(20).std() * np.sqrt(252)
    f["vol_60"] = log_ret.rolling(60).std() * np.sqrt(252)
    f["dist_52w_high"] = c / wide.high.rolling(252, min_periods=126).max() - 1
    f["dist_52w_low"] = c / wide.low.rolling(252, min_periods=126).min() - 1
    log_volume = np.log1p(wide.volume)
    earlier = log_volume.shift(1).rolling(20)
    f["volume_z"] = ((log_volume - earlier.mean()) / earlier.std().replace(0, np.nan)).clip(-10, 10)
    f["gap"] = wide.open / prev - 1
    f["jump_5d"] = jumps.astype(float).rolling(5, min_periods=1).max()
    f["log_adv20"] = np.log1p(dollar_volume.rolling(ADV_WINDOW).mean())
    # price move per dollar traded, in millions; a day with no dollar volume says nothing about it
    traded = dollar_volume.where(dollar_volume > 0)
    f["amihud_20"] = 1e6 * (c / prev - 1).abs().div(traded).replace(np.inf, np.nan).rolling(20, min_periods=15).mean()
    return f


def relative_strength(
    features: Mapping[str, pd.DataFrame], benchmark: str, etf_of: Mapping[str, str], etfs: Sequence[str]
) -> dict[str, pd.DataFrame]:
    """Returns over the benchmark and over the stock's sector ETF, plus that ETF's rank among `etfs`."""
    columns = list(features["ret_21"].columns)
    sector = [etf_of.get(symbol, benchmark) for symbol in columns]

    def per_stock(frame: pd.DataFrame) -> pd.DataFrame:
        picked = frame.reindex(columns=sector)
        picked.columns = columns
        return picked

    out: dict[str, pd.DataFrame] = {}
    for k in (21, 63):
        ret = features[f"ret_{k}"]
        out[f"ex_bench_{k}"] = ret.sub(ret[benchmark], axis=0)
        out[f"ex_sector_{k}"] = ret - per_stock(ret)
    rank = per_stock(features["ret_63"].reindex(columns=list(etfs)).rank(axis=1, pct=True))
    out["sector_rank_63"] = rank.loc[:, [e != benchmark for e in sector]].reindex(columns=columns)
    return out


def sector_trend(
    features: Mapping[str, pd.DataFrame], benchmark: str, etf_of: Mapping[str, str]
) -> dict[str, pd.DataFrame]:
    """The stock's sector ETF's own 12-1 momentum and distance from its 52-week high.

    NaN for a stock with no sector (its ETF is the benchmark) and where the ETF has no column.
    """
    columns = list(features["mom_12_1"].columns)
    sector = [etf_of.get(symbol, benchmark) for symbol in columns]
    has_sector = [etf != benchmark for etf in sector]
    out: dict[str, pd.DataFrame] = {}
    for name in ("mom_12_1", "dist_52w_high"):
        picked = features[name].reindex(columns=sector)
        picked.columns = columns
        picked.loc[:, [not has for has in has_sector]] = np.nan
        out[f"sector_{name}"] = picked
    return out


def forward_excess(
    close: pd.DataFrame, benchmark: str, horizons: Sequence[int] = HORIZONS
) -> dict[int, pd.DataFrame]:
    """The target: each stock's forward return over `h` sessions minus the benchmark's."""
    out: dict[int, pd.DataFrame] = {}
    for h in horizons:
        forward = close.shift(-h) / close - 1
        out[h] = forward.sub(forward[benchmark], axis=0)
    return out


def eligible(traded_close: pd.DataFrame, dollar_volume: pd.DataFrame) -> pd.DataFrame:
    """The screener's gates: a dollar, a million a day (20-day mean) and 60 sessions of history."""
    adv = dollar_volume.rolling(ADV_WINDOW).mean()
    history = traded_close.notna().cumsum()
    return (traded_close >= MIN_PRICE) & (adv >= MIN_DOLLAR_VOLUME) & (history >= MIN_HISTORY_DAYS)
