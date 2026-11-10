from datetime import datetime, timedelta

from advisor.daytrade.bars import Bar
from advisor.daytrade.rule import Plan, Trigger
from advisor.daytrade.track import track
from advisor.models import ET

DAY = datetime(2026, 10, 19, tzinfo=ET)
FLAT = DAY.replace(hour=15, minute=55)
PLAN = Plan(entry=100.0, stop=98.0, target=104.0, risk=2.0, flat_by=FLAT)


def _bar(start: datetime, lo: float, hi: float, close: float) -> Bar:
    return Bar(start, close, hi, lo, close, 1000)


T0 = DAY.replace(hour=10, minute=15)
TRIG = Trigger(bar=_bar(T0, 99.5, 100.5, 100.0), at=T0 + timedelta(minutes=5), entry=100.0, volume_x=2.0)


def _at(i: int) -> datetime:
    return T0 + timedelta(minutes=5 * i)


def test_stop() -> None:
    bars = [_bar(_at(1), 99, 101, 100), _bar(_at(2), 97, 100, 98)]
    o = track(PLAN, TRIG, bars, _at(10))
    assert (o.status, o.exit_price, o.exit_at, o.gross_r) == ("stop", 98.0, _at(3), -1.0)


def test_target() -> None:
    o = track(PLAN, TRIG, [_bar(_at(1), 99, 104.5, 104)], _at(10))
    assert (o.status, o.exit_price, o.gross_r) == ("target", 104.0, 2.0)


def test_both_in_one_bar_is_stop() -> None:
    o = track(PLAN, TRIG, [_bar(_at(1), 97, 105, 100)], _at(10))
    assert o.status == "stop" and o.gross_r == -1.0


def test_trigger_bar_ignored() -> None:
    bars = [_bar(T0, 90, 110, 100), _bar(_at(1), 99, 101, 100.5)]
    assert track(PLAN, TRIG, bars, _at(10)).status == "open"


def test_flat_at_last_bar() -> None:
    last = FLAT - timedelta(minutes=5)
    bars = [_bar(_at(1), 99, 101, 100), _bar(last, 99, 101, 101.0)]
    o = track(PLAN, TRIG, bars, FLAT)
    assert (o.status, o.exit_price, o.exit_at, o.gross_r) == ("flat", 101.0, FLAT, 0.5)


def test_open_uses_last_close_and_entry_when_none() -> None:
    o = track(PLAN, TRIG, [_bar(_at(1), 99, 101, 100.5)], _at(3))
    assert (o.status, o.last_price, o.last_at, o.gross_r) == ("open", 100.5, _at(2), None)
    o = track(PLAN, TRIG, [], TRIG.at)
    assert (o.status, o.last_price) == ("open", 100.0)


def test_incomplete_bar_not_counted() -> None:
    o = track(PLAN, TRIG, [_bar(_at(1), 90, 101, 95)], _at(1) + timedelta(minutes=2))
    assert o.status == "open" and o.last_price == 100.0
