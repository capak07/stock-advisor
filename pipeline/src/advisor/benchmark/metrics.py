"""Per-fold and pooled scores: rank IC, pinball, coverage, calibration, default policy."""
from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
import pandas as pd

from advisor.model.backtest import MAX_CALIBRATION_PTS, simulate_picks
from advisor.model.train import _bin_gaps, calibration_error, rank_ic
from advisor.models import Market


def pinball_loss(y: np.ndarray, q: np.ndarray, alpha: float) -> float:
    """Mean pinball loss at `alpha`: over- and under-shoots are weighted by the quantile."""
    d = np.asarray(y, float) - np.asarray(q, float)
    return float(np.mean(np.maximum(alpha * d, (alpha - 1) * d)))


def _mean_or_nan(values: Sequence[float]) -> float:
    values = [v for v in values if v == v]
    return sum(values) / len(values) if values else math.nan


def _metrics(frame: pd.DataFrame) -> dict[str, float]:
    y = frame["y"].to_numpy(float)
    q10, q50, q90 = (frame[c].to_numpy(float) for c in ("q10", "q50", "q90"))
    p10, p50, p90 = pinball_loss(y, q10, 0.1), pinball_loss(y, q50, 0.5), pinball_loss(y, q90, 0.9)
    p = frame["p"].to_numpy(float)
    mask = ~np.isnan(p)
    cal, beat = p[mask], y[mask] > 0
    if cal.size:
        gaps, _ = _bin_gaps(cal, beat, 10)
        cal_pts = calibration_error(cal, beat)
        max_gap = float(gaps.max())
    else:
        cal_pts = max_gap = math.nan
    return {
        "rows": int(len(frame)),
        "rank_ic": rank_ic(frame, "q50", "y"),
        "pinball_q10": p10,
        "pinball_q50": p50,
        "pinball_q90": p90,
        "pinball": (p10 + p50 + p90) / 3,
        "coverage_10_90": float(np.mean((y >= q10) & (y <= q90))),
        "calibration_pts": cal_pts,
        "max_bin_gap_pts": max_gap,
    }


def model_metrics(predictions: pd.DataFrame) -> dict[str, dict[int, dict[str, float]]]:
    """Each outer fold and the pool, by horizon. Fold 0 has no p, so no calibration."""
    pred = predictions.sort_values(["fold", "horizon", "day", "symbol"])
    out: dict[str, dict[int, dict[str, float]]] = {}
    for fold, part in pred.groupby("fold", sort=True):
        out[str(int(fold))] = {int(h): _metrics(g) for h, g in part.groupby("horizon")}
    out["pooled"] = {int(h): _metrics(g) for h, g in pred.groupby("horizon")}
    return out


def summary(metrics: dict, horizons: Sequence[int]) -> dict[str, dict[str, float]]:
    """One rank IC and one pinball per fold, each the mean over the horizons present."""
    return {
        k: {
            "rank_ic": _mean_or_nan([by_h[h]["rank_ic"] for h in horizons if h in by_h]),
            "pinball": _mean_or_nan([by_h[h]["pinball"] for h in horizons if h in by_h]),
        }
        for k, by_h in metrics.items()
    }


def calibrated_horizons(metrics: dict) -> tuple[int, ...]:
    """Horizons whose pooled calibration was measured and is within the backtest limit."""
    pooled = metrics["pooled"]
    return tuple(
        h for h in sorted(pooled)
        if pooled[h]["calibration_pts"] == pooled[h]["calibration_pts"]
        and pooled[h]["calibration_pts"] <= MAX_CALIBRATION_PTS
    )


def _months(days: pd.Series) -> int:
    return int(pd.to_datetime(days).dt.to_period("M").nunique())


def _policy_block(picks: pd.DataFrame, pred_days: pd.Series) -> dict:
    n = int(len(picks))
    months = _months(pred_days)
    if not n:
        return {
            "trades": 0,
            "trades_per_month": 0.0 if months else math.nan,
            "mean_net_pct": None,
            "hit_rate_net": None,
            "beat_rate": None,
            "mean_p": None,
            "claimed_gap_pts": None,
        }
    mean_p = float(picks["p"].mean())
    beat_rate = float((picks["y"] > 0).mean())
    return {
        "trades": n,
        "trades_per_month": n / months if months else math.nan,
        "mean_net_pct": float(picks["net"].mean() * 100),
        "hit_rate_net": float((picks["net"] > 0).mean()),
        "beat_rate": beat_rate,
        "mean_p": mean_p,
        "claimed_gap_pts": abs(mean_p - beat_rate) * 100,
    }


def policy_metrics(
    predictions: pd.DataFrame, market: Market, usd_fx_fee_pct: float
) -> dict[str, dict]:
    """Trades, hit rate, claimed-minus-realized gap — only folds that have p."""
    pred = predictions.sort_values(["fold", "horizon", "day", "symbol"])
    cal = pred.loc[~pred["p"].isna()].copy()
    if cal.empty:
        return {}
    picks = simulate_picks(cal, market, usd_fx_fee_pct)
    fold_by_day = pd.Series(
        cal["fold"].to_numpy(), index=pd.to_datetime(cal["day"])
    ).groupby(level=0).first()
    if picks.empty:
        picks = picks.copy()
        picks["fold"] = pd.Series(dtype=float)
    else:
        picks = picks.copy()
        picks["fold"] = pd.to_datetime(picks["day"]).map(fold_by_day)
    out: dict[str, dict] = {}
    for fold, part in cal.groupby("fold", sort=True):
        fold_picks = picks.loc[picks["fold"] == fold] if len(picks) else picks
        out[str(int(fold))] = _policy_block(fold_picks, part["day"])
    out["pooled"] = _policy_block(picks, cal["day"])
    return out
