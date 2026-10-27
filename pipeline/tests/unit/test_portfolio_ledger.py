from datetime import date

import pytest

from advisor.models import AssetType
from advisor.portfolio.ledger import Loss, Trade, build_ledger

FX = {date(2026, 9, 1): 1.35, date(2026, 10, 1): 1.4}


def buy(**over) -> Trade:
    fields = {
        "side": "buy", "account": "tfsa", "symbol": "RY.TO", "asset_type": AssetType.STOCK,
        "qty": 10.0, "price": 100.0, "currency": "CAD", "fx_rate_cad": None,
        "day": date(2026, 9, 2), "pick_id": None,
    }
    return Trade(**{**fields, **over})


def sell(**over) -> Trade:
    return buy(side="sell", **over)


def test_average_cost_per_account_and_asset():
    usd = {"symbol": "AAPL", "currency": "USD", "price": 200.0}
    ledger = build_ledger(
        [
            buy(**usd, fx_rate_cad=1.4),
            buy(**{**usd, "price": 220.0}, fx_rate_cad=1.35, day=date(2026, 9, 5)),
            buy(**usd, fx_rate_cad=1.4, account="rrsp"),
        ],
        FX,
    )
    tfsa, rrsp = ledger.positions
    assert (tfsa.account, tfsa.qty) == ("tfsa", 20)
    assert tfsa.cost_cad == pytest.approx(10 * 200 * 1.4 + 10 * 220 * 1.35)
    assert tfsa.opened_on == date(2026, 9, 2)
    assert (rrsp.account, rrsp.qty, rrsp.cost_cad) == ("rrsp", 10, pytest.approx(2800))
    assert ledger.problems == []


def test_a_sell_reduces_quantity_at_average_cost_and_a_loss_is_recorded():
    ledger = build_ledger([buy(), sell(qty=4.0, price=80.0, day=date(2026, 9, 10))], FX)
    (position,) = ledger.positions
    assert position.qty == 6
    assert position.cost_cad == pytest.approx(600)
    assert ledger.losses == [Loss("tfsa", "RY.TO", AssetType.STOCK, date(2026, 9, 10))]


def test_a_sell_at_a_gain_is_not_a_loss():
    ledger = build_ledger([buy(), sell(qty=4.0, price=120.0)], FX)
    assert ledger.losses == []


def test_a_days_buys_count_before_its_sells():
    ledger = build_ledger([sell(), buy()], FX)
    assert ledger.problems == []
    assert ledger.positions == []


def test_a_sell_of_more_than_is_held_applies_to_what_is_held():
    ledger = build_ledger([buy(), sell(qty=12.0, price=110.0)], FX)
    assert ledger.positions == []
    assert ledger.losses == []
    assert ledger.problems == ["RY.TO on 2026-09-02: sold 12 but held 10; counted as 10."]


def test_a_sell_with_nothing_held_is_left_out():
    ledger = build_ledger([sell()], FX)
    assert ledger.positions == []
    assert ledger.problems == ["RY.TO on 2026-09-02: a sell with nothing held, so it's left out."]


def test_selling_out_and_buying_again_opens_a_new_position():
    ledger = build_ledger(
        [
            buy(pick_id=7),
            sell(day=date(2026, 9, 10), price=90.0),
            buy(day=date(2026, 9, 25), price=80.0, pick_id=9),
        ],
        FX,
    )
    (position,) = ledger.positions
    assert position.opened_on == date(2026, 9, 25)
    assert position.pick_id == 9
    assert position.cost_cad == pytest.approx(800)
    assert len(ledger.losses) == 1


def test_the_pick_is_the_latest_non_null_one_among_the_buys():
    ledger = build_ledger(
        [
            buy(pick_id=3),
            buy(day=date(2026, 9, 5), pick_id=4),
            buy(day=date(2026, 9, 8), pick_id=None),
        ],
        FX,
    )
    assert ledger.positions[0].pick_id == 4


def test_a_usd_trade_without_any_rate_is_left_out_with_a_problem():
    aapl = {"symbol": "AAPL", "currency": "USD", "day": date(2026, 1, 5)}
    ledger = build_ledger([buy(**aapl)], {})
    assert ledger.positions == []
    assert ledger.problems == ["AAPL on 2026-01-05: no USD/CAD rate for that day, so it's left out."]


def test_a_usd_trade_uses_the_latest_rate_on_or_before_its_day():
    aapl = {"symbol": "AAPL", "currency": "USD", "price": 50.0, "day": date(2026, 10, 5)}
    ledger = build_ledger([buy(**aapl)], FX)
    assert ledger.positions[0].cost_cad == pytest.approx(10 * 50 * 1.4)
    early = build_ledger([buy(**{**aapl, "day": date(2026, 8, 1)})], FX)
    assert early.positions == []


def test_a_coin_leftover_that_is_a_rounding_error_closes_the_position():
    coin = {"symbol": "BTC", "asset_type": AssetType.CRYPTO, "account": "crypto"}
    ledger = build_ledger(
        [buy(**coin, qty=0.1), buy(**coin, qty=0.2), sell(**coin, qty=0.30000000000000004)], FX
    )
    assert ledger.positions == []
