from datetime import UTC, date, datetime

import pandas as pd
import pytest

from advisor.collectors.base import PartialFetch
from advisor.collectors.yfinance_earnings import YFinanceEarnings, parse_earnings
from advisor.models import ET, Market

AS_OF = datetime(2026, 10, 14, 12, 15, tzinfo=UTC)


class CountingLimiter:
    def __init__(self) -> None:
        self.count = 0

    def acquire(self) -> None:
        self.count += 1


class YFRateLimitError(Exception):
    pass


def frame(fixtures_dir, name: str) -> pd.DataFrame:
    path = fixtures_dir / "yfinance_earnings" / f"earnings_dates_{name}.json"
    return pd.read_json(path, orient="split")


def test_parse_gives_one_report_per_date_oldest_first(fixtures_dir):
    reports = parse_earnings("AAPL", frame(fixtures_dir, "AAPL"))
    assert len(reports) == 25
    assert reports == sorted(reports, key=lambda r: r.report_at)
    last, upcoming = reports[-2], reports[-1]
    assert last.report_at == datetime(2026, 7, 30, 16, 0, tzinfo=ET)
    assert last.eps_estimate == pytest.approx(1.89)
    assert (last.eps_actual, last.surprise_pct) == (pytest.approx(2.02), pytest.approx(6.74))
    assert upcoming.report_at == datetime(2026, 11, 2, 15, 0, tzinfo=ET)
    assert upcoming.eps_estimate == pytest.approx(1.98)
    assert (upcoming.eps_actual, upcoming.surprise_pct) == (None, None)


def test_tsx_reports_parse_the_same_way(fixtures_dir):
    reports = parse_earnings("RY.TO", frame(fixtures_dir, "RY_TO"))
    assert len(reports) == 25
    assert reports[-1].report_at == datetime(2026, 12, 3, 7, 0, tzinfo=ET)
    assert reports[-1].eps_actual is None
    assert reports[-2].eps_actual == pytest.approx(4.28)
    assert {r.symbol for r in reports} == {"RY.TO"}


def test_a_date_listed_twice_keeps_the_reported_row(fixtures_dir):
    reports = parse_earnings("BRK.B", frame(fixtures_dir, "BRK_B"))
    assert len(reports) == 24  # 25 rows; 2026-08-08 is listed twice
    [august] = [r for r in reports if r.report_at.date() == date(2026, 8, 8)]
    assert august.report_at.hour == 8
    assert (august.eps_actual, august.surprise_pct) == (pytest.approx(6.03), pytest.approx(17.4))


def test_no_coverage_yields_no_reports():
    assert parse_earnings("SPY", None) == []
    assert parse_earnings("SPY", pd.DataFrame()) == []


def test_earnings_are_core_and_cover_both_markets():
    collector = YFinanceEarnings()
    assert collector.core is True
    assert collector.markets == frozenset({Market.US, Market.TSX})


def test_fetch_maps_symbols_and_takes_one_limiter_token_per_symbol(fixtures_dir):
    loaded = []
    limiter = CountingLimiter()

    def load(yahoo_symbol):
        loaded.append(yahoo_symbol)
        return frame(fixtures_dir, "AAPL") if yahoo_symbol == "AAPL" else None  # others: no coverage

    records = YFinanceEarnings(load=load, limiter=limiter).fetch(["BRK.B", "AAPL", "RY.TO"], AS_OF)
    assert loaded == ["BRK-B", "AAPL", "RY.TO"]
    assert limiter.count == 3
    assert {r.symbol for r in records} == {"AAPL"}
    assert len(records) == 25


def test_rate_limiting_stops_the_loop(fixtures_dir):
    def load(yahoo_symbol):
        if yahoo_symbol == "BBB":
            raise YFRateLimitError("Too Many Requests")
        return frame(fixtures_dir, "AAPL")

    with pytest.raises(PartialFetch, match="stopped after 1 of 3 symbols") as caught:
        YFinanceEarnings(load=load).fetch(["AAA", "BBB", "CCC"], AS_OF)
    assert {r.symbol for r in caught.value.records} == {"AAA"}
