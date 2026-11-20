"""A holding's exit plan: simulated price paths from the asset's own past daily moves.

Each path is a block bootstrap of past daily log returns, BLOCK days at a time so that runs of
calm and stormy days stay together. Without a forecast the past drift is removed (no view on
direction); with one, the asset's excess over its benchmark is scaled and shifted to the
forecast's median and 10-90 width, and the benchmark's own moves are shifted to its median
drift. All path arithmetic is in log space; a simple return q becomes log(1 + q).

A stored plan shows only what the benchmark check passed for its class (`apply_verdict`).
"""

import hashlib
import math
from collections.abc import Callable, Mapping, Sequence
from datetime import date

import numpy as np

from advisor.models import AssetType

PLAN_VERSION = 1
PATHS = 4000
BLOCK = 5
LOOKBACK = 252
MIN_CLOSES = 60
TOUCH = 1 / 3
NO_FORECAST_HORIZON = 21
MIN_WIDTH = 1e-9  # a simulated 10-90 excess width under this is float noise, not a range (R11)


class NoPlan(ValueError):
    """A plan that cannot be built; the message is the reason shown in the run summary."""


def seed_of(symbol: str, day: date) -> int:
    """A seed that is the same on any machine: the first 8 bytes of sha256("symbol|day")."""
    digest = hashlib.sha256(f"{symbol}|{day.isoformat()}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def median_drift(bench_closes: Sequence[float], horizon: int) -> float:
    """The median simple return over every overlapping `horizon`-step window of the closes."""
    closes = np.asarray(bench_closes, dtype=float)
    if horizon < 1 or len(closes) <= horizon:
        raise NoPlan("too little price history")
    return float(np.median(closes[horizon:] / closes[:-horizon] - 1.0))


def _usable(close: float | None) -> bool:
    return close is not None and math.isfinite(close) and close > 0


def paired_moves(closes: Mapping[date, float], bench: Mapping[date, float]) -> np.ndarray:
    """Shape (n, 2): the asset's and the benchmark's daily log returns between consecutive
    closes the two have in common, over the last LOOKBACK common closes, oldest first.
    A date only one side has (or a close that is missing, not finite or not positive) is
    dropped, so both columns always span the same pair of dates."""
    common = sorted(d for d, c in closes.items() if _usable(c) and _usable(bench.get(d)))
    common = common[-LOOKBACK:]
    if len(common) < 2:
        return np.empty((0, 2))
    prices = np.log(np.array([[closes[d], bench[d]] for d in common], dtype=float))
    return np.diff(prices, axis=0)


def _indexes(n: int, horizon: int, seed: int) -> np.ndarray:
    """Shape (PATHS, horizon): row indexes of ceil(horizon / BLOCK) blocks of BLOCK consecutive
    rows per path, block starts uniform on 0 ... n - BLOCK, truncated to `horizon` steps."""
    blocks = math.ceil(horizon / BLOCK)
    starts = np.random.default_rng(seed).integers(0, n - BLOCK + 1, size=(PATHS, blocks))
    rows = starts[:, :, None] + np.arange(BLOCK)
    return rows.reshape(PATHS, blocks * BLOCK)[:, :horizon]


def simulate_raw(moves: np.ndarray, horizon: int, seed: int) -> np.ndarray:
    """The block sampler alone: the cumulative sum of the sampled rows of a 1-D `moves`,
    shape (PATHS, horizon). No demeaning, no rescaling."""
    moves = np.asarray(moves, dtype=float)
    return np.cumsum(moves[_indexes(len(moves), horizon, seed)], axis=1)


def _shift_median(paths: np.ndarray, target: float) -> np.ndarray:
    """Add a constant per-step shift so the median end equals `target`."""
    horizon = paths.shape[1]
    step = (target - np.median(paths[:, -1])) / horizon
    return paths + step * np.arange(1, horizon + 1)


def simulate(
    moves: np.ndarray,
    horizon: int,
    seed: int,
    *,
    forecast: tuple[float, float, float] | None = None,
    drift: float | None = None,
) -> np.ndarray:
    """Shape (PATHS, horizon): each path's cumulative log return after each step.

    `moves` is shape (n,) for an asset with no forecast, or (n, 2) from `paired_moves` with a
    forecast (q10, q50, q90) and the benchmark's median `drift`. Skew between the forecast's
    quantiles is not reproduced: one scale and one shift match its median and 10-90 width."""
    moves = np.asarray(moves, dtype=float)
    if len(moves) < MIN_CLOSES - 1:
        raise NoPlan("too little price history")

    if forecast is None:
        if moves.ndim != 1:
            raise ValueError("moves without a forecast must be 1-D")
        return simulate_raw(moves - moves.mean(), horizon, seed)

    if moves.ndim != 2 or moves.shape[1] != 2:
        raise ValueError("moves with a forecast must be shape (n, 2)")
    if drift is None:
        raise ValueError("a forecast needs the benchmark's drift")
    q10, q50, q90 = forecast
    if not (
        all(math.isfinite(q) for q in forecast) and -1 < q10 <= q50 <= q90 and q10 < q90
    ):
        raise NoPlan("forecast is not usable")

    # The same seed gives the same block indexes, so both columns of a row stay paired.
    excess = simulate_raw(moves[:, 0] - moves[:, 1], horizon, seed)
    ends = excess[:, -1]
    width = np.quantile(ends, 0.9) - np.quantile(ends, 0.1)
    if not width >= MIN_WIDTH:  # also refuses a NaN width
        raise NoPlan("forecast range has no width")
    excess = _shift_median(excess * ((math.log1p(q90) - math.log1p(q10)) / width), math.log1p(q50))

    bench = simulate_raw(moves[:, 1] - moves[:, 1].mean(), horizon, seed)
    bench = _shift_median(bench, math.log1p(drift))
    return excess + bench


def touch_share(paths: np.ndarray, level: float) -> float:
    """The share of paths whose highest cumulative log return is at or above `level`."""
    return float(np.mean(np.max(paths, axis=1) >= level))


def trail_of(atr_pct: float | None, trail_atr: float | None) -> float | None:
    """How far under the highest close the stop trails, as a fraction of the latest close
    (`trail_atr * atr_pct`); None, a fixed stop, when either is missing or not finite or the
    product is not in (0, 1)."""
    if atr_pct is None or trail_atr is None:
        return None
    trail = trail_atr * atr_pct
    return trail if math.isfinite(trail) and 0 < trail < 1 else None


def _first(hit: np.ndarray) -> np.ndarray:
    """Each path's first step where `hit` is true; the horizon when it never is."""
    return np.where(hit.any(axis=1), hit.argmax(axis=1), hit.shape[1])


def _trailing_hits(paths: np.ndarray, stop: float, trail: float) -> np.ndarray:
    """Each path's first step whose close is at or under its stop then in force, as
    `stops.trailing_stop` moves it (R12): the stop starts at `stop` (relative to today's price);
    after each step it becomes max(stop, highest close so far - trail * that step's close), the
    highest close starting at today's price. The horizon when the stop is never hit."""
    closes = np.exp(paths)  # each step's close over today's price
    count, horizon = closes.shape
    level = np.full(count, stop)
    high = np.ones(count)
    hit = np.full(count, horizon)
    for t in range(horizon):
        close = closes[:, t]
        hit[(hit == horizon) & (close <= level)] = t
        high = np.maximum(high, close)
        level = np.maximum(level, high - trail * close)
    return hit


def _stop_first(
    paths: np.ndarray, stop_level: float, sell_level: float, trail: float | None = None
) -> float:
    """The share of paths whose stop hit comes before their first step at or above `sell_level`;
    a path that never reaches `sell_level` counts if it hits the stop at all. Without `trail` the
    stop is held at `stop_level` (a log return); with it, the stop trails (R12)."""
    if trail is None:
        stopped = _first(paths <= stop_level)
    else:
        stopped = _trailing_hits(paths, math.exp(stop_level), trail)
    return float(np.mean(stopped < _first(paths >= sell_level)))


def read_plan(
    paths: np.ndarray,
    price: float,
    *,
    stop: float | None,
    breakeven: float | None,
    cost: float,
    atr_pct: float | None = None,
    trail_atr: float | None = None,
) -> dict:
    """The range, the sell-at price and the chances, read off cumulative log-return paths.

    The sell-at price is the k-th highest path maximum, k = ceil(TOUCH * N), so about one path
    in three closes at or above it. It is not given when it sits inside the round-trip cost or
    at or under today's stop. With today's ATR fraction and the policy's `trail_atr`, the stop
    trails along each path for the stop-first chance (R12); without them it is held fixed."""
    paths = np.asarray(paths, dtype=float)
    ends = paths[:, -1]
    q10, q50, q90 = np.quantile(ends, [0.1, 0.5, 0.9])
    k = math.ceil(round(TOUCH * len(paths), 9))  # rounding first: float error never adds one
    level = float(np.sort(np.max(paths, axis=1))[-k])
    sell_at: float | None = price * math.exp(level)
    p_touch = p_stop_first = None
    if sell_at <= price * (1 + cost) or (stop is not None and sell_at <= stop):
        sell_at = None
    else:
        p_touch = touch_share(paths, level)
        if stop is not None:
            p_stop_first = _stop_first(paths, math.log(stop / price), level, trail_of(atr_pct, trail_atr))
    return {
        "low": price * math.exp(q10),
        "mid": price * math.exp(q50),
        "high": price * math.exp(q90),
        "sell_at": sell_at,
        "p_touch": p_touch,
        "p_stop_first": p_stop_first,
        "p_up": float(np.mean(ends > 0)),
        "breakeven": breakeven,
        "p_breakeven": (
            None if breakeven is None else touch_share(paths, math.log(breakeven / price))
        ),
    }


def _up_to(closes: Mapping[date, float], day: date) -> dict[date, float]:
    """The usable closes dated on or before `day` (point-in-time), oldest first."""
    return {d: closes[d] for d in sorted(closes) if d <= day and _usable(closes[d])}


def _finite(value: object) -> bool:
    return not isinstance(value, float) or math.isfinite(value)


def build_plan(
    *,
    symbol: str,
    day: date,
    closes: Mapping[date, float],
    price: float | None,
    horizon: int | None,
    forecast: tuple[float, float, float] | None,
    bench_closes: Mapping[date, float] | None,
    stop: float | None,
    cost_cad: float,
    value_cad: float,
    cost: float,
    recheck: Callable[[int], date] | None = None,
    atr_pct: float | None = None,
    trail_atr: float | None = None,
) -> dict:
    """The stored exit plan for one holding on feature day `day`; the one builder the holdings
    stage and the benchmark check share (R6).

    With a forecast, its horizon and the benchmark's closes, the paths follow the forecast;
    otherwise they are volatility only, over NO_FORECAST_HORIZON steps. With the ATR fraction that
    set `stop` and the policy's `trail_atr`, the stop trails along each path (R12). Only closes
    dated on or before `day` are read. Raises NoPlan, and only NoPlan, when no plan can be built."""
    if not _usable(price):
        raise NoPlan("no price")
    try:
        plan = _build_plan(
            symbol, day, closes, price, horizon, forecast, bench_closes, stop,
            cost_cad, value_cad, cost, recheck, atr_pct, trail_atr,
        )
    except NoPlan:
        raise
    except Exception as exc:  # one holding's plan must never fail the stage
        raise NoPlan(f"plan could not be built: {type(exc).__name__}: {exc}") from exc
    if not all(_finite(v) for v in plan.values()):
        raise NoPlan("plan is not finite")
    return plan


def _build_plan(
    symbol, day, closes, price, horizon, forecast, bench_closes, stop,
    cost_cad, value_cad, cost, recheck, atr_pct, trail_atr,
) -> dict:
    seed = seed_of(symbol, day)
    own = _up_to(closes, day)
    if forecast is not None and horizon is not None and bench_closes is not None:
        basis = "forecast"
        bench = _up_to(bench_closes, day)
        drift = float(median_drift(list(bench.values())[-LOOKBACK:], horizon))
        paths = simulate(paired_moves(own, bench), horizon, seed, forecast=forecast, drift=drift)
    else:
        basis, horizon, drift = "volatility", NO_FORECAST_HORIZON, None
        last = np.array(list(own.values())[-LOOKBACK:], dtype=float)
        paths = simulate(np.diff(np.log(last)), horizon, seed)

    cost_price = float(price * cost_cad / value_cad) if value_cad > 0 else None
    breakeven = cost_price if cost_price is not None and value_cad < cost_cad else None
    return {
        **read_plan(
            paths, float(price), stop=stop, breakeven=breakeven, cost=cost,
            atr_pct=atr_pct, trail_atr=trail_atr,
        ),
        "version": PLAN_VERSION,
        "basis": basis,
        "drift": drift,
        "horizon": horizon,
        "cost_price": cost_price,
        "recheck_by": None if recheck is None else recheck(horizon).isoformat(),
        "status": None,
    }


UNVALIDATED = "unvalidated"
RESULTS = ("pass", "range_only", "fail")
NUMBERS = ("low", "mid", "high", "sell_at", "p_touch", "p_stop_first", "p_up", "breakeven", "p_breakeven")
SELL_AT = ("sell_at", "p_touch", "p_stop_first")


def plan_class(asset_type: AssetType, basis: str) -> str:
    """The benchmark check's class a plan is judged in: "coin" for a coin (R3), else its basis."""
    return "coin" if asset_type is AssetType.CRYPTO else basis


def _verdict_for(plan: Mapping, check: object, model: str | None, asset_type: AssetType) -> Mapping | None:
    """The plan's class's verdict in `check`, or None when there is none that applies or it is malformed."""
    if not isinstance(check, Mapping) or "error" in check or check.get("plan_version") != PLAN_VERSION:
        return None
    cls = plan_class(asset_type, plan.get("basis"))
    # only the forecast class reads the model, so only it must be the live one (R2)
    if cls == "forecast" and (model is None or check.get("model") != model):
        return None
    classes = check.get("classes")
    verdict = classes.get(cls) if isinstance(classes, Mapping) else None
    if not isinstance(verdict, Mapping) or verdict.get("result") not in RESULTS:
        return None
    checks = verdict.get("checks")
    if not isinstance(checks, Mapping) or not all(
        isinstance(checks.get(k), bool) for k in ("breakeven", "stop_first")
    ):
        return None
    rate = verdict.get("touch_rate")
    if verdict["result"] == "pass" and not (
        isinstance(rate, int | float) and not isinstance(rate, bool) and math.isfinite(rate) and 0 <= rate <= 1
    ):
        return None
    return verdict


def apply_verdict(
    plan: Mapping, check: Mapping | None, *, model: str | None, asset_type: AssetType = AssetType.STOCK
) -> dict:
    """A copy of the plan showing only what the benchmark check passed for its class, its `status` set.

    `check` is the market's `exit_plan` block from the latest benchmark; `model` is the live model's
    config name without its policy. "unvalidated" when no verdict applies (no block, an errored one,
    another plan version, no verdict for the class, or a forecast plan checked on another model);
    "fail" nulls every number; otherwise the status is the result and `p_touch` the measured rate.
    "range_only" hides the sell-at price and its chances. A failed break-even or stop-first check
    hides only its own chance (R7)."""
    out = dict(plan)
    verdict = _verdict_for(plan, check, model, asset_type)
    if verdict is None:
        out["status"] = UNVALIDATED
        return out
    result = verdict["result"]
    out["status"] = result
    if result == "fail":
        out.update(dict.fromkeys(NUMBERS))
        return out
    if result == "range_only":
        out.update(dict.fromkeys(SELL_AT))
    elif out.get("sell_at") is not None:  # a plan without a sell-at price has no touch chance to show
        out["p_touch"] = float(verdict["touch_rate"])
    checks = verdict["checks"]
    if not checks["stop_first"]:
        out["p_stop_first"] = None
    if not checks["breakeven"]:
        out["p_breakeven"] = None
    return out
