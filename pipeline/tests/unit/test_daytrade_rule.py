from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from advisor.daytrade.bars import Bar, YahooClient
from advisor.daytrade.rule import (
    OpeningRange,
    Trigger,
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
    assert rng is not None
    t = find_trigger(bars, s, rng, min_volume_x=0)
    assert t is not None
    assert t.bar.start == datetime(2026, 10, 19, 10, 10, tzinfo=ET)
    assert t.at == datetime(2026, 10, 19, 10, 15, tzinfo=ET)
    assert t.entry == 364.18


def test_trigger_with_volume_filter():
    s, bars, rng = _setup()
    assert rng is not None
    t = find_trigger(bars, s, rng, min_volume_x=1)
    assert t is not None
    assert t.at == datetime(2026, 10, 19, 10, 35, tzinfo=ET)
    assert t.entry == 365.75
    assert t.volume_x >= 1


def test_plan():
    s, bars, rng = _setup()
    assert rng is not None
    t = find_trigger(bars, s, rng, min_volume_x=0)
    assert t is not None
    p = plan_for(t, rng, s)
    assert p is not None
    assert (p.entry, p.stop, p.target) == (364.18, 358.32, 375.90)
    assert p.risk == pytest.approx(5.86)
    assert p.flat_by == datetime(2026, 10, 19, 15, 55, tzinfo=ET)


def test_stop_floors_exactly():
    s = session_for(DAY, Market.US)
    assert s is not None
    t0 = s.open + timedelta(minutes=15)
    bar = Bar(t0, 360, 366, 360, 365, 100)
    rng = OpeningRange(high=362.0, low=354.65, avg_volume=50)  # mid 358.325
    p = plan_for(Trigger(bar, t0 + timedelta(minutes=5), 365.0, 2.0), rng, s)
    assert p is not None
    assert p.stop == 358.32


def test_plan_none_when_stop_not_below_entry():
    s = session_for(DAY, Market.US)
    assert s is not None
    t0 = s.open + timedelta(minutes=15)
    rng = OpeningRange(high=100.0, low=100.0, avg_volume=1)
    assert plan_for(Trigger(Bar(t0, 1, 1, 1, 100.005, 1), t0, 100.0, 1.0), rng, s) is None


def test_close_at_range_high_is_not_trigger():
    s, bars, rng = _setup()
    assert rng is not None
    assert rng is not None
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
    assert s is not None
    assert s.no_entries_after == datetime(2026, 11, 27, 12, 30, tzinfo=ET)
    assert s.flat_by == datetime(2026, 11, 27, 12, 55, tzinfo=ET)


def test_tsx_only_holiday():
    d = date(2026, 8, 3)
    assert session_for(d, Market.US) is not None
    assert session_for(d, Market.TSX) is None


def _plan_with_risk(entry, stop):
    s = session_for(DAY, Market.US)
    assert s is not None
    t0 = s.open + timedelta(minutes=15)
    rng = OpeningRange(high=stop, low=stop, avg_volume=1)
    return plan_for(Trigger(Bar(t0, 1, 1, 1, entry, 1), t0, entry, 1.0), rng, s)


def test_min_risk_boundary_matches_skill():
    assert _plan_with_risk(200.0, 199.90) is not None  # risk == 0.05% of entry: allowed
    assert _plan_with_risk(200.0, 199.91) is None
    assert _plan_with_risk(364.0, 363.82) is None  # floor 0.182
    assert _plan_with_risk(364.0, 363.81) is not None  # risk 0.19


def test_under_cent_risk_rejected():
    assert _plan_with_risk(5.0, 5.0) is None  # risk 0 (< one cent)


def _late_setup(extra_start):
    s = session_for(DAY, Market.US)
    assert s is not None
    rng = OpeningRange(high=100.0, low=99.0, avg_volume=10)
    return s, rng, [Bar(extra_start, 100, 102, 100, 101, 100)]


def test_trigger_ending_at_no_entries_after_allowed():
    s = _late_setup(datetime(2026, 10, 19, 15, 25, tzinfo=ET))[0]
    _, rng, bars = _late_setup(datetime(2026, 10, 19, 15, 25, tzinfo=ET))
    assert find_trigger(bars, s, rng) is not None


def test_trigger_ending_after_no_entries_after_rejected():
    s, rng, bars = _late_setup(datetime(2026, 10, 19, 15, 30, tzinfo=ET))
    assert find_trigger(bars, s, rng) is None


def test_zero_avg_volume_range():
    s, _, bars = _late_setup(datetime(2026, 10, 19, 10, 0, tzinfo=ET))
    rng = OpeningRange(high=100.0, low=99.0, avg_volume=0)
    assert find_trigger(bars, s, rng, min_volume_x=1.5) is None
    t = find_trigger(bars, s, rng, min_volume_x=0)
    assert t is not None and t.volume_x == 0.0
