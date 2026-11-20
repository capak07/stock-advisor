"""The exit plan check: do a plan's stated chances hold up on history, and does a sell-at order pay?

Per calibrated outer fold, rows of the chosen model's walk-forward predictions are sampled; each gives
a plan built by `exit_plan.build_plan` exactly as the holdings stage builds one live (R6), from closes
dated on or before the sample day only. The pair is then judged on the closes after that day: where
it ended against the range, whether a close reached the sell-at price or the break-even, and what a
sell-at order did against simply holding with the trailing stop (R10). Touches are counted on daily
closes; intraday touches are not measured (R9).

The verdict per class decides what the live page may show (R7): `fail` when the range is off,
`range_only` when the touch rate or the order's value is off, else `pass`. A failed break-even or
stop-first check hides only that chance.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd

from advisor.benchmark.simulate import DailyPanel
from advisor.model.backtest import round_trip_cost
from advisor.model.crypto import CRYPTO
from advisor.models import Market
from advisor.policy import Policy
from advisor.portfolio.exit_plan import NO_FORECAST_HORIZON, TOUCH, NoPlan, build_plan

PAIRS_PER_FOLD = 400  # per class
TOLERANCE = {"touch": 5.0, "touch_third": 8.0, "coverage": 5.0, "bins": 10.0}  # in points
STATED_COVERAGE = 0.80  # the q10-q90 range
MIN_PAIRS = 200  # a class with fewer has no verdict ("Not validated yet")
MIN_VALUES = 50  # a check with fewer judged values fails
BINS = 5
THIRDS = 3
HIGH_SESSIONS = 126  # the synthetic cost: the highest close of these sessions up to the sample day
CLASSES = ("forecast", "volatility", "coin")
_QUANTILES = ["q10", "q50", "q90"]


@dataclass(frozen=True)
class Exits:
    """One bought pair's real exits, as fractions net of the round-trip cost."""

    stop_first: bool | None  # the stop day came before any close at or above the sell-at price
    with_order: float | None  # with a sell-at order resting at the sell-at price
    without_order: float  # holding with the trailing stop alone


@dataclass(frozen=True)
class Judged:
    """One sampled pair's plan and what happened after its sample day."""

    cls: str  # "forecast", "volatility" or "coin"
    fold: int
    atr_pct: float  # on the sample day
    plan: dict
    end_price: float  # the re-check date's close
    max_close: float  # the highest close up to the re-check date
    in_range: bool
    touched_sell_at: bool | None
    touched_breakeven: bool | None
    stop_first: bool | None
    with_order: float | None
    without_order: float | None


def walk_exits(
    price: float,
    after: Sequence[float],
    atrs: Sequence[float],
    *,
    sell_at: float | None,
    trail_atr: float,
    cost: float,
) -> Exits:
    """The exits of a pair bought at `price` on the sample day, on the `after` closes (R10).

    `atrs` holds the ATR fraction on the sample day, then on each session of `after`. The stop starts
    at `price * (1 - trail_atr * atrs[0])`; each close is checked against the stop in force, then the
    stop rises to the highest close since the sample day less `trail_atr` ATRs of that close, as
    `stops.trailing_stop` sets it. A day whose close is at or under the stop is a stop day. The order
    fills at `sell_at` on the first close at or above it; without one, or before it fills, the pair
    exits at the close on a stop day, else at the last close."""
    if len(after) == 0:
        raise ValueError("no closes after the sample day")
    stop = price * (1 - trail_atr * atrs[0])
    high = price
    sold = stopped = None  # the step of the first close at or above the sell-at price; of the stop day
    stop_close = math.nan
    for k, close in enumerate(after, start=1):
        if sold is None and sell_at is not None and close >= sell_at:
            sold = k
        if close <= stop:
            stopped, stop_close = k, close
            break  # both exits are known: nothing after the stop day is read
        high = max(high, close)
        atr = atrs[k]
        if math.isfinite(atr):
            stop = max(stop, high - trail_atr * atr * close)
    last = after[-1]
    without = (stop_close if stopped is not None else last) / price - 1 - cost
    if sell_at is None:
        return Exits(None, None, without)
    if sold is not None:  # filled first (the order rests in the market; the stop is judged at the close)
        return Exits(False, sell_at / price - 1 - cost, without)
    if stopped is not None:
        return Exits(True, stop_close / price - 1 - cost, without)
    return Exits(False, last / price - 1 - cost, without)


def _sample(predictions: pd.DataFrame, usable: Sequence[int], seed: int) -> pd.DataFrame:
    """Up to PAIRS_PER_FOLD rows per calibrated fold, with finite quantiles and P and a usable horizon."""
    keep = (
        predictions["horizon"].isin(list(usable))
        & (predictions["fold"] > 0)
        & predictions["p"].notna()
    )
    pool = predictions.loc[keep, ["day", "symbol", "horizon", "fold", *_QUANTILES, "p", "dollar_volume_20"]]
    pool = pool[np.isfinite(pool[[*_QUANTILES, "p"]].to_numpy(dtype=float)).all(axis=1)]
    rng = np.random.default_rng(seed)
    picked = []
    for fold in sorted(pool["fold"].unique()):
        here = pool[pool["fold"] == fold].sort_values(["day", "symbol", "horizon"])
        n = min(PAIRS_PER_FOLD, len(here))
        picked.append(here.iloc[np.sort(rng.choice(len(here), size=n, replace=False))])
    return pd.concat(picked) if picked else pool.iloc[:0]


@dataclass(frozen=True)
class _Arrays:
    dates: list  # python dates, as the live stage keys closes
    close: np.ndarray  # as stored: a missing close is NaN
    atr: np.ndarray
    rows: dict  # Timestamp -> row index
    cols: dict  # symbol -> column index
    bench: int


def _arrays(panel: DailyPanel) -> _Arrays:
    """The panel as arrays; no copy of the (large) panel is made when its two frames line up."""
    close, atr = panel.close, panel.atr_pct
    if not (atr.index.equals(close.index) and atr.columns.equals(close.columns)):
        atr = atr.reindex(index=close.index, columns=close.columns)
    return _Arrays(
        dates=[t.date() for t in close.index],
        close=close.to_numpy(dtype=float),
        atr=atr.to_numpy(dtype=float),
        rows={t: i for i, t in enumerate(close.index)},
        cols={s: j for j, s in enumerate(close.columns)},
        bench=close.columns.get_loc(panel.benchmark),
    )


def _carried(closes: np.ndarray, price: float) -> np.ndarray:
    """The closes after the sample day with a missing one carried forward from the last known close
    (the sample day's at first), as `simulate_book` reads them; nothing later is read."""
    out = closes.astype(float, copy=True)
    last = price
    for k, close in enumerate(out):
        if math.isfinite(close):
            last = close
        else:
            out[k] = last
    return out


def _judge(
    a: _Arrays,
    cls: str,
    fold: int,
    symbol: str,
    i: int,
    j: int,
    horizon: int,
    forecast: tuple[float, float, float] | None,
    cost: float,
    trail_atr: float,
) -> Judged | None:
    """The pair's plan built as live builds it, and what the closes after the sample day did to it; None
    when it is skipped (no price or ATR on the day, a horizon past the panel's end, or NoPlan)."""
    price, atr = a.close[i, j], a.atr[i, j]
    if not (math.isfinite(price) and price > 0 and math.isfinite(atr)):
        return None
    if i + horizon > len(a.dates) - 1:
        return None
    day = a.dates[i]
    closes = dict(zip(a.dates[: i + 1], a.close[: i + 1, j].tolist(), strict=True))
    bench = (
        dict(zip(a.dates[: i + 1], a.close[: i + 1, a.bench].tolist(), strict=True))
        if forecast is not None else None
    )
    high = float(np.nanmax(a.close[max(0, i - HIGH_SESSIONS + 1): i + 1, j]))
    stop = price * (1 - trail_atr * atr)
    try:
        plan = build_plan(
            symbol=symbol,
            day=day,
            closes=closes,
            price=float(price),
            horizon=horizon if forecast is not None else None,
            forecast=forecast,
            bench_closes=bench,
            stop=stop if stop > 0 else None,  # as the live stage: a stop at or under zero stops nothing
            cost_cad=high,
            value_cad=float(price),
            cost=cost,
            recheck=None,
            atr_pct=float(atr),  # R12: the plan's stop trails as `walk_exits` then walks it
            trail_atr=trail_atr,
        )
    except NoPlan:
        return None
    if plan["horizon"] != horizon:  # never: build_plan's horizon is the one asked for
        raise ValueError(f"{symbol} {day}: a plan over {plan['horizon']} sessions, not {horizon}")

    after = _carried(a.close[i + 1: i + 1 + horizon, j], float(price))
    end, top = float(after[-1]), float(after.max())
    sell_at, breakeven = plan["sell_at"], plan["breakeven"]
    exits = walk_exits(
        float(price), after.tolist(), a.atr[i: i + 1 + horizon, j].tolist(),
        sell_at=sell_at, trail_atr=trail_atr, cost=cost,
    )
    return Judged(
        cls=cls,
        fold=int(fold),
        atr_pct=float(atr),
        plan=plan,
        end_price=end,
        max_close=top,
        in_range=bool(plan["low"] <= end <= plan["high"]),
        touched_sell_at=None if sell_at is None else bool(top >= sell_at),
        touched_breakeven=None if breakeven is None else bool(top >= breakeven),
        stop_first=exits.stop_first,
        with_order=exits.with_order,
        without_order=None if sell_at is None else exits.without_order,
    )


def judge_pairs(
    predictions: pd.DataFrame,
    panel: DailyPanel,
    market: Market | str,
    usable: Sequence[int],
    usd_fx_fee_pct: float,
    policy: Policy,
    seed: int = 0,
) -> list[Judged]:
    """Sample the chosen model's walk-forward rows and judge a plan for each (see the module docstring).

    A stock's row gives a "forecast" plan (its quantiles and horizon) and a "volatility" plan (the
    forecast masked, NO_FORECAST_HORIZON sessions). A coin's row gives one "coin" plan, always
    volatility only (R3), over NO_FORECAST_HORIZON panel rows (one per day with a BTC close)."""
    coins = market == CRYPTO
    rows = _sample(predictions, usable, seed)
    if rows.empty:
        return []
    a = _arrays(panel)
    costs = round_trip_cost(market, rows["dollar_volume_20"].to_numpy(dtype=float), usd_fx_fee_pct)
    out = []
    for row, cost in zip(rows.itertuples(index=False), costs, strict=True):
        i, j = a.rows.get(pd.Timestamp(row.day)), a.cols.get(row.symbol)
        if i is None or j is None:
            continue
        if coins:
            plans = [("coin", NO_FORECAST_HORIZON, None)]
        else:
            forecast = (float(row.q10), float(row.q50), float(row.q90))
            plans = [("forecast", int(row.horizon), forecast), ("volatility", NO_FORECAST_HORIZON, None)]
        for cls, horizon, forecast in plans:
            judged = _judge(a, cls, row.fold, row.symbol, i, j, horizon, forecast, float(cost), policy.trail_atr)
            if judged is not None:
                out.append(judged)
    return out


def _mean(values: Sequence[float]) -> float | None:
    return float(np.mean(values)) if len(values) else None


def _thirds(pairs: Sequence[Judged]) -> list[int]:
    """Each pair's volatility third, 0 (calmest) to 2: terciles of `atr_pct` among its fold's pairs."""
    third = [0] * len(pairs)
    by_fold: dict[int, list[int]] = {}
    for k, p in enumerate(pairs):
        by_fold.setdefault(p.fold, []).append(k)
    for members in by_fold.values():
        order = sorted(members, key=lambda k: pairs[k].atr_pct)
        for t, part in enumerate(np.array_split(np.array(order, dtype=int), THIRDS)):
            for k in part:
                third[int(k)] = t
    return third


def _worst_bin(stated: Sequence[float], happened: Sequence[bool]) -> float | None:
    """The largest gap, as a fraction, between the stated chance and how often it happened, over five
    equal-count bins of the stated chance. None with fewer than MIN_VALUES values."""
    if len(stated) < MIN_VALUES:
        return None
    s, h = np.asarray(stated, dtype=float), np.asarray(happened, dtype=float)
    order = np.argsort(s, kind="stable")
    return float(max(abs(s[b].mean() - h[b].mean()) for b in np.array_split(order, BINS)))


def _within(gap: float | None, tolerance: float) -> bool:
    return gap is not None and gap * 100 <= tolerance


def _verdict(pairs: Sequence[Judged]) -> dict:
    thirds = _thirds(pairs)
    sold = [(p.touched_sell_at, t) for p, t in zip(pairs, thirds, strict=True) if p.touched_sell_at is not None]
    touch_rate = _mean([float(hit) for hit, _ in sold])
    by_third = [_mean([float(hit) for hit, t in sold if t == third]) for third in range(THIRDS)]
    touch = (
        len(sold) >= MIN_VALUES
        and abs(touch_rate - TOUCH) * 100 <= TOLERANCE["touch"]
        and all(r is not None and abs(r - TOUCH) * 100 <= TOLERANCE["touch_third"] for r in by_third)
    )

    coverage = _mean([float(p.in_range) for p in pairs])
    in_range = (
        len(pairs) >= MIN_VALUES and abs(coverage - STATED_COVERAGE) * 100 <= TOLERANCE["coverage"]
    )

    with_be = [p for p in pairs if p.touched_breakeven is not None and p.plan.get("p_breakeven") is not None]
    breakeven_worst = _worst_bin([p.plan["p_breakeven"] for p in with_be], [p.touched_breakeven for p in with_be])
    with_sf = [p for p in pairs if p.stop_first is not None and p.plan.get("p_stop_first") is not None]
    stop_first_worst = _worst_bin([p.plan["p_stop_first"] for p in with_sf], [p.stop_first for p in with_sf])

    gains = [(p.fold, p.with_order - p.without_order) for p in pairs
             if p.with_order is not None and p.without_order is not None]
    order_gain = _mean([g for _, g in gains])
    by_fold: dict[int, list[float]] = {}
    for fold, g in gains:
        by_fold.setdefault(fold, []).append(g)
    folds = len(by_fold)
    not_worse = sum(1 for values in by_fold.values() if np.mean(values) >= 0)
    value = len(gains) >= MIN_VALUES and order_gain >= 0 and not_worse >= math.ceil(folds / 2)

    checks = {
        "range": bool(in_range),
        "touch": bool(touch),
        "value": bool(value),
        "breakeven": _within(breakeven_worst, TOLERANCE["bins"]),
        "stop_first": _within(stop_first_worst, TOLERANCE["bins"]),
    }
    if not checks["range"]:
        result = "fail"
    elif not (checks["touch"] and checks["value"]):
        result = "range_only"
    else:
        result = "pass"
    return {
        "pairs": len(pairs),
        "touch_rate": touch_rate,
        "touch_by_third": by_third,
        "coverage": coverage,
        "breakeven_worst_bin": breakeven_worst,
        "stop_first_worst_bin": stop_first_worst,
        "order_gain": order_gain,
        "order_folds_not_worse": not_worse,
        "folds": folds,
        "checks": checks,
        "result": result,
    }


def verdicts(judged: Sequence[Judged]) -> dict[str, dict]:
    """Each class's verdict; a class with fewer than MIN_PAIRS judged pairs has none."""
    out = {}
    for cls in CLASSES:
        pairs = [p for p in judged if p.cls == cls]
        if len(pairs) >= MIN_PAIRS:
            out[cls] = _verdict(pairs)
    return out
