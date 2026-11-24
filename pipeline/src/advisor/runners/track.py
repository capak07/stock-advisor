"""How one signal plays out from the bars after it. Live tracking and the backtest both call `track`.

The entry is the first bar after the signal day, if it comes within 5 sessions. A trade settles on bars
up to 5 sessions after its hold-by, and never on a bar from a suspected unrecorded split on: Yahoo can
take days to rescale the history, and one bar at 10 times the price would book a fake target.
"""

from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np

from advisor.runners.plan import Outcome, Plan, gapped, plan_for, settle
from advisor.runners.rule import SPLIT_VOLUME_SESSIONS, Rule, Series, split_days

NO_PRICES = 5  # sessions without a bar before a signal is given up on, or an open trade closed
GAPPED = "gapped up at the open"
UNDER_STOP = "opened under the stop"
NO_PRICES_SIGNAL = "no prices after the signal"
NO_PRICES_HELD = "no prices: closed at the last close"


@dataclass(frozen=True)
class Tracked:
    """What happened to one signal.

    No reason and no outcome means it is still waiting: for a trustworthy entry bar, or (in the
    backtest) for sessions that reach its hold-by. A skip has a reason and no outcome; a trade closed at
    its last close for want of prices has both.
    """

    reason: str | None = None
    entry_day: date | None = None
    plan: Plan | None = None
    outcome: Outcome | None = None
    split_wait: bool = False  # a split-suspect bar is holding it back

    @property
    def status(self) -> str:
        if self.outcome is not None:
            return self.outcome.status
        return "waiting" if self.reason is None else "skipped"


def session_after(sessions: Sequence[date], day: date, n: int) -> date | None:
    """The n-th session after `day`; None past the sessions given."""
    i = bisect_right(sessions, day) + n - 1
    return sessions[i] if i < len(sessions) else None


def hold_by(entry_day: date, sessions: Sequence[date], rule: Rule) -> date | None:
    """The hold's last session, counting the entry day as day 1."""
    n = rule.hold_sessions
    return entry_day if n <= 1 else session_after(sessions, entry_day, n - 1)


def _past(sessions: Sequence[date], day: date, through: date) -> bool:
    """True once `through` is at least 5 sessions after `day`."""
    after = session_after(sessions, day, NO_PRICES)
    return after is not None and after <= through


def held_at_last_close(plan: Plan, last_day: date, last_close: float, sessions: Sequence[date],
                       through: date) -> Outcome | None:
    """An open trade with no trusted bar for 5 sessions, 5 sessions past its hold-by, closes at its last close."""
    if not (_past(sessions, last_day, through) and _past(sessions, plan.hold_by, through)):
        return None
    return Outcome("held", last_day, last_close, (last_close - plan.entry) / plan.r, last_day, last_close)


def _first_split(s: Series, start: int, stop: int) -> int:
    """The first split-suspect session in [start, stop), or stop. Reads the 50 sessions before start."""
    lo = max(0, start - SPLIT_VOLUME_SESSIONS)
    window = Series(days=s.days[lo:stop], open=s.open[lo:stop], high=s.high[lo:stop], low=s.low[lo:stop],
                    close=s.close[lo:stop], volume=s.volume[lo:stop], raw_close=s.raw_close[lo:stop])
    hits = np.flatnonzero(split_days(window)[start - lo:])
    return start + int(hits[0]) if hits.size else stop


def track(s: Series | None, signal_day: date, signal_close: float, signal_low: float, sessions: Sequence[date],
          rule: Rule, through: date) -> Tracked:
    """The signal on `signal_day`, from the bars after it in `s`, as of `through`, the last session priced.

    `signal_close` and `signal_low` must be on the same price scale as `s`. `sessions` must run past
    `through` far enough to hold the hold-by and the 5 sessions after it.
    """
    days = () if s is None else s.days
    start = bisect_right(days, signal_day)
    # no bar after an entry 5 sessions late, the whole hold and 5 more sessions can matter
    latest = session_after(sessions, signal_day, 2 * NO_PRICES + max(rule.hold_sessions, 1) - 1)
    stop = len(days) if latest is None else bisect_right(days, latest)
    end = start if s is None else _first_split(s, start, stop)
    held_back = end < stop
    bars = [] if s is None else s.bars(start, end)

    give_up = session_after(sessions, signal_day, NO_PRICES)
    if not bars or (give_up is not None and bars[0].day > give_up):
        if give_up is not None and give_up <= through:
            return Tracked(reason=NO_PRICES_SIGNAL)
        return Tracked(split_wait=held_back)

    entry_day, entry = bars[0].day, bars[0].open
    last = hold_by(entry_day, sessions, rule)
    if last is None:
        return Tracked(entry_day=entry_day)
    if gapped(signal_close, entry, rule):
        return Tracked(reason=GAPPED, entry_day=entry_day)
    plan = plan_for(entry, signal_low, last, rule)
    if plan is None:
        return Tracked(reason=UNDER_STOP, entry_day=entry_day)

    cap = session_after(sessions, plan.hold_by, NO_PRICES)
    outcome = settle([b for b in bars if cap is None or b.day <= cap], plan)
    if outcome.status != "open":
        return Tracked(entry_day=entry_day, plan=plan, outcome=outcome)
    held = held_at_last_close(plan, outcome.last_day, outcome.last_close, sessions, through)
    if held is not None:
        return Tracked(reason=NO_PRICES_HELD, entry_day=entry_day, plan=plan, outcome=held)
    return Tracked(entry_day=entry_day, plan=plan, outcome=outcome, split_wait=held_back)
