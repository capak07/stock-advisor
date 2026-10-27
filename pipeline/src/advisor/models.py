"""Shared domain types used across the pipeline."""

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Any, NamedTuple, Self
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator

ET = ZoneInfo("America/New_York")


class AssetType(StrEnum):
    STOCK = "stock"
    CRYPTO = "crypto"


class Market(StrEnum):
    """Stock markets in scope (spec §3). Crypto belongs to no market."""

    US = "US"
    TSX = "TSX"


class RunKind(StrEnum):
    PRE_OPEN = "pre_open"
    PRE_CLOSE = "pre_close"
    EARLY_CLOSE = "early_close"


class RunStatus(StrEnum):
    RUNNING = "running"
    SUCCESS = "success"
    DEGRADED = "degraded"
    FAILED = "failed"


class AssetRef(NamedTuple):
    symbol: str
    asset_type: AssetType


class DailyClose(NamedTuple):
    """A stored daily close (Plan 5a): Yahoo's adjusted close for a stock, Coinbase's for a coin."""

    ref: AssetRef
    day: date
    close: float
    currency: str  # "USD" or "CAD"


@dataclass(frozen=True)
class StoredModel:
    """A trained model's row in `models`; its files load separately."""

    version: str
    kind: str
    trained_at: datetime
    metrics: dict[str, Any]
    calibration_error: float | None
    active: bool


@dataclass(frozen=True)
class PredictionRow:
    """One stock's forecast at one horizon: the return range and P(beat the benchmark)."""

    symbol: str
    horizon_days: int
    q10: float
    q50: float
    q90: float
    p_beat: float
    benchmark: str
    model_version: str


@dataclass(frozen=True)
class PickRow:
    """One stock pick of a run (spec §6.1-§6.5): its hold, entry, stop, risk and why."""

    symbol: str
    market: Market
    style: str  # swing or position
    horizon_days: int
    exit_by: date  # the horizon's last session on the market's own calendar
    entry_ref_price: float  # the feature day's close
    stop: float
    risk_level: str
    risk_score: float
    max_position_pct: float
    rank: int  # within its style and market, from 1
    top_factors: list[dict[str, Any]]  # JSON-ready
    catalysts: list[dict[str, Any]]  # JSON-ready
    feature_day: date  # the market's feature day, the day entry_ref_price closed
    bench_ref_price: float  # the market's benchmark close on that day


@dataclass(frozen=True)
class LinkedPick:
    """The pick a holding was bought on, as the holdings stage reads it."""

    id: int
    horizon_days: int
    exit_by: date
    stop: float  # the trailing stop never sits below it
    status: str  # open, exited_early or graded
    top_factors: list[dict[str, Any]]  # what drove its forecast then


@dataclass(frozen=True)
class HoldingActionRow:
    """One holding's action of a run, per account (spec §7.3), with what grading it later needs.

    Prices are in the asset's own currency: USD for US stocks and coins, CAD for TSX stocks.
    """

    account: str
    symbol: str
    asset_type: AssetType
    action: str  # sell, trim, add or hold
    review: bool
    reasons: list[str]
    warnings: list[str]
    trailing_stop: float | None
    q10: float | None
    q50: float | None
    q90: float | None
    exit_by: date | None
    horizon_days: int | None  # None without a forecast (always for a coin)
    feature_day: date | None
    ref_price: float | None  # the feature day's close; None when not priced
    bench_ref_price: float | None  # the benchmark's close that day; None for a coin
    risk_level: str
    max_position_pct: float


class SymbolInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    asset_type: AssetType = AssetType.STOCK
    market: Market | None = None
    name: str
    exchange: str

    @model_validator(mode="after")
    def _market_matches_asset_type(self) -> Self:
        if (self.asset_type is AssetType.STOCK) != (self.market is not None):
            raise ValueError("stocks need a market and crypto has none")
        return self


class DailyBar(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    day: date
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)
    volume: float = Field(ge=0)
    source: str
