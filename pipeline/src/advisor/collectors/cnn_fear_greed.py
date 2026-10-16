"""CNN's Fear & Greed index for US stocks (spec source 22; unofficial, best-effort).

The endpoint answers 418 ("You're a bot") unless a request carries CNN's own Referer and Origin;
no browser User-Agent is needed. Daily points sit at 00:00 UTC of their day and the last point
is the live reading, so a day can appear twice: the later reading wins.
"""

import math
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx

from advisor.collectors.base import Cadence, Category, RateLimiter, Scope, get_with_retries
from advisor.collectors.series import SeriesObservation
from advisor.models import AssetType, Market

CNN_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
CNN_HEADERS = {"Referer": "https://www.cnn.com/", "Origin": "https://www.cnn.com"}
SERIES_NAME = "fear_greed"
LOOKBACK = timedelta(days=60)


def parse_history(payload: Mapping[str, Any], as_of: datetime) -> list[SeriesObservation]:
    """One reading per UTC day from the last 60 days up to `as_of`, oldest first."""
    cutoff_ms = as_of.timestamp() * 1000
    start = as_of.astimezone(UTC).date() - LOOKBACK
    latest: dict[date, tuple[float, float]] = {}  # day -> (timestamp in ms, score)
    for point in payload["fear_and_greed_historical"]["data"]:
        stamp, score = float(point["x"]), float(point["y"])
        day = datetime.fromtimestamp(stamp / 1000, UTC).date()
        if stamp > cutoff_ms or day < start or not math.isfinite(score):
            continue
        if day not in latest or stamp > latest[day][0]:
            latest[day] = (stamp, score)
    if not latest:
        raise ValueError("CNN sent no Fear & Greed readings")
    return [
        SeriesObservation(series=SERIES_NAME, day=day, value=score)
        for day, (_, score) in sorted(latest.items())
    ]


class CnnFearGreed:
    name = "cnn_fear_greed"
    category = Category.MACRO
    core = False
    best_effort = True
    cadence = Cadence.PER_RUN  # the reading moves during the session
    asset_types = frozenset({AssetType.STOCK})
    markets = frozenset({Market.US})
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
            self._client, CNN_URL, headers=CNN_HEADERS, limiter=self._limiter
        )
        return parse_history(response.json(), as_of)
