import math
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import psycopg
import pytest

from advisor.collectors.base import Cadence, Category, CollectorResult, CollectorStatus
from advisor.collectors.registry import build_registry
from advisor.config import Settings
from advisor.daytrade.track import Outcome as DayOutcome
from advisor.models import (
    AssetRef,
    AssetType,
    BenchmarkResult,
    DailyClose,
    HoldingActionRow,
    Market,
    PickRow,
    RunKind,
    RunStatus,
    SymbolInfo,
)
from advisor.monitor.quarters import QuarterRow
from advisor.monitor.rows import EarningsRow, FilingRow, InsiderRow
from advisor.news.stage import NewsRow, StoredNews
from advisor.recommend.verdicts import Verdict
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


def test_the_coin_list_is_stored_and_coins_that_left_it_are_deactivated(db):
    assert repo.coins_refreshed_on(db) is None
    repo.upsert_symbols(db, Market.US, [info("AAPL")])
    day_one, day_two = datetime(2026, 10, 19, 13, tzinfo=UTC), datetime(2026, 10, 20, 13, tzinfo=UTC)
    repo.upsert_coins(db, [("BTC", "Bitcoin", 2e12), ("ETH", "Ethereum", 4e11), ("LUNA", "Terra", 1e9)], day_one)
    repo.upsert_coins(db, [("BTC", "Bitcoin", 2.1e12), ("ETH", "Ethereum", None)], day_two)
    rows = db.execute(
        "select symbol, asset_type, market, name, exchange, market_cap::float as cap, active"
        " from symbols order by symbol"
    ).fetchall()
    assert [tuple(r.values()) for r in rows] == [
        ("AAPL", "stock", "US", "AAPL Inc. Common Stock", "NYSE", None, True),  # stocks are untouched
        ("BTC", "crypto", None, "Bitcoin", "CoinGecko", 2.1e12, True),
        ("ETH", "crypto", None, "Ethereum", "CoinGecko", None, True),
        ("LUNA", "crypto", None, "Terra", "CoinGecko", 1e9, False),
    ]
    assert repo.coins_refreshed_on(db) == date(2026, 10, 20)
    with pytest.raises(ValueError, match="empty coin list"):
        repo.upsert_coins(db, [], day_two)


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


def test_a_saved_model_is_inactive_until_activated_and_keeps_its_files(db):
    trained = datetime(2026, 10, 24, 11, 0, tzinfo=UTC)
    files = {"h5_q50": b"\x1f\x8bmodel", "meta": b"{}"}
    repo.save_model(db, "stock_tsx-202610241100", "stock_tsx", trained, {"mean_rank_ic": 0.02}, 2.5, files)
    assert repo.active_model(db, "stock_tsx") is None
    repo.activate_model(db, "stock_tsx", "stock_tsx-202610241100")
    active = repo.active_model(db, "stock_tsx")
    assert (active.version, active.metrics, active.calibration_error, active.trained_at, active.active) == (
        "stock_tsx-202610241100", {"mean_rank_ic": 0.02}, 2.5, trained, True,
    )
    assert repo.load_model_files(db, "stock_tsx-202610241100") == files


def test_activating_a_model_retires_only_its_kinds_old_one(db):
    at = datetime(2026, 10, 24, tzinfo=UTC)
    for version, kind in (("us-1", "stock_us"), ("us-2", "stock_us"), ("tsx-1", "stock_tsx")):
        repo.save_model(db, version, kind, at, {}, 1.0, {})
    repo.activate_model(db, "stock_us", "us-1")
    repo.activate_model(db, "stock_tsx", "tsx-1")
    repo.activate_model(db, "stock_us", "us-2")
    assert repo.active_model(db, "stock_us").version == "us-2"
    assert repo.active_model(db, "stock_tsx").version == "tsx-1"
    with pytest.raises(ValueError, match="no stock_tsx model us-1"):
        repo.activate_model(db, "stock_tsx", "us-1")


def test_pruning_keeps_the_active_model_and_the_newest_others(db):
    for i in range(4):
        repo.save_model(db, f"us-{i}", "stock_us", datetime(2026, 10, 1 + i, tzinfo=UTC), {}, 1.0, {"meta": b"x"})
    repo.activate_model(db, "stock_us", "us-0")
    assert repo.prune_models(db, "stock_us", keep=2) == 2
    assert [r["version"] for r in db.execute("select version from models order by version")] == ["us-0", "us-3"]
    assert db.execute("select count(*) as n from model_files").fetchone()["n"] == 2  # files go with their model


def test_fee_settings_are_read_in_percent(db):
    assert repo.fee_settings(db) == (1.5, 2.0)


def test_picks_round_trip_with_their_market_and_json_lists(db):
    run_id = repo.create_run(db, RunKind.PRE_OPEN, DAY)
    pick = PickRow(
        "TD.TO", Market.TSX, "position", 63, date(2027, 1, 14), 80.5, 72.0, "medium", 41.5, 3.0, 1,
        [{"feature": "ret_63", "contribution": 0.012}],
        [{"type": "earnings", "date": "2026-12-04"}],
        date(2026, 10, 13), 25.25,
    )
    repo.write_picks(db, run_id, [pick])
    repo.write_picks(db, run_id, [])
    row = db.execute("select * from picks").fetchone()
    assert (row["run_id"], row["symbol"], row["asset_type"], row["market"], row["style"]) == (
        run_id, "TD.TO", "stock", "TSX", "position",
    )
    assert (row["horizon_days"], row["exit_by"], float(row["entry_ref_price"]), float(row["stop"])) == (
        63, date(2027, 1, 14), 80.5, 72.0,
    )
    assert (row["risk_level"], row["risk_score"], row["max_position_pct"], row["rank"]) == ("medium", 41.5, 3.0, 1)
    assert row["top_factors"] == [{"feature": "ret_63", "contribution": 0.012}]
    assert row["catalysts"] == [{"type": "earnings", "date": "2026-12-04"}]
    assert (row["feature_day"], float(row["bench_ref_price"])) == (date(2026, 10, 13), 25.25)


def test_open_picks_carry_their_runs_kind_and_exited_early_ones_drop_out(db):
    run_id = repo.create_run(db, RunKind.PRE_OPEN, DAY)
    pick = PickRow(
        "TD.TO", Market.TSX, "swing", 21, date(2026, 11, 13), 80.5, 72.0, "medium", 41.5, 3.0, 1, [], [],
        date(2026, 10, 13), 25.25,
    )
    repo.write_picks(db, run_id, [pick, replace(pick, symbol="RY.TO", rank=2)])
    db.execute("update picks set status = 'graded' where symbol = 'RY.TO'")
    [open_pick] = repo.open_picks(db)
    assert (open_pick.symbol, open_pick.market, open_pick.horizon_days, open_pick.exit_by) == (
        "TD.TO", "TSX", 21, date(2026, 11, 13),
    )
    assert (open_pick.entry_ref_price, open_pick.stop, open_pick.bench_ref_price) == (80.5, 72.0, 25.25)
    assert (open_pick.feature_day, open_pick.run_kind) == (date(2026, 10, 13), "pre_open")
    repo.mark_exited_early(db, [open_pick.id])
    repo.mark_exited_early(db, [])
    assert repo.open_picks(db) == []
    assert db.execute("select status from picks where symbol = 'TD.TO'").fetchone()["status"] == "exited_early"


def test_watchlist_verdicts_round_trip_with_reasons_and_details(db):
    run_id = repo.create_run(db, RunKind.PRE_OPEN, DAY)
    verdicts = [
        Verdict("TD.TO", "stock", "buy", ["P(beat XIU.TO) 0.65 over 63 trading days"], {"stop": 72.0}),
        Verdict("ETH", "crypto", "hold", ["no crypto model yet"]),
    ]
    repo.write_watchlist_verdicts(db, run_id, verdicts)
    repo.write_watchlist_verdicts(db, run_id, [])
    rows = db.execute("select * from watchlist_verdicts order by symbol").fetchall()
    assert [(r["run_id"], r["symbol"], r["asset_type"], r["verdict"]) for r in rows] == [
        (run_id, "ETH", "crypto", "hold"), (run_id, "TD.TO", "stock", "buy"),
    ]
    assert rows[0]["reasons"] == ["no crypto model yet"] and rows[0]["details"] == {}
    assert rows[1]["reasons"] == ["P(beat XIU.TO) 0.65 over 63 trading days"]
    assert rows[1]["details"] == {"stop": 72.0}


def test_news_sentiment_is_read_per_stock_and_nan_when_news_ran_without_scores(db):
    run_id = repo.create_run(db, RunKind.PRE_OPEN, DAY)
    stock = AssetType.STOCK
    repo.write_features_live(db, run_id, [
        (AssetRef("AAA", stock), {"last_close": 10.0, "news_stories_48h": 3, "news_sentiment_mean": 0.4}),
        (AssetRef("BBB", stock), {"last_close": 10.0, "news_stories_48h": 0, "news_sentiment_mean": None}),
        (AssetRef("CCC", stock), {"last_close": 10.0}),  # the news stage never reached it
        (AssetRef("DDD", stock), {"news_stories_48h": 1, "news_sentiment_mean": -0.2}),  # not asked for
    ], NOW)
    out = repo.news_sentiment(db, run_id, ["AAA", "BBB", "CCC"])
    assert set(out) == {"AAA", "BBB"}
    assert out["AAA"] == 0.4 and math.isnan(out["BBB"])


def test_trades_and_rates_load_for_the_ledger(db):
    db.execute(
        "insert into lots (account, symbol, asset_type, qty, price, currency, fx_rate_cad, bought_at, pick_id)"
        " values ('tfsa', 'AAPL', 'stock', 3, 10, 'USD', 1.36, '2026-01-05', null)"
    )
    db.execute(
        "insert into sells (account, symbol, asset_type, qty, price, currency, fx_rate_cad, sold_at)"
        " values ('tfsa', 'AAPL', 'stock', 1, 12, 'USD', 1.38, '2026-03-02')"
    )
    repo.write_fx_rates(db, [(date(2026, 10, 12), 1.37), (date(2026, 10, 13), 1.38)])
    trades = repo.load_trades(db)
    trades.sort(key=lambda t: t.day)
    assert [(t.side, t.day, t.qty, t.price, t.fx_rate_cad, t.pick_id) for t in trades] == [
        ("buy", date(2026, 1, 5), 3.0, 10.0, 1.36, None),
        ("sell", date(2026, 3, 2), 1.0, 12.0, 1.38, None),
    ]
    assert trades[0].asset_type is AssetType.STOCK
    assert (trades[0].account, trades[0].symbol, trades[0].currency) == ("tfsa", "AAPL", "USD")
    assert repo.load_fx_rates(db) == {date(2026, 10, 12): 1.37, date(2026, 10, 13): 1.38}
    assert repo.latest_fx_rate(db) == 1.38


def test_the_newest_trailing_stop_per_holding_is_remembered(db):
    old = repo.create_run(db, RunKind.PRE_CLOSE, date(2026, 10, 13))
    new = repo.create_run(db, RunKind.PRE_CLOSE, date(2026, 10, 14))
    for run_id, stop, feature_day in [(old, 9.0, "2026-10-12"), (new, 9.5, "2026-10-13")]:
        db.execute(
            "insert into holding_actions (run_id, account, symbol, asset_type, action, trailing_stop, feature_day)"
            " values (%s, 'tfsa', 'AAPL', 'stock', 'hold', %s, %s)",
            (run_id, stop, feature_day),
        )
    # a newer row without a stop or feature day does not count
    newest = repo.create_run(db, RunKind.PRE_CLOSE, date(2026, 10, 15))
    db.execute(
        "insert into holding_actions (run_id, account, symbol, asset_type, action)"
        " values (%s, 'tfsa', 'AAPL', 'stock', 'hold')",
        (newest,),
    )
    assert repo.previous_trailing_stops(db) == {("tfsa", "AAPL", "stock"): (date(2026, 10, 13), 9.5)}


def _action(symbol: str, account: str = "tfsa", trailing_stop: float | None = 18.0) -> HoldingActionRow:
    return HoldingActionRow(
        account, symbol, AssetType.STOCK, "hold", False, [], [], trailing_stop, None, None, None,
        date(2026, 11, 13), 21, date(2026, 10, 13), 20.0, 25.0, "medium", 3.0,
    )


def test_a_rescale_multiplies_the_refs_recorded_before_it(db):
    run_id = repo.create_run(db, RunKind.PRE_OPEN, DAY)
    pick = PickRow(
        "TD.TO", Market.TSX, "swing", 21, date(2026, 11, 13), 20.0, 18.0, "medium", 41.5, 3.0, 1, [], [],
        date(2026, 10, 13), 25.0,
    )
    repo.write_picks(db, run_id, [
        pick,
        replace(pick, rank=2),  # graded below: untouched
        replace(pick, symbol="RY.TO", rank=3),
        replace(pick, symbol="AAPL", market=Market.US, rank=1),
    ])
    db.execute("update picks set status = 'graded' where rank = 2")
    repo.write_holding_actions(db, run_id, [
        _action("TD.TO"), _action("TD.TO", "rrsp", trailing_stop=None), _action("RY.TO"), _action("AAPL"),
    ])
    graded_run = repo.create_run(db, RunKind.PRE_OPEN, DAY)
    repo.write_holding_actions(db, graded_run, [_action("TD.TO")])
    db.execute(
        "insert into holding_action_outcomes (run_id, account, symbol, asset_type, exit_price, ret,"
        " ret_net_of_fx, bench_ret, excess, beat, hit_stop) values (%s, 'tfsa', 'TD.TO', 'stock', 21, 0.05,"
        " 0.05, 0, 0.05, true, false)",
        (graded_run,),
    )

    repo.rescale_refs(db, AssetRef("TD.TO", AssetType.STOCK), 0.5)  # a 2-for-1 split
    picks = db.execute("select symbol, rank, entry_ref_price, stop, bench_ref_price from picks order by id").fetchall()
    assert [(p["symbol"], float(p["entry_ref_price"]), float(p["stop"])) for p in picks] == [
        ("TD.TO", 10.0, 9.0), ("TD.TO", 20.0, 18.0), ("RY.TO", 20.0, 18.0), ("AAPL", 20.0, 18.0),
    ]
    actions = (
        "select run_id, account, symbol, ref_price, trailing_stop, bench_ref_price from holding_actions"
        " order by run_id, account, symbol"
    )
    held = db.execute(actions).fetchall()
    assert [(a["run_id"], a["account"], a["symbol"], float(a["ref_price"]),
             None if a["trailing_stop"] is None else float(a["trailing_stop"])) for a in held] == [
        (run_id, "rrsp", "TD.TO", 10.0, None),
        (run_id, "tfsa", "AAPL", 20.0, 18.0),
        (run_id, "tfsa", "RY.TO", 20.0, 18.0),
        (run_id, "tfsa", "TD.TO", 10.0, 9.0),
        (graded_run, "tfsa", "TD.TO", 20.0, 18.0),  # graded: its outcome stands
    ]

    # The TSX benchmark's rescale moves every TSX ref to it, and nothing of the US's.
    repo.rescale_refs(db, AssetRef("XIU.TO", AssetType.STOCK), 2.0)
    picks = db.execute("select symbol, bench_ref_price from picks order by id").fetchall()
    assert [(p["symbol"], float(p["bench_ref_price"])) for p in picks] == [
        ("TD.TO", 50.0), ("TD.TO", 25.0), ("RY.TO", 50.0), ("AAPL", 25.0),
    ]
    held = db.execute(actions).fetchall()
    assert [float(a["bench_ref_price"]) for a in held] == [50.0, 25.0, 50.0, 50.0, 25.0]


def test_a_picks_status_changes_only_while_it_is_open(db):
    run_id = repo.create_run(db, RunKind.PRE_OPEN, DAY)
    pick = PickRow(
        "TD.TO", Market.TSX, "swing", 21, date(2026, 11, 13), 20.0, 18.0, "medium", 41.5, 3.0, 1, [], [],
        date(2026, 10, 13), 25.0,
    )
    repo.write_picks(db, run_id, [pick, replace(pick, symbol="RY.TO", rank=2)])
    repo.mark_exited_early(db, [p.id for p in repo.open_picks(db) if p.symbol == "TD.TO"])
    repo.set_pick_status(db, [r["id"] for r in db.execute("select id from picks")], "graded")
    rows = db.execute("select symbol, status from picks order by id").fetchall()
    assert [(r["symbol"], r["status"]) for r in rows] == [("TD.TO", "exited_early"), ("RY.TO", "graded")]


def test_the_symbols_to_grade_are_open_picks_and_ungraded_actions_with_an_exit_by(db):
    run_id = repo.create_run(db, RunKind.PRE_OPEN, DAY)
    pick = PickRow(
        "TD.TO", Market.TSX, "swing", 21, date(2026, 11, 13), 20.0, 18.0, "medium", 41.5, 3.0, 1, [], [],
        date(2026, 10, 13), 25.0,
    )
    repo.write_picks(db, run_id, [pick, replace(pick, symbol="BB.TO", rank=2)])
    db.execute("update picks set status = 'graded' where symbol = 'BB.TO'")  # graded: nothing to wait for
    repo.write_holding_actions(db, run_id, [
        _action("AAPL"),
        _action("TD.TO"),  # also an open pick's: listed once
        replace(_action("MSFT"), exit_by=None),  # a hold with no horizon is never graded
        _action("NVDA"),  # graded below
        replace(_action("BTC", "crypto"), asset_type=AssetType.CRYPTO),  # coins aren't graded
    ])
    db.execute(
        "insert into holding_action_outcomes (run_id, account, symbol, asset_type, exit_price, ret,"
        " ret_net_of_fx, bench_ret, excess, beat, hit_stop) values (%s, 'tfsa', 'NVDA', 'stock', 21, 0.05,"
        " 0.05, 0, 0.05, true, false)",
        (run_id,),
    )
    assert repo.symbols_to_grade(db) == ["AAPL", "TD.TO"]


T0 = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)


def test_a_benchmark_run_is_started_and_finished(db):
    run_id = repo.start_benchmark_run(db, T0, "abc1234")
    repo.finish_benchmark_run(db, run_id, T0 + timedelta(hours=2), "success", {"markets": {}})
    row = db.execute("select * from benchmark_runs where id = %s", (run_id,)).fetchone()
    assert (row["status"], row["git_sha"], row["report"]) == ("success", "abc1234", {"markets": {}})


def test_a_killed_benchmark_is_marked_failed_by_the_next_start(db):
    killed = repo.start_benchmark_run(db, T0, None)
    repo.start_benchmark_run(db, T0 + timedelta(hours=8), None)
    row = db.execute("select * from benchmark_runs where id = %s", (killed,)).fetchone()
    assert row["status"] == "failed" and row["report"]["error"].startswith("abandoned")


def test_a_recent_running_benchmark_is_left_alone(db):
    running = repo.start_benchmark_run(db, T0, None)
    repo.start_benchmark_run(db, T0 + timedelta(hours=1), None)
    assert db.execute("select status from benchmark_runs where id = %s", (running,)).fetchone()["status"] == "running"


def test_accepting_a_config_retires_the_markets_previous_one(db):
    run_id = repo.start_benchmark_run(db, T0, None)
    assert repo.active_config(db, "TSX") is None
    first = repo.accept_config(db, "TSX", {"version": 1}, "first", run_id, T0)
    second = repo.accept_config(db, "TSX", {"version": 1, "x": 1}, "better", run_id, T0)
    active = repo.active_config(db, "TSX")
    assert active.id == second != first and active.reason == "better" and active.config == {"version": 1, "x": 1}
    repo.write_benchmark_results(db, run_id, [BenchmarkResult("TSX", "baseline", "pooled", {"a": 1})])
    assert db.execute("select metrics from benchmark_results").fetchone()["metrics"] == {"a": 1}


def test_the_top_coins_are_the_largest_listed_ones_without_stablecoins(db):
    now = datetime(2026, 10, 20, 13, tzinfo=UTC)
    repo.upsert_coins(db, [
        ("USDT", "Tether", 1.8e11), ("BTC", "Bitcoin", 2e12), ("ETH", "Ethereum", 4e11),
        ("SOL", "Solana", 9e10), ("NEW", "New coin", None),
    ], now)
    assert repo.top_coins(db, 3) == ["BTC", "ETH", "SOL"]
    assert repo.top_coins(db, 10) == ["BTC", "ETH", "SOL", "NEW"]  # no market cap last


def as_pipeline(db):
    db.execute("set role pipeline_rw")


def filing(accession="a1", symbol="AAPL", days_ago=1.0):
    return FilingRow(accession, symbol, "8-K", NOW - timedelta(days=days_ago), DAY, ["2.02"], "https://x/" + accession)


def quarter(symbol="AAPL", months_ago=0, revenue=100.0):
    end = date(2026, 9, 30) - timedelta(days=91 * months_ago)
    return QuarterRow(symbol, end - timedelta(days=90), end, end.year, "Q3", revenue, 50.0, 20.0, 10.0, 1.5,
                      "10-Q", end + timedelta(days=30), "acc", False)


def test_filings_are_idempotent_and_pruned_after_400_days(db):
    as_pipeline(db)
    try:
        repo.write_filings(db, [filing("a1"), filing("old", days_ago=401), filing("keep", days_ago=399)])
        repo.write_filings(db, [filing("a1")])
        repo.write_filings(db, [])
        repo.prune_holding_monitor(db, NOW)
    finally:
        db.execute("reset role")
    got = [r["accession"] for r in db.execute("select accession from filings order by accession").fetchall()]
    assert got == ["a1", "keep"]


def test_a_restated_quarter_replaces_values_and_only_12_are_kept(db):
    as_pipeline(db)
    try:
        repo.write_financial_quarters(db, [quarter(months_ago=i) for i in range(13)] + [quarter("MSFT")])
        repo.write_financial_quarters(db, [quarter(months_ago=0, revenue=120.0)])
    finally:
        db.execute("reset role")
    aapl = db.execute(
        "select period_end, revenue from financial_quarters where symbol = 'AAPL' order by period_end desc"
    ).fetchall()
    assert len(aapl) == 12 and float(aapl[0]["revenue"]) == 120.0
    assert aapl[-1]["period_end"] > quarter(months_ago=12).period_end
    assert db.execute("select count(*) as n from financial_quarters where symbol = 'MSFT'").fetchone()["n"] == 1


def test_earnings_reports_upsert_and_prune_after_3_years(db):
    def report(day, actual=None):
        return EarningsRow("AAPL", day, datetime.combine(day, datetime.min.time(), tzinfo=UTC), 1.0, actual, None)

    as_pipeline(db)
    try:
        repo.write_earnings_reports(db, [report(date(2026, 10, 30)), report(date(2023, 9, 1))])
        repo.write_earnings_reports(db, [report(date(2026, 10, 30), actual=1.2)])
        repo.prune_holding_monitor(db, NOW)
    finally:
        db.execute("reset role")
    rows = db.execute("select report_date, eps_actual from earnings_reports").fetchall()
    assert [(r["report_date"], float(r["eps_actual"])) for r in rows] == [(date(2026, 10, 30), 1.2)]


def test_a_moved_upcoming_earnings_date_replaces_the_old_one(db):
    def report(symbol, day, actual=None):
        return EarningsRow(symbol, day, datetime.combine(day, datetime.min.time(), tzinfo=UTC), 1.0, actual, None)

    as_pipeline(db)
    try:
        repo.write_earnings_reports(db, [
            report("AAPL", date(2026, 7, 30), actual=1.1), report("AAPL", date(2026, 11, 20)),
            report("MSFT", date(2026, 11, 21)),
        ])
        # Yahoo moves AAPL's next report; MSFT isn't fetched this time
        repo.write_earnings_reports(db, [report("AAPL", date(2026, 7, 30), actual=1.1), report("AAPL", date(2026, 11, 25))])
    finally:
        db.execute("reset role")
    rows = db.execute("select symbol, report_date, eps_actual from earnings_reports order by symbol, report_date").fetchall()
    assert [(r["symbol"], r["report_date"], r["eps_actual"] is not None) for r in rows] == [
        ("AAPL", date(2026, 7, 30), True), ("AAPL", date(2026, 11, 25), False), ("MSFT", date(2026, 11, 21), False),
    ]


def insider(line, days_ago=1.0, accession="i1"):
    return InsiderRow(accession, line, "AAPL", NOW - timedelta(days=days_ago), DAY, "A B", "CEO", "P",
                      10.0, 5.0, 50.0, False)


def test_a_rewritten_filing_or_insider_trade_keeps_when_it_was_first_stored(db):
    first = NOW - timedelta(days=3)
    as_pipeline(db)
    try:
        repo.write_filings(db, [filing("a1")])
        repo.write_insider_trades(db, [insider(0)])
    finally:
        db.execute("reset role")
    db.execute("update filings set added_at = %s", (first,))
    db.execute("update insider_trades set added_at = %s", (first,))
    as_pipeline(db)
    try:
        repo.write_filings(db, [replace(filing("a1"), items=["2.02", "9.01"]), filing("a2")])
        repo.write_insider_trades(db, [insider(0), insider(1)])
    finally:
        db.execute("reset role")
    filings = {r["accession"]: r["added_at"] for r in db.execute("select accession, added_at from filings").fetchall()}
    trades = {r["line"]: r["added_at"] for r in db.execute("select line, added_at from insider_trades").fetchall()}
    assert filings["a1"] == first and filings["a2"] > first
    assert trades[0] == first and trades[1] > first


def test_insider_trades_are_idempotent_and_pruned_after_400_days(db):
    def trade(line, days_ago=1.0, accession="i1"):
        return InsiderRow(accession, line, "AAPL", NOW - timedelta(days=days_ago), DAY, "A B", "CEO", "P",
                          10.0, 5.0, 50.0, False)

    as_pipeline(db)
    try:
        repo.write_insider_trades(db, [trade(0), trade(1), trade(0, 401, "old"), trade(0, 399, "keep")])
        repo.write_insider_trades(db, [trade(0), trade(1)])
        repo.prune_holding_monitor(db, NOW)
    finally:
        db.execute("reset role")
    got = db.execute("select accession, line from insider_trades order by accession, line").fetchall()
    assert [(r["accession"], r["line"]) for r in got] == [("i1", 0), ("i1", 1), ("keep", 0)]


def seed_alert(db, symbol, direction, level, asset_type="stock", hit=False, dismissed=False):
    return db.execute(
        "insert into price_alerts (symbol, asset_type, direction, level, hit_at, dismissed_at)"
        " values (%s, %s, %s, %s, %s, %s) returning id",
        (symbol, asset_type, direction, level, NOW if hit else None, NOW if dismissed else None),
    ).fetchone()["id"]


def test_active_alerts_skip_hit_and_dismissed_ones(db):
    a = seed_alert(db, "AAPL", "above", 200)
    seed_alert(db, "MSFT", "below", 300, hit=True)
    seed_alert(db, "NVDA", "below", 100, dismissed=True)
    c = seed_alert(db, "BTC", "above", 90000, "crypto")
    as_pipeline(db)
    try:
        alerts = repo.active_price_alerts(db)
        symbols = repo.alert_symbols(db)
    finally:
        db.execute("reset role")
    assert sorted((x.id, x.symbol, x.asset_type, x.direction, x.level) for x in alerts) == [
        (a, "AAPL", "stock", "above", 200.0), (c, "BTC", "crypto", "above", 90000.0)]
    assert symbols == {AssetRef("AAPL", AssetType.STOCK), AssetRef("BTC", AssetType.CRYPTO)}


def test_latest_closes_returns_each_assets_newest_day(db):
    aapl, btc = AssetRef("AAPL", AssetType.STOCK), AssetRef("BTC", AssetType.CRYPTO)
    repo.write_daily_closes(db, [
        DailyClose(aapl, DAY - timedelta(days=1), 100.0, "USD"), DailyClose(aapl, DAY, 110.0, "USD"),
        DailyClose(btc, DAY - timedelta(days=2), 5.0, "USD"),
    ])
    as_pipeline(db)
    try:
        got = repo.latest_closes(db, [aapl, btc, AssetRef("ZZZ", AssetType.STOCK)])
        assert repo.latest_closes(db, []) == {}
    finally:
        db.execute("reset role")
    assert got == {("AAPL", "stock"): 110.0, ("BTC", "crypto"): 5.0}


def test_mark_alerts_hit_never_overwrites_an_earlier_hit(db):
    first = seed_alert(db, "AAPL", "above", 100)
    second = seed_alert(db, "MSFT", "above", 100)
    as_pipeline(db)
    try:
        repo.mark_alerts_hit(db, [(first, 101.0)], NOW)
        repo.mark_alerts_hit(db, [(first, 150.0), (second, 102.0)], NOW + timedelta(days=1))
        repo.mark_alerts_hit(db, [], NOW)
    finally:
        db.execute("reset role")
    rows = {r["id"]: r for r in db.execute("select id, hit_at, hit_price from price_alerts").fetchall()}
    assert (rows[first]["hit_at"], float(rows[first]["hit_price"])) == (NOW, 101.0)
    assert (rows[second]["hit_at"], float(rows[second]["hit_price"])) == (NOW + timedelta(days=1), 102.0)


def signal_row(symbol="AAPL", market="US", **over):
    row = {
        "day": date(2026, 11, 10), "symbol": symbol, "market": market, "name": symbol + " Inc",
        "trigger_at": datetime(2026, 11, 10, 15, 0, tzinfo=UTC), "entry": 10.0, "or_high": 9.9,
        "or_low": 9.5, "stop": 9.7, "target": 10.6, "volume_x": 2.0, "cost_pct": 0.2, "cost_r": 0.07,
        "replay": {"p": 1}, "history": {"n": 2}, "net_replay_r": 0.3, "net_history_r": None,
        "eligible": True, "headlines": [],
    }
    row.update(over)
    return row


def test_daytrade_listings_are_active_stocks_in_us_and_tsx(db):
    repo.upsert_symbols(db, Market.US, [info("AAPL"), info("OLD")])
    repo.upsert_symbols(db, Market.US, [info("AAPL")])
    repo.upsert_symbols(db, Market.TSX, [info("RY.TO"), info("BAM-A.TO")])
    repo.upsert_coins(db, [("BTC", "Bitcoin", 2e12)], NOW)
    got = sorted((x.symbol, x.market) for x in repo.daytrade_listings(db))
    assert got == [("AAPL", Market.US), ("BAM-A.TO", Market.TSX), ("RY.TO", Market.TSX)]


def test_daytrade_settings_defaults(db):
    assert repo.daytrade_settings(db) == (1.5, 0.10, 50.0)


def test_daytrade_upsert_is_idempotent_and_keeps_rank_and_outcome(db):
    as_pipeline(db)
    try:
        day = date(2026, 11, 10)
        repo.start_daytrade_day(db, day, "scanning")
        repo.start_daytrade_day(db, day, "scanning")
        a = repo.upsert_daytrade_signal(db, signal_row())
        repo.set_daytrade_ranks(db, day, {a: 1})
        repo.update_daytrade_outcome(db, a, DayOutcome("target", NOW, 10.6, 2.0, 10.6, NOW), 1.9)
        again = repo.upsert_daytrade_signal(db, signal_row(entry=10.1, headlines=[{"title": "t"}]))
    finally:
        db.execute("reset role")
    assert again == a
    rows = repo.daytrade_signals_for(db, day)
    assert len(rows) == 1
    r = rows[0]
    assert (float(r["entry"]), r["rank"], r["status"], float(r["net_r"]), r["headlines"]) == (
        10.1, 1, "target", 1.9, [{"title": "t"}])


def test_daytrade_ranks_are_reset_when_reranked(db):
    day = date(2026, 11, 10)
    repo.start_daytrade_day(db, day, "scanning")
    a = repo.upsert_daytrade_signal(db, signal_row("AAPL"))
    b = repo.upsert_daytrade_signal(db, signal_row("MSFT"))
    repo.set_daytrade_ranks(db, day, {a: 1, b: 2})
    repo.set_daytrade_ranks(db, day, {b: 1})
    got = {r["symbol"]: r["rank"] for r in repo.daytrade_signals_for(db, day)}
    assert got == {"AAPL": None, "MSFT": 1}


def test_update_daytrade_day_only_known_columns(db):
    day = date(2026, 11, 10)
    repo.start_daytrade_day(db, day, "waiting")
    repo.update_daytrade_day(db, day, status="done", cycles=3, scanned=100)
    row = db.execute("select status, cycles, scanned from daytrade_days where day = %s", (day,)).fetchone()
    assert (row["status"], row["cycles"], row["scanned"]) == ("done", 3, 100)
    with pytest.raises(ValueError, match="bogus"):
        repo.update_daytrade_day(db, day, bogus=1)


def test_prune_daytrade_keeps_400_days(db):
    now = datetime(2026, 11, 10, 20, tzinfo=UTC)
    for d in (date(2026, 11, 10) - timedelta(days=401), date(2026, 11, 10) - timedelta(days=399)):
        repo.start_daytrade_day(db, d, "done")
    repo.upsert_daytrade_signal(db, signal_row(day=date(2026, 11, 10) - timedelta(days=401)))
    repo.prune_daytrade(db, now)
    assert [r["day"] for r in db.execute("select day from daytrade_days").fetchall()] == [
        date(2026, 11, 10) - timedelta(days=399)]
    assert db.execute("select count(*) as n from daytrade_signals").fetchone()["n"] == 0
