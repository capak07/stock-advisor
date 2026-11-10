"""The Time Machine: replays of the rest of the session, and the rule on past sessions.

Ported from the day-trader skill (MIT, github.com/Jakeschincariol/day-trader-skill):
timemachine.py (full_sessions, build_pool, pct, simulate, history_replay). The
random draws are the skill's, in the same order, so the same seed gives the same
numbers. Long only.
"""

import hashlib
import random
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from advisor.daytrade.bars import BAR_MIN, Bar
from advisor.daytrade.rule import (
    RANGE_BARS,
    Plan,
    Session,
    Trigger,
    find_trigger,
    opening_range,
    plan_for,
    session_for,
)
from advisor.models import ET, Market

SESSION_BARS = 78  # 9:30 to 16:00 in 5-minute bars


@dataclass(frozen=True)
class ReplayStats:
    replays: int
    target_first: float
    stop_first: float
    neither: float
    green: float
    avg_r: float
    close_p05: float
    close_p50: float
    close_p95: float
    sessions: int


@dataclass(frozen=True)
class HistoryStats:
    sessions: int
    fired: int
    target: int
    stop: int
    neither: int
    avg_r: float


def seed_for(day: date, symbol: str) -> int:
    digest = hashlib.sha256(f"{day.isoformat()}|{symbol}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def _full_sessions(history: Sequence[Bar], before: date) -> list[tuple[date, list[Bar]]]:
    days: dict[date, dict[int, Bar]] = {}
    for b in history:
        start = b.start.astimezone(ET)
        slot = (start.hour * 60 + start.minute - (9 * 60 + 30)) // BAR_MIN
        if 0 <= slot < SESSION_BARS:
            days.setdefault(start.date(), {})[slot] = b
    return [
        (d, [days[d][i] for i in range(SESSION_BARS)])
        for d in sorted(days)
        if d < before and len(days[d]) == SESSION_BARS
    ]


def _pct(a: list[float], q: float) -> float:
    return a[min(len(a) - 1, int(q * len(a)))]


def replay(
    history: Sequence[Bar],
    plan: Plan,
    trigger: Trigger,
    s: Session,
    *,
    replays: int = 10_000,
    seed: int,
    window: int = 2,
) -> ReplayStats:
    sessions = _full_sessions(history, s.day)
    if not sessions:
        raise ValueError("no full past sessions to replay")
    pool: list[list[tuple[float, float, float]]] = [[] for _ in range(SESSION_BARS)]
    for _, d in sessions:
        for i in range(1, SESSION_BARS):
            pc = d[i - 1].close
            pool[i].append((d[i].high / pc, d[i].low / pc, d[i].close / pc))
    k = int((trigger.at - s.open) / timedelta(minutes=BAR_MIN)) - 1
    last = int((plan.flat_by - s.open) / timedelta(minutes=BAR_MIN)) - 1
    entry, stop, target = plan.entry, plan.stop, plan.target
    risk = entry - stop
    r_target = round((target - entry) / risk, 4)

    def slot(rng: random.Random, i: int) -> int:
        return i if window == 0 else min(SESSION_BARS - 1, max(1, i + rng.randint(-window, window)))

    rng = random.Random(seed)
    choice = rng.choice
    n_target = n_stop = n_neither = green = 0
    r_sum = 0.0
    closes: list[float] = []
    for _ in range(replays):
        p = entry
        outcome = None
        for i in range(k + 1, last + 1):
            h, lo, c = choice(pool[slot(rng, i)])
            if outcome is None:
                if p * lo <= stop:
                    outcome = "stop"
                elif p * h >= target:
                    outcome = "target"
            p = p * c
        closes.append(p)
        if outcome == "target":
            n_target += 1
            green += 1
            r_sum += r_target
        elif outcome == "stop":
            n_stop += 1
            r_sum += -1.0
        else:
            n_neither += 1
            if p > entry:
                green += 1
            r_sum += (p - entry) / risk
    closes.sort()
    return ReplayStats(
        replays=replays,
        target_first=n_target / replays,
        stop_first=n_stop / replays,
        neither=n_neither / replays,
        green=green / replays,
        avg_r=r_sum / replays,
        close_p05=_pct(closes, 0.05),
        close_p50=_pct(closes, 0.5),
        close_p95=_pct(closes, 0.95),
        sessions=len(sessions),
    )


def rule_history(
    history: Sequence[Bar], before: date, market: Market, min_volume_x: float = 1.5
) -> HistoryStats:
    sessions = _full_sessions(history, before)
    rs: list[float] = []
    target_n = stop_n = neither_n = 0
    for d, bars in sessions:
        s = session_for(d, market)
        if s is None:
            continue
        rng = opening_range(bars, s)
        if rng is None:
            continue
        trig = find_trigger(bars, s, rng, min_volume_x)
        if trig is None:
            continue
        plan = plan_for(trig, rng, s)
        if plan is None:
            continue
        first = int((trig.at - s.open) / timedelta(minutes=BAR_MIN))
        last = int((s.flat_by - s.open) / timedelta(minutes=BAR_MIN)) - 1
        assert first >= RANGE_BARS
        outcome = None
        for b in bars[first : last + 1]:
            if b.low <= plan.stop:
                outcome = "stop"
                break
            if b.high >= plan.target:
                outcome = "target"
                break
        if outcome == "target":
            target_n += 1
            rs.append((plan.target - plan.entry) / plan.risk)
        elif outcome == "stop":
            stop_n += 1
            rs.append(-1.0)
        else:
            neither_n += 1
            rs.append((bars[last].close - plan.entry) / plan.risk)
    return HistoryStats(
        sessions=len(sessions),
        fired=len(rs),
        target=target_n,
        stop=stop_n,
        neither=neither_n,
        avg_r=sum(rs) / len(rs) if rs else 0.0,
    )
