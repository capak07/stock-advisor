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
