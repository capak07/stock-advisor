"""The day trade scan: today's opening-range breakouts across a list of stocks, in two stages.

Ported from the day-trader skill (MIT, github.com/Jakeschincariol/day-trader-skill):
scan.py (scan_orb, usable, orb_candidate, orb_hit, session_bars).

Stage 1 reads closes for every listing in a few spark requests and keeps the candidates:
a completed post-range bar closed at or above the highest range close (necessary for a
breakout). Stage 2 reads real 5-minute charts for the candidates and runs the rule.

Within a job, stage 2 remembers each charted candidate's real opening-range high and the last
bar it checked. A candidate is charted again only when a newer spark bar closed above that high
(the trigger's price condition; only the volume needs the chart). Charts go oldest checked bar
first (never charted counts as oldest), then most traded, so when the cap on charts per cycle
binds, every candidate still takes its turn.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from advisor.collectors.yfinance_bars import to_yahoo
from advisor.daytrade.bars import (
    BAR_MIN,
    SPARK_MAX,
    Bar,
    SparkSeries,
    YahooClient,
    YahooError,
    session_bars,
)
from advisor.daytrade.rule import (
    RANGE_BARS,
    OpeningRange,
    Plan,
    Session,
    Trigger,
    find_trigger,
    opening_range,
    plan_for,
    session_for,
)
from advisor.models import ET, Market


@dataclass(frozen=True)
class Listing:
    symbol: str
    market: Market
    name: str | None = None


@dataclass(frozen=True)
class Found:
    listing: Listing
    rng: OpeningRange
    trigger: Trigger
    plan: Plan
    bars: list[Bar]


# Yahoo symbol -> (its real opening-range high, the start of the last bar checked for it)
Charted = Mapping[str, tuple[float, datetime]]


@dataclass(frozen=True)
class ScanResult:
    scanned: int
    usable: int
    candidates: list[Listing]
    found: list[Found]
    errors: int
    unusable: int = 0  # stage-2 charts with a missing bar
    charted: dict[str, tuple[float, datetime]] = field(default_factory=dict)  # for the next cycle
    confirm: int = 0  # stage-2 charts wanted this cycle
    confirm_failed: int = 0  # of those, failed (or not tried after the bail-out)


def _usable(bars: Sequence[Bar], s: Session, cutoff: datetime) -> bool:
    """Every 5-minute slot from the open to the cutoff (or the close) is there, and the range at least."""
    end = min(cutoff, s.close)
    want = int((end - s.open).total_seconds() // (BAR_MIN * 60))
    if want < RANGE_BARS or len(bars) != want:
        return False
    return all(b.start.astimezone(ET) == s.open + timedelta(minutes=BAR_MIN * k) for k, b in enumerate(bars))


def _is_candidate(bars: Sequence[Bar]) -> bool:
    top = max(b.close for b in bars[:RANGE_BARS])
    return any(b.close >= top for b in bars[RANGE_BARS:])


def _spark_bars(points: Sequence[tuple[datetime, float]]) -> list[Bar]:
    return [Bar(t, c, c, c, c, 0.0) for t, c in points]

MAX_FAILED_BATCHES = 5  # in a row: Yahoo is down, stop the cycle
MAX_FAILED_CHARTS = 5  # the same for charts (stage 2 and tracking)
_NEVER = datetime.min.replace(tzinfo=UTC)  # "last checked" of a candidate never charted


def scan(
    client: YahooClient,
    listings: Sequence[Listing],
    now: datetime,
    *,
    min_price: float = 5.0,
    max_confirm: int | None = None,
    min_volume_x: float = 1.5,
    charted: Charted | None = None,
) -> ScanResult:
    now_et = now.astimezone(ET)
    cutoff = now_et.replace(second=0, microsecond=0)
    sessions: dict[Market, Session | None] = {}
    todo: list[tuple[Listing, str, Session]] = []
    for lst in listings:
        if lst.market not in sessions:
            sessions[lst.market] = session_for(now_et.date(), lst.market)
        s = sessions[lst.market]
        if s is not None:
            todo.append((lst, to_yahoo(lst.symbol), s))

    memory = dict(charted or {})
    errors = 0
    unusable_s2 = 0
    scanned = 0
    usable = 0
    spark: dict[str, SparkSeries] = {}
    failed: set[str] = set()
    streak = 0
    for k in range(0, len(todo), SPARK_MAX):
        if k:
            client.wait()
        batch = todo[k : k + SPARK_MAX]
        try:
            spark.update(client.spark_series([y for _, y, _ in batch], "1d", "5m"))
            streak = 0
        except YahooError:
            errors += len(batch)
            failed.update(y for _, y, _ in batch)
            streak += 1
            if streak >= MAX_FAILED_BATCHES:
                errors += len(todo) - (k + len(batch))
                return ScanResult(scanned, usable, [], [], errors, charted=memory)

    cands: list[tuple[Listing, str, Session, float, list[Bar]]] = []
    for lst, y, s in todo:
        if y in failed:
            continue
        series = spark.get(y)
        if series is None:
            errors += 1
            continue
        scanned += 1
        bars = session_bars(_spark_bars(series.points), s.day, cutoff)
        if not _usable(bars, s, cutoff):
            continue
        usable += 1
        last = bars[-1].close
        if last < min_price:
            continue
        if _is_candidate(bars):
            cands.append((lst, y, s, last * series.volume, bars))

    cands.sort(key=lambda c: (-c[3], c[0].symbol))
    queue: list[tuple[datetime, tuple[Listing, str, Session, float, list[Bar]]]] = []
    for c in cands:
        seen = memory.get(c[1])
        if seen is None:
            queue.append((_NEVER, c))
            continue
        high, checked = seen
        new = [b for b in c[4] if b.start > checked]
        if any(b.close > high for b in new):
            queue.append((checked, c))
        elif new:
            memory[c[1]] = (high, new[-1].start)  # checked: every new bar closed under the high
    # Re-checks (a charted stock whose newer bar closed above its range high: the likely triggers)
    # go first, oldest checked first; stocks never charted follow, most traded first (cands' order;
    # the sort is stable). Under a cap each kind is sure of half, so a trigger among the most traded
    # is found within a cycle and the never-charted are still worked through.
    again = sorted((q for q in queue if q[0] is not _NEVER), key=lambda q: q[0])
    fresh = [q for q in queue if q[0] is _NEVER]
    if max_confirm is not None:
        again = again[: max(max_confirm // 2, max_confirm - len(fresh))]
        fresh = fresh[: max_confirm - len(again)]
    ranked = [c for _, c in (*again, *fresh)]

    found: list[Found] = []
    failed_charts = streak = 0
    for i, (lst, y, s, _, _) in enumerate(ranked):
        if streak >= MAX_FAILED_CHARTS:
            failed_charts += len(ranked) - i  # Yahoo is down: the rest wait for the next cycle
            errors += len(ranked) - i
            break
        if i:
            client.wait()
        try:
            full = session_bars(client.chart(y, "1d", "5m"), s.day, cutoff)
        except YahooError:
            errors += 1
            failed_charts += 1
            streak += 1
            continue
        streak = 0
        if not _usable(full, s, cutoff):
            unusable_s2 += 1
            continue
        rng = opening_range(full, s)
        if rng is None:
            continue
        memory[y] = (rng.high, full[-1].start)
        trig = find_trigger(full, s, rng, min_volume_x)
        if trig is None:
            continue
        plan = plan_for(trig, rng, s)
        if plan is None:
            continue
        found.append(Found(lst, rng, trig, plan, full))
    found.sort(key=lambda f: (f.trigger.at, f.listing.symbol))
    return ScanResult(
        scanned, usable, [c[0] for c in cands], found, errors, unusable_s2,
        charted=memory, confirm=len(ranked), confirm_failed=failed_charts,
    )
