"""Point-in-time GARCH(1,1) volatility forecasts (spec §4).

Fits use returns before a cut-off; a day's variance is filtered over a fixed
`FILTER_WINDOW` of returns ending that day, started at the fit's `var0`, so
training and live match. A fit at α + β = 1 is kept; the h-step sum is built
step by step so it stays valid at the bound.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd
from arch import arch_model

GARCH_MIN_RETURNS = 500
FIT_WINDOW = 2520
FILTER_WINDOW = 250
# Percent-unit starting values for arch: mu, omega, alpha, beta, nu.
STARTING_VALUES = (0.05, 0.05, 0.08, 0.90, 8.0)


@dataclass(frozen=True)
class GarchParams:
    """GARCH(1,1)-t parameters in decimal return units, plus the fit sample's var0."""

    mu: float
    omega: float
    alpha: float
    beta: float
    nu: float
    var0: float

    def to_json(self) -> list[float]:
        return [self.mu, self.omega, self.alpha, self.beta, self.nu, self.var0]

    @classmethod
    def from_json(cls, v: Sequence[float]) -> "GarchParams":
        mu, omega, alpha, beta, nu, var0 = v
        return cls(
            float(mu), float(omega), float(alpha), float(beta), float(nu), float(var0)
        )


def fit_params(returns: pd.Series) -> GarchParams | None:
    """Fit GARCH(1,1)-t on the last `FIT_WINDOW` finite returns, or None if unfit."""
    clean = returns.dropna()
    if len(clean) > FIT_WINDOW:
        clean = clean.iloc[-FIT_WINDOW:]
    if len(clean) < GARCH_MIN_RETURNS:
        return None
    values = clean.to_numpy(dtype=float)
    if np.allclose(values, values[0]):
        return None
    try:
        result = arch_model(
            100.0 * values,
            mean="Constant",
            vol="GARCH",
            p=1,
            q=1,
            dist="t",
            rescale=False,
        ).fit(disp="off", show_warning=False, starting_values=np.array(STARTING_VALUES))
    except Exception:
        return None
    if getattr(result, "convergence_flag", 1) != 0:
        return None
    params = result.params
    try:
        mu_pct = float(params["mu"])
        omega_pct = float(params["omega"])
        alpha = float(params["alpha[1]"])
        beta = float(params["beta[1]"])
        nu = float(params["nu"])
    except (KeyError, TypeError, ValueError):
        return None
    if not all(np.isfinite(x) for x in (mu_pct, omega_pct, alpha, beta, nu)):
        return None
    if omega_pct <= 0 or alpha < 0 or beta < 0:
        return None
    var0 = float(np.var(values, ddof=0))
    return GarchParams(mu_pct / 100.0, omega_pct / 10_000.0, alpha, beta, nu, var0)


def fit_all(
    returns: pd.DataFrame, before: pd.Timestamp, symbols: Iterable[str]
) -> dict[str, GarchParams | None]:
    """Fit each symbol on returns strictly before `before`, in sorted symbol order."""
    prior = returns.loc[returns.index < before]
    out: dict[str, GarchParams | None] = {}
    for symbol in sorted(symbols):
        if symbol not in prior.columns:
            out[symbol] = None
        else:
            out[symbol] = fit_params(prior[symbol])
    return out


def garch_vol(
    returns: pd.Series, params: GarchParams | None, horizons: Sequence[int]
) -> pd.DataFrame:
    """Per-day `garch_vol_h` from a fixed 250-return filter ending that day.

    The filter starts at `var0`. E[σ²ₜ₊₁] is the filtered value; later steps are
    ω + (α + β)·previous, summed for h terms, then square-rooted.
    """
    cols = [f"garch_vol_{h}" for h in horizons]
    empty = pd.DataFrame(np.nan, index=returns.index, columns=cols)
    if params is None or len(returns) == 0:
        return empty

    r = returns.to_numpy(dtype=float)
    n = len(r)
    w = FILTER_WINDOW
    var0 = float(params.var0)
    mu, omega, alpha, beta = params.mu, params.omega, params.alpha, params.beta
    phi = alpha + beta
    eps2 = (r - mu) ** 2

    one_step = np.full(n, np.nan)
    if n >= w:
        kernel = beta ** np.arange(w, dtype=float)
        weighted = np.convolve(np.nan_to_num(eps2, nan=0.0), kernel, mode="full")
        beta_w = beta**w
        omega_sum = omega * (1.0 - beta_w) / (1.0 - beta) if beta != 1.0 else omega * w
        base = beta_w * var0 + omega_sum
        for t in range(w - 1, n):
            window = r[t - w + 1: t + 1]
            if not np.isfinite(window).all():
                continue
            one_step[t] = base + alpha * weighted[t]

    data = {}
    finite = np.isfinite(one_step)
    for h in horizons:
        total = np.full(n, np.nan)
        if finite.any():
            # Sum h forecast steps starting at the filtered one-step variance.
            step = one_step.copy()
            acc = np.zeros(n)
            for _ in range(h):
                acc = acc + step
                step = omega + phi * step
            total = np.where(finite, acc, np.nan)
        data[f"garch_vol_{h}"] = np.sqrt(total)
    return pd.DataFrame(data, index=returns.index)


def live_garch_vol(
    closes: pd.DataFrame, params: Mapping[str, GarchParams | None], horizons: Sequence[int]
) -> pd.DataFrame:
    """Symbol × `garch_vol_h` on the last day of `closes` (a market-calendar × symbol frame).

    The returns are the training data's (`dataset.log_returns`), so with the same parameters a live
    value equals the training value on the same day. A symbol without parameters gets NaN.
    """
    returns = np.log(closes / closes.shift(1))
    rows = {
        symbol: garch_vol(returns[symbol], params.get(symbol), horizons).iloc[-1] if len(closes) else None
        for symbol in closes.columns
    }
    cols = [f"garch_vol_{h}" for h in horizons]
    return pd.DataFrame({s: (r if r is not None else pd.Series(np.nan, index=cols)) for s, r in rows.items()}).T[cols]
