"""Enrichment stage (spec §4.3 stage 4): which symbols each collector gets, run concurrently.

Holdings and watchlist symbols always come first, so collectors with daily caps spend them on
the owner's positions before the rest of the shortlist (spec §7.2). A collector only gets stock symbols of the markets it covers.
"""

from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from itertools import zip_longest

from advisor.collectors.base import Collector, CollectorResult, Scope
from advisor.collectors.tracker import SourceTracker
from advisor.markets import market_of
from advisor.models import AssetType
from advisor.screener import ScreenRow

SHORTLIST_SIZE = 300
ENRICH_WORKERS = 8


def ranked_shortlist(
    passed: Sequence[ScreenRow],
    exclude: Sequence[str],
    size: int = SHORTLIST_SIZE,
    scores: Mapping[str, float] | None = None,
) -> list[str]:
    """Up to `size` passing symbols not in `exclude`.

    With `scores` (the model's screener score) the best score comes first, then dollar volume, then
    symbol; a symbol without a score follows every scored one. Without, dollar volume then symbol.
    """
    skip = set(exclude)

    def key(r: ScreenRow) -> tuple[bool, float, float, str]:
        score = None if scores is None else scores.get(r.symbol)
        return (score is None, -(score or 0.0), -r.adv20, r.symbol)

    return [r.symbol for r in sorted(passed, key=key) if r.symbol not in skip][:size]


def shortlist(
    passed: Sequence[ScreenRow], priority: Sequence[str], size: int = SHORTLIST_SIZE
) -> list[str]:
    """Priority symbols first (as given), then up to `size` passing symbols by dollar volume."""
    return list(priority) + ranked_shortlist(passed, priority, size)


def interleave(*lists: Sequence[str]) -> list[str]:
    """Round-robin merge (a1, b1, a2, b2, ...), so capped collectors reach every market's best."""
    return [symbol for group in zip_longest(*lists) for symbol in group if symbol is not None]


@dataclass(frozen=True)
class EnrichTargets:
    priority_stocks: list[str]  # holdings, then watchlist-only stocks
    crypto: list[str]  # held, then watchlist-only crypto (every crypto symbol is priority)
    ranked_stocks: list[str]  # the rest of the shortlist, best first

    @property
    def stocks(self) -> list[str]:
        return self.priority_stocks + self.ranked_stocks


def symbols_for(collector: Collector, targets: EnrichTargets) -> list[str]:
    if collector.scope is not Scope.SYMBOLS:
        return []

    def covered(stocks: Sequence[str]) -> list[str]:
        return [s for s in stocks if market_of(s) in collector.markets]

    symbols: list[str] = []
    stocks = AssetType.STOCK in collector.asset_types
    if stocks:
        symbols += covered(targets.priority_stocks)
    if AssetType.CRYPTO in collector.asset_types:
        symbols += targets.crypto  # held and watched crypto outrank the stock shortlist
    if stocks:
        symbols += covered(targets.ranked_stocks)
    return symbols


def wanted(collector: Collector, symbols: Sequence[str], targets: EnrichTargets) -> bool:
    """SYMBOLS collectors need targets; a crypto-only market-wide source needs some crypto."""
    if collector.scope is Scope.SYMBOLS:
        return bool(symbols)
    return AssetType.STOCK in collector.asset_types or bool(targets.crypto)


def run_enrichment(
    tracker: SourceTracker,
    collectors: Mapping[str, Collector],
    names: Sequence[str],
    targets: EnrichTargets,
    *,
    workers: int = ENRICH_WORKERS,
) -> dict[str, CollectorResult]:
    """Run each named collector once, concurrently, skipping those with nothing to do."""
    jobs: dict[str, list[str]] = {}
    for name in names:
        symbols = symbols_for(collectors[name], targets)
        if wanted(collectors[name], symbols, targets):
            jobs[name] = symbols
    if not jobs:
        return {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {name: pool.submit(tracker.run, name, symbols) for name, symbols in jobs.items()}
        return {name: future.result() for name, future in futures.items()}
