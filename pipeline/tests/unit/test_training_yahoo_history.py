import logging

import pandas as pd
import pytest

from advisor.collectors.yahoo import SilentFailure
from advisor.training.yahoo_history import MAX_FAILED_SHARE, YAHOO_CANARIES, analyst_history

COLUMNS = ["symbol", "graded_at", "firm", "action", "from_grade", "to_grade", "price_target_action"]


class YFRateLimitError(Exception):
    """Carries yfinance's error name, which is how yahoo.rate_limited recognises it."""


def _grades(rows: list[tuple[str, str, str, str, str, str]]) -> pd.DataFrame:
    """Yahoo's `upgrades_downgrades`: GradeDate index, then Firm, ToGrade, FromGrade, Action, priceTargetAction."""
    return pd.DataFrame(
        [r[1:] for r in rows], columns=["Firm", "ToGrade", "FromGrade", "Action", "priceTargetAction"],
        index=pd.DatetimeIndex([r[0] for r in rows], name="GradeDate"),
    )


ONE = [("2024-03-01 15:00", "GS", "Buy", "Hold", "up", "Raises")]


def test_the_history_keeps_one_row_per_event_and_symbol():
    data = {
        "AAPL": _grades([("2024-03-01 15:00", "GS", "Buy", "Hold", "up", "Raises"),
                         ("2024-04-01 15:00", "MS", "Sell", "Buy", "down", "Lowers")]),
        "MSFT": _grades([("2024-03-05 12:00", "JPM", "Buy", "Buy", "main", "Maintains")]),
    }
    events, empty = analyst_history(["AAPL", "MSFT"], lambda s: data[s], None)
    assert empty == 0
    assert list(events.columns) == COLUMNS
    assert events["symbol"].tolist() == ["AAPL", "AAPL", "MSFT"]
    assert events["graded_at"].dtype == "datetime64[ns]"
    first = events.iloc[0]
    assert (first["firm"], first["action"], first["from_grade"], first["to_grade"], first["price_target_action"]) == (
        "GS", "up", "Hold", "Buy", "Raises")
    assert events["graded_at"].iloc[0] == pd.Timestamp("2024-03-01 15:00")


def test_a_timezone_aware_grade_time_is_stored_as_naive_utc():
    data = _grades([("2024-03-01 10:00", "GS", "Buy", "Hold", "up", "Raises")])
    data.index = data.index.tz_localize("America/New_York")
    events, _ = analyst_history(["AAPL"], lambda s: data, None)
    assert events["graded_at"].iloc[0] == pd.Timestamp("2024-03-01 15:00")


def test_one_call_and_one_limiter_token_per_symbol():
    class Limiter:
        tokens = 0

        def acquire(self) -> None:
            Limiter.tokens += 1

    calls: list[str] = []

    def load(symbol: str) -> pd.DataFrame:
        calls.append(symbol)
        return _grades(ONE)

    analyst_history(["AAPL", "MSFT", "XYZ"], load, Limiter())  # type: ignore[arg-type]
    assert calls == ["AAPL", "MSFT", "XYZ"] and Limiter.tokens == 3


def test_the_history_stops_only_on_a_rate_limit():
    symbols = ["AAPL", "MSFT"] + [f"S{i:02d}" for i in range(98)]
    covered = set(symbols[:40])  # 60 of 100 empty: past collect_yahoo's 0.5 share and 25 streak

    def load(symbol: str) -> pd.DataFrame:
        return _grades(ONE) if symbol in covered else pd.DataFrame()

    events, empty = analyst_history(symbols, load, None)
    assert empty == 60
    assert sorted(events["symbol"].unique()) == sorted(covered)

    def limited(symbol: str) -> pd.DataFrame:
        raise YFRateLimitError("Too Many Requests")

    with pytest.raises(YFRateLimitError):
        analyst_history(symbols, limited, None)


def test_a_missing_canary_is_a_silent_failure():
    assert YAHOO_CANARIES == ("AAPL", "MSFT")

    def load(symbol: str) -> pd.DataFrame:
        return pd.DataFrame() if symbol == "AAPL" else _grades(ONE)

    with pytest.raises(SilentFailure):
        analyst_history(["ZZZ", "AAPL"], load, None)
    events, empty = analyst_history(["ZZZ", "MSFT"], load, None)
    assert empty == 0 and len(events) == 2  # a canary that is not asked for is not checked


def test_an_empty_history_has_the_columns():
    events, empty = analyst_history(["ZZZ"], lambda s: pd.DataFrame(), None)
    assert empty == 1 and events.empty and list(events.columns) == COLUMNS
    assert events["graded_at"].dtype == "datetime64[ns]"


def _hundred() -> list[str]:
    return ["AAPL", "MSFT"] + [f"S{i:02d}" for i in range(98)]


def test_a_failure_is_retried_once_through_the_limiter():
    class Limiter:
        tokens = 0

        def acquire(self) -> None:
            Limiter.tokens += 1

    seen: dict[str, int] = {}

    def load(symbol: str) -> pd.DataFrame:
        seen[symbol] = seen.get(symbol, 0) + 1
        if symbol == "XYZ" and seen[symbol] == 1:
            raise ConnectionError("reset")
        return _grades(ONE)

    events, empty = analyst_history(["XYZ", "ABC"], load, Limiter())  # type: ignore[arg-type]
    assert sorted(events["symbol"]) == ["ABC", "XYZ"] and empty == 0
    assert seen == {"XYZ": 2, "ABC": 1} and Limiter.tokens == 3


def test_a_symbol_that_fails_twice_is_logged_and_left_out(caplog):
    def load(symbol: str) -> pd.DataFrame:
        if symbol == "S05":
            raise ConnectionError("reset")
        return _grades(ONE)

    with caplog.at_level(logging.WARNING):
        events, empty = analyst_history(_hundred(), load, None)
    assert len(events) == 99 and "S05" not in set(events["symbol"]) and empty == 0
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1 and "S05" in warnings[0].getMessage() and "ConnectionError" in warnings[0].getMessage()


def test_too_many_failed_symbols_is_a_silent_failure():
    assert MAX_FAILED_SHARE == 0.02
    broken = {"S01", "S02", "S03"}  # 3 of 100

    def load(symbol: str) -> pd.DataFrame:
        if symbol in broken:
            raise TimeoutError("slow")
        return _grades(ONE)

    with pytest.raises(SilentFailure, match="3 of 100"):
        analyst_history(_hundred(), load, None)


def test_a_canary_that_fails_every_call_still_raises():
    def load(symbol: str) -> pd.DataFrame:
        if symbol == "MSFT":
            raise ConnectionError("reset")
        return _grades(ONE)

    with pytest.raises(SilentFailure):
        analyst_history(_hundred(), load, None)
