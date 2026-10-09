"""Shared domain types used across the pipeline."""

from datetime import date
from enum import StrEnum
from typing import NamedTuple
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

ET = ZoneInfo("America/New_York")


class AssetType(StrEnum):
    STOCK = "stock"
    CRYPTO = "crypto"


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


class SymbolInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    asset_type: AssetType = AssetType.STOCK
    name: str
    exchange: str


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
