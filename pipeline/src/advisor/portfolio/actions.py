"""Sell, trim, add or hold for each holding, by the spec's rules (spec §7.3, §7.5).

Position size is only ever a warning: an oversized holding is never trimmed for it, but it can't be an Add.
Tax warnings never change the action.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date

from advisor.models import AssetType, PredictionRow
from advisor.policy import DEFAULT_POLICY, Policy
from advisor.recommend.picks import because, best_horizon, choose_for_stock

GAIN_TRIM = 0.25
MOMENTUM_TRIM = 40.0
TAXABLE = frozenset({"crypto", "non_registered"})

_LEVELS = {"low": "Low", "medium": "Medium", "high": "High", "very_high": "Very High"}


@dataclass(frozen=True)
class Holding:
    """Everything one holding's action reads."""

    account: str
    symbol: str
    asset_type: AssetType
    benchmark: str | None
    price: float  # native latest close
    value_cad: float
    cost_cad: float
    portfolio_cad: float
    trailing_stop: float | None
    rows: list[PredictionRow]  # finite, usable horizons; empty means no forecast
    why_no_forecast: str | None
    cost: float
    sane: bool
    risk_level: str
    max_position_pct: float
    momentum_pct: float | None  # ret_21 percentile, 0-100
    signals_reversed: bool | None  # None: not linked to a pick, or not checkable
    review: list[str]  # the Review badge's reasons
    sold_at_loss_on: date | None  # newest taxable loss within 30 days of this asset, any account
    policy: Policy = DEFAULT_POLICY
    # the market's ranking under a rank policy (`picks.market_top`), so Add follows the picks
    top: Mapping | None = None


@dataclass(frozen=True)
class Action:
    action: str  # sell, trim, add or hold
    review: bool
    reasons: list[str]
    warnings: list[str] = field(default_factory=list)
    horizon: int | None = None
    q10: float | None = None
    q50: float | None = None
    q90: float | None = None


def _fmt(price: float) -> str:
    """2 decimals from 1 up; under 1, 4 significant figures without scientific notation."""
    if price >= 1 or price <= 0:
        return f"{price:.2f}"
    return f"{price:.{3 - math.floor(math.log10(price))}f}"


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _action(action: str, h: Holding, row: PredictionRow | None, reasons: list[str], warnings: list[str]) -> Action:
    """Build the Action: the Review badge's reasons come last, the range is the given row's."""
    return Action(
        action,
        bool(h.review),
        reasons + h.review,
        warnings,
        row.horizon_days if row else None,
        row.q10 if row else None,
        row.q50 if row else None,
        row.q90 if row else None,
    )


def decide(h: Holding) -> Action:
    """The first rule that fires wins: sell, then trim, then add, else hold."""
    choice = choose_for_stock(h.rows, h.cost, h.sane, h.policy, h.top)
    # the horizon that qualifies, so a stock the picks call a Buy is never sold for a weaker row
    best = next((r for r in h.rows if r.horizon_days == choice.horizon), None) if choice else None
    best = best or best_horizon(h.rows)
    benchmark = h.benchmark or (best.benchmark if best else None)
    # no portfolio value means no size information
    share = 100 * h.value_cad / h.portfolio_cad if h.portfolio_cad > 0 else None
    warnings: list[str] = []
    if share is not None and share > h.max_position_pct:
        level = _LEVELS.get(h.risk_level, h.risk_level)
        cap = f"{h.max_position_pct:g}"
        shown = f"{share:.1f}" if f"{share:.0f}" == cap else f"{share:.0f}"
        warnings.append(f"{shown}% of the portfolio; {level} risk allows {cap}%")

    sell: list[str] = []
    if h.trailing_stop is not None and h.price <= h.trailing_stop:
        sell.append(f"closed at {_fmt(h.price)}, under its trailing stop {_fmt(h.trailing_stop)}")
    if best is not None and best.p_beat <= h.policy.p_sell:
        sell.append(f"P(beat {benchmark}) {best.p_beat:.2f} over {best.horizon_days} trading days")
    if h.signals_reversed is True:
        sell.append("the signals behind its pick have reversed")
    if sell:
        if h.account in TAXABLE and h.value_cad < h.cost_cad:
            warnings.append(
                "selling at a loss: buying it again within 30 days before or after the sale "
                "denies the loss (superficial loss)"
            )
        return _action("sell", h, best, sell, warnings)

    if h.rows and h.momentum_pct is not None and h.cost_cad > 0:
        gain = h.value_cad / h.cost_cad - 1
        if gain >= GAIN_TRIM and h.momentum_pct < MOMENTUM_TRIM:
            reason = f"up {gain:.0%} and its 21-day momentum is at the {_ordinal(math.floor(h.momentum_pct))} percentile"
            return _action("trim", h, best, [reason], warnings)

    if choice is not None and (share is None or share < h.max_position_pct):
        reason = (
            f"would be a Buy today: {because(choice, benchmark)}, below its max size"
        )
        if h.sold_at_loss_on is not None:
            warnings.append(
                f"sold at a loss on {h.sold_at_loss_on}: adding now denies that loss (superficial loss)"
            )
        return _action("add", h, best, [reason], warnings)

    reason = (h.why_no_forecast or "no forecast yet") if not h.rows else "no rule fired"
    return _action("hold", h, best, [reason], warnings)
