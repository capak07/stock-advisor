import numpy as np
import pandas as pd

from advisor.model.groups import covered_symbols, days_since, sec_known, window_count


def test_a_record_known_on_the_row_day_is_not_read():
    events = pd.DataFrame({"symbol": ["A", "A"], "known": pd.to_datetime(["2026-03-02", "2026-03-10"])})
    counts = window_count(events, pd.DatetimeIndex(["2026-03-10", "2026-03-11"]), ["A", "B"], 90)
    assert counts.loc["2026-03-10", "A"] == 1 and counts.loc["2026-03-11", "A"] == 2
    assert counts["B"].tolist() == [0, 0]


def test_the_window_drops_a_record_after_its_days():
    events = pd.DataFrame({"symbol": ["A"], "known": pd.to_datetime(["2026-01-01"])})
    counts = window_count(events, pd.DatetimeIndex(["2026-03-31", "2026-04-01", "2026-04-02"]), ["A"], 90)
    assert counts["A"].tolist() == [1, 1, 0]  # 2026-04-01 - 90 days = 2026-01-01, still inside


def test_days_since_caps_and_is_missing_before_the_first_record():
    events = pd.DataFrame({"symbol": ["A"], "known": pd.to_datetime(["2025-01-02"])})
    out = days_since(events, pd.DatetimeIndex(["2025-01-02", "2025-01-12", "2026-01-12"]), ["A"], 120)
    assert np.isnan(out["A"].iloc[0]) and out["A"].iloc[1] == 10 and out["A"].iloc[2] == 120


def test_an_sec_filing_without_an_acceptance_time_is_known_one_session_after_filing():
    known = sec_known(pd.Series([pd.NaT, pd.Timestamp("2026-07-02 21:30", tz="UTC")]),
                      pd.Series(pd.to_datetime(["2026-07-02", "2026-07-02"])))
    assert known.tolist() == [pd.Timestamp("2026-07-06"), pd.Timestamp("2026-07-02")]  # July 3 is a holiday


def test_the_acceptance_date_is_the_eastern_date_not_the_utc_one():
    accepted = pd.Series(pd.to_datetime(["2026-03-10 02:30", "2026-03-10 13:59", "2026-07-01 03:59"], utc=True))
    known = sec_known(accepted, pd.Series(pd.to_datetime(["2026-03-10"] * 3)))
    # 02:30 UTC is still March 9 in New York; 13:59 UTC is 09:59 EDT on the 10th; 03:59 UTC is 23:59 EDT on June 30
    assert known.tolist() == [pd.Timestamp("2026-03-09"), pd.Timestamp("2026-03-10"), pd.Timestamp("2026-06-30")]
    assert known.dtype == np.dtype("datetime64[ns]")


def test_sec_known_keeps_the_index_and_leaves_a_missing_filing_date_missing():
    accepted = pd.Series([pd.NaT, pd.NaT], index=[7, 9], dtype="datetime64[ns, UTC]")
    known = sec_known(accepted, pd.Series(pd.to_datetime(["2026-03-06", None]), index=[7, 9]))
    assert known.index.tolist() == [7, 9]
    assert known.iloc[0] == pd.Timestamp("2026-03-09") and pd.isna(known.iloc[1])  # a Friday filing -> Monday


def test_window_count_sums_a_weight_and_ignores_other_symbols_and_missing_dates():
    events = pd.DataFrame({
        "symbol": ["A", "A", "A", "Z", "A"],
        "known": pd.to_datetime(["2026-03-01", "2026-03-05", "2026-03-05", "2026-03-05", None]),
        "value": [1.5, 2.0, 4.0, 100.0, 50.0],
    })
    days = pd.DatetimeIndex(["2026-03-05", "2026-03-06", "2026-03-14"], name="day")
    counts = window_count(events, days, ["A", "B"], 10, weight="value")
    assert counts["A"].tolist() == [1.5, 7.5, 6.0]  # on 03-14 the window starts 03-04, so 03-01 has left
    assert counts["B"].tolist() == [0, 0, 0] and counts.index.name == "day"
    assert list(counts.columns) == ["A", "B"]


def test_window_count_with_no_events_is_all_zero():
    empty = pd.DataFrame({"symbol": [], "known": pd.to_datetime([])})
    counts = window_count(empty, pd.DatetimeIndex(["2026-03-05"]), ["A"], 30)
    assert counts["A"].tolist() == [0]


def test_days_since_reads_the_latest_record_before_the_day_per_symbol():
    events = pd.DataFrame({"symbol": ["A", "A", "B"], "known": pd.to_datetime(["2026-03-01", "2026-03-08", "2026-03-09"])})
    out = days_since(events, pd.DatetimeIndex(["2026-03-08", "2026-03-09", "2026-03-10"]), ["A", "B", "C"], 30)
    assert out["A"].tolist() == [7, 1, 2]  # a record known on the day itself is not read
    assert np.isnan(out["B"].iloc[0]) and np.isnan(out["B"].iloc[1]) and out["B"].iloc[2] == 1
    assert out["C"].isna().all()


def test_covered_symbols_are_those_whose_cik_has_a_fact():
    facts = pd.DataFrame({"cik": [1, 1, 3]})
    tickers = pd.DataFrame({"symbol": ["A", "B", "C", "D"], "cik": [1, 2, 3, np.nan]})
    assert covered_symbols(facts, tickers) == {"A", "C"}
    assert covered_symbols(facts.iloc[:0], tickers) == set()
