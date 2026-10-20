from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import psycopg
import pytest

from advisor.collectors.base import Cadence, Category, CollectorResult, CollectorStatus
from advisor.collectors.registry import build_registry
from advisor.config import Settings
from advisor.models import AssetRef, AssetType, DailyClose, Market, RunKind, RunStatus, SymbolInfo
from advisor.news.stage import NewsRow, StoredNews
from advisor.store import repo
from fakes import FakeCollector, info

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


def test_sectors_are_set_on_known_stocks_and_kept_when_unclassified(db):
    repo.upsert_symbols(db, Market.US, [info("AAPL"), info("JPM"), info("ODD")])
    repo.write_sectors(db, [("AAPL", "Technology", "Consumer Electronics"), ("JPM", "Financial Services", "Banks—Diversified")])
    repo.write_sectors(db, [("AAPL", "Technology", "Consumer Electronics"), ("JPM", None, None), ("NEW", "Energy", "Oil & Gas E&P")])
    rows = db.execute("select symbol, sector, industry from symbols order by symbol").fetchall()
    assert [(r["symbol"], r["sector"], r["industry"]) for r in rows] == [
        ("AAPL", "Technology", "Consumer Electronics"),
        ("JPM", "Financial Services", "Banks—Diversified"),  # unclassified this week: kept
        ("ODD", None, None),
    ]  # NEW isn't in the universe table, so nothing is inserted


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


def news_row(symbol="AAPL", key="k1", hours_ago=1.0, sentiment=0.5, asset_type=AssetType.STOCK, cluster="c1"):
    return NewsRow(
        ref=AssetRef(symbol, asset_type), published_at=NOW - timedelta(hours=hours_ago),
        outlet="Reuters", url=f"https://www.reuters.com/{key}", title=f"Story {key}",
        sentiment=sentiment, cluster_id=cluster, story_key=key,
    )


def test_a_story_stored_by_an_earlier_run_is_kept_and_only_gains_a_missing_score(db):
    repo.write_news_items(db, [news_row(sentiment=None), news_row("BTC", asset_type=AssetType.CRYPTO)])
    repo.write_news_items(db, [news_row(sentiment=0.5), news_row(key="k2", sentiment=-0.25)])
    repo.write_news_items(db, [news_row(sentiment=0.9)])  # a later score never replaces one
    repo.write_news_items(db, [])
    rows = db.execute(
        "select symbol, asset_type, story_key, sentiment from news_items order by symbol, story_key"
    ).fetchall()
    assert [(r["symbol"], r["asset_type"], r["story_key"], r["sentiment"]) for r in rows] == [
        ("AAPL", "stock", "k1", 0.5), ("AAPL", "stock", "k2", -0.25), ("BTC", "crypto", "k1", 0.5),
    ]


def test_news_older_than_90_days_is_pruned(db):
    repo.write_news_items(db, [news_row(key="old", hours_ago=24 * 91), news_row(key="new")])
    assert repo.prune_news_items(db, NOW) == 1
    assert [r["story_key"] for r in db.execute("select story_key from news_items").fetchall()] == ["new"]


def test_daily_story_counts_cover_the_days_with_any_news(db):
    repo.write_news_items(db, [
        news_row(key="a", hours_ago=24 * 3, cluster="s1"),
        news_row(key="b", hours_ago=24 * 3, cluster="s1"),  # the same story twice: one
        news_row(key="c", hours_ago=24 * 3 - 1, cluster="s2"),
        news_row("RY.TO", key="d", hours_ago=24 * 2, cluster="s3"),
    ])
    counts = repo.news_daily_counts(
        db, [AssetRef("AAPL", AssetType.STOCK), AssetRef("TD.TO", AssetType.STOCK)],
        NOW - timedelta(days=10), NOW - timedelta(days=1),
    )
    assert counts == {
        AssetRef("AAPL", AssetType.STOCK): [2, 0],  # 2026-10-11 and 2026-10-12 (only RY.TO's day)
        AssetRef("TD.TO", AssetType.STOCK): [0, 0],
    }


def test_merging_features_adds_to_an_existing_row_or_creates_one(db):
    run_id = repo.create_run(db, RunKind.PRE_OPEN, DAY)
    aapl, ry = AssetRef("AAPL", AssetType.STOCK), AssetRef("RY.TO", AssetType.STOCK)
    repo.write_features_live(db, run_id, [(aapl, {"last_close": 150.0})], NOW)
    repo.merge_features_live(db, run_id, [(aapl, {"news_stories_48h": 2}), (ry, {"news_stories_48h": 0})], NOW)
    repo.merge_features_live(db, run_id, [], NOW)
    rows = db.execute("select symbol, features from features_live order by symbol").fetchall()
    assert [(r["symbol"], r["features"]) for r in rows] == [
        ("AAPL", {"last_close": 150.0, "news_stories_48h": 2}), ("RY.TO", {"news_stories_48h": 0}),
    ]


def test_a_symbol_can_hold_a_story_as_a_stock_and_as_a_coin(db):
    repo.write_news_items(db, [news_row("ONE"), news_row("ONE", asset_type=AssetType.CRYPTO)])
    rows = db.execute("select asset_type from news_items order by asset_type").fetchall()
    assert [r["asset_type"] for r in rows] == ["crypto", "stock"]


def test_a_later_missing_sentiment_keeps_the_score(db):
    repo.write_news_items(db, [news_row(sentiment=0.5)])
    repo.write_news_items(db, [news_row(sentiment=None)])
    assert db.execute("select sentiment from news_items").fetchone()["sentiment"] == 0.5


def test_daily_story_counts_respect_the_window(db):
    since = datetime(2026, 10, 10, tzinfo=UTC)
    until = datetime(2026, 10, 13, tzinfo=UTC)
    hours = lambda at: (NOW - at).total_seconds() / 3600  # noqa: E731
    repo.write_news_items(db, [
        news_row(key="a", hours_ago=hours(since), cluster="s1"),  # at `since`: counted
        news_row(key="b", hours_ago=hours(datetime(2026, 10, 12, 12, tzinfo=UTC)), cluster="s2"),
        news_row(key="c", hours_ago=hours(until), cluster="s3"),  # at `until`: left out
        news_row(key="d", hours_ago=hours(since - timedelta(days=1)), cluster="s4"),  # before
    ])
    counts = repo.news_daily_counts(db, [AssetRef("AAPL", AssetType.STOCK)], since, until)
    assert counts == {AssetRef("AAPL", AssetType.STOCK): [1, 1]}  # 2026-10-10 and 2026-10-12


def test_recent_news_returns_each_assets_rows_since_a_time(db):
    aapl = AssetRef("AAPL", AssetType.STOCK)
    repo.write_news_items(db, [
        news_row(key="new", hours_ago=10),
        news_row(key="old", hours_ago=100),
        news_row("BTC", key="coin", hours_ago=10, asset_type=AssetType.CRYPTO),
    ])
    assert repo.recent_news(db, [aapl], NOW - timedelta(hours=96)) == {
        aapl: [StoredNews(
            url="https://www.reuters.com/new", title="Story new",
            published_at=NOW - timedelta(hours=10), story_key="new",
        )],
    }


AAPL = AssetRef("AAPL", AssetType.STOCK)


def daily(symbol: str, day: date, close: float, asset_type: AssetType = AssetType.STOCK) -> DailyClose:
    return DailyClose(AssetRef(symbol, asset_type), day, close, "USD")


def test_closes_are_stored_and_a_refreshed_close_replaces_the_old_one(db):
    repo.write_daily_closes(db, [daily("AAPL", date(2026, 10, 12), 227.5), daily("AAPL", date(2026, 10, 13), 228.0)])
    repo.write_daily_closes(db, [daily("AAPL", date(2026, 10, 13), 228.4)])  # Yahoo re-adjusted it
    repo.write_daily_closes(db, [])
    assert repo.stored_closes(db, [AAPL], date(2026, 10, 1)) == {
        AAPL: {date(2026, 10, 12): 227.5, date(2026, 10, 13): 228.4},
    }
    assert repo.stored_closes(db, [AAPL], date(2026, 10, 13)) == {AAPL: {date(2026, 10, 13): 228.4}}
    assert repo.earliest_closes(db, [AAPL, AssetRef("MSFT", AssetType.STOCK)]) == {AAPL: date(2026, 10, 12)}


def test_a_coin_and_a_stock_can_share_a_symbol(db):
    day = date(2026, 10, 13)
    repo.write_daily_closes(db, [daily("LINK", day, 5.1), daily("LINK", day, 24.9, AssetType.CRYPTO)])
    stock, coin = AssetRef("LINK", AssetType.STOCK), AssetRef("LINK", AssetType.CRYPTO)
    assert repo.stored_closes(db, [stock, coin], day) == {stock: {day: 5.1}, coin: {day: 24.9}}
    assert repo.stored_closes(db, [coin], day) == {coin: {day: 24.9}}


def test_closes_before_a_day_can_be_rescaled(db):
    repo.write_daily_closes(db, [daily("AAPL", date(2026, 6, d), 200.0) for d in (1, 2, 3)])
    assert repo.rescale_closes(db, AAPL, date(2026, 6, 3), 0.5) == 2
    assert repo.stored_closes(db, [AAPL], date(2026, 6, 1)) == {
        AAPL: {date(2026, 6, 1): 100.0, date(2026, 6, 2): 100.0, date(2026, 6, 3): 200.0},
    }


def test_first_buys_cover_assets_sold_since(db):
    for symbol, asset_type, account, currency, fx, day in [
        ("AAPL", "stock", "tfsa", "USD", 1.36, "2025-05-12"),
        ("AAPL", "stock", "tfsa", "USD", 1.37, "2026-01-05"),
        ("BTC", "crypto", "crypto", "CAD", None, "2026-02-01"),
    ]:
        db.execute(
            "insert into lots (account, symbol, asset_type, qty, price, currency, fx_rate_cad, bought_at)"
            " values (%s, %s, %s, 1, 10, %s, %s, %s)",
            (account, symbol, asset_type, currency, fx, day),
        )
    db.execute(
        "insert into sells (account, symbol, asset_type, qty, price, currency, fx_rate_cad, sold_at)"
        " values ('tfsa', 'AAPL', 'stock', 2, 12, 'USD', 1.38, '2026-03-02')"
    )
    assert repo.first_buys(db) == {
        AAPL: date(2025, 5, 12), AssetRef("BTC", AssetType.CRYPTO): date(2026, 2, 1),
    }


def test_usd_cad_rates_are_stored_and_revised(db):
    assert repo.earliest_fx_rate(db) is None
    repo.write_fx_rates(db, [(date(2026, 10, 12), 1.37), (date(2026, 10, 13), 1.3712)])
    repo.write_fx_rates(db, [(date(2026, 10, 13), 1.3715)])  # the bank revised it
    repo.write_fx_rates(db, [])
    rows = db.execute("select day, usd_cad from fx_rates order by day").fetchall()
    assert [(r["day"], float(r["usd_cad"])) for r in rows] == [
        (date(2026, 10, 12), 1.37), (date(2026, 10, 13), 1.3715),
    ]
    assert repo.earliest_fx_rate(db) == date(2026, 10, 12)


def test_old_closes_are_pruned_except_holdings_and_benchmarks(db):
    old, recent = date(2024, 9, 2), date(2026, 10, 13)
    repo.write_daily_closes(db, [
        daily("AAPL", old, 150.0), daily("SPY", old, 540.0), daily("PLTR", old, 30.0),
        daily("PLTR", recent, 182.7),
    ])
    db.execute(
        "insert into lots (account, symbol, asset_type, qty, price, currency, fx_rate_cad, bought_at)"
        " values ('tfsa', 'AAPL', 'stock', 1, 150, 'USD', 1.35, '2024-09-02')"
    )
    assert repo.prune_daily_closes(db, date(2024, 10, 14), ["SPY", "XIU.TO"]) == 1
    rows = db.execute("select symbol, day from daily_closes order by symbol, day").fetchall()
    assert [(r["symbol"], r["day"]) for r in rows] == [("AAPL", old), ("PLTR", recent), ("SPY", old)]


def test_sources_mirror_the_registry(db):
    repo.write_sources(db, {
        "fred": FakeCollector("fred", core=True, category=Category.MACRO, cadence=Cadence.DAILY),
        "gone": FakeCollector("gone"),
    })
    repo.write_sources(db, {
        "fred": FakeCollector("fred", core=False, category=Category.MACRO, cadence=Cadence.DAILY),
        "coins": FakeCollector("coins", asset_types=frozenset({AssetType.CRYPTO}), markets=frozenset()),
        "both": FakeCollector(
            "both", asset_types=frozenset({AssetType.STOCK, AssetType.CRYPTO}), markets=frozenset({Market.US})
        ),
    })
    rows = db.execute(
        "select name, category, core, cadence, asset_types, markets from sources order by name"
    ).fetchall()
    assert [tuple(r.values()) for r in rows] == [
        ("both", "prices", True, "per_run", ["crypto", "stock"], ["US"]),
        ("coins", "prices", True, "per_run", ["crypto"], []),
        ("fred", "macro", False, "daily", ["stock"], ["TSX", "US"]),
    ]  # "gone" left the registry, so it left the table


def test_the_real_registry_fits_the_sources_table(db):
    # The table's CHECK lists copy the Python enums; a new category or cadence needs a migration.
    with httpx.Client() as client:
        collectors = build_registry(Settings("postgresql://x", Path(".cache")), client)
    repo.write_sources(db, collectors)
    names = [r["name"] for r in db.execute("select name from sources order by name").fetchall()]
    assert names == sorted(collectors)
