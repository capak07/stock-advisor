from datetime import UTC, date, datetime

import httpx
import pytest

from advisor.collectors.base import PartialFetch, Scope, check_deadline
from advisor.collectors.cache import DiskCache
from advisor.models import AssetType, Market, RunKind, RunStatus
from advisor.run import RunDeps, execute_run
from fakes import FRESH_START, FakeCollector, bar, fake_price_collectors, history

NOW = datetime(2026, 10, 14, 12, 15, tzinfo=UTC)
US = ["AAA", "BBB", "CCC"]
TSX = ["RY.TO", "TD.TO"]
SMALL = {Market.US: 3, Market.TSX: 2}
EVERYONE = ["AAA", "BBB", "CCC", "RY.TO", "TD.TO"]


def make_deps(db, tmp_path, *, prices=None, us_records=None, extra=None):
    collectors = fake_price_collectors(US, TSX)
    if us_records is not None:
        collectors["nasdaq_symbols"].records_for = us_records
    if prices is not None:
        collectors["yfinance_bars"] = prices
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
    tsx = symbol.endswith(".TO")
    db.execute(
        "insert into lots (account, symbol, asset_type, qty, price, currency, fx_rate_cad, bought_at)"
        " values ('tfsa', %s, 'stock', 10, 5, %s, %s, '2026-09-01')",
        (symbol, "CAD" if tsx else "USD", None if tsx else 1.37),
    )


def market_features(db, run_id):
    rows = db.execute(
        "select symbol, features from features_live where run_id = %s order by symbol", (run_id,)
    ).fetchall()
    return {r["symbol"]: r["features"] for r in rows}


def test_successful_run_is_published_with_a_per_market_summary(db, tmp_path):
    deps = make_deps(db, tmp_path)
    outcome = execute_run(deps, RunKind.PRE_OPEN, NOW, min_universe=SMALL)

    assert outcome.status is RunStatus.SUCCESS
    row = run_row(db, outcome.run_id)
    assert row["published"] is True
    assert (row["sources_ok"], row["sources_total"]) == (3, 3)
    assert row["summary"] == {
        "markets": {
            "US": {
                "universe": 3, "priced": 3, "passed_filters": 3, "fresh": 3,
                "fresh_since": "2026-10-12", "shortlist": 3,
            },
            "TSX": {  # the TSX was closed on 2026-10-12, so its floor is 10-09
                "universe": 2, "priced": 2, "passed_filters": 2, "fresh": 2,
                "fresh_since": "2026-10-09", "shortlist": 2,
            },
        },
        "priority": 0, "priority_unpriced": [], "unconfirmed_jumps": 0, "shortlist": 5,
    }
    assert deps.collectors["yfinance_bars"].calls == [EVERYONE]  # one call for both markets
    assert health(db, outcome.run_id) == [
        ("nasdaq_symbols", "ok"), ("tmx_symbols", "ok"), ("yfinance_bars", "ok"),
    ]
    markets = db.execute(
        "select market, count(*) as n from symbols where active group by market order by market"
    ).fetchall()
    assert [(r["market"], r["n"]) for r in markets] == [("TSX", 2), ("US", 3)]


def test_holdings_of_both_markets_are_priced_first_and_get_features(db, tmp_path):
    hold(db)
    hold(db, "SHOP.TO")
    db.execute("insert into watchlist (symbol, asset_type) values ('BTC', 'crypto')")
    deps = make_deps(db, tmp_path)
    outcome = execute_run(deps, RunKind.PRE_OPEN, NOW, min_universe=SMALL)

    assert deps.collectors["yfinance_bars"].calls == [["OTCX", "SHOP.TO"], EVERYONE]
    features = market_features(db, outcome.run_id)
    assert sorted(features) == ["OTCX", "SHOP.TO"]
    assert features["OTCX"] == {
        "last_close": 10.0, "adv20": 2_000_000.0, "history_days": 70, "last_day": "2026-10-13",
        "stale": False, "unconfirmed_jump": False,
    }
    assert outcome.summary["priority"] == 2
    assert outcome.summary["markets"]["US"]["priced"] == 4
    assert outcome.summary["markets"]["TSX"]["priced"] == 3


def test_each_market_is_judged_against_its_own_calendar(db, tmp_path):
    # Pre-open on 2026-10-13: the NYSE traded 10-12 (floor 10-09); the TSX was closed for
    # Thanksgiving (last session 10-09, floor 10-08). Bars ending 10-08 are fresh only on the TSX.
    hold(db)
    hold(db, "SHOP.TO")
    prices = FakeCollector(
        "yfinance_bars",
        records_for=lambda syms: [b for s in syms for b in history(s, 70, start=date(2026, 7, 31))],
    )
    outcome = execute_run(
        make_deps(db, tmp_path, prices=prices),
        RunKind.PRE_OPEN,
        datetime(2026, 10, 13, 12, 15, tzinfo=UTC),
        min_universe=SMALL,
    )

    features = market_features(db, outcome.run_id)
    assert {s: f["stale"] for s, f in features.items()} == {"OTCX": True, "SHOP.TO": False}
    us, tsx = outcome.summary["markets"]["US"], outcome.summary["markets"]["TSX"]
    assert (us["fresh_since"], us["fresh"]) == ("2026-10-09", 0)
    assert (tsx["fresh_since"], tsx["fresh"]) == ("2026-10-08", 3)
    assert outcome.status is RunStatus.FAILED
    assert outcome.summary["failed_reason"] == ["US: too few fresh priced symbols (0 of 4)"]


def test_holdings_are_saved_even_when_a_later_stage_fails(db, tmp_path):
    hold(db)
    deps = make_deps(db, tmp_path, us_records=lambda _: [object()])
    with pytest.raises(AttributeError):
        execute_run(deps, RunKind.PRE_OPEN, NOW, min_universe={Market.US: 1, Market.TSX: 1})
    assert db.execute("select symbol from features_live").fetchone()["symbol"] == "OTCX"
    row = db.execute("select * from runs").fetchone()
    assert (row["status"], row["published"]) == ("failed", False)
    assert row["summary"]["error"].startswith("AttributeError")


def test_price_outage_fails_the_run_for_both_markets(db, tmp_path):
    prices = FakeCollector("yfinance_bars", error=httpx.ConnectError("down"))
    outcome = execute_run(
        make_deps(db, tmp_path, prices=prices), RunKind.PRE_OPEN, NOW, min_universe=SMALL
    )

    assert outcome.status is RunStatus.FAILED
    assert run_row(db, outcome.run_id)["published"] is False
    assert outcome.summary["failed_reason"] == [
        "US: too few fresh priced symbols (0 of 3)",
        "TSX: too few fresh priced symbols (0 of 2)",
    ]
    assert ("yfinance_bars", "failed") in health(db, outcome.run_id)


def test_partial_prices_degrade_the_run(db, tmp_path):
    some = [b for s in ("AAA", "BBB", "RY.TO") for b in history(s, 70, start=FRESH_START)]
    prices = FakeCollector(
        "yfinance_bars", error=PartialFetch(some, "1 of 2 Yahoo downloads returned no bars")
    )
    outcome = execute_run(
        make_deps(db, tmp_path, prices=prices), RunKind.PRE_OPEN, NOW, min_universe=SMALL
    )

    assert outcome.status is RunStatus.DEGRADED
    assert run_row(db, outcome.run_id)["published"] is True
    assert ("yfinance_bars", "partial") in health(db, outcome.run_id)
    assert outcome.summary["markets"]["US"]["priced"] == 2
    assert outcome.summary["markets"]["TSX"]["priced"] == 1


def test_a_source_failing_in_one_phase_reports_one_partial_row(db, tmp_path):
    hold(db)

    def records_for(symbols):
        if list(symbols) != ["OTCX"]:
            raise httpx.ConnectError("down")
        return history("OTCX", 70, start=FRESH_START)

    prices = FakeCollector("yfinance_bars", records_for=records_for)
    outcome = execute_run(
        make_deps(db, tmp_path, prices=prices), RunKind.PRE_OPEN, NOW, min_universe=SMALL
    )
    rows = health(db, outcome.run_id)
    assert rows.count(("yfinance_bars", "partial")) == 1
    assert len([s for s, _ in rows if s == "yfinance_bars"]) == 1
    assert outcome.status is RunStatus.FAILED
    assert market_features(db, outcome.run_id)["OTCX"]["stale"] is False


def test_an_unconfirmed_jump_is_kept_and_flagged(db, tmp_path):
    hold(db, "SHOP.TO")

    def records_for(symbols):
        bars = [b for s in symbols for b in history(s, 70, start=FRESH_START)]
        jumps = {("SHOP.TO", date(2026, 10, 13)), ("RY.TO", date(2026, 10, 13))}
        return [  # both jump 10 -> 16 (+60%) on their latest bar
            bar(b.symbol, b.day, 16.0)
            if (b.symbol, b.day) in jumps or (b.symbol == "AAA" and b.day >= date(2026, 10, 1))
            else b  # AAA jumped on 10-01 and stays at the new level: flagged once, long ago
            for b in bars
        ]

    prices = FakeCollector("yfinance_bars", records_for=records_for)
    outcome = execute_run(
        make_deps(db, tmp_path, prices=prices), RunKind.PRE_OPEN, NOW, min_universe=SMALL
    )

    assert outcome.status is RunStatus.SUCCESS
    # SHOP.TO from phase 1, RY.TO from phase 2; AAA's older flagged day does not count
    assert outcome.summary["unconfirmed_jumps"] == 2
    features = market_features(db, outcome.run_id)["SHOP.TO"]
    assert (features["last_close"], features["unconfirmed_jump"]) == (16.0, True)


def test_enrichment_gets_priority_then_crypto_then_both_markets_interleaved(db, tmp_path):
    hold(db)
    db.execute("insert into watchlist (symbol, asset_type) values ('BTC', 'crypto')")
    extra = {
        "news": FakeCollector("news", core=False),
        "macro": FakeCollector("macro", scope=Scope.MARKET),
        "coins": FakeCollector("coins", asset_types=frozenset({AssetType.CRYPTO})),
        "mixed": FakeCollector("mixed", asset_types=frozenset({AssetType.STOCK, AssetType.CRYPTO})),
    }
    outcome = execute_run(
        make_deps(db, tmp_path, extra=extra), RunKind.PRE_OPEN, NOW, min_universe=SMALL
    )

    assert outcome.status is RunStatus.SUCCESS
    assert extra["news"].calls == [["OTCX", "AAA", "RY.TO", "BBB", "TD.TO", "CCC"]]
    assert extra["mixed"].calls == [["OTCX", "BTC", "AAA", "RY.TO", "BBB", "TD.TO", "CCC"]]
    assert extra["macro"].calls == [[]]
    assert extra["coins"].calls == [["BTC"]]
    assert outcome.summary["shortlist"] == 6
    assert [s for s, _ in health(db, outcome.run_id)] == [
        "coins", "macro", "mixed", "nasdaq_symbols", "news", "tmx_symbols", "yfinance_bars",
    ]


def test_a_failing_core_enrichment_source_degrades_the_run(db, tmp_path):
    extra = {"filings": FakeCollector("filings", core=True, error=httpx.ConnectError("down"))}
    outcome = execute_run(
        make_deps(db, tmp_path, extra=extra), RunKind.PRE_OPEN, NOW, min_universe=SMALL
    )
    assert outcome.status is RunStatus.DEGRADED
    assert ("filings", "failed") in health(db, outcome.run_id)


def test_a_truncated_universe_fails_the_run_and_keeps_that_markets_symbols(db, tmp_path):
    db.execute(
        "insert into symbols (symbol, asset_type, market, name, exchange)"
        " values ('OLD.TO', 'stock', 'TSX', 'Old Co', 'TSX')"
    )
    extra = {"news": FakeCollector("news")}
    outcome = execute_run(
        make_deps(db, tmp_path, extra=extra),
        RunKind.PRE_OPEN,
        NOW,
        min_universe={Market.US: 3, Market.TSX: 300},
    )

    assert outcome.status is RunStatus.FAILED
    assert outcome.summary["failed_reason"] == ["TSX: universe too small (2 < 300)"]
    assert run_row(db, outcome.run_id)["published"] is False
    rows = db.execute("select symbol, market, active from symbols order by symbol").fetchall()
    assert [(r["symbol"], r["market"], r["active"]) for r in rows] == [
        ("AAA", "US", True), ("BBB", "US", True), ("CCC", "US", True),  # US saved independently
        ("OLD.TO", "TSX", True),  # a truncated TSX universe deactivates nothing
    ]
    assert outcome.summary["markets"]["TSX"]["shortlist"] == 0
    assert outcome.summary["shortlist"] == 0
    assert extra["news"].calls == []  # a run that cannot publish spends no enrichment calls


def test_default_minimums_come_from_the_markets_table(db, tmp_path):
    outcome = execute_run(make_deps(db, tmp_path), RunKind.PRE_OPEN, NOW)
    assert outcome.summary["failed_reason"] == [
        "US: universe too small (3 < 1000)", "TSX: universe too small (2 < 300)",
    ]


def test_stale_prices_fail_the_run_and_flag_holding_features(db, tmp_path):
    hold(db)
    prices = FakeCollector(  # bars end 2026-08-09: two months behind a 2026-10-14 run
        "yfinance_bars", records_for=lambda syms: [b for s in syms for b in history(s, 70)]
    )
    outcome = execute_run(
        make_deps(db, tmp_path, prices=prices), RunKind.PRE_OPEN, NOW, min_universe=SMALL
    )

    assert outcome.status is RunStatus.FAILED
    assert run_row(db, outcome.run_id)["published"] is False
    assert outcome.summary["failed_reason"] == [
        "US: too few fresh priced symbols (0 of 4)",
        "TSX: too few fresh priced symbols (0 of 2)",
    ]
    assert market_features(db, outcome.run_id)["OTCX"]["stale"] is True


def test_unexpected_error_marks_run_failed_and_propagates(db, tmp_path):
    deps = make_deps(db, tmp_path, us_records=lambda _: [object()])
    with pytest.raises(AttributeError):
        execute_run(deps, RunKind.PRE_OPEN, NOW, min_universe={Market.US: 1, Market.TSX: 1})
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
    execute_run(make_deps(db, tmp_path), RunKind.PRE_OPEN, NOW, min_universe=SMALL)
    old = db.execute("select status from runs where kind = 'pre_close'").fetchone()
    assert old["status"] == "failed"


def test_a_holding_missed_in_phase_one_is_retried_and_saved_in_phase_two(db, tmp_path):
    hold(db)
    prices = FakeCollector(  # Yahoo silently answers nothing for the lone holding at first
        "yfinance_bars",
        records_for=lambda syms: (
            [] if list(syms) == ["OTCX"]
            else [b for s in syms for b in history(s, 70, start=FRESH_START)]
        ),
    )
    outcome = execute_run(
        make_deps(db, tmp_path, prices=prices), RunKind.PRE_OPEN, NOW, min_universe=SMALL
    )

    assert prices.calls == [["OTCX"], ["AAA", "BBB", "CCC", "OTCX", "RY.TO", "TD.TO"]]
    assert outcome.status is RunStatus.SUCCESS
    assert outcome.summary["priority_unpriced"] == []
    assert market_features(db, outcome.run_id)["OTCX"] == {
        "last_close": 10.0, "adv20": 2_000_000.0, "history_days": 70, "last_day": "2026-10-13",
        "stale": False, "unconfirmed_jump": False,
    }


def test_a_holding_yahoo_never_returns_degrades_the_run(db, tmp_path):
    hold(db)
    prices = FakeCollector(
        "yfinance_bars",
        records_for=lambda syms: [
            b for s in syms if s != "OTCX" for b in history(s, 70, start=FRESH_START)
        ],
    )
    outcome = execute_run(
        make_deps(db, tmp_path, prices=prices), RunKind.PRE_OPEN, NOW, min_universe=SMALL
    )

    assert outcome.status is RunStatus.DEGRADED
    assert run_row(db, outcome.run_id)["published"] is True
    assert outcome.summary["priority_unpriced"] == ["OTCX"]
    assert market_features(db, outcome.run_id) == {}


def test_a_watchlist_only_stock_yahoo_never_returns_stays_summary_only(db, tmp_path):
    db.execute("insert into watchlist (symbol, asset_type) values ('OTCX', 'stock')")
    prices = FakeCollector(
        "yfinance_bars",
        records_for=lambda syms: [
            b for s in syms if s != "OTCX" for b in history(s, 70, start=FRESH_START)
        ],
    )
    outcome = execute_run(
        make_deps(db, tmp_path, prices=prices), RunKind.PRE_OPEN, NOW, min_universe=SMALL
    )

    assert outcome.status is RunStatus.SUCCESS
    assert outcome.summary["priority_unpriced"] == ["OTCX"]


def test_an_empty_market_reports_only_its_universe_reason(db, tmp_path):
    deps = make_deps(db, tmp_path)
    deps.collectors["tmx_symbols"].records_for = lambda _: []
    outcome = execute_run(deps, RunKind.PRE_OPEN, NOW, min_universe=SMALL)

    assert outcome.status is RunStatus.FAILED
    assert outcome.summary["failed_reason"] == ["TSX: universe too small (0 < 2)"]


def test_a_source_past_the_run_budget_fails_and_the_run_still_publishes(db, tmp_path):
    extra = {
        "slow": FakeCollector("slow", core=False, records_for=lambda syms: (check_deadline(), [])[1])
    }
    outcome = execute_run(
        make_deps(db, tmp_path, extra=extra), RunKind.PRE_OPEN, NOW, min_universe=SMALL, run_budget=0
    )
    assert outcome.status is RunStatus.SUCCESS  # the price fakes never consult the deadline
    assert run_row(db, outcome.run_id)["published"] is True
    assert ("slow", "failed") in health(db, outcome.run_id)
