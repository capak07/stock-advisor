"""Bitcoin network activity from blockchain.com's chart API (spec source 53).

One keyless request per chart (several charts in one request answer 404), spaced about 10 s
apart. Each daily point sits at 00:00 UTC and the last one is yesterday's, so every point is a
finished day. The chart API reports hash rate in TH/s.
"""

import math
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from advisor.collectors.base import (
    BUDGET_EXHAUSTED,
    Cadence,
    Category,
    DeadlineExceeded,
    PartialFetch,
    RateLimiter,
    Scope,
    check_deadline,
    get_with_retries,
)
from advisor.collectors.series import SeriesObservation
from advisor.models import AssetType, Market

CHART_URL = "https://api.blockchain.info/charts/{name}"
BLOCKCHAIN_PER_MINUTE = 6  # one chart every 10 s
CHARTS = {
    "hash-rate": "network hash rate, TH/s",
    "difficulty": "mining difficulty",
    "n-transactions": "confirmed transactions per day",
    "transaction-fees-usd": "transaction fees paid per day, USD",
    "estimated-transaction-volume-usd": "estimated value moved on chain per day, USD",
}
TIMESPAN = "60days"


def parse_chart(name: str, payload: Mapping[str, Any], as_of: datetime) -> list[SeriesObservation]:
    """A chart's finished days before `as_of`'s UTC day, oldest first."""
    if payload.get("status") != "ok":
        raise ValueError(f"blockchain.com chart {name} answered {payload.get('status')!r}")
    today = as_of.astimezone(UTC).date()
    rows: list[SeriesObservation] = []
    for point in payload.get("values") or []:
        day = datetime.fromtimestamp(point["x"], UTC).date()
        value = float(point["y"])
        if day < today and math.isfinite(value):
            rows.append(SeriesObservation(series=name, day=day, value=value))
    return rows


class BlockchainStats:
    name = "blockchain_stats"
    category = Category.ONCHAIN
    core = False
    best_effort = False
    cadence = Cadence.DAILY
    asset_types = frozenset({AssetType.CRYPTO})
    markets: frozenset[Market] = frozenset()
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
        records: list[SeriesObservation] = []
        failures: list[str] = []
        for name in CHARTS:
            try:
                check_deadline()
                response = get_with_retries(
                    self._client,
                    CHART_URL.format(name=name),
                    params={"timespan": TIMESPAN, "format": "json", "sampled": "false"},
                    limiter=self._limiter,
                )
                rows = parse_chart(name, response.json(), as_of)
            except DeadlineExceeded:
                if not records:
                    raise
                raise PartialFetch(records, f"stopped at {name}: {BUDGET_EXHAUSTED}") from None
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                failures.append(f"{name}: {type(exc).__name__}: {exc}"[:200])
                continue
            if not rows:
                failures.append(f"{name}: no finished days")
            records.extend(rows)
        if failures:
            raise PartialFetch(
                records,
                f"{len(failures)} of {len(CHARTS)} blockchain.com charts failed; first: {failures[0]}",
            )
        return records
