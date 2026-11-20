"""Builds the training data: every Parquet file Plan 3b trains on, plus manifest.json.

Run weekly (`python -m advisor.training.build --out DIR`), from scratch each time. A build that
would train on a hollow dataset fails instead: a short universe, many stocks without bars, or a
missing benchmark or sector ETF. A few stocks without bars are only recorded in the manifest.

The US data groups' history (`training.history`) lives in a cache (`--history-cache`, Ruling R0):
- `--history-only` (the weekly history.yml): the universe and tickers.parquet, then the group download
  into the cache. Nothing else is built. It exits 1 when a wanted group ends unavailable (after writing
  the manifest; the workflow still saves the cache), so a failed group is never silent.
- `--no-history-download` (benchmark.yml, train.yml): the full build, then the fresh groups are copied
  from the cache. No group history is downloaded.
- neither (a local build): the full build, the group download, then the copy. `--groups none` skips
  the group history altogether, as before.
`--groups accepted` (train.yml): only the groups of the US market's accepted config, read from the database,
so train copies just what its model needs and a stale group it does not need is not recorded.
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
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx
import pandas as pd
import psycopg

from advisor.collectors.base import RateLimiter, make_client
from advisor.collectors.coinbase_candles import COINBASE_PER_MINUTE
from advisor.collectors.nasdaq_symbols import NasdaqSymbols
from advisor.collectors.openfda import OPENFDA_PER_MINUTE
from advisor.collectors.openfigi import OPENFIGI_PER_MINUTE, FigiBook
from advisor.collectors.registry import FINRA_PER_MINUTE
from advisor.collectors.sec import COMPANYFACTS_ZIP_URL, SEC_PER_MINUTE, TICKERS_URL, SecEdgar
from advisor.collectors.tmx_symbols import TmxSymbols
from advisor.collectors.yahoo import YAHOO_PER_MINUTE
from advisor.collectors.yfinance_bars import Downloader
from advisor.config import Settings
from advisor.markets import MARKETS
from advisor.models import ET, Market
from advisor.store import repo
from advisor.store.db import connect
from advisor.training import prices
from advisor.training.crypto import download_crypto
from advisor.training.fundamentals import reduce_companyfacts, universe_ciks
from advisor.training.history import (
    HistoryCache,
    HistoryDeps,
    accepted_groups,
    build_history,
    copy_history,
    wanted_groups,
)
from advisor.training.macro import MacroRefused, MacroUnavailable, macro_history
from advisor.training.prices import YahooThrottled, download_history, history_start
from advisor.training.sectors import all_sector_etfs, classify, industries, screen_industries

MAX_MISSING_SHARE = 0.2  # of a market's stocks Yahoo may send no bars for
FUNDAMENTALS_SINCE_YEARS = 2  # facts are read from this long before the price history starts
# group history starts this long before the price history: the longest look-backs (a year-old earnings
# report, a 365-day downgrade cap, openFDA's 180 days + 7 days' lag) are then full on the first row
GROUP_HISTORY_YEARS = 1

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
    history: HistoryDeps | None = None  # needed only by a plan that downloads group history


@dataclass(frozen=True)
class HistoryPlan:
    """The group-history step: which groups, the cache root, and the mode (see the module docstring)."""

    groups: frozenset[str]
    cache: Path
    only: bool = False  # the universe, tickers.parquet and the group download; nothing else
    download: bool = True  # False: copy the cached groups only


def _write(frame: pd.DataFrame, out: Path, name: str, manifest: dict) -> None:
    path = out / name
    frame.to_parquet(path, compression="zstd", index=False)
    manifest["files"][name] = {"rows": len(frame), "bytes": path.stat().st_size}


def _download_history(plan: HistoryPlan, deps: BuildDeps, tickers: pd.DataFrame, symbols: list[str],
                      since: date, now: datetime, manifest: dict) -> None:
    history = deps.history
    if history is None:
        raise BuildFailed("a group history download needs HistoryDeps")
    if history.cache.root != plan.cache:
        raise BuildFailed(f"the history deps' cache {history.cache.root} is not the plan's {plan.cache}")
    build_history(history.cache, plan.groups, history, tickers, symbols, history.names, since, now, manifest)


def _finish(out: Path, manifest: dict, began: float) -> dict:
    try:
        import resource  # Unix only; ru_maxrss is KiB on Linux

        manifest["peak_rss_mb"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024
    except ImportError:
        pass

    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    log.info("done in %.0f s", time.monotonic() - began)
    return manifest


def build(out: Path, now: datetime, deps: BuildDeps, limit: int | None = None,
          history: HistoryPlan | None = None) -> dict:
    """Write every file into `out` and return the manifest (also written as manifest.json).

    A failing step raises BuildFailed naming it, after writing a manifest that records the failure
    and lists the files already written. `history` adds the group-history step; None leaves it out.
    """
    out.mkdir(parents=True, exist_ok=True)
    today = now.astimezone(ET).date()
    start = history_start(today)
    since = history_start(start, years=GROUP_HISTORY_YEARS)
    manifest: dict[str, Any] = {
        "built_at": now.isoformat(),
        "start": start.isoformat(),
        "end": today.isoformat(),
        "files": {},
        "missing": {},
        "seconds": {},
    }
    if history is not None:
        manifest["history_groups"] = sorted(history.groups)
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

        if history is not None and history.only:  # the weekly history run: nothing else is built
            step = "history"
            began = time.monotonic()
            tickers = universe_ciks(deps.sec.get(TICKERS_URL).json(), stocks[Market.US])
            _write(tickers, out, "tickers.parquet", manifest)
            _download_history(history, deps, tickers, stocks[Market.US], since, now, manifest)
            timed("history", began)
            return _finish(out, manifest, build_began)

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
            manifest.setdefault("unavailable", {})["macro"] = str(exc)
            log.warning("macro: skipped, macro.parquet not written: %s", exc)
        timed("macro", began)

        for market in Market:
            step = f"prices_{market}"
            began = time.monotonic()
            extras = [MARKETS[market].benchmark, *all_sector_etfs()[market]]
            bars_history = download_history(
                [*stocks[market], *extras], start, today, download=deps.download, sleep=deps.sleep,
                log_as=f"prices {market}",
            )
            if bars_history.missing:
                # yfinance's cache sometimes drops a ticker ("database is locked"): ask once more
                log.info("prices %s: asking again for %d without bars", market, len(bars_history.missing))
                deps.sleep(prices.PAUSE_SECONDS)
                try:
                    again = download_history(
                        bars_history.missing, start, today, download=deps.download, sleep=deps.sleep,
                        log_as=f"prices {market} again",
                    )
                except YahooThrottled:  # keep the first answer: the market's missing-share rule decides
                    again = None
                if again is not None:
                    bars_history = prices.PriceHistory(
                        bars=pd.concat([bars_history.bars, again.bars], ignore_index=True).sort_values(
                            ["symbol", "day"], ignore_index=True
                        ),
                        events=pd.concat([bars_history.events, again.events], ignore_index=True).sort_values(
                            ["symbol", "day"], ignore_index=True
                        ),
                        missing=again.missing,
                    )
            gone = set(bars_history.missing)
            lost = [s for s in stocks[market] if s in gone]
            if len(lost) > MAX_MISSING_SHARE * len(stocks[market]):
                raise BuildFailed(
                    f"Yahoo sent no bars for {len(lost)} of {len(stocks[market])} {market} stocks"
                )
            absent = [s for s in extras if s in gone]
            if absent:
                raise BuildFailed(f"Yahoo sent no bars for {market} benchmark/ETFs: {', '.join(absent)}")
            _write(bars_history.bars, out, f"prices_{market}.parquet", manifest)
            _write(bars_history.events, out, f"events_{market}.parquet", manifest)
            manifest["missing"][str(market)] = lost
            timed(f"prices_{market}", began)
            log.info("prices %s: %d bars, %d stocks without", market, len(bars_history.bars), len(lost))

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

        if history is not None:
            step = "history"
            if history.download:  # a local build; the workflows download only in history.yml
                began = time.monotonic()
                _download_history(history, deps, tickers, stocks[Market.US], since, now, manifest)
                timed("history", began)
            began = time.monotonic()
            copy_history(HistoryCache(history.cache), out, history.groups, now, manifest)
            timed("history_copy", began)
    except Exception as exc:
        readable = isinstance(exc, BuildFailed | MacroRefused)
        message = f"{step} step failed: {exc if readable else f'{type(exc).__name__}: {exc}'}"
        manifest["failed"] = {"step": step, "error": message}
        (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
        raise BuildFailed(message) from exc

    try:
        limiter = RateLimiter(per_minute=COINBASE_PER_MINUTE, burst=3, sleep=deps.sleep)
        frame, counts = download_crypto(deps.http, today, limiter)
        _write(frame, out, "prices_crypto.parquet", manifest)
        manifest["crypto"] = counts
    except Exception as exc:
        manifest["crypto_error"] = f"{type(exc).__name__}: {exc}"

    return _finish(out, manifest, build_began)


ACCEPTED = "accepted"  # --groups accepted: resolved in `main`, which has the database


def _groups_option(choice: str) -> frozenset[str] | str:
    if choice.strip() == ACCEPTED:
        return ACCEPTED
    try:
        return wanted_groups(choice)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the stock model's training data.")
    parser.add_argument("--out", required=True, type=Path, help="directory to write the files to")
    parser.add_argument("--limit", type=int, help="stocks per market (a quick check, not a full build)")
    parser.add_argument("--no-db", action="store_true", help="don't write sectors to the database")
    parser.add_argument("--groups", type=_groups_option, default="all", metavar="CHOICE",
                        help="data groups' history: all (default), none, accepted (the US config's groups; needs the "
                             "database), or a comma list such as short,holders")
    parser.add_argument("--history-cache", type=Path, metavar="DIR",
                        help="the group-history cache (default: <out>/history-cache)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--history-only", action="store_true",
                      help="only download the group history into the cache (the weekly history workflow)")
    mode.add_argument("--no-history-download", action="store_true",
                      help="copy the fresh groups from the cache; download no group history")
    args = parser.parse_args(argv)
    if (args.history_only or args.no_history_download) and args.history_cache is None:
        parser.error("--history-only and --no-history-download need --history-cache")
    if args.groups == ACCEPTED and args.no_db:
        parser.error("--groups accepted reads the accepted config from the database, so it cannot run with --no-db")
    return args


def _history_plan(args: argparse.Namespace) -> HistoryPlan | None:
    """None when no group is wanted and no history mode is asked for: the build of before."""
    if not args.groups and not (args.history_only or args.no_history_download):
        return None
    return HistoryPlan(
        groups=args.groups,
        cache=args.history_cache or args.out / "history-cache",
        only=args.history_only,
        download=not args.no_history_download,
    )


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
        if args.groups == ACCEPTED:  # parse_args refused --no-db, so there is a connection
            row = repo.active_config(conn, str(Market.US))
            args.groups = accepted_groups(row.config if row else None)
        plan = _history_plan(args)
        history = None
        if plan is not None and plan.download:
            cache = HistoryCache(plan.cache)
            history = HistoryDeps(
                finra=client,
                fda=client,
                sec=sec,
                figis=FigiBook(client, cache.figi_path, RateLimiter(per_minute=OPENFIGI_PER_MINUTE)),
                cache=cache,
                names={info.symbol: info.name for info in listed[Market.US]},  # the whole US directory
                finra_limiter=RateLimiter(per_minute=FINRA_PER_MINUTE, burst=2),
                yahoo_limiter=RateLimiter(per_minute=YAHOO_PER_MINUTE, burst=2),
                fda_limiter=RateLimiter(per_minute=OPENFDA_PER_MINUTE, burst=2),
            )
        deps = BuildDeps(
            http=client,
            sec=sec,
            universe=lambda market: [info.symbol for info in listed[market]],
            conn=conn,
            history=history,
        )
        try:
            manifest = build(args.out, now, deps, limit=args.limit, history=plan)
        except BuildFailed as exc:
            log.error("%s (see %s)", exc, args.out / "manifest.json", exc_info=exc.__cause__ or exc)
            return 1
    print(json.dumps({k: v for k, v in manifest.items() if k != "missing"}))
    if plan is not None and plan.only:
        failed = sorted(set(manifest.get("unavailable", {})) & plan.groups)
        if failed:
            log.error("history groups unavailable, earlier files kept: %s (see %s)", ", ".join(failed),
                      args.out / "manifest.json")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
