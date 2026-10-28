from dataclasses import replace

from advisor.models import PredictionRow
from advisor.policy import DEFAULT_POLICY
from advisor.recommend.verdicts import coin_verdict, stock_verdict


def row(h, p, q50=0.04):
    return PredictionRow("AAA", h, q50 - 0.05, q50, q50 + 0.06, p, "SPY", "v1")


def test_a_higher_sell_line_avoids_a_stock_the_default_holds():
    held = stock_verdict("AAA", [row(63, 0.45)], 0.001, True, None, None)
    avoided = stock_verdict(
        "AAA", [row(63, 0.45)], 0.001, True, None, None, policy=replace(DEFAULT_POLICY, p_sell=0.46)
    )
    assert held.verdict == "hold" and avoided.verdict == "avoid"


def test_a_qualifying_watched_stock_is_a_buy_with_the_picks_fields():
    v = stock_verdict("AAA", [row(63, 0.62)], 0.031, True, {"stop": 94.0, "risk_level": "medium"}, None)
    assert v.verdict == "buy" and v.details == {"stop": 94.0, "risk_level": "medium"}
    assert v.reasons[0] == "P(beat SPY) 0.62 over 63 trading days"


def test_a_buy_explains_the_expected_return_against_costs():
    v = stock_verdict("AAA", [row(63, 0.62)], 0.031, True, {}, None)
    assert v.reasons[1] == "expected 4.0% against 3.1% round-trip costs"
    assert (v.symbol, v.asset_type) == ("AAA", "stock")


def test_low_odds_at_every_horizon_is_avoid():
    v = stock_verdict("AAA", [row(21, 0.40), row(63, 0.42)], 0.001, True, None, None)
    assert (v.verdict, v.reasons) == ("avoid", ["P(beat SPY) at most 0.42 at every horizon"])


def test_odds_just_above_the_avoid_line_at_one_horizon_is_not_avoid():
    v = stock_verdict("AAA", [row(21, 0.40), row(63, 0.43)], 0.001, True, None, None)
    assert v.verdict == "hold"


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
