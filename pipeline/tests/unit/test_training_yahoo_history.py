import pandas as pd
import pytest

from advisor.collectors.yahoo import SilentFailure
from advisor.training.yahoo_history import YAHOO_CANARIES, analyst_history

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
