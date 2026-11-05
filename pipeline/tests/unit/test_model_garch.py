"""Plan 6d Task 1: point-in-time GARCH(1,1) fit and volatility forecast."""

import numpy as np
import pandas as pd
import pytest

from advisor.model import garch
from advisor.model.garch import GarchParams, fit_all, fit_params, garch_vol


def simulate(n, omega=0.02, alpha=0.08, beta=0.90, nu=6.0, mu=0.03, seed=1):
    """Decimal log returns from a known GARCH(1,1)-t process (params in percent units)."""
    rng = np.random.default_rng(seed)
    s2 = omega / (1 - alpha - beta)
    rows = []
    for _ in range(n):
        z = rng.standard_t(nu) * np.sqrt((nu - 2) / nu)
        r = mu + np.sqrt(s2) * z
        s2 = omega + alpha * (r - mu) ** 2 + beta * s2
        rows.append(r)
    return pd.Series(np.asarray(rows) / 100, index=pd.bdate_range("2010-01-04", periods=n))


def test_a_fit_recovers_the_parameters_it_was_simulated_with():
    p = fit_params(simulate(3000))
    assert p is not None
    assert p.alpha == pytest.approx(0.08, abs=0.04) and p.beta == pytest.approx(0.90, abs=0.05)
    assert p.alpha + p.beta < 1 and p.omega > 0
    assert p.var0 == pytest.approx(simulate(3000).iloc[-2520:].var(ddof=0))


def test_under_500_returns_gives_no_fit_and_never_calls_arch(monkeypatch):
    calls = []
    real = garch.arch_model
    monkeypatch.setattr(garch, "arch_model", lambda y, *a, **k: calls.append(len(y)) or real(y, *a, **k))
    r = simulate(700)
    assert fit_params(r.iloc[:499]) is None and calls == []
    fit_params(r.iloc[:500])
    assert calls == [500]
    nan_tail = pd.concat([r.iloc[:499], pd.Series(np.nan, index=r.index[499:])])
    assert fit_params(nan_tail) is None and calls == [500]  # NaNs don't count


def test_a_degenerate_series_gives_none_not_an_error():
    flat = pd.Series(0.0, index=pd.bdate_range("2010-01-04", periods=800))
    assert fit_params(flat) is None


def _fake_fit(monkeypatch, flag, alpha, beta):
    class Result:
        convergence_flag = flag
        params = pd.Series({"mu": 0.05, "omega": 0.05, "alpha[1]": alpha, "beta[1]": beta, "nu": 6.0})

    class Model:
        def fit(self, *a, **k):
            return Result()

    monkeypatch.setattr(garch, "arch_model", lambda *a, **k: Model())


def test_a_fit_at_the_alpha_plus_beta_bound_is_kept_and_forecasts(monkeypatch):
    _fake_fit(monkeypatch, 0, 0.10, 0.90)
    p = fit_params(simulate(800))
    assert p is not None and p.alpha + p.beta == pytest.approx(1.0)
    assert garch_vol(simulate(800), p, (5, 21)).iloc[300:].notna().all().all()


def test_a_fit_that_did_not_converge_is_refused(monkeypatch):
    _fake_fit(monkeypatch, 1, 0.08, 0.90)
    assert fit_params(simulate(800)) is None


def test_a_fit_is_deterministic():
    assert fit_params(simulate(1500)) == fit_params(simulate(1500))


def test_only_the_last_2520_returns_are_fitted():
    r = simulate(3000)
    changed = r.copy()
    changed.iloc[0] = 0.5  # older than the last 2,520
    assert fit_params(changed) == fit_params(r)


def test_fit_all_uses_only_returns_before_the_cut_off():
    r = pd.DataFrame({"A": simulate(1500, seed=2), "B": simulate(1500, seed=3)})
    cut = r.index[1200]
    later = r.copy()
    later.loc[later.index >= cut] = 0.3
    assert fit_all(later, cut, ["A", "B", "ZZZ"]) == fit_all(r, cut, ["A", "B", "ZZZ"])
    assert fit_all(r, cut, ["ZZZ"]) == {"ZZZ": None}


def test_garch_vol_equals_the_explicit_recursion():
    r = simulate(600)
    p = GarchParams(mu=0.0003, omega=2e-6, alpha=0.08, beta=0.90, nu=6.0, var0=1.5e-4)
    out = garch_vol(r, p, (1, 21))
    t = 400
    window = r.iloc[t - 249: t + 1].to_numpy()
    s2 = p.var0
    for x in window:
        s2 = p.omega + p.alpha * (x - p.mu) ** 2 + p.beta * s2
    total, step = 0.0, s2
    for _ in range(21):
        total += step
        step = p.omega + (p.alpha + p.beta) * step
    assert out["garch_vol_1"].iloc[t] == pytest.approx(np.sqrt(s2), rel=1e-9)
    assert out["garch_vol_21"].iloc[t] == pytest.approx(np.sqrt(total), rel=1e-9)
    assert out["garch_vol_1"].iloc[:249].isna().all() and out["garch_vol_1"].iloc[249:].notna().all()


def test_garch_vol_on_a_day_ignores_later_returns():
    r = simulate(600)
    p = GarchParams(mu=0.0, omega=2e-6, alpha=0.08, beta=0.90, nu=6.0, var0=1.5e-4)
    later = r.copy()
    later.iloc[401:] = 0.4
    pd.testing.assert_frame_equal(garch_vol(later, p, (5,)).iloc[:401], garch_vol(r, p, (5,)).iloc[:401])


def test_a_missing_return_blanks_only_the_windows_that_hold_it():
    r = simulate(700)
    r.iloc[300] = np.nan
    out = garch_vol(r, GarchParams(0.0, 2e-6, 0.08, 0.90, 6.0, 1.5e-4), (5,))["garch_vol_5"]
    assert out.iloc[300:550].isna().all()
    assert pd.notna(out.iloc[299]) and out.iloc[550:].notna().all()


def test_no_parameters_give_nan():
    assert garch_vol(simulate(300), None, (5, 10)).isna().all().all()


def test_parameters_round_trip_through_json():
    p = GarchParams(0.0003, 2e-6, 0.08, 0.90, 6.0, 1.5e-4)
    assert GarchParams.from_json(p.to_json()) == p
