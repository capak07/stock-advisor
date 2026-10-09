"""Daily bars from the primary source, filled and cross-checked by the fallback source.

Sanity rule (spec §10): a close-to-close move above 50% is dropped unless the other source
reports the same close for that day within 2%.
"""

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from itertools import pairwise

from advisor.collectors.base import CollectorResult
from advisor.models import DailyBar

JUMP_LIMIT = 0.5
CONFIRM_TOLERANCE = 0.02

RunFn = Callable[[Sequence[str]], CollectorResult]


@dataclass(frozen=True)
class PriceFetch:
    bars: dict[str, list[DailyBar]]
    results: list[CollectorResult]


def group_bars(records: Iterable[DailyBar]) -> dict[str, list[DailyBar]]:
    by_symbol: dict[str, dict[date, DailyBar]] = {}
    for record in records:
        by_symbol.setdefault(record.symbol, {})[record.day] = record
    return {s: [days[d] for d in sorted(days)] for s, days in by_symbol.items()}


def _has_jump(bars: Sequence[DailyBar]) -> bool:
    return any(abs(cur.close / prev.close - 1) > JUMP_LIMIT for prev, cur in pairwise(bars))


def find_unconfirmed_jumps(bars: Sequence[DailyBar], reference: Sequence[DailyBar]) -> set[date]:
    ref_close = {b.day: b.close for b in reference}
    bad: set[date] = set()
    for prev, cur in pairwise(bars):
        if abs(cur.close / prev.close - 1) <= JUMP_LIMIT:
            continue
        other = ref_close.get(cur.day)
        if other is None or abs(other / cur.close - 1) > CONFIRM_TOLERANCE:
            bad.add(cur.day)
    return bad


def fetch_daily_bars(
    symbols: Sequence[str], *, primary_run: RunFn, fallback_run: RunFn
) -> PriceFetch:
    wanted = sorted(set(symbols))
    first = primary_run(wanted)
    results = [first]
    primary = group_bars(first.records)

    missing = [s for s in wanted if s not in primary]
    suspects = [s for s, bars in primary.items() if _has_jump(bars)]
    need = sorted(set(missing) | set(suspects))
    reference: dict[str, list[DailyBar]] = {}
    if need:
        second = fallback_run(need)
        results.append(second)
        reference = group_bars(second.records)

    bars: dict[str, list[DailyBar]] = {}
    for symbol in wanted:
        if symbol in primary:
            own, other = primary[symbol], reference.get(symbol, [])
        elif symbol in reference:
            own, other = reference[symbol], []
        else:
            continue
        bad = find_unconfirmed_jumps(own, other)
        kept = [b for b in own if b.day not in bad]
        if kept:
            bars[symbol] = kept
    return PriceFetch(bars=bars, results=results)
