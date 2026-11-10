"""Parity of the replay port with the day-trader skill's Time Machine.

Expected numbers come from the skill (timemachine.py, MIT) run on the fixture:

    python timemachine.py run --offline tests/fixtures/daytrade/TSLA-60d5m.json.gz \
        --symbol TSLA --date 2026-10-19 --entry 364.18 --stop 358.32 --target 375.90 \
        --entry-time "10:15 AM" --until 15:55 --seed 19 --json

    mc: p_target 0.0348, p_stop 0.2433, p_neither 0.7219, p_green 0.5043,
        avg_R 0.047, median_close 364.37, p5 355.78, p95 373.19, pool_sessions 59
    history (no volume filter): sessions 59, triggered 33, target 3, stop 17,
        close 13, avg_R -0.168
"""

import gzip
from datetime import date, datetime, timedelta
from pathlib import Path

from advisor.daytrade.bars import Bar, YahooClient
from advisor.daytrade.replay import replay, rule_history, seed_for
from advisor.daytrade.rule import Plan, Trigger, session_for
from advisor.models import ET, Market

FIX = Path(__file__).parent.parent / "fixtures" / "daytrade"
DAY = date(2026, 10, 19)


def _history():
    text = gzip.open(FIX / "TSLA-60d5m.json.gz", "rt", encoding="utf-8").read()
    return YahooClient(get=lambda url: text, sleep=lambda s: None).chart("TSLA", "60d", "5m")


def test_replay_matches_skill():
    s = session_for(DAY, Market.US)
    assert s is not None
    start = datetime(2026, 10, 19, 10, 10, tzinfo=ET)
    bar = Bar(start, 364.0, 364.5, 363.5, 364.18, 1000.0)
    trig = Trigger(bar=bar, at=start + timedelta(minutes=5), entry=364.18, volume_x=2.0)
    plan = Plan(entry=364.18, stop=358.32, target=375.90, risk=5.86, flat_by=s.flat_by)
    r = replay(_history(), plan, trig, s, replays=10_000, seed=19)
    assert r.sessions == 59
    assert r.replays == 10_000
    assert round(r.target_first, 4) == 0.0348
    assert round(r.stop_first, 4) == 0.2433
    assert round(r.neither, 4) == 0.7219
    assert round(r.green, 4) == 0.5043
    assert round(r.avg_r, 3) == 0.047
    assert round(r.close_p50, 2) == 364.37
    assert round(r.close_p05, 2) == 355.78
    assert round(r.close_p95, 2) == 373.19


def test_history_matches_skill_without_volume_filter():
    h = rule_history(_history(), DAY, Market.US, min_volume_x=0)
    assert (h.sessions, h.fired, h.target, h.stop, h.neither) == (59, 33, 3, 17, 13)
    assert round(h.avg_r, 3) == -0.168


def test_volume_filter_fires_less():
    h = rule_history(_history(), DAY, Market.US)
    assert h.sessions == 59
    assert 0 < h.fired < 33


def test_history_before_skips_short_and_later_sessions():
    h = rule_history(_history(), date(2026, 8, 1), Market.US, min_volume_x=0)
    assert 0 < h.sessions < 59


def test_seed_for_stable():
    assert seed_for(DAY, "TSLA") == seed_for(DAY, "TSLA")
    assert seed_for(DAY, "TSLA") != seed_for(DAY, "AAPL")
