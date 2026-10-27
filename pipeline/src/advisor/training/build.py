"""Builds the training data: every Parquet file Plan 3b trains on, plus manifest.json.

Run weekly (`python -m advisor.training.build --out DIR`), from scratch each time. A build that
would train on a hollow dataset fails instead: a short universe, many stocks without bars, or a
missing benchmark or sector ETF. A few stocks without bars are only recorded in the manifest.
"""

import argparse
import contextlib
import json
import logging
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
from advisor.collectors.yfinance_bars import Downloader
from advisor.config import Settings
from advisor.markets import MARKETS
from advisor.models import ET, Market
from advisor.store import repo
from advisor.store.db import connect
from advisor.training import prices
from advisor.training.fundamentals import reduce_companyfacts, universe_ciks
from advisor.training.macro import MacroRefused, MacroUnavailable, macro_history
from advisor.training.prices import YahooThrottled, download_history, history_start
from advisor.training.sectors import all_sector_etfs, classify, industries, screen_industries

MAX_MISSING_SHARE = 0.2  # of a market's stocks Yahoo may send no bars for
FUNDAMENTALS_SINCE_YEARS = 2  # facts are read from this long before the price history starts

log = logging.getLogger(__name__)


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
    download: Downloader = prices.training_download
    screen_sectors: Callable[[], dict[str, tuple[str, str]]] = _screen_sectors
    sleep: Callable[[float], None] = field(default=time.sleep)


def _write(frame: pd.DataFrame, out: Path, name: str, manifest: dict) -> None:
    path = out / name
    frame.to_parquet(path, compression="zstd", index=False)
    manifest["files"][name] = {"rows": len(frame), "bytes": path.stat().st_size}


def build(out: Path, now: datetime, deps: BuildDeps, limit: int | None = None) -> dict:
    """Write every file into `out` and return the manifest (also written as manifest.json).

    A failing step raises BuildFailed naming it, after writing a manifest that records the failure
    and lists the files already written.
    """
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
    build_began = time.monotonic()

    def timed(step: str, since: float) -> None:
        seconds[step] = round(time.monotonic() - since, 1)

    step = "universe"
    try:
        stocks: dict[Market, list[str]] = {}
        for market in Market:
            symbols = sorted(deps.universe(market))[:limit]
            if limit is None and len(symbols) < MARKETS[market].min_universe:
                raise BuildFailed(f"{market} universe too small: {len(symbols)}")
            stocks[market] = symbols
        log.info("universe: %s", ", ".join(f"{len(stocks[m])} {m}" for m in Market))

        step = "sectors"
        began = time.monotonic()
        labelled = classify([s for market in Market for s in stocks[market]], deps.screen_sectors())
        _write(labelled, out, "sectors.parquet", manifest)
        manifest["unclassified"] = int(labelled["sector"].isna().sum())
        if deps.conn is not None:
            repo.write_sectors(deps.conn, list(labelled.itertuples(index=False, name=None)))
        timed("sectors", began)

        # macro is quick when FRED is well, so it goes before the long Yahoo download: a FRED
        # that is down fails the build in minutes, not after half an hour of prices
        step = "macro"
        began = time.monotonic()
        try:
            _write(macro_history(deps.http, start, today, sleep=deps.sleep), out, "macro.parquet", manifest)
        except MacroUnavailable as exc:
            # nothing trains on macro.parquet yet (spec §5.1), and FRED stalls requests from
            # GitHub's runners, so a source that never answers is recorded, not fatal. A series
            # refused or sent empty still fails: that is a change to fix, not an outage.
            manifest["unavailable"] = {"macro": str(exc)}
            log.warning("macro: skipped, macro.parquet not written: %s", exc)
        timed("macro", began)

        for market in Market:
            step = f"prices_{market}"
            began = time.monotonic()
            extras = [MARKETS[market].benchmark, *all_sector_etfs()[market]]
            history = download_history(
                [*stocks[market], *extras], start, today, download=deps.download, sleep=deps.sleep,
                log_as=f"prices {market}",
            )
            if history.missing:
                # yfinance's cache sometimes drops a ticker ("database is locked"): ask once more
                log.info("prices %s: asking again for %d without bars", market, len(history.missing))
                deps.sleep(prices.PAUSE_SECONDS)
                try:
                    again = download_history(
                        history.missing, start, today, download=deps.download, sleep=deps.sleep,
                        log_as=f"prices {market} again",
                    )
                except YahooThrottled:  # keep the first answer: the market's missing-share rule decides
                    again = None
                if again is not None:
                    history = prices.PriceHistory(
                        bars=pd.concat([history.bars, again.bars], ignore_index=True).sort_values(
                            ["symbol", "day"], ignore_index=True
                        ),
                        events=pd.concat([history.events, again.events], ignore_index=True).sort_values(
                            ["symbol", "day"], ignore_index=True
                        ),
                        missing=again.missing,
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
            _write(history.events, out, f"events_{market}.parquet", manifest)
            manifest["missing"][str(market)] = lost
            timed(f"prices_{market}", began)
            log.info("prices %s: %d bars, %d stocks without", market, len(history.bars), len(lost))

        step = "fundamentals"
        began = time.monotonic()
        tickers = universe_ciks(deps.sec.get(TICKERS_URL).json(), stocks[Market.US])
        _write(tickers, out, "tickers.parquet", manifest)
        zip_path = out / "companyfacts.zip"
        try:
            log.info("fundamentals: companyfacts download")
            deps.sec.download(COMPANYFACTS_ZIP_URL, zip_path)
            timed("companyfacts_download", began)
            began = time.monotonic()
            log.info("fundamentals: companyfacts reduce for %d companies", len(tickers))
            facts, absent_ciks = reduce_companyfacts(
                zip_path, tickers["cik"], history_start(start, years=FUNDAMENTALS_SINCE_YEARS)
            )
        finally:
            zip_path.unlink(missing_ok=True)
        _write(facts, out, "fundamentals.parquet", manifest)
        manifest["missing"]["ciks"] = len(absent_ciks)
        timed("fundamentals", began)
    except Exception as exc:
        readable = isinstance(exc, BuildFailed | MacroRefused)
        message = f"{step} step failed: {exc if readable else f'{type(exc).__name__}: {exc}'}"
        manifest["failed"] = {"step": step, "error": message}
        (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
        raise BuildFailed(message) from exc

    try:
        import resource  # Unix only; ru_maxrss is KiB on Linux

        manifest["peak_rss_mb"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024
    except ImportError:
        pass

    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    log.info("done in %.0f s", time.monotonic() - build_began)
    return manifest


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the stock model's training data.")
    parser.add_argument("--out", required=True, type=Path, help="directory to write the files to")
    parser.add_argument("--limit", type=int, help="stocks per market (a quick check, not a full build)")
    parser.add_argument("--no-db", action="store_true", help="don't write sectors to the database")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # its request lines include query strings
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
        try:
            manifest = build(args.out, now, deps, limit=args.limit)
        except BuildFailed as exc:
            log.error("%s (see %s)", exc, args.out / "manifest.json", exc_info=exc.__cause__ or exc)
            return 1
    print(json.dumps({k: v for k, v in manifest.items() if k != "missing"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
