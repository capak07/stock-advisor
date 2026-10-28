"""Synthetic training data in Plan 3a's file layout, for the model tests.

Each stock moves with the benchmark plus its own constant daily drift (drawn with sd 0.0012 ×
`signal`) and its own noise. Sharing the benchmark's moves keeps excess returns independent across
stocks, as in a real market, so past returns predict future excess returns when `signal` > 0 and
nothing does when it is 0.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

from advisor.markets import MARKETS
from advisor.models import Market
from advisor.training.sectors import SECTOR_ETFS

STOCK_NOISE = 0.015  # sd of each stock's own daily log return, on top of the benchmark's


def _bars(symbol: str, closes: np.ndarray, days: pd.DatetimeIndex) -> pd.DataFrame:
    return pd.DataFrame({
        "symbol": symbol, "day": [d.date() for d in days], "open": closes, "high": closes * 1.01,
        "low": closes * 0.99, "close": closes, "volume": 1_000_000.0,
    })


def write_market(out: Path, market: Market, stocks: int = 40, days: int = 2340, seed: int = 7,
                 signal: float = 1.0, penny: bool = False) -> list[str]:
    out.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    calendar = pd.bdate_range("2017-01-02", periods=days, name="day")
    suffix = ".TO" if market == Market.TSX else ""
    sectors = list(SECTOR_ETFS[market])[:2]
    symbols = [f"Q{chr(65 + i // 26)}{chr(65 + i % 26)}{suffix}" for i in range(stocks)]

    def walk(drift: float | np.ndarray, noise: float = 0.02) -> np.ndarray:
        return 50 * np.exp(np.cumsum(drift + rng.normal(0, noise, days)))

    moves = 0.0003 + rng.normal(0, 0.02, days)  # the benchmark's daily log returns
    frames = [_bars(MARKETS[market].benchmark, 50 * np.exp(np.cumsum(moves)), calendar)]
    frames += [_bars(etf, walk(0.0003), calendar) for etf in SECTOR_ETFS[market].values()]
    frames += [_bars(s, walk(moves + rng.normal(0, 0.0012 * signal), STOCK_NOISE), calendar) for s in symbols]
    labels = [(s, sectors[i % 2], "Industry") for i, s in enumerate(symbols)]
    if penny:
        frames.append(_bars(f"QZZ{suffix}", np.full(days, 0.5), calendar))
        labels.append((f"QZZ{suffix}", sectors[0], "Industry"))
    pd.concat(frames).to_parquet(out / f"prices_{market}.parquet", index=False)
    pd.DataFrame({"symbol": [], "day": [], "dividend": [], "split": []}).to_parquet(out / f"events_{market}.parquet", index=False)
    pd.DataFrame(labels, columns=["symbol", "sector", "industry"]).to_parquet(out / "sectors.parquet", index=False)
    if market == Market.US:
        pd.DataFrame(columns=["cik", "metric", "concept", "unit", "start", "end", "value", "filed", "form", "accession"]
                     ).to_parquet(out / "fundamentals.parquet", index=False)
        pd.DataFrame({"symbol": pd.Series([], dtype=str), "cik": pd.Series([], dtype="int32")}).to_parquet(out / "tickers.parquet", index=False)
    # built during the last day's session: its bar is partial and must be left out
    (out / "manifest.json").write_text(json.dumps({"end": calendar[-1].date().isoformat()}))
    return symbols


CRYPTO_START = pd.Timestamp("2020-01-04")  # a Saturday: every crypto row falls on one


def _coin_bars(symbol, days, close, volume):
    close = np.asarray(close, float)
    return pd.DataFrame({"symbol": symbol, "day": [d.date() for d in days], "open": close, "high": close * 1.01,
                         "low": close * 0.99, "close": close, "volume": volume})


def write_crypto(tmp, coins=6, days=600, seed=1):
    rng = np.random.default_rng(seed)
    cal = pd.date_range(CRYPTO_START, periods=days)
    walk = lambda sd: np.exp(np.cumsum(rng.normal(0, sd, days)))  # noqa: E731
    frames = [_coin_bars("BTC", cal, 100 * walk(0.03), 1e6)]
    frames += [_coin_bars(f"C{i:03d}", cal, 10 * walk(0.04), 1e5 * (i + 1)) for i in range(coins)]
    frames += [_coin_bars("USDT", cal, np.ones(days), 1e9), _coin_bars("FLAT", cal, np.full(days, 5.0), 1e9)]
    frames.append(_coin_bars("YOUNG", cal[-200:], 3 * walk(0.04)[-200:], 1e9))
    pd.concat(frames).to_parquet(tmp / "prices_crypto.parquet", index=False)
    weekdays = cal[cal.dayofweek < 5]
    spy = 400 * np.exp(np.cumsum(rng.normal(0, 0.01, len(weekdays))))
    _coin_bars("SPY", weekdays, spy, 1e7).to_parquet(tmp / "prices_US.parquet", index=False)
    (tmp / "manifest.json").write_text(json.dumps({"end": (cal[-1] + pd.Timedelta(days=1)).date().isoformat()}))
    return pd.concat(frames), _coin_bars("SPY", weekdays, spy, 1e7)
