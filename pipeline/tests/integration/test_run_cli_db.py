import os

import pytest

from advisor.run import main
from fakes import fake_price_collectors

NOW_ARG = ["--now", "2026-10-14T12:15:00+00:00"]  # 08:15 ET, a pre-open slot


@pytest.fixture
def cli_env(db, monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    monkeypatch.setenv("ALPACA_KEY_ID", "test")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "test")
    monkeypatch.setenv("ADVISOR_CACHE_DIR", str(tmp_path))
    db.execute(
        "insert into runs (kind, et_date, status, published)"
        " values ('pre_open', '2026-10-14', 'success', true)"
    )
    return db


def test_an_already_published_slot_is_skipped(cli_env, monkeypatch, capsys):
    monkeypatch.setattr(
        "advisor.run.build_registry", lambda settings, client: pytest.fail("must not collect")
    )
    assert main(NOW_ARG) == 0
    assert "already published" in capsys.readouterr().out


def test_force_kind_runs_anyway_and_a_failed_run_exits_1(cli_env, monkeypatch, capsys):
    monkeypatch.setattr(
        "advisor.run.build_registry", lambda settings, client: fake_price_collectors()
    )
    assert main(["--force-kind", "pre_open", *NOW_ARG]) == 1  # 3-symbol universe < 1000
    assert '"status": "failed"' in capsys.readouterr().out
    assert cli_env.execute("select count(*) as n from runs").fetchone()["n"] == 2
