"""Simulate a policy's book day by day: entries on sampled days, exits on daily closes.

Entries follow the pick rules with the policy's lines; exits are the first of the stop, the
trailing stop (which only rises), the exit-by session, a re-forecast at the sell line, or the end
of the period. Costs come off once, on the exit day. Nothing dated on or after `end` is read, so a
period that ends where a later one begins can't see it.
"""

import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from advisor.markets import MARKETS
from advisor.model.backtest import PER_SECTOR, PICKS_PER_STYLE, SWING_HORIZONS, round_trip_cost
from advisor.model.features import _wilder, to_wide, true_range
from advisor.models import Market
from advisor.policy import Policy
from advisor.recommend.picks import POSITION_MAX_DROP

TRADE_COLUMNS = [
    "symbol", "entry_day", "exit_day", "horizon", "style", "p", "entry", "exit", "reason", "cost", "net", "beat",
]


@dataclass(frozen=True)
class DailyPanel:
    close: pd.DataFrame  # sessions x symbols: the closes the training targets are measured on
    atr_pct: pd.DataFrame  # the same shape: the `atr_14_pct` feature
    benchmark: str


@dataclass(frozen=True)
class Book:
    trades: pd.DataFrame
    daily: pd.Series  # the equal-weight book's return on every session of the period


def daily_panel(data_dir: Path, market: Market) -> DailyPanel:
    """The market's daily closes and ATR, on the benchmark's sessions, as `load_market` sees them."""
    benchmark = MARKETS[market].benchmark
    end = pd.Timestamp(json.loads((data_dir / "manifest.json").read_text())["end"])
    prices = pd.read_parquet(data_dir / f"prices_{market}.parquet")
    prices = prices[pd.to_datetime(prices["day"]) < end]  # the build's last bar is partial
    wide = to_wide(prices)
    calendar = wide.close.index[wide.close[benchmark].notna()]
    close, high, low = (f.reindex(calendar) for f in (wide.close, wide.high, wide.low))
    atr = _wilder(true_range(type(wide)(wide.open.reindex(calendar), high, low, close, wide.volume.reindex(calendar))), 14) / close
    return DailyPanel(close, atr, benchmark)


@dataclass
class _Open:
    entry_i: int
    entry: float
    bench_entry: float
    stop: float
    trail: float
    high: float
    horizon: int
    style: str
    p: float
    cost: float


def _candidates(rows: pd.DataFrame, policy: Policy, market: Market, fee: float) -> pd.DataFrame:
    df = rows.copy()
    df["cost"] = round_trip_cost(market, df["dollar_volume_20"].to_numpy(), fee)
    width = df["q90"] - df["q10"]
    ok = (df["p"] >= policy.p_buy) & (df["q50"] > df["cost"]) & (width > 0)
    if policy.horizons is not None:
        ok &= df["horizon"].isin(policy.horizons)
    if "jump_5d" in df:
        ok &= df["jump_5d"].fillna(0) != 1
    df = df[ok].copy()
    df["key"] = df["p"] if policy.rule == "p" else df["q50"] / (df["q90"] - df["q10"])
    # each symbol's best row; a tie goes to the shorter horizon
    df = df.sort_values(["symbol", "key", "horizon"], ascending=[True, False, True]).drop_duplicates("symbol")
    df["style"] = np.where(df["horizon"].isin(SWING_HORIZONS), "swing", "position")
    return df.sort_values(["style", "key", "symbol"], ascending=[True, False, True])


def simulate_book(
    pred: pd.DataFrame,
    panel: DailyPanel,
    policy: Policy,
    market: Market,
    usd_fx_fee_pct: float,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> Book:
    close = panel.close.ffill()
    in_period = (close.index >= start) & (close.index < end)
    sessions = close.index[in_period]
    position = {day: i for i, day in enumerate(close.index)}
    values, atr = close.to_numpy(), panel.atr_pct.to_numpy()
    col = {symbol: j for j, symbol in enumerate(close.columns)}
    bench = col[panel.benchmark]

    if pred.empty:
        pred = pd.DataFrame(columns=["day", "symbol", "horizon", "p"])
    pred = pred[pred["p"].notna() & pred["day"].isin(sessions) & pred["symbol"].isin(col)]
    by_day = {day: g for day, g in pred.groupby("day", sort=True)}
    sell_p = {(r.day, r.symbol, r.horizon): r.p for r in pred[["day", "symbol", "horizon", "p"]].itertuples()}

    held: dict[str, _Open] = {}
    trades, daily = [], []
    last = len(sessions) - 1
    for t, day in enumerate(sessions):
        i = position[day]
        returns, exited = [], set()
        for symbol in sorted(held):
            s, j = held[symbol], col[symbol]
            c = values[i, j]
            r = c / values[i - 1, j] - 1
            reason = None
            if c <= s.stop:
                reason = "stop"
            elif c <= s.trail:
                reason = "trail"
            elif i - s.entry_i >= s.horizon:
                reason = "exit_by"
            elif sell_p.get((day, symbol, s.horizon), math.inf) <= policy.p_sell:
                reason = "sell"
            elif t == last:
                reason = "end"
            if reason is None:
                s.high = max(s.high, c)
                if not math.isnan(atr[i, j]):
                    s.trail = max(s.trail, s.high - policy.trail_atr * atr[i, j] * c)
            else:
                r -= s.cost
                gain = c / s.entry - 1
                trades.append([
                    symbol, close.index[s.entry_i], day, s.horizon, s.style, s.p, s.entry, c, reason, s.cost,
                    gain - s.cost, c / s.entry > values[i, bench] / s.bench_entry,
                ])
                del held[symbol]
                exited.add(symbol)
            returns.append(r)
        daily.append(float(np.mean(returns)) if returns else 0.0)

        if day not in by_day or t == last:  # a position entered on the last session would close at once
            continue
        kept: dict[str, int] = {}
        per_group: dict[tuple[str, str], int] = {}
        for c in _candidates(by_day[day], policy, market, usd_fx_fee_pct).itertuples():
            j = col[c.symbol]
            entry, a = values[i, j], atr[i, j]
            if c.symbol in held or c.symbol in exited or math.isnan(entry) or math.isnan(a):
                continue
            group = (c.style, c.sector if isinstance(c.sector, str) else f"unlabelled:{c.symbol}")
            if kept.get(c.style, 0) >= PICKS_PER_STYLE or per_group.get(group, 0) >= PER_SECTOR:
                continue
            kept[c.style] = kept.get(c.style, 0) + 1
            per_group[group] = per_group.get(group, 0) + 1
            if c.style == "swing":
                stop = entry * (1 - policy.swing_atr * a)
            else:
                stop = max(entry * (1 - policy.position_atr * a), entry * (1 - POSITION_MAX_DROP))
            held[c.symbol] = _Open(i, entry, values[i, bench], stop, stop, entry, int(c.horizon), c.style, float(c.p),
                                   float(c.cost))
    return Book(pd.DataFrame(trades, columns=TRADE_COLUMNS), pd.Series(daily, index=sessions, dtype=float))


def book_metrics(book: Book) -> dict:
    trades, daily = book.trades, book.daily
    n = len(trades)
    months = daily.index.to_period("M").nunique() if len(daily) else 0
    cumulative = (1 + daily).cumprod()
    drawdown = float((1 - cumulative / cumulative.cummax()).max()) if len(daily) else 0.0
    std = float(daily.std()) if len(daily) > 1 else 0.0
    sharpe = math.sqrt(252) * float(daily.mean()) / std if n and std > 0 else math.nan
    out = {
        "trades": n, "trades_per_month": n / months if months else math.nan,
        "sharpe": sharpe, "max_drawdown": drawdown,
        "mean_net_pct": None, "hit_rate_net": None, "beat_rate": None, "mean_p": None, "claimed_gap_pts": None,
    }
    if n:
        mean_p, beat = float(trades["p"].mean()), float(trades["beat"].mean())
        out |= {
            "mean_net_pct": float(trades["net"].mean() * 100), "hit_rate_net": float((trades["net"] > 0).mean()),
            "beat_rate": beat, "mean_p": mean_p, "claimed_gap_pts": abs(mean_p - beat) * 100,
        }
    return out
