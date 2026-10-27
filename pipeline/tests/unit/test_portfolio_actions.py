from dataclasses import replace
from datetime import date

from advisor.models import AssetType, PredictionRow
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


def test_a_hit_trailing_stop_sells_whatever_the_forecast():
    a = decide(_holding(price=90.0, rows=[_BUY_ROW]))
    assert a.action == "sell"
    assert a.reasons == ["closed at 90.00, under its trailing stop 90.00"]
    assert decide(_holding(price=90.01, rows=[_BUY_ROW])).action != "sell"


def test_stop_prices_under_one_use_four_significant_figures():
    a = decide(_holding(price=0.5, trailing_stop=0.512345, rows=[]))
    assert a.reasons == ["closed at 0.5, under its trailing stop 0.5123"]


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
    assert a.reasons == ["up 25% and its 21-day momentum is at the 40th percentile"]
    assert decide(_holding(value_cad=1249.0, momentum_pct=39.9)).action == "hold"
    assert decide(_holding(value_cad=1250.0, momentum_pct=40.0)).action == "hold"
    assert decide(_holding(value_cad=1250.0, momentum_pct=None)).action == "hold"


def test_oversize_is_a_warning_never_a_trim():
    big = _holding(value_cad=36_000.0, cost_cad=36_000.0, max_position_pct=1.5, risk_level="very_high")
    a = decide(big)
    assert a.action == "hold"
    assert a.warnings == ["36% of the portfolio; Very High risk allows 1.5%"]
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
