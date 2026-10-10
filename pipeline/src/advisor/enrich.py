"""Enrichment stage (spec §4.3 stage 4): which symbols each collector gets, run concurrently.

Holdings and watchlist symbols always come first, so collectors with daily caps spend them on
the owner's positions before the rest of the shortlist (spec §7.2).
"""

from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from advisor.collectors.base import Collector, CollectorResult, Scope
from advisor.collectors.tracker import SourceTracker
from advisor.models import AssetType
from advisor.screener import ScreenRow

SHORTLIST_SIZE = 300
ENRICH_WORKERS = 8


def shortlist(
    passed: Sequence[ScreenRow], priority: Sequence[str], size: int = SHORTLIST_SIZE
) -> list[str]:
    """Priority symbols first (as given), then up to `size` passing symbols by dollar volume.

    Interim ranking: Plan 3's screener model replaces 20-day dollar volume as the sort key.
    """
    chosen = set(priority)
    ranked = [
        r.symbol
        for r in sorted(passed, key=lambda r: (-r.adv20, r.symbol))
        if r.symbol not in chosen
    ]
    return list(priority) + ranked[:size]


@dataclass(frozen=True)
class EnrichTargets:
    stocks: list[str]  # priority stocks first, then the shortlist
    crypto: list[str]  # held and watchlist crypto, holdings first


def symbols_for(collector: Collector, targets: EnrichTargets) -> list[str]:
    if collector.scope is not Scope.SYMBOLS:
        return []
    symbols: list[str] = []
    if AssetType.STOCK in collector.asset_types:
        symbols += targets.stocks
    if AssetType.CRYPTO in collector.asset_types:
        symbols += targets.crypto
    return symbols


def run_enrichment(
    tracker: SourceTracker,
    collectors: Mapping[str, Collector],
    names: Sequence[str],
    targets: EnrichTargets,
    *,
    workers: int = ENRICH_WORKERS,
) -> dict[str, CollectorResult]:
    """Run each named collector once, concurrently; SYMBOLS collectors with no targets are skipped."""
    jobs: dict[str, list[str]] = {}
    for name in names:
        collector = collectors[name]
        symbols = symbols_for(collector, targets)
        if collector.scope is Scope.SYMBOLS and not symbols:
            continue
        jobs[name] = symbols
    if not jobs:
        return {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {name: pool.submit(tracker.run, name, symbols) for name, symbols in jobs.items()}
        return {name: future.result() for name, future in futures.items()}
