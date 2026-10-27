"""The holdings stage: one action per holding and account each run (spec §7.3, §10).

It reads what stages 7 and 8 already computed (`MarketAdvice`), so a holding is judged on the same
rows, costs, sanity checks and risk as the picks and the watchlist. A coin, or a stock without a
forecast, gets the fallback rules: the stop and the size warning only.

`advise_stage` catches its own failures: they degrade a run and never stop its prices from publishing.
"""

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import pandas as pd
import psycopg

from advisor.collectors.base import CollectorResult
from advisor.collectors.coingecko import CryptoQuote
from advisor.markets import MARKETS, market_of
from advisor.model.market_run import Forecast, MarketModel, feature_day, model_failure
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
from advisor.portfolio.actions import TAXABLE, Holding, decide
from advisor.portfolio.ledger import Loss, Position, build_ledger
from advisor.portfolio.stops import atr_pct, trailing_stop
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


def _stop(p: Position, seen: _Priced, view: RunView, forecast: Forecast | None) -> float | None:
    """The trailing stop, native; None without a price to set it from."""
    if seen.price is None:
        return None
    if forecast is not None and p.symbol in forecast.features.index:
        atr = float(forecast.features.at[p.symbol, "atr_14_pct"])  # the model's own
    else:
        atr = atr_pct(seen.history)
    closes = [b.close for b in seen.history if b.day >= p.opened_on]
    found = view.previous.get((p.account, p.symbol, p.asset_type.value))
    previous = found[1] if found is not None and found[0] >= p.opened_on else None
    pick = view.picks.get(p.pick_id) if p.pick_id is not None else None
    stop = trailing_stop(closes, seen.price, atr, previous, pick.stop if pick else None)
    return stop if stop is not None and stop > 0 else None  # a stop at or under zero stops nothing


def _sold_at_loss_on(p: Position, losses: Sequence[Loss], today: date) -> date | None:
    """The newest taxable loss on this asset, in any account, within 30 days."""
    days = [
        loss.day for loss in losses
        if loss.symbol == p.symbol and loss.asset_type is p.asset_type and loss.account in TAXABLE
        and today - timedelta(days=SUPERFICIAL_DAYS) <= loss.day <= today
    ]
    return max(days, default=None)


def holding_inputs(positions: Sequence[Position], losses: Sequence[Loss], view: RunView) -> list[Holding]:
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
        rows: list[PredictionRow] = advice.inputs.rows.get(p.symbol, []) if advice else []
        if s.price is None and (market is not None or p.symbol not in view.quotes):
            why = NOT_PRICED
        elif market is None:
            why = NO_COIN_MODEL if s.history else NO_CANDLES
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
            benchmark=MARKETS[market].benchmark if market is not None else None,
            price=s.price if s.price is not None else math.nan,
            value_cad=value,
            cost_cad=p.cost_cad,
            portfolio_cad=portfolio,
            trailing_stop=_stop(p, s, view, forecast),
            rows=rows,
            why_no_forecast=None if rows else why,
            cost=advice.inputs.cost.get(p.symbol, 0.0) if advice else 0.0,
            sane=advice.inputs.sane.get(p.symbol, False) if advice else False,
            risk_level=risk_level,
            max_position_pct=max_pct,
            momentum_pct=float(pct) if math.isfinite(pct) else None,
            signals_reversed=reversed_,
            review=_review(p, s, view),
            sold_at_loss_on=_sold_at_loss_on(p, losses, view.today),
        ))
    return out


def action_rows(
    positions: Sequence[Position], holdings: Sequence[Holding], view: RunView
) -> list[HoldingActionRow]:
    """Each holding's action as its `holding_actions` row, with what grading it later needs."""
    out = []
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
        ))
    return out


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
        )
        rows = action_rows(positions, holding_inputs(positions, ledger.losses, view), view)
        with conn.transaction():  # every holding's action lands together or not at all
            repo.write_holding_actions(conn, run_id, rows)
    except Exception as exc:
        return model_failure(exc)
    by_action = {action: sum(1 for r in rows if r.action == action) for action in ACTIONS}
    summary: dict = {"written": len(rows), "by_action": by_action}
    if ledger.problems:
        summary["problems"] = ledger.problems
    return summary
