import json
from contextlib import nullcontext
from pathlib import Path

import pandas as pd
import psycopg
import pytest

from advisor.runners import weekly
from advisor.store import repo
from runner_data import AKAN_AFTER, akan, daily, more_flat_days

SWITCH = (Path(__file__).parents[3] / "supabase" / "manual" / "runners_switch_rule.sql").read_text(encoding="utf-8")


def write_training_files(out):
    """AKAN's history as the training build writes it, with no events. Built during its last day's session."""
    bars = more_flat_days([*akan(), *(daily("AKAN", b) for b in AKAN_AFTER)], 12)
    columns = ["symbol", "day", "open", "high", "low", "close", "volume"]
    pd.DataFrame([b.model_dump(include=set(columns)) for b in bars])[columns].to_parquet(
        out / "prices_US.parquet", index=False
    )
    pd.DataFrame({"symbol": [], "day": [], "dividend": [], "split": []}).to_parquet(
        out / "events_US.parquet", index=False
    )
    (out / "manifest.json").write_text(json.dumps({"end": bars[-1].day.isoformat()}))
    return bars


def test_the_first_backtest_freezes_version_1_and_later_ones_only_report(db, tmp_path):
    write_training_files(tmp_path)
    first = weekly.run(db, tmp_path)
    assert repo.live_runner_rule(db) == (1, first["pick"]["settings"])
    row = db.execute("select rule_version, frozen, pick, variants_tried from runner_backtests").fetchone()
    assert (row["rule_version"], row["variants_tried"]) == (1, 15) and row["frozen"]["settings"] == row["pick"]["settings"]
    weekly.run(db, tmp_path)
    assert repo.live_runner_rule(db)[0] == 1
    assert db.execute("select count(*) as n from runner_backtests").fetchone()["n"] == 2


def test_a_later_run_reports_the_live_rule(db, tmp_path):
    write_training_files(tmp_path)
    weekly.run(db, tmp_path)
    repo.freeze_runner_rule(db, {"volume_x": 20.0}, None)  # the owner switched to version 2
    second = weekly.run(db, tmp_path)
    assert repo.live_runner_rule(db) == (2, {"volume_x": 20.0})
    row = db.execute("select rule_version, frozen from runner_backtests order by id desc limit 1").fetchone()
    assert row["rule_version"] == 2 and row["frozen"] == second["frozen"]
    assert row["frozen"]["settings"]["volume_x"] == 20.0


def test_a_failed_freeze_leaves_no_backtest_naming_version_1(db, tmp_path, monkeypatch):
    write_training_files(tmp_path)

    def fail(*args):
        raise RuntimeError("the database went away")

    monkeypatch.setattr(weekly.repo, "freeze_runner_rule", fail)
    with pytest.raises(RuntimeError):
        weekly.run(db, tmp_path)
    assert db.execute("select count(*) as n from runner_backtests").fetchone()["n"] == 0


def test_the_builds_partial_last_day_is_left_out(db, tmp_path):
    bars = write_training_files(tmp_path)
    assert weekly.run(db, tmp_path)["data_to"] == bars[-2].day.isoformat()


def test_missing_files_exit_1_without_writing(db, tmp_path, monkeypatch):
    monkeypatch.setattr(weekly, "connect", lambda url: nullcontext(db))  # main opens its own connection
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused")
    assert weekly.main(["--data", str(tmp_path)]) == 1
    assert db.execute("select count(*) as n from runner_backtests").fetchone()["n"] == 0


def test_main_stores_the_backtest_and_exits_0(db, tmp_path, monkeypatch):
    write_training_files(tmp_path)
    monkeypatch.setattr(weekly, "connect", lambda url: nullcontext(db))
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused")
    assert weekly.main(["--data", str(tmp_path)]) == 0
    assert repo.live_runner_rule(db)[0] == 1


def test_the_owners_switch_makes_the_latest_pick_the_only_live_rule(db, tmp_path):
    write_training_files(tmp_path)
    weekly.run(db, tmp_path)
    latest = weekly.run(db, tmp_path)
    db.execute(SWITCH)
    backtest_id = db.execute("select max(id) as id from runner_backtests").fetchone()["id"]
    assert db.execute("select version, settings, backtest_id from runner_rules where live").fetchall() == [
        {"version": 2, "settings": latest["pick"]["settings"], "backtest_id": backtest_id}
    ]
    assert repo.runner_rule_settings(db)[1] == latest["pick"]["settings"]  # version 1 is kept, no longer live


def test_the_owners_switch_refuses_before_any_backtest(db):
    repo.freeze_runner_rule(db, {"volume_x": 20.0}, None)
    with pytest.raises(psycopg.errors.RaiseException):
        db.execute(SWITCH)
    assert repo.live_runner_rule(db) == (1, {"volume_x": 20.0})
