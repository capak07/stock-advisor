"""Run orchestrator: one pre-open, pre-close, or early-close pass of the pipeline.

Usage: python -m advisor.run [--force-kind pre_open|pre_close|early_close] [--now ISO-8601]
"""

import argparse
import contextlib
import json
import math
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta

import httpx
import pandas as pd
import psycopg

from advisor import screener
from advisor.coin_list import refresh_coin_list
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
from advisor.collectors.sec_xbrl import FinancialFact
from advisor.collectors.tracker import SourceTracker
from advisor.collectors.yfinance_bars import Downloader, yahoo_download
from advisor.company_names import CompanyNames
from advisor.config import Settings
from advisor.crypto_prices import BARS, CHECK, CRYPTO_STAGE, QUOTES, crypto_feature_rows
from advisor.enrich import EnrichTargets, interleave, ranked_shortlist, run_enrichment
from advisor.grade import grade_stage
from advisor.history import record as record_price_history
from advisor.markets import BENCHMARKS, MARKETS, market_of
from advisor.model.crypto import BTC, CRYPTO
from advisor.model.crypto_live import coin_costs, forecast_coins
from advisor.model.live import bars_frame, facts_frame, live_features, live_garch, split_events
from advisor.model.market_run import Forecast, MarketModel, feature_day, model_failure
from advisor.model.predict import load_active, predict_rows, screen_scores
from advisor.model.weekly import KIND
from advisor.models import ET, AssetRef, AssetType, DailyBar, Market, RunKind, RunStatus, SymbolInfo
from advisor.monitor.stage import monitor_stage
from advisor.news.mapping import TickerMap
from advisor.news.sentiment import Scorer, load_finbert
from advisor.news.stage import RECENT, WINDOW, process_news
from advisor.policy import DEFAULT_POLICY, policy_of
from advisor.portfolio.stage import advise_stage
from advisor.prices import PriceFetch, fetch_daily_bars, group_bars
from advisor.recommend.stage import recommend_stage
from advisor.schedule import freshness_floor, overdue_kinds, resolve_run_kind
from advisor.screener import ScreenRow
from advisor.store import repo
from advisor.store.db import connect
from advisor.training.prices import training_download
from advisor.training.sectors import SECTOR_ETFS, all_sector_etfs

MIN_PRICED_FRACTION = 0.5
RUN_BUDGET_SECONDS = 30 * 60  # spec §3; GitHub kills the job at 40 minutes
PRICES = "yfinance_bars"
PRICE_STAGE = frozenset({PRICES, *(spec.universe_source for spec in MARKETS.values())})
NEWS_HISTORY = timedelta(days=20)  # daily story counts behind the news volume z-score
SCORING_RESERVE_SECONDS = 120  # FinBERT runs only with this much of the run budget left
HISTORY_RECENT = timedelta(days=100)  # the chart's closes per run; the longer bar window is the model's
SECTOR_FUNDS = [etf for etfs in all_sector_etfs().values() for etf in etfs]


def no_scorer() -> Scorer | None:
    return None


@dataclass(frozen=True)
class RunDeps:
    conn: psycopg.Connection
    cache: DiskCache
    collectors: Mapping[str, Collector]
    names: CompanyNames = field(default_factory=CompanyNames)  # Google News queries by these
    news_scorer: Callable[[], Scorer | None] = no_scorer  # loads FinBERT; tests run without it
    # The price-history backfill's Yahoo download and Bank of Canada client; tests leave them off.
    download: Downloader | None = None
    http: httpx.Client | None = None
    # Yahoo's split events, for the US forecasts' fundamentals; tests leave it off (no events).
    split_download: Downloader | None = None


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
    models_ok: bool = True,
) -> RunStatus:
    if not (universe_ok and prices_ok):
        return RunStatus.FAILED
    if not holdings_ok:  # a held stock without a price is missing from the owner's advice
        return RunStatus.DEGRADED
    if not models_ok:  # a market's model stage failed: its prices still publish, its forecasts don't
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


INVEST_COINS = 15  # the largest coins forecast every run, held or not


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


def record_history(
    deps: RunDeps,
    now_utc: datetime,
    bars: Mapping[str, Sequence[DailyBar]],
    candles: Mapping[str, Sequence[DailyBar]],
    stocks: Sequence[str],
    coins: Sequence[str],
    results: Mapping[str, CollectorResult],
) -> dict:
    """Store the dashboard's daily closes and USD/CAD (Plan 5a). Errors land in the summary.

    Each stock's closes come from its last 100 days of bars only: every close given is rewritten,
    and the rest of the 400-day window is there for the model's features, not the chart.
    """
    valet = results.get("boc_valet")
    today = now_utc.astimezone(ET).date()
    recent = {s: [b for b in bars[s] if b.day >= today - HISTORY_RECENT] for s in stocks if s in bars}
    try:
        return record_price_history(
            deps.conn,
            today=today,
            stocks=stocks,
            stock_bars=recent,
            coins=coins,
            coin_bars=candles,
            valet=valet.records if valet is not None else [],
            download=deps.download,
            http=deps.http,
        )
    except Exception as exc:  # the price history is for the dashboard; it never fails a run
        return {"error": f"{type(exc).__name__}: {exc}"[:200]}


def load_models(conn: psycopg.Connection) -> tuple[dict[Market, MarketModel], dict[str, dict]]:
    """Each market's active model, loaded once per run, and its `summary["model"]` entry.

    A market without one, or whose model fails to load, gets neither the screener nor forecasts.
    """
    models: dict[Market, MarketModel] = {}
    summary: dict[str, dict] = {}
    for market in Market:
        try:
            active = load_active(conn, market)
            if active is None:  # no model, or one whose horizons are all uncalibrated
                none = repo.active_model(conn, KIND[market]) is None
                summary[market.value] = {"skipped": "no active model" if none else "no usable horizons"}
                continue
            labels = repo.stock_sectors(conn, market)
            stored = repo.active_model(conn, KIND[market])
        except Exception as exc:  # a broken model never stops the run's prices from publishing
            summary[market.value] = model_failure(exc)
            continue
        sectors = pd.DataFrame(labels, columns=["symbol", "sector", "industry"])
        # a model activated since load_active read it: its gate isn't this model's, so no picks
        metrics = stored.metrics if stored is not None and stored.version == active.version else {}
        models[market] = MarketModel(active, sectors, metrics)
        summary[market.value] = {
            "version": active.version, "screened": 0, "predicted": 0, "not_eligible": 0,
            "horizons": list(active.usable),
        }
    return models, summary


def load_crypto_model(conn: psycopg.Connection) -> tuple[MarketModel | None, dict]:
    """The active crypto model, or None when there is none. A broken file never fails the run."""
    try:
        active = load_active(conn, CRYPTO)
        if active is None:
            none = repo.active_model(conn, KIND[CRYPTO]) is None
            return None, {"skipped": "no active model" if none else "no usable horizons"}
        stored = repo.active_model(conn, KIND[CRYPTO])
    except Exception as exc:
        return None, model_failure(exc)
    metrics = stored.metrics if stored is not None and stored.version == active.version else {}
    sectors = pd.DataFrame(columns=["symbol", "sector", "industry"])
    return MarketModel(active, sectors, metrics), {
        "version": active.version, "predicted": 0, "horizons": list(active.usable),
    }


def model_features(
    market: Market,
    model: MarketModel,
    symbols: Sequence[str],
    bars: Mapping[str, Sequence[DailyBar]],
    kind: RunKind,
    now_utc: datetime,
    *,
    events: pd.DataFrame | None = None,
    facts: tuple[pd.DataFrame, pd.DataFrame] | None = None,
) -> pd.DataFrame:
    """Stage 6: the training code's features for `symbols` on the market's last session.

    Without `facts`, a US stock's fundamentals are missing; the screener uses none of them.
    """
    wanted = [*symbols, MARKETS[market].benchmark, *SECTOR_ETFS[market].values()]
    prices = bars_frame({s: bars[s] for s in dict.fromkeys(wanted) if s in bars})
    day, partial = feature_day(market, bars, kind, now_utc)
    if market is Market.US and facts is None:
        facts = facts_frame([])
    table, tickers = facts if facts is not None else (None, None)
    features = live_features(
        prices, market, day, sectors=model.sectors, partial_day=partial,
        events=events, facts=table, tickers=tickers,
    )
    garch = getattr(model.active.model, "garch", None)
    if garch is not None:  # a garch model reads each stock's GARCH volatility (Plan 6d); NaN without a fit
        features = features.join(live_garch(prices, market, day, garch, model.active.model.horizons))
    return features


def screen_market(
    market: Market,
    model: MarketModel,
    passed: Sequence[ScreenRow],
    bars: Mapping[str, Sequence[DailyBar]],
    kind: RunKind,
    now_utc: datetime,
) -> dict[str, float]:
    """Stage 3: the model's screener score per passing symbol it may score (as in training).

    An ineligible symbol, or a NaN or inf score, counts as none: those sort after every scored one.
    """
    if not passed:
        return {}
    features = model_features(market, model, [r.symbol for r in passed], bars, kind, now_utc)
    features = features[features["eligible"].astype(bool)]
    if features.empty:
        return {}
    scores = screen_scores(model.active, features)
    return {str(s): float(v) for s, v in scores.items() if math.isfinite(v)}


def model_feature_rows(features: pd.DataFrame, names: Sequence[str]) -> list[tuple[AssetRef, dict]]:
    """Each stock's model features for features_live, as JSON numbers (a missing one is left out).

    `model_eligible` says whether the model may score the stock: Plan 4 applies spec §10's fallback
    to a holding that got no forecast because it is not.
    """
    eligible = features["eligible"].astype(bool)
    rows = []
    present = [name for name in names if name in features.columns]
    for symbol, values in features[present].astype(float).iterrows():
        kept = {name: float(v) for name, v in values.items() if math.isfinite(v)}
        kept["model_eligible"] = bool(eligible[symbol])
        rows.append((AssetRef(str(symbol), AssetType.STOCK), kept))
    return rows


def forecast_market(
    deps: RunDeps,
    run_id: int,
    market: Market,
    model: MarketModel,
    symbols: Sequence[str],
    bars: Mapping[str, Sequence[DailyBar]],
    kind: RunKind,
    now_utc: datetime,
    results: Mapping[str, CollectorResult],
) -> tuple[dict, Forecast]:
    """Stage 7: forecasts for the `symbols` the model may score, and every one's model features.

    Training kept only eligible stock-days, so an ineligible stock gets `model_eligible: false` and
    no forecast. Returns the market's summary fields, and its features and forecasts for stage 8.

    US fundamentals come from the run's SEC facts. Split events are best-effort: without them a
    stock that split since its last filing gets off fundamentals, which beats no forecast at all.
    """
    added: dict = {}
    events, facts = None, None
    if market is Market.US:
        sec = results.get("sec_xbrl")
        filed = [f for f in (sec.records if sec is not None else []) if isinstance(f, FinancialFact)]
        facts = facts_frame(filed)
        if deps.split_download is not None and symbols:
            try:
                events = split_events(
                    symbols, now_utc.astimezone(ET).date(), download=deps.split_download
                )
            except Exception as exc:  # Yahoo throttling or the run budget: forecast without them
                added["split_events"] = f"failed: {type(exc).__name__}: {exc}"[:200]
    features = model_features(market, model, symbols, bars, kind, now_utc, events=events, facts=facts)
    benchmark = MARKETS[market].benchmark
    eligible = features[features["eligible"].astype(bool)]
    rows = predict_rows(model.active, eligible, benchmark) if not eligible.empty else []
    with deps.conn.transaction():  # a market's forecasts and their features land together or not at all
        repo.write_predictions(deps.conn, run_id, rows)
        repo.merge_features_live(
            deps.conn, run_id, model_feature_rows(features, model.active.model.features), now_utc
        )
    fields = {"predicted": len({r.symbol for r in rows}), "not_eligible": len(features) - len(eligible), **added}
    return fields, Forecast(features, list(rows))


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
    sources_error: str | None = None
    try:
        repo.write_sources(conn, deps.collectors)  # what the dashboard's Source health page lists
    except Exception as exc:  # the registry only feeds the dashboard; it never fails a run
        sources_error = f"{type(exc).__name__}: {exc}"[:200]
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
        # Assets with an active price alert that aren't held or watched, alphabetical: they're priced
        # and their closes stored, so the holding monitor can check the alert; nothing more.
        # The lookup belongs to the display-only monitor: a failure is recorded, never fails the run.
        monitor_error: str | None = None
        try:
            alerted = repo.alert_symbols(conn)
        except Exception as exc:
            alerted = set()
            monitor_error = f"{type(exc).__name__}: {exc}"[:200]
        alert_coins = sorted({r.symbol for r in alerted if r.asset_type is AssetType.CRYPTO} - set(crypto))
        # the largest coins are priced and forecast too, so the Invest page has coins to choose from;
        # only held and watched ones get enrichment, news, verdicts and actions, or can degrade the run
        priced_coins = list(dict.fromkeys([*crypto, *repo.top_coins(conn, INVEST_COINS)]))
        # Stocks grading waits on that aren't held or watched, such as one the owner has sold, and
        # stocks with only an alert: they're priced and their closes stored, and get no actions or verdicts.
        to_grade = [s for s in repo.symbols_to_grade(conn) if s not in priority]
        alert_stocks = sorted(
            {r.symbol for r in alerted if r.asset_type is AssetType.STOCK} - {*priority, *to_grade}
        )
        price_only = [*to_grade, *alert_stocks]

        # Phase 1: holdings and watchlist of both markets are priced and saved before anything
        # else can fail. The benchmarks come along for the dashboard's price history and, with the
        # sector ETFs, for the model's relative-strength features.
        first = fetch_prices(list(dict.fromkeys([*priority, *price_only, *BENCHMARKS, *SECTOR_FUNDS])))
        bars, flagged = dict(first.bars), dict(first.flagged)
        priority_rows = [screener.price_stats(s, bars[s]) for s in priority if s in bars]
        repo.write_features_live(
            conn, run_id, live_feature_rows(priority_rows, flagged, floors), now_utc
        )

        # Held and watched crypto too; CoinGecko's CAD quote is what values a crypto holding.
        quotes: dict[str, CryptoQuote] = {}
        candles: dict[str, list[DailyBar]] = {}
        crypto_features: dict[str, dict] = {}  # the holdings stage reads a coin's price check here
        if priced_coins or alert_coins:

            def crypto_records(name: str, symbols: Sequence[str] | None = None) -> list:
                asked = list(priced_coins if symbols is None else symbols)
                return list(tracker.run(name, asked).records) if asked and name in deps.collectors else []

            quotes = {quote.symbol: quote for quote in crypto_records(QUOTES)}
            # BTC's candles come along even when it isn't held: altcoin features are excess over BTC.
            # An alert-only coin gets its candles alone, for its stored closes: no quote, features or forecast.
            candle_symbols = list(dict.fromkeys([*priced_coins, *alert_coins, BTC]))
            candles, checks = group_bars(crypto_records(BARS, candle_symbols)), group_bars(crypto_records(CHECK))
            coin_rows = crypto_feature_rows(priced_coins, quotes, candles, checks, now_utc)
            repo.write_features_live(conn, run_id, coin_rows, now_utc)
            crypto_features = {ref.symbol: features for ref, features in coin_rows}

        # Phase 2: each market's universe, then one price fetch for everything not yet priced.
        universes: dict[Market, list[SymbolInfo]] = {}
        for market in Market:
            universes[market] = list(tracker.run(MARKETS[market].universe_source, []).records)
            if len(universes[market]) >= limits[market]:
                repo.upsert_symbols(conn, market, universes[market])
            deps.names.update({info.symbol: info.name for info in universes[market]})
        # The dashboard's search offers coins from this list (best-effort; never fails the run).
        coins = refresh_coin_list(conn, deps.http, now_utc) if deps.http is not None else "skipped"
        # A run that cannot publish skips the bulk fetch (about 7,400 Yahoo requests during a
        # TMX outage) but still retries the owner's unpriced holdings.
        universe_ok = all(len(universes[m]) >= limits[m] for m in Market)
        fetched = {*priority, *(s for s in price_only if s in bars)}  # a price-only stock isn't fetched twice
        rest = (
            sorted({r.symbol for u in universes.values() for r in u} - fetched)
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
        enriched = universe_ok and prices_ok

        # The models of stages 3 and 7, loaded once: a market whose load fails skips both. Every
        # model failure below is that market's alone, recorded in summary["model"]; it degrades the
        # run and never fails it.
        models, model_summary = load_models(conn)

        # Phase 2.5: the screener. A market with an active model ranks the survivors by its
        # screener score; one without (or whose screener fails) ranks them by dollar volume.
        scores: dict[Market, dict[str, float]] = {}
        for market, model in list(models.items()) if enriched else []:
            try:
                scores[market] = screen_market(
                    market, model, passes[market].passed, bars, kind, now_utc
                )
            except Exception as exc:
                model_summary[market.value] = model_failure(exc)
                del models[market]
            else:
                model_summary[market.value]["screened"] = len(scores[market])

        # Phase 3: enrichment, only for a run that can still publish.
        ranked = {
            m: ranked_shortlist(p.passed, priority, MARKETS[m].shortlist_size, scores=scores.get(m))
            for m, p in passes.items()
        }
        targets = EnrichTargets(
            priority_stocks=priority, crypto=crypto, ranked_stocks=interleave(*ranked.values())
        )
        news = empty_news_summary()
        price_history: dict = {}
        held_stocks = {ref.symbol for ref in held if ref.asset_type is AssetType.STOCK}
        picks_summary = {m.value: {"skipped": "the run can't publish"} for m in Market}
        verdicts_failure: dict | None = None
        actions_summary: dict = {"skipped": "the run can't publish"}
        graded_summary: dict = {"skipped": "the run can't publish"}
        monitor_summary: dict | None = {"skipped": "the run can't publish"}
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
            # Price history for the dashboard (Plan 5a), only from a run that can publish: a failed
            # run's prices may be why it failed. Its errors land in the summary, never fail the run.
            stocks = list(dict.fromkeys([*priority, *price_only, *targets.ranked_stocks, *BENCHMARKS]))
            price_history = record_history(deps, now_utc, bars, candles, stocks, [*crypto, *alert_coins], results)

            # The holding monitor: 8-Ks, quarters, earnings dates and insider trades from enrichment,
            # then the price alerts, checked against the closes just stored. Display only: a failure
            # is recorded in the summary and never degrades or fails the run.
            try:
                monitor_summary = monitor_stage(conn, results, now_utc)
            except Exception as exc:
                monitor_summary = None
                monitor_error = f"{type(exc).__name__}: {exc}"[:200]

            # Phase 3.5: forecasts for each market's holdings, watchlist and ranked shortlist, once
            # enrichment has brought the US filings. Each symbol is forecast once.
            forecasts: dict[Market, Forecast] = {}
            coin_rows: dict[str, list] = {}
            coin_why: dict[str, str] = {}
            coin_cost: dict[str, float] = {}
            coin_policy = DEFAULT_POLICY
            crypto_model, crypto_note = load_crypto_model(conn)
            if crypto_model is not None or "failed" in crypto_note:
                model_summary["crypto"] = crypto_note
            if crypto_model is not None and priced_coins:
                try:
                    history = {symbol: candles.get(symbol) or [] for symbol in dict.fromkeys([*priced_coins, BTC])}
                    spy = bars.get("SPY")
                    found, coin_why = forecast_coins(
                        crypto_model.active.model, history, spy[-1].close if spy else None, now_utc,
                    )
                    usable = set(crypto_model.active.usable)
                    version = crypto_model.active.version
                    forecast_for = set(priced_coins)
                    coin_rows = {
                        symbol: [replace(row, model_version=version) for row in its if row.horizon_days in usable]
                        for symbol, its in found.items()
                        if symbol in forecast_for
                    }
                    coin_rows = {symbol: its for symbol, its in coin_rows.items() if its}
                    coin_why = {
                        symbol: reason for symbol, reason in coin_why.items()
                        if symbol in forecast_for and symbol not in coin_rows
                    }
                    fee = repo.fee_settings(conn)[1]
                    priced = coin_costs(history, fee, now_utc)
                    coin_cost = {symbol: priced[symbol] for symbol in coin_rows if symbol in priced}
                    coin_policy = policy_of(crypto_model.metrics)
                    flat = [row for its in coin_rows.values() for row in its]
                    if flat:
                        with conn.transaction():
                            repo.write_predictions(conn, run_id, flat, asset_type="crypto")
                    model_summary["crypto"]["predicted"] = len(coin_rows)
                except Exception as exc:
                    model_summary["crypto"] = model_failure(exc)
                    coin_rows, coin_why, coin_cost = {}, {}, {}
                    coin_policy = DEFAULT_POLICY
            for market, model in models.items():
                own = [s for s in priority if market_of(s) is market]
                symbols = list(dict.fromkeys([*own, *ranked[market]]))
                try:
                    fields, forecasts[market] = forecast_market(
                        deps, run_id, market, model, symbols, bars, kind, now_utc, results
                    )
                    model_summary[market.value] |= fields
                except Exception as exc:  # its screener still ranked the shortlist: keep the version
                    kept = {k: model_summary[market.value][k] for k in ("version", "screened")}
                    model_summary[market.value] = kept | model_failure(exc)

            # Stage 8: picks and watchlist verdicts, after every earlier stage's writes. It catches
            # its own failures per market; the guard here only backs that up, so prices always publish.
            try:
                picks_summary, verdicts_failure, advice = recommend_stage(
                    conn, run_id, models, forecasts, model_summary, bars, flagged, held_stocks, watch,
                    results, kind, now_utc, coin_rows, coin_cost, coin_policy, coin_why,
                )
            except Exception as exc:
                picks_summary = {m.value: model_failure(exc) for m in Market}
                verdicts_failure = model_failure(exc)  # no verdicts were written either
                advice = {}  # its holdings get the fallback rules

            # The holdings stage: one action per holding and account, after stage 8's writes. It
            # catches its own failures too; this guard backs that up, so prices always publish.
            try:
                actions_summary = advise_stage(
                    conn, run_id, models=models, forecasts=forecasts, advice=advice,
                    model_summary=model_summary, bars=bars, flagged=flagged, quotes=quotes,
                    candles=candles, crypto_features=crypto_features, results=results, kind=kind,
                    now_utc=now_utc, coin_rows=coin_rows, coin_cost=coin_cost, coin_why=coin_why,
                    coin_policy=coin_policy,
                )
            except Exception as exc:
                actions_summary = model_failure(exc)

            # Stage 9: grading, after the holdings stage, so this run's own picks and actions are
            # in too. It catches its own failures; this guard backs that up, so prices always publish.
            try:
                forecast_rows = {s: r for a in advice.values() for s, r in a.inputs.rows.items()}
                policies = {market.value: policy_of(model.metrics) for market, model in models.items()}
                graded_summary = grade_stage(conn, run_id, bars, forecast_rows, kind, now_utc, policies)
            except Exception as exc:
                graded_summary = model_failure(exc)

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
            "coins": coins,
            "news": news,
            "history": price_history,
            "model": model_summary,
            "picks": picks_summary,
            "actions": actions_summary,
            "graded": graded_summary,
        }
        if monitor_summary is not None:
            summary["holding_monitor"] = monitor_summary
        if monitor_error is not None:
            summary["holding_monitor_error"] = monitor_error
        if verdicts_failure is not None:
            summary["verdicts"] = verdicts_failure
        model_version = ",".join(m["version"] for m in model_summary.values() if "version" in m)
        held_crypto = {ref.symbol for ref in held if ref.asset_type is AssetType.CRYPTO}
        status = decide_status(
            tracker.merged(),
            deps.collectors,
            universe_ok=universe_ok,
            prices_ok=prices_ok,
            holdings_ok=held_stocks <= bars.keys() and held_crypto <= quotes.keys(),
            # a failed model, market's picks, the verdicts, the holdings' actions or grading degrade
            # the run; prices still publish
            models_ok=not any("failed" in m for m in [*model_summary.values(), *picks_summary.values()])
            and verdicts_failure is None
            and "failed" not in actions_summary
            and "failed" not in graded_summary,
        )
        if status is RunStatus.FAILED:
            summary["failed_reason"] = [
                reason
                for p in passes.values()
                for reason in p.failed_reasons(prices_checked=universe_ok)
            ]
        if sources_error is not None:
            summary["sources_error"] = sources_error
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
        model_version=model_version or None,
    )
    return RunOutcome(run_id, status, summary)


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="advisor.run")
    parser.add_argument("--force-kind", choices=[kind.value for kind in RunKind])
    parser.add_argument("--now", help="ISO-8601 timestamp to use instead of the current time")
    return parser.parse_args(argv)


def _check_overdue(now: datetime) -> int:
    """A trigger outside every window: fail (exit 1 emails the owner) if a slot whose window
    closed today has no published run, else exit quietly."""
    overdue = overdue_kinds(now)
    if not overdue:
        print(f"{now.isoformat()}: outside every run window or market closed; nothing to do.")
        return 0
    today = now.astimezone(ET).date()
    with connect(Settings.from_env().database_url) as conn:
        never_ran = [kind for kind in overdue if not repo.has_published_run(conn, kind, today)]
    if never_ran:
        for kind in never_ran:
            print(f"{now.isoformat()}: {kind.value} run for {today} never ran (its trigger came late or not at all).")
        return 1
    print(f"{now.isoformat()}: outside every run window; today's due runs are published; nothing to do.")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    now = datetime.fromisoformat(args.now) if args.now else datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)

    kind = RunKind(args.force_kind) if args.force_kind else resolve_run_kind(now)
    if kind is None:
        return _check_overdue(now)

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
                download=yahoo_download,
                http=client,
                split_download=training_download,
            )
            outcome = execute_run(deps, kind, now)

    print(json.dumps({"run_id": outcome.run_id, "status": outcome.status.value, **outcome.summary}))
    return 1 if outcome.status is RunStatus.FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
