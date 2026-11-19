from datetime import date

import numpy as np
import pandas as pd
import pytest

from advisor.model.holders import HOLDERS_FEATURES, holders_features, quarter_known


def _quarters(symbol: str, rows: list[tuple[str, str, int, int]]) -> pd.DataFrame:
    """holders.parquet rows for one symbol: (period, known, shares, holders)."""
    return pd.DataFrame({
        "symbol": symbol,
        "cusip": f"{symbol}CUSIP",
        "period": [pd.Timestamp(p).date() for p, _, _, _ in rows],
        "known": [pd.Timestamp(k).date() for _, k, _, _ in rows],
        "shares": pd.array([s for _, _, s, _ in rows], dtype="int64"),
        "holders": pd.array([h for _, _, _, h in rows], dtype="int64"),
    })


def _shares(days: pd.DatetimeIndex, symbols, count: float) -> pd.DataFrame:
    return pd.DataFrame({s: count for s in symbols}, index=days)


def _no_splits() -> pd.DataFrame:
    return pd.DataFrame({"Z": [1.0]}, index=pd.DatetimeIndex(["2020-01-01"]))


def _split(symbol: str, on: str, ratio: float) -> pd.DataFrame:
    """Today's shares per then-share: `ratio` before the split day, 1 from it."""
    day = pd.Timestamp(on)
    return pd.DataFrame({symbol: [ratio, 1.0, 1.0]},
                        index=[day - pd.Timedelta(days=1), day, day + pd.Timedelta(days=400)])


def _features(quarters, days, symbols, splits=None, outstanding=10_000.0):
    days = pd.DatetimeIndex(days)
    return holders_features(quarters, _shares(days, symbols, outstanding),
                            _no_splits() if splits is None else splits, days, symbols)


def test_a_quarter_is_known_at_the_later_of_45_days_after_its_end_and_30_days_after_its_window():
    assert quarter_known(date(2025, 3, 31), date(2025, 5, 31)) == date(2025, 6, 30)  # the window decides
    assert quarter_known(date(2018, 9, 30), date(2018, 12, 31)) == date(2019, 1, 30)
    assert quarter_known(date(2025, 3, 31), date(2025, 3, 31)) == date(2025, 5, 15)  # the 45 days decide
    quarters = _quarters("A", [("2024-12-31", "2025-03-01", 1_000, 10), ("2025-03-31", "2025-06-30", 1_500, 12)])
    out = _features(quarters, ["2025-06-30", "2025-07-01"], ["A"])
    assert list(out) == HOLDERS_FEATURES
    assert np.isnan(out["holder_count_chg"]["A"].iloc[0])  # not read on its known day
    assert np.isnan(out["inst_shares_chg"]["A"].iloc[0])
    assert out["holder_count_chg"]["A"].iloc[1] == 2.0  # read the day after
    assert out["inst_shares_chg"]["A"].iloc[1] == pytest.approx(500 / 10_000)


def test_changes_need_the_previous_quarter():
    quarters = pd.concat([
        _quarters("A", [("2024-12-31", "2025-03-01", 2_000, 20), ("2025-03-31", "2025-06-01", 1_000, 15),
                        ("2025-09-30", "2025-11-15", 3_000, 30)]),  # 2025-06-30 is missing
        _quarters("B", [("2025-03-31", "2025-06-01", 1_000, 15)]),  # one quarter only
        _quarters("C", [("2024-09-30", "2024-12-01", 2_000, 20), ("2025-03-31", "2025-06-01", 1_000, 15)]),
        _quarters("D", [("2024-12-31", "2025-08-01", 2_000, 20), ("2025-03-31", "2025-06-01", 1_000, 15)]),
    ], ignore_index=True)
    out = _features(quarters, ["2025-06-02", "2025-08-02", "2025-11-16"], ["A", "B", "C", "D"])
    count, chg = out["holder_count_chg"], out["inst_shares_chg"]
    assert count["A"].iloc[:2].tolist() == [-5.0, -5.0]
    assert chg["A"].iloc[:2].tolist() == pytest.approx([-0.1, -0.1])
    assert np.isnan(count["A"].iloc[2]) and np.isnan(chg["A"].iloc[2])  # the latest quarter has no pair
    for symbol in ("B", "C"):  # no previous quarter; one 182 days earlier is not the previous quarter
        assert count[symbol].isna().all() and chg[symbol].isna().all()
    assert np.isnan(count["D"].iloc[0]) and np.isnan(chg["D"].iloc[0])  # its previous quarter not known yet
    assert count["D"].iloc[1] == -5.0


def test_a_split_between_quarters_is_not_a_change_in_shares():
    quarters = _quarters("A", [("2024-12-31", "2025-03-01", 1_000, 10), ("2025-03-31", "2025-06-01", 2_000, 13)])
    out = _features(quarters, ["2025-07-01"], ["A"], splits=_split("A", "2025-02-15", 2.0))
    assert out["inst_shares_chg"]["A"].iloc[0] == pytest.approx(0.0)  # 1,000 then-shares are 2,000 today
    assert out["holder_count_chg"]["A"].iloc[0] == 3.0


def test_a_symbol_without_a_cusip_reads_missing():
    quarters = _quarters("A", [("2024-12-31", "2025-03-01", 1_000, 10), ("2025-03-31", "2025-06-01", 1_500, 12)])
    out = _features(quarters, ["2025-07-01"], ["A", "B"])  # no CUSIP for B, so no quarters
    assert out["holder_count_chg"]["A"].iloc[0] == 2.0
    assert out["holder_count_chg"]["B"].isna().all() and out["inst_shares_chg"]["B"].isna().all()
    missing = _features(None, ["2025-07-01"], ["A"])  # the source did not run cleanly
    assert all(missing[name].isna().all().all() for name in HOLDERS_FEATURES)


def test_shares_outstanding_missing_reads_missing_share_change_only():
    quarters = _quarters("A", [("2024-12-31", "2025-03-01", 1_000, 10), ("2025-03-31", "2025-06-01", 1_500, 12)])
    out = _features(quarters, ["2025-07-01"], ["A"], outstanding=np.nan)
    assert np.isnan(out["inst_shares_chg"]["A"].iloc[0])
    assert out["holder_count_chg"]["A"].iloc[0] == 2.0


def test_a_latest_quarter_known_over_200_days_ago_reads_missing():
    """Ruling R11: a CUSIP missing from later data sets does not carry its last pair forever."""
    from advisor.model.holders import HOLDERS_STALE_DAYS

    known = pd.Timestamp("2025-06-30")
    quarters = _quarters("A", [("2024-12-31", "2025-03-01", 1_000, 10), ("2025-03-31", "2025-06-30", 1_500, 12)])
    days = [known + pd.Timedelta(days=199), known + pd.Timedelta(days=HOLDERS_STALE_DAYS),
            known + pd.Timedelta(days=201)]
    out = _features(quarters, days, ["A"])
    assert HOLDERS_STALE_DAYS == 200
    assert out["holder_count_chg"]["A"].iloc[:2].tolist() == [2.0, 2.0]
    assert out["inst_shares_chg"]["A"].iloc[0] == pytest.approx(500 / 10_000)
    assert out["holder_count_chg"]["A"].iloc[2:].isna().all()
    assert out["inst_shares_chg"]["A"].iloc[2:].isna().all()
