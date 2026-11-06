import uuid
from contextlib import contextmanager
from datetime import UTC, datetime

import psycopg
import pytest

OWNER = uuid.UUID("00000000-0000-0000-0000-000000000001")
STRANGER = uuid.UUID("00000000-0000-0000-0000-000000000002")
AAPL_LOT = (
    "insert into lots (account, symbol, asset_type, qty, price, currency, fx_rate_cad, bought_at)"
    " values ('tfsa', 'AAPL', 'stock', 1, 100, 'USD', 1.37, '2026-10-01')"
)


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
            AAPL_LOT
        )
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            owned_db.execute("insert into runs (kind, et_date) values ('pre_close', '2026-10-14')")


def test_stranger_cannot_write_lots(owned_db):
    with acting_as(owned_db, "authenticated", STRANGER):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            owned_db.execute(
                AAPL_LOT
            )


def test_only_one_published_run_per_kind_and_day(db):
    db.execute("insert into runs (kind, et_date, published) values ('pre_open', '2026-10-14', true)")
    with pytest.raises(psycopg.errors.UniqueViolation):
        db.execute(
            "insert into runs (kind, et_date, published) values ('pre_open', '2026-10-14', true)"
        )


@pytest.mark.parametrize(
    "symbol", ["aapl", "BRK-B", " TSLA", "$TSLA", "ry.to", "RY.TSX", "RCI.B.TO", "REI-UNIT.TO", "RY-.TO"]
)
def test_malformed_stock_symbols_are_rejected(db, symbol):
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute("insert into watchlist (symbol, asset_type) values (%s, 'stock')", (symbol,))


@pytest.mark.parametrize("table", ["watchlist", "lots", "sells"])
def test_us_tsx_and_crypto_symbols_are_accepted_everywhere(db, table):
    for symbol, asset_type in [
        ("BRK.B", "stock"), ("RY.TO", "stock"), ("RCI-B.TO", "stock"), ("REI-UN.TO", "stock"),
        ("BTC", "crypto"),
    ]:
        if table == "watchlist":
            db.execute(
                "insert into watchlist (symbol, asset_type) values (%s, %s)", (symbol, asset_type)
            )
            continue
        day = "bought_at" if table == "lots" else "sold_at"
        db.execute(
            f"insert into {table} (account, symbol, asset_type, qty, price, currency, {day})"
            " values (%s, %s, %s, 1, 10, 'CAD', '2026-10-01')",
            ("crypto" if asset_type == "crypto" else "tfsa", symbol, asset_type),
        )
    assert db.execute(f"select count(*) as n from {table}").fetchone()["n"] == 5


def test_every_public_table_has_row_level_security(db):
    rows = db.execute(
        "select c.relname from pg_class c join pg_namespace n on n.oid = c.relnamespace"
        " where n.nspname = 'public' and c.relkind = 'r' and not c.relrowsecurity"
    ).fetchall()
    assert rows == []


def test_owner_can_update_and_delete_lots(owned_db):
    owned_db.execute(
        AAPL_LOT
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
                AAPL_LOT
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
        AAPL_LOT
    )
    with acting_as(db, "pipeline_rw"):
        db.execute("insert into runs (kind, et_date) values ('pre_open', '2026-10-14')")
        assert len(db.execute("select * from lots").fetchall()) == 1
        for statement in (
            "insert into lots (account, symbol, asset_type, qty, price, currency, fx_rate_cad,"
            " bought_at) values ('tfsa', 'MSFT', 'stock', 1, 100, 'USD', 1.37, '2026-10-01')",
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
        " consecutive_failures, context) values (null, 'nasdaq_symbols', 'partial', 5, 1, 0, 'health')"
    )
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(
            "insert into source_health (run_id, source, status, latency_ms, records,"
            " consecutive_failures, context) values (null, 'nasdaq_symbols', 'ok', 5, 1, 0, 'run')"
        )


def test_stocks_need_a_market_and_crypto_has_none(db):
    db.execute(
        "insert into symbols (symbol, asset_type, market, name, exchange) values"
        " ('RY.TO', 'stock', 'TSX', 'Royal Bank of Canada', 'TSX'), ('BTC', 'crypto', null, 'Bitcoin', '-')"
    )
    for values in [("AAPL", "stock", None), ("ETH", "crypto", "US"), ("VOD", "stock", "LSE")]:
        with pytest.raises(psycopg.errors.CheckViolation):
            db.execute(
                "insert into symbols (symbol, asset_type, market, name, exchange)"
                " values (%s, %s, %s, 'n', 'x')",
                values,
            )


def test_crypto_lives_only_in_the_crypto_account(db):
    lot = (
        "insert into lots (account, symbol, asset_type, qty, price, currency, bought_at)"
        " values (%s, %s, %s, 1, 10, 'CAD', '2026-10-01')"
    )
    db.execute(lot, ("crypto", "BTC", "crypto"))
    for values in [("tfsa", "ETH", "crypto"), ("crypto", "RY.TO", "stock"), ("cash", "RY.TO", "stock")]:
        with pytest.raises(psycopg.errors.CheckViolation):
            db.execute(lot, values)


def test_usd_trades_need_an_exchange_rate(db):
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(
            "insert into sells (account, symbol, asset_type, qty, price, currency, sold_at)"
            " values ('tfsa', 'AAPL', 'stock', 1, 100, 'USD', '2026-10-01')"
        )
    db.execute(
        "insert into sells (account, symbol, asset_type, qty, price, currency, sold_at)"
        " values ('tfsa', 'RY.TO', 'stock', 1, 100, 'CAD', '2026-10-01')"
    )


def test_holding_actions_are_per_account_without_data_conflict(db):
    run_id = db.execute(
        "insert into runs (kind, et_date) values ('pre_open', '2026-10-14') returning id"
    ).fetchone()["id"]
    action = (
        "insert into holding_actions (run_id, account, symbol, asset_type, action)"
        " values (%s, %s, 'AAPL', 'stock', %s)"
    )
    db.execute(action, (run_id, "tfsa", "hold"))
    db.execute(action, (run_id, "rrsp", "trim"))  # the same stock in a second account
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(action, (run_id, "fhsa", "data_conflict"))
    row = db.execute("select warnings from holding_actions where account = 'tfsa'").fetchone()
    assert row["warnings"] == []


def test_picks_and_models_are_per_market(db):
    run_id = db.execute(
        "insert into runs (kind, et_date) values ('pre_open', '2026-10-14') returning id"
    ).fetchone()["id"]
    pick = (
        "insert into picks (run_id, symbol, market, style, horizon_days, exit_by, entry_ref_price,"
        " stop, risk_level, risk_score, max_position_pct, rank)"
        " values (%s, 'RY.TO', %s, 'swing', 10, '2026-10-28', 10, 9, 'low', 0.1, 5, 1)"
    )
    db.execute(pick, (run_id, "TSX"))
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(pick, (run_id, None))
    db.execute("insert into models (version, kind, trained_at) values ('v1', 'stock_tsx', now())")
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute("insert into models (version, kind, trained_at) values ('v2', 'stock', now())")


def test_settings_has_one_seeded_row_that_only_the_owner_can_update(owned_db):
    row = owned_db.execute("select * from settings").fetchone()
    assert (
        row["usd_fx_fee_pct"], row["crypto_fee_pct"],
        row["tfsa_round_trips_warn"], row["tfsa_short_hold_share_warn"],
    ) == (1.5, 2.0, 24, 0.5)
    with acting_as(owned_db, "authenticated", OWNER):
        assert owned_db.execute("update settings set usd_fx_fee_pct = 1.0").rowcount == 1
        assert owned_db.execute("delete from settings").rowcount == 0  # no delete policy
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            owned_db.execute("insert into settings (id) values (1)")
    with acting_as(owned_db, "authenticated", STRANGER):
        assert owned_db.execute("select * from settings").fetchall() == []
        assert owned_db.execute("update settings set usd_fx_fee_pct = 9").rowcount == 0
    assert owned_db.execute("select usd_fx_fee_pct from settings").fetchone()["usd_fx_fee_pct"] == 1
    with pytest.raises(psycopg.errors.CheckViolation):
        owned_db.execute("update settings set tfsa_short_hold_share_warn = 1.5")


def test_anon_sees_and_changes_no_settings(owned_db):
    with acting_as(owned_db, "anon"):
        assert owned_db.execute("select * from settings").fetchall() == []
        assert owned_db.execute("update settings set usd_fx_fee_pct = 9").rowcount == 0
    assert owned_db.execute("select usd_fx_fee_pct from settings").fetchone()["usd_fx_fee_pct"] == 1.5


def test_pipeline_reads_settings_but_cannot_change_them(db):
    with acting_as(db, "pipeline_rw"):
        assert db.execute("select usd_fx_fee_pct from settings").fetchone()["usd_fx_fee_pct"] == 1.5
        for statement in (
            "update settings set usd_fx_fee_pct = 0",
            "delete from settings",
            "insert into settings (id) values (2)",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                db.execute(statement)


def test_the_owner_reads_price_history_and_only_the_pipeline_writes_it(owned_db):
    owned_db.execute("insert into daily_closes values ('AAPL', 'stock', '2026-10-13', 228, 'USD')")
    owned_db.execute("insert into fx_rates values ('2026-10-13', 1.3712)")
    with acting_as(owned_db, "authenticated", OWNER):
        assert len(owned_db.execute("select * from daily_closes").fetchall()) == 1
        assert len(owned_db.execute("select * from fx_rates").fetchall()) == 1
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            owned_db.execute("insert into daily_closes values ('MSFT', 'stock', '2026-10-13', 410, 'USD')")
        assert owned_db.execute("update fx_rates set usd_cad = 1").rowcount == 0
        assert owned_db.execute("delete from daily_closes").rowcount == 0
    with acting_as(owned_db, "authenticated", STRANGER):
        assert owned_db.execute("select * from daily_closes").fetchall() == []
        assert owned_db.execute("select * from fx_rates").fetchall() == []
    with acting_as(owned_db, "pipeline_rw"):
        owned_db.execute("insert into daily_closes values ('MSFT', 'stock', '2026-10-13', 410, 'USD')")
        assert owned_db.execute("update fx_rates set usd_cad = 1.3715").rowcount == 1


@pytest.mark.parametrize(
    ("symbol", "asset_type", "currency"),
    [("aapl", "stock", "USD"), ("RY.TSX", "stock", "CAD"), ("btc", "crypto", "USD"), ("AAPL", "stock", "EUR")],
)
def test_malformed_closes_are_rejected(db, symbol, asset_type, currency):
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(
            "insert into daily_closes values (%s, %s, '2026-10-13', 10, %s)", (symbol, asset_type, currency)
        )


def test_the_owner_reads_sources_and_only_the_pipeline_writes_them(owned_db):
    owned_db.execute(
        "insert into sources (name, category, core, cadence, asset_types, markets)"
        " values ('fred', 'macro', true, 'daily', '{stock}', '{US,TSX}')"
    )
    with acting_as(owned_db, "authenticated", OWNER):
        assert [r["name"] for r in owned_db.execute("select name from sources").fetchall()] == ["fred"]
        assert owned_db.execute("update sources set core = false").rowcount == 0
        assert owned_db.execute("delete from sources").rowcount == 0
    with acting_as(owned_db, "authenticated", STRANGER):
        assert owned_db.execute("select * from sources").fetchall() == []
    with acting_as(owned_db, "pipeline_rw"):
        assert owned_db.execute("update sources set core = false").rowcount == 1


@pytest.mark.parametrize(
    ("category", "cadence", "asset_types", "markets"),
    [("weather", "daily", "{stock}", "{US}"), ("macro", "hourly", "{stock}", "{US}"),
     ("macro", "daily", "{}", "{US}"), ("macro", "daily", "{bond}", "{US}"),
     ("macro", "daily", "{stock}", "{NYSE}")],
)
def test_malformed_sources_are_rejected(db, category, cadence, asset_types, markets):
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(
            "insert into sources (name, category, core, cadence, asset_types, markets)"
            " values ('x', %s, true, %s, %s, %s)",
            (category, cadence, asset_types, markets),
        )


def test_the_owner_learns_each_sources_last_good_answer(owned_db):
    for source, status, at in [
        ("fred", "partial", "2026-10-15T19:00Z"), ("fred", "failed", "2026-10-16T19:00Z"),
        ("fred", "ok", "2026-10-14T19:00Z"), ("sec_8k", "stale", "2026-10-16T19:00Z"),
    ]:
        owned_db.execute(
            "insert into source_health (source, status, latency_ms, records, consecutive_failures,"
            " attempted_at, context) values (%s, %s, 1, 1, 0, %s, 'health')",
            (source, status, at),
        )
    last_ok = "select source, attempted_at from source_last_ok"
    with acting_as(owned_db, "authenticated", OWNER):
        assert [tuple(r.values()) for r in owned_db.execute(last_ok).fetchall()] == [
            ("fred", datetime(2026, 10, 15, 19, tzinfo=UTC)),
        ]  # a stale answer served old values, so it isn't a good one
    with acting_as(owned_db, "authenticated", STRANGER):
        assert owned_db.execute(last_ok).fetchall() == []


def test_only_the_owner_learns_the_database_size(owned_db):
    size = "select public.database_size() as size"
    with acting_as(owned_db, "authenticated", OWNER):
        assert owned_db.execute(size).fetchone()["size"] > 0
    with acting_as(owned_db, "authenticated", STRANGER):
        assert owned_db.execute(size).fetchone()["size"] is None
    with acting_as(owned_db, "anon"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            owned_db.execute(size)


def test_the_owner_reads_model_files_and_only_the_pipeline_writes_them(owned_db):
    owned_db.execute("insert into models (version, kind, trained_at) values ('v1', 'stock_tsx', now())")
    owned_db.execute("insert into model_files (version, name, body) values ('v1', 'meta', '\\x7b7d')")
    with acting_as(owned_db, "authenticated", OWNER):
        assert [r["name"] for r in owned_db.execute("select name from model_files").fetchall()] == ["meta"]
        assert owned_db.execute("delete from model_files").rowcount == 0
    with acting_as(owned_db, "authenticated", STRANGER):
        assert owned_db.execute("select * from model_files").fetchall() == []
    with acting_as(owned_db, "pipeline_rw"):
        assert owned_db.execute("update model_files set body = '\\x00'").rowcount == 1
    with pytest.raises(psycopg.errors.CheckViolation):
        owned_db.execute("insert into model_files (version, name, body) values ('v1', 'Bad Name', '\\x00')")


def _run(db) -> int:
    return db.execute(
        "insert into runs (kind, et_date) values ('pre_open', '2026-10-14') returning id"
    ).fetchone()["id"]


def test_holding_actions_carry_what_grading_needs(db):
    run_id = _run(db)
    action = (
        "insert into holding_actions (run_id, account, symbol, asset_type, action, horizon_days,"
        " feature_day, ref_price, bench_ref_price, risk_level, max_position_pct)"
        " values (%s, 'tfsa', 'AAPL', 'stock', 'hold', 10, '2026-10-13', 100, 500, %s, 5)"
    )
    db.execute(action, (run_id, "medium"))
    row = db.execute(
        "select horizon_days, feature_day, ref_price, bench_ref_price, risk_level, max_position_pct"
        " from holding_actions"
    ).fetchone()
    assert row["horizon_days"] == 10
    assert str(row["feature_day"]) == "2026-10-13"
    assert (row["ref_price"], row["bench_ref_price"]) == (100, 500)
    assert (row["risk_level"], row["max_position_pct"]) == ("medium", 5)
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(action.replace("'tfsa'", "'rrsp'"), (run_id, "extreme"))


def test_a_holding_action_outcome_belongs_to_its_action(db):
    run_id = _run(db)
    outcome = (
        "insert into holding_action_outcomes (run_id, account, symbol, asset_type, exit_price,"
        " ret, ret_net_of_fx, bench_ret, excess, beat, hit_stop)"
        " values (%s, 'tfsa', 'AAPL', 'stock', %s, 0.05, 0.04, 0.01, 0.04, true, false)"
    )
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        db.execute(outcome, (run_id, 110))
    db.execute(
        "insert into holding_actions (run_id, account, symbol, asset_type, action)"
        " values (%s, 'tfsa', 'AAPL', 'stock', 'hold')",
        (run_id,),
    )
    db.execute(outcome, (run_id, 110))
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(outcome.replace("'AAPL'", "'MSFT'"), (run_id, 0))
    db.execute("delete from runs where id = %s", (run_id,))
    assert db.execute("select count(*) as n from holding_action_outcomes").fetchone()["n"] == 0


def test_picks_record_their_feature_day_and_benchmark_price(db):
    run_id = _run(db)
    db.execute(
        "insert into picks (run_id, symbol, market, style, horizon_days, exit_by, entry_ref_price,"
        " stop, risk_level, risk_score, max_position_pct, rank, feature_day, bench_ref_price)"
        " values (%s, 'AAPL', 'US', 'swing', 10, '2026-10-28', 10, 9, 'low', 0.1, 5, 1,"
        " '2026-10-13', 500)",
        (run_id,),
    )
    row = db.execute("select feature_day, bench_ref_price from picks").fetchone()
    assert str(row["feature_day"]) == "2026-10-13"
    assert row["bench_ref_price"] == 500


RUN = "insert into benchmark_runs (started_at) values ('2026-11-01T09:00Z') returning id"


def test_the_owner_reads_benchmarks_and_only_the_pipeline_writes_them(owned_db):
    run_id = owned_db.execute(RUN).fetchone()["id"]
    owned_db.execute("insert into benchmark_results (run_id, market, variant, fold, metrics) values (%s, 'TSX', 'baseline', 'pooled', '{}')", (run_id,))
    owned_db.execute("insert into accepted_configs (market, config, reason, accepted_at, benchmark_run_id, active) values ('TSX', '{}', 'r', now(), %s, true)", (run_id,))
    for table in ("benchmark_runs", "benchmark_results", "accepted_configs"):
        with acting_as(owned_db, "authenticated", OWNER):
            assert len(owned_db.execute(f"select * from {table}").fetchall()) == 1
            assert owned_db.execute(f"delete from {table}").rowcount == 0
        with acting_as(owned_db, "authenticated", STRANGER):
            assert owned_db.execute(f"select * from {table}").fetchall() == []
    with acting_as(owned_db, "pipeline_rw"):
        assert owned_db.execute("update benchmark_runs set status = 'success'").rowcount == 1


def test_one_accepted_config_is_active_per_market(db):
    run_id = db.execute(RUN).fetchone()["id"]
    insert = "insert into accepted_configs (market, config, reason, accepted_at, benchmark_run_id, active) values (%s, '{}', 'r', now(), %s, true)"
    db.execute(insert, ("US", run_id))
    db.execute(insert, ("crypto", run_id))
    with pytest.raises(psycopg.errors.UniqueViolation):
        db.execute(insert, ("US", run_id))


@pytest.mark.parametrize("column, value", [("market", "us"), ("variant", "Baseline"), ("fold", "pool"), ("fold", "10")])
def test_malformed_benchmark_results_are_rejected(db, column, value):
    run_id = db.execute(RUN).fetchone()["id"]
    row = {"market": "TSX", "variant": "baseline", "fold": "0"} | {column: value}
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute("insert into benchmark_results (run_id, market, variant, fold, metrics) values (%s, %s, %s, %s, '{}')",
                   (run_id, row["market"], row["variant"], row["fold"]))



def test_a_rank_pick_is_stored_with_its_place(db):
    run_id = _run(db)
    cols = ("insert into picks (run_id, symbol, market, style, horizon_days, exit_by, entry_ref_price,"
            " stop, risk_level, risk_score, max_position_pct, rank, feature_day, bench_ref_price{extra})"
            " values (%s, 'RY.TO', 'TSX', 'swing', 21, '2026-12-07', 10, 9, 'low', 0.1, 5, 1,"
            " '2026-11-06', 500{values})")
    db.execute(cols.format(extra=", chosen_by, score_rank, score_of", values=", 'rank', 2, 380"), (run_id,))
    db.execute(cols.format(extra="", values=""), (run_id,))  # an older writer: chosen by P
    rows = db.execute("select chosen_by, score_rank, score_of from picks order by id").fetchall()
    assert [tuple(r.values()) for r in rows] == [("rank", 2, 380), ("p", None, None)]
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(cols.format(extra=", chosen_by", values=", 'luck'"), (run_id,))
