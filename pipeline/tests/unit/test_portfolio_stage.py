import contextlib
import math
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pandas as pd
import psycopg
import pytest

from advisor.collectors.base import CollectorResult, CollectorStatus
from advisor.collectors.clinical_trials import TrialActivity
from advisor.collectors.coingecko import CryptoQuote
from advisor.collectors.yfinance_earnings import EarningsReport
from advisor.model.market_run import Forecast, MarketModel
from advisor.model.variants import BASELINE
from advisor.models import ET, AssetType, DailyBar, LinkedPick, Market, PredictionRow, RunKind
from advisor.policy import DEFAULT_POLICY
from advisor.portfolio.actions import Holding, decide
from advisor.portfolio.exit_plan import PLAN_VERSION, build_plan
from advisor.portfolio.ledger import Loss, Position
from advisor.portfolio.stage import (
    RunView,
    _plan_cost,
    action_rows,
    advise_stage,
    holding_inputs,
    signals_reversed,
)
from advisor.portfolio.stops import atr_pct, trailing_stop
from advisor.recommend.stage import NOT_ELIGIBLE, MarketAdvice, StockInputs, scheduled_events
from advisor.schedule import sessions_after
from fakes import bar

DAY = date(2026, 10, 13)  # both markets' feature day
TODAY = date(2026, 10, 14)
OPENED = date(2026, 9, 1)


def _row(symbol: str, h: int = 63, p: float = 0.5, q50: float = 0.01) -> PredictionRow:
    return PredictionRow(symbol, h, -0.05, q50, 0.08, p, "XIU.TO", "v1")


def _bars(symbol: str, closes: list[float], end: date = DAY) -> list[DailyBar]:
    return [bar(symbol, end - timedelta(days=len(closes) - 1 - i), c) for i, c in enumerate(closes)]


def _candles(symbol: str, n: int = 30, end: date = DAY) -> list[DailyBar]:
    """Coin candles with a real daily range, so their ATR isn't zero."""
    return [
        DailyBar(symbol=symbol, day=end - timedelta(days=n - 1 - i), open=1.0 + i / 100, high=1.05 + i / 100,
                 low=0.95 + i / 100, close=1.0 + i / 100, volume=1e6, source="coinbase")
        for i in range(n)
    ]


def _position(symbol: str, account: str = "tfsa", qty: float = 10.0, cost_cad: float = 500.0,
              asset_type: AssetType = AssetType.STOCK, pick_id: int | None = None) -> Position:
    return Position(account, symbol, asset_type, qty, cost_cad, OPENED, pick_id)


def _tsx(rows: dict[str, list[PredictionRow]], features: dict[str, dict], risk: dict[str, tuple[str, float]]):
    """A TSX forecast and its stage-8 advice."""
    frame = pd.DataFrame({s: {"eligible": True, "atr_14_pct": 0.04, "ret_21": 0.0} | f for s, f in features.items()}).T
    forecast = Forecast(frame, [r for rs in rows.values() for r in rs])
    inputs = StockInputs(DAY, False, rows, dict.fromkeys(rows, True), dict.fromkeys(rows, 0.004))
    risk_frame = pd.DataFrame(
        {"risk_level": {s: lvl for s, (lvl, _) in risk.items()}, "max_position_pct": {s: m for s, (_, m) in risk.items()}}
    )
    return forecast, MarketAdvice(inputs, risk_frame)


def _view(**kw) -> RunView:
    base = RunView(
        today=TODAY,
        days={Market.TSX: (DAY, False), Market.US: (DAY, False)},
        bars={"XIU.TO": _bars("XIU.TO", [40.0]), "SPY": _bars("SPY", [600.0])},
        flagged={},
        quotes={},
        candles={},
        crypto_features={},
        forecasts={},
        advice={},
        no_forecast={Market.TSX: "no active model", Market.US: "no active model"},
        scheduled={},
        usd_cad=1.4,
        previous={},
        picks={},
        explain=lambda market, symbol, h: [],
    )
    return replace(base, **kw)


def test_a_forecast_stock_reads_stage_8s_rows_risk_and_momentum():
    rows = {s: [_row(s)] for s in ["RY.TO", "TD.TO", "BB.TO"]} | {"NA.TO": []}  # NA.TO's rows weren't finite
    forecast, advice = _tsx(
        rows,
        {"RY.TO": {"ret_21": 0.2, "atr_14_pct": 0.05}, "TD.TO": {"ret_21": 0.1}, "BB.TO": {"ret_21": 0.3},
         "NA.TO": {"ret_21": 0.9}},
        {"RY.TO": ("high", 1.5), "TD.TO": ("low", 5.0), "BB.TO": ("low", 5.0)},
    )
    closes = [50.0, 64.0, 60.0]  # the high since purchase is 64
    view = _view(
        forecasts={Market.TSX: forecast}, advice={Market.TSX: advice},
        bars={**_view().bars, "RY.TO": _bars("RY.TO", closes), "TD.TO": _bars("TD.TO", [20.0])},
    )
    ry, td = holding_inputs([_position("RY.TO"), _position("TD.TO", cost_cad=100.0)], [], view)
    assert ry.rows == rows["RY.TO"] and (ry.cost, ry.sane, ry.why_no_forecast) == (0.004, True, None)
    assert (ry.risk_level, ry.max_position_pct) == ("high", 1.5)
    assert ry.momentum_pct == pytest.approx(200 / 3)  # 2nd of 3: NA.TO has no rows, so isn't ranked
    assert (ry.benchmark, ry.price, ry.value_cad, ry.cost_cad) == ("XIU.TO", 60.0, 600.0, 500.0)
    assert ry.portfolio_cad == 800.0  # 600 + 200
    assert ry.trailing_stop == pytest.approx(64 - 2.5 * 0.05 * 60)  # the model's ATR
    assert td.momentum_pct == pytest.approx(100 / 3)


def test_a_stocks_row_carries_what_grading_needs():
    forecast, advice = _tsx({"RY.TO": [_row("RY.TO", 63, p=0.5)]}, {"RY.TO": {}}, {"RY.TO": ("medium", 3.0)})
    view = _view(forecasts={Market.TSX: forecast}, advice={Market.TSX: advice},
                 bars={**_view().bars, "RY.TO": _bars("RY.TO", [60.0])})
    positions = [_position("RY.TO")]
    (row,), _ = action_rows(positions, holding_inputs(positions, [], view), view)
    assert (row.account, row.symbol, row.asset_type, row.action) == ("tfsa", "RY.TO", AssetType.STOCK, "hold")
    assert (row.horizon_days, row.exit_by, row.feature_day) == (63, date(2027, 1, 13), DAY)
    assert (row.ref_price, row.bench_ref_price) == (60.0, 40.0)
    assert (row.q10, row.q50, row.q90) == (-0.05, 0.01, 0.08)
    assert (row.risk_level, row.max_position_pct) == ("medium", 3.0)


def test_a_stock_without_a_forecast_says_why():
    forecast, advice = _tsx({"RY.TO": [_row("RY.TO")]}, {"RY.TO": {}, "XX.TO": {"eligible": False}},
                            {"RY.TO": ("low", 5.0)})
    view = _view(
        forecasts={Market.TSX: forecast}, advice={Market.TSX: advice},
        no_forecast={Market.US: "the model failed this run"},
        bars={**_view().bars, "RY.TO": _bars("RY.TO", [60.0]), "XX.TO": _bars("XX.TO", [0.5]),
              "AAA": _bars("AAA", [10.0])},
    )
    positions = [_position("XX.TO"), _position("AAA"), _position("ZZ.TO")]
    ineligible, failed, unpriced = holding_inputs(positions, [], view)
    assert (ineligible.why_no_forecast, ineligible.rows) == (NOT_ELIGIBLE, [])
    assert (ineligible.risk_level, ineligible.max_position_pct, ineligible.momentum_pct) == ("very_high", 0.5, None)
    assert failed.why_no_forecast == "the model failed this run"
    assert failed.value_cad == pytest.approx(10.0 * 10 * 1.4)  # a US stock's USD close at the latest rate
    assert (unpriced.why_no_forecast, unpriced.value_cad, unpriced.trailing_stop) == ("not priced this run", 500.0, None)
    rows, _ = action_rows(positions, [ineligible, failed, unpriced], view)
    assert [(r.action, r.reasons) for r in rows] == [
        ("hold", [NOT_ELIGIBLE]), ("hold", ["the model failed this run"]), ("hold", ["not priced this run"]),
    ]
    assert [r.horizon_days for r in rows] == [None, None, None]
    assert rows[2].ref_price is None


def test_a_coin_is_valued_from_its_quote_and_stopped_on_its_candles():
    candles = _candles("BONK")
    quote = CryptoQuote(symbol="BONK", coin_id="bonk", price_cad=1.8, updated_at=datetime(2026, 10, 14, tzinfo=UTC))
    view = _view(candles={"BONK": candles}, quotes={"BONK": quote})
    positions = [_position("BONK", "crypto", qty=1000.0, asset_type=AssetType.CRYPTO)]
    (coin,) = holding_inputs(positions, [], view)
    assert (coin.price, coin.value_cad, coin.benchmark) == (candles[-1].close, 1800.0, None)
    closes = [c.close for c in candles if c.day >= OPENED]
    assert coin.trailing_stop == pytest.approx(trailing_stop(closes, candles[-1].close, atr_pct(candles), None, None))
    assert (coin.why_no_forecast, coin.risk_level, coin.max_position_pct) == ("no crypto model yet", "very_high", 0.5)
    (row,), _ = action_rows(positions, [coin], view)
    assert (row.action, row.reasons) == ("hold", ["no crypto model yet"])
    assert (row.feature_day, row.ref_price, row.bench_ref_price) == (DAY, candles[-1].close, None)
    assert (row.horizon_days, row.exit_by) == (None, None)

    # without a CAD quote the USD candle is converted at the latest rate
    (unquoted,) = holding_inputs(positions, [], replace(view, quotes={}))
    assert unquoted.value_cad == pytest.approx(candles[-1].close * 1000 * 1.4)


def test_a_held_coin_under_the_sell_line_is_sold_and_its_stop_uses_the_policy():
    row = PredictionRow("BONK", 7, -0.02, 0.01, 0.08, 0.40, "BTC", "v")
    candles = _candles("BONK")
    quote = CryptoQuote(symbol="BONK", coin_id="bonk", price_cad=1.8, updated_at=datetime(2026, 10, 14, tzinfo=UTC))
    view = _view(candles={"BONK": candles}, quotes={"BONK": quote}, coin_rows={"BONK": [row]}, coin_cost={"BONK": 0.001})
    positions = [_position("BONK", "crypto", qty=1000.0, asset_type=AssetType.CRYPTO)]
    (coin,) = holding_inputs(positions, [], view)
    assert coin.rows == [row] and coin.sane and coin.benchmark == "BTC" and coin.policy == DEFAULT_POLICY
    (action,), _ = action_rows(positions, [coin], view)
    assert action.action == "sell"
    wide = replace(DEFAULT_POLICY, trail_atr=5.0)
    looser = holding_inputs(positions, [], replace(view, coin_policy=wide))[0]
    assert looser.trailing_stop == pytest.approx(
        trailing_stop([c.close for c in candles if c.day >= OPENED], candles[-1].close, atr_pct(candles), None, None, wide)
    )
    assert looser.trailing_stop < coin.trailing_stop


def test_a_coin_without_candles_holds_without_a_stop():
    quote = CryptoQuote(symbol="WIF", coin_id="wif", price_cad=2.5, updated_at=datetime(2026, 10, 14, tzinfo=UTC))
    view = _view(quotes={"WIF": quote}, previous={("crypto", "WIF", "crypto"): (date(2026, 10, 12), 1.0)})
    positions = [_position("WIF", "crypto", qty=100.0, asset_type=AssetType.CRYPTO)]
    (coin,) = holding_inputs(positions, [], view)
    assert (coin.value_cad, coin.trailing_stop) == (250.0, None)
    (row,), _ = action_rows(positions, [coin], view)
    assert (row.action, row.trailing_stop, row.ref_price, row.feature_day) == ("hold", None, None, None)
    assert row.reasons == ["no crypto model yet, and no daily candles for a trailing stop"]


def test_one_stock_in_two_accounts_gets_two_rows():
    forecast, advice = _tsx({"RY.TO": [_row("RY.TO")]}, {"RY.TO": {}}, {"RY.TO": ("low", 5.0)})
    view = _view(forecasts={Market.TSX: forecast}, advice={Market.TSX: advice},
                 bars={**_view().bars, "RY.TO": _bars("RY.TO", [60.0])})
    positions = [_position("RY.TO", "tfsa"), _position("RY.TO", "rrsp", qty=5.0)]
    holdings = holding_inputs(positions, [], view)
    assert [h.value_cad for h in holdings] == [600.0, 300.0]
    assert holdings[0].rows == holdings[1].rows == [_row("RY.TO")]
    rows, _ = action_rows(positions, holdings, view)
    assert [(r.account, r.symbol) for r in rows] == [("tfsa", "RY.TO"), ("rrsp", "RY.TO")]


def test_the_review_window_is_five_sessions_and_includes_today_at_pre_close():
    fifth = sessions_after(Market.TSX, DAY, 5)
    assert fifth == date(2026, 10, 20)
    results = {
        "yfinance_earnings": CollectorResult("yfinance_earnings", CollectorStatus.OK, [
            EarningsReport(symbol="RY.TO", report_at=datetime(2026, 10, 13, 17, 0, tzinfo=ET)),  # the feature day
            EarningsReport(symbol="TD.TO", report_at=datetime(2026, 10, 21, 7, 0, tzinfo=ET)),  # the 6th session
        ], 0),
        "clinical_trials": CollectorResult("clinical_trials", CollectorStatus.OK, [
            TrialActivity(symbol="RY.TO", as_of=DAY, next_completion=fifth),
        ], 0),
    }
    bars = {**_view().bars, "RY.TO": _bars("RY.TO", [60.0]), "TD.TO": _bars("TD.TO", [20.0])}
    positions = [_position("RY.TO"), _position("TD.TO")]
    view = _view(scheduled=scheduled_events(results), bars=bars, flagged={"TD.TO": {DAY}})
    ry, td = holding_inputs(positions, [], view)
    assert ry.review == ["phase 2/3 trial completion on Oct 20"]
    assert td.review == ["the latest bar is a flagged, unconfirmed jump"]

    at_pre_close = replace(view, days={Market.TSX: (DAY, True), Market.US: (DAY, True)})
    ry, td = holding_inputs(positions, [], at_pre_close)
    assert ry.review == ["earnings on Oct 13", "phase 2/3 trial completion on Oct 20"]
    (row, _), _ = action_rows(positions, [ry, td], at_pre_close)
    assert row.review is True and row.reasons[-2:] == ry.review


def test_an_unconfirmed_coin_price_asks_for_review():
    view = _view(candles={"BONK": _candles("BONK")}, crypto_features={"BONK": {"unconfirmed_price": True}})
    (coin,) = holding_inputs([_position("BONK", "crypto", asset_type=AssetType.CRYPTO)], [], view)
    assert coin.review == ["the latest bar is a flagged, unconfirmed jump"]


def test_reversed_signals_need_most_of_the_picks_factors_flipped():
    then = [{"feature": "a", "contribution": 0.1}, {"feature": "b", "contribution": -0.2},
            {"feature": "c", "contribution": 0.3}, {"feature": "d", "contribution": 0.0}]  # d says nothing

    def now(**c: float) -> list[dict]:
        return [{"feature": f, "contribution": v} for f, v in ({"a": 0.1, "b": -0.2, "c": 0.3, "d": 0.5} | c).items()]

    assert signals_reversed(then, now(a=-0.1, b=0.05)) is True  # 2 of 3
    assert signals_reversed(then, now(a=-0.1)) is False  # 1 of 3
    assert signals_reversed([{"feature": "d", "contribution": 0.0}], now()) is None  # nothing to compare


def test_a_linked_pick_sets_the_floor_the_reversal_and_a_later_exit_by():
    forecast, advice = _tsx({"RY.TO": [_row("RY.TO", 63)]}, {"RY.TO": {"atr_14_pct": 0.5}}, {"RY.TO": ("low", 5.0)})
    factors = [{"feature": "ret_21", "contribution": 0.2}, {"feature": "rsi_14", "contribution": 0.1}]
    pick = LinkedPick(id=7, horizon_days=63, exit_by=date(2027, 2, 1), stop=55.0, status="open", top_factors=factors)
    asked = []

    def explain(market, symbol, h):
        asked.append((market, symbol, h))
        return [{"feature": "ret_21", "contribution": -0.1}, {"feature": "rsi_14", "contribution": -0.3}]

    view = _view(forecasts={Market.TSX: forecast}, advice={Market.TSX: advice}, picks={7: pick}, explain=explain,
                 bars={**_view().bars, "RY.TO": _bars("RY.TO", [60.0])})
    positions = [_position("RY.TO", pick_id=7)]
    (h,) = holding_inputs(positions, [], view)
    assert asked == [(Market.TSX, "RY.TO", 63)]
    assert h.signals_reversed is True
    assert h.trailing_stop == 55.0  # the ATR stop (60 - 75) is under the pick's own
    (row,), _ = action_rows(positions, [h], view)
    assert row.action == "sell"
    assert row.exit_by == date(2027, 2, 1)  # the open pick's, later than 63 sessions after the feature day

    # a pick whose horizon isn't forecast this run can't be checked
    other = replace(view, picks={7: replace(pick, horizon_days=10)})
    (h,) = holding_inputs(positions, [], other)
    assert h.signals_reversed is None


def test_a_stop_from_before_the_position_opened_is_ignored():
    view = _view(bars={**_view().bars, "RY.TO": _bars("RY.TO", [60.0] * 20)},
                 previous={("tfsa", "RY.TO", "stock"): (date(2026, 8, 31), 59.0)})
    (h,) = holding_inputs([_position("RY.TO")], [], view)
    assert h.trailing_stop == 60.0  # flat bars: no ATR, so the last close
    kept = replace(view, previous={("tfsa", "RY.TO", "stock"): (date(2026, 10, 9), 61.0)})
    (h,) = holding_inputs([_position("RY.TO")], [], kept)
    assert h.trailing_stop == 61.0


def test_a_taxable_loss_in_the_last_30_days_is_remembered_across_accounts():
    view = _view(bars={**_view().bars, "AAA": _bars("AAA", [10.0])})
    losses = [
        Loss("non_registered", "AAA", AssetType.STOCK, date(2026, 9, 10)),
        Loss("non_registered", "AAA", AssetType.STOCK, date(2026, 9, 20)),
        Loss("tfsa", "AAA", AssetType.STOCK, date(2026, 10, 1)),  # not taxable
        Loss("non_registered", "BBB", AssetType.STOCK, date(2026, 10, 1)),
    ]
    (h,) = holding_inputs([_position("AAA")], losses, view)
    assert h.sold_at_loss_on == date(2026, 9, 20)
    (h,) = holding_inputs([_position("AAA")], losses[:1], view)
    assert h.sold_at_loss_on is None  # 34 days ago


def _ry_view(closes: list[float], **kw) -> RunView:
    """RY.TO with a forecast whose ATR is 4%, so its stop is the high less 10% of the last close."""
    forecast, advice = _tsx({"RY.TO": [_row("RY.TO")]}, {"RY.TO": {}}, {"RY.TO": ("low", 5.0)})
    return _view(forecasts={Market.TSX: forecast}, advice={Market.TSX: advice},
                 bars={**_view().bars, "RY.TO": _bars("RY.TO", closes)}, **kw)


def test_a_close_from_before_the_position_opened_doesnt_set_the_high():
    closes = [100.0] + [60.0] * 49  # 50 bars back from Oct 13: the 100 is Aug 25, before Sep 1
    (h,) = holding_inputs([_position("RY.TO")], [], _ry_view(closes))
    assert h.trailing_stop == pytest.approx(60 - 2.5 * 0.04 * 60)


def test_a_flagged_close_doesnt_raise_the_stop():
    view = _ry_view([50.0, 80.0, 60.0], flagged={"RY.TO": {DAY - timedelta(days=1)}})  # the 80 is unconfirmed
    (h,) = holding_inputs([_position("RY.TO")], [], view)
    assert h.trailing_stop == pytest.approx(60 - 2.5 * 0.04 * 60)  # not 80 - 6


def test_an_unconfirmed_coin_candle_doesnt_raise_the_stop():
    candles = _candles("BONK")  # rising: the latest close is the high
    view = _view(candles={"BONK": candles}, crypto_features={"BONK": {"unconfirmed_price": True}})
    (coin,) = holding_inputs([_position("BONK", "crypto", asset_type=AssetType.CRYPTO)], [], view)
    closes = [c.close for c in candles[:-1]]
    expected = trailing_stop(closes, candles[-1].close, atr_pct(candles), None, None)
    assert coin.trailing_stop == pytest.approx(expected)
    assert max(closes) < candles[-1].close


def test_a_graded_picks_stop_isnt_a_floor():
    pick = LinkedPick(id=7, horizon_days=63, exit_by=date(2026, 9, 30), stop=70.0, status="graded", top_factors=[])
    view = _ry_view([60.0], picks={7: pick})
    (h,) = holding_inputs([_position("RY.TO", pick_id=7)], [], view)
    assert h.trailing_stop == pytest.approx(60 - 2.5 * 0.04 * 60)  # not the graded pick's stale 70
    (h,) = holding_inputs([_position("RY.TO", pick_id=7)], [], replace(view, picks={7: replace(pick, status="open")}))
    assert h.trailing_stop == 70.0


# --- the exit plan ---------------------------------------------------------------------------------


def _wave(symbol: str, n: int, base: float, step: int = 7, end: date = DAY) -> list[DailyBar]:
    """n daily bars ending `end`, with a wiggle (its pattern set by `step`) so the moves are not all alike."""
    return [
        bar(symbol, end - timedelta(days=n - 1 - i), base * (1 + 0.01 * ((i * step) % 5 - 2) + 0.001 * i))
        for i in range(n)
    ]


def _plan_view(symbol: str = "RY.TO", n: int = 120, **kw) -> RunView:
    """A TSX stock with a forecast, and n closes for it and for XIU.TO."""
    forecast, advice = _tsx({symbol: [_row(symbol, 21)]}, {symbol: {}}, {symbol: ("low", 5.0)})
    bars = {**_view().bars, "XIU.TO": _wave("XIU.TO", n, 40.0, step=3), symbol: _wave(symbol, n, 60.0)}
    return _view(forecasts={Market.TSX: forecast}, advice={Market.TSX: advice}, bars=bars, **kw)


def _rows(view: RunView, positions: list[Position]):
    return action_rows(positions, holding_inputs(positions, [], view), view)


def test_a_holding_with_a_forecast_gets_a_forecast_plan_rechecked_at_its_horizon():
    (row,), reasons = _rows(_plan_view(), [_position("RY.TO")])
    assert reasons == {}
    assert row.exit_plan["basis"] == "forecast"
    assert row.exit_plan["horizon"] == row.horizon_days == 21
    assert row.exit_plan["recheck_by"] == sessions_after(Market.TSX, DAY, 21).isoformat()
    assert row.exit_plan["recheck_by"] == row.exit_by.isoformat()


def test_a_pick_linked_holding_rechecks_at_its_own_horizon_not_the_picks_later_exit_by():
    pick = LinkedPick(id=7, horizon_days=21, exit_by=date(2027, 2, 1), stop=1.0, status="open", top_factors=[])
    (row,), _ = _rows(_plan_view(picks={7: pick}), [_position("RY.TO", pick_id=7)])
    assert row.exit_by == pick.exit_by
    assert row.exit_plan["recheck_by"] == sessions_after(Market.TSX, DAY, 21).isoformat()
    assert row.exit_plan["recheck_by"] < row.exit_by.isoformat()


def test_a_forecast_without_benchmark_bars_falls_back_to_volatility_rechecked_in_21_sessions():
    view = _plan_view()
    view = replace(view, bars={k: v for k, v in view.bars.items() if k != "XIU.TO"})
    (row,), reasons = _rows(view, [_position("RY.TO")])
    assert reasons == {}
    assert row.exit_plan["basis"] == "volatility"
    assert row.exit_plan["horizon"] == 21
    assert row.exit_plan["recheck_by"] == sessions_after(Market.TSX, DAY, 21).isoformat()


def test_a_coin_gets_a_volatility_plan_rechecked_in_21_calendar_days_even_with_model_rows():
    coin_row = PredictionRow("BONK", 7, -0.02, 0.03, 0.08, 0.60, "BTC", "v")
    quote = CryptoQuote(symbol="BONK", coin_id="bonk", price_cad=1.8, updated_at=datetime(2026, 10, 14, tzinfo=UTC))
    view = _view(
        candles={"BONK": _candles("BONK", n=120)}, quotes={"BONK": quote}, coin_rows={"BONK": [coin_row]},
        coin_cost={"BONK": 0.001},
        bars={**_view().bars, "BTC": _wave("BTC", 120, 100.0, 3), "SPY": _wave("SPY", 120, 600.0, 3)},
    )
    positions = [_position("BONK", "crypto", qty=1000.0, asset_type=AssetType.CRYPTO)]
    (row,), reasons = _rows(view, positions)
    assert reasons == {}
    plan = row.exit_plan
    assert (plan["basis"], plan["drift"], plan["horizon"]) == ("volatility", None, 21)
    assert plan["recheck_by"] == (DAY + timedelta(days=21)).isoformat()


def test_a_holding_with_too_little_history_has_no_plan_and_a_reason_while_the_others_keep_theirs():
    view = _plan_view()
    forecast, advice = _tsx(
        {"NEW": [_row("NEW", 21)], "RY.TO": [_row("RY.TO", 21)]}, {"NEW": {}, "RY.TO": {}},
        {"NEW": ("low", 5.0), "RY.TO": ("low", 5.0)},
    )
    view = replace(view, forecasts={Market.TSX: forecast}, advice={Market.TSX: advice},
                   bars={**view.bars, "NEW": _wave("NEW", 10, 5.0)})
    rows, reasons = _rows(view, [_position("NEW", "tfsa"), _position("RY.TO", "rrsp")])
    assert rows[0].exit_plan is None
    assert reasons == {"tfsa:NEW": "too little price history"}
    assert rows[1].exit_plan["basis"] == "forecast"


def test_an_unpriced_holding_has_no_plan_and_the_reason_no_price():
    view = _plan_view()
    (row,), reasons = _rows(view, [_position("ZZ.TO")])  # no bars at all: not priced, no feature day
    assert row.exit_plan is None and reasons == {"tfsa:ZZ.TO": "no price"}
    # a holding whose price is NaN gets the same reason through build_plan
    (h,) = holding_inputs([_position("RY.TO")], [], view)
    (row,), reasons = action_rows([_position("RY.TO")], [replace(h, price=math.nan)], view)
    assert row.exit_plan is None and reasons == {"tfsa:RY.TO": "no price"}


def test_a_holding_under_water_gets_its_break_even_price():
    view = _plan_view()
    positions = [_position("RY.TO")]
    (h,) = holding_inputs(positions, [], view)
    under = replace(h, cost_cad=1000.0, value_cad=800.0, price=4.0)
    (row,), reasons = action_rows(positions, [under], view)
    assert reasons == {}
    assert row.exit_plan["breakeven"] == pytest.approx(5.0)
    assert row.exit_plan["cost_price"] == pytest.approx(5.0)


def _bare(symbol: str, asset_type: AssetType = AssetType.STOCK, cost: float = 0.0) -> Holding:
    return Holding(
        "tfsa", symbol, asset_type, None, 10.0, 100.0, 100.0, 1000.0, None, [], None, cost, False, "low", 5.0,
        None, None, [], None,
    )


def test_the_plan_cost_matches_the_benchmark_checks_cost():
    view = _view(fees=(1.5, 1.0))
    assert _plan_cost(_bare("AAPL"), view) == pytest.approx(0.033)  # 0.003 spread + 2 x 1.5%
    assert _plan_cost(_bare("RY.TO"), view) == pytest.approx(0.003)
    coin = _bare("BONK", AssetType.CRYPTO)
    assert _plan_cost(coin, view) == pytest.approx(0.023)  # 0.003 + 2 x 1.0%
    assert _plan_cost(coin, replace(view, coin_cost={"BONK": 0.0042})) == pytest.approx(0.0042)
    assert _plan_cost(_bare("AAPL", cost=0.0123), view) == 0.0123


def test_a_stocks_plan_cost_reads_its_dollar_volume_from_the_features():
    forecast, _ = _tsx({"AAPL": [_row("AAPL")]}, {"AAPL": {"dollar_volume_20": 5e9}}, {"AAPL": ("low", 5.0)})
    view = _view(fees=(1.5, 1.0), forecasts={Market.US: forecast})
    assert _plan_cost(_bare("AAPL"), view) == pytest.approx(0.001 + 0.03)  # the large-company spread


def test_decide_is_unchanged_by_the_plan():
    view = _plan_view()
    positions = [_position("RY.TO")]
    (h,) = holding_inputs(positions, [], view)
    expected = decide(h)
    (row,), _ = action_rows(positions, [h], view)
    assert (row.action, row.review, row.reasons, row.warnings) == (
        expected.action, expected.review, expected.reasons, expected.warnings,
    )
    assert (row.horizon_days, row.exit_by, row.q10, row.q50, row.q90) == (
        expected.horizon, sessions_after(Market.TSX, DAY, 21), expected.q10, expected.q50, expected.q90,
    )
    assert row.action == "hold" and row.exit_plan is not None


def test_the_plan_trails_the_stop_with_the_holdings_own_atr_and_policy(monkeypatch):
    # R12: the live plan gets the ATR `_stop` used (the model's 4% here) and the policy's trail_atr,
    # so its stop-first chance is simulated with the stop trailing, not held fixed
    from advisor.portfolio import stage

    seen = []

    def spy(**kwargs):
        seen.append(kwargs)
        return build_plan(**kwargs)

    monkeypatch.setattr(stage, "build_plan", spy)
    policy = replace(DEFAULT_POLICY, trail_atr=1.5)
    view = _plan_view()
    positions = [_position("RY.TO")]
    (row,), reasons = action_rows(positions, holding_inputs(positions, [], view, {Market.TSX: policy}), view)
    assert reasons == {}
    (kw,) = seen
    assert (kw["atr_pct"], kw["trail_atr"]) == (0.04, 1.5)
    assert kw["stop"] == pytest.approx(row.trailing_stop)
    plan = row.exit_plan
    assert plan["sell_at"] is not None and plan["p_stop_first"] is not None
    fixed = build_plan(**{**kw, "atr_pct": None, "trail_atr": None})
    assert plan["p_stop_first"] > fixed["p_stop_first"]


def test_a_coins_plan_trails_with_the_atr_of_its_candles(monkeypatch):
    from advisor.portfolio import stage

    seen = []
    monkeypatch.setattr(stage, "build_plan", lambda **kw: seen.append(kw) or build_plan(**kw))
    candles = _candles("BONK", n=120)
    quote = CryptoQuote(symbol="BONK", coin_id="bonk", price_cad=1.8, updated_at=datetime(2026, 10, 14, tzinfo=UTC))
    view = _view(candles={"BONK": candles}, quotes={"BONK": quote})
    positions = [_position("BONK", "crypto", qty=1000.0, asset_type=AssetType.CRYPTO)]
    _rows(view, positions)
    (kw,) = seen
    assert kw["atr_pct"] == pytest.approx(atr_pct(candles)) and kw["trail_atr"] == DEFAULT_POLICY.trail_atr


def test_a_holding_without_an_atr_gets_a_fixed_stop_plan(monkeypatch):
    from advisor.portfolio import stage

    seen = []
    monkeypatch.setattr(stage, "build_plan", lambda **kw: seen.append(kw) or build_plan(**kw))
    view = _view(candles={"BONK": _candles("BONK", n=10)})  # too few candles for an ATR
    _rows(view, [_position("BONK", "crypto", qty=1000.0, asset_type=AssetType.CRYPTO)])
    (kw,) = seen
    assert kw["atr_pct"] is None


# --- the benchmark check's verdict ---------------------------------------------------------------


def _verdict(result: str = "pass") -> dict:
    checks = {"range": True, "touch": True, "value": True, "breakeven": True, "stop_first": True}
    return {"pairs": 500, "touch_rate": 0.31, "checks": checks, "result": result}


def _check(model: str = "factors", **classes: dict) -> dict:
    return {"plan_version": PLAN_VERSION, "model": model, "classes": classes, "seconds": 2.0}


def test_a_holdings_stored_plan_carries_the_checks_status():
    view = _plan_view(exit_check={"TSX": _check(forecast=_verdict())}, model_names={Market.TSX: "factors"})
    (row,), reasons = _rows(view, [_position("RY.TO")])
    assert reasons == {}
    built = _rows(_plan_view(), [_position("RY.TO")])[0][0].exit_plan
    assert built["status"] == "unvalidated"  # no check read at all
    assert built["sell_at"] is not None
    assert row.exit_plan == {**built, "status": "pass", "p_touch": 0.31}


def test_a_forecast_plan_checked_on_another_model_is_unvalidated():
    view = _plan_view(exit_check={"TSX": _check(forecast=_verdict())}, model_names={Market.TSX: "baseline"})
    (row,), _ = _rows(view, [_position("RY.TO")])
    assert row.exit_plan["status"] == "unvalidated" and row.exit_plan["p_touch"] != 0.31
    view = _plan_view(exit_check={"TSX": _check(forecast=_verdict())})  # the market's model name is unknown
    (row,), _ = _rows(view, [_position("RY.TO")])
    assert row.exit_plan["status"] == "unvalidated"


def test_a_stocks_plan_reads_its_own_markets_check():
    view = _plan_view(exit_check={"US": _check(forecast=_verdict())}, model_names={Market.TSX: "factors"})
    (row,), _ = _rows(view, [_position("RY.TO")])
    assert row.exit_plan["status"] == "unvalidated"


def test_a_coins_plan_reads_the_crypto_checks_coin_verdict_whatever_the_model():
    quote = CryptoQuote(symbol="BONK", coin_id="bonk", price_cad=1.8, updated_at=datetime(2026, 10, 14, tzinfo=UTC))
    positions = [_position("BONK", "crypto", qty=1000.0, asset_type=AssetType.CRYPTO)]
    base = _view(candles={"BONK": _candles("BONK", n=120)}, quotes={"BONK": quote})
    crypto = _check("baseline", coin=_verdict("range_only"), volatility=_verdict())
    (row,), reasons = _rows(replace(base, exit_check={"crypto": crypto}), positions)
    assert reasons == {}
    assert row.exit_plan["status"] == "range_only" and row.exit_plan["sell_at"] is None
    (row,), _ = _rows(replace(base, exit_check={"crypto": _check("baseline", volatility=_verdict())}), positions)
    assert row.exit_plan["status"] == "unvalidated"  # a coin never reads the stocks' volatility verdict


def test_a_verdict_that_breaks_the_matching_leaves_the_plan_unvalidated(monkeypatch):
    from advisor.portfolio import stage

    def broken(plan, check, **kw):
        raise RuntimeError("verdict broke")

    monkeypatch.setattr(stage, "apply_verdict", broken)
    view = _plan_view(exit_check={"TSX": _check(forecast=_verdict())}, model_names={Market.TSX: "factors"})
    (row,), reasons = _rows(view, [_position("RY.TO")])
    assert reasons == {} and row.exit_plan["status"] == "unvalidated" and row.exit_plan["sell_at"] is not None


class _Conn:
    def transaction(self):
        return contextlib.nullcontext()


def _advise(monkeypatch, latest_exit_check, configs: dict) -> tuple[dict, list]:
    """advise_stage on one TSX holding with a forecast, every read of the database faked."""
    from advisor.portfolio import stage
    from advisor.store import repo

    view = _plan_view()
    written = []
    position = _position("RY.TO")
    ledger = SimpleNamespace(positions=[position], losses=[], problems=[])
    monkeypatch.setattr(stage, "build_ledger", lambda trades, rates: ledger)
    for name, value in {
        "load_trades": [], "load_fx_rates": {}, "latest_fx_rate": 1.4, "previous_trailing_stops": {},
        "load_picks": {}, "fee_settings": (0.0, 0.0),
    }.items():
        monkeypatch.setattr(repo, name, lambda *a, value=value, **k: value)
    monkeypatch.setattr(repo, "latest_exit_check", latest_exit_check)
    monkeypatch.setattr(repo, "write_holding_actions", lambda conn, run_id, rows: written.extend(rows))
    models = {
        m: MarketModel(active=None, sectors=pd.DataFrame(), metrics={"config": config}) for m, config in configs.items()
    }
    summary = advise_stage(
        _Conn(), 1, models=models, forecasts=view.forecasts, advice=view.advice, model_summary={},
        bars=view.bars, flagged={}, quotes={}, candles={}, crypto_features={}, results={},
        kind=RunKind.PRE_OPEN, now_utc=datetime(2026, 10, 14, 12, 15, tzinfo=UTC),
    )
    return summary, written


def test_the_stage_matches_the_check_on_the_live_models_name_without_its_policy(monkeypatch):
    stored = replace(BASELINE, policy=DEFAULT_POLICY).to_json()  # the live config carries a policy
    summary, (row,) = _advise(monkeypatch, lambda conn: {"TSX": _check("baseline", forecast=_verdict())},
                              {Market.TSX: stored})
    assert summary["written"] == 1
    assert row.exit_plan["status"] == "pass"


@pytest.mark.parametrize("config", [None, {"version": 999}, "odd"])
def test_a_market_whose_stored_config_cannot_be_read_has_unvalidated_forecast_plans(monkeypatch, config):
    summary, (row,) = _advise(monkeypatch, lambda conn: {"TSX": _check("baseline", forecast=_verdict())},
                              {Market.TSX: config})
    assert summary["written"] == 1
    assert row.exit_plan["status"] == "unvalidated"


def test_a_failed_read_of_the_check_leaves_every_plan_unvalidated_and_the_stage_succeeds(monkeypatch):
    def broken(conn):
        raise psycopg.OperationalError("the check broke")

    summary, (row,) = _advise(monkeypatch, broken, {Market.TSX: BASELINE.to_json()})
    assert "failed" not in summary and summary["written"] == 1
    assert row.exit_plan is not None and row.exit_plan["status"] == "unvalidated"
