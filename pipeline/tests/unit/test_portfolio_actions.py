from dataclasses import replace
from datetime import date

from advisor.models import AssetType, PredictionRow
from advisor.policy import DEFAULT_POLICY
from advisor.portfolio.actions import Holding, decide


def _row(h: int = 10, p: float = 0.5, q10: float = -0.05, q50: float = 0.01, q90: float = 0.07) -> PredictionRow:
    return PredictionRow("AAA", h, q10, q50, q90, p, "SPY", "v1")


def _holding(**kw) -> Holding:
    base = Holding(
        account="tfsa",
        symbol="AAA",
        asset_type=AssetType.STOCK,
        benchmark="SPY",
        price=100.0,
        value_cad=1000.0,
        cost_cad=1000.0,
        portfolio_cad=100_000.0,
        trailing_stop=90.0,
        rows=[_row()],
        why_no_forecast=None,
        cost=0.005,
        sane=True,
        risk_level="medium",
        max_position_pct=5.0,
        momentum_pct=70.0,
        signals_reversed=None,
        review=[],
        sold_at_loss_on=None,
    )
    return replace(base, **kw)


# choose's own boundary row: p 0.58, q50 just over cost
_BUY_ROW = _row(p=0.58, q50=0.0051)


def test_a_held_coin_under_the_sell_line_is_sold():
    coin = _holding(
        symbol="ETH", asset_type=AssetType.CRYPTO, benchmark="BTC",
        rows=[_row(h=7, p=0.40)], sane=True,
    )
    assert decide(coin).action == "sell"


def test_a_higher_sell_line_sells_a_forecast_the_default_holds():
    held = decide(_holding(rows=[_row(p=0.45)]))
    sold = decide(_holding(rows=[_row(p=0.45)], policy=replace(DEFAULT_POLICY, p_sell=0.46)))
    assert held.action == "hold" and sold.action == "sell"


def test_a_hit_trailing_stop_sells_whatever_the_forecast():
    a = decide(_holding(price=90.0, rows=[_BUY_ROW]))
    assert a.action == "sell"
    assert a.reasons == ["closed at 90.00, under its trailing stop 90.00"]
    assert decide(_holding(price=90.01, rows=[_BUY_ROW])).action != "sell"


def test_stop_prices_under_one_use_four_significant_figures():
    a = decide(_holding(price=0.5, trailing_stop=0.512345, rows=[]))
    assert a.reasons == ["closed at 0.5000, under its trailing stop 0.5123"]


def test_a_best_horizon_at_or_under_0_42_sells():
    a = decide(_holding(rows=[_row(p=0.42)]))
    assert a.action == "sell"
    assert a.reasons == ["P(beat SPY) 0.42 over 10 trading days"]
    assert decide(_holding(rows=[_row(p=0.43)])).action == "hold"


def test_reversed_pick_signals_sell():
    a = decide(_holding(signals_reversed=True))
    assert a.action == "sell"
    assert a.reasons == ["the signals behind its pick have reversed"]
    assert decide(_holding(signals_reversed=False)).action == "hold"


def test_a_big_gain_with_fading_momentum_trims():
    a = decide(_holding(value_cad=1250.0, momentum_pct=39.9))
    assert a.action == "trim"
    assert a.reasons == ["up 25% and its 21-day momentum is at the 39th percentile"]
    assert decide(_holding(value_cad=1249.0, momentum_pct=39.9)).action == "hold"
    assert decide(_holding(value_cad=1250.0, momentum_pct=40.0)).action == "hold"
    assert decide(_holding(value_cad=1250.0, momentum_pct=None)).action == "hold"


def test_oversize_is_a_warning_never_a_trim():
    big = _holding(value_cad=36_000.0, cost_cad=36_000.0, max_position_pct=1.5, risk_level="high")
    a = decide(big)
    assert a.action == "hold"
    assert a.warnings == ["36% of the portfolio; High risk allows 1.5%"]
    still = decide(replace(big, rows=[_BUY_ROW]))
    assert still.action == "hold"
    assert len(still.warnings) == 1


def test_a_qualifying_holding_below_its_max_adds():
    a = decide(_holding(rows=[_BUY_ROW]))
    assert a.action == "add"
    assert a.reasons == ["would be a Buy today: P(beat SPY) 0.58 over 10 trading days, below its max size"]
    assert (a.horizon, a.q10, a.q50, a.q90) == (10, -0.05, 0.0051, 0.07)
    assert a.warnings == []


def test_sell_trim_and_hold_carry_the_best_horizon_range():
    a = decide(_holding(rows=[_row(h=5, q50=0.01), _row(h=20, q50=0.04)]))
    assert a.action == "hold"
    assert a.reasons == ["no rule fired"]
    assert a.horizon == 20 and a.q50 == 0.04


def test_without_a_forecast_only_the_stop_can_act():
    h = _holding(rows=[], why_no_forecast="too little history", value_cad=1400.0, momentum_pct=10.0)
    a = decide(h)
    assert a.action == "hold"
    assert a.reasons == ["too little history"]
    assert a.horizon is None and a.q10 is None and a.q50 is None and a.q90 is None
    assert decide(replace(h, price=89.0)).action == "sell"


def test_review_is_a_badge_on_top_of_the_action():
    a = decide(_holding(price=80.0, review=["earnings on Nov 3"]))
    assert a.action == "sell"
    assert a.review is True
    assert a.reasons[0].startswith("closed at") and a.reasons[-1] == "earnings on Nov 3"
    assert decide(_holding()).review is False


_LOSS = "selling at a loss: buying it again within 30 days before or after the sale denies the loss (superficial loss)"


def test_tax_warnings_only_in_taxable_accounts():
    loss = dict(price=80.0, value_cad=800.0)
    assert decide(_holding(account="tfsa", **loss)).warnings == []
    for acct in ("crypto", "non_registered"):
        a = decide(_holding(account=acct, **loss))
        assert a.action == "sell" and a.warnings == [_LOSS]
    # a Sell at a gain in a taxable account has none
    assert decide(_holding(account="crypto", price=80.0, value_cad=1200.0)).warnings == []

    add = decide(_holding(account="tfsa", rows=[_BUY_ROW], sold_at_loss_on=date(2026, 10, 1)))
    assert add.action == "add"
    assert add.warnings == ["sold at a loss on 2026-10-01: adding now denies that loss (superficial loss)"]
    # not an Add: no warning
    assert decide(_holding(sold_at_loss_on=date(2026, 10, 1))).warnings == []


def test_micro_prices_print_without_scientific_notation():
    a = decide(_holding(price=0.000003091, trailing_stop=0.000003123, rows=[]))
    assert a.reasons == ["closed at 0.000003091, under its trailing stop 0.000003123"]
    assert decide(_holding(price=0.5, trailing_stop=0.5, rows=[])).reasons == [
        "closed at 0.5000, under its trailing stop 0.5000"
    ]


def test_a_qualifying_horizon_beats_a_worse_best_ratio_row():
    # the best-ratio row has p 0.40, but another horizon qualifies as a Buy
    bad = _row(h=5, p=0.40, q10=-0.01, q50=0.02, q90=0.03)
    good = _row(h=20, p=0.60, q10=-0.10, q50=0.02, q90=0.10)
    a = decide(_holding(rows=[bad, good]))
    assert a.action == "add"
    assert a.horizon == 20
    over = decide(_holding(rows=[bad, good], value_cad=6000.0, cost_cad=6000.0))
    assert over.action == "hold" and over.horizon == 20


def test_no_portfolio_value_means_no_size_information():
    a = decide(_holding(rows=[_BUY_ROW], portfolio_cad=0.0))
    assert a.action == "add" and a.warnings == []


def test_ordinals_and_size_decimals():
    for pct, word in [(39.9, "39th"), (1, "1st"), (2, "2nd"), (3, "3rd"), (11, "11th"), (13, "13th"), (21, "21st"), (22, "22nd")]:
        a = decide(_holding(value_cad=1250.0, momentum_pct=pct))
        assert a.reasons == [f"up 25% and its 21-day momentum is at the {word} percentile"]
    a = decide(_holding(value_cad=5300.0, cost_cad=5300.0, max_position_pct=5.0))
    assert a.warnings == ["5.3% of the portfolio; Medium risk allows 5%"]


def test_a_holding_the_rank_picks_take_can_add():
    # owner's decision 2026-11-06: Add follows the picks under a rank policy
    from advisor.recommend.picks import top_by_horizon
    rank = replace(DEFAULT_POLICY, top_n=1)
    mine = _row(p=0.49, q50=0.0051)
    top = top_by_horizon([mine, replace(mine, symbol="ZZZ", p_beat=0.40)], 1)
    a = decide(_holding(rows=[mine], policy=rank, top=top))
    assert a.action == "add"
    assert a.reasons == ["would be a Buy today: ranked #1 of 2 by the model over 10 trading days, below its max size"]
    assert decide(_holding(rows=[mine], policy=rank)).action != "add"  # no ranking given: the P rule
