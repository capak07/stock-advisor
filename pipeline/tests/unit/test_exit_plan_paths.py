import hashlib
import math
from datetime import date, timedelta

import numpy as np
import pytest

from advisor.portfolio.exit_plan import (
    BLOCK,
    LOOKBACK,
    PATHS,
    NoPlan,
    median_drift,
    paired_moves,
    seed_of,
    simulate,
    simulate_raw,
)

DAY = date(2026, 11, 20)


def _moves(n=252, sd=0.02, seed=1):
    return np.random.default_rng(seed).normal(0.0, sd, n)


def test_the_seed_is_stable_across_runs_and_differs_by_symbol_and_day():
    assert seed_of("AAPL", DAY) == seed_of("AAPL", DAY)
    assert len({seed_of("AAPL", DAY), seed_of("MSFT", DAY), seed_of("AAPL", date(2026, 11, 19))}) == 3
    assert seed_of("AAPL", DAY) == int.from_bytes(hashlib.sha256(b"AAPL|2026-11-20").digest()[:8], "big")


def test_the_same_seed_gives_the_same_paths():
    a, b = simulate(_moves(), 21, 7), simulate(_moves(), 21, 7)
    assert a.shape == (PATHS, 21) and np.array_equal(a, b)
    assert not np.array_equal(a, simulate(_moves(), 21, 8))


def test_without_a_forecast_the_median_path_is_flat():
    paths = simulate(_moves() + 0.004, 21, 7)  # a strong past drift must not carry over
    assert abs(np.median(paths[:, -1])) < 0.01


def test_with_a_forecast_the_ends_match_the_quantiles_and_the_benchmark_drift():
    rng = np.random.default_rng(3)
    bench = rng.normal(0.0004, 0.01, 252)
    pair = np.column_stack([bench + rng.normal(0, 0.02, 252), bench])
    paths = simulate(pair, 21, 7, forecast=(-0.08, 0.02, 0.15), drift=0.01)
    ends = paths[:, -1]
    # excess quantiles composed with the benchmark's median drift: 0.0198 + 0.0100 = 0.0298
    assert np.median(ends) == pytest.approx(math.log(1.02) + math.log(1.01), abs=0.01)
    assert np.quantile(ends, 0.9) - np.quantile(ends, 0.1) > math.log(1.15) - math.log(0.92)  # benchmark spread adds


def test_with_a_constant_benchmark_the_ends_match_the_forecast_median_and_width():
    rng = np.random.default_rng(3)
    bench = np.full(251, 0.0004)  # no benchmark spread: the ends are the excess plus the drift
    pair = np.column_stack([bench + rng.normal(0, 0.02, 251), bench])
    ends = simulate(pair, 21, 7, forecast=(-0.08, 0.02, 0.15), drift=0.01)[:, -1]
    assert np.median(ends) == pytest.approx(math.log(1.02) + math.log(1.01), abs=0.005)  # 0.02975
    width = np.quantile(ends, 0.9) - np.quantile(ends, 0.1)
    assert width == pytest.approx(math.log(1.15) - math.log(0.92), abs=0.01)  # 0.22314
    # q10 and q90 alone are not asserted: one scale and one shift cannot reproduce skew


def test_blocks_keep_consecutive_days_together():
    moves = np.arange(252, dtype=float)  # each value names its own row
    steps = np.diff(simulate_raw(moves, 21, 7), axis=1, prepend=0.0)
    inside = np.ones(21, bool); inside[::BLOCK] = False  # noqa: E702
    assert np.all(np.diff(steps, axis=1)[:, inside[1:]] == 1.0)


def test_block_starts_cover_the_whole_range_and_stay_inside_it():
    moves = np.arange(100, dtype=float)
    steps = np.diff(simulate_raw(moves, 21, 7), axis=1, prepend=0.0)
    starts = steps[:, ::BLOCK]
    assert starts.min() == 0 and starts.max() == 100 - BLOCK
    assert steps.max() <= 99


def test_a_pair_uses_the_same_blocks_for_both_columns():
    rows = np.arange(252, dtype=float)
    pair = np.column_stack([2 * rows, rows])  # the excess column is the benchmark column
    paths = simulate(pair, 21, 7, forecast=(-0.08, 0.02, 0.15), drift=0.01)
    excess = simulate(np.column_stack([rows, np.full(252, 0.0)]), 21, 7, forecast=(-0.08, 0.02, 0.15), drift=0.0)
    bench_raw = simulate_raw(rows - rows.mean(), 21, 7)
    # the benchmark part is the raw benchmark paths plus a straight-line shift
    bench_part = paths - excess
    shift = bench_part - bench_raw
    steps = np.diff(shift, axis=1)
    np.testing.assert_allclose(steps, np.full_like(steps, steps[0, 0]), atol=1e-9)


@pytest.mark.parametrize("forecast", [
    (-1.0, 0.0, 0.1),      # q10 <= -1
    (0.1, 0.0, 0.1),       # q90 <= q10
    (math.nan, 0.0, 0.1),  # not finite
    (0.0, 0.2, 0.1),       # q50 above q90
    (0.0, -0.1, 0.1),      # q50 below q10
])
def test_an_unusable_forecast_is_refused(forecast):
    pair = np.column_stack([_moves(), _moves(seed=2)])
    with pytest.raises(NoPlan, match="forecast is not usable"):
        simulate(pair, 21, 7, forecast=forecast, drift=0.0)


def test_a_flat_excess_has_no_width():
    bench = _moves()
    pair = np.column_stack([bench, bench])  # e.g. the benchmark itself: the excess is 0 every day
    with pytest.raises(NoPlan, match="forecast range has no width"):
        simulate(pair, 21, 7, forecast=(-0.08, 0.02, 0.15), drift=0.0)


def test_too_little_history_is_refused():
    with pytest.raises(NoPlan, match="too little price history"):
        simulate(_moves(n=58), 21, 7)  # 58 < MIN_CLOSES - 1 = 59
    assert simulate(_moves(n=59), 21, 7).shape == (PATHS, 21)


def test_too_little_paired_history_is_refused():
    pair = np.column_stack([_moves(n=58), _moves(n=58, seed=2)])
    with pytest.raises(NoPlan, match="too little price history"):
        simulate(pair, 21, 7, forecast=(-0.08, 0.02, 0.15), drift=0.0)


def test_no_plan_is_a_value_error():
    assert issubclass(NoPlan, ValueError)
    assert str(NoPlan("no price")) == "no price"


def test_median_drift_reads_every_overlapping_window():
    closes = [100 * 1.01 ** i for i in range(60)]  # 39 windows, each 1.01 ** 21 - 1
    assert median_drift(closes, 21) == pytest.approx(1.01 ** 21 - 1)


def test_median_drift_takes_the_median_window():
    closes = [100.0, 110.0, 99.0, 99.0]  # one-step returns: +10%, -10%, 0%
    assert median_drift(closes, 1) == pytest.approx(0.0)


def test_median_drift_needs_a_full_window():
    with pytest.raises(NoPlan, match="too little price history"):
        median_drift([100.0] * 21, 21)
    assert median_drift([100.0] * 22, 21) == 0.0


def _days(n, start=date(2025, 1, 1)):
    return [start + timedelta(days=i) for i in range(n)]


def test_paired_moves_drops_dates_only_one_side_has():
    d = _days(5)
    closes = {d[0]: 100.0, d[1]: 110.0, d[2]: 121.0, d[4]: 133.1}
    bench = {d[0]: 50.0, d[2]: 55.0, d[3]: 60.0, d[4]: 60.5}
    rows = paired_moves(closes, bench)
    # common closes: d0, d2, d4
    assert rows.shape == (2, 2)
    np.testing.assert_allclose(rows[0], [math.log(121 / 100), math.log(55 / 50)])
    np.testing.assert_allclose(rows[1], [math.log(133.1 / 121), math.log(60.5 / 55)])


def test_a_gap_never_pairs_returns_over_different_spans():
    d = _days(4)
    closes = {d[0]: 100.0, d[1]: 200.0, d[2]: 100.0, d[3]: 100.0}  # d1 has no benchmark close
    bench = {d[0]: 10.0, d[2]: 10.0, d[3]: 20.0}
    rows = paired_moves(closes, bench)
    # d0 -> d2 for both sides, then d2 -> d3 for both sides
    np.testing.assert_allclose(rows, [[0.0, 0.0], [0.0, math.log(2.0)]])


def test_paired_moves_reads_the_last_lookback_common_closes_oldest_first():
    d = _days(300)
    closes = {day: 100.0 * 1.001 ** i for i, day in enumerate(d)}
    bench = {day: 50.0 * 1.002 ** i * (1.01 if i % 2 else 1.0) for i, day in enumerate(d)}
    bench = dict(sorted(bench.items(), reverse=True))  # input order does not matter
    rows = paired_moves(closes, bench)
    assert rows.shape == (LOOKBACK - 1, 2) == (251, 2)
    asset = [closes[day] for day in d]
    bench_by_day = [bench[day] for day in d]
    assert rows[-1, 0] == pytest.approx(math.log(asset[-1] / asset[-2]))
    assert rows[-1, 1] == pytest.approx(math.log(bench_by_day[-1] / bench_by_day[-2]))
    assert rows[0, 0] == pytest.approx(math.log(asset[300 - LOOKBACK + 1] / asset[300 - LOOKBACK]))


def test_paired_moves_with_fewer_common_closes_reads_them_all():
    d = _days(10)
    closes = {day: 100.0 + i for i, day in enumerate(d)}
    rows = paired_moves(closes, dict(closes))
    assert rows.shape == (9, 2)
    assert paired_moves({}, {}).shape == (0, 2)
