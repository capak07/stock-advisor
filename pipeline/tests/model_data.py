"""Synthetic training data in Plan 3a's file layout, for the model tests.

Each stock drifts at its own constant daily rate (drawn with sd 0.0012 × `signal`) plus noise, so
past returns predict future excess returns when `signal` > 0 and nothing does when it is 0.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

from advisor.markets import MARKETS
from advisor.models import Market
from advisor.training.sectors import SECTOR_ETFS


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

    def walk(drift: float) -> np.ndarray:
        return 50 * np.exp(np.cumsum(drift + rng.normal(0, 0.02, days)))

    frames = [_bars(MARKETS[market].benchmark, walk(0.0003), calendar)]
    frames += [_bars(etf, walk(0.0003), calendar) for etf in SECTOR_ETFS[market].values()]
    frames += [_bars(s, walk(rng.normal(0, 0.0012 * signal)), calendar) for s in symbols]
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
