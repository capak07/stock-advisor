"""Sell, trim, add or hold for each holding, by the spec's rules (spec §7.3, §7.5).

Position size is only ever a warning: an oversized holding is never trimmed for it, but it can't be an Add.
Tax warnings never change the action.
"""

from dataclasses import dataclass, field
from datetime import date

from advisor.models import AssetType, PredictionRow
from advisor.recommend.picks import best_horizon, choose
from advisor.recommend.verdicts import AVOID_P

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
    """2 decimals, or 4 significant figures under 1."""
    return f"{price:.2f}" if price >= 1 else f"{price:.4g}"


def _range(action: str, h: Holding, row: PredictionRow | None, reasons: list[str], warnings: list[str]) -> Action:
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
    best = best_horizon(h.rows)
    benchmark = h.benchmark or (best.benchmark if best else None)
    share = 100 * h.value_cad / h.portfolio_cad
    warnings: list[str] = []
    if share > h.max_position_pct:
        level = _LEVELS.get(h.risk_level, h.risk_level)
        warnings.append(f"{share:.0f}% of the portfolio; {level} risk allows {h.max_position_pct:g}%")

    sell: list[str] = []
    if h.trailing_stop is not None and h.price <= h.trailing_stop:
        sell.append(f"closed at {_fmt(h.price)}, under its trailing stop {_fmt(h.trailing_stop)}")
    if best is not None and best.p_beat <= AVOID_P:
        sell.append(f"P(beat {benchmark}) {best.p_beat:.2f} over {best.horizon_days} trading days")
    if h.signals_reversed is True:
        sell.append("the signals behind its pick have reversed")
    if sell:
        if h.account in TAXABLE and h.value_cad < h.cost_cad:
            warnings.append(
                "selling at a loss: buying it again within 30 days before or after the sale "
                "denies the loss (superficial loss)"
            )
        return _range("sell", h, best, sell, warnings)

    if h.rows and h.momentum_pct is not None and h.cost_cad > 0:
        gain = h.value_cad / h.cost_cad - 1
        if gain >= GAIN_TRIM and h.momentum_pct < MOMENTUM_TRIM:
            reason = f"up {gain:.0%} and its 21-day momentum is at the {h.momentum_pct:.0f}th percentile"
            return _range("trim", h, best, [reason], warnings)

    choice = choose(h.rows, h.cost, h.sane)
    if choice is not None and share < h.max_position_pct:
        reason = (
            f"would be a Buy today: P(beat {benchmark}) {choice.p_beat:.2f} "
            f"over {choice.horizon} trading days, below its max size"
        )
        if h.sold_at_loss_on is not None:
            warnings.append(
                f"sold at a loss on {h.sold_at_loss_on}: adding now denies that loss (superficial loss)"
            )
        return Action("add", bool(h.review), [reason] + h.review, warnings, choice.horizon, choice.q10, choice.q50, choice.q90)

    reason = (h.why_no_forecast or "no forecast yet") if not h.rows else "no rule fired"
    return _range("hold", h, best, [reason], warnings)
