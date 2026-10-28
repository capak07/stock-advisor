"""The crypto model's data: a weekly row for each of the top coins, judged against BTC.

Coins trade every day, so horizons, windows and the embargo count calendar days. An altcoin's
target is its forward return minus BTC's; BTC's own is minus SPY's, using SPY's last close on or
before each day (spec §5.4). Stablecoins and wrapped coins are left out: their "excess over BTC" is
just BTC's move, inverted. `crypto_frames` is shared by training and the live run.
"""

import json
from pathlib import Path

import pandas as pd

from advisor.model.dataset import MarketData
from advisor.model.features import (
    PRICE_FEATURES,
    Wide,
    forward_excess,
    jump_days,
    price_features,
    to_wide,
)
from advisor.screener import ADV_WINDOW

CRYPTO = "crypto"
BTC = "BTC"
CRYPTO_HORIZONS = (7, 14, 30, 90, 180)
CRYPTO_SAMPLE_EVERY = 7
CRYPTO_WARMUP = 252  # days of closes before a coin's first row (the 12-month momentum look-back)
UNIVERSE = 100  # coins per day, by trailing 30-day dollar volume
VOLUME_WINDOW = 30
PEG_VOL = 0.05  # annualised 60-day volatility under this is a peg, not a market
EXCLUDED = frozenset({
    "USDT", "USDC", "DAI", "PAX", "USDP", "PYUSD", "GUSD", "BUSD", "TUSD", "FDUSD", "EURC",
    "WBTC", "CBBTC", "CBETH", "WETH", "STETH",
})
CRYPTO_FEATURES = PRICE_FEATURES + ["ex_btc_21", "ex_btc_63"]


def crypto_frames(prices: pd.DataFrame) -> tuple[Wide, dict[str, pd.DataFrame], pd.DataFrame]:
    """The coins' wide frames on the days with a BTC close, their features, and USD dollar volume."""
    wide = to_wide(prices)
    calendar = wide.close.index[wide.close[BTC].notna()]
    wide = Wide(*(frame.reindex(calendar) for frame in (wide.open, wide.high, wide.low, wide.close, wide.volume)))
    dollar_volume = wide.close * wide.volume
    features = price_features(wide, dollar_volume, jump_days(wide.close))
    for k in (21, 63):
        ret = features[f"ret_{k}"]
        features[f"ex_btc_{k}"] = ret.sub(ret[BTC], axis=0)
    return wide, {name: features[name] for name in CRYPTO_FEATURES}, dollar_volume


def _universe(close: pd.DataFrame, dollar_volume: pd.DataFrame, vol_60: pd.DataFrame) -> pd.DataFrame:
    """Each day's top coins by trailing dollar volume, among those with a year of closes."""
    ok = close.notna() & (close.notna().cumsum() >= CRYPTO_WARMUP) & (vol_60 >= PEG_VOL)  # a NaN vol fails
    ok.loc[:, [c for c in ok.columns if c in EXCLUDED]] = False
    volume = dollar_volume.rolling(VOLUME_WINDOW).mean().where(ok)
    rank = volume.rank(axis=1, ascending=False, method="first")
    return rank <= UNIVERSE


def load_crypto(data_dir: Path) -> MarketData:
    manifest = json.loads((data_dir / "manifest.json").read_text())
    if "failed" in manifest:
        raise ValueError(f"the training data build failed: {manifest['failed']['error']}")
    end = pd.Timestamp(manifest["end"])
    prices = pd.read_parquet(data_dir / "prices_crypto.parquet")
    prices = prices[pd.to_datetime(prices["day"]) < end]
    wide, features, dollar_volume = crypto_frames(prices)
    calendar = wide.close.index

    targets = forward_excess(wide.close, BTC, CRYPTO_HORIZONS)
    spy = pd.read_parquet(data_dir / "prices_US.parquet")
    spy = spy[spy["symbol"] == "SPY"].assign(day=lambda f: pd.to_datetime(f["day"])).set_index("day")["close"]
    spy = spy.reindex(spy.index.union(calendar)).ffill().reindex(calendar)  # the last close on or before
    for h, target in targets.items():
        btc = wide.close[BTC].shift(-h) / wide.close[BTC] - 1
        target[BTC] = btc - (spy.shift(-h) / spy - 1)

    days = calendar[CRYPTO_WARMUP::CRYPTO_SAMPLE_EVERY]
    frames = {name: frame.loc[days] for name, frame in features.items()}
    frames |= {f"y_{h}": target.loc[days] for h, target in targets.items()}
    frames["dollar_volume_20"] = dollar_volume.rolling(ADV_WINDOW).mean().loc[days]
    stacked = pd.concat({name: frame.stack(future_stack=True) for name, frame in frames.items()}, axis=1)
    stacked.index.names = ["day", "symbol"]
    keep = _universe(wide.close, dollar_volume, features["vol_60"]).loc[days].stack(future_stack=True)
    rows = stacked[keep.reindex(stacked.index, fill_value=False).astype(bool)].reset_index()
    rows["sector"] = None
    columns = ["day", "symbol", "sector", "dollar_volume_20", *(f"y_{h}" for h in CRYPTO_HORIZONS), *CRYPTO_FEATURES]
    return MarketData(CRYPTO, rows[columns].reset_index(drop=True), list(CRYPTO_FEATURES), calendar)
