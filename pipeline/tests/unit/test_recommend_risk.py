import math

import numpy as np
import pandas as pd
import pytest

from advisor.recommend.risk import disagreement, risk_levels

NAN = float("nan")


def frame(rows: dict[str, dict]) -> pd.DataFrame:
    base = {"vol_60": 0.3, "width": 0.1, "disagreement": 0.0, "log_adv20": 18.0, "event": 0.0,
            "log_mcap": 23.0, "groups_missing_share": 0.0}
    return pd.DataFrame({s: base | r for s, r in rows.items()}).T.astype(float)


def test_signals_that_split_evenly_disagree_fully():
    assert disagreement(0.1, -0.2, NAN) == 1.0
    assert disagreement(0.1, 0.2, 0.3) == 0.0
    assert disagreement(0.1, -0.2, 0.3) == pytest.approx(2 / 3)
    assert math.isnan(disagreement(0.1, NAN, NAN))  # one direction can't disagree


def test_the_riskiest_stock_by_every_measure_ranks_very_high():
    rows = {f"S{i}": {"vol_60": 0.1 + i / 100, "width": 0.05 + i / 1000, "log_adv20": 20 - i / 10,
                      "log_mcap": 25 - i / 10} for i in range(20)}
    out = risk_levels(frame(rows))
    assert out.loc["S19", "risk_level"] == "very_high" and out.loc["S19", "max_position_pct"] == 0.5
    assert out.loc["S0", "risk_level"] == "low" and out.loc["S0", "max_position_pct"] == 5.0
    assert out["risk_score"].between(0, 100).all()


def test_floors_lift_the_level():
    # TINY and SPARSE are the calmest names (lowest vol and width), so they are "low" unless a floor lifts them
    rows = {f"S{i}": {"vol_60": 0.2 + i / 100, "width": 0.1 + i / 100} for i in range(12)}
    rows["TINY"] = {"vol_60": 0.05, "width": 0.01, "log_mcap": np.log(250e6)}  # under $300M: at least High
    rows["SPARSE"] = {"vol_60": 0.05, "width": 0.01, "groups_missing_share": 0.75}  # over half missing: Medium
    out = risk_levels(frame(rows))
    assert out.loc["TINY", "risk_level"] == "high" and out.loc["TINY", "max_position_pct"] == 1.5
    assert out.loc["SPARSE", "risk_level"] == "medium" and out.loc["SPARSE", "max_position_pct"] == 3.0
    assert out.loc["S0", "risk_level"] == "low"


def test_a_row_with_no_components_is_the_most_cautious_and_leaves_the_others_alone():
    rows = {f"S{i}": {"vol_60": 0.1 + i / 50, "width": 0.05 + i / 100} for i in range(4)}
    without = risk_levels(frame(rows))
    blank = {k: NAN for k in ("vol_60", "width", "disagreement", "log_adv20", "event", "log_mcap")}
    out = risk_levels(frame(rows | {"BLANK": blank}))
    assert out.loc["BLANK", "risk_score"] == 100.0
    assert out.loc["BLANK", "risk_level"] == "very_high" and out.loc["BLANK", "max_position_pct"] == 0.5
    cols = ["risk_level", "max_position_pct"]
    assert out.loc[list(rows), cols].equals(without[cols])


@pytest.mark.parametrize("column", ["log_adv20", "log_mcap"])
def test_lower_liquidity_and_smaller_size_score_riskier(column):
    rows = {f"S{i}": {column: 20.0 + i} for i in range(10)}
    out = risk_levels(frame(rows))
    assert out["risk_score"].is_monotonic_decreasing


def test_a_missing_component_renormalises_that_stocks_weights():
    rows = {f"S{i}": {"vol_60": 0.1 + i / 100, "width": 0.1 + i / 100} for i in range(4)}
    rows["S0"]["width"] = NAN
    out = risk_levels(frame(rows))
    # S0 has the lowest vol of four (percentile 25); its other available components tie at 62.5.
    # Width is missing, so the remaining weights (0.80) renormalise.
    expected = (0.30 * 25 + (0.15 + 0.15 + 0.10 + 0.10) * 62.5) / 0.80
    assert out.loc["S0", "risk_score"] == pytest.approx(expected)


def test_missing_components_drop_out_and_weights_renormalise():
    rows = {f"T{i}": {"log_mcap": NAN, "disagreement": NAN, "vol_60": 0.1 + i / 50} for i in range(10)}
    out = risk_levels(frame(rows))  # a TSX market: no size, no disagreement
    assert out["risk_score"].notna().all()
    assert list(out.sort_values("risk_score").index) == [f"T{i}" for i in range(10)]
