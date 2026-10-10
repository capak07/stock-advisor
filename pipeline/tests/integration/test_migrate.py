from pathlib import Path

import psycopg
import pytest

from advisor.store.db import MIGRATIONS_DIR
from advisor.store.migrate import migrate


def recorded(db) -> list[str]:
    return [r["name"] for r in db.execute("select name from schema_migrations order by name")]


def write(directory: Path, name: str, sql: str) -> None:
    (directory / name).write_text(sql, encoding="utf-8")


def exists(db, table: str) -> bool:
    return db.execute("select to_regclass(%s) is not null as ok", (f"public.{table}",)).fetchone()["ok"]


def test_db_fixture_records_every_migration(db):
    assert recorded(db) == sorted(p.name for p in MIGRATIONS_DIR.glob("*.sql"))


def test_migrate_is_a_no_op_when_up_to_date(db):
    assert migrate(db) == []


def test_new_migration_is_applied_once(db, tmp_path):
    write(tmp_path, "0099_extra.sql",
          "create table extra_t (i int); alter table extra_t enable row level security;")
    assert migrate(db, tmp_path) == ["0099_extra.sql"]
    assert migrate(db, tmp_path) == []
    assert exists(db, "extra_t")


def test_failed_migration_is_rolled_back_and_not_recorded(db, tmp_path):
    write(tmp_path, "0098_bad.sql", "create table half_done (i int); select * from missing_table;")
    with pytest.raises(psycopg.errors.UndefinedTable):
        migrate(db, tmp_path)
    assert not exists(db, "half_done")
    assert "0098_bad.sql" not in recorded(db)


def test_baseline_records_older_files_without_running_them(db, tmp_path):
    write(tmp_path, "0001_a.sql", "create table should_not_exist (i int);")
    write(tmp_path, "0002_b.sql",
          "create table b_t (i int); alter table b_t enable row level security;")
    assert migrate(db, tmp_path, baseline="0001_a.sql") == ["0002_b.sql"]
    assert not exists(db, "should_not_exist")
    assert {"0001_a.sql", "0002_b.sql"} <= set(recorded(db))


def test_unknown_baseline_is_rejected(db, tmp_path):
    write(tmp_path, "0001_a.sql", "select 1;")
    with pytest.raises(ValueError, match="unknown baseline"):
        migrate(db, tmp_path, baseline="0005_nope.sql")
