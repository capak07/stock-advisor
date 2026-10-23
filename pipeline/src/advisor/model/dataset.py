"""One market's training rows: a stock-day row per eligible stock on every tenth session.

Reads Plan 3a's weekly Parquet files. Every feature uses only bars up to its day; the targets
(`y_{h}`) look ahead and are NaN near the end of the history.
"""

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from advisor.markets import MARKETS
from advisor.model.features import (
    HORIZONS,
    PRICE_FEATURES,
    RS_FEATURES,
    Wide,
    as_traded,
    eligible,
    forward_excess,
    jump_days,
    price_features,
    relative_strength,
    split_factor,
    to_wide,
)
from advisor.model.fundamentals import FUNDAMENTAL_FEATURES, fundamental_features
from advisor.models import Market
from advisor.screener import ADV_WINDOW
from advisor.training.sectors import SECTOR_ETFS, sector_etf

SAMPLE_EVERY = 10
WARMUP = 252  # sessions a stock needs before its first row (the 12-month momentum look-back)


@dataclass(frozen=True)
class MarketData:
    market: Market
    rows: pd.DataFrame
    features: list[str]
    calendar: pd.DatetimeIndex


def load_market(data_dir: Path, market: Market) -> MarketData:
    benchmark = MARKETS[market].benchmark
    etfs = sorted(SECTOR_ETFS[market].values())
    # the build ran during its last session, so that day's bar is partial
    end = pd.Timestamp(json.loads((data_dir / "manifest.json").read_text())["end"])
    prices = pd.read_parquet(data_dir / f"prices_{market}.parquet")
    prices = prices[pd.to_datetime(prices["day"]) < end]
    events = pd.read_parquet(data_dir / f"events_{market}.parquet")
    sectors = pd.read_parquet(data_dir / "sectors.parquet")

    wide = to_wide(prices)
    # a day only some symbols have would blank their rolling windows
    calendar = wide.close.index[wide.close[benchmark].notna()]
    wide = Wide(*(frame.reindex(calendar) for frame in (wide.open, wide.high, wide.low, wide.close, wide.volume)))
    split_adjusted, traded = as_traded(wide, events)
    dollar_volume = split_adjusted * wide.volume
    days = calendar[WARMUP::SAMPLE_EVERY]

    features = price_features(wide, dollar_volume, jump_days(wide.close))
    etf_of = {row.symbol: sector_etf(market, row.sector) for row in sectors.itertuples()}
    features |= relative_strength(features, benchmark, etf_of, etfs)
    names = PRICE_FEATURES + RS_FEATURES
    if market == Market.US:
        facts = pd.read_parquet(data_dir / "fundamentals.parquet")
        tickers = pd.read_parquet(data_dir / "tickers.parquet")
        splits = split_factor(calendar, list(wide.close.columns), events)
        features |= fundamental_features(facts, tickers, days, split_adjusted.loc[days], splits.loc[days])
        names = names + FUNDAMENTAL_FEATURES

    frames = {name: features[name].loc[days] for name in names}
    frames |= {f"y_{h}": target.loc[days] for h, target in forward_excess(wide.close, benchmark).items()}
    frames["dollar_volume_20"] = dollar_volume.rolling(ADV_WINDOW).mean().loc[days]
    stacked = pd.concat({name: frame.stack(future_stack=True) for name, frame in frames.items()}, axis=1)
    stacked.index.names = ["day", "symbol"]
    keep = eligible(traded, dollar_volume).loc[days].stack(future_stack=True)
    keep = keep.reindex(stacked.index, fill_value=False).astype(bool)
    rows = stacked[keep].reset_index()
    rows = rows[~rows["symbol"].isin([benchmark, *etfs])]
    label = sectors.drop_duplicates("symbol").set_index("symbol")["sector"]
    rows["sector"] = rows["symbol"].map(label)
    columns = ["day", "symbol", "sector", "dollar_volume_20", *(f"y_{h}" for h in HORIZONS), *names]
    return MarketData(market, rows[columns].reset_index(drop=True), names, calendar)
