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
from typing import Any

import httpx
import numpy as np
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
from advisor.collectors.clinical_trials import TrialActivity
from advisor.collectors.coingecko import CryptoQuote
from advisor.collectors.registry import build_registry
from advisor.collectors.sec_events import MaterialEvent
from advisor.collectors.sec_xbrl import FinancialFact
from advisor.collectors.tracker import SourceTracker
from advisor.collectors.yfinance_bars import Downloader, yahoo_download
from advisor.collectors.yfinance_earnings import EarningsReport
from advisor.company_names import CompanyNames
from advisor.config import Settings
from advisor.crypto_prices import BARS, CHECK, CRYPTO_STAGE, QUOTES, crypto_feature_rows
from advisor.enrich import EnrichTargets, interleave, ranked_shortlist, run_enrichment
from advisor.history import record as record_price_history
from advisor.markets import BENCHMARKS, MARKETS, market_of
from advisor.model.backtest import round_trip_cost
from advisor.model.features import PRICE_FEATURES, RS_FEATURES
from advisor.model.fundamentals import FUNDAMENTAL_FEATURES
from advisor.model.live import bars_frame, facts_frame, live_features, split_events
from advisor.model.predict import ActiveModel, load_active, predict_rows, screen_scores
from advisor.model.weekly import KIND
from advisor.models import (
    ET,
    AssetRef,
    AssetType,
    DailyBar,
    Market,
    PickRow,
    PredictionRow,
    RunKind,
    RunStatus,
    SymbolInfo,
)
from advisor.news.mapping import TickerMap
from advisor.news.sentiment import Scorer, load_finbert
from advisor.news.stage import RECENT, WINDOW, process_news
from advisor.prices import PriceFetch, fetch_daily_bars, group_bars
from advisor.recommend.picks import SWING_ATR, best_horizon, choose, rank_picks, stop_price
from advisor.recommend.risk import disagreement, risk_levels
from advisor.recommend.verdicts import Verdict, coin_verdict, stock_verdict
from advisor.schedule import freshness_floor, missed_run_kind, resolve_run_kind, sessions_after
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
PARTIAL_KINDS = frozenset({RunKind.PRE_CLOSE, RunKind.EARLY_CLOSE})  # runs during a session
EIGHT_K_DAYS = 3  # decision 11: 8-K filings this many days old or newer are a pick's catalysts
NOT_ELIGIBLE = "not eligible for the model (under $1, thin trading or new)"


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


@dataclass(frozen=True)
class MarketModel:
    """A market's active model, with the sector labels its relative-strength features compare by.

    `metrics` are the stored model's, which hold its backtest gate (`picks_enabled`, `picks_reason`).
    """

    active: ActiveModel
    sectors: pd.DataFrame
    metrics: Mapping[str, Any] = field(default_factory=dict)


def model_failure(exc: Exception) -> dict:
    return {"failed": f"{type(exc).__name__}: {exc}"[:200]}


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


def feature_day(
    market: Market, bars: Mapping[str, Sequence[DailyBar]], kind: RunKind, now_utc: datetime
) -> tuple[pd.Timestamp, bool]:
    """The market's last session (its benchmark's last bar), and whether that bar is still partial."""
    # On a 13:00 US early close the 15:15 TSX pre-close run calls a complete US bar partial: conservative.
    benchmark = MARKETS[market].benchmark
    if not bars.get(benchmark):
        raise ValueError(f"no {benchmark} bars")
    day = bars[benchmark][-1].day
    return pd.Timestamp(day), kind in PARTIAL_KINDS and day == now_utc.astimezone(ET).date()


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
    return live_features(
        prices, market, day, sectors=model.sectors, partial_day=partial,
        events=events, facts=table, tickers=tickers,
    )


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
    for symbol, values in features[list(names)].astype(float).iterrows():
        kept = {name: float(v) for name, v in values.items() if math.isfinite(v)}
        kept["model_eligible"] = bool(eligible[symbol])
        rows.append((AssetRef(str(symbol), AssetType.STOCK), kept))
    return rows


@dataclass(frozen=True)
class Forecast:
    """A market's stage-7 output that stage 8 recommends from."""

    features: pd.DataFrame  # one row per priced symbol, forecast or not (`eligible` says which)
    rows: list[PredictionRow]


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


@dataclass(frozen=True)
class StockInputs:
    """What the pick and verdict rules read for a market's forecast stocks, keyed by symbol."""

    day: date  # the market's feature day
    rows: dict[str, list[PredictionRow]]  # finite forecasts only
    sane: dict[str, bool]
    cost: dict[str, float]


def _finite(row: PredictionRow) -> bool:
    return all(math.isfinite(v) for v in (row.q10, row.q50, row.q90, row.p_beat))


def is_sane(
    symbol: str,
    features: pd.DataFrame,
    bars: Mapping[str, Sequence[DailyBar]],
    flagged: Mapping[str, set[date]],
    day: date,
) -> bool:
    """Decision 8 (spec §6.1): today's data may back a pick.

    The last bar is on the feature day with a positive close and isn't a flagged jump, no jump in
    the last 5 sessions, and ATR is known and small enough that a swing stop, 2 ATR below entry,
    stays above zero (a pick needs a stop).
    """
    history = bars.get(symbol)
    if not history or symbol not in features.index:
        return False
    last = history[-1]
    if last.day != day or not last.close > 0 or last.day in flagged.get(symbol, ()):
        return False
    atr = float(features.at[symbol, "atr_14_pct"])
    return float(features.at[symbol, "jump_5d"]) == 0 and 0 <= atr < 1 / SWING_ATR  # NaN fails both


def stock_inputs(
    market: Market,
    forecast: Forecast,
    bars: Mapping[str, Sequence[DailyBar]],
    flagged: Mapping[str, set[date]],
    day: date,
    usd_fx_fee_pct: float,
) -> StockInputs:
    """Each forecast stock's finite rows, sanity flag and round-trip cost (the backtest gate's)."""
    by_symbol: dict[str, list[PredictionRow]] = {}
    for row in forecast.rows:
        by_symbol.setdefault(row.symbol, []).append(row)
    features = forecast.features
    rows, sane, cost = {}, {}, {}
    for symbol, its in by_symbol.items():
        rows[symbol] = [r for r in its if _finite(r)]  # a non-finite value never reaches the rules
        sane[symbol] = len(rows[symbol]) == len(its) and is_sane(symbol, features, bars, flagged, day)
        volume = features.at[symbol, "dollar_volume_20"] if symbol in features.index else math.nan
        cost[symbol] = float(round_trip_cost(market, np.array([volume], dtype=float), usd_fx_fee_pct)[0])
    return StockInputs(day, rows, sane, cost)


def _records(results: Mapping[str, CollectorResult], name: str, kind: type) -> list:
    result = results.get(name)
    return [r for r in (result.records if result is not None else []) if isinstance(r, kind)]


def _et_day(at: datetime) -> date:
    return at.astimezone(ET).date() if at.tzinfo is not None else at.date()


def scheduled_events(results: Mapping[str, CollectorResult]) -> dict[str, list[tuple[date, dict]]]:
    """Each stock's coming earnings reports and phase 2/3 trial completions (decisions 4 and 11)."""
    out: dict[str, dict[tuple, tuple[date, dict]]] = {}
    for report in _records(results, "yfinance_earnings", EarningsReport):
        day = _et_day(report.report_at)
        out.setdefault(report.symbol, {})[("earnings", day)] = (day, {"type": "earnings", "date": day.isoformat()})
    for trial in _records(results, "clinical_trials", TrialActivity):
        if trial.next_completion is not None:
            day, exact = trial.next_completion, trial.next_completion_exact
            out.setdefault(trial.symbol, {})[("trial", day)] = (
                day, {"type": "trial_completion", "date": day.isoformat(), "exact": exact},
            )
    return {symbol: list(events.values()) for symbol, events in out.items()}


def recent_filings(results: Mapping[str, CollectorResult], today: date) -> dict[str, list[tuple[date, dict]]]:
    """Each stock's 8-K filings from the last `EIGHT_K_DAYS` days (decision 11)."""
    out: dict[str, list[tuple[date, dict]]] = {}
    for event in _records(results, "sec_8k", MaterialEvent):
        if today - timedelta(days=EIGHT_K_DAYS) <= event.filing_date <= today:
            out.setdefault(event.symbol, []).append(
                (event.filing_date, {"type": "8-K", "date": event.filing_date.isoformat(), "items": list(event.items)})
            )
    return out


def risk_frame(
    market: Market,
    features: pd.DataFrame,
    width: Mapping[str, float],
    event: Mapping[str, float],
    news: Mapping[str, float],
) -> pd.DataFrame:
    """`risk_levels`' input for the market's forecast stocks (the keys of `width`), decisions 1-6."""
    symbols = list(width)
    f = features.reindex(symbols)

    def column(name: str) -> pd.Series:  # a feature the market doesn't have is missing for all
        return f[name].astype(float) if name in f else pd.Series(math.nan, index=symbols)

    sentiment = pd.Series([news.get(s, math.nan) for s in symbols], index=symbols, dtype=float)
    fundamental = column("rev_growth")  # US only
    groups = [f.reindex(columns=PRICE_FEATURES), f.reindex(columns=RS_FEATURES)]
    if market is Market.US:
        groups.append(f.reindex(columns=FUNDAMENTAL_FEATURES))
    missing = [g.astype(float).isna().all(axis=1) for g in groups]
    missing.append(pd.Series([s not in news for s in symbols], index=symbols))  # the news group
    return pd.DataFrame(
        {
            "vol_60": column("vol_60"),
            "width": pd.Series(width, dtype=float),
            "disagreement": [
                disagreement(t, u, n)
                for t, u, n in zip(column("ex_bench_63"), fundamental, sentiment, strict=True)
            ],
            "log_adv20": column("log_adv20"),
            "event": pd.Series(event, dtype=float).reindex(symbols),
            "log_mcap": column("log_mcap"),  # US only: a TSX stock has no size component or floor
            "groups_missing_share": sum(m.astype(float) for m in missing) / len(missing),
        },
        index=symbols,
    )


def recommend_market(
    market: Market,
    model: MarketModel,
    forecast: Forecast,
    inputs: StockInputs,
    bars: Mapping[str, Sequence[DailyBar]],
    held: set[str],
    news: Mapping[str, float],
    results: Mapping[str, CollectorResult],
    today: date,
) -> tuple[list[PickRow], dict[str, dict], dict]:
    """Stage 8 for one market: its picks, the pick fields of every qualifying stock (a watched Buy
    carries them), and its `summary["picks"]` entry.

    Every qualifying stock gets the fields, held or not and enabled or not; only a market whose
    backtest gate passed gets picks, and never of a stock already held (decision 7).
    """
    day = inputs.day
    population = {s: rows for s, rows in inputs.rows.items() if rows}
    choices = {
        s: c for s, rows in population.items() if (c := choose(rows, inputs.cost[s], inputs.sane[s])) is not None
    }
    # decision 2: the chosen horizon, else the best-ratio one, sets the risk width and event window
    horizon: dict[str, int] = {}
    width: dict[str, float] = {}
    for s, rows in population.items():
        chosen, best = choices.get(s), best_horizon(rows)
        if chosen is not None:
            horizon[s], width[s] = chosen.horizon, chosen.q90 - chosen.q10
        elif best is not None:
            horizon[s], width[s] = best.horizon_days, best.q90 - best.q10
        else:  # no horizon with a positive width: no width, and no hold to hold an event
            width[s] = math.nan
    exits = {h: sessions_after(market, day, h) for h in set(horizon.values())}
    scheduled = scheduled_events(results)
    in_hold = {
        s: [(d, e) for d, e in scheduled.get(s, []) if day < d <= exits[h]] for s, h in horizon.items()
    }
    event = {s: float(bool(in_hold[s])) if s in horizon else math.nan for s in population}

    enabled = model.metrics.get("picks_enabled") is True
    if not population:
        return [], {}, {"swing": 0, "position": 0} if enabled else {"disabled": picks_reason(model)}
    risk = risk_levels(risk_frame(market, forecast.features, width, event, news))

    factors: dict[str, list[dict]] = {}
    for h in {c.horizon for c in choices.values()}:
        at_h = [s for s, c in choices.items() if c.horizon == h]
        explained = model.active.model.contributions(forecast.features.loc[at_h], h)
        factors |= {
            str(s): [p for p in parts if math.isfinite(p["contribution"])] for s, parts in explained.items()
        }
    filings = recent_filings(results, today)
    details: dict[str, dict] = {}
    for s, c in choices.items():
        entry = bars[s][-1].close  # decision 9: the feature day's close (sanity checked the day)
        catalysts = sorted([*in_hold[s], *filings.get(s, [])], key=lambda pair: (pair[0], pair[1]["type"]))
        details[s] = {
            "style": c.style,
            "horizon_days": c.horizon,
            "exit_by": exits[c.horizon].isoformat(),
            "entry_ref_price": entry,
            "stop": stop_price(c.style, entry, float(forecast.features.at[s, "atr_14_pct"])),
            "risk_level": str(risk.at[s, "risk_level"]),
            "risk_score": float(risk.at[s, "risk_score"]),
            "max_position_pct": float(risk.at[s, "max_position_pct"]),
            "top_factors": factors.get(s, []),
            "catalysts": [e for _, e in catalysts],
        }
    if not enabled:
        return [], details, {"disabled": picks_reason(model)}

    labels = model.sectors.drop_duplicates("symbol").set_index("symbol")["sector"]
    candidates = [c for s, c in choices.items() if s not in held]
    sectors = {c.symbol: (labels.get(c.symbol) if pd.notna(labels.get(c.symbol)) else None) for c in candidates}
    picks = []
    for c, rank in rank_picks(candidates, sectors):
        d = details[c.symbol]
        d["rank"] = rank
        picks.append(PickRow(
            c.symbol, market, c.style, c.horizon, exits[c.horizon], d["entry_ref_price"], d["stop"],
            d["risk_level"], d["risk_score"], d["max_position_pct"], rank, d["top_factors"], d["catalysts"],
        ))
    counts = {style: sum(1 for p in picks if p.style == style) for style in ("swing", "position")}
    return picks, details, counts


def picks_reason(model: MarketModel) -> str:
    reason = model.metrics.get("picks_reason")
    return str(reason) if reason else "the model has no backtest gate result"


def watch_verdicts(
    watch: set[AssetRef],
    forecasts: Mapping[Market, Forecast],
    inputs: Mapping[Market, StockInputs],
    details: Mapping[Market, dict[str, dict]],
    enabled: Mapping[Market, bool],
    no_forecast: Mapping[Market, str],
) -> list[Verdict]:
    """A verdict for every watched symbol (spec §6.5); each stock's says whether its market has picks."""
    verdicts = []
    for ref in sorted(watch):
        if ref.asset_type is AssetType.CRYPTO:
            verdicts.append(coin_verdict(ref.symbol))
            continue
        market = market_of(ref.symbol)
        if market not in inputs:
            verdict = stock_verdict(ref.symbol, [], 0.0, False, None, no_forecast[market])
        else:
            features, given = forecasts[market].features, inputs[market]
            if ref.symbol not in features.index:
                why = "not priced this run"
            elif not bool(features.at[ref.symbol, "eligible"]):
                why = NOT_ELIGIBLE
            else:
                why = "no forecast this run"
            verdict = stock_verdict(
                ref.symbol, given.rows.get(ref.symbol, []), given.cost.get(ref.symbol, 0.0),
                given.sane.get(ref.symbol, False), details.get(market, {}).get(ref.symbol), why,
            )
        flag = {"market_picks_enabled": enabled.get(market, False)}
        verdicts.append(replace(verdict, details={**verdict.details, **flag}))
    return verdicts


def recommend_stage(
    deps: RunDeps,
    run_id: int,
    models: Mapping[Market, MarketModel],
    forecasts: Mapping[Market, Forecast],
    model_summary: Mapping[str, dict],
    bars: Mapping[str, Sequence[DailyBar]],
    flagged: Mapping[str, set[date]],
    held: set[str],
    watch: set[AssetRef],
    results: Mapping[str, CollectorResult],
    kind: RunKind,
    now_utc: datetime,
) -> tuple[dict[str, dict], dict | None]:
    """Stage 8: each market's picks, then the watchlist's verdicts. Returns `summary["picks"]` and
    the verdicts' failure, if any. Every failure is caught here: it degrades the run, never fails it.
    """
    conn = deps.conn
    today = now_utc.astimezone(ET).date()
    summary: dict[str, dict] = {}
    inputs: dict[Market, StockInputs] = {}
    details: dict[Market, dict[str, dict]] = {}
    no_forecast: dict[Market, str] = {}
    for market in Market:
        if market not in forecasts:
            skipped = model_summary.get(market.value, {}).get("skipped")
            no_forecast[market] = skipped or "the model failed this run"
            summary[market.value] = {"skipped": skipped or "no forecasts: the model failed"}
            continue
        try:
            day = feature_day(market, bars, kind, now_utc)[0].date()
            fee = repo.fee_settings(conn)[0]
            inputs[market] = stock_inputs(market, forecasts[market], bars, flagged, day, fee)
            news = repo.news_sentiment(conn, run_id, list(inputs[market].rows))
            picks, found, summary[market.value] = recommend_market(
                market, models[market], forecasts[market], inputs[market], bars, held, news, results, today
            )
            with conn.transaction():  # a market's picks land together or not at all
                repo.write_picks(conn, run_id, picks)
            details[market] = found
        except Exception as exc:
            summary[market.value] = model_failure(exc)
            # a Buy must carry a pick's fields, and these weren't built: its stocks are Hold
            inputs.pop(market, None)
            no_forecast[market] = "the recommender failed this run"
    enabled = {m: model.metrics.get("picks_enabled") is True for m, model in models.items()}
    try:
        verdicts = watch_verdicts(watch, forecasts, inputs, details, enabled, no_forecast)
        with conn.transaction():
            repo.write_watchlist_verdicts(conn, run_id, verdicts)
    except Exception as exc:
        return summary, model_failure(exc)
    return summary, None


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

        # Phase 1: holdings and watchlist of both markets are priced and saved before anything
        # else can fail. The benchmarks come along for the dashboard's price history and, with the
        # sector ETFs, for the model's relative-strength features.
        first = fetch_prices([*priority, *BENCHMARKS, *SECTOR_FUNDS])
        bars, flagged = dict(first.bars), dict(first.flagged)
        priority_rows = [screener.price_stats(s, bars[s]) for s in priority if s in bars]
        repo.write_features_live(
            conn, run_id, live_feature_rows(priority_rows, flagged, floors), now_utc
        )

        # Held and watched crypto too; CoinGecko's CAD quote is what values a crypto holding.
        quotes: dict[str, CryptoQuote] = {}
        candles: dict[str, list[DailyBar]] = {}
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
        # The dashboard's search offers coins from this list (best-effort; never fails the run).
        coins = refresh_coin_list(conn, deps.http, now_utc) if deps.http is not None else "skipped"
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
            stocks = [*priority, *targets.ranked_stocks, *BENCHMARKS]
            price_history = record_history(deps, now_utc, bars, candles, stocks, crypto, results)

            # Phase 3.5: forecasts for each market's holdings, watchlist and ranked shortlist, once
            # enrichment has brought the US filings. Each symbol is forecast once.
            forecasts: dict[Market, Forecast] = {}
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
                picks_summary, verdicts_failure = recommend_stage(
                    deps, run_id, models, forecasts, model_summary, bars, flagged, held_stocks, watch,
                    results, kind, now_utc,
                )
            except Exception as exc:
                picks_summary = {m.value: model_failure(exc) for m in Market}

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
        }
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
            # a failed model, market's picks or the verdicts degrade the run; prices still publish
            models_ok=not any("failed" in m for m in [*model_summary.values(), *picks_summary.values()])
            and verdicts_failure is None,
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
                download=yahoo_download,
                http=client,
                split_download=training_download,
            )
            outcome = execute_run(deps, kind, now)

    print(json.dumps({"run_id": outcome.run_id, "status": outcome.status.value, **outcome.summary}))
    return 1 if outcome.status is RunStatus.FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
