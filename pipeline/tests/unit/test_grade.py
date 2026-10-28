from dataclasses import replace
from datetime import date

import pytest

from advisor.grade import exit_early, grade
from advisor.models import PredictionRow
from advisor.policy import DEFAULT_POLICY
from advisor.store.repo import OpenPick


def _pick(id: int, horizon_days: int = 63, symbol: str = "AAA") -> OpenPick:
    return OpenPick(
        id=id, symbol=symbol, market="TSX", horizon_days=horizon_days, exit_by=date(2027, 1, 13),
        entry_ref_price=10.0, stop=9.0, feature_day=date(2026, 10, 13), bench_ref_price=20.0, run_kind="pre_open",
    )


def _row(symbol: str, h: int, p: float) -> PredictionRow:
    return PredictionRow(symbol, h, -0.05, 0.01, 0.07, p, "XIU.TO", "v1")


def test_exit_early_flags_a_pick_whose_p_fell_to_0_42():
    picks = [_pick(1, symbol="AAA"), _pick(2, symbol="BBB"), _pick(3, symbol="CCC"), _pick(4, 21, "DDD")]
    rows = {
        "AAA": [_row("AAA", 63, 0.42)],
        "BBB": [_row("BBB", 63, 0.43)],
        # CCC has no row this run; DDD has rows, but not at its own horizon (21)
        "DDD": [_row("DDD", 63, 0.10)],
    }
    assert exit_early(picks, rows) == [1]


def test_a_higher_sell_line_flags_a_pick_the_default_keeps():
    rows = {"AAA": [_row("AAA", 63, 0.45)]}
    assert exit_early([_pick(1)], rows) == []
    assert exit_early([_pick(1)], rows, {"TSX": replace(DEFAULT_POLICY, p_sell=0.46)}) == [1]


def test_exit_early_reads_the_row_at_the_picks_own_horizon():
    rows = {"AAA": [_row("AAA", 21, 0.10), _row("AAA", 63, 0.60)]}
    assert exit_early([_pick(1, 63)], rows) == []
    assert exit_early([_pick(2, 21)], rows) == [2]


FEATURE_DAY = date(2026, 10, 1)


def _grade(closes, bench_closes, *, stop=9.5, exit_by=date(2026, 10, 9), us=False, fee_pct=1.5, exit_now=None):
    return grade(10.0, stop, FEATURE_DAY, exit_by, closes, 20.0, bench_closes, fee_pct, us, exit_now)


BENCH = {date(2026, 10, d): 20.0 + d / 10 for d in (1, 2, 5, 6, 7, 8, 9, 13)}


def test_a_hit_stop_exits_at_the_first_close_under_it():
    closes = {
        date(2026, 9, 30): 9.0,  # before the feature day: not part of the hold
        FEATURE_DAY: 10.0,
        date(2026, 10, 2): 9.8,
        date(2026, 10, 5): 9.4,
        date(2026, 10, 6): 9.0,
        date(2026, 10, 9): 11.0,
    }
    out = _grade(closes, BENCH)
    assert (out.exit_day, out.exit_price, out.exit_reason, out.hit_stop) == (date(2026, 10, 5), 9.4, "stop", True)
    assert out.ret == pytest.approx(-0.06)
    assert out.bench_ret == pytest.approx(20.5 / 20 - 1)
    assert out.excess == pytest.approx(-0.06 - (20.5 / 20 - 1))
    assert out.beat is False
    # a close equal to the stop hits it too
    assert _grade(closes, BENCH, stop=9.4).exit_day == date(2026, 10, 5)


def test_without_a_stop_hit_the_exit_is_the_close_on_exit_by():
    closes = {date(2026, 10, 2): 10.5, date(2026, 10, 9): 11.0, date(2026, 10, 13): 8.0}  # 10-13 is after the hold
    out = _grade(closes, BENCH)
    assert (out.exit_day, out.exit_price, out.exit_reason, out.hit_stop) == (date(2026, 10, 9), 11.0, "exit_by", False)
    assert out.ret == pytest.approx(0.1)
    assert out.excess == pytest.approx(0.1 - (20.9 / 20 - 1))
    assert out.beat is True
    assert _grade(closes, BENCH, stop=None).exit_day == date(2026, 10, 9)
    # exit-by on a holiday (the TSX's Thanksgiving): the last close before it, once a later one exists
    holiday = {date(2026, 10, 2): 10.5, date(2026, 10, 9): 11.0, date(2026, 10, 13): 12.0}
    out = _grade(holiday, BENCH, exit_by=date(2026, 10, 12))
    assert (out.exit_day, out.exit_price, out.exit_reason) == (date(2026, 10, 9), 11.0, "exit_by")


def test_us_returns_are_also_shown_net_of_the_conversion_fee():
    closes = {date(2026, 10, 9): 11.0}
    us = _grade(closes, BENCH, us=True, fee_pct=1.5)
    assert us.ret == pytest.approx(0.1)
    assert us.ret_net_of_fx == pytest.approx(0.1 - 0.03)
    tsx = _grade(closes, BENCH, us=False, fee_pct=1.5)
    assert tsx.ret_net_of_fx == tsx.ret


def test_nothing_is_graded_until_the_exit_close_exists():
    # Review Focus 5: no close on or after exit-by yet, so the hold isn't over
    assert _grade({date(2026, 10, 2): 10.5, date(2026, 10, 8): 11.0}, BENCH) is None
    # exit-by on a holiday with no later close: 10-9's close may not be the last one before it
    assert _grade({date(2026, 10, 9): 11.0}, BENCH, exit_by=date(2026, 10, 12)) is None
    # the stock's exit close exists but the benchmark's doesn't
    no_bench = {d: c for d, c in BENCH.items() if d != date(2026, 10, 9)}
    assert _grade({date(2026, 10, 9): 11.0}, no_bench) is None
    assert _grade({date(2026, 10, 5): 9.0}, {date(2026, 10, 9): 21.0}, exit_by=date(2027, 1, 13)) is None
    # an early exit on a day without the stock's close
    assert _grade({date(2026, 10, 2): 10.5}, BENCH, exit_by=date(2027, 1, 13), exit_now=date(2026, 10, 7)) is None


def test_an_early_exit_grades_at_that_days_close():
    closes = {date(2026, 10, 2): 10.2, date(2026, 10, 7): 10.4}
    out = _grade(closes, BENCH, exit_by=date(2027, 1, 13), exit_now=date(2026, 10, 7))
    assert (out.exit_day, out.exit_price, out.exit_reason, out.hit_stop) == (
        date(2026, 10, 7), 10.4, "exit_early", False,
    )
    assert out.ret == pytest.approx(0.04)
    assert out.bench_ret == pytest.approx(20.7 / 20 - 1)
    # a stop hit before it still exits at the stop
    hit = _grade({**closes, date(2026, 10, 5): 9.0}, BENCH, exit_by=date(2027, 1, 13), exit_now=date(2026, 10, 7))
    assert (hit.exit_day, hit.exit_reason, hit.hit_stop) == (date(2026, 10, 5), "stop", True)
