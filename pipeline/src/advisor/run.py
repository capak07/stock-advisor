"""Run orchestrator: one pre-open, pre-close, or early-close pass of the pipeline.

Usage: python -m advisor.run [--force-kind pre_open|pre_close|early_close] [--now ISO-8601]
"""

import argparse
import contextlib
import json
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

import psycopg

from advisor import screener
from advisor.collectors.base import (
    Category,
    Collector,
    CollectorResult,
    CollectorStatus,
    make_client,
)
from advisor.collectors.cache import DiskCache
from advisor.collectors.coingecko import CryptoQuote
from advisor.collectors.registry import build_registry
from advisor.collectors.tracker import SourceTracker
from advisor.company_names import CompanyNames
from advisor.config import Settings
from advisor.crypto_prices import BARS, CHECK, CRYPTO_STAGE, QUOTES, crypto_feature_rows
from advisor.enrich import EnrichTargets, interleave, ranked_shortlist, run_enrichment
from advisor.markets import MARKETS, market_of
from advisor.models import ET, AssetRef, AssetType, DailyBar, Market, RunKind, RunStatus, SymbolInfo
from advisor.news.mapping import TickerMap
from advisor.news.sentiment import Scorer, load_finbert
from advisor.news.stage import RECENT, WINDOW, process_news
from advisor.prices import PriceFetch, fetch_daily_bars, group_bars
from advisor.schedule import freshness_floor, missed_run_kind, resolve_run_kind
from advisor.screener import ScreenRow
from advisor.store import repo
from advisor.store.db import connect

MIN_PRICED_FRACTION = 0.5
RUN_BUDGET_SECONDS = 30 * 60  # spec §3; GitHub kills the job at 40 minutes
PRICES = "yfinance_bars"
PRICE_STAGE = frozenset({PRICES, *(spec.universe_source for spec in MARKETS.values())})
NEWS_HISTORY = timedelta(days=20)  # daily story counts behind the news volume z-score
SCORING_RESERVE_SECONDS = 120  # FinBERT runs only with this much of the run budget left


def no_scorer() -> Scorer | None:
    return None


@dataclass(frozen=True)
class RunDeps:
    conn: psycopg.Connection
    cache: DiskCache
    collectors: Mapping[str, Collector]
    names: CompanyNames = field(default_factory=CompanyNames)  # Google News queries by these
    news_scorer: Callable[[], Scorer | None] = no_scorer  # loads FinBERT; tests run without it


@dataclass(frozen=True)
class RunOutcome:
    run_id: int
    status: RunStatus
    summary: dict


@dataclass(frozen=True)
class MarketPass:
    """One market's universe and price check (spec §10: either market failing fails the run)."""

    market: Market
    universe: int
    min_universe: int
    symbols: int  # the universe plus this market's priority symbols
    priced: int
    fresh: int
    fresh_since: date
    passed: list[ScreenRow]

    @property
    def universe_ok(self) -> bool:
        return self.universe >= self.min_universe

    @property
    def prices_ok(self) -> bool:
        return self.symbols > 0 and self.fresh >= MIN_PRICED_FRACTION * self.symbols

    def failed_reasons(self, *, prices_checked: bool = True) -> list[str]:
        reasons = []
        if not self.universe_ok:
            reasons.append(
                f"{self.market}: universe too small ({self.universe} < {self.min_universe})"
            )
        empty = self.symbols == 0  # an empty market has no prices to report on
        if prices_checked and not self.prices_ok and not (empty and not self.universe_ok):
            reasons.append(
                f"{self.market}: too few fresh priced symbols ({self.fresh} of {self.symbols})"
            )
        return reasons


def check_market(
    market: Market,
    universe: Sequence[SymbolInfo],
    min_universe: int,
    priority: Sequence[str],
    bars: Mapping[str, Sequence[DailyBar]],
    floor: date,
) -> MarketPass:
    symbols = {s for s in priority if market_of(s) is market} | {r.symbol for r in universe}
    priced = {s: bars[s] for s in symbols if s in bars}
    return MarketPass(
        market=market,
        universe=len(universe),
        min_universe=min_universe,
        symbols=len(symbols),
        priced=len(priced),
        fresh=sum(1 for history in priced.values() if history[-1].day >= floor),
        fresh_since=floor,
        passed=screener.hard_filter(priced, fresh_since=floor),
    )


def decide_status(
    results: Sequence[CollectorResult],
    collectors: Mapping[str, Collector],
    *,
    universe_ok: bool,
    prices_ok: bool,
    holdings_ok: bool = True,
) -> RunStatus:
    if not (universe_ok and prices_ok):
        return RunStatus.FAILED
    if not holdings_ok:  # a held stock without a price is missing from the owner's advice
        return RunStatus.DEGRADED
    if any(collectors[r.name].core and r.status is not CollectorStatus.OK for r in results):
        return RunStatus.DEGRADED
    return RunStatus.SUCCESS


def live_feature_rows(
    rows: Sequence[ScreenRow], flagged: Mapping[str, set[date]], floors: Mapping[Market, date]
) -> list[tuple[AssetRef, dict]]:
    return [
        (
            AssetRef(r.symbol, AssetType.STOCK),
            {
                **r.as_features(),
                "stale": not r.is_fresh(floors[market_of(r.symbol)]),
                "unconfirmed_jump": r.last_day in flagged.get(r.symbol, ()),
            },
        )
        for r in rows
    ]


def priority_order(held: set[AssetRef], watch: set[AssetRef], asset_type: AssetType) -> list[str]:
    """Holdings first, then watchlist-only symbols, each alphabetical (spec §7.2)."""
    held_symbols = sorted(ref.symbol for ref in held if ref.asset_type is asset_type)
    watch_only = sorted(
        {ref.symbol for ref in watch if ref.asset_type is asset_type} - set(held_symbols)
    )
    return held_symbols + watch_only


def empty_news_summary() -> dict:
    return {"items": 0, "stories": 0, "rows": 0, "assets": 0, "sentiment": "not run"}


def news_stage(
    deps: RunDeps,
    run_id: int,
    results: Mapping[str, CollectorResult],
    targets: EnrichTargets,
    coin_names: Mapping[str, str],
    now_utc: datetime,
    deadline_at: float,
) -> dict:
    """Stage 5: store the run's stories and merge per-asset news features into features_live."""
    sources = {n for n, c in deps.collectors.items() if c.category is Category.NEWS}
    repo.prune_news_items(deps.conn, now_utc)
    if not sources:
        return empty_news_summary()
    items = [record for name in sources if name in results for record in results[name].records]
    refs = [AssetRef(s, AssetType.STOCK) for s in targets.stocks]
    refs += [AssetRef(s, AssetType.CRYPTO) for s in targets.crypto]
    ticker_map = TickerMap(dict(deps.names.items()), coin_names, refs)
    # Whole UTC days only: a partial first or last day would skew the volume baseline.
    history_end = (now_utc - RECENT).replace(hour=0, minute=0, second=0, microsecond=0)
    history = repo.news_daily_counts(deps.conn, refs, history_end - NEWS_HISTORY, history_end)
    stored = repo.recent_news(deps.conn, refs, now_utc - 2 * WINDOW)
    scorer: Scorer | None = None
    if not items:
        sentiment = "no items"
    elif time.monotonic() > deadline_at - SCORING_RESERVE_SECONDS:
        sentiment = "skipped: run budget"
    else:
        try:
            scorer = deps.news_scorer()
        except Exception as exc:  # a failed model download must not fail the run
            sentiment = f"failed: {type(exc).__name__}: {exc}"[:200]
        else:
            sentiment = "finbert" if scorer is not None else "unavailable"
    try:
        outcome = process_news(
            items, ticker_map, refs, now_utc, scorer=scorer, history=history, stored=stored
        )
    except Exception as exc:
        if scorer is None:
            raise  # a bug in the stage itself fails the run (spec §10)
        sentiment = f"failed: {type(exc).__name__}: {exc}"[:200]  # scoring failed: keep the stories unscored
        outcome = process_news(
            items, ticker_map, refs, now_utc, scorer=None, history=history, stored=stored
        )
    repo.write_news_items(deps.conn, outcome.rows)
    if items:  # with no stories at all a source outage must leave the values missing, not zero
        repo.merge_features_live(deps.conn, run_id, outcome.features, now_utc)
    return {**outcome.summary, "sentiment": sentiment}


def execute_run(
    deps: RunDeps,
    kind: RunKind,
    now_utc: datetime,
    *,
    min_universe: Mapping[Market, int] | None = None,
    run_budget: float = RUN_BUDGET_SECONDS,
) -> RunOutcome:
    conn = deps.conn
    limits = {m: MARKETS[m].min_universe for m in Market} | dict(min_universe or {})
    # spec §10: a last bar older than its own market's floor counts as missing
    floors = {m: freshness_floor(kind, now_utc, market=m) for m in Market}
    repo.sweep_abandoned_runs(conn, now_utc)
    run_id = repo.create_run(conn, kind, now_utc.astimezone(ET).date())
    deadline_at = time.monotonic() + run_budget
    tracker = SourceTracker(
        deps.collectors,
        deps.cache,
        now_utc,
        repo.load_source_states(conn, deps.collectors),
        deadline_at=deadline_at,
    )

    def fetch_prices(symbols: Sequence[str]) -> PriceFetch:
        return fetch_daily_bars(symbols, run=lambda s: tracker.run(PRICES, s))

    def record_health() -> None:
        for result, failures in tracker.health_rows():
            repo.record_source_health(conn, run_id, result, failures, now_utc)

    try:
        held, watch = repo.load_held_symbols(conn), repo.load_watchlist(conn)
        priority = priority_order(held, watch, AssetType.STOCK)
        crypto = priority_order(held, watch, AssetType.CRYPTO)

        # Phase 1: holdings and watchlist of both markets are priced and saved before anything
        # else can fail.
        first = fetch_prices(priority) if priority else PriceFetch({}, {})
        bars, flagged = dict(first.bars), dict(first.flagged)
        priority_rows = [screener.price_stats(s, bars[s]) for s in priority if s in bars]
        repo.write_features_live(
            conn, run_id, live_feature_rows(priority_rows, flagged, floors), now_utc
        )

        # Held and watched crypto too; CoinGecko's CAD quote is what values a crypto holding.
        quotes: dict[str, CryptoQuote] = {}
        if crypto:

            def crypto_records(name: str) -> list:
                return list(tracker.run(name, crypto).records) if name in deps.collectors else []

            quotes = {quote.symbol: quote for quote in crypto_records(QUOTES)}
            candles, checks = group_bars(crypto_records(BARS)), group_bars(crypto_records(CHECK))
            repo.write_features_live(
                conn, run_id, crypto_feature_rows(crypto, quotes, candles, checks, now_utc), now_utc
            )

        # Phase 2: each market's universe, then one price fetch for everything not yet priced.
        universes: dict[Market, list[SymbolInfo]] = {}
        for market in Market:
            universes[market] = list(tracker.run(MARKETS[market].universe_source, []).records)
            if len(universes[market]) >= limits[market]:
                repo.upsert_symbols(conn, market, universes[market])
            deps.names.update({info.symbol: info.name for info in universes[market]})
        # A run that cannot publish skips the bulk fetch (about 7,400 Yahoo requests during a
        # TMX outage) but still retries the owner's unpriced holdings.
        universe_ok = all(len(universes[m]) >= limits[m] for m in Market)
        rest = (
            sorted({r.symbol for u in universes.values() for r in u} - set(priority))
            if universe_ok
            else []
        )
        # A priority symbol phase 1 left unpriced (Yahoo can miss silently) gets a second try.
        retry = [s for s in priority if s not in bars]
        if rest or retry:
            second = fetch_prices(rest + retry)
            recovered = [screener.price_stats(s, second.bars[s]) for s in retry if s in second.bars]
            repo.write_features_live(
                conn, run_id, live_feature_rows(recovered, second.flagged, floors), now_utc
            )
            bars = {**second.bars, **bars}
            flagged = {**second.flagged, **flagged}

        passes = {
            m: check_market(m, universes[m], limits[m], priority, bars, floors[m]) for m in Market
        }
        prices_ok = all(p.prices_ok for p in passes.values())

        # Phase 3: enrichment, only for a run that can still publish.
        ranked = {
            m: ranked_shortlist(p.passed, priority, MARKETS[m].shortlist_size)
            for m, p in passes.items()
        }
        targets = EnrichTargets(
            priority_stocks=priority, crypto=crypto, ranked_stocks=interleave(*ranked.values())
        )
        enriched = universe_ok and prices_ok
        news = empty_news_summary()
        if enriched:
            results = run_enrichment(
                tracker,
                deps.collectors,
                [name for name in deps.collectors if name not in PRICE_STAGE | CRYPTO_STAGE],
                targets,
            )
            # Stage 5: the news stage, over what the news sources fetched.
            coin_names = {q.symbol: q.name for q in quotes.values() if q.name}
            news = news_stage(deps, run_id, results, targets, coin_names, now_utc, deadline_at)

        summary = {
            "markets": {
                m.value: {
                    "universe": p.universe,
                    "priced": p.priced,
                    "passed_filters": len(p.passed),
                    "fresh": p.fresh,
                    "fresh_since": p.fresh_since.isoformat(),
                    "shortlist": len(ranked[m]) if enriched else 0,
                }
                for m, p in passes.items()
            },
            "priority": len(priority),
            "priority_unpriced": sorted(set(priority) - bars.keys()),
            # symbols whose latest bar is flagged (what the Review badge and Buy block use), not
            # every symbol with a flagged day somewhere in the lookback
            "unconfirmed_jumps": sum(
                1 for s, days in flagged.items() if s in bars and bars[s][-1].day in days
            ),
            "shortlist": len(targets.stocks) if enriched else 0,
            "crypto": len(crypto),
            "crypto_unquoted": sorted(set(crypto) - quotes.keys()),
            "news": news,
        }
        held_stocks = {ref.symbol for ref in held if ref.asset_type is AssetType.STOCK}
        held_crypto = {ref.symbol for ref in held if ref.asset_type is AssetType.CRYPTO}
        status = decide_status(
            tracker.merged(),
            deps.collectors,
            universe_ok=universe_ok,
            prices_ok=prices_ok,
            holdings_ok=held_stocks <= bars.keys() and held_crypto <= quotes.keys(),
        )
        if status is RunStatus.FAILED:
            summary["failed_reason"] = [
                reason
                for p in passes.values()
                for reason in p.failed_reasons(prices_checked=universe_ok)
            ]
    except Exception as exc:
        with contextlib.suppress(Exception):  # never let bookkeeping hide the real error
            record_health()
        repo.finish_run(
            conn, run_id, RunStatus.FAILED,
            sources_ok=tracker.count_healthy(),
            sources_total=len(deps.collectors),
            summary={"error": f"{type(exc).__name__}: {exc}"[:500]},
        )
        raise

    record_health()
    repo.finish_run(
        conn, run_id, status,
        sources_ok=tracker.count_healthy(),
        sources_total=len(deps.collectors),
        summary=summary,
    )
    return RunOutcome(run_id, status, summary)


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="advisor.run")
    parser.add_argument("--force-kind", choices=[kind.value for kind in RunKind])
    parser.add_argument("--now", help="ISO-8601 timestamp to use instead of the current time")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    now = datetime.fromisoformat(args.now) if args.now else datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)

    kind = RunKind(args.force_kind) if args.force_kind else resolve_run_kind(now)
    if kind is None:
        missed = missed_run_kind(now)
        if missed is not None:  # exit 1 fails the GitHub job, so the owner gets an email
            print(
                f"{now.isoformat()}: {missed.value} run window missed"
                " (trigger arrived too late); no run."
            )
            return 1
        print(f"{now.isoformat()}: outside every run window or market closed; nothing to do.")
        return 0

    settings = Settings.from_env()
    with connect(settings.database_url) as conn:
        if not args.force_kind and repo.has_published_run(conn, kind, now.astimezone(ET).date()):
            print(f"{kind.value} already published today; nothing to do.")
            return 0
        with make_client() as client:
            names = CompanyNames()
            deps = RunDeps(
                conn,
                DiskCache(settings.cache_dir, clock=lambda: now),
                build_registry(settings, client, names=names),
                names=names,
                news_scorer=load_finbert,
            )
            outcome = execute_run(deps, kind, now)

    print(json.dumps({"run_id": outcome.run_id, "status": outcome.status.value, **outcome.summary}))
    return 1 if outcome.status is RunStatus.FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
