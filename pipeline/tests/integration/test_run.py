from datetime import UTC, datetime

import httpx
import pytest

from advisor.collectors.base import PartialFetch, Scope
from advisor.collectors.cache import DiskCache
from advisor.models import AssetType, RunKind, RunStatus
from advisor.run import RunDeps, execute_run
from fakes import FRESH_START, FakeCollector, fake_price_collectors, history

NOW = datetime(2026, 10, 14, 12, 15, tzinfo=UTC)
UNIVERSE = ["AAA", "BBB", "CCC"]


def make_deps(db, tmp_path, *, universe=UNIVERSE, alpaca=None, universe_records=None, extra=None):
    collectors = fake_price_collectors(universe)
    if universe_records is not None:
        collectors["nasdaq_symbols"].records_for = universe_records
    if alpaca is not None:
        collectors["alpaca_bars"] = alpaca
    collectors.update(extra or {})
    return RunDeps(db, DiskCache(tmp_path), collectors)


def run_row(db, run_id):
    return db.execute("select * from runs where id = %s", (run_id,)).fetchone()


def health(db, run_id):
    rows = db.execute(
        "select source, status from source_health where run_id = %s order by source", (run_id,)
    ).fetchall()
    return [(r["source"], r["status"]) for r in rows]


def hold(db, symbol="OTCX"):
    db.execute(
        "insert into lots (symbol, asset_type, qty, price, bought_at)"
        " values (%s, 'stock', 10, 5, '2026-09-01')",
        (symbol,),
    )


def test_successful_run_is_published_with_summary(db, tmp_path):
    deps = make_deps(db, tmp_path)
    outcome = execute_run(deps, RunKind.PRE_OPEN, NOW, min_universe=3)

    assert outcome.status is RunStatus.SUCCESS
    row = run_row(db, outcome.run_id)
    assert row["published"] is True
    assert (row["sources_ok"], row["sources_total"]) == (3, 3)
    assert row["summary"] == {
        "universe": 3, "priced": 3, "passed_filters": 3, "priority": 0, "priority_unpriced": [],
        "fresh": 3, "fresh_since": "2026-10-12", "shortlist": 3,
    }
    assert deps.collectors["yfinance_bars"].calls == []
    assert health(db, outcome.run_id) == [("alpaca_bars", "ok"), ("nasdaq_symbols", "ok")]
    assert db.execute("select count(*) as n from symbols where active").fetchone()["n"] == 3


def test_holdings_are_priced_first_and_get_features(db, tmp_path):
    hold(db)
    db.execute("insert into watchlist (symbol, asset_type) values ('BTC', 'crypto')")
    deps = make_deps(db, tmp_path)
    outcome = execute_run(deps, RunKind.PRE_OPEN, NOW, min_universe=3)

    assert deps.collectors["alpaca_bars"].calls == [["OTCX"], ["AAA", "BBB", "CCC"]]
    assert health(db, outcome.run_id) == [("alpaca_bars", "ok"), ("nasdaq_symbols", "ok")]
    features = db.execute(
        "select symbol, features from features_live where run_id = %s", (outcome.run_id,)
    ).fetchall()
    assert [f["symbol"] for f in features] == ["OTCX"]
    assert features[0]["features"]["last_close"] == 10.0
    assert outcome.summary["priority"] == 1
    assert outcome.summary["priced"] == 4


def test_holdings_are_saved_even_when_a_later_stage_fails(db, tmp_path):
    hold(db)
    deps = make_deps(db, tmp_path, universe_records=lambda _: [object()])
    with pytest.raises(AttributeError):
        execute_run(deps, RunKind.PRE_OPEN, NOW, min_universe=1)
    assert db.execute("select symbol from features_live").fetchone()["symbol"] == "OTCX"
    row = db.execute("select * from runs").fetchone()
    assert (row["status"], row["published"]) == ("failed", False)
    assert row["summary"]["error"].startswith("AttributeError")


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


def test_partial_primary_prices_degrade_the_run_and_fall_back_for_the_rest(db, tmp_path):
    some = [b for s in ("AAA", "BBB") for b in history(s, 70, start=FRESH_START)]
    alpaca = FakeCollector("alpaca_bars", error=PartialFetch(some, "1 of 2 Alpaca requests failed"))
    deps = make_deps(db, tmp_path, alpaca=alpaca)
    outcome = execute_run(deps, RunKind.PRE_OPEN, NOW, min_universe=3)

    assert outcome.status is RunStatus.DEGRADED
    assert deps.collectors["yfinance_bars"].calls == [["CCC"]]
    assert health(db, outcome.run_id) == [
        ("alpaca_bars", "partial"), ("nasdaq_symbols", "ok"), ("yfinance_bars", "ok"),
    ]
    assert outcome.summary["priced"] == 3


def test_a_source_failing_in_one_phase_reports_one_partial_row(db, tmp_path):
    hold(db)

    def records_for(symbols):
        if list(symbols) != ["OTCX"]:
            raise httpx.ConnectError("down")
        return history("OTCX", 70, start=FRESH_START)

    alpaca = FakeCollector("alpaca_bars", records_for=records_for)
    outcome = execute_run(
        make_deps(db, tmp_path, alpaca=alpaca), RunKind.PRE_OPEN, NOW, min_universe=3
    )
    rows = health(db, outcome.run_id)
    assert rows.count(("alpaca_bars", "partial")) == 1
    assert len([s for s, _ in rows if s == "alpaca_bars"]) == 1
    assert ("yfinance_bars", "ok") in rows
    assert outcome.status is RunStatus.DEGRADED
    assert outcome.summary["priced"] == 4


def test_enrichment_collectors_get_priority_first_then_the_shortlist(db, tmp_path):
    hold(db)
    db.execute("insert into watchlist (symbol, asset_type) values ('BTC', 'crypto')")
    extra = {
        "news": FakeCollector("news", core=False),
        "macro": FakeCollector("macro", scope=Scope.MARKET),
        "coins": FakeCollector("coins", asset_types=frozenset({AssetType.CRYPTO})),
    }
    outcome = execute_run(make_deps(db, tmp_path, extra=extra), RunKind.PRE_OPEN, NOW, min_universe=3)

    assert outcome.status is RunStatus.SUCCESS
    assert extra["news"].calls == [["OTCX", "AAA", "BBB", "CCC"]]
    assert extra["macro"].calls == [[]]
    assert extra["coins"].calls == [["BTC"]]
    assert outcome.summary["shortlist"] == 4
    assert [s for s, _ in health(db, outcome.run_id)] == [
        "alpaca_bars", "coins", "macro", "nasdaq_symbols", "news",
    ]


def test_a_failing_core_enrichment_source_degrades_the_run(db, tmp_path):
    extra = {"filings": FakeCollector("filings", core=True, error=httpx.ConnectError("down"))}
    outcome = execute_run(make_deps(db, tmp_path, extra=extra), RunKind.PRE_OPEN, NOW, min_universe=3)
    assert outcome.status is RunStatus.DEGRADED
    assert ("filings", "failed") in health(db, outcome.run_id)


def test_truncated_universe_fails_the_run_and_stays_unpublished(db, tmp_path):
    db.execute(
        "insert into symbols (symbol, asset_type, name, exchange)"
        " values ('OLD', 'stock', 'Old Co', 'NYSE')"
    )
    extra = {"news": FakeCollector("news")}
    outcome = execute_run(
        make_deps(db, tmp_path, extra=extra), RunKind.PRE_OPEN, NOW, min_universe=1000
    )
    assert outcome.status is RunStatus.FAILED
    assert outcome.summary["failed_reason"] == ["universe too small (3 < 1000)"]
    assert run_row(db, outcome.run_id)["published"] is False
    old = db.execute("select active from symbols where symbol = 'OLD'").fetchone()
    assert old["active"] is True
    assert db.execute("select count(*) as n from symbols").fetchone()["n"] == 1
    assert outcome.summary["shortlist"] == 0
    assert extra["news"].calls == []  # a run that cannot publish spends no enrichment calls


def test_stale_prices_fail_the_run_and_flag_holding_features(db, tmp_path):
    hold(db)
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
    assert ("nasdaq_symbols", "ok") in health(db, row["id"])


def test_abandoned_runs_are_swept_when_a_run_starts(db, tmp_path):
    db.execute(
        "insert into runs (kind, et_date, started_at)"
        " values ('pre_close', '2026-10-13', '2026-10-14 09:00+00')"
    )
    execute_run(make_deps(db, tmp_path), RunKind.PRE_OPEN, NOW, min_universe=3)
    old = db.execute("select status from runs where kind = 'pre_close'").fetchone()
    assert old["status"] == "failed"
