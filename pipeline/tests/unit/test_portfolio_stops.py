import math
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from advisor.model.features import Wide, jump_days, price_features
from advisor.models import DailyBar
from advisor.portfolio.stops import atr_pct, trailing_stop


def make_bars(n: int) -> list[DailyBar]:
    rng = np.random.default_rng(7)
    close = 50 * np.exp(np.cumsum(rng.normal(0, 0.02, n)))
    return [
        DailyBar(
            symbol="X", day=date(2026, 1, 5) + timedelta(days=i), open=c * 0.995, high=c * 1.02,
            low=c * 0.98, close=c, volume=1_000_000.0, source="test",
        )
        for i, c in enumerate(close)
    ]


def test_atr_pct_matches_the_model_feature():
    bars = make_bars(30)
    days = pd.Index([b.day for b in bars], name="day")
    cols = {k: pd.DataFrame({"X": [getattr(b, k) for b in bars]}, index=days) for k in
            ("open", "high", "low", "close", "volume")}
    w = Wide(**cols)
    f = price_features(w, w.close * w.volume, jump_days(w.close))
    assert atr_pct(bars) == pytest.approx(f["atr_14_pct"].iloc[-1]["X"])
    assert not math.isnan(atr_pct(bars))


def test_atr_pct_is_nan_without_enough_bars():
    assert math.isnan(atr_pct(make_bars(14)))
    assert not math.isnan(atr_pct(make_bars(15)))


def test_the_stop_is_the_highest_close_less_two_and_a_half_atr():
    assert trailing_stop([10, 12, 11], 11, 0.10, None, None) == pytest.approx(9.25)


def test_the_stop_only_moves_up_and_never_below_the_original():
    assert trailing_stop([10, 12, 11], 11, 0.10, 9.8, None) == 9.8
    assert trailing_stop([10, 12, 11], 11, 0.10, None, 9.5) == 9.5


def test_a_position_with_no_close_since_purchase_uses_the_last_close():
    assert trailing_stop([], 20, 0.05, None, None) == pytest.approx(20 - 2.5)


def test_no_atr_and_no_memory_gives_no_stop():
    assert trailing_stop([10, 12], 11, math.nan, None, None) is None
    assert trailing_stop([10, 12], 11, math.nan, 7.0, None) == 7.0
