from datetime import UTC, date, datetime

import pytest

from advisor.collectors.base import CollectorResult, CollectorStatus
from advisor.models import AssetRef, AssetType, RunKind, RunStatus, SymbolInfo
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
    assert repo.load_source_state(db, "alpaca_bars").consecutive_failures == 0

    failed = CollectorResult("alpaca_bars", CollectorStatus.FAILED, [], 120, "ConnectError: down")
    repo.record_source_health(db, run_id, failed, 3, datetime(2026, 10, 13, 19, 15, tzinfo=UTC))
    skipped = CollectorResult("alpaca_bars", CollectorStatus.SKIPPED, [], 0, "circuit breaker open")
    repo.record_source_health(db, run_id, skipped, 3, NOW)

    state = repo.load_source_state(db, "alpaca_bars")
    assert state.consecutive_failures == 3
    assert state.last_attempt_et_date == date(2026, 10, 13)

    row = db.execute("select * from source_health where status = 'failed'").fetchone()
    assert (row["latency_ms"], row["records"], row["error"]) == (120, 0, "ConnectError: down")


def test_upsert_symbols_inserts_updates_and_deactivates(db):
    repo.upsert_symbols(db, [info("AAPL"), info("GONE")])
    repo.upsert_symbols(db, [info("AAPL", exchange="NASDAQ"), info("MSFT")])
    rows = db.execute("select symbol, exchange, active from symbols order by symbol").fetchall()
    assert [(r["symbol"], r["exchange"], r["active"]) for r in rows] == [
        ("AAPL", "NASDAQ", True),
        ("GONE", "NYSE", False),
        ("MSFT", "NYSE", True),
    ]


def test_upsert_symbols_refuses_an_empty_stock_universe(db):
    repo.upsert_symbols(db, [info("AAPL")])
    crypto = SymbolInfo(symbol="BTC", asset_type=AssetType.CRYPTO, name="Bitcoin", exchange="-")
    for symbols in ([], [crypto]):
        with pytest.raises(ValueError, match="refusing to upsert an empty stock universe"):
            repo.upsert_symbols(db, symbols)
    rows = db.execute("select symbol, active from symbols").fetchall()
    assert [(r["symbol"], r["active"]) for r in rows] == [("AAPL", True)]


def test_load_held_symbols_nets_sells(db):
    db.execute(
        "insert into lots (symbol, asset_type, qty, price, bought_at) values"
        " ('AAPL', 'stock', 10, 100, '2026-01-02'),"
        " ('SOLD', 'stock', 5, 20, '2026-01-02'),"
        " ('BTC', 'crypto', 0.5, 60000, '2026-02-01')"
    )
    db.execute(
        "insert into sells (symbol, asset_type, qty, price, sold_at) values"
        " ('AAPL', 'stock', 4, 120, '2026-05-01'), ('SOLD', 'stock', 5, 25, '2026-05-01')"
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
