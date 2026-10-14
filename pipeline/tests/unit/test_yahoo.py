import pytest

from advisor.collectors.base import PartialFetch
from advisor.collectors.yahoo import SilentFailure, collect_yahoo
from fakes import info


class CountingLimiter:
    def __init__(self) -> None:
        self.count = 0

    def acquire(self) -> None:
        self.count += 1


def symbols_of(count: int) -> list[str]:
    return [f"S{n}" for n in range(count)]


def answering(empty: set[str], calls: list[str] | None = None):
    def fetch_one(symbol: str):
        if calls is not None:
            calls.append(symbol)
        return [] if symbol in empty else [info(symbol)]

    return fetch_one


def test_most_symbols_empty_is_a_partial_result_not_ok():
    symbols = symbols_of(20)
    empty = {symbols[0], *symbols[1::2]}  # 11 empties, never two in a row beyond the first pair
    with pytest.raises(PartialFetch, match="Yahoo returned nothing for 11 of 20 symbols") as caught:
        collect_yahoo(symbols, answering(empty), limiter=None)
    assert len(caught.value.records) == 9


def test_half_empty_is_still_ok():
    symbols = symbols_of(20)
    records = collect_yahoo(symbols, answering(set(symbols[::2])), limiter=None)
    assert len(records) == 10


def test_a_small_set_skips_the_coverage_check():
    symbols = symbols_of(19)
    assert collect_yahoo(symbols, answering(set(symbols)), limiter=None) == []


def test_a_long_run_of_empties_stops_the_loop():
    symbols = symbols_of(30)
    calls: list[str] = []
    with pytest.raises(PartialFetch, match="stopped after") as caught:
        collect_yahoo(symbols, answering(set(symbols[2:]), calls), limiter=None)
    assert len(calls) == 27
    assert [r.symbol for r in caught.value.records] == ["S0", "S1"]


def test_empty_from_the_start_raises_silent_failure():
    symbols = symbols_of(30)
    with pytest.raises(SilentFailure):
        collect_yahoo(symbols, answering(set(symbols)), limiter=None)


def test_the_limiter_is_acquired_once_per_call_made():
    symbols = symbols_of(30)
    calls: list[str] = []
    limiter = CountingLimiter()
    with pytest.raises(PartialFetch):
        collect_yahoo(symbols, answering(set(symbols[2:]), calls), limiter=limiter)
    assert limiter.count == len(calls) == 27
