import json
import sys
import types
from datetime import UTC, date, datetime

import pandas as pd
import pytest

from advisor.collectors.yfinance_options import (
    Chain,
    ChainSet,
    OptionsView,
    YFinanceOptions,
    atm_iv,
    choose_expiries,
    options_view,
)
from advisor.models import Market

AS_OF = datetime(2026, 10, 19, 15, 30, tzinfo=UTC)  # 11:30 ET, when the fixtures were taken
TODAY = date(2026, 10, 19)
COLUMNS = ["contractSymbol", "lastTradeDate", "strike", "lastPrice", "bid", "ask", "change",
           "percentChange", "volume", "openInterest", "impliedVolatility", "inTheMoney"]


def answer(fixtures_dir, name: str) -> dict:
    """One of Yahoo's /v7/finance/options answers (its `result[0]`), trimmed to strikes near spot."""
    text = (fixtures_dir / "yfinance_options" / name).read_text(encoding="utf-8")
    return json.loads(text)["optionChain"]["result"][0]


def frame(contracts: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(contracts).reindex(columns=COLUMNS)  # as yfinance builds it


def expiry_of(epoch: int) -> date:
    return datetime.fromtimestamp(epoch, UTC).date()


def chain_of(result: dict) -> Chain:
    options = result["options"][0]
    return Chain(expiry_of(options["expirationDate"]), frame(options["calls"]), frame(options["puts"]))


def aapl(fixtures_dir) -> ChainSet:
    first = answer(fixtures_dir, "AAPL_first.json")
    chains = [chain_of(first)] + [
        chain_of(answer(fixtures_dir, name)) for name in ("AAPL_20261026.json", "AAPL_20261120.json")
    ]
    return ChainSet(first["quote"], [expiry_of(e) for e in first["expirationDates"]], chains)


def test_the_near_expiry_is_a_week_out_and_the_mid_one_closest_to_a_month(fixtures_dir):
    expiries = aapl(fixtures_dir).expiries
    assert expiries[0] == TODAY  # Yahoo lists today's 0DTE expiry first
    assert choose_expiries(expiries, TODAY) == [date(2026, 10, 26), date(2026, 11, 20)]
    assert choose_expiries([date(2026, 10, 23)], TODAY) == []  # nothing a week out
    assert choose_expiries([date(2026, 11, 13)], TODAY) == [date(2026, 11, 13)]  # near is mid


def test_an_apple_summary_from_real_chains(fixtures_dir):
    view = options_view("AAPL", aapl(fixtures_dir), AS_OF)
    assert (view.near_expiry, view.mid_expiry, view.expiries) == (date(2026, 10, 26), date(2026, 11, 20), 23)
    assert view.underlying_price == pytest.approx(343.135)
    assert view.market_state == "REGULAR"
    assert view.quote_time == datetime(2026, 10, 19, 15, 28, 21, tzinfo=UTC)
    assert view.atm_iv_near == pytest.approx(0.2246, abs=5e-4)
    assert view.atm_iv_mid == pytest.approx(0.2689, abs=5e-4)
    assert view.skew_near == pytest.approx(0.0497, abs=5e-4)
    # Volume and open interest leave out today's 0DTE chain
    near_and_mid = aapl(fixtures_dir).chains[1:]
    assert view.call_volume == sum(int(c.calls["volume"].fillna(0).sum()) for c in near_and_mid)
    assert view.put_call_volume == pytest.approx(view.put_volume / view.call_volume)
    assert view.put_call_open_interest == pytest.approx(view.put_open_interest / view.call_open_interest)


def test_quotes_without_a_bid_or_with_yahoos_placeholder_iv_are_not_used():
    def side(*rows):
        return frame([{"strike": s, "bid": b, "ask": a, "impliedVolatility": iv} for s, b, a, iv in rows])

    chain = Chain(
        date(2026, 10, 26),
        side((95, 6.0, 6.2, 0.30), (100, 2.0, 2.1, 0.00001), (105, 0.0, 0.5, 0.90)),
        side((95, 0.9, 1.0, 0.34), (100, 2.4, 2.5, 0.00001), (105, 5.0, 5.2, 0.26)),
    )
    # 100 has only placeholders and 105's call has no bid: interpolate 95 (0.32) and 105 (0.26)
    assert atm_iv(chain, 100.0) == pytest.approx(0.29)
    assert atm_iv(Chain(date(2026, 10, 26), side(), side()), 100.0) is None


def test_put_call_ratios_use_only_the_near_and_mid_chains():
    def chain(expiry, calls, puts):
        def side(volume, open_interest):
            return frame([{"strike": 100, "bid": 1.0, "ask": 1.1, "impliedVolatility": 0.3,
                           "volume": volume, "openInterest": open_interest}])
        return Chain(expiry, side(*calls), side(*puts))

    front = chain(date(2026, 10, 22), (100000, 50000), (200000, 60000))  # 3 days out: not near
    near = chain(date(2026, 10, 26), (10, 100), (20, 200))
    mid = chain(date(2026, 11, 18), (30, 300), (40, 400))
    expiries = [front.expiry, near.expiry, mid.expiry]
    view = options_view("XYZ", ChainSet({"regularMarketPrice": 100.0}, expiries, [front, near, mid]), AS_OF)
    assert (view.near_expiry, view.mid_expiry) == (near.expiry, mid.expiry)
    assert (view.call_volume, view.put_volume) == (40, 60)
    assert (view.call_open_interest, view.put_open_interest) == (400, 600)
    assert view.put_call_volume == pytest.approx(1.5)


def test_a_stock_without_options_or_a_price_yields_no_record():
    assert options_view("AACG", ChainSet({"regularMarketPrice": 0.81}, [], []), AS_OF) is None
    assert options_view("X", ChainSet({}, [TODAY], []), AS_OF) is None


class FakeTicker:
    """yfinance's Ticker as the loader uses it, answering from the fixtures and counting requests."""

    requests: list[str] = []

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        self._first = None

    def option_chain(self, date: str | None = None):
        FakeTicker.requests.append(f"{self.symbol} {date or 'first'}")
        result = self.answers[self.symbol if date is None else f"{self.symbol} {date}"]
        if not result["options"]:
            return types.SimpleNamespace(calls=None, puts=None, underlying=None)
        self._first = self._first or result
        options = result["options"][0]
        return types.SimpleNamespace(
            calls=frame(options["calls"]), puts=frame(options["puts"]), underlying=result["quote"]
        )

    @property
    def options(self) -> tuple[str, ...]:
        return tuple(expiry_of(e).isoformat() for e in self._first["expirationDates"])


class CountingLimiter:
    def __init__(self) -> None:
        self.count = 0

    def acquire(self) -> None:
        self.count += 1


@pytest.fixture
def fake_yfinance(fixtures_dir, monkeypatch):
    FakeTicker.requests = []
    FakeTicker.answers = {
        "AAPL": answer(fixtures_dir, "AAPL_first.json"),
        "AAPL 2026-10-26": answer(fixtures_dir, "AAPL_20261026.json"),
        "AAPL 2026-11-20": answer(fixtures_dir, "AAPL_20261120.json"),
        "AACG": answer(fixtures_dir, "noopts_AACG.json"),
    }
    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=FakeTicker))
    return FakeTicker


def test_yahoo_takes_three_requests_and_a_token_for_each(fake_yfinance):
    limiter = CountingLimiter()
    records = YFinanceOptions(limiter=limiter).fetch(["AAPL", "AACG"], AS_OF)
    assert fake_yfinance.requests == ["AAPL first", "AAPL 2026-10-26", "AAPL 2026-11-20", "AACG first"]
    assert limiter.count == 4
    assert [r.symbol for r in records] == ["AAPL"]  # AACG lists no options
    assert isinstance(records[0], OptionsView)


def test_share_classes_are_asked_in_yahoos_form():
    asked = []

    def load(yahoo_symbol, choose):
        asked.append(yahoo_symbol)
        return ChainSet({"regularMarketPrice": 500.0}, [date(2026, 10, 30)], [])

    records = YFinanceOptions(load=load).fetch(["BRK.B"], AS_OF)
    assert asked == ["BRK-B"]  # "BRK.B" gets an empty stub from Yahoo
    assert [r.symbol for r in records] == ["BRK.B"]


def test_the_source_is_us_only_per_run_and_capped():
    collector = YFinanceOptions()
    assert collector.markets == frozenset({Market.US})
    assert collector.cadence == "per_run"
    assert collector.max_symbols == 40
