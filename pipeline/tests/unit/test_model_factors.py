"""Point-in-time factor portfolios: top third minus bottom third, known before they earn."""

import numpy as np
import pandas as pd
import pytest

from advisor.model.dataset import load_market
from advisor.model.factors import (
    FACTORS,
    RIDGE_SHARE,
    alpha_target,
    factor_returns,
    fallback_count,
    form_days,
    forward_factor_sums,
    rolling_betas,
)
from advisor.models import Market
from model_data import write_market


def _calendar():
    return pd.bdate_range("2020-01-06", periods=6)


def _book():
    """30 names. Formation on day 1 holds through day 3; formation on day 3 holds after that.

    Day 2 is the first holding session: longs (s00–s09) return +0.10, shorts (s20–s29) return −0.20.
    Day 3 is the next formation day and still the first portfolio: longs +0.50, shorts −0.50.
    """
    days = _calendar()
    names = [f"s{i:02d}" for i in range(30)]
    close = pd.DataFrame(100.0, index=days, columns=[*names, "SPY"])
    long, short = names[:10], names[-10:]
    close.loc[days[2], long] = 110.0
    close.loc[days[2], short] = 80.0
    close.loc[days[2], "SPY"] = 110.0
    close.loc[days[3], long] = 165.0  # 110 * 1.5
    close.loc[days[3], short] = 40.0  # 80 * 0.5
    close.loc[days[4], long] = 82.5  # 165 * 0.5
    close.loc[days[4], short] = 80.0  # 40 * 2
    char = pd.DataFrame(np.nan, index=days, columns=names)
    char.loc[days[1]] = np.arange(30, 0, -1)  # s00 highest
    char.loc[days[3]] = np.arange(1, 31)  # s29 highest: the opposite book
    universe = pd.DataFrame(True, index=days, columns=names)
    formed = pd.DatetimeIndex([days[1], days[3]])
    return days, names, close, {"size": char}, universe, formed


def test_top_minus_bottom_matches_a_hand_value():
    days, _names, close, chars, universe, formed = _book()
    out = factor_returns(close, chars, universe, "SPY", formed)
    # 0.10 − (−0.20) = 0.30 the session after formation; the formation day itself is still the prior book
    assert out.loc[days[2], "size"] == pytest.approx(0.30)
    assert out.loc[days[3], "size"] == pytest.approx(1.0)  # 0.50 − (−0.50), held through the next formation day
    assert out.loc[days[4], "size"] == pytest.approx(1.5)  # the reversed book: 1.0 − (−0.5)
    assert out.loc[days[2], "mkt"] == pytest.approx(0.10)
    assert out.loc[days[:2], "size"].isna().all()


def test_factor_returns_are_point_in_time():
    days, names, close, chars, universe, formed = _book()
    base = factor_returns(close, chars, universe, "SPY", formed)
    t = days[2]
    later_close = close.copy()
    later_close.loc[days[days > t], names[:10]] = 1000.0
    later_char = {"size": chars["size"].copy()}
    later_char["size"].loc[days[days > t]] = 0.0
    same = factor_returns(later_close, later_char, universe, "SPY", formed)
    pd.testing.assert_frame_equal(base.loc[days <= t], same.loc[days <= t])

    # a characteristic dated on formation day d changes nothing before the next session
    d = days[3]
    flipped = {"size": chars["size"].copy()}
    flipped["size"].loc[d] = np.arange(30, 0, -1)
    alt = factor_returns(close, flipped, universe, "SPY", formed)
    before = days[days < d + pd.tseries.offsets.BDay()]
    pd.testing.assert_series_equal(base.loc[before, "size"], alt.loc[before, "size"])
    assert base.loc[days[4], "size"] != alt.loc[days[4], "size"]


def test_fewer_than_30_names_is_nan():
    days = _calendar()
    names = [f"s{i:02d}" for i in range(9)]
    close = pd.DataFrame(100.0, index=days, columns=names)
    close.loc[days[2], names[:3]] = 110.0
    close.loc[days[2], names[-3:]] = 80.0
    char = pd.DataFrame(np.nan, index=days, columns=names)
    char.loc[days[1]] = np.arange(9, 0, -1)
    universe = pd.DataFrame(True, index=days, columns=names)
    out = factor_returns(close, {"mom": char}, universe, names[0], pd.DatetimeIndex([days[1]]))
    assert out["mom"].isna().all()


def test_tsx_factors_are_market_and_momentum_only():
    assert FACTORS[Market.TSX] == ("mkt", "mom")


def test_portfolios_reform_every_second_sample_day():
    days = _calendar()
    assert form_days(days).equals(days[::2])


def _factor_path():
    """300 sessions of two orthogonal factors and a return of 0.8·f1 − 0.5·f2, then one more day."""
    rng = np.random.default_rng(0)
    n = 300
    f1 = rng.normal(size=n)
    f2 = rng.normal(size=n)
    f2 = f2 - f1 * (f1 @ f2) / (f1 @ f1)
    f2 *= np.linalg.norm(f1) / np.linalg.norm(f2)
    y = 0.8 * f1 - 0.5 * f2
    days = pd.bdate_range("2016-01-04", periods=n + 1)
    factors = pd.DataFrame(0.0, index=days, columns=["f1", "f2"])
    excess = pd.DataFrame(0.0, index=days, columns=["AAA"])
    factors.iloc[:n, 0] = f1
    factors.iloc[:n, 1] = f2
    excess.iloc[:n, 0] = y
    return days, factors, excess


def test_ridge_recovers_known_betas():
    days, factors, excess = _factor_path()
    got = rolling_betas(excess, factors, pd.DatetimeIndex([days[-1]]), window=300, min_days=126)
    beta = np.array([got["f1"].iloc[0, 0], got["f2"].iloc[0, 0]])
    # λ = RIDGE_SHARE × trace(XᵀX) / k shrinks an orthogonal loading by 1/(1+RIDGE_SHARE).
    # 0.8/1.1 is 0.073 from 0.8, so "within 0.05 of the raw betas" cannot hold for this λ.
    shrunk = np.array([0.8, -0.5]) / (1 + RIDGE_SHARE)
    assert beta == pytest.approx(shrunk, abs=0.05)


def test_rolling_betas_are_point_in_time():
    days, factors, excess = _factor_path()
    t = days[200]
    when = pd.DatetimeIndex([t])
    base = rolling_betas(excess, factors, when, window=252, min_days=126)
    changed_excess, changed_factors = excess.copy(), factors.copy()
    changed_excess.loc[days >= t] = 5.0
    changed_factors.loc[days >= t] = 5.0
    alt = rolling_betas(changed_excess, changed_factors, when, window=252, min_days=126)
    for name in ("f1", "f2"):
        pd.testing.assert_frame_equal(base[name], alt[name])
        assert np.isfinite(base[name].iloc[0, 0])


def test_forward_factor_sum_is_the_next_h_sessions():
    days = _calendar()
    factors = pd.DataFrame({"mkt": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]}, index=days)
    assert forward_factor_sums(factors, [2])[2].loc[days[0], "mkt"] == pytest.approx(0.5)


def test_a_missing_beta_falls_back_to_the_raw_target():
    rows = pd.DataFrame({
        "y_5": [0.10, 0.20],
        "beta_mkt": [1.0, np.nan],
        "beta_mom": [0.5, 0.25],
        "f_mkt_5": [0.01, 0.02],
        "f_mom_5": [0.04, 0.08],
    })
    alpha = alpha_target(rows, 5, ("mkt", "mom"))
    assert alpha.iloc[0] == pytest.approx(0.10 - (1.0 * 0.01 + 0.5 * 0.04))
    assert alpha.iloc[1] == pytest.approx(0.20)
    assert fallback_count(rows, ("mkt", "mom")) == 1


def test_load_market_with_factors_adds_columns_and_keeps_the_old_ones(tmp_path):
    write_market(tmp_path, Market.TSX, stocks=40, days=800)
    plain = load_market(tmp_path, Market.TSX)
    factored = load_market(tmp_path, Market.TSX, with_factors=True)
    pd.testing.assert_frame_equal(plain.rows, factored.rows[list(plain.rows.columns)])
    assert plain.factors is None
    assert factored.factors is not None and factored.factors.names == ("mkt", "mom")
    for col in ("beta_mkt", "beta_mom", "f_mkt_5", "f_mom_5"):
        assert col in factored.rows.columns
