"""The holdings stage: one action per holding and account each run (spec §7.3, §10).

It reads what stages 7 and 8 already computed (`MarketAdvice`), so a holding is judged on the same
rows, costs, sanity checks and risk as the picks and the watchlist. A coin, or a stock without a
forecast, gets the fallback rules: the stop and the size warning only.

Each holding's exit plan shows only what the latest benchmark check passed for its class (`apply_verdict`).

`advise_stage` catches its own failures: they degrade a run and never stop its prices from publishing.
"""

import logging
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import psycopg

from advisor.collectors.base import CollectorResult
from advisor.collectors.coingecko import CryptoQuote
from advisor.markets import MARKETS, market_of
from advisor.model.backtest import round_trip_cost
from advisor.model.crypto import CRYPTO
from advisor.model.market_run import Forecast, MarketModel, feature_day, model_failure
from advisor.model.variants import ModelConfig
from advisor.models import (
    ET,
    AssetType,
    DailyBar,
    HoldingActionRow,
    LinkedPick,
    Market,
    PredictionRow,
    RunKind,
)
from advisor.policy import DEFAULT_POLICY, Policy, policy_of
from advisor.portfolio.actions import TAXABLE, Holding, decide
from advisor.portfolio.exit_plan import UNVALIDATED, NoPlan, apply_verdict, build_plan
from advisor.portfolio.ledger import Loss, Position, build_ledger
from advisor.portfolio.stops import atr_pct, trailing_stop
from advisor.recommend.picks import market_top
from advisor.recommend.risk import LEVELS
from advisor.recommend.stage import (
    RECOMMENDER_FAILED,
    MarketAdvice,
    hold_events,
    missing_market_reason,
    scheduled_events,
    why_no_forecast,
)
from advisor.recommend.verdicts import NO_COIN_MODEL
from advisor.schedule import sessions_after
from advisor.store import repo

REVIEW_SESSIONS = 5  # an earnings report or trial readout this close asks for review (spec §7.3)
SUPERFICIAL_DAYS = 30  # spec §7.5
NOT_PRICED = "not priced this run"
NO_CANDLES = f"{NO_COIN_MODEL}, and no daily candles for a trailing stop"
FLAGGED = "the latest bar is a flagged, unconfirmed jump"
ACTIONS = ("sell", "trim", "add", "hold")
# spec §6.4: a stock with every risk component missing is Very High; coins and stocks outside
# stage 8's population are judged the same way
FALLBACK_RISK, _, FALLBACK_MAX_PCT = LEVELS[-1]

Explain = Callable[[Market, str, int], list[dict]]
log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RunView:
    """What this run knows that the holdings' actions read, besides the positions themselves."""

    today: date  # ET
    days: Mapping[Market, tuple[date, bool]]  # each market's feature day, and whether its bar is partial
    bars: Mapping[str, Sequence[DailyBar]]
    flagged: Mapping[str, set[date]]
    quotes: Mapping[str, CryptoQuote]  # CoinGecko, in CAD
    candles: Mapping[str, Sequence[DailyBar]]  # Coinbase, in USD
    crypto_features: Mapping[str, dict]
    forecasts: Mapping[Market, Forecast]
    advice: Mapping[Market, MarketAdvice]  # stage 8's work; a market that failed there has none
    no_forecast: Mapping[Market, str]  # why a market without advice has no forecasts
    scheduled: Mapping[str, list[tuple[date, dict]]]
    usd_cad: float | None  # the latest rate
    previous: Mapping[tuple[str, str, str], tuple[date, float]]  # the last run's stops
    picks: Mapping[int, LinkedPick]
    explain: Explain  # today's contribution of every feature to a stock's forecast at a horizon
    coin_rows: Mapping[str, Sequence[PredictionRow]] = field(default_factory=dict)
    coin_cost: Mapping[str, float] = field(default_factory=dict)
    coin_why: Mapping[str, str] = field(default_factory=dict)
    coin_policy: Policy = DEFAULT_POLICY
    fees: tuple[float, float] = (0.0, 0.0)  # (USD FX fee, crypto fee) in percent
    exit_check: Mapping[str, dict] = field(default_factory=dict)  # the market's (or "crypto") latest check
    model_names: Mapping[Market, str] = field(default_factory=dict)  # each live model's config, no policy


@dataclass(frozen=True)
class _Priced:
    """A position's latest price as this run saw it."""

    market: Market | None  # None for a coin
    history: Sequence[DailyBar]  # its bars or candles, oldest first
    price: float | None  # the last close, native; None when not priced
    day: date | None  # the feature day
    same_day: bool  # the feature day is today and its bar partial


def _priced(p: Position, view: RunView) -> _Priced:
    if p.asset_type is AssetType.CRYPTO:
        history = view.candles.get(p.symbol) or []
        last = history[-1] if history else None
        return _Priced(None, history, last.close if last else None, last.day if last else None, False)
    market = market_of(p.symbol)
    history = view.bars.get(p.symbol) or []
    price = history[-1].close if history else None
    if market in view.days:
        day, same_day = view.days[market]
    else:  # no benchmark bars: the stock's own last bar
        day, same_day = (history[-1].day if history else None), False
    return _Priced(market, history, price, day, same_day)


def _value_cad(p: Position, seen: _Priced, view: RunView) -> float:
    """The position's value in CAD, or its cost when this run has no price for it."""
    if p.asset_type is AssetType.CRYPTO and p.symbol in view.quotes:
        return view.quotes[p.symbol].price_cad * p.qty
    if seen.price is None:
        return p.cost_cad
    if seen.market is Market.TSX:
        return seen.price * p.qty
    return seen.price * p.qty * view.usd_cad if view.usd_cad is not None else p.cost_cad


def _momentum(view: RunView) -> dict[Market, pd.Series]:
    """Each market's 21-day momentum percentile (0-100) among stage 8's population."""
    out = {}
    for market, advice in view.advice.items():
        population = [s for s, rows in advice.inputs.rows.items() if rows]
        features = view.forecasts[market].features
        ret = features.reindex(index=population, columns=["ret_21"])["ret_21"].astype(float)
        out[market] = ret.rank(pct=True) * 100
    return out


def signals_reversed(then: Sequence[dict], now: Sequence[dict]) -> bool | None:
    """Whether most of a pick's driving factors now push the other way: more than half of its
    non-zero contributions have flipped sign. None when it has none to compare."""
    today = {part["feature"]: part["contribution"] for part in now}
    driving = [part for part in then if part["contribution"] != 0 and math.isfinite(part["contribution"])]
    if not driving:
        return None
    flipped = sum(1 for part in driving if part["contribution"] * today.get(part["feature"], 0.0) < 0)
    return flipped > len(driving) / 2


def _mon_d(day: date) -> str:
    return f"{day:%b} {day.day}"


def _review(p: Position, seen: _Priced, view: RunView) -> list[str]:
    """The Review badge's reasons: an event within 5 sessions, or an unconfirmed latest price."""
    if seen.market is None:  # a coin: Coinbase's latest close against Kraken's
        return [FLAGGED] if view.crypto_features.get(p.symbol, {}).get("unconfirmed_price") is True else []
    reasons = []
    if seen.day is not None:
        window = {p.symbol: (seen.day, sessions_after(seen.market, seen.day, REVIEW_SESSIONS))}
        events = hold_events(view.scheduled, window, seen.same_day)[p.symbol]
        for day, event in sorted(events, key=lambda pair: pair[0]):
            what = "earnings" if event["type"] == "earnings" else "phase 2/3 trial completion"
            reasons.append(f"{what} on {_mon_d(day)}")
    if seen.history and seen.history[-1].day in view.flagged.get(p.symbol, ()):
        reasons.append(FLAGGED)
    return reasons


def _atr(symbol: str, seen: _Priced, forecast: Forecast | None) -> float:
    """The ATR fraction a holding's stop trails by: the model's own `atr_14_pct` when the forecast
    has the symbol, else one from its bars or candles. NaN when there is none."""
    if forecast is not None and symbol in forecast.features.index:
        return float(forecast.features.at[symbol, "atr_14_pct"])
    return atr_pct(seen.history)


def _stop(
    p: Position,
    seen: _Priced,
    view: RunView,
    forecast: Forecast | None,
    policy: Policy = DEFAULT_POLICY,
) -> float | None:
    """The trailing stop, native; None without a price to set it from."""
    if seen.price is None:
        return None
    atr = _atr(p.symbol, seen, forecast)
    # an unconfirmed jump would raise the stop for good, so it never sets the high
    history = seen.history
    if seen.market is None and view.crypto_features.get(p.symbol, {}).get("unconfirmed_price") is True:
        history = history[:-1]
    flagged = view.flagged.get(p.symbol, ())
    closes = [b.close for b in history if b.day >= p.opened_on and b.day not in flagged]
    found = view.previous.get((p.account, p.symbol, p.asset_type.value))
    previous = found[1] if found is not None and found[0] >= p.opened_on else None
    pick = view.picks.get(p.pick_id) if p.pick_id is not None else None
    # only an open pick's stop follows a split (`repo.rescale_refs`), so only it is a floor
    floor = pick.stop if pick is not None and pick.status == "open" else None
    stop = trailing_stop(closes, seen.price, atr, previous, floor, policy)
    return stop if stop is not None and stop > 0 else None  # a stop at or under zero stops nothing


def _sold_at_loss_on(p: Position, losses: Sequence[Loss], today: date) -> date | None:
    """The newest taxable loss on this asset, in any account, within 30 days."""
    days = [
        loss.day for loss in losses
        if loss.symbol == p.symbol and loss.asset_type is p.asset_type and loss.account in TAXABLE
        and today - timedelta(days=SUPERFICIAL_DAYS) <= loss.day <= today
    ]
    return max(days, default=None)


def holding_inputs(
    positions: Sequence[Position],
    losses: Sequence[Loss],
    view: RunView,
    policies: Mapping[Market, Policy] | None = None,
) -> list[Holding]:
    """Each position's `Holding`, in the positions' order."""
    seen = [_priced(p, view) for p in positions]
    values = [_value_cad(p, s, view) for p, s in zip(positions, seen, strict=True)]
    portfolio = sum(values)
    momentum = _momentum(view)
    out = []
    for p, s, value in zip(positions, seen, values, strict=True):
        market = s.market
        advice = view.advice.get(market) if market is not None else None
        forecast = view.forecasts.get(market) if market is not None else None
        if market is None:
            rows = list(view.coin_rows.get(p.symbol, []))
            policy = view.coin_policy
            benchmark = rows[0].benchmark if rows else None
            cost = float(view.coin_cost.get(p.symbol, 0.0)) if rows else 0.0
            sane = bool(rows)
        else:
            rows = advice.inputs.rows.get(p.symbol, []) if advice else []
            policy = (policies or {}).get(market, DEFAULT_POLICY)
            benchmark = MARKETS[market].benchmark
            cost = advice.inputs.cost.get(p.symbol, 0.0) if advice else 0.0
            sane = advice.inputs.sane.get(p.symbol, False) if advice else False
        if s.price is None and (market is not None or p.symbol not in view.quotes):
            why = NOT_PRICED
            rows, sane = [], False
        elif market is None and rows:
            why = None
        elif market is None:
            why = view.coin_why.get(p.symbol) or (NO_COIN_MODEL if s.history else NO_CANDLES)
        elif advice is None:
            why = view.no_forecast[market]
        else:
            why = why_no_forecast(p.symbol, forecast.features)
        risk_level, max_pct = FALLBACK_RISK, FALLBACK_MAX_PCT
        if advice is not None and p.symbol in advice.risk.index:
            risk_level = str(advice.risk.at[p.symbol, "risk_level"])
            max_pct = float(advice.risk.at[p.symbol, "max_position_pct"])
        pct = momentum[market].get(p.symbol, math.nan) if market in momentum and rows else math.nan
        pick = view.picks.get(p.pick_id) if p.pick_id is not None else None
        reversed_ = None
        if pick is not None and market is not None and any(r.horizon_days == pick.horizon_days for r in rows):
            reversed_ = signals_reversed(pick.top_factors, view.explain(market, p.symbol, pick.horizon_days))
        out.append(Holding(
            account=p.account,
            symbol=p.symbol,
            asset_type=p.asset_type,
            benchmark=benchmark,
            price=s.price if s.price is not None else math.nan,
            value_cad=value,
            cost_cad=p.cost_cad,
            portfolio_cad=portfolio,
            trailing_stop=_stop(p, s, view, forecast, policy),
            rows=rows,
            why_no_forecast=None if rows else why,
            cost=cost,
            sane=sane,
            risk_level=risk_level,
            max_position_pct=max_pct,
            momentum_pct=float(pct) if math.isfinite(pct) else None,
            signals_reversed=reversed_,
            review=_review(p, s, view),
            sold_at_loss_on=_sold_at_loss_on(p, losses, view.today),
            policy=policy,
            top=market_top(advice.inputs.rows, advice.inputs.sane, policy) if advice and market else None,
        ))
    return out


def _plan_cost(h: Holding, view: RunView) -> float:
    """The round-trip cost the exit plan uses: the same `round_trip_cost` the benchmark check uses (R6).

    `h.cost` when positive (stage 8's, or the coin's own); else a coin's `coin_cost` when it has one;
    else the market's spread, and the currency fee (a stock) or the crypto fee (a coin) both ways."""
    if h.cost > 0:
        return float(h.cost)
    if h.asset_type is AssetType.CRYPTO:
        if h.symbol in view.coin_cost:
            return float(view.coin_cost[h.symbol])
        return float(round_trip_cost(CRYPTO, np.array([math.nan]), view.fees[1])[0])
    market = market_of(h.symbol)
    forecast = view.forecasts.get(market)
    volume = math.nan  # unknown: the small-company spread
    if forecast is not None and h.symbol in forecast.features.index and "dollar_volume_20" in forecast.features:
        volume = float(forecast.features.at[h.symbol, "dollar_volume_20"])
    return float(round_trip_cost(market, np.array([volume]), view.fees[0])[0])


def _exit_plan(h: Holding, seen: _Priced, view: RunView, action) -> dict:
    """The holding's exit plan, or NoPlan with the reason. Any other failure inside is NoPlan too."""
    if seen.day is None:
        raise NoPlan("no price")
    # the stop trails along each path by the ATR `_stop` used and the policy's multiple (R12)
    atr = _atr(h.symbol, seen, view.forecasts.get(seen.market) if seen.market is not None else None)
    flagged = view.flagged.get(h.symbol, ())
    closes = {b.day: b.close for b in seen.history if b.day not in flagged}
    day = seen.day
    forecast = None
    bench_closes = None
    if seen.market is None:  # a coin: volatility only, and `view.bars` is never read (R3)
        def recheck(n: int) -> date:
            return day + timedelta(days=n)
    else:
        market = seen.market

        def recheck(n: int) -> date:
            return sessions_after(market, day, n)

        if None not in (action.q10, action.q50, action.q90):
            forecast = (float(action.q10), float(action.q50), float(action.q90))
            bench = view.bars.get(h.benchmark) if h.benchmark is not None else None
            if bench:
                bench_closes = {b.day: b.close for b in bench}
    return build_plan(
        symbol=h.symbol,
        day=day,
        closes=closes,
        price=h.price,
        horizon=None if action.horizon is None else int(action.horizon),
        forecast=forecast,
        bench_closes=bench_closes,
        stop=h.trailing_stop,
        cost_cad=h.cost_cad,
        value_cad=h.value_cad,
        cost=_plan_cost(h, view),
        recheck=recheck,
        atr_pct=atr if math.isfinite(atr) else None,
        trail_atr=h.policy.trail_atr,
    )


def _checked(plan: dict, p: Position, seen: _Priced, view: RunView) -> dict:
    """The plan as the latest benchmark check lets it be shown; "unvalidated" when matching it fails."""
    try:
        if seen.market is None:  # a coin: the "coin" class never compares models
            return apply_verdict(plan, view.exit_check.get(CRYPTO), model=None, asset_type=AssetType.CRYPTO)
        check = view.exit_check.get(seen.market.value)
        return apply_verdict(plan, check, model=view.model_names.get(seen.market), asset_type=p.asset_type)
    except Exception:  # reading the verdict never fails the stage
        log.exception("the exit plan check could not be applied to %s", p.symbol)
        return {**plan, "status": UNVALIDATED}


def _model_names(models: Mapping[Market, MarketModel]) -> dict[Market, str]:
    """Each market's live model config name without its policy, as the benchmark check names it (R2).
    A market whose stored config is missing or unreadable is left out."""
    out = {}
    for market, model in models.items():
        try:
            out[market] = replace(ModelConfig.from_json(model.metrics["config"]), policy=None).name
        except Exception as exc:
            log.warning("no model name for %s's exit plan check: %s: %s", market, type(exc).__name__, exc)
    return out


def _exit_check(conn: psycopg.Connection) -> dict[str, dict]:
    """The latest benchmark check per market, or {} when it cannot be read: never a failed stage."""
    try:
        with conn.transaction():
            return repo.latest_exit_check(conn)
    except Exception:
        log.exception("the latest exit plan check could not be read")
        return {}


def action_rows(
    positions: Sequence[Position], holdings: Sequence[Holding], view: RunView
) -> tuple[list[HoldingActionRow], dict[str, str]]:
    """Each holding's action as its `holding_actions` row, with what grading it later needs, and for
    each holding without an exit plan, "{account}:{symbol}" -> why."""
    out = []
    no_plan: dict[str, str] = {}
    for p, h in zip(positions, holdings, strict=True):
        action = decide(h)
        seen = _priced(p, view)
        exit_by = None
        if action.horizon is not None and seen.market is not None and seen.day is not None:
            exit_by = sessions_after(seen.market, seen.day, action.horizon)
        pick = view.picks.get(p.pick_id) if p.pick_id is not None else None
        if pick is not None and pick.status == "open" and (exit_by is None or pick.exit_by > exit_by):
            exit_by = pick.exit_by
        bench_ref = None
        if seen.market is not None:
            bench = view.bars.get(MARKETS[seen.market].benchmark)
            bench_ref = bench[-1].close if bench else None
        plan = None
        try:
            plan = _exit_plan(h, seen, view, action)
        except NoPlan as exc:
            no_plan[f"{p.account}:{p.symbol}"] = str(exc)
        except Exception as exc:  # one holding's plan never fails the stage
            no_plan[f"{p.account}:{p.symbol}"] = f"{type(exc).__name__}: {exc}"
        if plan is not None:
            plan = _checked(plan, p, seen, view)
        out.append(HoldingActionRow(
            account=p.account,
            symbol=p.symbol,
            asset_type=p.asset_type,
            action=action.action,
            review=action.review,
            reasons=action.reasons,
            warnings=action.warnings,
            trailing_stop=h.trailing_stop,
            q10=action.q10,
            q50=action.q50,
            q90=action.q90,
            exit_by=exit_by,
            horizon_days=action.horizon,
            feature_day=seen.day,
            ref_price=seen.price,
            bench_ref_price=bench_ref,
            risk_level=h.risk_level,
            max_position_pct=h.max_position_pct,
            exit_plan=plan,
        ))
    return out, no_plan


def advise_stage(
    conn: psycopg.Connection,
    run_id: int,
    *,
    models: Mapping[Market, MarketModel],
    forecasts: Mapping[Market, Forecast],
    advice: Mapping[Market, MarketAdvice],
    model_summary: Mapping[str, dict],
    bars: Mapping[str, Sequence[DailyBar]],
    flagged: Mapping[str, set[date]],
    quotes: Mapping[str, CryptoQuote],
    candles: Mapping[str, Sequence[DailyBar]],
    crypto_features: Mapping[str, dict],
    results: Mapping[str, CollectorResult],
    kind: RunKind,
    now_utc: datetime,
    coin_rows: Mapping[str, Sequence[PredictionRow]] | None = None,
    coin_cost: Mapping[str, float] | None = None,
    coin_why: Mapping[str, str] | None = None,
    coin_policy: Policy | None = None,
) -> dict:
    """The holdings stage: writes every holding's action, all in one transaction. Returns
    `summary["actions"]`; a failure is caught and returned as `model_failure`, never raised."""
    try:
        ledger = build_ledger(repo.load_trades(conn), repo.load_fx_rates(conn))
        positions = ledger.positions
        days = {}
        for market in Market:
            if bars.get(MARKETS[market].benchmark):
                day, partial = feature_day(market, bars, kind, now_utc)
                days[market] = (day.date(), partial)

        def explain(market: Market, symbol: str, h: int) -> list[dict]:
            model = models[market].active.model
            x = forecasts[market].features.loc[[symbol]]
            return model.contributions(x, h, top=len(model.features))[symbol]

        view = RunView(
            today=now_utc.astimezone(ET).date(),
            days=days,
            bars=bars,
            flagged=flagged,
            quotes=quotes,
            candles=candles,
            crypto_features=crypto_features,
            forecasts=forecasts,
            advice=advice,
            no_forecast={
                m: RECOMMENDER_FAILED if m in forecasts else missing_market_reason(m, model_summary)
                for m in Market if m not in advice
            },
            scheduled=scheduled_events(results),
            usd_cad=repo.latest_fx_rate(conn),
            previous=repo.previous_trailing_stops(conn),
            picks=repo.load_picks(conn, sorted({p.pick_id for p in positions if p.pick_id is not None})),
            explain=explain,
            coin_rows=coin_rows or {},
            coin_cost=coin_cost or {},
            coin_why=coin_why or {},
            coin_policy=coin_policy or DEFAULT_POLICY,
            fees=repo.fee_settings(conn),
            exit_check=_exit_check(conn),
            model_names=_model_names(models),
        )
        policies = {market: policy_of(model.metrics) for market, model in models.items()}
        rows, no_plan = action_rows(positions, holding_inputs(positions, ledger.losses, view, policies), view)
        with conn.transaction():  # every holding's action lands together or not at all
            repo.write_holding_actions(conn, run_id, rows)
    except Exception as exc:
        return model_failure(exc)
    by_action = {action: sum(1 for r in rows if r.action == action) for action in ACTIONS}
    summary: dict = {"written": len(rows), "by_action": by_action}
    if ledger.problems:
        summary["problems"] = ledger.problems
    if no_plan:
        summary["no_exit_plan"] = no_plan
    return summary
