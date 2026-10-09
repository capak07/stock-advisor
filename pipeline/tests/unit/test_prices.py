from datetime import date

from advisor.collectors.base import CollectorResult, CollectorStatus
from advisor.prices import fetch_daily_bars, find_unconfirmed_jumps
from fakes import bar, history


def runner(name, bars_by_symbol, calls, status=CollectorStatus.OK):
    def run(symbols):
        calls.append((name, list(symbols)))
        records = [b for s in symbols for b in bars_by_symbol.get(s, [])]
        return CollectorResult(name, status, records, 5)
    return run


def jumpy(symbol, source):
    return [
        bar(symbol, date(2026, 10, 12), 10.0, source=source),
        bar(symbol, date(2026, 10, 13), 16.0, source=source),  # +60%
    ]


def test_primary_covers_everything_so_fallback_is_not_called():
    calls = []
    result = fetch_daily_bars(
        ["AAA"],
        primary_run=runner("alpaca_bars", {"AAA": history("AAA", 3)}, calls),
        fallback_run=runner("yfinance_bars", {}, calls),
    )
    assert calls == [("alpaca_bars", ["AAA"])]
    assert len(result.bars["AAA"]) == 3
    assert [r.name for r in result.results] == ["alpaca_bars"]


def test_missing_symbols_come_from_fallback():
    calls = []
    result = fetch_daily_bars(
        ["AAA", "BBB"],
        primary_run=runner("alpaca_bars", {"AAA": history("AAA", 3)}, calls),
        fallback_run=runner("yfinance_bars", {"BBB": history("BBB", 2, source="yfinance")}, calls),
    )
    assert calls[1] == ("yfinance_bars", ["BBB"])
    assert [b.source for b in result.bars["BBB"]] == ["yfinance", "yfinance"]


def test_jump_confirmed_by_fallback_is_kept_and_unconfirmed_is_dropped():
    calls = []
    result = fetch_daily_bars(
        ["CONF", "LONE"],
        primary_run=runner(
            "alpaca_bars", {"CONF": jumpy("CONF", "alpaca"), "LONE": jumpy("LONE", "alpaca")}, calls
        ),
        fallback_run=runner("yfinance_bars", {"CONF": jumpy("CONF", "yfinance")}, calls),
    )
    assert calls[1] == ("yfinance_bars", ["CONF", "LONE"])
    assert [b.day for b in result.bars["CONF"]] == [date(2026, 10, 12), date(2026, 10, 13)]
    assert [b.day for b in result.bars["LONE"]] == [date(2026, 10, 12)]


def test_primary_failure_uses_fallback_for_all():
    calls = []
    result = fetch_daily_bars(
        ["AAA", "BBB"],
        primary_run=runner("alpaca_bars", {}, calls, status=CollectorStatus.FAILED),
        fallback_run=runner(
            "yfinance_bars",
            {"AAA": history("AAA", 2, source="yfinance"), "BBB": history("BBB", 2, source="yfinance")},
            calls,
        ),
    )
    assert sorted(result.bars) == ["AAA", "BBB"]
    assert [r.status for r in result.results] == [CollectorStatus.FAILED, CollectorStatus.OK]


def test_symbol_with_no_bars_anywhere_is_absent():
    result = fetch_daily_bars(
        ["NONE"],
        primary_run=runner("alpaca_bars", {}, []),
        fallback_run=runner("yfinance_bars", {}, []),
    )
    assert result.bars == {}


def test_find_unconfirmed_jumps_uses_two_percent_tolerance():
    bars = jumpy("X", "alpaca")
    near = [bar("X", date(2026, 10, 13), 16.3, source="yfinance")]  # within 2%
    far = [bar("X", date(2026, 10, 13), 17.0, source="yfinance")]   # 6% away
    assert find_unconfirmed_jumps(bars, near) == set()
    assert find_unconfirmed_jumps(bars, far) == {date(2026, 10, 13)}
    assert find_unconfirmed_jumps(bars, []) == {date(2026, 10, 13)}


def test_reversion_after_dropped_spike_is_kept():
    bars = [
        bar("X", date(2026, 10, 12), 10.0, source="alpaca"),
        bar("X", date(2026, 10, 13), 30.0, source="alpaca"),
        bar("X", date(2026, 10, 14), 10.0, source="alpaca"),
    ]
    assert find_unconfirmed_jumps(bars, []) == {date(2026, 10, 13)}


def test_persistent_move_loses_only_the_jump_day():
    bars = [
        bar("X", date(2026, 10, 12), 10.0, source="alpaca"),
        bar("X", date(2026, 10, 13), 16.0, source="alpaca"),
        bar("X", date(2026, 10, 14), 16.2, source="alpaca"),
        bar("X", date(2026, 10, 15), 16.5, source="alpaca"),
    ]
    assert find_unconfirmed_jumps(bars, []) == {date(2026, 10, 13)}
