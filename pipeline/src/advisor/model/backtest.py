"""Backtest the pick rules on out-of-sample predictions, after costs, and gate a market.

The picks follow the spec's rules (probability floor, return above cost, best hold per stock,
ten per style with a sector cap). A market's picks may only be shown when they would have made
money after costs and the model's probabilities were honest.
"""

from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd

from advisor.models import Market
from advisor.policy import DEFAULT_POLICY, Policy

P_MIN = 0.58
SWING_HORIZONS = frozenset({5, 10, 20})
PICKS_PER_STYLE = 10
PER_SECTOR = 3
MIN_PICKS = 30
MAX_CALIBRATION_PTS = 5.0
LARGE_DOLLAR_VOLUME = 10_000_000.0
SPREAD_LARGE = 0.001
SPREAD_SMALL = 0.003

PICK_COLUMNS = ["day", "symbol", "sector", "horizon", "style", "p", "q50", "ratio", "y", "cost", "net"]


def round_trip_cost(market: Market, dollar_volume_20: np.ndarray, usd_fx_fee_pct: float) -> np.ndarray:
    """Buy-and-sell cost as a fraction: the spread, plus the currency fee both ways for US stocks."""
    spread = np.where(np.asarray(dollar_volume_20) >= LARGE_DOLLAR_VOLUME, SPREAD_LARGE, SPREAD_SMALL)
    if market is Market.US:
        return spread + 2 * usd_fx_fee_pct / 100
    return spread


def _priced(predictions: pd.DataFrame, market: Market, usd_fx_fee_pct: float) -> pd.DataFrame:
    """The forecasts the pick rules consider, with their round-trip cost and q50-to-range ratio."""
    df = predictions.copy()
    if "jump_5d" in df:  # spec 6.1: the latest bar must not be a flagged, unconfirmed jump
        df = df[df["jump_5d"].fillna(0) != 1]
    df["cost"] = round_trip_cost(market, df["dollar_volume_20"].to_numpy(), usd_fx_fee_pct)
    width = df["q90"] - df["q10"]
    df["ratio"] = (df["q50"] / width).where(width > 0)
    return df


def pick_funnel(
    predictions: pd.DataFrame, market: Market, usd_fx_fee_pct: float, policy: Policy = DEFAULT_POLICY
) -> dict[str, Any]:
    """How many forecasts pass each pick rule, and the highest P(beat) reached: why picks are few."""
    df = _priced(predictions, market, usd_fx_fee_pct)
    if policy.horizons is not None:
        df = df[df["horizon"].isin(policy.horizons)]
    p = df["p"]
    confident = p >= policy.p_buy  # a NaN P never is
    affordable = df["q50"] > df["cost"]
    known = p.notna().any()
    return {
        "forecasts": len(df),
        "p_at_least_floor": int(confident.sum()),
        "above_cost": int(affordable.sum()),
        "both": int((confident & affordable & df["ratio"].notna()).sum()),
        "p_max": float(p.max()) if known else None,
        "p_99": float(p.quantile(0.99)) if known else None,
        "mean_cost": float(df["cost"].mean()) if len(df) else None,
        "p_max_by_horizon": {int(h): float(v) for h, v in p.groupby(df["horizon"]).max().dropna().items()},
    }


def simulate_picks(
    predictions: pd.DataFrame, market: Market, usd_fx_fee_pct: float, policy: Policy = DEFAULT_POLICY
) -> pd.DataFrame:
    """One row per pick: each day and style, the best stocks within the sector cap.

    `rule="ratio"` ranks by expected return per unit of range; `"p"` ranks by P(beat).
    A tie goes to the shorter horizon. `horizons`, when set, is the only set considered.
    A stock is a separate bet only once its earlier pick's hold has ended.
    """
    df = _priced(predictions, market, usd_fx_fee_pct)
    if policy.horizons is not None:
        df = df[df["horizon"].isin(policy.horizons)]
    df = df[(df["p"] >= policy.p_buy) & (df["q50"] > df["cost"]) & df["ratio"].notna()]
    if df.empty:
        return pd.DataFrame(columns=PICK_COLUMNS)

    rank = "p" if policy.rule == "p" else "ratio"
    df = df.sort_values(["day", "symbol", rank, "horizon"], ascending=[True, True, False, True])
    df = df.drop_duplicates(["day", "symbol"], keep="first")
    df["style"] = np.where(df["horizon"].isin(SWING_HORIZONS), "swing", "position")
    # a stock without a sector label counts alone, not as one shared group
    df["_group"] = df["sector"].where(df["sector"].notna(), "unlabelled:" + df["symbol"].astype(str))

    df = df.sort_values(["day", "style", rank, "symbol"], ascending=[True, True, False, True])
    chosen = []
    held_until: dict[str, np.datetime64] = {}  # symbol -> the day its pick's hold ends
    for day, today in df.groupby("day", sort=True):
        day64 = np.datetime64(day, "D")
        for symbol in [s for s, end in held_until.items() if end <= day64]:
            del held_until[symbol]
        today = today[~today["symbol"].isin(held_until)]
        today = today[today.groupby(["style", "_group"]).cumcount() < PER_SECTOR]
        today = today[today.groupby("style").cumcount() < PICKS_PER_STYLE]
        for symbol, horizon in zip(today["symbol"], today["horizon"], strict=True):
            # business days only: holidays are ignored, so the end is approximate
            held_until[symbol] = np.busday_offset(day64, int(horizon), roll="forward")
        chosen.append(today)
    df = pd.concat(chosen)
    df["net"] = df["y"] - df["cost"]
    return df[PICK_COLUMNS].reset_index(drop=True)


def _group_metrics(picks: pd.DataFrame) -> dict[str, Any]:
    if picks.empty:
        return {"picks": 0, "mean_net_pct": None, "hit_rate_net": None, "beat_rate": None, "mean_p": None}
    return {
        "picks": len(picks),
        "mean_net_pct": float(picks["net"].mean() * 100),
        "hit_rate_net": float((picks["net"] > 0).mean()),
        "beat_rate": float((picks["y"] > 0).mean()),
        "mean_p": float(picks["p"].mean()),
    }


def pick_metrics(picks: pd.DataFrame) -> dict[str, dict]:
    """Net return and hit rates over all picks and per style; rates are fractions."""
    return {
        "all": _group_metrics(picks),
        "swing": _group_metrics(picks[picks["style"] == "swing"]),
        "position": _group_metrics(picks[picks["style"] == "position"]),
    }


def gate(metrics: Mapping[str, Any], calibration_pts: float) -> tuple[bool, str]:
    """Whether a market's picks may be shown, and the plain-words reason."""
    overall = metrics["all"]
    n = overall["picks"]
    if n < MIN_PICKS:
        return False, f"only {n} backtest picks (needs {MIN_PICKS})"
    net = overall["mean_net_pct"]
    if not net > 0:  # written so a NaN fails
        if net is not None and net == net:
            return False, f"backtest picks lost {abs(net):.2f}% after costs"
        return False, "backtest picks couldn't be scored"
    if calibration_pts != calibration_pts:
        return False, "probabilities couldn't be checked (no calibrated predictions)"
    if not calibration_pts <= MAX_CALIBRATION_PTS:
        return False, f"probabilities off by {calibration_pts:.1f} points (limit {MAX_CALIBRATION_PTS:g})"
    claimed, beat = overall["mean_p"], overall["beat_rate"]
    gap_pts = abs(claimed - beat) * 100
    if gap_pts != gap_pts:
        return False, "backtest picks couldn't be scored"
    if not gap_pts <= MAX_CALIBRATION_PTS:
        return False, f"picks claimed {claimed:.0%} but beat their benchmark {beat:.0%} of the time"
    return True, f"{n} backtest picks gained {net:.2f}% after costs"
