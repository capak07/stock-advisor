"""Point-in-time factor returns for one market.

A portfolio is formed from the characteristic on formation day d and held from the next session
through the next formation day inclusive. `mkt` is the benchmark's own daily return. Fewer than
30 ranked names leaves that holding period missing: a 9-name book is not a third of a universe.
"""

import io
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from urllib.request import urlopen

import numpy as np
import pandas as pd

from advisor.models import Market

# Same string as advisor.model.crypto.CRYPTO. Importing it here would cycle through dataset.
CRYPTO = "crypto"
MIN_NAMES = 30
RIDGE_SHARE = 0.1  # λ = RIDGE_SHARE × trace(XᵀX) / k
BETA_WINDOW = 252
BETA_MIN_DAYS = 126

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


@dataclass(frozen=True)
class FactorFrames:
    names: tuple[str, ...]
    beta_columns: tuple[str, ...]
    forward: dict[int, pd.DataFrame]  # horizon → day × f_<name>_<h>
    daily: pd.DataFrame


def _ridge(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    k = x.shape[1]
    xtx = x.T @ x
    lam = RIDGE_SHARE * float(np.trace(xtx)) / k
    return np.linalg.solve(xtx + lam * np.eye(k), x.T @ y)


def rolling_betas(
    excess: pd.DataFrame,
    factors: pd.DataFrame,
    days: pd.DatetimeIndex,
    window: int = BETA_WINDOW,
    min_days: int = BETA_MIN_DAYS,
) -> dict[str, pd.DataFrame]:
    """Ridge β of each stock's daily excess return on the factor returns.

    For row day t the window is the `window` sessions ending the session before t. A stock with
    fewer than `min_days` complete sessions in that window gets NaN betas.
    """
    calendar = pd.DatetimeIndex(excess.index.union(factors.index)).sort_values()
    excess = excess.reindex(calendar)
    factors = factors.reindex(calendar)
    names = list(factors.columns)
    x_all = factors.to_numpy(dtype=float)
    y_all = excess.to_numpy(dtype=float)
    index = pd.DatetimeIndex(days)
    out = {name: pd.DataFrame(np.nan, index=index, columns=excess.columns, dtype=float) for name in names}
    if not names:
        return out
    for day in index:
        end = int(calendar.searchsorted(pd.Timestamp(day), side="left"))
        start = max(0, end - window)
        xw, yw = x_all[start:end], y_all[start:end]
        finite_x = np.isfinite(xw).all(axis=1)
        for j, _symbol in enumerate(excess.columns):
            ok = finite_x & np.isfinite(yw[:, j])
            if int(ok.sum()) < min_days:
                continue
            beta = np.ravel(_ridge(xw[ok], yw[ok, j]))
            for name, value in zip(names, beta, strict=True):
                out[name].at[day, excess.columns[j]] = value
    return out


def forward_factor_sums(factors: pd.DataFrame, horizons: Sequence[int]) -> dict[int, pd.DataFrame]:
    """F_k,h(t) = sum of factor k's daily returns over the h sessions after t."""
    out = {}
    for h in horizons:
        total = factors.shift(-1)
        for step in range(2, h + 1):
            total = total + factors.shift(-step)
        out[int(h)] = total
    return out


def stock_characteristics(
    market: Market, features: Mapping[str, pd.DataFrame], universe: pd.DataFrame
) -> dict[str, pd.DataFrame]:
    """The non-market characteristics. A higher value is the long third. US value is the mean of
    the cross-sectional percentile ranks of the two yields, using whichever of them is present."""
    mom = features["mom_12_1"]
    if market is Market.TSX:
        return {"mom": mom}
    held = universe.reindex(index=features["earnings_yield"].index, columns=features["earnings_yield"].columns)
    earnings = features["earnings_yield"].where(held).rank(axis=1, pct=True)
    sales = features["sales_yield"].where(held).rank(axis=1, pct=True)
    pair = np.stack([earnings.to_numpy(dtype=float), sales.to_numpy(dtype=float)])
    with np.errstate(invalid="ignore"):
        value = np.nanmean(pair, axis=0)
    return {
        "size": -features["log_mcap"],
        "value": pd.DataFrame(value, index=earnings.index, columns=earnings.columns),
        "prof": features["op_margin"],
        "mom": mom,
    }


def make_factors(
    close: pd.DataFrame,
    characteristics: Mapping[str, pd.DataFrame],
    universe: pd.DataFrame,
    benchmark: str,
    sample_days: pd.DatetimeIndex,
    horizons: Sequence[int],
    names: Sequence[str],
) -> tuple[FactorFrames, dict[str, pd.DataFrame]]:
    """Daily factor returns, rolling betas on the sample days, and forward factor sums."""
    close = close.sort_index()
    daily = factor_returns(close, characteristics, universe, benchmark, form_days(sample_days))
    daily = daily.reindex(columns=list(names))
    ret = close / close.shift(1) - 1
    excess = ret.sub(ret[benchmark], axis=0)
    betas = rolling_betas(excess, daily, pd.DatetimeIndex(sample_days))
    forward = {
        h: frame.rename(columns={name: f"f_{name}_{h}" for name in names})
        for h, frame in forward_factor_sums(daily, horizons).items()
    }
    beta_columns = tuple(f"beta_{name}" for name in names)
    return FactorFrames(tuple(names), beta_columns, forward, daily), betas


def join_factor_columns(
    rows: pd.DataFrame, betas: Mapping[str, pd.DataFrame], frames: FactorFrames
) -> pd.DataFrame:
    """Append beta_<name> and f_<name>_<h> without reordering the rows."""
    out = rows.copy()
    index = pd.MultiIndex.from_arrays([pd.DatetimeIndex(out["day"]), out["symbol"]])
    for name, frame in betas.items():
        stacked = frame.stack(future_stack=True)
        stacked.index.names = ["day", "symbol"]
        out[f"beta_{name}"] = stacked.reindex(index).to_numpy()
    for frame in frames.forward.values():
        aligned = frame.reindex(pd.DatetimeIndex(out["day"]))
        for col in frame.columns:
            out[col] = aligned[col].to_numpy()
    return out


def alpha_target(rows: pd.DataFrame, h: int, names: Sequence[str]) -> pd.Series:
    """y_h minus the factor part. A row with any NaN beta keeps y_h."""
    y = rows[f"y_{h}"]
    betas = rows[[f"beta_{name}" for name in names]]
    shift = sum(rows[f"beta_{name}"] * rows[f"f_{name}_{h}"] for name in names)
    return y.where(betas.isna().any(axis=1), y - shift)


def fallback_count(rows: pd.DataFrame, names: Sequence[str]) -> int:
    """Rows whose target falls back to y_h because a beta is missing."""
    betas = rows[[f"beta_{name}" for name in names]]
    return int(betas.isna().any(axis=1).sum())


_FRENCH_5 = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_5_Factors_2x3_daily_CSV.zip"
_FRENCH_MOM = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Momentum_Factor_daily_CSV.zip"
_FRENCH_PAIRS = (("size", "SMB"), ("value", "HML"), ("prof", "RMW"), ("mom", "Mom"))


def _french_table(blob: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        text = archive.read(archive.namelist()[0]).decode("latin1")
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if "Mkt-RF" in line or line.strip().endswith(",Mom"))
    header = [part.strip() for part in lines[start].split(",")]
    rows = []
    for line in lines[start + 1:]:
        if not line.strip() or not line[0].isdigit():
            break
        rows.append([part.strip() for part in line.split(",")])
    frame = pd.DataFrame(rows, columns=header)
    frame.index = pd.to_datetime(frame.iloc[:, 0], format="%Y%m%d")
    for col in frame.columns[1:]:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    return frame


def french_cross_check(daily: pd.DataFrame) -> str:
    """Correlation of our US factors with Kenneth French's. Never used in training.

    Any failure, including a missing overlap, reads `cross-check unavailable`.
    """
    try:
        with urlopen(_FRENCH_5, timeout=15) as response:  # noqa: S310  keyless published CSV
            five = _french_table(response.read())
        with urlopen(_FRENCH_MOM, timeout=15) as response:  # noqa: S310
            mom = _french_table(response.read())
        french = five.join(mom[["Mom"]], how="inner")
        parts = []
        for ours, theirs in _FRENCH_PAIRS:
            joined = daily[ours].to_frame("ours").join(french[theirs].rename("theirs"), how="inner").dropna()
            corr = float(joined["ours"].corr(joined["theirs"])) if len(joined) > 2 else float("nan")
            if corr != corr:
                raise ValueError("no overlap")
            parts.append(f"{ours} vs {theirs} {corr:.2f}")
        return ", ".join(parts)
    except Exception:
        return "cross-check unavailable"
