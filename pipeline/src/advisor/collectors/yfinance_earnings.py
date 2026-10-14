"""Earnings report dates, EPS estimates, actuals and surprises via yfinance (source 17, core).

One record per report: past reports carry the actual EPS and the surprise, upcoming ones only
the estimate. Yahoo sometimes lists one report twice (a scheduled and a reported row for the
same day); the reported row wins. Symbols Yahoo doesn't cover (ETFs, unknown tickers) come back
as None and yield no records. Plan 3 derives days to the next report and the last surprise.
"""

import logging
import math
from collections.abc import Callable, Sequence
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd
from pydantic import BaseModel, ConfigDict

from advisor.collectors.base import Cadence, Category, RateLimiter, Scope, collect_per_symbol
from advisor.collectors.yahoo import rate_limited
from advisor.collectors.yfinance_bars import to_yahoo
from advisor.models import ET, AssetType, Market

Loader = Callable[[str], pd.DataFrame | None]
REPORTS = 12  # about three years of quarters plus the next one; Yahoo may send more


class EarningsReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    report_at: datetime  # scheduled or actual report time, in ET
    eps_estimate: float | None = None
    eps_actual: float | None = None  # None until reported
    surprise_pct: float | None = None


def _yahoo_load(yahoo_symbol: str) -> pd.DataFrame | None:
    import yfinance as yf  # imported lazily: slow import, and tests inject a fake

    logging.getLogger("yfinance").setLevel(logging.CRITICAL)  # it logs an ERROR line per 404
    return yf.Ticker(yahoo_symbol).get_earnings_dates(limit=REPORTS)


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def parse_earnings(symbol: str, frame: pd.DataFrame | None) -> list[EarningsReport]:
    """One report per ET date, oldest first; a reported row beats a scheduled one."""
    if frame is None or frame.empty:
        return []
    by_day: dict[date, EarningsReport] = {}
    for stamp, row in frame.iterrows():
        at = pd.Timestamp(stamp)
        if at.tzinfo is None:
            at = at.tz_localize("UTC")
        report = EarningsReport(
            symbol=symbol,
            report_at=at.tz_convert(ET).to_pydatetime(),
            eps_estimate=_number(row.get("EPS Estimate")),
            eps_actual=_number(row.get("Reported EPS")),
            surprise_pct=_number(row.get("Surprise(%)")),
        )
        day = report.report_at.date()
        kept = by_day.get(day)
        if kept is None or (kept.eps_actual is None and report.eps_actual is not None):
            by_day[day] = report
    return sorted(by_day.values(), key=lambda report: report.report_at)


class YFinanceEarnings:
    name = "yfinance_earnings"
    category = Category.FUNDAMENTALS
    core = True  # spec §4.2: the earnings catalyst feeds event risk and the Review badge
    best_effort = True
    cadence = Cadence.DAILY
    asset_types = frozenset({AssetType.STOCK})
    markets = frozenset({Market.US, Market.TSX})
    record_type = EarningsReport
    freshness = timedelta(days=7)
    scope = Scope.SYMBOLS
    canary = ("AAPL", "RY.TO")
    canary_requires_records = True
    max_symbols = None

    def __init__(self, load: Loader | None = None, limiter: RateLimiter | None = None) -> None:
        self._load = load or _yahoo_load
        self._limiter = limiter

    def fetch(self, symbols: Sequence[str], as_of: datetime) -> list[EarningsReport]:
        def one(symbol: str) -> list[EarningsReport]:
            if self._limiter is not None:
                self._limiter.acquire()
            return parse_earnings(symbol, self._load(to_yahoo(symbol)))

        return collect_per_symbol(symbols, one, is_fatal=rate_limited)
