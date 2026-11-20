import numpy as np
import pandas as pd
import pytest

from advisor.model.insider import INSIDER_FEATURES, insider_features

D = pd.Timestamp("2026-06-01")
DAY = pd.Timedelta(days=1)


def _trades(rows: list[tuple]) -> pd.DataFrame:
    """Trades in insider_trades.parquet's columns, from (symbol, code, shares, price, known day[, owners,
    officer]); each is accepted at 15:00 UTC (11:00 ET), so it is known on its own day."""
    full = [(*row, *((["OWNER ONE"], False)[len(row) - 5:])) for row in rows]
    known = [pd.Timestamp(row[4]) for row in full]
    return pd.DataFrame({
        "symbol": [row[0] for row in full],
        "accession": [f"0000000000-26-{i:06d}" for i in range(len(full))],
        "filing_date": [day.date() for day in known],
        "accepted_at": pd.to_datetime([day + pd.Timedelta(hours=15) for day in known], utc=True),
        "trade_date": [(day - pd.Timedelta(days=2)).date() for day in known],
        "code": [row[1] for row in full],
        "shares": [float(row[2]) for row in full],
        "price": [row[3] for row in full],
        "owners": [list(row[5]) for row in full],
        "officer": [bool(row[6]) for row in full],
        "director": False,
        "ten_percent_owner": False,
        "filed_ticker": [row[0] for row in full],
    })


def _value(day, symbols: list[str], value: float) -> pd.DataFrame:
    return pd.DataFrame(value, index=pd.DatetimeIndex([day]), columns=symbols)


def _days(*days) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(list(days))


def test_the_feature_names():
    assert INSIDER_FEATURES == ["insider_net_buy_90d", "insider_buyers_90d", "officer_buy_180d"]


def test_net_buying_is_a_share_of_market_value():
    trades = _trades([("A", "P", 10_000, 50.0, D - 10 * DAY), ("A", "S", 2_000, 50.0, D - 20 * DAY)])  # (.., known day)
    out = insider_features(trades, _value(D, ["A"], 1e9), {"A"}, pd.DatetimeIndex([D]), ["A"])
    assert list(out) == INSIDER_FEATURES
    assert out["insider_net_buy_90d"].loc[D, "A"] == pytest.approx(400_000 / 1e9)


def test_a_covered_symbol_without_trades_reads_zero_and_an_uncovered_one_missing():
    out = insider_features(_trades([]), _value(D, ["A", "B"], 1e9), {"A"}, pd.DatetimeIndex([D]), ["A", "B"])
    assert out["insider_buyers_90d"].loc[D, "A"] == 0 and np.isnan(out["insider_buyers_90d"].loc[D, "B"])
    for name in INSIDER_FEATURES:
        assert out[name].loc[D, "A"] == 0 and np.isnan(out[name].loc[D, "B"])


def test_distinct_buyers_count_each_owner_once():
    trades = _trades([
        ("A", "P", 100, 10.0, D - 5 * DAY, ["SMITH JOHN"], False),
        ("A", "P", 100, 10.0, D - 30 * DAY, ["SMITH JOHN"], False),
        ("A", "P", 100, None, D - 40 * DAY, ["DOE JANE", "ROE RICHARD"], False),  # joint filing, no price
        ("A", "S", 100, 10.0, D - 10 * DAY, ["SELLER SAM"], False),  # a seller is no buyer
        ("A", "P", 100, 10.0, D - 95 * DAY, ["OLD OWEN"], False),  # outside the 90 days
    ])
    out = insider_features(trades, _value(D, ["A"], 1e6), {"A"}, pd.DatetimeIndex([D]), ["A"])
    assert out["insider_buyers_90d"].loc[D, "A"] == 3
    # the priceless buy adds no dollars: (2 x 1,000 bought - 1,000 sold) / 1e6
    assert out["insider_net_buy_90d"].loc[D, "A"] == pytest.approx(1_000 / 1e6)


def test_buyers_read_owners_stored_as_arrays():
    trades = _trades([("A", "P", 100, 10.0, D - 5 * DAY, ["X"], False)])
    trades["owners"] = [np.array(["X", "Y"], dtype=object)]  # as read back from parquet
    out = insider_features(trades, _value(D, ["A"], 1e6), {"A"}, pd.DatetimeIndex([D]), ["A"])
    assert out["insider_buyers_90d"].loc[D, "A"] == 2


def test_an_officer_buy_counts_for_180_days():
    trades = _trades([
        ("A", "P", 100, 10.0, D - 170 * DAY, ["BOSS BETTY"], True),
        ("B", "P", 100, 10.0, D - 10 * DAY, ["DIRECTOR DAN"], False),  # not an officer
        ("C", "S", 100, 10.0, D - 10 * DAY, ["BOSS BOB"], True),  # an officer sale is no buy
        ("E", "P", 100, 10.0, D - 181 * DAY, ["BOSS EVE"], True),  # outside the 180 days
    ])
    symbols = ["A", "B", "C", "E"]
    days = _days(D, D + 11 * DAY)
    value = pd.DataFrame(1e6, index=days, columns=symbols)
    out = insider_features(trades, value, set(symbols), days, symbols)
    assert out["officer_buy_180d"].loc[D].tolist() == [1, 0, 0, 0]
    assert out["officer_buy_180d"].loc[D + 11 * DAY].tolist() == [0, 0, 0, 0]  # A's buy is 181 days old
    assert out["insider_buyers_90d"].loc[D].tolist() == [0, 1, 0, 0]


def test_a_trade_accepted_on_the_row_day_is_not_read():
    trades = _trades([("A", "P", 1_000, 10.0, D, ["BOSS BETTY"], True)])
    days = _days(D, D + DAY)
    value = pd.DataFrame(1e6, index=days, columns=["A"])
    out = insider_features(trades, value, {"A"}, days, ["A"])
    assert out["insider_net_buy_90d"]["A"].tolist() == [0, pytest.approx(0.01)]
    assert out["insider_buyers_90d"]["A"].tolist() == [0, 1]
    assert out["officer_buy_180d"]["A"].tolist() == [0, 1]


def test_a_trade_without_acceptance_time_waits_one_session_after_filing():
    trades = _trades([("A", "P", 1_000, 10.0, pd.Timestamp("2026-07-02"))])
    trades["accepted_at"] = pd.NaT  # July 3 is a holiday: known on the 6th
    days = _days("2026-07-06", "2026-07-07")
    out = insider_features(trades, pd.DataFrame(1e6, index=days, columns=["A"]), {"A"}, days, ["A"])
    assert out["insider_buyers_90d"]["A"].tolist() == [0, 1]


def test_net_buying_without_a_market_value_is_missing():
    trades = _trades([("A", "P", 1_000, 10.0, D - 5 * DAY)])
    out = insider_features(trades, _value(D, ["A"], np.nan), {"A"}, pd.DatetimeIndex([D]), ["A"])
    assert np.isnan(out["insider_net_buy_90d"].loc[D, "A"])
    assert out["insider_buyers_90d"].loc[D, "A"] == 1


def test_a_missing_source_reads_missing_not_zero():
    out = insider_features(None, _value(D, ["A"], 1e9), {"A"}, pd.DatetimeIndex([D]), ["A"])
    for name in INSIDER_FEATURES:
        assert np.isnan(out[name].loc[D, "A"])


def test_a_training_row_after_the_data_sets_coverage_end_reads_missing():
    """SEC's quarterly data sets end at their newest quarter: a row after it would count empty windows as 0."""
    end = pd.Timestamp("2026-09-30")
    trades = _trades([("A", "P", 1_000, 10.0, end - 5 * DAY, ["BOSS BETTY"], True)])
    days = _days(end, end + DAY, end + 2 * DAY, end + 44 * DAY)
    value = pd.DataFrame(1e6, index=days, columns=["A", "B"])
    out = insider_features(trades, value, {"A", "B"}, days, ["A", "B"], coverage_end=end.date())
    # 10-01 still reads every filing known before it (all through 09-30); from 10-02 the window has a hole
    assert out["insider_buyers_90d"]["A"].tolist()[:2] == [1, 1]
    assert out["insider_buyers_90d"]["B"].tolist()[:2] == [0, 0]
    for name in INSIDER_FEATURES:
        assert out[name].iloc[2:].isna().all().all(), name
    live = insider_features(trades, value, {"A", "B"}, days, ["A", "B"])  # live: no coverage end
    assert live["insider_buyers_90d"]["A"].tolist() == [1, 1, 1, 1]
