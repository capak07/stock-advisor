"""Tune the recommendation policy on inner folds, under hard limits.

A fixed grid, searched in three stages (entries, then stops, then the sell line) so the search
stays near a hundred simulations per fold instead of seventeen thousand. A combination that trades
too little, draws down too far, trades too often or claims more than it delivers is never chosen,
however well it scores. Tuning for an outer fold reads nothing dated on or after that fold.
"""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from itertools import product

import pandas as pd

from advisor.benchmark.folds import inner_walk_forward
from advisor.benchmark.metrics import calibrated_horizons, model_metrics
from advisor.benchmark.simulate import Book, DailyPanel, book_metrics, simulate_book
from advisor.model.backtest import MAX_CALIBRATION_PTS
from advisor.model.dataset import MarketData
from advisor.model.train import Fold, TrainConfig
from advisor.model.variants import ModelConfig
from advisor.models import Market
from advisor.policy import DEFAULT_POLICY, Policy

GRID = {
    "p_buy": (0.54, 0.56, 0.58, 0.60, 0.62, 0.64, 0.66),
    "rule": ("ratio", "p"),
    "top_n": (None, 3, 5, 10),  # spec §11: the top N by rank instead of a P floor
    "horizons": (None, (5, 10, 20), (21, 63, 126)),
    "swing_atr": (1.5, 2.0, 2.5, 3.0),
    "position_atr": (2.0, 2.5, 3.0, 3.5, 4.0),
    "trail_atr": (2.0, 2.5, 3.0, 3.5),
    "p_sell": (0.38, 0.40, 0.42, 0.44, 0.46),
}
STAGES = (("p_buy", "top_n", "rule", "horizons"), ("swing_atr", "position_atr", "trail_atr"), ("p_sell",))
MIN_TRADES = 30
MAX_DRAWDOWN = 0.25
MAX_TRADES_PER_MONTH = 20
DD_SOFT = 0.15  # drawdown past this costs objective, before the hard limit rejects it
DD_PENALTY = 2.0


@dataclass(frozen=True)
class Tuned:
    policy: Policy | None
    objective: float | None  # None when nothing was feasible
    tried: int
    reason: str


def _bad(x: float | None) -> bool:
    return x is None or x != x


def failures(per_period: Sequence[dict], pooled: dict) -> list[str]:
    """Every hard limit the book breaks, in plain words; empty when it meets them all."""
    out = []
    if not pooled["trades"] >= MIN_TRADES:
        out.append(f"only {pooled['trades']} trades (needs {MIN_TRADES})")
    for k, m in enumerate(per_period, start=1):
        if _bad(m["max_drawdown"]):
            out.append(f"period {k} drawdown couldn't be measured")
        elif m["max_drawdown"] > MAX_DRAWDOWN:
            out.append(f"period {k} drew down {m['max_drawdown']:.0%} (limit {MAX_DRAWDOWN:.0%})")
    for k, m in enumerate(per_period, start=1):
        if _bad(m["trades_per_month"]):
            out.append(f"period {k} trades a month couldn't be measured")
        elif m["trades_per_month"] > MAX_TRADES_PER_MONTH:
            out.append(f"period {k} made {m['trades_per_month']:.0f} trades a month (limit {MAX_TRADES_PER_MONTH})")
    if _bad(pooled["claimed_gap_pts"]):
        out.append("picks' claimed P couldn't be checked")
    elif pooled["claimed_gap_pts"] > MAX_CALIBRATION_PTS:
        out.append(
            f"picks claimed {pooled['mean_p']:.0%} but beat {pooled['beat_rate']:.0%} "
            f"(limit {MAX_CALIBRATION_PTS:g} points)"
        )
    if _bad(pooled["sharpe"]):
        out.append("net Sharpe couldn't be measured")
    return out


def score(
    pred: pd.DataFrame, panel: DailyPanel, policy: Policy, market: Market, fee: float, periods: Sequence[Fold]
) -> dict:
    """The policy's book in each period and pooled, its hard-limit failures and its objective."""
    return score_each(pred, panel, [policy] * len(periods), market, fee, periods)


def score_each(
    pred: pd.DataFrame,
    panel: DailyPanel,
    policies: Sequence[Policy],
    market: Market,
    fee: float,
    periods: Sequence[Fold],
) -> dict:
    """As `score`, with each period run under its own policy (one tuned for each outer fold)."""
    books = [
        simulate_book(pred, panel, policy, market, fee, f.start, f.end)
        for policy, f in zip(policies, periods, strict=True)
    ]
    pooled = book_metrics(Book(
        pd.concat([b.trades for b in books], ignore_index=True),
        pd.concat([b.daily for b in books]).sort_index(),
    ))
    per_period = [book_metrics(b) for b in books]
    failed = failures(per_period, pooled)
    objective = None
    if not failed:
        objective = pooled["sharpe"] - DD_PENALTY * max(0.0, pooled["max_drawdown"] - DD_SOFT)
    return {"per_period": per_period, "pooled": pooled, "feasible": not failed, "failures": failed,
            "objective": objective}


def stage_policies(best: Policy, names: Sequence[str]) -> list[Policy]:
    """The stage's grid as policies on top of `best`. A rank policy ignores `p_buy`, so it is tried
    once, at the grid's first `p_buy`; a sell line at or over the buy line is skipped."""
    out = []
    for values in product(*(GRID[name] for name in names)):
        policy = replace(best, **dict(zip(names, values, strict=True)))
        if not policy.p_sell < policy.p_buy:
            continue
        if policy.top_n is not None and "p_buy" in names and policy.p_buy != GRID["p_buy"][0]:
            continue
        out.append(policy)
    return out


def tune(pred: pd.DataFrame, panel: DailyPanel, market: Market, fee: float, periods: Sequence[Fold]) -> Tuned:
    """The best feasible policy, stage by stage; on ties the earlier grid value wins."""
    best, tried = DEFAULT_POLICY, 0
    objective = None
    for n, names in enumerate(STAGES, start=1):
        found, most = None, None
        for policy in stage_policies(best, names):
            s = score(pred, panel, policy, market, fee, periods)
            tried += 1
            if s["feasible"] and (found is None or s["objective"] > found[1]):
                found = (policy, s["objective"])
            if most is None or s["pooled"]["trades"] > most["pooled"]["trades"]:
                most = s
        if found is None:
            why = most["failures"][0] if most and most["failures"] else "nothing to simulate"
            return Tuned(None, None, tried, f"no stage-{n} combination met the limits: best failed on {why}")
        best, objective = found
    return Tuned(best, objective, tried, f"net Sharpe objective {objective:.2f} over {len(periods)} inner periods")


def inner_periods(
    data: MarketData, config: ModelConfig, train_config: TrainConfig, outer: Fold
) -> tuple[pd.DataFrame, list[Fold]]:
    """Calibrated inner predictions for `outer`, and the inner folds that have them."""
    wf = inner_walk_forward(data, config, train_config, outer)
    pred = wf.predictions
    if pred.empty or not pred["p"].notna().any():
        return pred, []
    usable = calibrated_horizons(model_metrics(pred))
    pred = pred[pred["p"].notna() & pred["horizon"].isin(usable)]
    return pred, [wf.folds[int(k)] for k in sorted(pred["fold"].unique())]


def tune_for_outer(
    data: MarketData,
    config: ModelConfig,
    train_config: TrainConfig,
    panel: DailyPanel,
    market: Market,
    fee: float,
    outer: Fold,
) -> Tuned:
    """The policy tuned on the inner folds of `outer`; the last of them ends where `outer` begins."""
    pred, periods = inner_periods(data, config, train_config, outer)
    if not periods:
        return Tuned(None, None, 0, "no calibrated inner predictions to tune on")
    return tune(pred, panel, market, fee, periods)

