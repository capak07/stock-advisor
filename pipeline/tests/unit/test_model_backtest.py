from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from advisor.model.backtest import gate, pick_funnel, pick_metrics, round_trip_cost, simulate_picks
from advisor.models import Market
from advisor.policy import DEFAULT_POLICY

DAY = pd.Timestamp("2025-03-03")


def frame(rows) -> pd.DataFrame:
    return pd.DataFrame(
        [{"day": DAY, "symbol": s, "sector": sec, "horizon": h, "p": p, "q10": q10, "q50": q50, "q90": q90, "y": y,
          "dollar_volume_20": 2e7} for s, sec, h, p, q10, q50, q90, y in rows]
    )


def test_round_trip_costs_follow_the_market_rules():
    dollar_volume = np.array([2e7, 5e6])
    assert round_trip_cost(Market.US, dollar_volume, 1.5) == pytest.approx([0.031, 0.033])
    assert round_trip_cost(Market.TSX, dollar_volume, 1.5) == pytest.approx([0.001, 0.003])


def test_a_stock_is_picked_once_at_its_best_qualifying_horizon():
    picks = simulate_picks(frame([
        ("AAA.TO", "Energy", 10, 0.60, -0.02, 0.01, 0.03, 0.02),  # q50/(q90-q10) = 0.20
        ("AAA.TO", "Energy", 63, 0.62, -0.05, 0.04, 0.10, 0.06),  # 0.27: the better hold
        ("BBB.TO", "Energy", 20, 0.57, -0.02, 0.03, 0.05, 0.01),  # P below 0.58
        ("CCC.TO", "Energy", 20, 0.70, -0.02, 0.0005, 0.05, 0.01),  # q50 below the 0.10% cost
    ]), Market.TSX, 1.5)
    assert picks[["symbol", "horizon", "style"]].values.tolist() == [["AAA.TO", 63, "position"]]
    assert picks["net"].iloc[0] == pytest.approx(0.06 - 0.001)


def test_each_style_takes_ten_with_at_most_three_per_sector():
    rows = [(f"E{i}.TO", "Energy", 20, 0.65, -0.02, 0.02 + i / 1000, 0.06, 0.0) for i in range(5)]
    rows += [(f"T{i}.TO", f"Sector{i}", 20, 0.65, -0.02, 0.01, 0.06, 0.0) for i in range(12)]
    picks = simulate_picks(frame(rows), Market.TSX, 1.5)
    assert len(picks) == 10 and set(picks["style"]) == {"swing"}
    assert sorted(picks.loc[picks["sector"] == "Energy", "symbol"]) == ["E2.TO", "E3.TO", "E4.TO"]


def test_unlabelled_stocks_do_not_share_a_sector_cap_and_nan_p_is_never_picked():
    rows = [(f"U{i}.TO", None, 20, 0.65, -0.02, 0.02, 0.06, 0.0) for i in range(5)]
    rows.append(("NAN.TO", "Energy", 20, np.nan, -0.02, 0.05, 0.06, 0.0))
    picks = simulate_picks(frame(rows), Market.TSX, 1.5)
    assert sorted(picks["symbol"]) == [f"U{i}.TO" for i in range(5)]


def test_the_funnel_counts_the_forecasts_each_pick_rule_lets_through():
    rows = [
        ("AAA", "Tech", 10, 0.60, -0.02, 0.05, 0.08, 0.0),  # passes both
        ("BBB", "Tech", 10, 0.57, -0.02, 0.05, 0.08, 0.0),  # P below 0.58
        ("CCC", "Tech", 63, 0.70, -0.02, 0.02, 0.08, 0.0),  # q50 below the 3.1% US round trip
        ("DDD", "Tech", 63, 0.40, -0.02, 0.01, 0.08, 0.0),  # neither
        ("EEE", "Tech", 63, np.nan, -0.02, 0.05, 0.08, 0.0),  # no calibrated P
    ]
    funnel = pick_funnel(frame(rows), Market.US, 1.5)
    assert funnel == {
        "forecasts": 5, "p_at_least_floor": 2, "above_cost": 3, "both": 1,
        "p_max": pytest.approx(0.70), "p_99": pytest.approx(0.697), "mean_cost": pytest.approx(0.031),
        "p_max_by_horizon": {10: pytest.approx(0.60), 63: pytest.approx(0.70)},
    }


def test_an_empty_funnel_has_no_maximum():
    funnel = pick_funnel(frame([("X.TO", "Energy", 5, 0.5, -0.1, 0.0, 0.1, 0.0)]).iloc[0:0], Market.TSX, 1.5)
    assert funnel["forecasts"] == 0 and funnel["p_max"] is None and funnel["p_max_by_horizon"] == {}


def test_pick_metrics_are_per_style_and_overall():
    picks = pd.DataFrame({"style": ["swing", "swing", "position"], "net": [0.02, -0.01, 0.05],
                          "y": [0.021, -0.009, 0.051], "p": [0.6, 0.6, 0.7]})
    m = pick_metrics(picks)
    assert m["all"]["picks"] == 3
    assert m["all"]["mean_net_pct"] == pytest.approx(2.0)
    assert m["all"]["hit_rate_net"] == pytest.approx(2 / 3)
    assert m["all"]["beat_rate"] == pytest.approx(2 / 3)
    assert m["all"]["mean_p"] == pytest.approx(0.6333, abs=1e-3)
    assert m["swing"]["picks"] == 2 and m["position"]["mean_net_pct"] == pytest.approx(5.0)
    empty = pick_metrics(picks.iloc[:0])
    assert empty["all"] == {"picks": 0, "mean_net_pct": None, "hit_rate_net": None, "beat_rate": None, "mean_p": None}


def test_the_gate_needs_enough_profitable_honestly_calibrated_picks():
    def m(picks, net, p, beat):
        return {"all": {"picks": picks, "mean_net_pct": net, "hit_rate_net": beat, "beat_rate": beat, "mean_p": p}}

    assert gate(m(40, 0.8, 0.62, 0.60), 3.0) == (True, "40 backtest picks gained 0.80% after costs")
    assert gate(m(12, 0.8, 0.62, 0.60), 3.0) == (False, "only 12 backtest picks (needs 30)")
    assert gate(m(40, -1.2, 0.62, 0.60), 3.0) == (False, "backtest picks lost 1.20% after costs")
    assert gate(m(40, 0.8, 0.62, 0.60), 6.1) == (False, "probabilities off by 6.1 points (limit 5)")
    assert gate(m(40, 0.8, 0.66, 0.51), 3.0) == (
        False, "picks claimed 66% but beat their benchmark 51% of the time",
    )
    assert gate(pick_metrics(pd.DataFrame(columns=["style", "net", "y", "p"])), 2.0) == (
        False, "only 0 backtest picks (needs 30)",
    )


def test_the_gate_fails_closed_on_missing_numbers():
    def m(net, p, beat):
        return {"all": {"picks": 40, "mean_net_pct": net, "hit_rate_net": beat, "beat_rate": beat, "mean_p": p}}

    nan = float("nan")
    assert gate(m(0.8, 0.62, 0.60), nan) == (False, "probabilities couldn't be checked (no calibrated predictions)")
    assert gate(m(nan, 0.62, 0.60), 3.0) == (False, "backtest picks couldn't be scored")
    assert gate(m(0.8, nan, 0.60), 3.0) == (False, "backtest picks couldn't be scored")
    assert gate(m(0.8, 0.62, nan), 3.0) == (False, "backtest picks couldn't be scored")


def test_a_flagged_jump_on_the_latest_bar_is_never_picked():
    rows = frame([
        ("AAA.TO", "Energy", 20, 0.65, -0.02, 0.03, 0.05, 0.01),
        ("BBB.TO", "Energy", 20, 0.65, -0.02, 0.03, 0.05, 0.01),
    ])
    rows["jump_5d"] = [1.0, 0.0]
    assert simulate_picks(rows, Market.TSX, 1.5)["symbol"].tolist() == ["BBB.TO"]
    assert simulate_picks(rows.drop(columns="jump_5d"), Market.TSX, 1.5)["symbol"].tolist() == ["AAA.TO", "BBB.TO"]


def test_a_stock_still_held_is_not_picked_again():
    def row(day, h):
        return {"day": pd.Timestamp(day), "symbol": "AAA.TO", "sector": "Energy", "horizon": h, "p": 0.65,
                "q10": -0.05, "q50": 0.04, "q90": 0.10, "y": 0.03, "dollar_volume_20": 2e7}
    preds = pd.DataFrame([row("2025-03-03", 63), row("2025-03-17", 63), row("2025-06-02", 63)])
    picks = simulate_picks(preds, Market.TSX, 1.5)
    # 03-17 is inside the first 63-session hold; 06-02 is 65 business days on, so it's a new bet
    assert [str(d.date()) for d in picks["day"]] == ["2025-03-03", "2025-06-02"]


def test_a_lower_buy_line_picks_a_row_the_default_skips():
    rows = frame([("AAA.TO", "Energy", 10, 0.55, -0.02, 0.04, 0.10, 0.02)])
    assert simulate_picks(rows, Market.TSX, 1.5).empty
    loose = replace(DEFAULT_POLICY, p_buy=0.54)
    assert simulate_picks(rows, Market.TSX, 1.5, policy=loose)["symbol"].tolist() == ["AAA.TO"]
    assert pick_funnel(rows, Market.TSX, 1.5)["p_at_least_floor"] == 0
    assert pick_funnel(rows, Market.TSX, 1.5, policy=loose)["p_at_least_floor"] == 1


def test_the_pick_rule_and_the_horizon_set_follow_the_policy():
    rows = frame([
        ("AAA.TO", "Energy", 10, 0.70, -0.02, 0.01, 0.08, 0.02),  # ratio 0.10
        ("AAA.TO", "Energy", 63, 0.60, -0.05, 0.04, 0.05, 0.03),  # ratio 0.40, so the default hold
    ])
    by_p = simulate_picks(rows, Market.TSX, 1.5, policy=replace(DEFAULT_POLICY, rule="p"))
    swing = simulate_picks(rows, Market.TSX, 1.5, policy=replace(DEFAULT_POLICY, horizons=(5, 10, 20)))
    assert by_p["horizon"].tolist() == [10]
    assert swing["horizon"].tolist() == [10]


def test_a_short_hold_ends_before_the_next_sample_day():
    preds = pd.DataFrame([
        {"day": pd.Timestamp(d), "symbol": "BBB.TO", "sector": "Energy", "horizon": 5, "p": 0.65,
         "q10": -0.02, "q50": 0.02, "q90": 0.04, "y": 0.01, "dollar_volume_20": 2e7}
        for d in ("2025-03-03", "2025-03-17")
    ])
    assert len(simulate_picks(preds, Market.TSX, 1.5)) == 2
