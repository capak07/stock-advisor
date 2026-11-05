"""One market's training rows: a stock-day row per eligible stock on every tenth session.

Reads Plan 3a's weekly Parquet files. Every feature uses only bars up to its day; the targets
(`y_{h}`) look ahead and are NaN near the end of the history.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from advisor.markets import MARKETS
from advisor.model.factors import (
    FACTORS,
    FactorFrames,
    join_factor_columns,
    make_factors,
    stock_characteristics,
)
from advisor.model.features import (
    EXTRA_FEATURES,
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
    sector_trend,
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
    market: Market | str  # "crypto" for the coin model
    rows: pd.DataFrame
    features: list[str]
    calendar: pd.DatetimeIndex
    factors: FactorFrames | None = None
    extras: tuple[str, ...] = ()  # columns on the rows beyond `features`, for configs that name them
    # daily log returns of the close on `calendar`, one column per symbol with rows (Plan 6d's GARCH)
    returns: pd.DataFrame | None = None
    # a fold start -> each symbol's GARCH parameters fitted before it, shared by the variants and folds
    # that run on this data (spec §4: fitted once per asset per training fold)
    garch_cache: dict = field(default_factory=dict, compare=False, repr=False)


def log_returns(close: pd.DataFrame, symbols) -> pd.DataFrame:
    """Daily log returns of the close for `symbols`, in sorted order: the series GARCH is fitted on.

    The same definition as `vol_60`'s returns, so the two volatilities read the same moves.
    """
    columns = sorted(set(symbols))
    close = close[columns]
    return np.log(close / close.shift(1))


@dataclass(frozen=True)
class FeatureFrames:
    wide: Wide
    calendar: pd.DatetimeIndex
    names: list[str]
    extras: list[str]
    features: dict[str, pd.DataFrame]  # full calendar for price and RS features, `days` for fundamentals
    dollar_volume: pd.DataFrame
    eligible: pd.DataFrame


def feature_frames(
    prices: pd.DataFrame,
    events: pd.DataFrame,
    sectors: pd.DataFrame,
    market: Market,
    days: pd.DatetimeIndex,
    *,
    facts: pd.DataFrame | None = None,
    tickers: pd.DataFrame | None = None,
    split_calendar: pd.DatetimeIndex | None = None,
) -> FeatureFrames:
    """The one feature step shared by training and live runs, so their features cannot drift apart.

    `prices` is Plan 3a's long layout. `split_calendar` is the calendar the daily split factor is
    built on for the fundamentals; it must reach back past any filing in use (default: the days
    with a benchmark close).
    """
    benchmark = MARKETS[market].benchmark
    etfs = sorted(SECTOR_ETFS[market].values())
    wide = to_wide(prices)
    # a day only some symbols have would blank their rolling windows
    calendar = wide.close.index[wide.close[benchmark].notna()]
    wide = Wide(*(frame.reindex(calendar) for frame in (wide.open, wide.high, wide.low, wide.close, wide.volume)))
    split_adjusted, traded = as_traded(wide, events)
    dollar_volume = split_adjusted * wide.volume

    features = price_features(wide, dollar_volume, jump_days(wide.close))
    etf_of = {row.symbol: sector_etf(market, row.sector) for row in sectors.itertuples()}
    features |= relative_strength(features, benchmark, etf_of, etfs)
    features |= sector_trend(features, benchmark, etf_of)
    names = PRICE_FEATURES + RS_FEATURES
    if market == Market.US:
        splits = split_factor(calendar if split_calendar is None else split_calendar, list(wide.close.columns), events)
        # the daily factor, for symbols that split: a shares or EPS date falls between sample days
        splits = splits.loc[:, splits.ne(1).any()]
        features |= fundamental_features(facts, tickers, days, split_adjusted.loc[days], splits)
        names = names + FUNDAMENTAL_FEATURES
    return FeatureFrames(wide, calendar, names, list(EXTRA_FEATURES), features, dollar_volume, eligible(traded, dollar_volume))


def load_market(data_dir: Path, market: Market, with_factors: bool = False, with_garch: bool = False) -> MarketData:
    benchmark = MARKETS[market].benchmark
    etfs = sorted(SECTOR_ETFS[market].values())
    # the build ran during its last session, so that day's bar is partial
    manifest = json.loads((data_dir / "manifest.json").read_text())
    if "failed" in manifest:  # its files are partial, or left over from an earlier build
        raise ValueError(f"the training data build failed: {manifest['failed']['error']}")
    end = pd.Timestamp(manifest["end"])
    prices = pd.read_parquet(data_dir / f"prices_{market}.parquet")
    prices = prices[pd.to_datetime(prices["day"]) < end]
    events = pd.read_parquet(data_dir / f"events_{market}.parquet")
    sectors = pd.read_parquet(data_dir / "sectors.parquet")
    facts = pd.read_parquet(data_dir / "fundamentals.parquet") if market == Market.US else None
    tickers = pd.read_parquet(data_dir / "tickers.parquet") if market == Market.US else None

    # the calendar is the days with a benchmark close; the sample days come from it
    bench = prices[(prices["symbol"] == benchmark) & prices["close"].notna()]
    days = pd.DatetimeIndex(sorted(pd.to_datetime(bench["day"]).unique()))[WARMUP::SAMPLE_EVERY]
    built = feature_frames(prices, events, sectors, market, days, facts=facts, tickers=tickers)
    wide, calendar, names, dollar_volume = built.wide, built.calendar, built.names, built.dollar_volume

    extras = built.extras
    frames = {name: built.features[name].loc[days] for name in [*names, *extras]}
    frames |= {f"y_{h}": target.loc[days] for h, target in forward_excess(wide.close, benchmark).items()}
    frames["dollar_volume_20"] = dollar_volume.rolling(ADV_WINDOW).mean().loc[days]
    stacked = pd.concat({name: frame.stack(future_stack=True) for name, frame in frames.items()}, axis=1)
    stacked.index.names = ["day", "symbol"]
    keep = built.eligible.loc[days].stack(future_stack=True)
    keep = keep.reindex(stacked.index, fill_value=False).astype(bool)
    rows = stacked[keep].reset_index()
    rows = rows[~rows["symbol"].isin([benchmark, *etfs])]
    label = sectors.drop_duplicates("symbol").set_index("symbol")["sector"]
    rows["sector"] = rows["symbol"].map(label)
    columns = ["day", "symbol", "sector", "dollar_volume_20", *(f"y_{h}" for h in HORIZONS), *names, *extras]
    factors = None
    if with_factors:
        universe = built.eligible.copy()
        for symbol in (benchmark, *etfs):
            if symbol in universe.columns:
                universe[symbol] = False
        factors, betas = make_factors(
            wide.close, stock_characteristics(market, built.features, universe), universe,
            benchmark, days, HORIZONS, FACTORS[market],
        )
    rows = rows[columns].reset_index(drop=True)
    if factors is not None:
        rows = join_factor_columns(rows, betas, factors)
    returns = log_returns(wide.close, rows["symbol"].unique()) if with_garch else None
    del built, wide, dollar_volume, frames, stacked  # the full-calendar frames are large
    return MarketData(market, rows, names, calendar, factors, tuple(extras), returns)
