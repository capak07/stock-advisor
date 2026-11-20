"""FINRA's short interest and daily short volume as history tables for the stock model.

Short interest comes from one file per settlement (the dates are listed by FINRA's partitions API) and
short volume from one file per trading day. Every file is parsed whole, with FINRA's own symbols, and
a file more than FINRA_CACHE_AFTER_DAYS old is cached that way: files are re-issued only soon after
publication, and a symbol that joins the universe later still finds its old rows. Whole or fetched, the
rows are mapped onto the universe on read.

FINRA answers 403 or 404 for a file it has not published. Only a short-volume session at most
UNPUBLISHED_GRACE_DAYS old may be that (its file comes out that evening) and is skipped. Every settlement
date comes from FINRA's partitions API, so its file is published, and an older session's file has been out
for days: a 403 or 404 there is an outage or a removed file, and raises FinraMissing, so the short group
fails (keeping its earlier files) instead of writing a history with a hole that reads as stale values.

Columns: short interest `symbol`, `settlement`, `short_interest`, `avg_daily_volume`, `days_to_cover`
(NaN for FINRA's 999.99 or without volume); short volume `symbol`, `day`, `short_volume`, `total_volume`.
Dates are `date` values.
"""

from collections.abc import Callable, Mapping, Sequence
from datetime import date, timedelta
from typing import Protocol

import httpx
import pandas as pd

from advisor.collectors.base import RateLimiter, check_deadline, get_with_retries
from advisor.collectors.finra_short_interest import (
    FINRA_SHORT_INTEREST_URL,
    UNPUBLISHED,
    parse_short_interest,
)
from advisor.collectors.finra_short_volume import FINRA_SHORT_VOLUME_URL, parse_short_volume
from advisor.symbols import requested_by_key, symbol_key

PARTITIONS_URL = "https://api.finra.org/partitions/group/otcMarket/name/consolidatedShortInterest"
FINRA_CACHE_AFTER_DAYS = 90  # a file dated over this long before today never changes again
UNPUBLISHED_GRACE_DAYS = 3  # a short-volume session this recent may not be published yet
INTEREST_COLUMNS = ["symbol", "settlement", "short_interest", "avg_daily_volume", "days_to_cover"]
VOLUME_COLUMNS = ["symbol", "day", "short_volume", "total_volume"]
_DTYPES = {
    "short_interest": "int64", "avg_daily_volume": "float64", "days_to_cover": "float64",
    "short_volume": "float64", "total_volume": "float64",
}


class FinraMissing(Exception):
    """FINRA did not serve a file that must be published: a listed settlement or an older session."""


class HistoryCache(Protocol):
    """The part of the group-history cache these functions use: whole frames by kind and key."""

    def get(self, kind: str, key: str) -> pd.DataFrame | None: ...

    def put(self, kind: str, key: str, frame: pd.DataFrame) -> None: ...


def settlement_dates(client: httpx.Client) -> list[date]:
    """Every settlement date FINRA has a short interest file for, ascending."""
    payload = get_with_retries(client, PARTITIONS_URL).json()
    return sorted({date.fromisoformat(item["partitions"][0]) for item in payload["availablePartitions"]})


def _frame(rows: Sequence[tuple], columns: list[str]) -> pd.DataFrame:
    frame = pd.DataFrame(list(rows), columns=columns)
    frame = frame.astype({name: _DTYPES[name] for name in columns if name in _DTYPES})
    frame["symbol"] = frame["symbol"].astype("string")
    return frame


def _interest_frame(text: str) -> pd.DataFrame:
    return _frame([
        (r.symbol, r.settlement_date, r.short_interest,
         float("nan") if r.avg_daily_volume is None else float(r.avg_daily_volume),
         float("nan") if r.days_to_cover is None else r.days_to_cover)
        for r in parse_short_interest(text, None)
    ], INTEREST_COLUMNS)


def _volume_frame(text: str) -> pd.DataFrame:
    return _frame([
        (r.symbol, r.trade_date, r.short_volume, r.total_volume) for r in parse_short_volume(text, None)
    ], VOLUME_COLUMNS)


def _on_universe(frame: pd.DataFrame, wanted: Mapping[str, str], seen: dict[str, str | None]) -> pd.DataFrame:
    """The rows of the wanted symbols, with FINRA's spelling replaced by the canonical one.

    `seen` maps each FINRA symbol met so far to its canonical symbol (None when not wanted). It is shared
    by every file of one history, so each distinct symbol is keyed once, not once per row of each file.
    """
    for finra_symbol in frame["symbol"].dropna().unique():
        if finra_symbol not in seen:
            seen[finra_symbol] = wanted.get(symbol_key(finra_symbol))
    mapped = frame["symbol"].map(seen).astype("string")
    kept = frame.assign(symbol=mapped)
    return kept[kept["symbol"].notna()].drop_duplicates("symbol")


def _history(
    client: httpx.Client,
    dates: Sequence[date],
    symbols: Sequence[str],
    cache: HistoryCache | None,
    limiter: RateLimiter | None,
    today: date,
    *,
    kind: str,
    url: str,
    parse: Callable[[str], pd.DataFrame],
    columns: list[str],
    date_column: str,
    may_be_unpublished: Callable[[date], bool],
) -> pd.DataFrame:
    wanted = requested_by_key(symbols)
    seen: dict[str, str | None] = {}
    parts: list[pd.DataFrame] = []
    for day in dates:
        check_deadline()
        key = day.isoformat()
        frame = cache.get(kind, key) if cache is not None else None
        if frame is None:
            try:
                response = get_with_retries(client, url.format(day=day), limiter=limiter)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code not in UNPUBLISHED:
                    raise
                if may_be_unpublished(day):
                    continue
                raise FinraMissing(f"FINRA answered {exc.response.status_code} for its {kind} file of {day}") from exc
            frame = parse(response.text)
            if cache is not None and (today - day).days > FINRA_CACHE_AFTER_DAYS:
                cache.put(kind, key, frame)
        parts.append(_on_universe(frame, wanted, seen))
    parts = [part for part in parts if not part.empty]
    if not parts:
        return _frame([], columns)
    out = pd.concat(parts, ignore_index=True)
    out = out.astype({name: _DTYPES[name] for name in columns if name in _DTYPES})
    return out.sort_values(["symbol", date_column], kind="stable").reset_index(drop=True)


def short_interest_history(
    client: httpx.Client,
    dates: Sequence[date],
    symbols: Sequence[str],
    cache: HistoryCache | None,
    limiter: RateLimiter | None,
    today: date,
) -> pd.DataFrame:
    """One row per universe symbol per settlement file in `dates`, which FINRA's partitions API listed
    (`settlement_dates`): a file it does not serve raises FinraMissing."""
    return _history(
        client, dates, symbols, cache, limiter, today, kind="finra_interest", url=FINRA_SHORT_INTEREST_URL,
        parse=_interest_frame, columns=INTEREST_COLUMNS, date_column="settlement",
        may_be_unpublished=lambda day: False,
    )


def short_volume_history(
    client: httpx.Client,
    days: Sequence[date],
    symbols: Sequence[str],
    cache: HistoryCache | None,
    limiter: RateLimiter | None,
    today: date,
) -> pd.DataFrame:
    """One row per universe symbol per daily file in `days`. A session at most UNPUBLISHED_GRACE_DAYS before
    `today` that FINRA does not serve is skipped; an older one raises FinraMissing."""
    return _history(
        client, days, symbols, cache, limiter, today, kind="finra_volume", url=FINRA_SHORT_VOLUME_URL,
        parse=_volume_frame, columns=VOLUME_COLUMNS, date_column="day",
        may_be_unpublished=lambda day: today - day <= timedelta(days=UNPUBLISHED_GRACE_DAYS),
    )
