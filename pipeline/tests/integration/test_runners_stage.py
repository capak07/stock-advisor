from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from advisor.runners.live import runners_stage
from advisor.runners.rule import STARTING, Bar
from advisor.store import repo
from fakes import FakeSec, info
from runner_data import AKAN_AFTER, akan, daily, filing

NOW = datetime(2026, 11, 16, 13, 15, tzinfo=UTC)  # Monday 8:15 a.m. in New York: D is Fri 2026-11-13


def test_an_ignition_yesterday_is_stored_waiting_with_a_preview_plan(db):
    got = runners_stage(db, {"AKAN": akan()}, [info("AKAN")], NOW)
    assert got == {"signals": 1, "split_suspect": 0, "entered": 0, "closed": 0, "open": 0, "unchecked": 1}
    [row] = repo.unsettled_runner_signals(db)
    assert (row["symbol"], row["name"], row["status"], row["rule_version"]) == ("AKAN", info("AKAN").name, "waiting", 0)
    assert (float(row["stop"]), float(row["target"]), row["hold_by"]) == (1.02, 2.04, date(2026, 11, 30))
    assert row["entry"] is None and row["warnings_checked"] is False


def test_running_the_same_morning_twice_changes_nothing(db):
    runners_stage(db, {"AKAN": akan()}, [info("AKAN")], NOW)
    assert runners_stage(db, {"AKAN": akan()}, [info("AKAN")], NOW)["signals"] == 0
    assert len(repo.unsettled_runner_signals(db)) == 1


def test_the_next_mornings_run_fills_the_entry_then_the_target_closes_it(db):
    runners_stage(db, {"AKAN": akan()}, [info("AKAN")], NOW)
    day2 = [*akan(), daily("AKAN", AKAN_AFTER[0])]
    assert runners_stage(db, {"AKAN": day2}, [info("AKAN")], NOW + timedelta(days=1))["entered"] == 1
    [row] = repo.unsettled_runner_signals(db)
    assert (row["status"], float(row["entry"]), float(row["stop"]), float(row["target"])) == ("open", 1.92, 1.44, 2.88)
    day4 = [*day2, daily("AKAN", AKAN_AFTER[1]), daily("AKAN", AKAN_AFTER[2])]
    assert runners_stage(db, {"AKAN": day4}, [info("AKAN")], NOW + timedelta(days=3))["closed"] == 1
    row = db.execute("select status, exit_price, gross_r, net_r, cost_r from runner_signals").fetchone()
    assert (row["status"], float(row["exit_price"]), float(row["gross_r"])) == ("target", 2.88, 2.0)
    assert float(row["net_r"]) == pytest.approx(2.0 - float(row["cost_r"]))


def test_a_bar_dated_today_is_ignored(db):  # Review Focus 3
    late = [*akan(), daily("AKAN", AKAN_AFTER[0])]  # Monday's bar present in Monday's run
    runners_stage(db, {"AKAN": late}, [info("AKAN")], NOW)
    [row] = repo.unsettled_runner_signals(db)
    assert (row["signal_day"], row["status"], row["entry"]) == (date(2026, 11, 13), "waiting", None)


def test_a_stale_last_bar_does_not_signal(db):
    assert runners_stage(db, {"AKAN": akan()}, [info("AKAN")], NOW + timedelta(days=1))["signals"] == 0


def test_no_bars_for_5_sessions_after_the_signal_skips_it(db):  # Review Focus 2
    runners_stage(db, {"AKAN": akan()}, [info("AKAN")], NOW)
    runners_stage(db, {"AKAN": akan()}, [info("AKAN")], datetime(2026, 11, 23, 13, 15, tzinfo=UTC))
    row = db.execute("select status, skip_reason from runner_signals").fetchone()
    assert (row["status"], row["skip_reason"]) == ("skipped", "no prices after the signal")


def test_an_open_runner_without_prices_past_its_hold_by_closes_at_the_last_close(db):  # Review Focus 2
    runners_stage(db, {"AKAN": akan()}, [info("AKAN")], NOW)
    day2 = [*akan(), daily("AKAN", AKAN_AFTER[0])]
    runners_stage(db, {"AKAN": day2}, [info("AKAN")], NOW + timedelta(days=1))
    runners_stage(db, {"AKAN": day2}, [info("AKAN")], datetime(2026, 12, 8, 13, 15, tzinfo=UTC))
    row = db.execute("select status, exit_price, skip_reason from runner_signals").fetchone()
    assert (row["status"], float(row["exit_price"]), row["skip_reason"]) == ("held", 2.21, "no prices: closed at the last close")


def test_a_frozen_rule_is_used_and_recorded(db):
    repo.freeze_runner_rule(db, replace(STARTING, volume_x=1000.0).settings(), None)
    assert runners_stage(db, {"AKAN": akan()}, [info("AKAN")], NOW)["signals"] == 0  # 892x is under 1000x
    repo.freeze_runner_rule(db, STARTING.settings(), None)
    runners_stage(db, {"AKAN": akan()}, [info("AKAN")], NOW)
    assert repo.unsettled_runner_signals(db)[0]["rule_version"] == 2


def test_warnings_and_splits_are_stored(db):
    sec = FakeSec(cik=1888014, filings=[filing("F-1/A", date(2026, 11, 13))])
    runners_stage(db, {"AKAN": akan()}, [info("AKAN")], NOW, sec=sec, splits=lambda s: {"AKAN": [(date(2026, 10, 20), 0.2)]})
    row = repo.unsettled_runner_signals(db)[0]
    assert row["warnings_checked"] is True
    assert [w["kind"] for w in row["warnings"]] == ["share_sale", "reverse_split"]


def test_an_open_runner_missing_from_a_runs_prices_stays_open(db):
    runners_stage(db, {"AKAN": akan()}, [info("AKAN")], NOW)
    day2 = [*akan(), daily("AKAN", AKAN_AFTER[0])]
    runners_stage(db, {"AKAN": day2}, [info("AKAN")], NOW + timedelta(days=1))
    # D is Mon 11-23, 6 sessions after the signal: a waiting signal would be skipped by now
    got = runners_stage(db, {}, [info("AKAN")], datetime(2026, 11, 24, 13, 15, tzinfo=UTC))
    [row] = repo.unsettled_runner_signals(db)
    assert (row["status"], float(row["entry"]), got["open"]) == ("open", 1.92, 1)


def test_a_failed_split_fetch_stores_the_signal_unchecked(db):
    def throttled(symbols):
        raise RuntimeError("throttled")

    got = runners_stage(db, {"AKAN": akan()}, [info("AKAN")], NOW, sec=FakeSec(cik=1888014), splits=throttled)
    assert (got["signals"], got["unchecked"]) == (1, 1)
    assert repo.unsettled_runner_signals(db)[0]["warnings_checked"] is False


def after_a_1_for_5_split(bars):
    """The same bars as Yahoo returns them after a 1-for-5 reverse split: prices x5, volume /5."""
    return [
        b.model_copy(update={"open": b.open * 5, "high": b.high * 5, "low": b.low * 5, "close": b.close * 5,
                             "volume": b.volume / 5})
        for b in bars
    ]


def test_a_split_while_waiting_plans_the_entry_on_the_new_price_scale(db):
    runners_stage(db, {"AKAN": akan()}, [info("AKAN")], NOW)
    # D's adjusted low is 3.63, within 25% of the 4.50 open: the stop is D's low on the new scale, not 4.50 x 0.75
    entry_day = Bar(date(2026, 11, 16), 0.90, 1.00, 0.80, 0.96, 1_000_000.0)
    rescaled = after_a_1_for_5_split([*akan(), daily("AKAN", entry_day)])
    runners_stage(db, {"AKAN": rescaled}, [info("AKAN")], NOW + timedelta(days=1))
    [row] = repo.unsettled_runner_signals(db)
    assert (row["status"], float(row["entry"]), float(row["stop"]), float(row["target"])) == ("open", 4.50, 3.63, 6.24)
    assert (float(row["signal_close"]), float(row["signal_low"])) == (1.36, 0.726)  # stored as traded


def test_a_split_while_waiting_is_not_taken_for_a_gap(db):
    repo.freeze_runner_rule(db, replace(STARTING, gap_skip=0.15).settings(), None)
    runners_stage(db, {"AKAN": akan()}, [info("AKAN")], NOW)
    # the adjusted open is 5% above D's adjusted close of 6.80; against the stored 1.36 it would look like 425%
    entry_day = Bar(date(2026, 11, 16), 1.428, 1.50, 1.38, 1.44, 1_000_000.0)
    rescaled = after_a_1_for_5_split([*akan(), daily("AKAN", entry_day)])
    runners_stage(db, {"AKAN": rescaled}, [info("AKAN")], NOW + timedelta(days=1))
    row = db.execute("select status, skip_reason, entry from runner_signals").fetchone()
    assert (row["status"], row["skip_reason"]) == ("open", None)
    assert float(row["entry"]) == pytest.approx(7.14)
