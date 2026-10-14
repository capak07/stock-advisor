import json
from datetime import UTC, datetime

import pandas as pd
import pytest

from advisor.collectors.base import DeadlineExceeded, PartialFetch
from advisor.collectors.yahoo import rate_limited
from advisor.collectors.yfinance_analyst import YFinanceAnalyst, analyst_view
from advisor.models import Market

AS_OF = datetime(2026, 10, 12, 20, 0, tzinfo=UTC)


class CountingLimiter:
    def __init__(self) -> None:
        self.count = 0

    def acquire(self) -> None:
        self.count += 1


class YFRateLimitError(Exception):  # same name as yfinance's, which `rate_limited` matches
    pass


def aapl(fixtures_dir):
    base = fixtures_dir / "yfinance_analyst"
    targets = json.loads((base / "price_targets.json").read_text(encoding="utf-8"))
    recommendations = pd.read_json(base / "recommendations.json", orient="split")
    upgrades = pd.read_json(base / "upgrades.json", orient="split")
    upgrades.index.name = "GradeDate"
    return targets, recommendations, upgrades


def test_analyst_view_from_real_aapl_data(fixtures_dir):
    view = analyst_view("AAPL", *aapl(fixtures_dir), AS_OF)
    assert view.target_mean == pytest.approx(328.09384)
    assert (view.target_low, view.target_high, view.target_median) == (215.0, 405.0, 340.0)
    assert (view.rec_strong_buy, view.rec_buy, view.rec_hold, view.rec_sell, view.rec_strong_sell) == (
        6, 19, 13, 3, 3,
    )
    assert (view.upgrades_30d, view.downgrades_30d, view.upgrades_90d, view.downgrades_90d) == (0, 0, 2, 2)
    assert (view.target_raises_30d, view.target_lowers_30d) == (2, 1)


def test_no_coverage_yields_no_record():
    assert analyst_view("SPY", {}, pd.DataFrame(), pd.DataFrame(), AS_OF) is None


def test_zero_or_missing_targets_are_treated_as_missing():
    view = analyst_view("X", {"mean": 0.0, "low": 12.5}, pd.DataFrame(), pd.DataFrame(), AS_OF)
    assert view.target_mean is None
    assert view.target_low == 12.5
    assert view.target_high is None


def test_yahoo_analyst_covers_both_markets_and_is_capped():
    collector = YFinanceAnalyst()
    assert collector.markets == frozenset({Market.US, Market.TSX})
    assert collector.max_symbols == 200


def test_fetch_maps_symbols_and_takes_one_limiter_token_per_symbol(fixtures_dir):
    data = aapl(fixtures_dir)
    loaded = []
    limiter = CountingLimiter()

    def load(yahoo_symbol):
        loaded.append(yahoo_symbol)
        return data

    records = YFinanceAnalyst(load=load, limiter=limiter).fetch(["BRK.B", "AAPL", "RY.TO"], AS_OF)
    assert loaded == ["BRK-B", "AAPL", "RY.TO"]
    assert [r.symbol for r in records] == ["BRK.B", "AAPL", "RY.TO"]
    assert limiter.count == 3


def test_a_failing_symbol_is_a_partial_result(fixtures_dir):
    data = aapl(fixtures_dir)

    def load(yahoo_symbol):
        if yahoo_symbol == "BAD":
            raise KeyError("quoteSummary")
        return data

    with pytest.raises(PartialFetch, match="BAD") as caught:
        YFinanceAnalyst(load=load).fetch(["AAPL", "BAD"], AS_OF)
    assert [r.symbol for r in caught.value.records] == ["AAPL"]


def test_rate_limiting_stops_the_loop(fixtures_dir):
    data = aapl(fixtures_dir)
    loaded = []

    def load(yahoo_symbol):
        loaded.append(yahoo_symbol)
        if yahoo_symbol == "BBB":
            raise YFRateLimitError("Too Many Requests")
        return data

    assert rate_limited(YFRateLimitError("x")) and not rate_limited(KeyError("x"))
    with pytest.raises(PartialFetch, match="stopped after 1 of 3 symbols"):
        YFinanceAnalyst(load=load).fetch(["AAA", "BBB", "CCC"], AS_OF)
    assert loaded == ["AAA", "BBB"]


def test_the_run_deadline_ends_the_loop_with_what_was_gathered(fixtures_dir):
    data = aapl(fixtures_dir)

    def load(yahoo_symbol):
        if yahoo_symbol == "BBB":
            raise DeadlineExceeded("run time budget exhausted")
        return data

    with pytest.raises(PartialFetch, match="stopped after 1 of 3 symbols") as caught:
        YFinanceAnalyst(load=load).fetch(["AAA", "BBB", "CCC"], AS_OF)
    assert [r.symbol for r in caught.value.records] == ["AAA"]
