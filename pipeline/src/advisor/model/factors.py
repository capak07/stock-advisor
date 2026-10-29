"""Point-in-time factor returns for one market.

A portfolio is formed from the characteristic on formation day d and held from the next session
through the next formation day inclusive. `mkt` is the benchmark's own daily return. Fewer than
30 ranked names leaves that holding period missing: a 9-name book is not a third of a universe.
"""

from collections.abc import Mapping

import numpy as np
import pandas as pd

from advisor.models import Market

# Same string as advisor.model.crypto.CRYPTO. Importing it here would cycle through dataset.
CRYPTO = "crypto"
MIN_NAMES = 30

FACTORS: dict[Market | str, tuple[str, ...]] = {
    Market.US: ("mkt", "size", "value", "prof", "mom"),
    Market.TSX: ("mkt", "mom"),
    CRYPTO: ("mkt", "size", "mom"),
}


def form_days(sample_days: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Every second sample day: portfolios reform every 20 sessions when rows are every 10th."""
    return pd.DatetimeIndex(sample_days[::2])


def factor_returns(
    close: pd.DataFrame,
    characteristics: Mapping[str, pd.DataFrame],
    universe: pd.DataFrame,
    benchmark: str,
    form_days: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Daily factor returns indexed by the close calendar, one column per factor.

    `characteristics` are day × symbol, and a higher value is the long side. `universe` is the
    same shape, True where a name may be ranked that day.
    """
    close = close.sort_index()
    ret = close / close.shift(1) - 1
    calendar = pd.DatetimeIndex(close.index)
    out = pd.DataFrame({"mkt": ret[benchmark].to_numpy()}, index=calendar)
    formed = [pd.Timestamp(day) for day in form_days]
    positions = {day: i for i, day in enumerate(calendar)}
    for name, char in characteristics.items():
        column = pd.Series(np.nan, index=calendar, dtype=float)
        char = char.reindex(index=calendar)
        held = universe.reindex(index=calendar).fillna(False).astype(bool)
        for i, day in enumerate(formed):
            if day not in positions:
                continue
            values = char.loc[day].where(held.loc[day]).drop(labels=[benchmark], errors="ignore").dropna()
            if len(values) < MIN_NAMES:
                continue
            third = len(values) // 3
            ordered = values.sort_values(ascending=False, kind="mergesort")
            long = ordered.index[:third]
            short = ordered.index[-third:]
            start = positions[day] + 1
            if i + 1 < len(formed) and formed[i + 1] in positions:
                end = positions[formed[i + 1]] + 1
            elif i + 1 < len(formed):
                end = int(calendar.searchsorted(formed[i + 1], side="right"))
            else:
                end = len(calendar)
            if start >= end:
                continue
            window = calendar[start:end]
            long_ret = ret.loc[window, long].mean(axis=1, skipna=True)
            short_ret = ret.loc[window, short].mean(axis=1, skipna=True)
            column.loc[window] = long_ret.to_numpy() - short_ret.to_numpy()
        out[name] = column
    return out
