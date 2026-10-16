"""The Crypto Fear & Greed index from alternative.me (spec source 23).

One keyless call returns the last 30 daily values, newest first. Values and timestamps are
strings; a timestamp is 00:00 UTC of its day, and the day's value is published soon after. An
error comes back as HTTP 200 with `metadata.error` set and no data.
"""

import math
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from advisor.collectors.base import Cadence, Category, RateLimiter, Scope, get_with_retries
from advisor.collectors.series import SeriesObservation
from advisor.models import AssetType, Market

FNG_URL = "https://api.alternative.me/fng/"
SERIES_NAME = "crypto_fear_greed"
DAYS = 30


def parse_index(payload: Mapping[str, Any], as_of: datetime) -> list[SeriesObservation]:
    """Daily values up to `as_of`'s UTC day, oldest first."""
    error = (payload.get("metadata") or {}).get("error")
    if error:
        raise ValueError(f"alternative.me: {error}")
    today = as_of.astimezone(UTC).date()
    rows: list[SeriesObservation] = []
    for point in payload.get("data") or []:
        day = datetime.fromtimestamp(int(point["timestamp"]), UTC).date()
        value = float(point["value"])
        if day <= today and math.isfinite(value):
            rows.append(SeriesObservation(series=SERIES_NAME, day=day, value=value))
    if not rows:
        raise ValueError("alternative.me sent no Fear & Greed values")
    return sorted(rows, key=lambda row: row.day)


class CryptoFearGreed:
    name = "crypto_fear_greed"
    category = Category.MACRO
    core = False
    best_effort = False
    cadence = Cadence.DAILY
    asset_types = frozenset({AssetType.CRYPTO})
    markets: frozenset[Market] = frozenset()  # crypto belongs to no stock market
    record_type = SeriesObservation
    freshness = timedelta(days=3)
    scope = Scope.MARKET
    canary: tuple[str, ...] = ()
    canary_requires_records = True
    max_symbols = None

    def __init__(self, client: httpx.Client, limiter: RateLimiter | None = None) -> None:
        self._client = client
        self._limiter = limiter

    def fetch(self, symbols: Sequence[str], as_of: datetime) -> list[SeriesObservation]:
        response = get_with_retries(
            self._client,
            FNG_URL,
            params={"limit": DAYS, "format": "json"},
            limiter=self._limiter,
        )
        return parse_index(response.json(), as_of)
