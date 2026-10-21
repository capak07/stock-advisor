"""Builds the training data: every Parquet file Plan 3b trains on, plus manifest.json.

Run weekly (`python -m advisor.training.build --out DIR`), from scratch each time. A build that
would train on a hollow dataset fails instead: a short universe, many stocks without bars, or a
missing benchmark or sector ETF. A few stocks without bars are only recorded in the manifest.
"""

import argparse
import contextlib
import json
import os
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pandas as pd
import psycopg

from advisor.collectors.base import RateLimiter, make_client
from advisor.collectors.nasdaq_symbols import NasdaqSymbols
from advisor.collectors.sec import COMPANYFACTS_ZIP_URL, SEC_PER_MINUTE, TICKERS_URL, SecEdgar
from advisor.collectors.tmx_symbols import TmxSymbols
from advisor.collectors.yfinance_bars import Downloader, yahoo_download
from advisor.config import Settings
from advisor.markets import MARKETS
from advisor.models import ET, Market
from advisor.store import repo
from advisor.store.db import connect
from advisor.training.fundamentals import reduce_companyfacts, universe_ciks
from advisor.training.macro import macro_history
from advisor.training.prices import download_history, history_start
from advisor.training.sectors import all_sector_etfs, classify, industries, screen_industries

MAX_MISSING_SHARE = 0.2  # of a market's stocks Yahoo may send no bars for
FUNDAMENTALS_SINCE_YEARS = 2  # facts are read from this long before the price history starts


class BuildFailed(Exception):
    """The data is too incomplete to train on."""


def _screen_sectors() -> dict[str, tuple[str, str]]:
    return screen_industries(industries())


@dataclass
class BuildDeps:
    http: httpx.Client
    sec: SecEdgar
    universe: Callable[[Market], list[str]]
    conn: psycopg.Connection | None = None
    download: Downloader = yahoo_download
    screen_sectors: Callable[[], dict[str, tuple[str, str]]] = _screen_sectors
    sleep: Callable[[float], None] = field(default=time.sleep)


def _write(frame: pd.DataFrame, out: Path, name: str, manifest: dict) -> None:
    path = out / name
    frame.to_parquet(path, compression="zstd", index=False)
    manifest["files"][name] = {"rows": len(frame), "bytes": path.stat().st_size}


def build(out: Path, now: datetime, deps: BuildDeps, limit: int | None = None) -> dict:
    """Write every file into `out` and return the manifest (also written as manifest.json)."""
    out.mkdir(parents=True, exist_ok=True)
    today = now.astimezone(ET).date()
    start = history_start(today)
    manifest: dict[str, Any] = {
        "built_at": now.isoformat(),
        "start": start.isoformat(),
        "end": today.isoformat(),
        "files": {},
        "missing": {},
        "seconds": {},
    }
    seconds: dict[str, float] = manifest["seconds"]

    def timed(step: str, since: float) -> None:
        seconds[step] = round(time.monotonic() - since, 1)

    stocks: dict[Market, list[str]] = {}
    for market in Market:
        symbols = sorted(deps.universe(market))[:limit]
        if limit is None and len(symbols) < MARKETS[market].min_universe:
            raise BuildFailed(f"{market} universe too small: {len(symbols)}")
        stocks[market] = symbols

    began = time.monotonic()
    labelled = classify([s for market in Market for s in stocks[market]], deps.screen_sectors())
    _write(labelled, out, "sectors.parquet", manifest)
    manifest["unclassified"] = int(labelled["sector"].isna().sum())
    if deps.conn is not None:
        repo.write_sectors(deps.conn, list(labelled.itertuples(index=False, name=None)))
    timed("sectors", began)

    for market in Market:
        began = time.monotonic()
        extras = [MARKETS[market].benchmark, *all_sector_etfs()[market]]
        history = download_history(
            [*stocks[market], *extras], start, today, download=deps.download, sleep=deps.sleep
        )
        gone = set(history.missing)
        lost = [s for s in stocks[market] if s in gone]
        if len(lost) > MAX_MISSING_SHARE * len(stocks[market]):
            raise BuildFailed(
                f"Yahoo sent no bars for {len(lost)} of {len(stocks[market])} {market} stocks"
            )
        absent = [s for s in extras if s in gone]
        if absent:
            raise BuildFailed(f"Yahoo sent no bars for {market} benchmark/ETFs: {', '.join(absent)}")
        _write(history.bars, out, f"prices_{market}.parquet", manifest)
        manifest["missing"][str(market)] = lost
        timed(f"prices_{market}", began)

    began = time.monotonic()
    tickers = universe_ciks(deps.sec.get(TICKERS_URL).json(), stocks[Market.US])
    _write(tickers, out, "tickers.parquet", manifest)
    zip_path = out / "companyfacts.zip"
    try:
        deps.sec.download(COMPANYFACTS_ZIP_URL, zip_path)
        timed("companyfacts_download", began)
        began = time.monotonic()
        facts, absent_ciks = reduce_companyfacts(
            zip_path, tickers["cik"], history_start(start, years=FUNDAMENTALS_SINCE_YEARS)
        )
    finally:
        zip_path.unlink(missing_ok=True)
    _write(facts, out, "fundamentals.parquet", manifest)
    manifest["missing"]["ciks"] = len(absent_ciks)
    timed("fundamentals", began)

    began = time.monotonic()
    _write(macro_history(deps.http, start, today), out, "macro.parquet", manifest)
    timed("macro", began)

    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the stock model's training data.")
    parser.add_argument("--out", required=True, type=Path, help="directory to write the files to")
    parser.add_argument("--limit", type=int, help="stocks per market (a quick check, not a full build)")
    parser.add_argument("--no-db", action="store_true", help="don't write sectors to the database")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    now = datetime.now(UTC)
    with contextlib.ExitStack() as stack:
        client = stack.enter_context(make_client(timeout=60.0))
        sec = SecEdgar(
            client,
            os.environ.get("SEC_USER_AGENT"),
            RateLimiter(per_minute=SEC_PER_MINUTE, burst=5),
        )
        listed = {
            Market.US: NasdaqSymbols(client).fetch([], now),
            Market.TSX: TmxSymbols(client).fetch([], now),
        }
        conn = None
        if not args.no_db:
            conn = stack.enter_context(connect(Settings.from_env().database_url))
        deps = BuildDeps(
            http=client,
            sec=sec,
            universe=lambda market: [info.symbol for info in listed[market]],
            conn=conn,
        )
        manifest = build(args.out, now, deps, limit=args.limit)
    print(json.dumps({k: v for k, v in manifest.items() if k != "missing"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
