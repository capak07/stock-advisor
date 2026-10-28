"""Stage 8: each market's picks and the watchlist's verdicts (spec §6), from the run's forecasts.

`recommend_stage` catches its own failures per market and for the verdicts: they degrade a run and
never stop its prices from publishing.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import psycopg

from advisor.collectors.base import CollectorResult
from advisor.collectors.clinical_trials import TrialActivity
from advisor.collectors.sec_events import MaterialEvent
from advisor.collectors.yfinance_earnings import EarningsReport
from advisor.markets import MARKETS, market_of
from advisor.model.backtest import round_trip_cost
from advisor.model.features import PRICE_FEATURES, RS_FEATURES
from advisor.model.fundamentals import FUNDAMENTAL_FEATURES
from advisor.model.market_run import Forecast, MarketModel, feature_day, model_failure
from advisor.models import (
    ET,
    AssetRef,
    AssetType,
    DailyBar,
    Market,
    PickRow,
    PredictionRow,
    RunKind,
)
from advisor.policy import DEFAULT_POLICY, Policy, policy_of
from advisor.recommend.picks import best_horizon, choose, rank_picks, stop_price
from advisor.recommend.risk import disagreement, risk_levels
from advisor.recommend.verdicts import Verdict, coin_verdict, stock_verdict
from advisor.schedule import sessions_after
from advisor.store import repo

EIGHT_K_DAYS = 3  # decision 11: 8-K filings this many days old or newer are a pick's catalysts
NOT_ELIGIBLE = "not eligible for the model (under $1, thin trading or new)"
RECOMMENDER_FAILED = "the recommender failed this run"


@dataclass(frozen=True)
class StockInputs:
    """What the pick and verdict rules read for a market's forecast stocks, keyed by symbol."""

    day: date  # the market's feature day
    # the feature day is today and its bar partial (a pre-close run): the entry is today's 3:15
    # price, so an event later today still falls inside the hold
    same_day: bool
    rows: dict[str, list[PredictionRow]]  # finite forecasts only
    sane: dict[str, bool]
    cost: dict[str, float]


@dataclass(frozen=True)
class MarketAdvice:
    """A market's stage-8 work that the holdings stage reuses, so holdings are judged on the same numbers."""

    inputs: StockInputs
    # every population stock (a forecast stock with finite rows), indexed by symbol: risk_level,
    # max_position_pct and the rest of `risk_levels`' output
    risk: pd.DataFrame


NO_RISK = pd.DataFrame({"risk_level": pd.Series(dtype=object), "max_position_pct": pd.Series(dtype=float)})


def _finite(row: PredictionRow) -> bool:
    return all(math.isfinite(v) for v in (row.q10, row.q50, row.q90, row.p_beat))


def is_sane(
    symbol: str,
    features: pd.DataFrame,
    bars: Mapping[str, Sequence[DailyBar]],
    flagged: Mapping[str, set[date]],
    day: date,
    policy: Policy = DEFAULT_POLICY,
) -> bool:
    """Decision 8 (spec §6.1): today's data may back a pick.

    The last bar is on the feature day with a positive close and isn't a flagged jump, no jump in
    the last 5 sessions, and ATR is known and small enough that a swing stop, 2 ATR below entry,
    stays above zero (a pick needs a stop).

    Deliberately stricter than the backtest's `simulate_picks`: a NaN `jump_5d` fails here, and the
    ATR bound has no backtest counterpart. Don't "fix" either side to match the other.
    """
    history = bars.get(symbol)
    if not history or symbol not in features.index:
        return False
    last = history[-1]
    if last.day != day or not last.close > 0 or last.day in flagged.get(symbol, ()):
        return False
    atr = float(features.at[symbol, "atr_14_pct"])
    return float(features.at[symbol, "jump_5d"]) == 0 and 0 <= atr < 1 / policy.swing_atr  # NaN fails both


def stock_inputs(
    market: Market,
    forecast: Forecast,
    bars: Mapping[str, Sequence[DailyBar]],
    flagged: Mapping[str, set[date]],
    day: date,
    same_day: bool,
    usd_fx_fee_pct: float,
    policy: Policy = DEFAULT_POLICY,
) -> StockInputs:
    """Each forecast stock's finite rows, sanity flag and round-trip cost (the backtest gate's)."""
    by_symbol: dict[str, list[PredictionRow]] = {}
    for row in forecast.rows:
        by_symbol.setdefault(row.symbol, []).append(row)
    features = forecast.features
    rows, sane, cost = {}, {}, {}
    for symbol, its in by_symbol.items():
        rows[symbol] = [r for r in its if _finite(r)]  # a non-finite value never reaches the rules
        sane[symbol] = len(rows[symbol]) == len(its) and is_sane(
            symbol, features, bars, flagged, day, policy
        )
        volume = features.at[symbol, "dollar_volume_20"] if symbol in features.index else math.nan
        cost[symbol] = float(round_trip_cost(market, np.array([volume], dtype=float), usd_fx_fee_pct)[0])
    return StockInputs(day, same_day, rows, sane, cost)


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


def hold_events(
    scheduled: Mapping[str, list[tuple[date, dict]]],
    windows: Mapping[str, tuple[date, date]],
    same_day: bool,
) -> dict[str, list[tuple[date, dict]]]:
    """Each stock's scheduled events inside its hold, `(feature day, exit-by]` per stock.

    With `same_day` (a pre-close run, whose entry is today's 3:15 price) the feature day counts too.
    """
    return {
        s: [(d, e) for d, e in scheduled.get(s, []) if (start <= d if same_day else start < d) and d <= end]
        for s, (start, end) in windows.items()
    }


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
    in_hold: Mapping[str, list],
    news: Mapping[str, float],
) -> pd.DataFrame:
    """`risk_levels`' input for the market's forecast stocks (the keys of `width`), decisions 1-6.

    `in_hold` holds each stock's events inside its hold; a stock missing from it has no hold.
    """
    symbols = list(width)
    f = features.reindex(symbols)
    missing_all = pd.Series(math.nan, index=symbols)

    def column(name: str) -> pd.Series:  # a feature the market doesn't have is missing for all
        return f[name].astype(float) if name in f else missing_all

    us = market is Market.US
    sentiment = pd.Series([news.get(s, math.nan) for s in symbols], index=symbols, dtype=float)
    fundamental = column("rev_growth") if us else missing_all  # fundamentals are US only
    event = [float(bool(in_hold[s])) if s in in_hold else math.nan for s in symbols]
    groups = [f.reindex(columns=PRICE_FEATURES), f.reindex(columns=RS_FEATURES)]
    if us:
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
            "event": event,
            "log_mcap": column("log_mcap") if us else missing_all,  # a TSX stock has no size term or floor
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
) -> tuple[list[PickRow], dict[str, dict], dict, pd.DataFrame, dict[str, dict]]:
    """Stage 8 for one market: its picks, the pick fields of every qualifying stock (a watched Buy
    carries them), its `summary["picks"]` entry, the risk of every stock with a forecast, and the
    advice each of those stocks' Ticker page explains it with (`features_live.features.advice`).

    Every qualifying stock gets the fields, held or not and enabled or not; only a market whose
    backtest gate passed gets picks, and never of a stock already held (decision 7).
    """
    day = inputs.day
    policy = policy_of(model.metrics)
    population = {s: rows for s, rows in inputs.rows.items() if rows}
    choices = {
        s: c for s, rows in population.items()
        if (c := choose(rows, inputs.cost[s], inputs.sane[s], policy)) is not None
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
    windows = {s: (day, exits[h]) for s, h in horizon.items()}
    in_hold = hold_events(scheduled_events(results), windows, inputs.same_day)

    enabled = model.metrics.get("picks_enabled") is True
    if not population:
        status = {"swing": 0, "position": 0} if enabled else {"disabled": picks_reason(model)}
        return [], {}, status, NO_RISK.copy(), {}
    risk = risk_levels(risk_frame(market, forecast.features, width, in_hold, news))

    # every stock with a hold is explained at it: a pick's factors, and any Ticker page's (Plan 4b)
    factors: dict[str, list[dict]] = {}
    for h in set(horizon.values()):
        at_h = [s for s, x in horizon.items() if x == h]
        explained = model.active.model.contributions(forecast.features.loc[at_h], h)
        factors |= {
            str(s): [p for p in parts if math.isfinite(p["contribution"])] for s, parts in explained.items()
        }
    filings = recent_filings(results, today)

    def catalysts_of(s: str) -> list[dict]:
        events = sorted([*in_hold.get(s, []), *filings.get(s, [])], key=lambda pair: (pair[0], pair[1]["type"]))
        return [e for _, e in events]

    explanations = {
        s: {
            "horizon": int(h),
            "top_factors": factors.get(s, []),
            "catalysts": catalysts_of(s),
            "round_trip_cost": float(inputs.cost[s]),
        }
        for s, h in horizon.items()
    }
    details: dict[str, dict] = {}
    for s, c in choices.items():
        entry = bars[s][-1].close  # decision 9: the feature day's close (sanity checked the day)
        details[s] = {
            "style": c.style,
            "horizon_days": c.horizon,
            "exit_by": exits[c.horizon].isoformat(),
            "entry_ref_price": entry,
            "stop": stop_price(c.style, entry, float(forecast.features.at[s, "atr_14_pct"]), policy),
            "risk_level": str(risk.at[s, "risk_level"]),
            "risk_score": float(risk.at[s, "risk_score"]),
            "max_position_pct": float(risk.at[s, "max_position_pct"]),
            "top_factors": factors.get(s, []),
            "catalysts": catalysts_of(s),
        }
    if not enabled:
        return [], details, {"disabled": picks_reason(model)}, risk, explanations

    labels = model.sectors.drop_duplicates("symbol").set_index("symbol")["sector"]
    candidates = [c for s, c in choices.items() if s not in held]
    sectors = {c.symbol: (labels.get(c.symbol) if pd.notna(labels.get(c.symbol)) else None) for c in candidates}
    bench_close = bars[MARKETS[market].benchmark][-1].close  # the benchmark's feature-day close
    picks = []
    for c, rank in rank_picks(candidates, sectors):
        d = details[c.symbol]
        d["rank"] = rank
        picks.append(PickRow(
            c.symbol, market, c.style, c.horizon, exits[c.horizon], d["entry_ref_price"], d["stop"],
            d["risk_level"], d["risk_score"], d["max_position_pct"], rank, d["top_factors"], d["catalysts"],
            day, bench_close,
        ))
    counts = {style: sum(1 for p in picks if p.style == style) for style in ("swing", "position")}
    return picks, details, counts, risk, explanations


def picks_reason(model: MarketModel) -> str:
    reason = model.metrics.get("picks_reason")
    return str(reason) if reason else "the model has no backtest gate result"


def why_no_forecast(symbol: str, features: pd.DataFrame) -> str:
    """Why a stock of a market that has forecasts got none itself."""
    if symbol not in features.index:
        return "not priced this run"
    if not bool(features.at[symbol, "eligible"]):
        return NOT_ELIGIBLE
    return "no forecast this run"


def missing_market_reason(market: Market, model_summary: Mapping[str, dict]) -> str:
    """Why a market has no forecasts at all: its model was skipped, or failed."""
    return model_summary.get(market.value, {}).get("skipped") or "the model failed this run"


def watch_verdicts(
    watch: set[AssetRef],
    held: set[str],
    forecasts: Mapping[Market, Forecast],
    inputs: Mapping[Market, StockInputs],
    details: Mapping[Market, dict[str, dict]],
    enabled: Mapping[Market, bool],
    no_forecast: Mapping[Market, str],
    policies: Mapping[Market, Policy] | None = None,
) -> list[Verdict]:
    """A verdict for every watched symbol (spec §6.5); each stock's says whether its market has picks.

    A watched stock that is also held keeps its verdict (never a pick, so no rank) and says `held`.
    """
    policies = policies or {}
    verdicts = []
    for ref in sorted(watch):
        if ref.asset_type is AssetType.CRYPTO:
            verdicts.append(coin_verdict(ref.symbol))
            continue
        market = market_of(ref.symbol)
        policy = policies.get(market, DEFAULT_POLICY)
        if market not in inputs:
            verdict = stock_verdict(ref.symbol, [], 0.0, False, None, no_forecast[market], policy)
        else:
            given = inputs[market]
            why = why_no_forecast(ref.symbol, forecasts[market].features)
            verdict = stock_verdict(
                ref.symbol, given.rows.get(ref.symbol, []), given.cost.get(ref.symbol, 0.0),
                given.sane.get(ref.symbol, False), details.get(market, {}).get(ref.symbol), why, policy,
            )
        flag = {"market_picks_enabled": enabled.get(market, False)}
        if ref.symbol in held:
            flag["held"] = True
        verdicts.append(replace(verdict, details={**verdict.details, **flag}))
    return verdicts


def recommend_stage(
    conn: psycopg.Connection,
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
) -> tuple[dict[str, dict], dict | None, dict[Market, MarketAdvice]]:
    """Stage 8: each market's picks, then the watchlist's verdicts. Returns `summary["picks"]`, the
    verdicts' failure, if any, and each market's `MarketAdvice` (none for a market that failed here).
    Every failure is caught here: it degrades the run, never fails it.
    """
    today = now_utc.astimezone(ET).date()
    summary: dict[str, dict] = {}
    inputs: dict[Market, StockInputs] = {}
    details: dict[Market, dict[str, dict]] = {}
    no_forecast: dict[Market, str] = {}
    advice: dict[Market, MarketAdvice] = {}
    for market in Market:
        if market not in forecasts:
            skipped = model_summary.get(market.value, {}).get("skipped")
            no_forecast[market] = missing_market_reason(market, model_summary)
            summary[market.value] = {"skipped": skipped or "no forecasts: the model failed"}
            continue
        try:
            day, partial = feature_day(market, bars, kind, now_utc)
            fee = repo.fee_settings(conn)[0]
            policy = policy_of(models[market].metrics)
            inputs[market] = stock_inputs(
                market, forecasts[market], bars, flagged, day.date(), partial, fee, policy
            )
            news = repo.news_sentiment(conn, run_id, list(inputs[market].rows))
            picks, found, summary[market.value], risk, explanations = recommend_market(
                market, models[market], forecasts[market], inputs[market], bars, held, news, results, today
            )
            with conn.transaction():  # a market's picks and its stocks' advice land together or not at all
                repo.write_picks(conn, run_id, picks)
                repo.merge_features_live(
                    conn, run_id,
                    [(AssetRef(s, AssetType.STOCK), {"advice": e}) for s, e in explanations.items()],
                    now_utc,
                )
            details[market] = found
            advice[market] = MarketAdvice(inputs[market], risk)
        except Exception as exc:
            summary[market.value] = model_failure(exc)
            # a Buy must carry a pick's fields, and these weren't built: its stocks are Hold
            inputs.pop(market, None)
            no_forecast[market] = RECOMMENDER_FAILED
    enabled = {m: model.metrics.get("picks_enabled") is True for m, model in models.items()}
    try:
        policies = {market: policy_of(model.metrics) for market, model in models.items()}
        verdicts = watch_verdicts(
            watch, held, forecasts, inputs, details, enabled, no_forecast, policies
        )
        with conn.transaction():
            repo.write_watchlist_verdicts(conn, run_id, verdicts)
    except Exception as exc:
        return summary, model_failure(exc), advice
    return summary, None, advice
