"""Point-in-time factor portfolios: top third minus bottom third, known before they earn."""

import numpy as np
import pandas as pd
import pytest

from advisor.model.factors import FACTORS, factor_returns, form_days
from advisor.models import Market


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
