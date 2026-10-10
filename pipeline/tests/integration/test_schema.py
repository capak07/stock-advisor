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


@pytest.mark.parametrize("symbol", ["aapl", "BRK-B", " TSLA", "$TSLA"])
def test_malformed_stock_symbols_are_rejected(db, symbol):
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute("insert into watchlist (symbol, asset_type) values (%s, 'stock')", (symbol,))


def test_well_formed_stock_and_crypto_symbols_are_accepted(db):
    db.execute("insert into watchlist (symbol, asset_type) values ('BRK.B', 'stock')")
    db.execute("insert into watchlist (symbol, asset_type) values ('BTC', 'crypto')")
    assert db.execute("select count(*) as n from watchlist").fetchone()["n"] == 2


def test_every_public_table_has_row_level_security(db):
    rows = db.execute(
        "select c.relname from pg_class c join pg_namespace n on n.oid = c.relnamespace"
        " where n.nspname = 'public' and c.relkind = 'r' and not c.relrowsecurity"
    ).fetchall()
    assert rows == []


def test_owner_can_update_and_delete_lots(owned_db):
    owned_db.execute(
        "insert into lots (symbol, asset_type, qty, price, bought_at)"
        " values ('AAPL', 'stock', 1, 100, '2026-10-01')"
    )
    with acting_as(owned_db, "authenticated", OWNER):
        updated = owned_db.execute("update lots set qty = 2 where symbol = 'AAPL'")
        assert updated.rowcount == 1
        deleted = owned_db.execute("delete from lots where symbol = 'AAPL'")
        assert deleted.rowcount == 1
    assert owned_db.execute("select count(*) as n from lots").fetchone()["n"] == 0


def test_anon_cannot_write_lots(owned_db):
    with acting_as(owned_db, "anon"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            owned_db.execute(
                "insert into lots (symbol, asset_type, qty, price, bought_at)"
                " values ('AAPL', 'stock', 1, 100, '2026-10-01')"
            )


def test_owner_cannot_write_picks(owned_db):
    run_id = owned_db.execute("select id from runs").fetchone()["id"]
    with acting_as(owned_db, "authenticated", OWNER):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            owned_db.execute(
                "insert into picks (run_id, symbol, style, horizon_days, exit_by,"
                " entry_ref_price, stop, risk_level, risk_score, max_position_pct, rank)"
                " values (%s, 'AAPL', 'swing', 10, '2026-10-28', 10, 9, 'low', 0.1, 5, 1)",
                (run_id,),
            )


def test_pipeline_role_writes_pipeline_tables_but_only_reads_holdings(db):
    db.execute(
        "insert into lots (symbol, asset_type, qty, price, bought_at)"
        " values ('AAPL', 'stock', 1, 100, '2026-10-01')"
    )
    with acting_as(db, "pipeline_rw"):
        db.execute("insert into runs (kind, et_date) values ('pre_open', '2026-10-14')")
        assert len(db.execute("select * from lots").fetchall()) == 1
        for statement in (
            "insert into lots (symbol, asset_type, qty, price, bought_at)"
            " values ('MSFT', 'stock', 1, 100, '2026-10-01')",
            "insert into watchlist (symbol, asset_type) values ('NVDA', 'stock')",
            "update app_config set owner_id = owner_id",
            "create table sneaky (i int)",
            "select * from schema_migrations",
            "update lots set qty = qty",
            "delete from lots",
            "update sells set qty = qty",
            "delete from sells",
            "delete from watchlist",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                db.execute(statement)


def test_every_table_except_migrations_has_a_pipeline_policy(db):
    missing = db.execute(
        "select c.relname from pg_class c join pg_namespace n on n.oid = c.relnamespace"
        " where n.nspname = 'public' and c.relkind = 'r' and c.relname <> 'schema_migrations'"
        " and not exists (select 1 from pg_policies p where p.schemaname = 'public'"
        "   and p.tablename = c.relname and 'pipeline_rw' = any(p.roles))"
    ).fetchall()
    assert missing == []


def test_health_rows_have_no_run_and_run_rows_need_one(db):
    db.execute(
        "insert into source_health (run_id, source, status, latency_ms, records,"
        " consecutive_failures, context) values (null, 'alpaca_bars', 'partial', 5, 1, 0, 'health')"
    )
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(
            "insert into source_health (run_id, source, status, latency_ms, records,"
            " consecutive_failures, context) values (null, 'alpaca_bars', 'ok', 5, 1, 0, 'run')"
        )
