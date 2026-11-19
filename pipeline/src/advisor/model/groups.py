"""The US data groups as model features: their history files, the frames they load into, and the one
function that turns the frames into wide day x symbol feature frames.

The point-in-time helpers every group shares live in `advisor.model.pit` (re-exported here). A group's
history is written weekly by `training.history`; `load_history` reads whatever of it the data directory
holds, and a group whose files are missing loads as None: its features read NaN, never zero, and its
rows fail closed in training (`variants.missing_groups`).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from advisor.model.analyst import ANALYST_FEATURES, analyst_features
from advisor.model.analyst import coverage as analyst_coverage
from advisor.model.catalysts import CATALYSTS_FEATURES, catalysts_features
from advisor.model.earnings import EARNINGS_FEATURES
from advisor.model.estimates import ESTIMATES_FEATURES, estimates_features
from advisor.model.events import EVENTS_FEATURES, events_features
from advisor.model.fundamentals import shares_outstanding
from advisor.model.holders import HOLDERS_FEATURES, holders_features
from advisor.model.insider import INSIDER_FEATURES, insider_features
from advisor.model.pit import (  # noqa: F401  (re-exported: the helpers' original home)
    covered_symbols,
    days_since,
    sec_known,
    window_count,
)
from advisor.model.short import SHORT_FEATURES, short_features

# Each data group's history files (written by `training.history`, read by the dataset), in the spec's
# priority order. `earnings` needs only fundamentals.parquet, so it is not a key.
GROUP_FILES: dict[str, tuple[str, ...]] = {
    "short": ("short_interest.parquet", "short_volume.parquet"),
    "analyst": ("analyst_events.parquet",),
    "insider": ("insider_trades.parquet",),
    "events": ("material_events.parquet", "large_holders.parquet"),
    "holders": ("holders.parquet",),
    "estimates": ("earnings_estimates.parquet",),
    "catalysts": ("fda_events.parquet",),
}

# every data group, in the order a config name lists them
DATA_GROUPS = ("short", "analyst", "insider", "events", "holders", "earnings", "estimates", "catalysts")
GROUP_FEATURES: dict[str, list[str]] = {
    "short": SHORT_FEATURES,
    "analyst": ANALYST_FEATURES,
    "insider": INSIDER_FEATURES,
    "events": EVENTS_FEATURES,
    "holders": HOLDERS_FEATURES,
    "earnings": EARNINGS_FEATURES,
    "estimates": ESTIMATES_FEATURES,
    "catalysts": CATALYSTS_FEATURES,
}
ALL_GROUP_FEATURES = [name for group in DATA_GROUPS for name in GROUP_FEATURES[group]]
# the letter each group takes in a config name that would pass 40 characters
LETTERS = {"short": "s", "analyst": "a", "insider": "i", "events": "v", "holders": "h", "earnings": "e",
           "estimates": "t", "catalysts": "c"}


@dataclass(frozen=True, eq=False)  # frames do not compare
class GroupHistory:
    """The groups' history frames; None for a file the data directory does not hold."""

    short_interest: pd.DataFrame | None = None
    short_volume: pd.DataFrame | None = None
    analyst_events: pd.DataFrame | None = None
    analyst_coverage: pd.DataFrame | None = None  # built from `analyst_events`, not a file
    material_events: pd.DataFrame | None = None
    large_holders: pd.DataFrame | None = None
    insider_trades: pd.DataFrame | None = None
    holders: pd.DataFrame | None = None
    estimates: pd.DataFrame | None = None
    fda_events: pd.DataFrame | None = None


# each file of GROUP_FILES -> the GroupHistory field it loads into: the file stem, but `estimates`
FILE_FIELDS: dict[str, str] = {
    name: "estimates" if name == "earnings_estimates.parquet" else name.removesuffix(".parquet")
    for files in GROUP_FILES.values() for name in files
}


def load_history(data_dir: Path) -> GroupHistory:
    """The history files of `GROUP_FILES` that exist in `data_dir`; a missing file is None."""
    loaded = {
        field: pd.read_parquet(data_dir / name)
        for name, field in FILE_FIELDS.items() if (data_dir / name).exists()
    }
    if (events := loaded.get("analyst_events")) is not None:
        loaded["analyst_coverage"] = analyst_coverage(events)
    return GroupHistory(**loaded)


def present(history: GroupHistory) -> frozenset[str]:
    """The groups whose every source frame is present. `earnings` needs only the SEC facts, so it is always there."""
    have = {
        group for group, files in GROUP_FILES.items()
        if all(getattr(history, FILE_FIELDS[name]) is not None for name in files)
    }
    return frozenset(have | {"earnings"})


def group_features(history: GroupHistory, facts: pd.DataFrame, tickers: pd.DataFrame, split_adjusted: pd.DataFrame,
                   splits: pd.DataFrame, days: pd.DatetimeIndex, symbols: Sequence[str]) -> dict[str, pd.DataFrame]:
    """Wide frames (days x `symbols`) of every name in ALL_GROUP_FEATURES except the earnings ones.

    A source that is absent (None) leaves its features NaN. The shares outstanding the short, holders and
    insider features divide by are computed once here, and only when one of those groups has its history.
    """
    symbols = list(symbols)
    needs_shares = any(
        frame is not None for frame in (history.short_interest, history.holders, history.insider_trades))
    shares = (shares_outstanding(facts, tickers, days, symbols, splits) if needs_shares
              else pd.DataFrame(np.nan, index=days, columns=symbols))
    market_value = split_adjusted.loc[days, symbols] * shares
    covered = covered_symbols(facts, tickers)
    out = short_features(history.short_interest, history.short_volume, shares, splits, days, symbols)
    out |= analyst_features(history.analyst_events, history.analyst_coverage, days, symbols)
    out |= insider_features(history.insider_trades, market_value, covered, days, symbols)
    out |= events_features(history.material_events, history.large_holders, covered, days, symbols)
    out |= holders_features(history.holders, shares, splits, days, symbols)
    out |= estimates_features(history.estimates, days, symbols)
    out |= catalysts_features(history.fda_events, days, symbols)
    return out
