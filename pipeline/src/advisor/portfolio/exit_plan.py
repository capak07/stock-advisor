"""A holding's exit plan: simulated price paths from the asset's own past daily moves.

Each path is a block bootstrap of past daily log returns, BLOCK days at a time so that runs of
calm and stormy days stay together. Without a forecast the past drift is removed (no view on
direction); with one, the asset's excess over its benchmark is scaled and shifted to the
forecast's median and 10-90 width, and the benchmark's own moves are shifted to its median
drift. All path arithmetic is in log space; a simple return q becomes log(1 + q).
"""

import hashlib
import math
from collections.abc import Mapping, Sequence
from datetime import date

import numpy as np

PLAN_VERSION = 1
PATHS = 4000
BLOCK = 5
LOOKBACK = 252
MIN_CLOSES = 60
TOUCH = 1 / 3
NO_FORECAST_HORIZON = 21


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
    if not width > 0:
        raise NoPlan("forecast range has no width")
    excess = _shift_median(excess * ((math.log1p(q90) - math.log1p(q10)) / width), math.log1p(q50))

    bench = simulate_raw(moves[:, 1] - moves[:, 1].mean(), horizon, seed)
    bench = _shift_median(bench, math.log1p(drift))
    return excess + bench
