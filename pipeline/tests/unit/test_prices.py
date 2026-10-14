from datetime import date

from advisor.collectors.base import CollectorResult, CollectorStatus
from advisor.prices import fetch_daily_bars, find_jumps
from fakes import bar, history


def day(i: int) -> date:
    return date(2026, 10, 12 + i)


def closes(*values: float) -> list:
    return [bar("X", day(i), value) for i, value in enumerate(values)]


def test_a_move_within_fifty_percent_is_not_flagged():
    assert find_jumps(closes(10.0, 14.9, 10.0)) == set()


def test_a_jump_is_flagged_not_dropped():
    assert find_jumps(closes(10.0, 16.0)) == {day(1)}


def test_a_crash_is_flagged_too():
    assert find_jumps(closes(10.0, 4.0)) == {day(1)}


def test_reversion_after_a_spike_is_not_flagged():
    assert find_jumps(closes(10.0, 30.0, 10.0)) == {day(1)}


def test_a_persistent_move_flags_only_the_jump_day():
    assert find_jumps(closes(10.0, 16.0, 16.2, 16.5)) == {day(1)}


def test_no_bars_means_no_flags():
    assert find_jumps([]) == set()


def runner(bars_by_symbol, calls, status=CollectorStatus.OK):
    def run(symbols):
        calls.append(list(symbols))
        records = [b for s in symbols for b in bars_by_symbol.get(s, [])]
        return CollectorResult("yfinance_bars", status, records, 5)
    return run


def test_fetch_daily_bars_asks_once_and_keeps_flagged_bars():
    calls = []
    jumpy = [bar("JMP", day(0), 10.0), bar("JMP", day(1), 16.0)]
    result = fetch_daily_bars(
        ["JMP", "AAA", "JMP", "NONE"], run=runner({"AAA": history("AAA", 3), "JMP": jumpy}, calls)
    )
    assert calls == [["AAA", "JMP", "NONE"]]
    assert sorted(result.bars) == ["AAA", "JMP"]
    assert [b.close for b in result.bars["JMP"]] == [10.0, 16.0]
    assert result.flagged == {"JMP": {day(1)}}


def test_fetch_daily_bars_sorts_by_day_and_keeps_the_last_bar_per_day():
    records = [bar("A", day(1), 11.0), bar("A", day(0), 10.0), bar("A", day(1), 12.0)]
    result = fetch_daily_bars(["A"], run=runner({"A": records}, []))
    assert [(b.day, b.close) for b in result.bars["A"]] == [(day(0), 10.0), (day(1), 12.0)]
