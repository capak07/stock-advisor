from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from advisor.daytrade.bars import Bar, YahooClient
from advisor.daytrade.rule import (
    OpeningRange,
    find_trigger,
    opening_range,
    plan_for,
    session_for,
)
from advisor.models import ET, Market

FIX = Path(__file__).parent.parent / "fixtures" / "daytrade"
DAY = date(2026, 10, 19)


def _bars():
    text = (FIX / "TSLA-2026-10-19-5m.json").read_text(encoding="utf-8")
    return YahooClient(get=lambda url: text, sleep=lambda s: None).chart("TSLA", "1d", "5m")


def _setup():
    s = session_for(DAY, Market.US)
    assert s is not None
    bars = _bars()
    return s, bars, opening_range(bars, s)


def test_range():
    _, _, rng = _setup()
    assert rng is not None
    assert round(rng.high, 2) == 362.18
    assert round(rng.low, 2) == 354.47


def test_trigger_without_volume_filter():
    s, bars, rng = _setup()
    t = find_trigger(bars, s, rng, min_volume_x=0)
    assert t.bar.start == datetime(2026, 10, 19, 10, 10, tzinfo=ET)
    assert t.at == datetime(2026, 10, 19, 10, 15, tzinfo=ET)
    assert t.entry == 364.18


def test_trigger_with_volume_filter():
    s, bars, rng = _setup()
    t = find_trigger(bars, s, rng, min_volume_x=1)
    assert t.at == datetime(2026, 10, 19, 10, 35, tzinfo=ET)
    assert t.entry == 365.75
    assert t.volume_x >= 1


def test_plan():
    s, bars, rng = _setup()
    p = plan_for(find_trigger(bars, s, rng, min_volume_x=0), rng, s)
    assert (p.entry, p.stop, p.target) == (364.18, 358.32, 375.90)
    assert p.risk == pytest.approx(5.86)
    assert p.flat_by == datetime(2026, 10, 19, 15, 55, tzinfo=ET)


def test_stop_floors_exactly():
    s = session_for(DAY, Market.US)
    t0 = s.open + timedelta(minutes=15)
    bar = Bar(t0, 360, 366, 360, 365, 100)
    from advisor.daytrade.rule import Trigger

    rng = OpeningRange(high=362.0, low=354.65, avg_volume=50)  # mid 358.325
    p = plan_for(Trigger(bar, t0 + timedelta(minutes=5), 365.0, 2.0), rng, s)
    assert p.stop == 358.32


def test_plan_none_when_stop_not_below_entry():
    s = session_for(DAY, Market.US)
    t0 = s.open + timedelta(minutes=15)
    from advisor.daytrade.rule import Trigger

    rng = OpeningRange(high=100.0, low=100.0, avg_volume=1)
    assert plan_for(Trigger(Bar(t0, 1, 1, 1, 100.005, 1), t0, 100.0, 1.0), rng, s) is None


def test_close_at_range_high_is_not_trigger():
    s, bars, rng = _setup()
    flat = [b for b in bars if b.start.time() < datetime(2026, 1, 1, 9, 45).time()]
    t0 = s.open + timedelta(minutes=15)
    flat.append(Bar(t0, 360, 365, 360, rng.high, 10_000_000))
    assert find_trigger(flat, s, rng, min_volume_x=0) is None


def test_missing_range_bar():
    s, bars, _ = _setup()
    kept = [b for b in bars if b.start != datetime(2026, 10, 19, 9, 35, tzinfo=ET)]
    assert opening_range(kept, s) is None


def test_early_close_session():
    s = session_for(date(2026, 11, 27), Market.US)
    assert s.no_entries_after == datetime(2026, 11, 27, 12, 30, tzinfo=ET)
    assert s.flat_by == datetime(2026, 11, 27, 12, 55, tzinfo=ET)


def test_tsx_only_holiday():
    d = date(2026, 8, 3)
    assert session_for(d, Market.US) is not None
    assert session_for(d, Market.TSX) is None
