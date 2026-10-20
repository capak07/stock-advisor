"""Eight years of daily bars from Yahoo, as one long table for the stock model to train on.

The whole history is downloaded again each week, never topped up: Yahoo rescales old closes after
every split and dividend, so yesterday's stored bars would no longer line up with today's.
Bars are adjusted (auto_adjust), so returns computed from them are total returns.
yf.download never raises when Yahoo blocks it, it returns empty frames, so several empty
downloads in a row mean throttling and the remaining ones are not sent.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

from advisor.collectors.base import check_deadline
from advisor.collectors.yfinance_bars import (
    MAX_CONSECUTIVE_EMPTY,
    SYMBOLS_PER_DOWNLOAD,
    Downloader,
    to_yahoo,
    yahoo_download,
)

HISTORY_YEARS = 8
PAUSE_SECONDS = 3.0
PRICE_COLUMNS = ["open", "high", "low", "close"]
COLUMNS = ["symbol", "day", *PRICE_COLUMNS, "volume"]


class YahooThrottled(Exception):
    """Several downloads in a row came back empty: Yahoo is blocking or rate-limiting us."""


@dataclass(frozen=True)
class PriceHistory:
    bars: pd.DataFrame
    missing: list[str]  # requested symbols that came back without a single bar


def history_start(today: date, years: int = HISTORY_YEARS) -> date:
    return today - timedelta(days=round(years * 365.25))


def _empty() -> pd.DataFrame:
    return pd.DataFrame({
        "symbol": pd.Series([], dtype="string"),
        "day": pd.Series([], dtype="object"),
        **{c: pd.Series([], dtype="float32") for c in PRICE_COLUMNS},
        "volume": pd.Series([], dtype="int64"),
    })[COLUMNS]


def bars_frame(frame: pd.DataFrame | None, yahoo_to_symbol: dict[str, str]) -> pd.DataFrame:
    """yf.download's wide (ticker, field) frame as long rows: one per symbol and trading day."""
    if frame is None or frame.empty:
        return _empty()
    if not isinstance(frame.columns, pd.MultiIndex):
        (only,) = yahoo_to_symbol  # yfinance returns flat columns for a single ticker
        frame = pd.concat({only: frame}, axis=1)
    long = frame.stack(level=0, future_stack=True)
    long.index.names = ["day", "ticker"]
    long = long.reset_index()
    long["symbol"] = long["ticker"].map(yahoo_to_symbol)
    long = long.rename(columns=str.lower)
    prices = long[PRICE_COLUMNS]
    keep = long["symbol"].notna() & prices.notna().all(axis=1) & (prices > 0).all(axis=1)
    long = long[keep]
    if long.empty:
        return _empty()
    out = pd.DataFrame({
        "symbol": long["symbol"].astype("string"),
        "day": [stamp.date() for stamp in pd.to_datetime(long["day"])],
        **{c: long[c].astype("float32") for c in PRICE_COLUMNS},
        "volume": long["volume"].fillna(0).clip(lower=0).astype("int64"),
    })
    return out.sort_values(["symbol", "day"], ignore_index=True)[COLUMNS]


def download_history(
    symbols: list[str],
    start: date,
    end: date,
    *,
    download: Downloader = yahoo_download,
    sleep: Callable[[float], None] = time.sleep,
    pause: float = PAUSE_SECONDS,
) -> PriceHistory:
    unique = list(dict.fromkeys(symbols))
    chunks = [unique[i : i + SYMBOLS_PER_DOWNLOAD] for i in range(0, len(unique), SYMBOLS_PER_DOWNLOAD)]
    frames: list[pd.DataFrame] = []
    streak = 0
    for index, chunk in enumerate(chunks):
        if index:
            check_deadline()
            sleep(pause)
        mapping = {to_yahoo(s): s for s in chunk}
        # yfinance's end is exclusive, so ask for the day after
        got = bars_frame(download(list(mapping), start, end + timedelta(days=1)), mapping)
        if got.empty:
            streak += 1
            if streak >= MAX_CONSECUTIVE_EMPTY:
                raise YahooThrottled(f"{streak} Yahoo downloads in a row came back empty")
        else:
            streak = 0
            frames.append(got)
    bars = pd.concat(frames, ignore_index=True) if frames else _empty()
    have = set(bars["symbol"])
    return PriceHistory(bars=bars, missing=[s for s in unique if s not in have])
