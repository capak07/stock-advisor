from datetime import timedelta

import numpy as np
import pandas as pd

from advisor.collectors.base import FEATURE_DAY_MARGIN_DAYS
from advisor.collectors.sec_events import LOOKBACK
from advisor.model.events import DAYS_SINCE_8K_CAP, EVENT_ITEMS, EVENTS_FEATURES, events_features


def _eightks(rows: list[tuple[str | None, str, list[str]]], symbol: str = "AAA") -> pd.DataFrame:
    """One symbol's 8-Ks as (true UTC acceptance time or None, filing date, items)."""
    return pd.DataFrame({
        "symbol": symbol,
        "accession": [f"0000000000-26-{i:06d}" for i in range(len(rows))],
        "form": "8-K",
        "filing_date": [pd.Timestamp(r[1]).date() for r in rows],
        "accepted_at": pd.to_datetime([r[0] for r in rows], utc=True),
        "items": [r[2] for r in rows],
    })


def _holders(rows: list[tuple[str, str]], symbol: str = "AAA") -> pd.DataFrame:
    """One symbol's 13D/Gs as (form, true UTC acceptance time)."""
    return pd.DataFrame({
        "symbol": symbol,
        "accession": [f"0000000000-26-{i:06d}" for i in range(len(rows))],
        "form": [r[0] for r in rows],
        "filing_date": [pd.Timestamp(r[1]).date() for r in rows],
        "accepted_at": pd.to_datetime([r[1] for r in rows], utc=True),
        "activist": ["13D" in r[0] for r in rows],
    })


def _days(*days: str) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(pd.to_datetime(list(days)))


def _at(day: str, offset: int) -> str:
    return (pd.Timestamp(day) + pd.Timedelta(days=offset)).strftime("%Y-%m-%d 15:00")


def test_the_feature_names_and_the_cap():
    assert EVENT_ITEMS == ("5.02", "1.01", "2.01", "4.02", "3.01")
    assert EVENTS_FEATURES == ["ev_502_90d", "ev_101_90d", "ev_201_90d", "ev_402_90d", "ev_301_90d",
                               "days_since_8k", "activist_13d_180d", "passive_13g_90d"]
    assert DAYS_SINCE_8K_CAP == 120 and FEATURE_DAY_MARGIN_DAYS == 7
    # live sees the cap's 120 days of 8-Ks counted from a pre-open run's earlier feature day (Ruling R13)
    assert LOOKBACK == timedelta(days=DAYS_SINCE_8K_CAP + FEATURE_DAY_MARGIN_DAYS)


def test_item_counts_over_90_days_by_acceptance():
    # 21:00 UTC is 16:00 EST on March 2: known on the 2nd, read from the 3rd
    filings = _eightks([("2026-03-02 21:00", "2026-03-02", ["5.02", "9.01"])])
    days = _days("2026-03-02", "2026-03-03", "2026-05-31", "2026-06-01")
    out = events_features(filings, None, {"AAA"}, days, ["AAA"])
    assert list(out) == EVENTS_FEATURES
    assert out["ev_502_90d"]["AAA"].tolist() == [0, 1, 1, 0]  # 2026-05-31 - 90 days = 2026-03-02
    assert out["ev_101_90d"]["AAA"].tolist() == [0, 0, 0, 0]
    assert out["days_since_8k"]["AAA"].tolist() == [120, 1, 90, 91]


def test_each_item_counts_the_filings_that_list_it():
    day = "2026-06-01"
    filings = _eightks([
        (_at(day, -5), day, ["1.01", "2.01"]),
        (_at(day, -20), day, ["1.01"]),
        (_at(day, -30), day, ["4.02", "3.01", "5.02"]),
        (_at(day, -120), day, ["5.02"]),  # outside the 90 days
    ])
    out = events_features(filings, None, {"AAA"}, _days(day), ["AAA"])
    counts = {name: out[name].loc[day, "AAA"] for name in EVENTS_FEATURES[:5]}
    assert counts == {"ev_502_90d": 1, "ev_101_90d": 2, "ev_201_90d": 1, "ev_402_90d": 1, "ev_301_90d": 1}
    assert out["days_since_8k"].loc[day, "AAA"] == 5


def test_an_8k_without_acceptance_time_waits_one_session_after_filing():
    filings = _eightks([(None, "2026-07-02", ["5.02"])])  # July 3 is a holiday: known on the 6th
    days = _days("2026-07-03", "2026-07-06", "2026-07-07")
    out = events_features(filings, None, {"AAA"}, days, ["AAA"])
    assert out["ev_502_90d"]["AAA"].tolist() == [0, 0, 1]
    assert out["days_since_8k"]["AAA"].tolist() == [120, 120, 1]


def test_days_since_8k_is_120_for_a_covered_symbol_without_one():
    filings = _eightks([(_at("2026-01-02", 0), "2026-01-02", ["2.02"])])
    days = _days("2026-03-02", "2026-06-01")
    out = events_features(filings, _holders([]), {"AAA", "BBB"}, days, ["AAA", "BBB", "CCC"])
    assert out["days_since_8k"]["AAA"].tolist() == [59, 120]  # capped once the 8-K is over 120 days old
    assert out["days_since_8k"]["BBB"].tolist() == [120, 120]  # SEC facts, no 8-K
    for name in EVENTS_FEATURES[:5] + ["activist_13d_180d", "passive_13g_90d"]:
        assert out[name]["BBB"].tolist() == [0, 0]  # covered: no filings reads zero
    for name in EVENTS_FEATURES:
        assert out[name]["CCC"].isna().all()  # no SEC facts: missing, never zero


def test_13d_and_13g_indicators_use_their_own_windows():
    day = "2026-09-01"
    holders = _holders([("SCHEDULE 13D", _at(day, -170)), ("SCHEDULE 13G", _at(day, -100))])
    out = events_features(_eightks([]), holders, {"AAA"}, _days(day), ["AAA"])
    assert out["activist_13d_180d"].loc[day, "AAA"] == 1
    assert out["passive_13g_90d"].loc[day, "AAA"] == 0


def test_the_holder_features_are_indicators_not_counts():
    day = "2026-09-01"
    holders = _holders([("SCHEDULE 13G", _at(day, -10)), ("SCHEDULE 13G/A", _at(day, -20)),
                        ("SC 13D", _at(day, -30)), ("SC 13D/A", _at(day, -40))])
    out = events_features(_eightks([]), holders, {"AAA"}, _days(day), ["AAA"])
    assert out["activist_13d_180d"].loc[day, "AAA"] == 1
    assert out["passive_13g_90d"].loc[day, "AAA"] == 1


def test_a_missing_source_reads_missing_not_zero():
    days = _days("2026-06-01")
    out = events_features(None, _holders([]), {"AAA"}, days, ["AAA"])
    for name in EVENTS_FEATURES[:6]:
        assert np.isnan(out[name].loc["2026-06-01", "AAA"])
    assert out["activist_13d_180d"].loc["2026-06-01", "AAA"] == 0
    out = events_features(_eightks([]), None, {"AAA"}, days, ["AAA"])
    assert out["days_since_8k"].loc["2026-06-01", "AAA"] == 120
    assert out["activist_13d_180d"]["AAA"].isna().all() and out["passive_13g_90d"]["AAA"].isna().all()


def test_items_read_back_from_parquet_as_arrays_still_count():
    filings = _eightks([(_at("2026-05-01", 0), "2026-05-01", ["5.02"])])
    filings["items"] = [np.array(["5.02", "9.01"], dtype=object)]
    out = events_features(filings, None, {"AAA"}, _days("2026-06-01"), ["AAA"])
    assert out["ev_502_90d"].loc["2026-06-01", "AAA"] == 1
