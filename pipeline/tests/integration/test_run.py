import dataclasses
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest

from advisor.collectors.base import Category, PartialFetch, Scope, check_deadline
from advisor.collectors.cache import DiskCache
from advisor.collectors.coingecko import CryptoQuote
from advisor.collectors.feeds import NewsItem, TickerNewsItem
from advisor.models import AssetRef, AssetType, Market, RunKind, RunStatus
from advisor.news.stage import NewsRow
from advisor.run import RunDeps, empty_news_summary, execute_run
from advisor.store import repo
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
        "crypto": 0, "crypto_unquoted": [],
        "news": {"items": 0, "stories": 0, "rows": 0, "assets": 0, "sentiment": "not run"},
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
    deps = make_deps(db, tmp_path, extra=extra)
    outcome = execute_run(
        deps,
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
    assert deps.collectors["yfinance_bars"].calls == []  # no bulk Yahoo fetch for a run that cannot publish


def test_a_run_that_cannot_publish_still_retries_unpriced_holdings(db, tmp_path):
    hold(db)

    def records_for(symbols):  # phase 1 misses the holding; the retry finds it
        if list(symbols) == ["OTCX"] and not prices.calls[:-1]:
            return []
        return [b for s in symbols for b in history(s, 70, start=FRESH_START)]

    prices = FakeCollector("yfinance_bars", best_effort=True, records_for=records_for)
    deps = make_deps(db, tmp_path, prices=prices)
    outcome = execute_run(
        deps, RunKind.PRE_OPEN, NOW, min_universe={Market.US: 3, Market.TSX: 300}
    )

    assert prices.calls == [["OTCX"], ["OTCX"]]  # the retry, but no bulk fetch
    assert outcome.status is RunStatus.FAILED
    assert outcome.summary["failed_reason"] == ["TSX: universe too small (2 < 300)"]
    assert outcome.summary["priority_unpriced"] == []
    assert "OTCX" in market_features(db, outcome.run_id)


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


CRYPTO = frozenset({AssetType.CRYPTO})


def crypto_sources(quoted=("BTC",), kraken_close=82100.0) -> dict[str, FakeCollector]:
    """CoinGecko, Coinbase and Kraken fakes: Coinbase's 30 finished days end 2026-10-13 at 82,000."""

    def quote(symbol: str) -> CryptoQuote:
        return CryptoQuote(
            symbol=symbol, coin_id=symbol.lower(), price_cad=117087.0, market_cap_rank=1,
            updated_at=NOW,
        )

    def candles(symbols):
        start = date(2026, 9, 14)
        return [b for s in symbols for b in history(s, 30, 82000.0, source="coinbase", start=start)]

    return {
        "coingecko": FakeCollector(
            "coingecko", asset_types=CRYPTO, record_type=CryptoQuote,
            records_for=lambda symbols: [quote(s) for s in symbols if s in quoted],
        ),
        "coinbase_candles": FakeCollector(
            "coinbase_candles", core=False, asset_types=CRYPTO, records_for=candles
        ),
        "kraken_ohlc": FakeCollector(
            "kraken_ohlc", core=False, asset_types=CRYPTO,
            records_for=lambda symbols: [
                bar(s, date(2026, 10, 13), kraken_close, source="kraken") for s in symbols
            ],
        ),
    }


def hold_crypto(db, symbol="BTC"):
    db.execute(
        "insert into lots (account, symbol, asset_type, qty, price, currency, bought_at)"
        " values ('crypto', %s, 'crypto', 0.5, 100000, 'CAD', '2026-09-01')",
        (symbol,),
    )


def test_held_crypto_is_priced_in_the_holdings_phase(db, tmp_path):
    hold_crypto(db)
    extra = crypto_sources()
    outcome = execute_run(
        make_deps(db, tmp_path, extra=extra), RunKind.PRE_OPEN, NOW, min_universe=SMALL
    )

    assert outcome.status is RunStatus.SUCCESS
    for name in extra:  # once each, for the coins, and not again in enrichment
        assert extra[name].calls == [["BTC"]]
    row = db.execute(
        "select asset_type, features from features_live where run_id = %s and symbol = 'BTC'",
        (outcome.run_id,),
    ).fetchone()
    assert row["asset_type"] == "crypto"
    assert row["features"] == {
        "price_cad": 117087.0, "market_cap_cad": None, "volume_24h_cad": None,
        "change_24h_pct": None, "market_cap_rank": 1,
        "quote_updated_at": "2026-10-14T12:15:00+00:00", "quote_stale": False,
        "last_close_usd": 82000.0, "history_days": 30, "last_day": "2026-10-13",
        "stale": False, "unconfirmed_price": False,
    }
    assert (outcome.summary["crypto"], outcome.summary["crypto_unquoted"]) == (1, [])


def test_a_held_coin_without_a_cad_quote_degrades_the_run(db, tmp_path):
    hold_crypto(db)
    outcome = execute_run(
        make_deps(db, tmp_path, extra=crypto_sources(quoted=())), RunKind.PRE_OPEN, NOW,
        min_universe=SMALL,
    )
    assert outcome.status is RunStatus.DEGRADED  # the holding can't be valued in CAD
    assert outcome.summary["crypto_unquoted"] == ["BTC"]


def test_a_watched_coin_without_a_quote_stays_summary_only(db, tmp_path):
    db.execute("insert into watchlist (symbol, asset_type) values ('ETH', 'crypto')")
    outcome = execute_run(
        make_deps(db, tmp_path, extra=crypto_sources(quoted=())), RunKind.PRE_OPEN, NOW,
        min_universe=SMALL,
    )
    assert outcome.status is RunStatus.SUCCESS
    assert outcome.summary["crypto_unquoted"] == ["ETH"]


def test_exchanges_that_disagree_leave_the_latest_crypto_price_unconfirmed(db, tmp_path):
    hold_crypto(db)
    outcome = execute_run(
        make_deps(db, tmp_path, extra=crypto_sources(kraken_close=90000.0)), RunKind.PRE_OPEN,
        NOW, min_universe=SMALL,
    )
    assert market_features(db, outcome.run_id)["BTC"]["unconfirmed_price"] is True


def test_a_failing_coingecko_values_holdings_from_its_last_quote(db, tmp_path):
    hold_crypto(db)
    extra = crypto_sources()
    extra["coingecko"].freshness = timedelta(days=2)  # as the real source: quotes are cached
    execute_run(make_deps(db, tmp_path, extra=extra), RunKind.PRE_OPEN, NOW, min_universe=SMALL)
    extra["coingecko"].error = httpx.HTTPStatusError(
        "HTTP 429", request=httpx.Request("GET", "https://api.coingecko.com"),
        response=httpx.Response(429),
    )
    outcome = execute_run(
        make_deps(db, tmp_path, extra=extra), RunKind.PRE_CLOSE, NOW, min_universe=SMALL
    )
    assert outcome.status is RunStatus.DEGRADED  # a core source served from cache
    assert outcome.summary["crypto_unquoted"] == []
    assert ("coingecko", "stale") in health(db, outcome.run_id)
    assert market_features(db, outcome.run_id)["BTC"]["price_cad"] == 117087.0


def test_without_crypto_no_crypto_source_is_asked(db, tmp_path):
    hold(db)
    extra = crypto_sources()
    outcome = execute_run(
        make_deps(db, tmp_path, extra=extra), RunKind.PRE_OPEN, NOW, min_universe=SMALL
    )
    assert outcome.status is RunStatus.SUCCESS
    assert [extra[name].calls for name in extra] == [[], [], []]


def news_sources() -> dict[str, FakeCollector]:
    """A per-stock source with one story per stock, and a market-wide feed with one tagged story."""

    def per_stock(symbols):
        return [
            TickerNewsItem(
                symbol=s, source="google_news", outlet="Reuters", title=f"{s} wins a big contract",
                url=f"https://news.google.com/rss/articles/{s}", published_at=NOW - timedelta(hours=2),
            )
            for s in symbols
        ]

    def market_wide(_):
        return [
            NewsItem(
                source="cnbc_news", outlet="CNBC", title="Dividend raised (NYSE: AAA)",
                url="https://www.cnbc.com/aaa-dividend", published_at=NOW - timedelta(hours=1),
            ),
            NewsItem(
                source="cnbc_news", outlet="CNBC", title="Bitcoin slides below $60,000",
                url="https://www.cnbc.com/bitcoin", published_at=NOW - timedelta(hours=1),
            ),
        ]

    return {
        "google_news": FakeCollector(
            "google_news", category=Category.NEWS, record_type=TickerNewsItem, records_for=per_stock
        ),
        "cnbc_news": FakeCollector(
            "cnbc_news", core=False, category=Category.NEWS, scope=Scope.MARKET,
            record_type=NewsItem, records_for=market_wide,
        ),
    }


def test_the_news_stage_stores_stories_and_adds_news_features(db, tmp_path):
    hold(db)
    calls: list = []

    def scorer(titles):
        calls.append(sorted(titles))
        return [0.5] * len(titles)

    deps = dataclasses.replace(
        make_deps(db, tmp_path, extra=news_sources()), news_scorer=lambda: scorer
    )
    outcome = execute_run(deps, RunKind.PRE_OPEN, NOW, min_universe=SMALL)

    assert outcome.status is RunStatus.SUCCESS
    assert outcome.summary["news"] == {
        "items": 8, "stories": 8, "rows": 7, "assets": 6, "sentiment": "finbert",
    }  # the Bitcoin story names no target: no coin is held or watched
    rows = db.execute(
        "select symbol, asset_type, outlet, sentiment from news_items order by symbol, outlet"
    ).fetchall()
    assert [(r["symbol"], r["outlet"]) for r in rows] == [
        ("AAA", "CNBC"), ("AAA", "Reuters"), ("BBB", "Reuters"), ("CCC", "Reuters"),
        ("OTCX", "Reuters"), ("RY.TO", "Reuters"), ("TD.TO", "Reuters"),
    ]
    assert {r["sentiment"] for r in rows} == {0.5}
    assert len(calls) == 1 and len(calls[0]) == 7  # one scoring pass, one headline per story kept
    features = market_features(db, outcome.run_id)
    assert features["AAA"]["news_stories_48h"] == 2
    assert features["OTCX"]["last_close"] == 10.0  # merged into the holding's price row
    assert features["OTCX"]["news_stories_48h"] == 1


def test_a_coins_name_from_coingecko_finds_its_news(db, tmp_path):
    hold_crypto(db)
    extra = crypto_sources() | news_sources()
    named = CryptoQuote(symbol="BTC", coin_id="bitcoin", name="Bitcoin", price_cad=117087.0, updated_at=NOW)
    extra["coingecko"].records_for = lambda symbols: [named]
    outcome = execute_run(make_deps(db, tmp_path, extra=extra), RunKind.PRE_OPEN, NOW, min_universe=SMALL)
    rows = db.execute("select symbol, asset_type, title from news_items where asset_type = 'crypto'").fetchall()
    assert [(r["symbol"], r["title"]) for r in rows] == [("BTC", "Bitcoin slides below $60,000")]
    assert outcome.summary["news"]["sentiment"] == "unavailable"  # tests run without FinBERT


def test_a_failing_sentiment_model_leaves_stories_unscored_and_the_run_publishes(db, tmp_path):
    def broken():
        raise OSError("couldn't reach huggingface.co")

    deps = dataclasses.replace(make_deps(db, tmp_path, extra=news_sources()), news_scorer=broken)
    outcome = execute_run(deps, RunKind.PRE_OPEN, NOW, min_universe=SMALL)
    assert outcome.status is RunStatus.SUCCESS
    assert outcome.summary["news"]["sentiment"] == "failed: OSError: couldn't reach huggingface.co"
    rows = db.execute("select sentiment from news_items").fetchall()
    assert len(rows) == 6 and {r["sentiment"] for r in rows} == {None}  # a later run scores them


def stored_news(db):
    return db.execute("select symbol, sentiment from news_items order by symbol, outlet").fetchall()


def test_a_scorer_that_raises_leaves_stories_unscored(db, tmp_path):
    hold(db)

    def raising_scorer(titles):
        raise RuntimeError("boom")

    deps = dataclasses.replace(
        make_deps(db, tmp_path, extra=news_sources()), news_scorer=lambda: raising_scorer
    )
    outcome = execute_run(deps, RunKind.PRE_OPEN, NOW, min_universe=SMALL)

    assert outcome.status is RunStatus.SUCCESS
    assert outcome.summary["news"]["sentiment"].startswith("failed: RuntimeError")
    rows = stored_news(db)
    assert len(rows) == 7 and {r["sentiment"] for r in rows} == {None}  # a later run scores them
    assert market_features(db, outcome.run_id)["OTCX"]["news_stories_48h"] == 1


def test_scoring_is_skipped_near_the_run_budget(db, tmp_path, monkeypatch):
    monkeypatch.setattr("advisor.run.SCORING_RESERVE_SECONDS", 10**6)
    hold(db)
    calls: list = []

    def scorer(titles):
        calls.append(titles)
        return [0.5] * len(titles)

    deps = dataclasses.replace(
        make_deps(db, tmp_path, extra=news_sources()), news_scorer=lambda: scorer
    )
    outcome = execute_run(deps, RunKind.PRE_OPEN, NOW, min_universe=SMALL)

    assert outcome.status is RunStatus.SUCCESS
    assert outcome.summary["news"]["sentiment"] == "skipped: run budget"
    assert calls == []
    rows = stored_news(db)
    assert len(rows) == 7 and {r["sentiment"] for r in rows} == {None}


def test_old_news_is_pruned(db, tmp_path):
    old = NewsRow(
        ref=AssetRef("AAA", AssetType.STOCK), published_at=NOW - timedelta(days=91),
        outlet="Reuters", url="https://www.reuters.com/old", title="Story old",
        sentiment=0.5, cluster_id="old", story_key="old",
    )
    repo.write_news_items(db, [old])
    execute_run(
        make_deps(db, tmp_path, extra=news_sources()), RunKind.PRE_OPEN, NOW, min_universe=SMALL
    )
    titles = [r["title"] for r in db.execute("select title from news_items").fetchall()]
    assert "Story old" not in titles
    assert len(titles) == 6  # this run's stories were stored


def test_no_news_items_means_no_news_features(db, tmp_path):
    hold(db)
    calls: list = []

    def scorer(titles):
        calls.append(titles)
        return [0.5] * len(titles)

    extra = news_sources()
    for source in extra.values():
        source.records_for = lambda symbols: []
    deps = dataclasses.replace(make_deps(db, tmp_path, extra=extra), news_scorer=lambda: scorer)
    outcome = execute_run(deps, RunKind.PRE_OPEN, NOW, min_universe=SMALL)

    assert outcome.summary["news"]["sentiment"] == "no items"
    assert calls == []
    features = market_features(db, outcome.run_id)["OTCX"]
    assert features["last_close"] == 10.0
    assert [key for key in features if key.startswith("news_")] == []  # missing, not zero
    assert stored_news(db) == []


def test_news_does_not_run_when_the_run_is_not_enriched(db, tmp_path):
    extra = news_sources()
    outcome = execute_run(
        make_deps(db, tmp_path, extra=extra), RunKind.PRE_OPEN, NOW,
        min_universe={Market.US: 3, Market.TSX: 300},
    )

    assert outcome.status is RunStatus.FAILED
    assert outcome.summary["news"] == empty_news_summary()
    assert [source.calls for source in extra.values()] == [[], []]
    assert stored_news(db) == []


def test_a_story_stored_by_an_earlier_run_is_not_stored_twice(db, tmp_path):
    hold(db)
    # An earlier run stored OTCX's story under another outlet's item, an hour before this run's copy.
    repo.write_news_items(db, [NewsRow(
        ref=AssetRef("OTCX", AssetType.STOCK), published_at=NOW - timedelta(hours=3),
        outlet="Earlier Wire", url="https://www.example.com/otcx-contract",
        title="OTCX wins a big contract", sentiment=None, cluster_id="earlier", story_key="e" * 16,
    )])
    deps = dataclasses.replace(make_deps(db, tmp_path, extra=news_sources()), news_scorer=lambda: None)
    execute_run(deps, RunKind.PRE_OPEN, NOW, min_universe=SMALL)
    rows = db.execute(
        "select outlet from news_items where symbol = 'OTCX' and title = 'OTCX wins a big contract'"
    ).fetchall()
    assert [r["outlet"] for r in rows] == ["Earlier Wire"]
