import os
from datetime import date

import httpx

from advisor.health import main
from advisor.store import repo
from fakes import FakeCollector, bar


def test_health_cli_records_rows_without_a_run_and_fails_on_a_core_source(db, monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    monkeypatch.setenv("ADVISOR_CACHE_DIR", str(tmp_path))
    collectors = {
        "good": FakeCollector("good", canary=("AAPL",),
                              records_for=lambda s: [bar("AAPL", date(2026, 10, 9), 1.0)]),
        "bad": FakeCollector("bad", core=True, canary=("AAPL",), error=httpx.ConnectError("down")),
    }
    monkeypatch.setattr("advisor.health.build_registry", lambda settings, client: collectors)

    assert main([]) == 1
    rows = db.execute(
        "select source, status, run_id, context from source_health order by source"
    ).fetchall()
    assert [(r["source"], r["status"], r["run_id"], r["context"]) for r in rows] == [
        ("bad", "failed", None, "health"), ("good", "ok", None, "health"),
    ]
    # The daily check also writes the registry, so the dashboard lists every source.
    names = [r["name"] for r in db.execute("select name from sources order by name").fetchall()]
    assert names == ["bad", "good"]


def test_health_cli_carries_on_when_the_registry_cant_be_written(db, monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    monkeypatch.setenv("ADVISOR_CACHE_DIR", str(tmp_path))
    collectors = {
        "good": FakeCollector("good", canary=("AAPL",),
                              records_for=lambda s: [bar("AAPL", date(2026, 10, 9), 1.0)]),
    }
    monkeypatch.setattr("advisor.health.build_registry", lambda settings, client: collectors)

    def refused(conn, collectors):
        raise RuntimeError("new row violates check constraint")

    monkeypatch.setattr(repo, "write_sources", refused)

    assert main([]) == 0  # the check itself ran, and passed
    assert "RuntimeError: new row violates check constraint" in capsys.readouterr().err
    rows = db.execute("select source, status from source_health").fetchall()
    assert [(r["source"], r["status"]) for r in rows] == [("good", "ok")]
