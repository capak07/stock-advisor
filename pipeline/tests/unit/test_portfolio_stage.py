from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pandas as pd
import pytest

from advisor.collectors.base import CollectorResult, CollectorStatus
from advisor.collectors.clinical_trials import TrialActivity
from advisor.collectors.coingecko import CryptoQuote
from advisor.collectors.yfinance_earnings import EarningsReport
from advisor.model.market_run import Forecast
from advisor.models import ET, AssetType, DailyBar, LinkedPick, Market, PredictionRow
from advisor.policy import DEFAULT_POLICY
from advisor.portfolio.ledger import Loss, Position
from advisor.portfolio.stage import RunView, action_rows, holding_inputs, signals_reversed
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
    (row,) = action_rows(positions, holding_inputs(positions, [], view), view)
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
    rows = action_rows(positions, [ineligible, failed, unpriced], view)
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
    (row,) = action_rows(positions, [coin], view)
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
    (action,) = action_rows(positions, [coin], view)
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
    (row,) = action_rows(positions, [coin], view)
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
    rows = action_rows(positions, holdings, view)
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
    row, _ = action_rows(positions, [ry, td], at_pre_close)
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
    (row,) = action_rows(positions, [h], view)
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
