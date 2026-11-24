from dataclasses import replace

import pytest

from advisor.runners.rule import STARTING, Rule, ignitions, series_of, stats_at
from runner_data import AKAN, quiet, then


def test_akans_ignition_day_signals():
    s = series_of(then(quiet(price=0.672), **AKAN))
    got = ignitions(s, STARTING)
    assert got.signal.tolist()[-1] is True and got.signal.sum() == 1
    stats = stats_at(s, len(s.days) - 1, STARTING)
    assert stats["change_pct"] == pytest.approx(102.38, abs=0.01)
    assert stats["volume_x"] == pytest.approx(892.11, abs=0.01)
    assert stats["close_pos"] == pytest.approx(0.651, abs=0.001)
    assert stats["dollar_volume"] == pytest.approx(121_326_960)


@pytest.mark.parametrize("change", [
    {"volume": 900_000.0},                 # 9x: under 10x
    {"close": 0.80, "high": 0.80},         # +19%: under 20%
    {"close": 1.10},                       # closes at 38% of the range: under the top half
    {"close": 5.20, "high": 6.00},         # above $5
    {"volume": 1_200_000.0},               # 12x but only $1.6M traded
])
def test_each_threshold_is_needed(change):
    s = series_of(then(quiet(price=0.672), **(AKAN | change)))
    assert not ignitions(s, STARTING).signal.any()


def test_a_stock_under_50_cents_does_not_signal():
    s = series_of(then(quiet(price=0.20), open=0.21, high=0.50, low=0.21, close=0.45, volume=89_211_000))
    assert not ignitions(s, STARTING).signal.any()


def test_only_the_first_ignition_in_20_sessions_signals():
    bars = then(quiet(price=0.672), **AKAN)
    bars = then(bars, open=1.92, high=2.38, low=1.70, close=2.21, volume=99_663_300.0)  # the real next day: ignites again
    assert ignitions(series_of(bars), STARTING).signal.tolist()[-2:] == [True, False]


def test_49_sessions_of_history_is_too_few():
    assert not ignitions(series_of(then(quiet(n=49, price=0.672), **AKAN)), STARTING).signal.any()


def test_a_window_without_volume_gives_no_signal_and_no_error():   # Review Focus 4
    s = series_of(then(quiet(price=0.672, volume=0.0), **AKAN))
    assert not ignitions(s, STARTING).signal.any()


def test_an_unrecorded_reverse_split_in_the_window_is_suspect_not_a_signal():
    bars = quiet(n=40, price=0.30, volume=1_000_000.0)
    bars = then(bars, open=3.00, high=3.10, low=2.90, close=3.00, volume=90_000.0)   # 10x overnight on thin volume
    for _ in range(25):
        bars = then(bars, open=3.00, high=3.05, low=2.95, close=3.00, volume=100_000.0)
    bars = then(bars, open=3.05, high=4.40, low=3.00, close=4.20, volume=20_000_000.0)
    got = ignitions(series_of(bars), STARTING)
    assert not got.signal.any() and got.split_suspect.tolist()[-1] is True


def test_a_real_spike_on_huge_volume_is_not_a_split():
    bars = then(quiet(price=0.672), **AKAN)                      # doubles on 892x volume
    for _ in range(25):
        bars = then(bars, open=1.36, high=1.40, low=1.30, close=1.36, volume=3_000_000.0)
    bars = then(bars, open=1.40, high=2.90, low=1.38, close=2.80, volume=400_000_000.0)
    got = ignitions(series_of(bars), STARTING)
    assert got.signal.tolist()[-1] is True and not got.split_suspect.any()


def test_settings_round_trip_and_tolerate_old_rows():
    assert Rule.from_settings(STARTING.settings()) == STARTING
    assert Rule.from_settings({"volume_x": 20.0, "gone": 1}) == replace(STARTING, volume_x=20.0)
