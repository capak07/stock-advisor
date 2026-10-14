from datetime import UTC, date, datetime

import psycopg
import pytest

from advisor.collectors.base import CollectorResult, CollectorStatus
from advisor.models import AssetRef, AssetType, Market, RunKind, RunStatus, SymbolInfo
from advisor.store import repo
from fakes import info

DAY = date(2026, 10, 14)
NOW = datetime(2026, 10, 14, 12, 15, tzinfo=UTC)


def finish(db, run_id, status):
    repo.finish_run(db, run_id, status, sources_ok=2, sources_total=3, summary={"universe": 5})


def test_success_and_degraded_runs_publish_failed_does_not(db):
    for status, published in [
        (RunStatus.SUCCESS, True),
        (RunStatus.DEGRADED, True),
        (RunStatus.FAILED, False),
    ]:
        kind = {RunStatus.SUCCESS: RunKind.PRE_OPEN, RunStatus.DEGRADED: RunKind.PRE_CLOSE,
                RunStatus.FAILED: RunKind.EARLY_CLOSE}[status]
        run_id = repo.create_run(db, kind, DAY)
        finish(db, run_id, status)
        row = db.execute("select * from runs where id = %s", (run_id,)).fetchone()
        assert row["status"] == status.value
        assert row["published"] is published
        assert row["finished_at"] is not None
        assert row["summary"] == {"universe": 5}
        assert (row["sources_ok"], row["sources_total"]) == (2, 3)


def test_rerun_replaces_the_published_run_for_the_same_slot(db):
    first = repo.create_run(db, RunKind.PRE_OPEN, DAY)
    finish(db, first, RunStatus.SUCCESS)
    second = repo.create_run(db, RunKind.PRE_OPEN, DAY)
    finish(db, second, RunStatus.SUCCESS)
    published = db.execute("select id from runs where published").fetchall()
    assert [r["id"] for r in published] == [second]


def test_failed_rerun_keeps_the_published_run_for_the_same_slot(db):
    first = repo.create_run(db, RunKind.PRE_OPEN, DAY)
    finish(db, first, RunStatus.SUCCESS)
    second = repo.create_run(db, RunKind.PRE_OPEN, DAY)
    finish(db, second, RunStatus.FAILED)
    published = db.execute("select id from runs where published").fetchall()
    assert [r["id"] for r in published] == [first]


def test_has_published_run(db):
    assert repo.has_published_run(db, RunKind.PRE_OPEN, DAY) is False
    run_id = repo.create_run(db, RunKind.PRE_OPEN, DAY)
    assert repo.has_published_run(db, RunKind.PRE_OPEN, DAY) is False
    finish(db, run_id, RunStatus.SUCCESS)
    assert repo.has_published_run(db, RunKind.PRE_OPEN, DAY) is True
    assert repo.has_published_run(db, RunKind.PRE_CLOSE, DAY) is False


def test_source_state_tracks_failures_and_ignores_skips_for_last_attempt(db):
    run_id = repo.create_run(db, RunKind.PRE_OPEN, DAY)
    assert repo.load_source_state(db, "nasdaq_symbols").consecutive_failures == 0

    failed = CollectorResult("nasdaq_symbols", CollectorStatus.FAILED, [], 120, "ConnectError: down")
    repo.record_source_health(db, run_id, failed, 3, datetime(2026, 10, 13, 19, 15, tzinfo=UTC))
    skipped = CollectorResult("nasdaq_symbols", CollectorStatus.SKIPPED, [], 0, "circuit breaker open")
    repo.record_source_health(db, run_id, skipped, 3, NOW)

    state = repo.load_source_state(db, "nasdaq_symbols")
    assert state.consecutive_failures == 3
    assert state.last_attempt_et_date == date(2026, 10, 13)

    row = db.execute("select * from source_health where status = 'failed'").fetchone()
    assert (row["latency_ms"], row["records"], row["error"]) == (120, 0, "ConnectError: down")


def test_upsert_symbols_deactivates_only_within_its_market(db):
    repo.upsert_symbols(db, Market.US, [info("AAPL"), info("GONE")])
    repo.upsert_symbols(db, Market.TSX, [info("RY.TO")])
    repo.upsert_symbols(db, Market.US, [info("AAPL", exchange="NASDAQ"), info("MSFT")])
    rows = db.execute(
        "select symbol, market, exchange, active from symbols order by symbol"
    ).fetchall()
    assert [(r["symbol"], r["market"], r["exchange"], r["active"]) for r in rows] == [
        ("AAPL", "US", "NASDAQ", True),
        ("GONE", "US", "NYSE", False),
        ("MSFT", "US", "NYSE", True),
        ("RY.TO", "TSX", "TSX", True),  # a US universe never deactivates TSX symbols
    ]


def test_upsert_symbols_refuses_empty_or_foreign_universes(db):
    repo.upsert_symbols(db, Market.US, [info("AAPL")])
    with pytest.raises(ValueError, match="refusing to upsert an empty US universe"):
        repo.upsert_symbols(db, Market.US, [])
    crypto = SymbolInfo(symbol="BTC", asset_type=AssetType.CRYPTO, name="Bitcoin", exchange="-")
    for strays in ([crypto], [info("AAPL"), info("RY.TO")]):
        with pytest.raises(ValueError, match="not US stocks"):
            repo.upsert_symbols(db, Market.US, strays)
    rows = db.execute("select symbol, active from symbols").fetchall()
    assert [(r["symbol"], r["active"]) for r in rows] == [("AAPL", True)]


def test_load_held_symbols_nets_sells(db):
    db.execute(
        "insert into lots (account, symbol, asset_type, qty, price, currency, fx_rate_cad, bought_at)"
        " values ('tfsa', 'AAPL', 'stock', 10, 100, 'USD', 1.37, '2026-01-02'),"
        " ('tfsa', 'SOLD', 'stock', 5, 20, 'USD', 1.37, '2026-01-02'),"
        " ('crypto', 'BTC', 'crypto', 0.5, 60000, 'CAD', null, '2026-02-01')"
    )
    db.execute(
        "insert into sells (account, symbol, asset_type, qty, price, currency, fx_rate_cad, sold_at)"
        " values ('tfsa', 'AAPL', 'stock', 4, 120, 'USD', 1.36, '2026-05-01'),"
        " ('tfsa', 'SOLD', 'stock', 5, 25, 'USD', 1.36, '2026-05-01')"
    )
    assert repo.load_held_symbols(db) == {
        AssetRef("AAPL", AssetType.STOCK),
        AssetRef("BTC", AssetType.CRYPTO),
    }


def test_load_watchlist(db):
    db.execute("insert into watchlist (symbol, asset_type) values ('NVDA', 'stock'), ('ETH', 'crypto')")
    assert repo.load_watchlist(db) == {
        AssetRef("NVDA", AssetType.STOCK),
        AssetRef("ETH", AssetType.CRYPTO),
    }


def test_write_features_live(db):
    run_id = repo.create_run(db, RunKind.PRE_OPEN, DAY)
    repo.write_features_live(
        db, run_id, [(AssetRef("AAPL", AssetType.STOCK), {"last_close": 150.0})], NOW
    )
    repo.write_features_live(db, run_id, [], NOW)
    row = db.execute("select * from features_live").fetchone()
    assert (row["symbol"], row["asset_type"], row["features"]) == (
        "AAPL", "stock", {"last_close": 150.0},
    )


def test_record_source_health_supports_health_context(db):
    ok = CollectorResult("nasdaq_symbols", CollectorStatus.OK, [], 7)
    repo.record_source_health(db, None, ok, 0, NOW, context="health")
    row = db.execute("select run_id, context from source_health").fetchone()
    assert (row["run_id"], row["context"]) == (None, "health")
    with pytest.raises(psycopg.errors.CheckViolation):
        repo.record_source_health(db, None, ok, 0, NOW)  # context defaults to "run"


def test_load_source_states_returns_one_state_per_source(db):
    run_id = repo.create_run(db, RunKind.PRE_OPEN, DAY)
    failed = CollectorResult("nasdaq_symbols", CollectorStatus.FAILED, [], 1, "down")
    repo.record_source_health(db, run_id, failed, 2, NOW)
    states = repo.load_source_states(db, ["nasdaq_symbols", "yfinance_bars"])
    assert states["nasdaq_symbols"].consecutive_failures == 2
    assert states["yfinance_bars"].consecutive_failures == 0


def test_sweep_marks_only_old_running_runs_abandoned(db):
    db.execute(
        "insert into runs (kind, et_date, started_at) values"
        " ('pre_close', '2026-10-13', '2026-10-14 08:00+00'),"
        " ('pre_open', '2026-10-14', '2026-10-14 11:30+00')"
    )
    assert repo.sweep_abandoned_runs(db, NOW) == 1  # NOW is 2026-10-14 12:15 UTC
    rows = db.execute("select kind, status, summary from runs order by started_at").fetchall()
    assert rows[0]["status"] == "failed"
    assert rows[0]["summary"]["error"].startswith("abandoned")
    assert rows[1]["status"] == "running"
