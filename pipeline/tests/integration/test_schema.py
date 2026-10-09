import uuid
from contextlib import contextmanager

import psycopg
import pytest

OWNER = uuid.UUID("00000000-0000-0000-0000-000000000001")
STRANGER = uuid.UUID("00000000-0000-0000-0000-000000000002")


@contextmanager
def acting_as(conn, role: str, user_id: uuid.UUID | None = None):
    conn.execute(f"set role {role}")
    conn.execute(
        "select set_config('request.jwt.claim.sub', %s, false)", (str(user_id or ""),)
    )
    try:
        yield
    finally:
        conn.execute("reset role")
        conn.execute("select set_config('request.jwt.claim.sub', '', false)")


@pytest.fixture
def owned_db(db):
    db.execute("insert into app_config (id, owner_id) values (1, %s)", (OWNER,))
    db.execute("insert into runs (kind, et_date) values ('pre_open', '2026-10-14')")
    return db


def test_owner_reads_runs(owned_db):
    with acting_as(owned_db, "authenticated", OWNER):
        assert len(owned_db.execute("select * from runs").fetchall()) == 1


def test_stranger_and_anon_see_nothing(owned_db):
    with acting_as(owned_db, "authenticated", STRANGER):
        assert owned_db.execute("select * from runs").fetchall() == []
    with acting_as(owned_db, "anon"):
        assert owned_db.execute("select * from runs").fetchall() == []


def test_owner_can_write_lots_but_not_runs(owned_db):
    with acting_as(owned_db, "authenticated", OWNER):
        owned_db.execute(
            "insert into lots (symbol, asset_type, qty, price, bought_at)"
            " values ('AAPL', 'stock', 1, 100, '2026-10-01')"
        )
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            owned_db.execute("insert into runs (kind, et_date) values ('pre_close', '2026-10-14')")


def test_stranger_cannot_write_lots(owned_db):
    with acting_as(owned_db, "authenticated", STRANGER):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            owned_db.execute(
                "insert into lots (symbol, asset_type, qty, price, bought_at)"
                " values ('AAPL', 'stock', 1, 100, '2026-10-01')"
            )


def test_only_one_published_run_per_kind_and_day(db):
    db.execute("insert into runs (kind, et_date, published) values ('pre_open', '2026-10-14', true)")
    with pytest.raises(psycopg.errors.UniqueViolation):
        db.execute(
            "insert into runs (kind, et_date, published) values ('pre_open', '2026-10-14', true)"
        )
