"""Live coin forecasts from the run's Coinbase candles, on the training feature code."""

import math
from collections.abc import Mapping, Sequence
from datetime import date, datetime

import numpy as np
import pandas as pd

from advisor.model.backtest import round_trip_cost
from advisor.model.crypto import BTC, CRYPTO, CRYPTO_FEATURES, CRYPTO_WARMUP, crypto_frames
from advisor.model.train import FinalModel
from advisor.models import DailyBar, PredictionRow
from advisor.screener import ADV_WINDOW

_COLUMNS = ["symbol", "day", "open", "high", "low", "close", "volume"]


def _finished(bars: Mapping[str, Sequence[DailyBar]], as_of: datetime | date) -> dict[str, list[DailyBar]]:
    cutoff = as_of.date() if isinstance(as_of, datetime) else as_of
    return {symbol: [bar for bar in history if bar.day < cutoff] for symbol, history in bars.items()}


def _prices(bars: Mapping[str, Sequence[DailyBar]]) -> pd.DataFrame:
    rows = [
        (symbol, bar.day, bar.open, bar.high, bar.low, bar.close, bar.volume)
        for symbol, history in bars.items()
        for bar in history
    ]
    return pd.DataFrame(rows, columns=_COLUMNS)


def forecast_coins(
    model: FinalModel,
    bars: Mapping[str, Sequence[DailyBar]],
    spy_close: float | None,
    as_of: datetime | date,
) -> tuple[dict[str, list[PredictionRow]], dict[str, str]]:
    """Each coin's forecasts on its last finished day, and why any coin was left out.

    `spy_close` is the latest SPY close. Training uses it only for BTC's target, so the live
    features do not; BTC's benchmark is still SPY.
    """
    del spy_close
    finished = _finished(bars, as_of)
    if not finished.get(BTC):
        return {}, {symbol: "no BTC candles this run" for symbol in finished}

    reasons: dict[str, str] = {}
    for symbol, history in finished.items():
        if not history:
            reasons[symbol] = "no daily candles"
    wide, features, _dollar = crypto_frames(_prices(finished))
    last = wide.close.index[-1]
    counts = wide.close.notna().sum()
    ready = []
    for symbol in finished:
        if symbol in reasons:
            continue
        n = int(counts.get(symbol, 0))
        if n < CRYPTO_WARMUP:
            reasons[symbol] = f"only {n} days of history (needs {CRYPTO_WARMUP})"
            continue
        ready.append(symbol)
    if not ready:
        return {}, reasons

    frame = pd.DataFrame({name: features[name].loc[last] for name in CRYPTO_FEATURES}).reindex(ready)
    present = [name for name in model.features if name in frame.columns]
    finite = frame[present].map(math.isfinite).all(axis=1)
    frame = frame.loc[finite]
    if frame.empty:
        return {}, reasons
    predicted = model.predict(frame).dropna(subset=["q10", "q50", "q90", "p_beat"])
    version = getattr(model, "version", "")
    rows: dict[str, list[PredictionRow]] = {}
    for symbol, row in predicted.iterrows():
        name = str(symbol)
        rows.setdefault(name, []).append(PredictionRow(
            name, int(row["horizon"]), float(row["q10"]), float(row["q50"]), float(row["q90"]),
            float(row["p_beat"]), "SPY" if name == BTC else "BTC", str(version),
        ))
    return rows, reasons


def coin_costs(
    bars: Mapping[str, Sequence[DailyBar]], fee_pct: float, as_of: datetime | date
) -> dict[str, float]:
    """Round-trip cost per coin from its 20-day dollar volume, or nothing without BTC candles."""
    finished = _finished(bars, as_of)
    if not finished.get(BTC):
        return {}
    prices = _prices(finished)
    if prices.empty:
        return {}
    _wide, _features, dollar_volume = crypto_frames(prices)
    last = dollar_volume.index[-1]
    adv = dollar_volume.rolling(ADV_WINDOW).mean().loc[last]
    out = {}
    for symbol, volume in adv.items():
        volume = 0.0 if not math.isfinite(volume) else float(volume)
        out[str(symbol)] = float(round_trip_cost(CRYPTO, np.array([volume]), fee_pct)[0])
    return out
