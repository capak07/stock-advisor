from dataclasses import replace

import pytest

from advisor.models import AssetType, PredictionRow
from advisor.policy import DEFAULT_POLICY
from advisor.recommend.verdicts import TSX_BASIS, coin_verdict, stock_verdict


def row(h, p, q50=0.04):
    return PredictionRow("AAA", h, q50 - 0.05, q50, q50 + 0.06, p, "SPY", "v1")


def test_a_higher_sell_line_avoids_a_stock_the_default_holds():
    held = stock_verdict("AAA", [row(63, 0.45)], 0.001, True, None, None)
    avoided = stock_verdict(
        "AAA", [row(63, 0.45)], 0.001, True, None, None, policy=replace(DEFAULT_POLICY, p_sell=0.46)
    )
    assert held.verdict == "hold" and avoided.verdict == "avoid"


def test_a_tsx_buy_ends_with_the_filings_note_and_a_us_buy_does_not():
    tsx = stock_verdict("RY.TO", [row(63, 0.62)], 0.001, True, {"stop": 40.0}, None)
    us = stock_verdict("AAA", [row(63, 0.62)], 0.001, True, {"stop": 94.0}, None)
    assert tsx.reasons[-1] == TSX_BASIS and tsx.details["basis"] == TSX_BASIS
    assert TSX_BASIS not in us.reasons and "basis" not in us.details


def test_a_qualifying_watched_stock_is_a_buy_with_the_picks_fields():
    v = stock_verdict("AAA", [row(63, 0.62)], 0.031, True, {"stop": 94.0, "risk_level": "medium"}, None)
    assert v.verdict == "buy" and v.details == {"stop": 94.0, "risk_level": "medium"}
    assert v.reasons[0] == "P(beat SPY) 0.62 over 63 trading days"


def test_a_buy_explains_the_expected_return_against_costs():
    v = stock_verdict("AAA", [row(63, 0.62)], 0.031, True, {}, None)
    assert v.reasons[1] == "expected 4.0% against 3.1% round-trip costs"
    assert (v.symbol, v.asset_type) == ("AAA", "stock")


def test_low_odds_at_the_best_ratio_horizon_is_avoid():
    # equal ratios: the tie goes to the shorter horizon, as for a holding
    v = stock_verdict("AAA", [row(21, 0.40), row(63, 0.42)], 0.001, True, None, None)
    assert (v.verdict, v.reasons) == ("avoid", ["P(beat SPY) 0.40 over 21 trading days"])


def test_the_best_ratio_horizon_decides_avoid_not_the_other_horizons():
    worse_elsewhere = stock_verdict("AAA", [row(21, 0.40, q50=0.02), row(63, 0.50, q50=0.06)], 0.001, True, None, None)
    better_elsewhere = stock_verdict("AAA", [row(21, 0.40, q50=0.06), row(63, 0.50, q50=0.02)], 0.001, True, None, None)
    assert worse_elsewhere.verdict == "hold"
    assert better_elsewhere.verdict == "avoid"  # 63 is above the line, but 21 is the horizon a holding is judged at


def test_odds_just_above_the_avoid_line_at_the_best_ratio_horizon_is_not_avoid():
    v = stock_verdict("AAA", [row(21, 0.43), row(63, 0.40)], 0.001, True, None, None)
    assert v.verdict == "hold"


def test_no_horizon_with_a_range_is_never_avoid():
    flat = PredictionRow("AAA", 21, 0.01, 0.01, 0.01, 0.30, "SPY", "v1")
    assert stock_verdict("AAA", [flat], 0.001, True, None, None).verdict == "hold"


@pytest.mark.parametrize(
    "rows",
    [
        [row(21, 0.40), row(63, 0.42)],
        [row(21, 0.40, q50=0.06), row(63, 0.50, q50=0.02)],
        [row(21, 0.40, q50=0.02), row(63, 0.50, q50=0.06)],
        [row(21, 0.43), row(63, 0.40)],
        [row(10, 0.42)],
        [row(10, 0.4201)],
        [row(63, 0.62)],
        [PredictionRow("AAA", 21, 0.01, 0.01, 0.01, 0.30, "SPY", "v1")],
    ],
)
def test_a_watched_stock_is_avoid_exactly_when_holding_it_would_be_a_forecast_sell(rows):
    from advisor.portfolio.actions import Holding, decide

    holding = Holding(
        account="tfsa", symbol="AAA", asset_type=AssetType.STOCK, benchmark="SPY", price=100.0,
        value_cad=1000.0, cost_cad=1000.0, portfolio_cad=100_000.0, trailing_stop=None, rows=rows,
        why_no_forecast=None, cost=0.001, sane=True, risk_level="medium", max_position_pct=5.0,
        momentum_pct=70.0, signals_reversed=None, review=[], sold_at_loss_on=None,
    )
    verdict = stock_verdict("AAA", rows, 0.001, True, None, None)
    assert (verdict.verdict == "avoid") == (decide(holding).action == "sell")
    assert (verdict.verdict == "buy") == (decide(holding).action == "add")


def test_anything_else_is_hold():
    v = stock_verdict("AAA", [row(21, 0.40), row(63, 0.55, q50=0.06)], 0.001, True, None, None)
    assert v.verdict == "hold" and v.details["horizon"] == 63  # 63 has the better q50/(q90 - q10)


def test_hold_details_describe_the_best_ratio_horizon_forecast():
    v = stock_verdict("AAA", [row(21, 0.50), row(63, 0.55, q50=0.06)], 0.001, True, None, None)
    assert v.details == {"horizon": 63, "p_beat": 0.55, "q10": 0.06 - 0.05, "q50": 0.06, "q90": 0.06 + 0.06}


def test_hold_gives_the_first_failing_check():
    low_p = stock_verdict("AAA", [row(63, 0.55)], 0.001, True, None, None)
    assert low_p.reasons == ["doesn't qualify as a buy", "P(beat SPY) 0.55 is under 0.58 at every horizon"]
    costly = stock_verdict("AAA", [row(63, 0.62)], 0.05, True, None, None)
    assert costly.reasons[0] == "doesn't qualify as a buy"
    assert "does not clear" in costly.reasons[1]
    unsane = stock_verdict("AAA", [row(63, 0.62)], 0.001, False, None, None)
    assert unsane.verdict == "hold" and "sanity" in unsane.reasons[1]


def test_a_watched_stock_without_a_forecast_is_hold_with_the_reason():
    v = stock_verdict("AAA", [], 0.001, True, None, "not eligible for the model (under $1, thin trading or new)")
    assert (v.verdict, v.reasons) == ("hold", ["not eligible for the model (under $1, thin trading or new)"])


def test_a_watched_coin_waits_for_the_crypto_model():
    v = coin_verdict("ETH")
    assert v.reasons == ["no crypto model yet"] and v.verdict == "hold" and v.asset_type == "crypto"


def test_a_watched_coin_with_a_forecast_is_bought_or_avoided_and_is_not_a_pick():
    buy = coin_verdict("ETH", [row(7, 0.70)], 0.001, DEFAULT_POLICY)
    avoid = coin_verdict("ETH", [row(7, 0.40)], 0.001, DEFAULT_POLICY)
    assert buy.verdict == "buy" and buy.asset_type == "crypto" and "rank" not in buy.details
    assert avoid.verdict == "avoid"


def test_a_coin_the_model_could_not_forecast_says_why():
    from advisor.recommend.verdicts import NO_COIN_MODEL, coin_verdict
    assert coin_verdict("NEW").reasons == [NO_COIN_MODEL]
    assert coin_verdict("NEW", why="only 120 days of history (needs 252)").reasons == ["only 120 days of history (needs 252)"]
