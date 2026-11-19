import numpy as np
import pandas as pd
from pytest import approx

from advisor.model.estimates import (
    ESTIMATE_STALE_DAYS,
    ESTIMATES_FEATURES,
    NEXT_REPORT_DAYS,
    STREAK_REPORTS,
    SURPRISE_CLIP,
    estimates_features,
    report_timing,
)


def _reports(rows: list[tuple[str, float | None, float | None]], symbol: str = "AAA") -> pd.DataFrame:
    """One symbol's (report day, estimate, actual) rows in the long frame `estimates_history` writes."""
    return pd.DataFrame({
        "symbol": symbol,
        "report_day": pd.to_datetime([r[0] for r in rows]).astype("datetime64[ns]"),
        "timing": None,
        "eps_estimate": [r[1] for r in rows],
        "eps_actual": [r[2] for r in rows],
    })


def _days(*days: str) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(pd.to_datetime(list(days)))


def test_the_constants():
    assert ESTIMATES_FEATURES == ["eps_surprise_last", "eps_beat_streak", "days_to_next_report"]
    assert (SURPRISE_CLIP, STREAK_REPORTS, NEXT_REPORT_DAYS, ESTIMATE_STALE_DAYS) == (1.0, 4, 364, 200)


def test_a_report_is_read_from_the_session_after_it():
    reports = _reports([("2025-11-18", 1.0, 1.1)])
    out = estimates_features(reports, _days("2025-11-18", "2025-11-19"), ["AAA"])
    assert list(out) == ESTIMATES_FEATURES
    assert np.isnan(out["eps_surprise_last"]["AAA"].iloc[0])  # the report day itself: not yet read
    assert out["eps_surprise_last"]["AAA"].iloc[1] == approx(0.1)
    # the same holds for the date estimate: a report on the row day gives no "last year's" date yet
    assert np.isnan(out["days_to_next_report"]["AAA"].iloc[0])
    assert out["days_to_next_report"]["AAA"].iloc[1] == 363


def test_surprise_is_against_the_absolute_consensus_and_clipped():
    day = "2025-11-19"
    loss = estimates_features(_reports([("2025-11-10", -0.50, -0.40)]), _days(day), ["AAA"])
    assert loss["eps_surprise_last"].loc[day, "AAA"] == approx(0.20)  # a smaller loss beats
    big = estimates_features(_reports([("2025-11-10", 0.10, 0.50)]), _days(day), ["AAA"])
    assert big["eps_surprise_last"].loc[day, "AAA"] == 1.0  # (0.5 - 0.1) / 0.1 = 4, clipped
    miss = estimates_features(_reports([("2025-11-10", 1.0, -5.0)]), _days(day), ["AAA"])
    assert miss["eps_surprise_last"].loc[day, "AAA"] == -1.0


def test_surprise_is_missing_for_a_zero_estimate_a_stale_report_or_no_numbers():
    day = "2025-11-19"
    zero = estimates_features(_reports([("2025-11-10", 0.0, 0.3)]), _days(day), ["AAA"])
    assert np.isnan(zero["eps_surprise_last"].loc[day, "AAA"])
    # the latest report with both numbers decides: an older usable one is not a fallback
    older = estimates_features(_reports([("2025-10-01", 1.0, 1.2), ("2025-11-10", 0.0, 0.3)]),
                               _days(day), ["AAA"])
    assert np.isnan(older["eps_surprise_last"].loc[day, "AAA"])
    last = pd.Timestamp(day) - pd.Timedelta(days=ESTIMATE_STALE_DAYS)
    fresh = estimates_features(_reports([(str(last.date()), 1.0, 1.2)]), _days(day), ["AAA"])
    assert fresh["eps_surprise_last"].loc[day, "AAA"] == approx(0.2)  # 200 days old: still read
    stale = estimates_features(_reports([(str((last - pd.Timedelta(days=1)).date()), 1.0, 1.2)]),
                               _days(day), ["AAA"])
    assert np.isnan(stale["eps_surprise_last"].loc[day, "AAA"])
    no_actual = estimates_features(_reports([("2025-11-10", 1.0, None)]), _days(day), ["AAA"])
    assert np.isnan(no_actual["eps_surprise_last"].loc[day, "AAA"])
    skipped = estimates_features(_reports([("2025-10-01", 1.0, 1.2), ("2025-11-10", 1.0, None)]),
                                 _days(day), ["AAA"])
    assert skipped["eps_surprise_last"].loc[day, "AAA"] == approx(0.2)  # a row without an actual is skipped


def test_the_streak_needs_four_reports():
    rows = [("2025-01-29", 1.0, 1.1), ("2025-04-30", 1.0, 0.9), ("2025-07-30", 1.0, 1.2), ("2025-10-29", 1.0, 1.0)]
    reports = _reports(rows)
    days = _days("2025-07-31", "2025-10-30", "2025-11-19")
    out = estimates_features(reports, days, ["AAA", "BBB"])
    assert np.isnan(out["eps_beat_streak"]["AAA"].iloc[0])  # three reports so far
    assert out["eps_beat_streak"]["AAA"].iloc[1] == 2  # 1.1, 1.2 beat; 0.9 missed; 1.0 equals: not a beat
    assert out["eps_beat_streak"]["BBB"].isna().all()
    more = _reports(rows + [("2025-11-12", 1.0, 2.0)])
    assert estimates_features(more, days, ["AAA"])["eps_beat_streak"]["AAA"].iloc[2] == 2  # the last four: 0.9, 1.2, 1.0, 2.0
    sparse = _reports(rows[:3] + [("2025-10-29", 1.0, None)])
    assert np.isnan(estimates_features(sparse, days, ["AAA"])["eps_beat_streak"]["AAA"].iloc[2])


def test_next_report_is_last_years_same_quarter_plus_364_days():
    rows = [("2025-01-29", 1.0, 1.1), ("2025-04-30", 1.0, 1.1), ("2025-07-30", 1.0, 1.1), ("2025-10-29", 1.0, 1.1)]
    out = estimates_features(_reports(rows), _days("2025-11-19"), ["AAA"])
    assert out["days_to_next_report"].loc["2025-11-19", "AAA"] == 70  # 2026-01-28 minus 2025-11-19
    # a report more than a year back no longer counts; the next one is then the following quarter's
    later = estimates_features(_reports(rows), _days("2026-02-01", "2026-12-01"), ["AAA"])
    assert later["days_to_next_report"]["AAA"].iloc[0] == 87  # 2025-04-30 + 364 = 2026-04-29
    assert np.isnan(later["days_to_next_report"]["AAA"].iloc[1])  # all four are more than 364 days back


def test_a_scheduled_future_report_is_never_read():
    rows = [("2025-01-29", 1.0, 1.1), ("2025-04-30", 1.0, 1.1), ("2025-07-30", 1.0, 1.1), ("2025-10-29", 1.0, 1.1)]
    days = _days("2025-11-19")
    base = estimates_features(_reports(rows), days, ["AAA"])
    with_future = estimates_features(_reports(rows + [("2025-12-01", 1.2, None)]), days, ["AAA"])
    for name in ESTIMATES_FEATURES:
        pd.testing.assert_frame_equal(base[name], with_future[name])
    assert base["days_to_next_report"].loc["2025-11-19", "AAA"] == 70  # not 12, the scheduled date's distance


def test_without_reports_every_feature_is_missing():
    days = _days("2025-11-19")
    for reports in (None, _reports([("2025-11-10", 1.0, 1.1)], symbol="BBB")):
        out = estimates_features(reports, days, ["AAA"])
        assert list(out) == ESTIMATES_FEATURES
        assert all(frame["AAA"].isna().all() for frame in out.values())


def test_a_reported_and_a_scheduled_row_on_one_day_count_once():
    rows = [("2025-10-29", 1.0, None), ("2025-10-29", 1.0, 1.5)]
    out = estimates_features(_reports(rows), _days("2025-11-19"), ["AAA"])
    assert out["eps_surprise_last"].loc["2025-11-19", "AAA"] == approx(0.5)


def test_report_timing_reads_before_open_after_close_and_unknown():
    stamps = pd.Series(pd.to_datetime([
        "2025-10-29 07:00", "2025-10-29 16:05", "2025-10-29 00:00", "2025-10-29 12:00",
        "2025-10-29 09:30", "2025-10-29 16:00", "2025-10-29 09:29",
    ]).tz_localize("America/New_York"))
    timing = report_timing(stamps)
    assert timing.tolist() == ["before-open", "after-close", None, None, None, "after-close", "before-open"]
    assert timing.iloc[2] is None
    assert report_timing(stamps.dt.tz_localize(None)).tolist() == timing.tolist()  # naive: read as ET
    assert report_timing(stamps.dt.tz_convert("UTC")).tolist() == timing.tolist()


def test_a_day_with_a_time_of_day_never_reads_a_report_from_its_own_date():
    """A live timestamp (15:15 on the report day) is still the report day: the report is not yet read."""
    reports = _reports([("2025-11-18", 1.0, 1.1)])
    days = pd.DatetimeIndex([pd.Timestamp("2025-11-18 15:15"), pd.Timestamp("2025-11-19 09:00")])
    out = estimates_features(reports, days, ["AAA"])
    assert np.isnan(out["eps_surprise_last"]["AAA"].iloc[0])
    assert np.isnan(out["days_to_next_report"]["AAA"].iloc[0])
    assert out["eps_surprise_last"]["AAA"].iloc[1] == approx(0.1)
    assert out["days_to_next_report"]["AAA"].iloc[1] == 363
