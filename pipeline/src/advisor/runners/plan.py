"""The trade plan from the entry price, and how a trade settles bar by bar."""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal

from advisor.runners.rule import Bar, Rule


@dataclass(frozen=True)
class Plan:
    entry: float
    stop: float
    target: float
    hold_by: date

    @property
    def r(self) -> float:
        return self.entry - self.stop


def _floor_cent(x: float) -> float:
    return math.floor(x * 100 + 1e-9) / 100  # 1.92 * 0.75 gives 1.44, not 1.43


def plan_for(entry: float, signal_low: float, hold_by: date, rule: Rule) -> Plan | None:
    """The stop is the closer of D's low and the floor under the entry.

    None when there is no stop, or no stop under the entry: a zero R would divide by zero.
    """
    candidates = []
    if signal_low < entry:
        candidates.append(signal_low)
    if rule.stop_floor is not None:
        candidates.append(entry * (1 - rule.stop_floor))
    if not candidates:
        return None
    stop = _floor_cent(max(candidates))
    if stop <= 0 or stop >= entry:
        return None
    return Plan(entry=entry, stop=stop, target=round(entry + rule.target_r * (entry - stop), 2), hold_by=hold_by)


def gapped(signal_close: float, entry: float, rule: Rule) -> bool:
    """True when the entry opens too far above D's close to take."""
    return rule.gap_skip is not None and entry / signal_close - 1 > rule.gap_skip


@dataclass(frozen=True)
class Outcome:
    status: Literal["open", "target", "stop", "held"]
    exit_day: date | None
    exit_price: float | None
    gross_r: float | None
    last_day: date
    last_close: float


def settle(bars: Sequence[Bar], plan: Plan) -> Outcome:
    """Walk the bars from the entry day. A bar that touches both the stop and the target is a stop."""

    def closed(status: Literal["target", "stop", "held"], bar: Bar, price: float) -> Outcome:
        return Outcome(status, bar.day, price, (price - plan.entry) / plan.r, bar.day, bar.close)

    for bar in bars:
        if bar.open <= plan.stop:
            return closed("stop", bar, bar.open)
        if bar.open >= plan.target:
            return closed("target", bar, bar.open)
        if bar.low <= plan.stop:
            return closed("stop", bar, plan.stop)
        if bar.high >= plan.target:
            return closed("target", bar, plan.target)
        if bar.day >= plan.hold_by:
            return closed("held", bar, bar.close)
    last = bars[-1]
    return Outcome("open", None, None, None, last.day, last.close)
