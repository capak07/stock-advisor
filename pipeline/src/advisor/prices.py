"""Daily stock bars from Yahoo, the only stock price source (spec R7).

Jump rule (spec §10): a close that moves more than 50% against both the last accepted close and
the previous close is flagged as an unconfirmed jump. With no second source to confirm it, the
bar is kept; features, picks and holding actions treat flagged days with care.
"""

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from itertools import pairwise

from advisor.collectors.base import CollectorResult
from advisor.models import DailyBar

JUMP_LIMIT = 0.5

RunFn = Callable[[Sequence[str]], CollectorResult]


@dataclass(frozen=True)
class PriceFetch:
    bars: dict[str, list[DailyBar]]
    flagged: dict[str, set[date]]  # only symbols with at least one unconfirmed jump


def group_bars(records: Iterable[DailyBar]) -> dict[str, list[DailyBar]]:
    by_symbol: dict[str, dict[date, DailyBar]] = {}
    for record in records:
        by_symbol.setdefault(record.symbol, {})[record.day] = record
    return {s: [days[d] for d in sorted(days)] for s, days in by_symbol.items()}


def find_jumps(bars: Sequence[DailyBar]) -> set[date]:
    """Days whose close moves >50% vs both the last unflagged close and the previous close."""
    flagged: set[date] = set()
    if not bars:
        return flagged
    last_accepted = bars[0].close
    for prev, cur in pairwise(bars):
        if (
            abs(cur.close / last_accepted - 1) > JUMP_LIMIT
            and abs(cur.close / prev.close - 1) > JUMP_LIMIT
        ):
            flagged.add(cur.day)
        else:
            last_accepted = cur.close
    return flagged


def fetch_daily_bars(symbols: Sequence[str], *, run: RunFn) -> PriceFetch:
    """One Yahoo call for `symbols`; every bar is kept and jumps are flagged."""
    bars = group_bars(run(sorted(set(symbols))).records)
    flagged = {symbol: days for symbol, history in bars.items() if (days := find_jumps(history))}
    return PriceFetch(bars=bars, flagged=flagged)
