"""Daily bars from Yahoo Finance via yfinance (source 3): fallback and cross-check for Alpaca."""

from collections.abc import Callable, Sequence
from datetime import date, datetime, timedelta

import pandas as pd

from advisor.collectors.base import Cadence, Category
from advisor.models import ET, AssetType, DailyBar

Downloader = Callable[[list[str], date, date], pd.DataFrame]
SYMBOLS_PER_DOWNLOAD = 100
LOOKBACK = timedelta(days=100)


def to_yahoo(symbol: str) -> str:
    return symbol.replace(".", "-")


def _yahoo_download(tickers: list[str], start: date, end: date) -> pd.DataFrame:
    import yfinance as yf  # imported lazily: slow import, and tests inject a fake

    return yf.download(
        tickers=tickers,
        start=start.isoformat(),
        end=end.isoformat(),
        group_by="ticker",
        auto_adjust=True,
        threads=True,
        progress=False,
    )


def parse_frame(frame: pd.DataFrame | None, yahoo_to_symbol: dict[str, str]) -> list[DailyBar]:
    if frame is None or frame.empty:
        return []
    if not isinstance(frame.columns, pd.MultiIndex):
        (only,) = yahoo_to_symbol  # yfinance returns flat columns for a single ticker
        frame = pd.concat({only: frame}, axis=1)
    bars: list[DailyBar] = []
    for ticker in frame.columns.get_level_values(0).unique():
        symbol = yahoo_to_symbol.get(ticker)
        if symbol is None:
            continue
        for stamp, row in frame[ticker].dropna(subset=["Close"]).iterrows():
            try:
                bars.append(DailyBar(
                    symbol=symbol,
                    day=stamp.date(),
                    open=float(row["Open"]),
                    high=float(row["High"]),
                    low=float(row["Low"]),
                    close=float(row["Close"]),
                    volume=float(row["Volume"]),
                    source="yfinance",
                ))
            except ValueError:  # NaN or non-positive fields fail validation
                continue
    return bars


class YFinanceBars:
    name = "yfinance_bars"
    category = Category.PRICES
    core = False
    best_effort = True
    cadence = Cadence.PER_RUN
    asset_types = frozenset({AssetType.STOCK})
    record_type = DailyBar
    freshness = None

    def __init__(self, download: Downloader | None = None) -> None:
        self._download = download or _yahoo_download

    def fetch(self, symbols: Sequence[str], as_of: datetime) -> list[DailyBar]:
        unique = sorted(set(symbols))
        start = (as_of - LOOKBACK).astimezone(ET).date()
        end = as_of.astimezone(ET).date() + timedelta(days=1)
        bars: list[DailyBar] = []
        for i in range(0, len(unique), SYMBOLS_PER_DOWNLOAD):
            mapping = {to_yahoo(s): s for s in unique[i : i + SYMBOLS_PER_DOWNLOAD]}
            bars.extend(parse_frame(self._download(list(mapping), start, end), mapping))
        return bars
