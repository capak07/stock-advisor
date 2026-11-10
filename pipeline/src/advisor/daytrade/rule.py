"""The opening-range breakout rule: session clock, range, entry trigger, exit plan.

Ported from the day-trader skill (MIT, github.com/Jakeschincariol/day-trader-skill):
entry.py (evaluate, early_cutoff) and exit.py (compute, floor_cents). Long only.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from datetime import time as dtime
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal

from advisor.daytrade.bars import BAR_MIN, Bar
from advisor.models import ET, Market
from advisor.schedule import market_close_et

RANGE_BARS = 3
TARGET_R = 2
CENT = Decimal("0.01")
MIN_RISK_PCT = Decimal("0.05")  # the skill: a stop tighter than 0.05% of the price is refused


@dataclass(frozen=True)
class Session:
    day: date
    market: Market
    open: datetime
    close: datetime
    no_entries_after: datetime
    flat_by: datetime


@dataclass(frozen=True)
class OpeningRange:
    high: float
    low: float
    avg_volume: float


@dataclass(frozen=True)
class Trigger:
    bar: Bar
    at: datetime  # bar.start + 5 minutes
    entry: float
    volume_x: float


@dataclass(frozen=True)
class Plan:
    entry: float
    stop: float
    target: float
    risk: float
    flat_by: datetime


def session_for(day: date, market: Market) -> Session | None:
    close_t = market_close_et(day, market)
    if close_t is None:
        return None
    close = datetime.combine(day, close_t, tzinfo=ET)
    return Session(
        day=day,
        market=market,
        open=datetime.combine(day, dtime(9, 30), tzinfo=ET),
        close=close,
        no_entries_after=close - timedelta(minutes=30),
        flat_by=close - timedelta(minutes=5),
    )


def opening_range(bars: Sequence[Bar], s: Session) -> OpeningRange | None:
    by_start = {b.start.astimezone(ET): b for b in bars}
    rng: list[Bar] = []
    for i in range(RANGE_BARS):
        b = by_start.get(s.open + timedelta(minutes=BAR_MIN * i))
        if b is None:
            return None
        rng.append(b)
    return OpeningRange(
        high=max(b.high for b in rng),
        low=min(b.low for b in rng),
        avg_volume=sum(b.volume for b in rng) / RANGE_BARS,
    )


def find_trigger(
    bars: Sequence[Bar], s: Session, rng: OpeningRange, min_volume_x: float = 1.5
) -> Trigger | None:
    first = s.open + timedelta(minutes=BAR_MIN * RANGE_BARS)
    for b in sorted(bars, key=lambda x: x.start):
        start = b.start.astimezone(ET)
        end = start + timedelta(minutes=BAR_MIN)
        if start < first or end > s.no_entries_after:
            continue
        if b.close <= rng.high:
            continue
        if rng.avg_volume > 0:
            vx = b.volume / rng.avg_volume
        elif min_volume_x <= 0:
            vx = 0.0
        else:
            continue
        if vx < min_volume_x:
            continue
        return Trigger(bar=b, at=end, entry=_cents(Decimal(repr(b.close))), volume_x=vx)
    return None


def _cents(x: Decimal) -> float:
    return float(x.quantize(CENT, rounding=ROUND_HALF_UP))


def plan_for(trigger: Trigger, rng: OpeningRange, s: Session) -> Plan | None:
    entry = Decimal(repr(trigger.entry))
    mid = (Decimal(repr(rng.high)) + Decimal(repr(rng.low))) / 2
    stop = mid.quantize(CENT, rounding=ROUND_FLOOR)
    risk = entry - stop
    if stop <= 0 or risk < max(CENT, entry * MIN_RISK_PCT / 100):
        return None
    target = (entry + TARGET_R * risk).quantize(CENT, rounding=ROUND_HALF_UP)
    return Plan(
        entry=float(entry),
        stop=float(stop),
        target=float(target),
        risk=float(risk),
        flat_by=s.flat_by,
    )
