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
    rows = {f"S{i}": {} for i in range(10)}
    rows["TINY"] = {"log_mcap": np.log(250e6)}  # under $300M: at least High
    rows["SPARSE"] = {"groups_missing_share": 0.75}  # missing over half its groups: at least Medium
    out = risk_levels(frame(rows))
    assert out.loc["TINY", "risk_level"] in {"high", "very_high"}
    assert out.loc["SPARSE", "risk_level"] in {"medium", "high", "very_high"}


def test_missing_components_drop_out_and_weights_renormalise():
    rows = {f"T{i}": {"log_mcap": NAN, "disagreement": NAN, "vol_60": 0.1 + i / 50} for i in range(10)}
    out = risk_levels(frame(rows))  # a TSX market: no size, no disagreement
    assert out["risk_score"].notna().all()
    assert list(out.sort_values("risk_score").index) == [f"T{i}" for i in range(10)]
