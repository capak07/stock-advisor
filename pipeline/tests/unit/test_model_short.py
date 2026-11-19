import numpy as np
import pandas as pd
import pytest

from advisor.model.short import SHORT_FEATURES, short_features


def _interest(symbol: str, settlements: list[str], shorts: list[int], dtc: float = 2.0) -> pd.DataFrame:
    return pd.DataFrame({
        "symbol": symbol,
        "settlement": pd.to_datetime(settlements).date,
        "short_interest": pd.array(shorts, dtype="int64"),
        "avg_daily_volume": 500_000.0,
        "days_to_cover": dtc,
    })


def _shares(days: pd.DatetimeIndex, symbol: str, count: float) -> pd.DataFrame:
    return pd.DataFrame({symbol: count}, index=days)


def _no_splits() -> pd.DataFrame:
    return pd.DataFrame({"A": [1.0]}, index=pd.DatetimeIndex(["2020-01-01"]))


def _split(symbol: str, on: str, ratio: float) -> pd.DataFrame:
    """Today's shares per then-share: `ratio` before the split day, 1 from it."""
    day = pd.Timestamp(on)
    return pd.DataFrame({symbol: [ratio, 1.0, 1.0]}, index=[day - pd.Timedelta(days=1), day, day + pd.Timedelta(days=400)])


def _sessions_before(day: str, count: int) -> list[str]:
    return [d.strftime("%Y-%m-%d") for d in pd.bdate_range(end=pd.Timestamp(day) - pd.Timedelta(days=1), periods=count)]


def _volume(symbol: str, sessions: list[str], short: float, total: float) -> pd.DataFrame:
    return pd.DataFrame({
        "symbol": symbol, "day": pd.to_datetime(sessions).date, "short_volume": short, "total_volume": total,
    })


def _ratio_on(volume: pd.DataFrame, day: str, symbols=("A", "B")) -> float:
    days = pd.DatetimeIndex([day])
    shares = pd.DataFrame({s: 1.0 for s in symbols}, index=days)
    out = short_features(None, volume, shares, _no_splits(), days, list(symbols))
    return out["short_vol_ratio_20d"]["A"].iloc[0]


def test_short_interest_is_read_after_its_12th_session():
    interest = _interest("A", ["2026-05-29", "2026-06-15"], [1_000_000, 1_500_000])
    # known: 2026-05-29 -> 2026-06-16; 2026-06-15 -> 2026-07-02 (June 19 and July 3 are holidays)
    days = pd.DatetimeIndex(["2026-06-16", "2026-06-17", "2026-07-02", "2026-07-06"])
    out = short_features(interest, None, _shares(days, "A", 10_000_000), _no_splits(), days, ["A"])
    pct = out["short_pct_shares"]["A"]
    assert np.isnan(pct.iloc[0])  # the row day itself reads nothing yet
    assert pct.iloc[1:].tolist() == pytest.approx([0.10, 0.10, 0.15])
    assert np.isnan(out["short_chg"]["A"].iloc[1])  # no previous settlement
    assert out["short_chg"]["A"].iloc[3] == pytest.approx(0.05)
    assert out["days_to_cover"]["A"].iloc[1:].tolist() == [2.0, 2.0, 2.0]
    assert out["short_vol_ratio_20d"]["A"].isna().all()  # no volume given


def test_a_split_between_two_reports_is_not_a_change():
    day = pd.DatetimeIndex(["2026-03-02"])  # after 2026-02-18 (the 2026-01-30 report's 12th session), within 45 days
    interest = _interest("A", ["2026-01-15", "2026-01-30"], [1_000_000, 2_000_000])
    splits = _split("A", "2026-01-20", 2.0)  # 2-for-1: the first report is 2,000,000 on today's basis
    out = short_features(interest, None, _shares(day, "A", 20_000_000), splits, day, ["A"])
    assert out["short_chg"]["A"].iloc[0] == pytest.approx(0.0)
    assert out["short_pct_shares"]["A"].iloc[0] == pytest.approx(0.10)


def test_a_report_older_than_45_days_reads_missing():
    interest = _interest("A", ["2025-12-31", "2026-01-15"], [900_000, 1_000_000])  # known 2026-02-03 for the second
    days = pd.DatetimeIndex(["2026-03-01", "2026-03-02", "2026-03-03"])  # 45, 46 and 47 days after 2026-01-15
    out = short_features(interest, None, _shares(days, "A", 10_000_000), _no_splits(), days, ["A"])
    for name in ("short_pct_shares", "days_to_cover", "short_chg"):
        assert out[name]["A"].isna().tolist() == [False, True, True]
    assert out["short_chg"]["A"].iloc[0] == pytest.approx(0.01)


def test_a_symbol_finra_does_not_list_reads_missing():
    interest = _interest("A", ["2026-01-15"], [1_000_000])
    volume = _volume("A", _sessions_before("2026-02-10", 12), short=40, total=100)
    days = pd.DatetimeIndex(["2026-02-10"])
    shares = pd.DataFrame({"A": 10_000_000.0, "B": 10_000_000.0}, index=days)
    out = short_features(interest, volume, shares, _no_splits(), days, ["A", "B"])
    assert list(out) == SHORT_FEATURES
    assert out["short_pct_shares"]["A"].notna().all() and out["short_vol_ratio_20d"]["A"].notna().all()
    for name in SHORT_FEATURES:
        assert list(out[name].columns) == ["A", "B"] and out[name]["B"].isna().all()


def test_a_missing_source_reads_missing_in_its_columns():
    days = pd.DatetimeIndex(["2026-02-10"])
    out = short_features(None, None, _shares(days, "A", 1.0), _no_splits(), days, ["A"])
    assert list(out) == SHORT_FEATURES
    assert all(frame["A"].isna().all() for frame in out.values())


def test_short_interest_without_shares_reads_missing():
    interest = _interest("A", ["2026-01-15"], [1_000_000])
    days = pd.DatetimeIndex(["2026-02-10"])
    shares = _shares(days, "A", np.nan)
    out = short_features(interest, None, shares, _no_splits(), days, ["A"])
    assert np.isnan(out["short_pct_shares"]["A"].iloc[0])
    assert out["days_to_cover"]["A"].iloc[0] == 2.0  # FINRA's own value needs no share count


def test_short_volume_ratio_needs_ten_of_twenty_sessions():
    nine = _volume("A", _sessions_before("2026-06-30", 9), short=40, total=100)
    ten = _volume("A", _sessions_before("2026-06-30", 10), short=40, total=100)
    assert np.isnan(_ratio_on(nine, "2026-06-30"))
    assert _ratio_on(ten, "2026-06-30") == pytest.approx(0.40)


def test_short_volume_ratio_reads_the_last_twenty_file_days_not_the_symbols_last_rows():
    sessions = _sessions_before("2026-06-30", 30)  # oldest first
    b = _volume("B", sessions, short=50, total=100)  # B makes all 30 sessions file days
    old = _volume("A", sessions[:10], short=90, total=100)
    twelve = pd.concat([b, old, _volume("A", sessions[-12:], short=30, total=100)])
    nine = pd.concat([b, old, _volume("A", sessions[-9:], short=30, total=100)])
    assert _ratio_on(twelve, "2026-06-30") == pytest.approx(0.30)  # A's ten older rows are outside the window
    assert np.isnan(_ratio_on(nine, "2026-06-30"))


def test_short_volume_of_the_row_day_is_not_read_and_empty_days_are_skipped():
    sessions = _sessions_before("2026-06-30", 12)
    rows = pd.concat([
        _volume("A", sessions, short=30, total=100),
        _volume("A", ["2026-06-30"], short=100, total=100),  # the row day's own file: not known yet
        _volume("A", ["2026-06-26"], short=0, total=0),  # a row without volume is not a session of the symbol's
    ])
    rows = rows.drop_duplicates(["symbol", "day"], keep="last")
    assert _ratio_on(rows, "2026-06-30") == pytest.approx(0.30)
