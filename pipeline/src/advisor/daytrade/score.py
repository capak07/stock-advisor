"""Cost of a round trip, net R, eligibility and the top-3 rank."""

from collections.abc import Sequence
from dataclasses import dataclass

from advisor.daytrade.replay import HistoryStats, ReplayStats
from advisor.daytrade.rule import Plan
from advisor.models import Market

MIN_FIRED = 20
TOP_N = 3


@dataclass(frozen=True)
class Scored:
    key: tuple[str, str]
    net_history_r: float | None
    net_replay_r: float
    eligible: bool


def cost_pct(market: Market, usd_fx_fee_pct: float, spread_pct: float) -> float:
    """Round-trip cost in percent: US pays the FX fee on both legs plus the spread."""
    if market == Market.US:
        return 2 * usd_fx_fee_pct + spread_pct
    return spread_pct


def cost_r(cost_pct: float, plan: Plan) -> float:
    return cost_pct / 100 * plan.entry / (plan.entry - plan.stop)


def score(
    history: HistoryStats, rep: ReplayStats, cost_r: float
) -> tuple[float | None, float, bool]:
    net_replay = rep.avg_r - cost_r
    if history.fired < MIN_FIRED:
        return None, net_replay, False
    net_history = history.avg_r - cost_r
    return net_history, net_replay, net_history > 0 and net_replay > 0


def rank(items: Sequence[Scored]) -> dict[tuple[str, str], int]:
    ok = [i for i in items if i.eligible and i.net_history_r is not None]
    ok.sort(key=lambda i: (-(i.net_history_r or 0.0), -i.net_replay_r, i.key))
    return {i.key: n for n, i in enumerate(ok[:TOP_N], start=1)}
