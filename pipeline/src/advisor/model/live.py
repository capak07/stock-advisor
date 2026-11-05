"""Live features: the training feature step run on a short window of recent bars.

`live_features` calls `feature_frames`, the same code `load_market` trains on, so a stock's live
features equal its training features for the same day (given enough history in the window).
"""

import time
from collections.abc import Callable, Mapping, Sequence
from datetime import date, timedelta

import numpy as np
import pandas as pd

from advisor.collectors.sec_xbrl import FinancialFact
from advisor.collectors.yfinance_bars import LOOKBACK, Downloader
from advisor.markets import MARKETS
from advisor.model.dataset import feature_frames
from advisor.model.features import to_wide
from advisor.model.garch import GarchParams, live_garch_vol
from advisor.models import DailyBar, Market
from advisor.screener import ADV_WINDOW
from advisor.training.prices import download_history, training_download
from advisor.training.sectors import SECTOR_ETFS

VOLUME_FEATURES = ("volume_z", "log_adv20", "amihud_20")
# the window of bars a live run fetches; it must cover the 252-session look-back (see the collector)
LIVE_WINDOW = LOOKBACK
SPLIT_REACH = timedelta(days=3 * 365)  # the split factor reaches back past any filing in use
_BARS = ["symbol", "day", "open", "high", "low", "close", "volume"]
_EVENTS = ["symbol", "day", "dividend", "split"]
_FACTS = ["cik", "metric", "concept", "unit", "start", "end", "value", "filed", "form", "accession"]


def bars_frame(bars: Mapping[str, Sequence[DailyBar]]) -> pd.DataFrame:
    """The training layout (`symbol, day, open, high, low, close, volume`, `day` as a date) from bars."""
    rows = [
        (bar.symbol, bar.day, bar.open, bar.high, bar.low, bar.close, bar.volume)
        for series in bars.values() for bar in series
    ]
    return pd.DataFrame(rows, columns=_BARS)


def facts_frame(facts: Sequence[FinancialFact]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The run's SEC facts as Plan 3a's `(facts, tickers)`; each symbol gets a stable synthetic `cik`.

    The cik is the symbol's position among the sorted symbols: the model only needs a join key.
    """
    ciks = {symbol: np.int32(i) for i, symbol in enumerate(sorted({f.symbol for f in facts}))}
    rows = [(ciks[f.symbol], f.metric, f.concept, f.unit, f.start, f.end, f.value, f.filed, f.form, f.accession)
            for f in facts]
    table = pd.DataFrame(rows, columns=_FACTS)
    table["cik"] = table["cik"].astype("int32")
    tickers = pd.DataFrame({"symbol": list(ciks), "cik": pd.Series(list(ciks.values()), dtype="int32")})
    return table, tickers


def split_events(
    symbols: Sequence[str],
    today: date,
    *,
    download: Downloader = training_download,
    sleep: Callable[[float], None] = time.sleep,
) -> pd.DataFrame:
    """Three years of split and dividend events for `symbols`: what puts SEC figures on today's shares."""
    return download_history(list(symbols), today - SPLIT_REACH, today, download=download, sleep=sleep).events


def _day_row(prices, events, sectors, market, day, facts, tickers, session: pd.Timestamp) -> pd.DataFrame:
    """Every symbol's features and eligibility on `session`, from the bars up to and including it."""
    days = pd.DatetimeIndex([session])
    frames = feature_frames(
        prices[pd.to_datetime(prices["day"]) <= session], events, sectors, market, days,
        facts=facts, tickers=tickers, split_calendar=pd.bdate_range(session - SPLIT_REACH, session),
    )
    out = pd.DataFrame({name: frames.features[name].loc[session] for name in [*frames.names, *frames.extras]})
    out["eligible"] = frames.eligible.loc[session].astype(bool)
    out["dollar_volume_20"] = frames.dollar_volume.rolling(ADV_WINDOW).mean().loc[session]
    return out


def live_garch(
    prices: pd.DataFrame,
    market: Market,
    day: pd.Timestamp,
    params: Mapping[str, GarchParams | None],
    horizons: Sequence[int],
) -> pd.DataFrame:
    """Symbol × `garch_vol_h` on `day` for a garch model (Plan 6d), from the bars up to and including it.

    The closes sit on the market's calendar (its benchmark's bars), as in training, so a live value
    matches the training value on the same day.
    """
    benchmark = MARKETS[market].benchmark
    upto = prices[pd.to_datetime(prices["day"]) <= pd.Timestamp(day)]
    close = to_wide(upto).close
    close = close.loc[close.index[close[benchmark].notna()]]
    symbols = [s for s in close.columns if s in params]
    return live_garch_vol(close[symbols], params, horizons)


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
    Either way a stock without a close on `day` is not eligible.
    """
    benchmark = MARKETS[market].benchmark
    etfs = [benchmark, *SECTOR_ETFS[market].values()]
    events = events if events is not None else pd.DataFrame(columns=_EVENTS)
    day = pd.Timestamp(day)
    # the market's calendar is the benchmark's bars, not any one symbol's latest day
    sessions = pd.to_datetime(prices.loc[prices["symbol"] == benchmark, "day"])
    if not (sessions == day).any():
        raise ValueError(f"no {benchmark} bar for {day:%Y-%m-%d}")
    out = _day_row(prices, events, sectors, market, day, facts, tickers, day)
    if partial_day:
        previous = pd.Timestamp(sessions[sessions < day].max())
        last = _day_row(prices, events, sectors, market, day, facts, tickers, previous).reindex(out.index)
        for name in (*VOLUME_FEATURES, "eligible", "dollar_volume_20"):
            out[name] = last[name]
        out["eligible"] = out["eligible"].fillna(False).astype(bool)
    # a stock with no close on `day` has nothing to score, whatever the previous session said
    on_day = prices.loc[(pd.to_datetime(prices["day"]) == day) & prices["close"].notna(), "symbol"]
    out["eligible"] = out["eligible"] & out.index.isin(set(on_day))
    out = out.drop(index=etfs, errors="ignore")
    label = sectors.drop_duplicates("symbol").set_index("symbol")["sector"]
    out["sector"] = out.index.map(label)
    out.index.name = "symbol"
    return out
