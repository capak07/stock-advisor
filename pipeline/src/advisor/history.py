"""Daily closes and USD/CAD for the dashboard's charts and CAD values (Plan 5a).

**Closes.**
- Stocks: Yahoo's split- and dividend-adjusted closes from the run's bars, for holdings, the
  watchlist, the ranked shortlist and the two benchmarks (SPY, XIU.TO).
- Crypto: Coinbase's daily closes, in USD, for held and watched coins.
- A symbol ever bought, a watched stock and the benchmarks reach back a year, or to the first buy
  if that's earlier. The first run that finds one short backfills it from Yahoo in one call. Yahoo
  sometimes drops a symbol from a download (yfinance's cache can report "database is locked");
  it stays short, so the next run asks again.
- Every run fetches 290 days of a coin's candles. A coin ever bought reaches back a year, or to
  its first buy, through Coinbase's older candles, 300 days a request (Plan 5c).
- After two years, closes are pruned, except for symbols ever bought and the benchmarks.

**Splits and dividends.** Yahoo re-adjusts every close before a split or ex-dividend day. When a
run's oldest fresh closes all differ from the stored ones by one factor, the older stored closes
are rescaled by it, so a 2-for-1 split doesn't show as a 50% drop. A lone bad quote moves one
day, not all of them, so it changes nothing.

**USD/CAD.** The Bank of Canada's daily rate, from the run's Valet call, backfilled the same way.
"""

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, date, datetime, time, timedelta
from statistics import median

import httpx
import psycopg

from advisor.collectors.base import get_with_retries
from advisor.collectors.boc_valet import VALET_URL, parse_observations
from advisor.collectors.coinbase_candles import CANDLES_URL, ONE_DAY, parse_candles
from advisor.collectors.coins import listed_as
from advisor.collectors.series import SeriesObservation
from advisor.collectors.yfinance_bars import SYMBOLS_PER_DOWNLOAD, Downloader, parse_frame, to_yahoo
from advisor.markets import BENCHMARKS, market_of
from advisor.models import AssetRef, AssetType, DailyBar, DailyClose, Market
from advisor.prices import group_bars
from advisor.store import repo

HISTORY = timedelta(days=365)
KEEP = timedelta(days=730)
SLACK = timedelta(days=7)  # a start that falls on a long weekend isn't a gap
OVERLAP_DAYS = 5  # the oldest fresh days compared with stored closes
REBASE_TOLERANCE = 0.002  # within 0.2%: the same adjustment
REBASE_AGREEMENT = 0.01  # days within 1% of the median ratio agree on it
USD_CAD = "FXUSDCAD"
COIN_WINDOW = timedelta(days=300)  # Coinbase answers at most 300 daily candles a request
BENCHMARK_REFS = tuple(AssetRef(symbol, AssetType.STOCK) for symbol in BENCHMARKS)


def currency_of(ref: AssetRef) -> str:
    if ref.asset_type is AssetType.CRYPTO:
        return "USD"  # Coinbase quotes coins in USD
    return "CAD" if market_of(ref.symbol) is Market.TSX else "USD"


def closes_from_bars(
    bars: Mapping[str, Sequence[DailyBar]], refs: Iterable[AssetRef]
) -> list[DailyClose]:
    return [
        DailyClose(ref, bar.day, bar.close, currency_of(ref))
        for ref in refs
        for bar in bars.get(ref.symbol, ())
    ]


def rebase_factor(stored: Mapping[date, float], fresh: Sequence[DailyClose]) -> float | None:
    """The factor older stored closes need because Yahoo re-adjusted history, or None.

    It compares the oldest fresh days that are also stored. They're older than any split or
    ex-dividend day inside the fresh window, so they carry the same adjustment as the stored rows
    before it. Most of them (all, with fewer than three) must agree on one factor.
    """
    overlap = sorted((c.day, c.close) for c in fresh if c.day in stored)[:OVERLAP_DAYS]
    if not overlap:
        return None
    ratios = [close / stored[day] for day, close in overlap]
    factor = median(ratios)
    if abs(factor - 1) <= REBASE_TOLERANCE:
        return None
    agreeing = [r for r in ratios if abs(r / factor - 1) <= REBASE_AGREEMENT]
    return factor if len(agreeing) >= min(3, len(ratios)) else None


def store_closes(conn: psycopg.Connection, closes: Sequence[DailyClose]) -> list[str]:
    """Write closes, first rescaling older stored ones that Yahoo re-adjusted.

    A stock's rescale also rescales the prices picks and holding actions recorded for it before
    this run (`repo.rescale_refs`), so a split mid-hold isn't graded as a stop-out.

    All of it happens in one transaction: a rescale kept without its fresh closes would be found,
    and applied, again by the next run. Returns the rescaled symbols.
    """
    by_ref: dict[AssetRef, list[DailyClose]] = defaultdict(list)
    for close in closes:
        by_ref[close.ref].append(close)
    if not by_ref:
        return []
    stored = repo.stored_closes(conn, by_ref, min(c.day for c in closes))
    rescaled = []
    with conn.transaction():
        for ref, fresh in by_ref.items():
            factor = rebase_factor(stored.get(ref, {}), fresh)
            if factor is not None:
                repo.rescale_closes(conn, ref, min(c.day for c in fresh), factor)
                if ref.asset_type is AssetType.STOCK:  # the refs grading and trailing stops compare with
                    repo.rescale_refs(conn, ref, factor)
                rescaled.append(ref.symbol)
        repo.write_daily_closes(conn, closes)
    return sorted(rescaled)


def backfill_starts(
    today: date,
    first_buys: Mapping[AssetRef, date],
    watched: Iterable[AssetRef],
    earliest: Mapping[AssetRef, date],
) -> dict[AssetRef, date]:
    """Where each stock's closes should start, for those whose stored closes don't reach it."""
    year_ago = today - HISTORY
    wanted = {ref: min(year_ago, day) for ref, day in first_buys.items()}
    for ref in watched:
        wanted.setdefault(ref, year_ago)
    oldest_buy = min(first_buys.values(), default=year_ago)
    for ref in BENCHMARK_REFS:
        wanted[ref] = min(year_ago, oldest_buy)
    return {
        ref: start
        for ref, start in wanted.items()
        if ref.asset_type is AssetType.STOCK and (ref not in earliest or earliest[ref] > start + SLACK)
    }


def download_closes(
    starts: Mapping[AssetRef, date], today: date, download: Downloader
) -> list[DailyClose]:
    """Yahoo history for the backfill, 100 symbols a call, each call from its earliest start."""
    refs = sorted(starts, key=lambda ref: (starts[ref], ref.symbol))
    closes: list[DailyClose] = []
    for i in range(0, len(refs), SYMBOLS_PER_DOWNLOAD):
        batch = refs[i : i + SYMBOLS_PER_DOWNLOAD]
        yahoo = {to_yahoo(ref.symbol): ref.symbol for ref in batch}
        frame = download(list(yahoo), min(starts[ref] for ref in batch), today + timedelta(days=1))
        closes += closes_from_bars(group_bars(parse_frame(frame, yahoo)), batch)
    return closes


def coin_backfill_starts(
    today: date, first_buys: Mapping[AssetRef, date], earliest: Mapping[AssetRef, date]
) -> dict[AssetRef, date]:
    """Where each coin ever bought should start, for those whose stored closes don't reach it."""
    year_ago = today - HISTORY
    starts = {
        ref: min(year_ago, day) for ref, day in first_buys.items() if ref.asset_type is AssetType.CRYPTO
    }
    return {
        ref: start
        for ref, start in starts.items()
        if ref not in earliest or earliest[ref] > start + SLACK
    }


def fetch_coin_closes(client: httpx.Client, ref: AssetRef, start: date, end: date) -> list[DailyClose]:
    """Coinbase's daily USD closes from `start` up to, not including, `end`, 300 days a request.

    A coin Coinbase doesn't list (404) has none.
    """
    product = f"{listed_as(ref.symbol)}-USD"
    closes: list[DailyClose] = []
    window = start
    while window < end:
        stop = min(window + COIN_WINDOW, end)
        try:
            response = get_with_retries(
                client,
                CANDLES_URL.format(product=product),
                params={"granularity": ONE_DAY, "start": f"{window}T00:00:00Z", "end": f"{stop}T00:00:00Z"},
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return []
            raise
        bars = parse_candles(ref.symbol, response.json(), datetime.combine(stop, time(), UTC))
        closes += [DailyClose(ref, bar.day, bar.close, "USD") for bar in bars if bar.day >= window]
        window = stop
    return closes


def usd_cad(records: Iterable[SeriesObservation]) -> list[tuple[date, float]]:
    return sorted({record.day: record.value for record in records if record.series == USD_CAD}.items())


def fetch_usd_cad(client: httpx.Client, start: date) -> list[tuple[date, float]]:
    response = get_with_retries(
        client, VALET_URL.format(series=USD_CAD), params={"start_date": start.isoformat()}
    )
    return usd_cad(parse_observations(response.json(), [USD_CAD]))


def fx_backfill_start(
    today: date, first_buys: Mapping[AssetRef, date], earliest: date | None
) -> date | None:
    start = min(today - HISTORY, min(first_buys.values(), default=today - HISTORY))
    return start if earliest is None or earliest > start + SLACK else None


def record(
    conn: psycopg.Connection,
    *,
    today: date,
    stocks: Iterable[str],
    stock_bars: Mapping[str, Sequence[DailyBar]],
    coins: Iterable[str],
    coin_bars: Mapping[str, Sequence[DailyBar]],
    valet: Iterable[SeriesObservation],
    download: Downloader | None,
    http: httpx.Client | None,
) -> dict:
    """The run's history step. A failed backfill is reported in the summary, not raised."""
    stock_refs = [AssetRef(s, AssetType.STOCK) for s in sorted(set(stocks))]
    coin_refs = [AssetRef(c, AssetType.CRYPTO) for c in sorted(set(coins))]
    closes = closes_from_bars(stock_bars, stock_refs) + closes_from_bars(coin_bars, coin_refs)
    rescaled = store_closes(conn, closes)
    summary: dict = {"closes": len(closes), "backfilled": [], "fx": 0}

    buys = repo.first_buys(conn)
    watched = repo.load_watchlist(conn)
    history_refs = {*buys, *watched, *BENCHMARK_REFS}
    starts = backfill_starts(today, buys, watched, repo.earliest_closes(conn, history_refs))
    if starts and download is not None:
        try:
            fetched = download_closes(starts, today, download)
            rescaled += store_closes(conn, fetched)
            got = {c.ref for c in fetched}
            summary["backfilled"] = sorted(ref.symbol for ref in got)
            if missing := sorted(ref.symbol for ref in starts if ref not in got):
                summary["backfill_missing"] = missing  # still short, so the next run asks again
        except Exception as exc:  # Yahoo is unofficial: a failed backfill waits for the next run
            summary["backfill_error"] = f"{type(exc).__name__}: {exc}"[:200]

    earliest_coins = repo.earliest_closes(conn, [ref for ref in buys if ref.asset_type is AssetType.CRYPTO])
    coin_starts = coin_backfill_starts(today, buys, earliest_coins)
    if coin_starts and http is not None:
        try:
            fetched = [
                close
                for ref, start in sorted(coin_starts.items())
                for close in fetch_coin_closes(http, ref, start, earliest_coins.get(ref, today))
            ]
            store_closes(conn, fetched)
            got = {c.ref for c in fetched}
            summary["backfilled"] = sorted([*summary["backfilled"], *(ref.symbol for ref in got)])
            if missing := sorted(ref.symbol for ref in coin_starts if ref not in got):
                summary["backfill_missing"] = sorted([*summary.get("backfill_missing", []), *missing])
        except Exception as exc:  # Coinbase's history waits for the next run
            summary["coin_backfill_error"] = f"{type(exc).__name__}: {exc}"[:200]

    rates = usd_cad(valet)
    repo.write_fx_rates(conn, rates)
    fx_start = fx_backfill_start(today, buys, repo.earliest_fx_rate(conn))
    if fx_start is not None and http is not None:
        try:
            older = fetch_usd_cad(http, fx_start)
            repo.write_fx_rates(conn, older)
            rates += older
        except Exception as exc:
            summary["fx_error"] = f"{type(exc).__name__}: {exc}"[:200]
    summary["fx"] = len({day for day, _ in rates})
    summary["rescaled"] = sorted(set(rescaled))
    summary["pruned"] = repo.prune_daily_closes(conn, today - KEEP, BENCHMARKS)
    return summary
