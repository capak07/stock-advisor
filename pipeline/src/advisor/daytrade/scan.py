"""The day trade scan: today's opening-range breakouts across a list of stocks, in two stages.

Ported from the day-trader skill (MIT, github.com/Jakeschincariol/day-trader-skill):
scan.py (scan_orb, usable, orb_candidate, orb_hit, session_bars).

Stage 1 reads closes for every listing in a few spark requests and keeps the candidates:
a completed post-range bar closed at or above the highest range close (necessary for a
breakout). Stage 2 reads real 5-minute charts for the candidates and runs the rule.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from advisor.collectors.yfinance_bars import to_yahoo
from advisor.daytrade.bars import BAR_MIN, SPARK_MAX, Bar, YahooClient, YahooError, session_bars
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


@dataclass(frozen=True)
class ScanResult:
    scanned: int
    usable: int
    candidates: list[Listing]
    found: list[Found]
    errors: int


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


def scan(
    client: YahooClient,
    listings: Sequence[Listing],
    now: datetime,
    *,
    min_price: float = 5.0,
    max_confirm: int | None = None,
    min_volume_x: float = 1.5,
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

    errors = 0
    scanned = 0
    usable = 0
    spark: dict[str, list[tuple[datetime, float]]] = {}
    failed: set[str] = set()
    for k in range(0, len(todo), SPARK_MAX):
        batch = todo[k : k + SPARK_MAX]
        try:
            spark.update(client.spark_closes([y for _, y, _ in batch], "1d", "5m"))
        except YahooError:
            errors += len(batch)
            failed.update(y for _, y, _ in batch)

    cands: list[tuple[Listing, str, Session, float]] = []
    for lst, y, s in todo:
        if y in failed:
            continue
        pts = spark.get(y)
        if pts is None:
            errors += 1
            continue
        scanned += 1
        bars = session_bars(_spark_bars(pts), s.day, cutoff)
        if not _usable(bars, s, cutoff):
            continue
        usable += 1
        last = bars[-1].close
        if last < min_price:
            continue
        if _is_candidate(bars):
            # spark carries no volume, so the stage-1 order is by price alone
            cands.append((lst, y, s, last))

    cands.sort(key=lambda c: -c[3])
    ranked = cands if max_confirm is None else cands[:max_confirm]

    found: list[Found] = []
    for lst, y, s, _ in ranked:
        try:
            full = session_bars(client.chart(y, "1d", "5m"), s.day, cutoff)
        except YahooError:
            errors += 1
            continue
        if not _usable(full, s, cutoff):
            errors += 1
            continue
        rng = opening_range(full, s)
        if rng is None:
            continue
        trig = find_trigger(full, s, rng, min_volume_x)
        if trig is None:
            continue
        plan = plan_for(trig, rng, s)
        if plan is None:
            continue
        found.append(Found(lst, rng, trig, plan, full))
    found.sort(key=lambda f: (f.trigger.at, f.listing.symbol))
    return ScanResult(scanned, usable, [c[0] for c in cands], found, errors)
