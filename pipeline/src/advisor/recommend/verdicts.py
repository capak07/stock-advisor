"""Buy, hold or avoid for each watched symbol, with plain reasons (spec §6.5).

A buy qualifies by exactly the pick rule (`choose`), so the watchlist never disagrees with the picks.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from advisor.markets import market_of
from advisor.models import Market, PredictionRow
from advisor.policy import DEFAULT_POLICY, Policy
from advisor.recommend.picks import because, best_horizon, choose_for_stock

TSX_BASIS = (
    "Price and sector only: TSX stocks have no company filings in this model, so weigh this call accordingly."
)

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
    top: Mapping[int, Mapping[str, tuple[int, int]]] | None = None,
) -> Verdict:
    """`top` is the market's ranking under a rank policy (`picks.market_top`), so a rank pick is a Buy."""
    if not rows:
        return Verdict(symbol, "stock", "hold", [why_no_forecast or "no forecast yet"])
    benchmark = rows[0].benchmark
    choice = choose_for_stock(rows, cost, sane, policy, top)
    if choice is not None:
        reasons = [
            because(choice, benchmark),
            f"expected {choice.q50:.1%} against {cost:.1%} round-trip costs",
        ]
        details = dict(pick_details or {})
        if market_of(symbol) is Market.TSX:
            reasons.append(TSX_BASIS)
            details["basis"] = TSX_BASIS
        return Verdict(symbol, "stock", "buy", reasons, details)
    # judged at the horizon a holding is (portfolio/actions.py `decide`), so a watched stock you hold
    # is never Avoid on the Watchlist and Hold on My Portfolio, or the other way round
    best = best_horizon(rows)
    if best is not None and best.p_beat <= policy.p_sell:
        return Verdict(
            symbol, "stock", "avoid", [f"P(beat {benchmark}) {best.p_beat:.2f} over {best.horizon_days} trading days"]
        )
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
