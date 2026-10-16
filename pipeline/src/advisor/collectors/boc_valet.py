"""USD/CAD, the policy rate and Government of Canada yields from the Bank of Canada Valet API
(spec source 7).

One keyless JSON call returns every series since the lookback. A day a series has no value (a
holiday, or today's rate before publication) simply lacks it.
"""

import math
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from typing import Any

import httpx

from advisor.collectors.base import (
    Cadence,
    Category,
    PartialFetch,
    RateLimiter,
    Scope,
    get_with_retries,
)
from advisor.collectors.series import SeriesObservation
from advisor.models import ET, AssetType, Market

VALET_URL = "https://www.bankofcanada.ca/valet/observations/{series}/json"
SERIES = {
    "FXUSDCAD": "USD/CAD, daily average",
    "V39079": "target for the overnight rate (policy rate)",
    "BD.CDN.2YR.DQ.YLD": "2-year Government of Canada benchmark bond yield",
    "BD.CDN.10YR.DQ.YLD": "10-year Government of Canada benchmark bond yield",
}
LOOKBACK = timedelta(days=120)  # enough for a 63-session trend


def parse_observations(
    payload: Mapping[str, Any], series: Sequence[str]
) -> list[SeriesObservation]:
    rows: list[SeriesObservation] = []
    for observation in payload["observations"]:
        day = date.fromisoformat(observation["d"])
        for name in series:
            raw = (observation.get(name) or {}).get("v")
            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue
            if math.isfinite(value):
                rows.append(SeriesObservation(series=name, day=day, value=value))
    return sorted(rows, key=lambda row: (row.series, row.day))


class BankOfCanadaValet:
    name = "boc_valet"
    category = Category.PRICES  # spec §4.2 lists it with the price sources
    core = False
    best_effort = False
    cadence = Cadence.DAILY
    asset_types = frozenset({AssetType.STOCK})
    markets = frozenset({Market.US, Market.TSX})
    record_type = SeriesObservation
    freshness = timedelta(days=7)
    scope = Scope.MARKET
    canary: tuple[str, ...] = ()
    canary_requires_records = True
    max_symbols = None

    def __init__(self, client: httpx.Client, limiter: RateLimiter | None = None) -> None:
        self._client = client
        self._limiter = limiter

    def fetch(self, symbols: Sequence[str], as_of: datetime) -> list[SeriesObservation]:
        start = as_of.astimezone(ET).date() - LOOKBACK
        response = get_with_retries(
            self._client,
            VALET_URL.format(series=",".join(SERIES)),
            params={"start_date": start.isoformat()},
            limiter=self._limiter,
        )
        records = parse_observations(response.json(), list(SERIES))
        missing = sorted(set(SERIES) - {record.series for record in records})
        if missing:
            message = f"Bank of Canada sent no observations for {', '.join(missing)}"
            if records:
                raise PartialFetch(records, message)
            raise ValueError(message)
        return records
