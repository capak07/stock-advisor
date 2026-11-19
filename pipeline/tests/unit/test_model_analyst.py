import pandas as pd

from advisor.model.analyst import (
    ANALYST_CAP_ROWS,
    ANALYST_FEATURES,
    DOWNGRADE_CAP,
    analyst_features,
    coverage,
    coverage_from,
)


def _events(rows: list[tuple[str, str, str | None]], symbol: str = "AAA") -> pd.DataFrame:
    """One symbol's (graded_at naive UTC, action, price target action) rows."""
    return pd.DataFrame({
        "symbol": symbol,
        "graded_at": pd.to_datetime([r[0] for r in rows]).astype("datetime64[ns]"),
        "firm": "Firm",
        "action": [r[1] for r in rows],
        "from_grade": "Hold",
        "to_grade": "Buy",
        "price_target_action": [r[2] for r in rows],
    })


def _days(*days: str) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(pd.to_datetime(list(days)))


def _at(day: str, offset: int) -> str:
    return (pd.Timestamp(day) + pd.Timedelta(days=offset)).strftime("%Y-%m-%d 15:00")


def test_counts_are_missing_before_the_first_recorded_event():
    events = _events([("2024-03-01 15:00", "up", None)])
    days = _days("2024-02-28", "2024-03-01", "2024-03-04")
    out = analyst_features(events, coverage(events), days, ["AAA", "BBB"])
    assert list(out) == ANALYST_FEATURES
    for name in ANALYST_FEATURES:
        assert out[name]["AAA"].iloc[:2].isna().all()  # up to and including the oldest known day
        assert out[name]["BBB"].isna().all()  # no recorded event: never read as zero
    assert out["net_upgrades_30d"]["AAA"].iloc[2] == 1


def test_net_upgrades_over_30_and_90_days():
    day = "2024-06-03"
    events = _events([
        (_at(day, -10), "up", None),
        (_at(day, -40), "up", None),
        (_at(day, -50), "down", None),
        (_at(day, -200), "main", None),
    ])
    out = analyst_features(events, coverage(events), _days(day), ["AAA"])
    assert out["net_upgrades_30d"].loc[day, "AAA"] == 1
    assert out["net_upgrades_90d"].loc[day, "AAA"] == 1


def test_target_raises_minus_cuts():
    day = "2024-06-03"
    events = _events([
        (_at(day, -5), "main", "Raises"),
        (_at(day, -20), "main", "Raises"),
        (_at(day, -30), "main", "Lowers"),
        (_at(day, -80), "up", "Lowers"),
        (_at(day, -95), "main", "Raises"),  # outside 90 days
        (_at(day, -3), "main", "Maintains"),
    ])
    out = analyst_features(events, coverage(events), _days(day), ["AAA"])
    assert out["net_target_raises_90d"].loc[day, "AAA"] == 0  # 2 raises - 2 cuts
    assert out["net_upgrades_90d"].loc[day, "AAA"] == 1


def test_an_event_graded_on_the_row_day_is_not_read():
    events = _events([
        ("2024-03-01 15:00", "up", "Raises"),
        ("2024-03-05 15:00", "down", "Lowers"),
    ])
    out = analyst_features(events, coverage(events), _days("2024-03-05", "2024-03-06"), ["AAA"])
    assert out["net_upgrades_30d"]["AAA"].tolist() == [1, 0]
    assert out["net_target_raises_90d"]["AAA"].tolist() == [1, 0]
    assert out["days_since_downgrade"]["AAA"].isna().iloc[0]
    assert out["days_since_downgrade"]["AAA"].iloc[1] == 1


def test_a_grade_after_the_close_is_known_by_its_eastern_date():
    # 2024-03-02 02:00 UTC is 21:00 ET on 2024-03-01
    events = _events([("2024-03-02 02:00", "up", None), ("2024-03-01 15:00", "up", None)])
    out = analyst_features(events, coverage(events), _days("2024-03-01", "2024-03-02"), ["AAA"])
    assert out["net_upgrades_30d"]["AAA"].isna().iloc[0]
    assert out["net_upgrades_30d"]["AAA"].iloc[1] == 2


def test_a_capped_symbol_reads_missing_until_its_window_is_covered():
    events = _events([("2020-01-02 15:00", "main", "Raises"), ("2020-06-01 15:00", "down", None)])
    capped = pd.DataFrame({"symbol": ["AAA"], "oldest": [pd.Timestamp("2020-01-02")], "rows": [ANALYST_CAP_ROWS]})
    days = _days("2020-03-31", "2020-04-02", "2020-12-31", "2021-01-04")
    out = analyst_features(events, capped, days, ["AAA"])
    for name in ("net_upgrades_30d", "net_upgrades_90d", "net_target_raises_90d"):
        assert out[name]["AAA"].isna().tolist() == [True, False, False, False]
    assert out["days_since_downgrade"]["AAA"].isna().tolist() == [True, True, True, False]
    assert out["days_since_downgrade"]["AAA"].iloc[3] == 217

    # the same history from an uncapped symbol is read as soon as it can be
    free = analyst_features(events, capped.assign(rows=ANALYST_CAP_ROWS - 1), days, ["AAA"])
    assert free["net_upgrades_90d"]["AAA"].notna().all()
    assert free["days_since_downgrade"]["AAA"].isna().tolist() == [True, True, False, False]
    assert free["days_since_downgrade"]["AAA"].iloc[2] == 213


def test_days_since_downgrade_caps_at_365():
    events = _events([("2020-01-02 15:00", "down", None), ("2022-01-03 15:00", "up", None)])
    days = _days("2020-01-03", "2020-06-01", "2022-02-01")
    out = analyst_features(events, coverage(events), days, ["AAA"])
    assert out["days_since_downgrade"]["AAA"].tolist() == [1, 151, DOWNGRADE_CAP]


def test_coverage_from_takes_the_et_date_of_the_oldest_grade():
    oldest = pd.Series([pd.Timestamp("2020-01-02 03:00")], index=["AAA"])
    out = coverage_from(oldest, pd.Series([7], index=["AAA"]))
    assert list(out.columns) == ["symbol", "oldest", "rows"]
    assert out["symbol"].tolist() == ["AAA"]
    assert out["oldest"].iloc[0] == pd.Timestamp("2020-01-01")
    assert out["rows"].iloc[0] == 7


def test_coverage_counts_each_symbols_rows_and_oldest_event():
    events = pd.concat([
        _events([("2020-01-02 15:00", "up", None), ("2020-03-02 15:00", "up", None)], "AAA"),
        _events([("2021-05-05 15:00", "down", None)], "BBB"),
    ])
    out = coverage(events).set_index("symbol")
    assert out.loc["AAA", "rows"] == 2 and out.loc["AAA", "oldest"] == pd.Timestamp("2020-01-02")
    assert out.loc["BBB", "rows"] == 1 and out.loc["BBB", "oldest"] == pd.Timestamp("2021-05-05")


def test_a_missing_source_reads_missing():
    out = analyst_features(None, None, _days("2024-01-02"), ["AAA"])
    assert list(out) == ANALYST_FEATURES
    assert all(frame.isna().all().all() for frame in out.values())


def test_an_empty_history_reads_missing():
    events = pd.DataFrame(columns=["symbol", "graded_at", "firm", "action", "from_grade", "to_grade",
                                   "price_target_action"]).astype({"graded_at": "datetime64[ns]"})
    out = analyst_features(events, coverage(events), _days("2024-01-02"), ["AAA"])
    assert all(frame.isna().all().all() for frame in out.values())
