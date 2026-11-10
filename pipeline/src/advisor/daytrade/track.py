"""Follows a published trade to its target, stop or flat-by exit."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from advisor.daytrade.bars import BAR_MIN, Bar
from advisor.daytrade.rule import Plan, Trigger


@dataclass(frozen=True)
class Outcome:
    status: str  # 'open' | 'target' | 'stop' | 'flat'
    exit_at: datetime | None
    exit_price: float | None
    gross_r: float | None
    last_price: float
    last_at: datetime


def track(plan: Plan, trigger: Trigger, bars_after: Sequence[Bar], now: datetime) -> Outcome:
    """Walk the completed bars after the trigger bar, up to the flat-by bar.

    The flat-by bar is the one that closes at plan.flat_by, the same bar replay.py
    treats as its last (index (flat_by - open) / 5 min - 1). Stop is checked before
    target within a bar. A gap below the stop at the open still exits at the stop
    price: the skill's convention, optimistic.
    """
    step = timedelta(minutes=BAR_MIN)
    last_price, last_at = trigger.entry, trigger.at
    for b in sorted(bars_after, key=lambda x: x.start):
        end = b.start + step
        if end <= trigger.at or end > plan.flat_by or end > now:
            continue
        last_price, last_at = b.close, end
        if b.low <= plan.stop:
            return Outcome("stop", end, plan.stop, (plan.stop - plan.entry) / plan.risk, b.close, end)
        if b.high >= plan.target:
            gross = (plan.target - plan.entry) / plan.risk
            return Outcome("target", end, plan.target, gross, b.close, end)
        if end == plan.flat_by:
            return Outcome("flat", end, b.close, (b.close - plan.entry) / plan.risk, b.close, end)
    return Outcome("open", None, None, None, last_price, last_at)
