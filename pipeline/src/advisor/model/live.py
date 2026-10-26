"""Live features: the training feature step run on a short window of recent bars.

`live_features` calls `feature_frames`, the same code `load_market` trains on, so a stock's live
features equal its training features for the same day (given enough history in the window).
"""

from collections.abc import Mapping, Sequence

import pandas as pd

from advisor.collectors.yfinance_bars import LOOKBACK
from advisor.markets import MARKETS
from advisor.model.dataset import feature_frames
from advisor.models import DailyBar, Market
from advisor.training.sectors import SECTOR_ETFS

VOLUME_FEATURES = ("volume_z", "log_adv20")
# the window of bars a live run fetches; it must cover the 252-session look-back (see the collector)
LIVE_WINDOW = LOOKBACK
SPLIT_REACH = pd.Timedelta(days=3 * 365)  # the split factor reaches back past any filing in use
_BARS = ["symbol", "day", "open", "high", "low", "close", "volume"]
_EVENTS = ["symbol", "day", "dividend", "split"]


def bars_frame(bars: Mapping[str, Sequence[DailyBar]]) -> pd.DataFrame:
    """The training layout (`symbol, day, open, high, low, close, volume`, `day` as a date) from bars."""
    rows = [
        (bar.symbol, bar.day, bar.open, bar.high, bar.low, bar.close, bar.volume)
        for series in bars.values() for bar in series
    ]
    return pd.DataFrame(rows, columns=_BARS)


def _day_row(prices, events, sectors, market, day, facts, tickers, session: pd.Timestamp) -> pd.DataFrame:
    """Every symbol's features and eligibility on `session`, from the bars up to and including it."""
    days = pd.DatetimeIndex([session])
    frames = feature_frames(
        prices[pd.to_datetime(prices["day"]) <= session], events, sectors, market, days,
        facts=facts, tickers=tickers, split_calendar=pd.bdate_range(session - SPLIT_REACH, session),
    )
    out = pd.DataFrame({name: frames.features[name].loc[session] for name in frames.names})
    out["eligible"] = frames.eligible.loc[session].astype(bool)
    out["dollar_volume_20"] = frames.dollar_volume.rolling(20).mean().loc[session]
    return out


def live_features(
    prices: pd.DataFrame,
    market: Market,
    day: pd.Timestamp,
    *,
    sectors: pd.DataFrame,
    partial_day: bool,
    events: pd.DataFrame | None = None,
    facts: pd.DataFrame | None = None,
    tickers: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """One row per stock on `day`: the market's features, `eligible`, `dollar_volume_20` and `sector`.

    With `partial_day` today's bar is incomplete (its volume is partway through the session), so the
    volume features and eligibility come from the previous session; prices still use today's bar.
    """
    benchmark = MARKETS[market].benchmark
    etfs = [benchmark, *SECTOR_ETFS[market].values()]
    events = events if events is not None else pd.DataFrame(columns=_EVENTS)
    day = pd.Timestamp(day)
    out = _day_row(prices, events, sectors, market, day, facts, tickers, day)
    if partial_day:
        before = pd.to_datetime(prices["day"]) < day
        previous = pd.Timestamp(pd.to_datetime(prices.loc[before, "day"]).max())
        last = _day_row(prices, events, sectors, market, day, facts, tickers, previous).reindex(out.index)
        for name in (*VOLUME_FEATURES, "eligible", "dollar_volume_20"):
            out[name] = last[name]
        out["eligible"] = out["eligible"].fillna(False).astype(bool)
    out = out.drop(index=etfs, errors="ignore")
    label = sectors.drop_duplicates("symbol").set_index("symbol")["sector"]
    out["sector"] = out.index.map(label)
    out.index.name = "symbol"
    return out
