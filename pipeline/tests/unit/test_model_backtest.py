import numpy as np
import pandas as pd
import pytest

from advisor.model.backtest import gate, pick_metrics, round_trip_cost, simulate_picks
from advisor.models import Market

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
