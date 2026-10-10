from datetime import UTC, date, datetime, timedelta

import httpx
import pytest

from advisor.collectors.base import Cadence, Scope
from advisor.collectors.cache import DiskCache
from advisor.models import RunKind, RunStatus, SymbolInfo
from advisor.run import RunDeps, execute_run
from fakes import FakeCollector, history, info

NOW = datetime(2026, 10, 14, 12, 15, tzinfo=UTC)
UNIVERSE = ["AAA", "BBB", "CCC"]
FRESH_START = date(2026, 8, 5)  # 70 daily bars from here end 2026-10-13, fresh for NOW


def make_deps(db, tmp_path, *, universe=UNIVERSE, alpaca=None, universe_records=None):
    collectors = {
        "nasdaq_symbols": FakeCollector(
            "nasdaq_symbols",
            records_for=universe_records or (lambda _: [info(s) for s in universe]),
            record_type=SymbolInfo,
            cadence=Cadence.DAILY,
            freshness=timedelta(days=3),
            scope=Scope.UNIVERSE,
        ),
        "alpaca_bars": alpaca or FakeCollector(
            "alpaca_bars",
            records_for=lambda syms: [b for s in syms for b in history(s, 70, start=FRESH_START)],
        ),
        "yfinance_bars": FakeCollector(
            "yfinance_bars",
            core=False,
            best_effort=True,
            records_for=lambda syms: [
                b for s in syms for b in history(s, 70, source="yfinance", start=FRESH_START)
            ],
        ),
    }
    return RunDeps(db, DiskCache(tmp_path), collectors)


def run_row(db, run_id):
    return db.execute("select * from runs where id = %s", (run_id,)).fetchone()


def health(db, run_id):
    rows = db.execute(
        "select source, status from source_health where run_id = %s order by source", (run_id,)
    ).fetchall()
    return [(r["source"], r["status"]) for r in rows]


def test_successful_run_is_published_with_summary(db, tmp_path):
    deps = make_deps(db, tmp_path)
    outcome = execute_run(deps, RunKind.PRE_OPEN, NOW, min_universe=3)

    assert outcome.status is RunStatus.SUCCESS
    row = run_row(db, outcome.run_id)
    assert row["published"] is True
    assert (row["sources_ok"], row["sources_total"]) == (3, 3)
    assert row["summary"] == {
        "universe": 3, "priced": 3, "passed_filters": 3, "priority": 0, "priority_unpriced": [],
        "fresh": 3, "fresh_since": "2026-10-12",
    }
    assert deps.collectors["yfinance_bars"].calls == []
    assert health(db, outcome.run_id) == [("alpaca_bars", "ok"), ("nasdaq_symbols", "ok")]
    assert db.execute("select count(*) as n from symbols where active").fetchone()["n"] == 3


def test_holding_outside_universe_is_priced_and_gets_features(db, tmp_path):
    db.execute(
        "insert into lots (symbol, asset_type, qty, price, bought_at)"
        " values ('OTCX', 'stock', 10, 5, '2026-09-01')"
    )
    db.execute("insert into watchlist (symbol, asset_type) values ('BTC', 'crypto')")
    outcome = execute_run(make_deps(db, tmp_path), RunKind.PRE_OPEN, NOW, min_universe=3)

    features = db.execute(
        "select symbol, features from features_live where run_id = %s", (outcome.run_id,)
    ).fetchall()
    assert [f["symbol"] for f in features] == ["OTCX"]
    assert features[0]["features"]["last_close"] == 10.0
    assert outcome.summary["priority"] == 1
    assert outcome.summary["priced"] == 4


def test_primary_price_outage_falls_back_and_marks_run_degraded(db, tmp_path):
    alpaca = FakeCollector("alpaca_bars", error=httpx.ConnectError("down"))
    outcome = execute_run(
        make_deps(db, tmp_path, alpaca=alpaca), RunKind.PRE_CLOSE, NOW, min_universe=3
    )

    assert outcome.status is RunStatus.DEGRADED
    row = run_row(db, outcome.run_id)
    assert row["published"] is True
    assert row["sources_ok"] == 2
    assert health(db, outcome.run_id) == [
        ("alpaca_bars", "failed"), ("nasdaq_symbols", "ok"), ("yfinance_bars", "ok"),
    ]
    assert outcome.summary["priced"] == 3


def test_truncated_universe_fails_the_run_and_stays_unpublished(db, tmp_path):
    db.execute(
        "insert into symbols (symbol, asset_type, name, exchange)"
        " values ('OLD', 'stock', 'Old Co', 'NYSE')"
    )
    outcome = execute_run(make_deps(db, tmp_path), RunKind.PRE_OPEN, NOW, min_universe=1000)
    assert outcome.status is RunStatus.FAILED
    assert outcome.summary["failed_reason"] == ["universe too small (3 < 1000)"]
    assert run_row(db, outcome.run_id)["published"] is False
    old = db.execute("select active from symbols where symbol = 'OLD'").fetchone()
    assert old["active"] is True
    assert db.execute("select count(*) as n from symbols").fetchone()["n"] == 1


def test_stale_prices_fail_the_run_and_flag_holding_features(db, tmp_path):
    db.execute(
        "insert into lots (symbol, asset_type, qty, price, bought_at)"
        " values ('OTCX', 'stock', 10, 5, '2026-09-01')"
    )
    alpaca = FakeCollector(  # bars end 2026-08-09: two months behind a 2026-10-14 run
        "alpaca_bars", records_for=lambda syms: [b for s in syms for b in history(s, 70)]
    )
    outcome = execute_run(
        make_deps(db, tmp_path, alpaca=alpaca), RunKind.PRE_OPEN, NOW, min_universe=3
    )

    assert outcome.status is RunStatus.FAILED
    assert run_row(db, outcome.run_id)["published"] is False
    assert outcome.summary["failed_reason"] == ["too few fresh priced symbols (0 of 4)"]
    features = db.execute(
        "select features from features_live where run_id = %s and symbol = 'OTCX'",
        (outcome.run_id,),
    ).fetchone()["features"]
    assert features["stale"] is True


def test_unexpected_error_marks_run_failed_and_propagates(db, tmp_path):
    deps = make_deps(db, tmp_path, universe_records=lambda _: [object()])
    with pytest.raises(AttributeError):
        execute_run(deps, RunKind.PRE_OPEN, NOW, min_universe=1)
    row = db.execute("select * from runs").fetchone()
    assert row["status"] == "failed"
    assert row["published"] is False
    assert row["summary"]["error"].startswith("AttributeError")
