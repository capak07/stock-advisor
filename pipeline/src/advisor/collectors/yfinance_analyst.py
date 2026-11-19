"""Analyst price targets, recommendation counts and rating changes via yfinance (source 16).

yfinance has no batch API for these, so the collector goes symbol by symbol through the shared
Yahoo limiter. A symbol Yahoo doesn't cover comes back empty and yields no record. The source
is capped per call (spec §7.2): holdings come first and the rest wait for a later run.

A view also keeps the rating changes the model's analyst features read (`model.analyst`): those of
the last EVENT_DAYS days plus the latest downgrade before them (days since a downgrade is capped at a
year), and the oldest change and the count of Yahoo's whole list, which say whether Yahoo's capped list
still covers a window (Ruling R3, F19).
"""

import logging
import math
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pandas as pd
from pydantic import BaseModel, ConfigDict

from advisor.collectors.base import Cadence, Category, RateLimiter, Scope
from advisor.collectors.yahoo import collect_yahoo
from advisor.collectors.yfinance_bars import to_yahoo
from advisor.model.analyst import DOWNGRADE_CAP
from advisor.models import ET, AssetType, Market

TickerData = tuple[dict, pd.DataFrame, pd.DataFrame]  # price targets, recommendations, rating changes
Loader = Callable[[str], TickerData]
EVENT_DAYS = DOWNGRADE_CAP  # the rating changes a view keeps: the analyst features' longest reach (365 days)
# Yahoo's upgrades_downgrades columns -> RatingEvent fields (the same as the training history's)
_EVENT_FIELDS = {
    "Firm": "firm", "Action": "action", "FromGrade": "from_grade", "ToGrade": "to_grade",
    "priceTargetAction": "price_target_action",
}


class RatingEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    graded_at: datetime  # naive UTC, as Yahoo stamps it
    firm: str | None = None
    action: str | None = None  # "up", "down", "main", "init", "reit"
    from_grade: str | None = None
    to_grade: str | None = None
    price_target_action: str | None = None  # "Raises", "Lowers", ...


class AnalystView(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    as_of: date  # ET date the view was fetched
    target_mean: float | None = None
    target_low: float | None = None
    target_high: float | None = None
    target_median: float | None = None
    rec_strong_buy: int | None = None
    rec_buy: int | None = None
    rec_hold: int | None = None
    rec_sell: int | None = None
    rec_strong_sell: int | None = None
    upgrades_30d: int = 0
    downgrades_30d: int = 0
    upgrades_90d: int = 0
    downgrades_90d: int = 0
    target_raises_30d: int = 0
    target_lowers_30d: int = 0
    # the model's rating history: a view cached before these fields existed has none, so the
    # symbol's analyst features read missing until the next fetch
    events: list[RatingEvent] = []
    oldest_event: datetime | None = None  # naive UTC, as `graded_at`: the oldest change Yahoo lists
    event_count: int = 0  # the changes Yahoo lists


def _quietly(read: Callable[[], Any], empty: Any) -> Any:
    """yfinance raises YFDataException when a symbol simply lacks this data; that isn't a failure."""
    try:
        return read()
    except Exception as exc:
        if type(exc).__name__ == "YFDataException":
            return empty
        raise


def read_ticker(ticker: Any) -> TickerData:
    """Price targets, recommendations and rating changes from a yfinance Ticker, each guarded."""
    return (
        _quietly(lambda: ticker.analyst_price_targets, {}) or {},
        _quietly(lambda: ticker.recommendations, pd.DataFrame()),
        _quietly(lambda: ticker.upgrades_downgrades, pd.DataFrame()),
    )


def _yahoo_load(yahoo_symbol: str) -> TickerData:
    import yfinance as yf  # imported lazily: slow import, and tests inject a fake

    logging.getLogger("yfinance").setLevel(logging.CRITICAL)  # it logs an ERROR line per 404
    return read_ticker(yf.Ticker(yahoo_symbol))


def _price(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _graded(upgrades: pd.DataFrame | None, now: pd.Timestamp, days: int) -> tuple[int, int, int, int]:
    """(upgrades, downgrades, target raises, target lowers) graded in the last `days` days."""
    if upgrades is None or upgrades.empty:
        return 0, 0, 0, 0
    recent = upgrades[(upgrades.index >= now - pd.Timedelta(days=days)) & (upgrades.index <= now)]
    action = recent["Action"] if "Action" in recent else pd.Series(dtype=str)
    target = recent["priceTargetAction"] if "priceTargetAction" in recent else pd.Series(dtype=str)
    return (
        int((action == "up").sum()),
        int((action == "down").sum()),
        int((target == "Raises").sum()),
        int((target == "Lowers").sum()),
    )


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def rating_events(upgrades: pd.DataFrame | None, now: pd.Timestamp) -> tuple[list[RatingEvent], datetime | None, int]:
    """(the kept rating changes, oldest first; the oldest change's time; how many Yahoo lists).

    Kept: the changes graded in the EVENT_DAYS days up to `now` (naive UTC), and the latest downgrade
    graded before them. Grade times are naive UTC, as the training history has them.
    """
    if upgrades is None or upgrades.empty:
        return [], None, 0
    graded = pd.to_datetime(upgrades.index, utc=True).tz_localize(None)
    frame = pd.DataFrame({"graded_at": graded})
    for source, name in _EVENT_FIELDS.items():
        frame[name] = upgrades[source].to_numpy() if source in upgrades else None
    frame = frame.dropna(subset=["graded_at"]).sort_values("graded_at", kind="stable").reset_index(drop=True)
    if frame.empty:
        return [], None, 0
    recent = frame["graded_at"] >= now - pd.Timedelta(days=EVENT_DAYS)
    older_downs = frame.index[~recent & frame["action"].eq("down").fillna(False).astype(bool)]
    if len(older_downs):
        recent.loc[older_downs[-1]] = True
    events = [
        RatingEvent(graded_at=row.graded_at.to_pydatetime(),
                    **{name: _text(getattr(row, name)) for name in _EVENT_FIELDS.values()})
        for row in frame[recent].itertuples(index=False)
    ]
    return events, frame["graded_at"].iloc[0].to_pydatetime(), len(frame)


def analyst_view(
    symbol: str,
    targets: dict | None,
    recommendations: pd.DataFrame | None,
    upgrades: pd.DataFrame | None,
    as_of: datetime,
) -> AnalystView | None:
    targets = targets or {}
    latest = None
    if recommendations is not None and not recommendations.empty and "period" in recommendations:
        current = recommendations[recommendations["period"] == "0m"]
        if not current.empty:
            latest = current.iloc[0]
    has_upgrades = upgrades is not None and not upgrades.empty
    if not targets and latest is None and not has_upgrades:
        return None

    def count(column: str) -> int | None:
        if latest is None or column not in latest or pd.isna(latest[column]):
            return None
        return int(latest[column])

    now = pd.Timestamp(as_of.astimezone(UTC).replace(tzinfo=None))  # grade dates are naive UTC
    up_30, down_30, raises_30, lowers_30 = _graded(upgrades, now, 30)
    up_90, down_90, _, _ = _graded(upgrades, now, 90)
    events, oldest, listed = rating_events(upgrades, now)
    return AnalystView(
        symbol=symbol,
        as_of=as_of.astimezone(ET).date(),
        target_mean=_price(targets.get("mean")),
        target_low=_price(targets.get("low")),
        target_high=_price(targets.get("high")),
        target_median=_price(targets.get("median")),
        rec_strong_buy=count("strongBuy"),
        rec_buy=count("buy"),
        rec_hold=count("hold"),
        rec_sell=count("sell"),
        rec_strong_sell=count("strongSell"),
        upgrades_30d=up_30,
        downgrades_30d=down_30,
        upgrades_90d=up_90,
        downgrades_90d=down_90,
        target_raises_30d=raises_30,
        target_lowers_30d=lowers_30,
        events=events,
        oldest_event=oldest,
        event_count=listed,
    )


class YFinanceAnalyst:
    name = "yfinance_analyst"
    category = Category.FUNDAMENTALS
    core = False
    best_effort = True
    cadence = Cadence.DAILY
    asset_types = frozenset({AssetType.STOCK})
    markets = frozenset({Market.US, Market.TSX})
    record_type = AnalystView
    freshness = timedelta(days=3)
    scope = Scope.SYMBOLS
    canary = ("AAPL", "RY.TO")
    canary_requires_records = True
    # 300 US and 100 TSX shortlisted stocks plus holdings, so every forecast stock has its rating history
    max_symbols = 600

    def __init__(self, load: Loader | None = None, limiter: RateLimiter | None = None) -> None:
        self._load = load or _yahoo_load
        self._limiter = limiter

    def fetch(self, symbols: Sequence[str], as_of: datetime) -> list[AnalystView]:
        def one(symbol: str) -> list[AnalystView]:
            view = analyst_view(symbol, *self._load(to_yahoo(symbol)), as_of)
            return [view] if view else []

        return collect_yahoo(symbols, one, limiter=self._limiter)
