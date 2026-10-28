"""Buy, hold or avoid for each watched symbol, with plain reasons (spec §6.5).

A buy qualifies by exactly the pick rule (`choose`), so the watchlist never disagrees with the picks.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field

from advisor.models import PredictionRow
from advisor.policy import DEFAULT_POLICY, Policy
from advisor.recommend.picks import best_horizon, choose

AVOID_P = 0.42
NO_COIN_MODEL = "no crypto model yet"  # spec §5.4: coins get the fallback rules


@dataclass(frozen=True)
class Verdict:
    symbol: str
    asset_type: str
    verdict: str  # buy, hold or avoid
    reasons: list[str]
    details: dict = field(default_factory=dict)


def _first_failing_check(
    rows: Sequence[PredictionRow], cost: float, sane: bool, policy: Policy = DEFAULT_POLICY
) -> str:
    """Why `choose` found no qualifying horizon, in the order the rule checks."""
    if not sane:
        return "the model's sanity checks failed on this run"
    benchmark = rows[0].benchmark
    max_p = max(r.p_beat for r in rows)
    if not max_p >= policy.p_buy:  # written so NaN fails
        return f"P(beat {benchmark}) {max_p:.2f} is under {policy.p_buy:.2f} at every horizon"
    likely = [r for r in rows if r.p_beat >= policy.p_buy]
    max_q50 = max(r.q50 for r in likely)
    if not max_q50 > cost:
        return f"expected {max_q50:.1%} does not clear {cost:.1%} round-trip costs"
    return "the forecast range has no width"


def stock_verdict(
    symbol: str,
    rows: Sequence[PredictionRow],
    cost: float,
    sane: bool,
    pick_details: dict | None,
    why_no_forecast: str | None,
    policy: Policy = DEFAULT_POLICY,
) -> Verdict:
    if not rows:
        return Verdict(symbol, "stock", "hold", [why_no_forecast or "no forecast yet"])
    benchmark = rows[0].benchmark
    choice = choose(rows, cost, sane, policy)
    if choice is not None:
        reasons = [
            f"P(beat {benchmark}) {choice.p_beat:.2f} over {choice.horizon} trading days",
            f"expected {choice.q50:.1%} against {cost:.1%} round-trip costs",
        ]
        return Verdict(symbol, "stock", "buy", reasons, dict(pick_details or {}))
    max_p = max(r.p_beat for r in rows)
    if all(r.p_beat <= policy.p_sell for r in rows):
        return Verdict(symbol, "stock", "avoid", [f"P(beat {benchmark}) at most {max_p:.2f} at every horizon"])
    best = best_horizon(rows)
    details = (
        {"horizon": best.horizon_days, "p_beat": best.p_beat, "q10": best.q10, "q50": best.q50, "q90": best.q90}
        if best
        else {}
    )
    reasons = ["doesn't qualify as a buy", _first_failing_check(rows, cost, sane, policy)]
    return Verdict(symbol, "stock", "hold", reasons, details)


def coin_verdict(
    symbol: str,
    rows: Sequence[PredictionRow] | None = None,
    cost: float = 0.0,
    policy: Policy = DEFAULT_POLICY,
    why: str | None = None,
) -> Verdict:
    """A coin's verdict. With no forecast it's a Hold, saying why (by default, no model yet); with
    one it uses the stock rule."""
    if not rows:
        return Verdict(symbol, "crypto", "hold", [why or NO_COIN_MODEL])
    verdict = stock_verdict(symbol, rows, cost, True, None, None, policy)
    return Verdict(symbol, "crypto", verdict.verdict, verdict.reasons, verdict.details)
