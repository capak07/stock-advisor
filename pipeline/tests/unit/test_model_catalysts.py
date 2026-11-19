import numpy as np
import pandas as pd

from advisor.collectors.openfda import APPROVAL_WINDOW_DAYS, FDA_LAG_DAYS, RECALL_WINDOW_DAYS
from advisor.model.catalysts import CATALYSTS_FEATURES, catalysts_features


def _events(rows: list[tuple[str, str, str, str]]) -> pd.DataFrame:
    """(symbol, kind, day, event_id) rows, with `day` as date values like the history file."""
    return pd.DataFrame({
        "symbol": pd.Series([r[0] for r in rows], dtype="string"),
        "kind": pd.Series([r[1] for r in rows], dtype="string"),
        "day": [pd.Timestamp(r[2]).date() for r in rows],
        "event_id": pd.Series([r[3] for r in rows], dtype="string"),
    })


def _days(*days: str) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(pd.to_datetime(list(days)))


def _offset(day: str, offset: int) -> str:
    return (pd.Timestamp(day) + pd.Timedelta(days=offset)).strftime("%Y-%m-%d")


def test_the_feature_names_and_windows():
    assert CATALYSTS_FEATURES == ["fda_approvals_180d", "fda_recalls_90d"]
    assert (FDA_LAG_DAYS, APPROVAL_WINDOW_DAYS, RECALL_WINDOW_DAYS) == (7, 180, 90)


def test_an_approval_counts_a_week_after_its_date_for_180_days():
    approved = "2026-01-05"
    events = _events([("AAA", "approval", approved, "NDA1:original:20260105:0")])
    known = _offset(approved, FDA_LAG_DAYS)
    days = _days(
        approved, known,  # not yet known, then known on the row day: neither reads it
        _offset(known, 1),  # the first day after the known day
        _offset(known, APPROVAL_WINDOW_DAYS),  # the last day inside the window
        _offset(known, APPROVAL_WINDOW_DAYS + 1),
    )
    out = catalysts_features(events, days, ["AAA"])
    assert list(out) == CATALYSTS_FEATURES
    assert out["fda_approvals_180d"]["AAA"].tolist() == [0, 0, 1, 1, 0]
    assert out["fda_recalls_90d"]["AAA"].tolist() == [0, 0, 0, 0, 0]


def test_a_recall_counts_for_90_days_and_does_not_count_as_an_approval():
    events = _events([("AAA", "recall", "2026-02-02", "R1")])
    known = _offset("2026-02-02", FDA_LAG_DAYS)
    days = _days(known, _offset(known, 1), _offset(known, RECALL_WINDOW_DAYS), _offset(known, RECALL_WINDOW_DAYS + 1))
    out = catalysts_features(events, days, ["AAA"])
    assert out["fda_recalls_90d"]["AAA"].tolist() == [0, 1, 1, 0]
    assert out["fda_approvals_180d"]["AAA"].tolist() == [0, 0, 0, 0]


def test_one_recall_event_listing_three_products_counts_once():
    events = _events([
        ("AAA", "recall", "2026-02-02", "R1"),
        ("AAA", "recall", "2026-02-02", "R1"),
        ("AAA", "recall", "2026-02-02", "R1"),
        ("AAA", "recall", "2026-02-09", "R2"),
    ])
    out = catalysts_features(events, _days("2026-03-01"), ["AAA"])
    assert out["fda_recalls_90d"]["AAA"].tolist() == [2]


def test_every_symbol_reads_zero_without_events_and_missing_without_the_source():
    days = _days("2026-03-01", "2026-03-02")
    events = _events([("AAA", "approval", "2026-02-01", "NDA1:original:20260201:0")])
    out = catalysts_features(events, days, ["AAA", "BBB"])
    assert out["fda_approvals_180d"].to_dict("list") == {"AAA": [1, 1], "BBB": [0, 0]}
    assert out["fda_recalls_90d"].to_dict("list") == {"AAA": [0, 0], "BBB": [0, 0]}
    none = catalysts_features(None, days, ["AAA", "BBB"])
    assert list(none) == CATALYSTS_FEATURES
    for frame in none.values():
        assert list(frame.columns) == ["AAA", "BBB"] and frame.index.equals(days)
        assert frame.isna().all().all()
    empty = catalysts_features(_events([]), days, ["AAA"])  # a source that ran and found nothing
    assert not np.isnan(empty["fda_approvals_180d"].to_numpy()).any()
    assert empty["fda_recalls_90d"]["AAA"].tolist() == [0, 0]


def test_an_event_listed_on_several_dates_is_dated_by_its_earliest_row():
    """Ruling R12: whatever order the rows come in, the earliest date dates the event."""
    events = _events([
        ("AAA", "recall", "2026-04-20", "R1"),  # listed again later, first in the frame
        ("AAA", "recall", "2026-01-05", "R1"),
        ("AAA", "approval", "2026-05-01", "NDA1:x"),
        ("AAA", "approval", "2026-01-05", "NDA1:x"),
    ])
    first_known = _offset("2026-01-05", FDA_LAG_DAYS)
    later_known = _offset("2026-04-20", FDA_LAG_DAYS)
    days = _days(_offset(first_known, 1), _offset(later_known, 1), _offset(first_known, APPROVAL_WINDOW_DAYS + 1))
    out = catalysts_features(events, days, ["AAA"])
    assert out["fda_recalls_90d"]["AAA"].tolist() == [1, 0, 0]  # the later listing does not renew it
    assert out["fda_approvals_180d"]["AAA"].tolist() == [1, 1, 0]
