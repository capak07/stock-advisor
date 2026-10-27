import dataclasses
import math
from datetime import UTC, date, datetime, timedelta

import httpx
import pandas as pd
import pytest

from advisor.collectors.base import Category, PartialFetch, Scope, check_deadline
from advisor.collectors.cache import DiskCache
from advisor.collectors.clinical_trials import TrialActivity
from advisor.collectors.coingecko import CryptoQuote
from advisor.collectors.feeds import NewsItem, TickerNewsItem
from advisor.collectors.sec_events import MaterialEvent
from advisor.collectors.series import SeriesObservation
from advisor.collectors.yfinance_earnings import EarningsReport
from advisor.markets import MARKETS
from advisor.model.dataset import load_market
from advisor.model.train import PARAMS, TrainConfig, fit_final, to_files, walk_forward
from advisor.models import (
    ET,
    AssetRef,
    AssetType,
    DailyClose,
    Market,
    PredictionRow,
    RunKind,
    RunStatus,
)
from advisor.news.stage import NewsRow
from advisor.recommend.risk import risk_levels
from advisor.run import RunDeps, empty_news_summary, execute_run
from advisor.store import repo
from advisor.training.sectors import all_sector_etfs
from fakes import FRESH_START, FakeCollector, bar, fake_price_collectors, history
from model_data import write_market

NOW = datetime(2026, 10, 14, 12, 15, tzinfo=UTC)
US = ["AAA", "BBB", "CCC"]
TSX = ["RY.TO", "TD.TO"]
SMALL = {Market.US: 3, Market.TSX: 2}
EVERYONE = ["AAA", "BBB", "CCC", "RY.TO", "TD.TO"]
# what phase 1 prices besides the holdings (the call is sorted): the benchmarks and sector ETFs
FUNDS = sorted(["SPY", "XIU.TO", *(etf for etfs in all_sector_etfs().values() for etf in etfs)])


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
        "crypto": 0, "crypto_unquoted": [], "coins": "skipped",
        "news": {"items": 0, "stories": 0, "rows": 0, "assets": 0, "sentiment": "not run"},
        # 70 closes for each shortlisted stock and for SPY and XIU.TO
        "history": {"closes": 490, "backfilled": [], "fx": 0, "rescaled": [], "pruned": 0},
        "model": {"US": {"skipped": "no active model"}, "TSX": {"skipped": "no active model"}},
        "picks": {"US": {"skipped": "no active model"}, "TSX": {"skipped": "no active model"}},
        "actions": {"written": 0, "by_action": {"sell": 0, "trim": 0, "add": 0, "hold": 0}},
    }
    # The benchmarks and sector ETFs are priced with the holdings, then one call covers both markets.
    assert deps.collectors["yfinance_bars"].calls == [FUNDS, EVERYONE]
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

    assert deps.collectors["yfinance_bars"].calls == [["OTCX", "SHOP.TO", *FUNDS], EVERYONE]
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

    def records_for(symbols):  # phase 1 (the holding and the benchmarks) works, the bulk fetch fails
        if "SPY" not in symbols:
            raise httpx.ConnectError("down")
        return [b for s in symbols for b in history(s, 70, start=FRESH_START)]

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
    # Only the benchmarks and ETFs (no holdings here): no bulk Yahoo fetch for a run that cannot publish.
    assert deps.collectors["yfinance_bars"].calls == [FUNDS]


def test_a_run_that_cannot_publish_still_retries_unpriced_holdings(db, tmp_path):
    hold(db)

    def records_for(symbols):  # phase 1 misses the holding (not the benchmarks); the retry finds it
        missing = {"OTCX"} if "SPY" in symbols else set()
        return [b for s in symbols if s not in missing for b in history(s, 70, start=FRESH_START)]

    prices = FakeCollector("yfinance_bars", best_effort=True, records_for=records_for)
    deps = make_deps(db, tmp_path, prices=prices)
    outcome = execute_run(
        deps, RunKind.PRE_OPEN, NOW, min_universe={Market.US: 3, Market.TSX: 300}
    )

    assert prices.calls == [["OTCX", *FUNDS], ["OTCX"]]  # the retry, but no bulk fetch
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
        records_for=lambda syms: [  # phase 1 answers only the benchmarks
            b for s in syms if not ("SPY" in syms and s == "OTCX")
            for b in history(s, 70, start=FRESH_START)
        ],
    )
    outcome = execute_run(
        make_deps(db, tmp_path, prices=prices), RunKind.PRE_OPEN, NOW, min_universe=SMALL
    )

    assert prices.calls == [["OTCX", *FUNDS], ["AAA", "BBB", "CCC", "OTCX", "RY.TO", "TD.TO"]]
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


def closes_by_symbol(db):
    rows = db.execute(
        "select symbol, currency, count(*) as n from daily_closes"
        " group by symbol, currency order by symbol"
    ).fetchall()
    return [(r["symbol"], r["currency"], r["n"]) for r in rows]


def test_a_run_stores_closes_for_holdings_watchlist_shortlist_and_benchmarks(db, tmp_path):
    hold(db)
    db.execute("insert into watchlist (symbol, asset_type) values ('NVDA', 'stock')")
    outcome = execute_run(make_deps(db, tmp_path), RunKind.PRE_OPEN, NOW, min_universe=SMALL)

    assert closes_by_symbol(db) == [
        ("AAA", "USD", 70), ("BBB", "USD", 70), ("CCC", "USD", 70), ("NVDA", "USD", 70),
        ("OTCX", "USD", 70), ("RY.TO", "CAD", 70), ("SPY", "USD", 70), ("TD.TO", "CAD", 70),
        ("XIU.TO", "CAD", 70),
    ]
    assert outcome.summary["history"] == {
        "closes": 630, "backfilled": [], "fx": 0, "rescaled": [], "pruned": 0,
    }  # no backfill: these tests leave the Yahoo download off


def test_held_coins_get_coinbase_closes_in_usd(db, tmp_path):
    hold_crypto(db)
    execute_run(make_deps(db, tmp_path, extra=crypto_sources()), RunKind.PRE_OPEN, NOW, min_universe=SMALL)
    row = db.execute(
        "select count(*) as n, min(currency) as currency, max(close) as close from daily_closes"
        " where symbol = 'BTC' and asset_type = 'crypto'"
    ).fetchone()
    assert (row["n"], row["currency"], float(row["close"])) == (30, "USD", 82000.0)


def valet_source(records):
    return FakeCollector(
        "boc_valet", core=False, scope=Scope.MARKET, record_type=SeriesObservation,
        records_for=lambda _: records,
    )


def test_the_first_run_backfills_a_year_of_closes_and_usd_cad(db, tmp_path, fixtures_dir):
    hold(db)  # bought 2026-09-01, so a year back is the start
    calls = []

    def download(tickers, start, end):
        calls.append((sorted(tickers), start, end))
        index = pd.DatetimeIndex([pd.Timestamp("2025-10-14"), pd.Timestamp("2025-10-15")])
        columns = pd.MultiIndex.from_product([tickers, ["Open", "High", "Low", "Close", "Volume"]])
        return pd.DataFrame([[9, 9, 9, 9.0, 100] * len(tickers)] * 2, index=index, columns=columns)

    body = (fixtures_dir / "boc" / "valet_observations_recent10.json").read_bytes()
    asked = []

    def bank(request):
        asked.append(request.url.params["start_date"])
        return httpx.Response(200, content=body)

    run_rate = SeriesObservation(series="FXUSDCAD", day=date(2026, 10, 13), value=1.3712)
    with httpx.Client(transport=httpx.MockTransport(bank)) as client:
        deps = dataclasses.replace(
            make_deps(db, tmp_path, extra={"boc_valet": valet_source([run_rate])}),
            download=download, http=client,
        )
        outcome = execute_run(deps, RunKind.PRE_OPEN, NOW, min_universe=SMALL)

    assert calls == [(["OTCX", "SPY", "XIU.TO"], date(2025, 10, 14), date(2026, 10, 15))]
    history = outcome.summary["history"]
    assert history["backfilled"] == ["OTCX", "SPY", "XIU.TO"]
    first = db.execute("select min(day) as day from daily_closes where symbol = 'SPY'").fetchone()
    assert first["day"] == date(2025, 10, 14)
    assert asked == ["2025-10-14"]  # the run had only Oct 13; the bank fills the year
    rates = db.execute("select count(*) as n, max(day) as last from fx_rates").fetchone()
    assert history["fx"] == rates["n"] >= 10 and rates["last"] == date(2026, 10, 13)
    assert outcome.status is RunStatus.SUCCESS


def test_a_failed_backfill_is_reported_and_the_run_still_publishes(db, tmp_path):
    hold(db)

    def download(tickers, start, end):
        raise RuntimeError("Yahoo said no")

    deps = dataclasses.replace(make_deps(db, tmp_path), download=download)
    outcome = execute_run(deps, RunKind.PRE_OPEN, NOW, min_universe=SMALL)

    assert outcome.status is RunStatus.SUCCESS
    assert run_row(db, outcome.run_id)["published"] is True
    history = outcome.summary["history"]
    assert history["backfill_error"] == "RuntimeError: Yahoo said no"
    assert history["closes"] == 560  # the holding, 5 shortlisted stocks and 2 benchmarks, 70 each


def test_a_split_rescales_the_stored_history(db, tmp_path):
    # Before a 2-for-1 split OTCX closed at 20; the fresh, re-adjusted bars say 10 from Aug 5.
    otcx = AssetRef("OTCX", AssetType.STOCK)
    repo.write_daily_closes(db, [
        DailyClose(otcx, date(2026, 7, 1) + timedelta(days=i), 20.0, "USD") for i in range(70)
    ])
    hold(db)
    outcome = execute_run(make_deps(db, tmp_path), RunKind.PRE_OPEN, NOW, min_universe=SMALL)

    assert outcome.summary["history"]["rescaled"] == ["OTCX"]
    stored = repo.stored_closes(db, [otcx], date(2026, 7, 1))[otcx]
    assert set(stored.values()) == {10.0}  # July rescaled, the fresh window replaced
    assert min(stored) == date(2026, 7, 1)


def test_a_rescale_whose_write_fails_is_undone_so_the_next_run_rescales_once(
    db, tmp_path, monkeypatch
):
    otcx = AssetRef("OTCX", AssetType.STOCK)
    repo.write_daily_closes(db, [
        DailyClose(otcx, date(2026, 7, 1) + timedelta(days=i), 20.0, "USD") for i in range(70)
    ])
    hold(db)

    def lost_connection(conn, closes):
        raise RuntimeError("connection lost")

    monkeypatch.setattr(repo, "write_daily_closes", lost_connection)
    first = execute_run(make_deps(db, tmp_path), RunKind.PRE_OPEN, NOW, min_universe=SMALL)
    assert first.summary["history"] == {"error": "RuntimeError: connection lost"}
    stored = repo.stored_closes(db, [otcx], date(2026, 7, 1))[otcx]
    assert set(stored.values()) == {20.0}  # July wasn't halved without the fresh closes

    monkeypatch.undo()
    second = execute_run(make_deps(db, tmp_path), RunKind.PRE_OPEN, NOW, min_universe=SMALL)
    assert second.summary["history"]["rescaled"] == ["OTCX"]
    stored = repo.stored_closes(db, [otcx], date(2026, 7, 1))[otcx]
    assert set(stored.values()) == {10.0}  # halved once, not twice


def test_a_symbol_yahoo_drops_from_the_backfill_is_named_and_asked_again(db, tmp_path):
    hold(db)
    calls = []

    def download(tickers, start, end):  # Yahoo leaves the holding out of the answer
        calls.append(sorted(tickers))
        answered = [t for t in tickers if t != "OTCX"]
        index = pd.DatetimeIndex([pd.Timestamp("2025-10-14")])
        columns = pd.MultiIndex.from_product([answered, ["Open", "High", "Low", "Close", "Volume"]])
        return pd.DataFrame([[9, 9, 9, 9.0, 100] * len(answered)], index=index, columns=columns)

    deps = dataclasses.replace(make_deps(db, tmp_path), download=download)
    first = execute_run(deps, RunKind.PRE_OPEN, NOW, min_universe=SMALL)
    assert first.summary["history"]["backfilled"] == ["SPY", "XIU.TO"]
    assert first.summary["history"]["backfill_missing"] == ["OTCX"]

    second = execute_run(deps, RunKind.PRE_OPEN, NOW, min_universe=SMALL)
    assert calls[-1] == ["OTCX"]  # only the one still short
    assert second.summary["history"]["backfill_missing"] == ["OTCX"]


def test_a_bank_of_canada_outage_is_reported_and_the_run_keeps_its_closes(db, tmp_path):
    hold(db)
    run_rate = SeriesObservation(series="FXUSDCAD", day=date(2026, 10, 13), value=1.3712)
    down = httpx.MockTransport(lambda request: httpx.Response(404, text="not found"))
    with httpx.Client(transport=down) as client:
        deps = dataclasses.replace(
            make_deps(db, tmp_path, extra={"boc_valet": valet_source([run_rate])}), http=client
        )
        outcome = execute_run(deps, RunKind.PRE_OPEN, NOW, min_universe=SMALL)

    assert outcome.status is RunStatus.SUCCESS
    history = outcome.summary["history"]
    assert history["fx_error"].startswith("HTTPStatusError: HTTP 404")
    assert history["fx"] == 1 and history["closes"] == 560  # the run's own rate and closes are kept


def test_a_run_that_cannot_publish_leaves_the_price_history_alone(db, tmp_path):
    hold(db)
    deps = dataclasses.replace(
        make_deps(db, tmp_path), download=lambda *args: pytest.fail("no backfill for a failed run")
    )
    outcome = execute_run(deps, RunKind.PRE_OPEN, NOW, min_universe={Market.US: 3, Market.TSX: 300})

    assert outcome.status is RunStatus.FAILED
    assert outcome.summary["history"] == {}
    assert closes_by_symbol(db) == []


def test_a_run_writes_the_registry_to_sources(db, tmp_path):
    deps = make_deps(db, tmp_path)
    execute_run(deps, RunKind.PRE_OPEN, NOW, min_universe=SMALL)
    names = [r["name"] for r in db.execute("select name from sources order by name").fetchall()]
    assert names == sorted(deps.collectors)


def test_a_registry_that_cant_be_written_is_reported_and_the_run_publishes(
    db, tmp_path, monkeypatch
):
    def refused(conn, collectors):
        raise RuntimeError("new row violates check constraint")

    monkeypatch.setattr(repo, "write_sources", refused)
    outcome = execute_run(make_deps(db, tmp_path), RunKind.PRE_OPEN, NOW, min_universe=SMALL)

    assert outcome.status is RunStatus.SUCCESS
    row = run_row(db, outcome.run_id)
    assert row["published"] is True
    assert row["summary"]["sources_error"] == "RuntimeError: new row violates check constraint"


def coinbase(asked, *, listed=True):
    """A Coinbase that answers each candle request with a close of 60,000 for every day asked."""

    def handler(request):
        if request.url.host != "api.exchange.coinbase.com":
            return httpx.Response(404)  # the Bank of Canada isn't under test here
        start = date.fromisoformat(request.url.params["start"][:10])
        stop = date.fromisoformat(request.url.params["end"][:10])
        asked.append((start, stop))
        if not listed:
            return httpx.Response(404)
        days = [start + timedelta(days=i) for i in range((stop - start).days)]
        stamp = lambda d: datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp()  # noqa: E731
        return httpx.Response(200, json=[[stamp(d), 6e4, 6e4, 6e4, 6e4, 1.0] for d in reversed(days)])

    return httpx.MockTransport(handler)


def test_a_held_coin_is_backfilled_from_coinbase_to_a_year_back(db, tmp_path):
    hold_crypto(db)  # bought 2026-09-01; the run's own candles start 2026-09-14
    asked = []
    with httpx.Client(transport=coinbase(asked)) as client:
        deps = dataclasses.replace(make_deps(db, tmp_path, extra=crypto_sources()), http=client)
        outcome = execute_run(deps, RunKind.PRE_OPEN, NOW, min_universe=SMALL)

    assert asked == [(date(2025, 10, 14), date(2026, 8, 10)), (date(2026, 8, 10), date(2026, 9, 14))]
    assert outcome.summary["history"]["backfilled"] == ["BTC"]
    row = db.execute(
        "select min(day) as first, count(*) as n from daily_closes where symbol = 'BTC' and asset_type = 'crypto'"
    ).fetchone()
    assert (row["first"], row["n"]) == (date(2025, 10, 14), 335 + 30)


def test_a_coin_coinbase_doesnt_list_is_named_and_the_run_publishes(db, tmp_path):
    hold_crypto(db)
    asked = []
    with httpx.Client(transport=coinbase(asked, listed=False)) as client:
        deps = dataclasses.replace(make_deps(db, tmp_path, extra=crypto_sources()), http=client)
        outcome = execute_run(deps, RunKind.PRE_OPEN, NOW, min_universe=SMALL)

    assert outcome.status is RunStatus.SUCCESS
    assert outcome.summary["history"]["backfill_missing"] == ["BTC"]


def test_a_coinbase_failure_during_the_coin_backfill_is_recorded_and_the_run_publishes(db, tmp_path):
    hold_crypto(db)
    refused = httpx.MockTransport(lambda request: httpx.Response(400, text="bad request"))
    with httpx.Client(transport=refused) as client:
        deps = dataclasses.replace(make_deps(db, tmp_path, extra=crypto_sources()), http=client)
        outcome = execute_run(deps, RunKind.PRE_OPEN, NOW, min_universe=SMALL)

    assert outcome.status is RunStatus.SUCCESS
    history = outcome.summary["history"]
    assert history["coin_backfill_error"].startswith("HTTPStatusError: HTTP 400")
    assert history["backfilled"] == []  # nothing came back, so the next run asks again


def coingecko_list(asked):
    """CoinGecko's /coins/markets pages for the coin list, and Coinbase's products, of which BTC
    and ETH are the only top coins; every other request answers 404."""
    products = [
        {"id": f"{base}-USD", "base_currency": base, "quote_currency": "USD", "status": "online", "trading_disabled": False}
        for base in ["BTC", "ETH", *(f"X{i}" for i in range(60))]
    ]

    def handler(request):
        if request.url.host == "api.exchange.coinbase.com" and request.url.path == "/products":
            return httpx.Response(200, json=products)
        if request.url.host != "api.coingecko.com" or "page" not in request.url.params:
            return httpx.Response(404)
        page = request.url.params["page"]
        asked.append(page)
        rows = [{"symbol": f"o{page}{i:03d}", "name": f"Other {page} {i}", "market_cap_rank": i + 10} for i in range(250)]
        if page == "1":
            rows[:2] = [{"symbol": "btc", "name": "Bitcoin", "market_cap_rank": 1}, {"symbol": "eth", "name": "Ethereum", "market_cap_rank": 2}]
        return httpx.Response(200, json=rows)

    return httpx.MockTransport(handler)


def test_the_coin_list_is_stored_once_a_day(db, tmp_path):
    asked = []
    with httpx.Client(transport=coingecko_list(asked)) as client:
        deps = dataclasses.replace(make_deps(db, tmp_path), http=client)
        first = execute_run(deps, RunKind.PRE_OPEN, NOW, min_universe=SMALL)
        second = execute_run(deps, RunKind.PRE_CLOSE, NOW, min_universe=SMALL)

    assert (first.summary["coins"], second.summary["coins"]) == (2, "fresh")
    assert asked == ["1", "2"]  # the second run of the day asks nothing
    rows = db.execute("select symbol, name from symbols where asset_type = 'crypto' order by symbol").fetchall()
    assert [(r["symbol"], r["name"]) for r in rows] == [("BTC", "Bitcoin"), ("ETH", "Ethereum")]


def test_a_coingecko_failure_leaves_the_coin_list_and_the_run_alone(db, tmp_path):
    refused = httpx.MockTransport(lambda request: httpx.Response(400, text="bad request"))
    with httpx.Client(transport=refused) as client:
        deps = dataclasses.replace(make_deps(db, tmp_path), http=client)
        outcome = execute_run(deps, RunKind.PRE_OPEN, NOW, min_universe=SMALL)

    assert outcome.status is RunStatus.SUCCESS
    assert outcome.summary["coins"].startswith("failed: HTTPStatusError: HTTP 400")


FAST = TrainConfig(horizons=(5, 63), rounds=40, params={**PARAMS, "min_data_in_leaf": 50, "num_threads": 2})


@pytest.fixture(scope="module")
def tsx_model_files(tmp_path_factory):
    out = tmp_path_factory.mktemp("tsx-model")
    write_market(out, Market.TSX, stocks=20, days=1100)
    data = load_market(out, Market.TSX)
    return to_files(fit_final(data, walk_forward(data, FAST), FAST))


def activate_tsx(db, files, usable=(63,)):
    repo.save_model(db, "stock_tsx-1", "stock_tsx", NOW, {"usable_horizons": list(usable)}, 3.0, files)
    repo.activate_model(db, "stock_tsx", "stock_tsx-1")


def test_the_active_model_forecasts_the_tsx_shortlist_and_holdings(db, tmp_path, tsx_model_files):
    activate_tsx(db, tsx_model_files)
    hold(db, "RY.TO")
    outcome = execute_run(make_deps(db, tmp_path), RunKind.PRE_OPEN, NOW, min_universe=SMALL)
    assert outcome.status is RunStatus.SUCCESS
    rows = db.execute("select symbol, horizon_days, benchmark, model_version from predictions"
                      " where run_id = %s order by symbol", (outcome.run_id,)).fetchall()
    assert {r["symbol"] for r in rows} == {"RY.TO", "TD.TO"}
    assert {(r["horizon_days"], r["benchmark"], r["model_version"]) for r in rows} == {(63, "XIU.TO", "stock_tsx-1")}
    assert outcome.summary["model"]["TSX"]["predicted"] == 2
    assert outcome.summary["model"]["US"] == {"skipped": "no active model"}
    assert run_row(db, outcome.run_id)["model_version"] == "stock_tsx-1"
    assert "ret_5" in market_features(db, outcome.run_id)["RY.TO"]


def priced_by_volume(volumes):
    """A Yahoo fake whose fresh 70-day histories differ only in each symbol's daily volume."""
    return FakeCollector(
        "yfinance_bars",
        best_effort=True,
        records_for=lambda syms: [
            b for s in syms for b in history(s, 70, volume=volumes.get(s, 200_000.0), start=FRESH_START)
        ],
    )


def test_a_market_without_a_model_ranks_by_dollar_volume(db, tmp_path):
    prices = priced_by_volume({"CCC": 400_000.0, "AAA": 300_000.0, "TD.TO": 300_000.0})
    extra = {"news": FakeCollector("news", core=False)}
    outcome = execute_run(
        make_deps(db, tmp_path, prices=prices, extra=extra), RunKind.PRE_OPEN, NOW, min_universe=SMALL
    )
    assert outcome.status is RunStatus.SUCCESS
    assert outcome.summary["model"] == {"US": {"skipped": "no active model"}, "TSX": {"skipped": "no active model"}}
    # each market's shortlist by dollar volume (US: CCC, AAA, BBB; TSX: TD.TO, RY.TO), interleaved
    assert extra["news"].calls == [["CCC", "TD.TO", "AAA", "RY.TO", "BBB"]]
    assert db.execute("select count(*) as n from predictions").fetchone()["n"] == 0
    assert run_row(db, outcome.run_id)["model_version"] is None


def test_an_active_model_shortlists_by_its_screener_score_not_dollar_volume(
    db, tmp_path, tsx_model_files, monkeypatch
):
    activate_tsx(db, tsx_model_files)
    monkeypatch.setitem(MARKETS, Market.TSX, dataclasses.replace(MARKETS[Market.TSX], shortlist_size=1))
    screened = []

    def scores(active, features):  # the screener prefers RY.TO, which trades less than TD.TO
        screened.append(sorted(features.index))
        return pd.Series({"RY.TO": 2.0, "TD.TO": 1.0}).reindex(features.index)

    monkeypatch.setattr("advisor.run.screen_scores", scores)
    prices = priced_by_volume({"TD.TO": 300_000.0})
    outcome = execute_run(make_deps(db, tmp_path, prices=prices), RunKind.PRE_OPEN, NOW, min_universe=SMALL)
    assert outcome.status is RunStatus.SUCCESS
    assert screened == [["RY.TO", "TD.TO"]]
    assert outcome.summary["markets"]["TSX"]["shortlist"] == 1
    rows = db.execute("select distinct symbol from predictions where run_id = %s", (outcome.run_id,)).fetchall()
    assert [r["symbol"] for r in rows] == ["RY.TO"]  # by dollar volume it would have been TD.TO


def test_a_stock_the_model_may_not_score_gets_no_score_and_no_forecast(db, tmp_path, tsx_model_files):
    activate_tsx(db, tsx_model_files)
    hold(db, "TD.TO")  # a holding too: the gate applies to every stock

    def records_for(symbols):  # TD.TO has no bar on 10-13, the TSX's last session (still fresh)
        return [
            b for s in symbols
            for b in history(s, 69 if s == "TD.TO" else 70, start=FRESH_START)
        ]

    prices = FakeCollector("yfinance_bars", best_effort=True, records_for=records_for)
    outcome = execute_run(make_deps(db, tmp_path, prices=prices), RunKind.PRE_OPEN, NOW, min_universe=SMALL)
    assert outcome.status is RunStatus.SUCCESS
    tsx = outcome.summary["model"]["TSX"]
    assert (tsx["screened"], tsx["predicted"], tsx["not_eligible"]) == (1, 1, 1)
    rows = db.execute("select distinct symbol from predictions where run_id = %s", (outcome.run_id,)).fetchall()
    assert [r["symbol"] for r in rows] == ["RY.TO"]
    features = market_features(db, outcome.run_id)
    assert features["TD.TO"]["model_eligible"] is False
    assert features["TD.TO"]["last_close"] == 10.0  # its price row is still there for Plan 4
    assert features["RY.TO"]["model_eligible"] is True


def test_a_model_that_fails_degrades_the_run_and_prices_still_publish(db, tmp_path, tsx_model_files):
    activate_tsx(db, {**tsx_model_files, "h63_q50": b"not a model"})
    outcome = execute_run(make_deps(db, tmp_path), RunKind.PRE_OPEN, NOW, min_universe=SMALL)
    assert outcome.status is RunStatus.DEGRADED
    assert outcome.summary["model"]["TSX"]["failed"].startswith(("OSError", "LightGBMError", "BadGzipFile", "ValueError"))
    assert run_row(db, outcome.run_id)["published"] is True


def test_a_failed_forecast_keeps_the_version_that_ranked_the_shortlist(
    db, tmp_path, tsx_model_files, monkeypatch
):
    activate_tsx(db, tsx_model_files)

    def broken(active, features, benchmark):
        raise RuntimeError("boom")

    monkeypatch.setattr("advisor.run.predict_rows", broken)
    outcome = execute_run(make_deps(db, tmp_path), RunKind.PRE_OPEN, NOW, min_universe=SMALL)
    assert outcome.status is RunStatus.DEGRADED
    assert outcome.summary["model"]["TSX"] == {
        "version": "stock_tsx-1", "screened": 2, "failed": "RuntimeError: boom",
    }
    assert run_row(db, outcome.run_id)["model_version"] == "stock_tsx-1"  # its screener ranked the run
    assert db.execute("select count(*) as n from predictions").fetchone()["n"] == 0


def test_an_active_model_without_usable_horizons_is_skipped_not_failed(db, tmp_path, tsx_model_files):
    activate_tsx(db, tsx_model_files, usable=())
    outcome = execute_run(make_deps(db, tmp_path), RunKind.PRE_OPEN, NOW, min_universe=SMALL)
    assert outcome.status is RunStatus.SUCCESS
    assert outcome.summary["model"]["TSX"] == {"skipped": "no usable horizons"}
    assert db.execute("select count(*) as n from predictions").fetchone()["n"] == 0
    assert run_row(db, outcome.run_id)["model_version"] is None


def test_failed_split_events_leave_a_note_and_the_us_forecasts_still_run(db, tmp_path, tsx_model_files):
    # The TSX model's features (price and relative strength) are a subset of the US ones, so it
    # stands in for a US model here.
    repo.save_model(db, "stock_us-1", "stock_us", NOW, {"usable_horizons": [63]}, 3.0, tsx_model_files)
    repo.activate_model(db, "stock_us", "stock_us-1")
    asked = []

    def refused(tickers, start, end):
        asked.append(sorted(tickers))
        raise RuntimeError("Yahoo said no")

    deps = dataclasses.replace(make_deps(db, tmp_path), split_download=refused)
    outcome = execute_run(deps, RunKind.PRE_OPEN, NOW, min_universe=SMALL)
    assert outcome.status is RunStatus.SUCCESS
    assert asked == [US]  # the US stocks being forecast
    us = outcome.summary["model"]["US"]
    assert us["split_events"] == "failed: RuntimeError: Yahoo said no"
    assert (us["version"], us["screened"], us["predicted"], us["horizons"]) == ("stock_us-1", 3, 3, [63])
    rows = db.execute("select symbol, benchmark from predictions where run_id = %s", (outcome.run_id,)).fetchall()
    assert {(r["symbol"], r["benchmark"]) for r in rows} == {(s, "SPY") for s in US}
    assert run_row(db, outcome.run_id)["model_version"] == "stock_us-1"


def test_the_chart_history_keeps_only_the_last_100_days_of_the_longer_window(db, tmp_path):
    prices = FakeCollector(  # 200 daily bars ending 2026-10-13, like the 400-day window's
        "yfinance_bars",
        records_for=lambda syms: [b for s in syms for b in history(s, 200, start=date(2026, 3, 28))],
    )
    outcome = execute_run(make_deps(db, tmp_path, prices=prices), RunKind.PRE_OPEN, NOW, min_universe=SMALL)
    assert outcome.status is RunStatus.SUCCESS
    row = db.execute(
        "select min(day) as first, count(*) as n from daily_closes where symbol = 'AAA'"
    ).fetchone()
    assert (row["first"], row["n"]) == (date(2026, 7, 6), 100)  # 100 days before 2026-10-14


def confident(active, features, benchmark):
    return [PredictionRow(s, 63, -0.05, 0.04, 0.10, 0.65, benchmark, active.version) for s in features.index]


def test_qualifying_forecasts_become_picks_and_watched_stocks_get_verdicts(db, tmp_path, tsx_model_files, monkeypatch):
    activate_tsx(db, tsx_model_files)
    db.execute("update models set metrics = metrics || '{\"picks_enabled\": true}'::jsonb")
    db.execute("insert into watchlist (symbol, asset_type) values ('TD.TO', 'stock'), ('ETH', 'crypto')")
    hold(db, "RY.TO")
    monkeypatch.setattr("advisor.run.predict_rows", confident)
    outcome = execute_run(make_deps(db, tmp_path), RunKind.PRE_OPEN, NOW, min_universe=SMALL)
    assert outcome.status is RunStatus.SUCCESS
    picks = db.execute("select symbol, market, style, horizon_days, stop, entry_ref_price, rank from picks"
                       " where run_id = %s", (outcome.run_id,)).fetchall()
    assert [p["symbol"] for p in picks] == ["TD.TO"]  # RY.TO is held: never a pick
    assert picks[0]["style"] == "position" and picks[0]["market"] == "TSX" and picks[0]["rank"] == 1
    assert float(picks[0]["stop"]) >= float(picks[0]["entry_ref_price"]) * 0.85  # numeric columns read as Decimal
    verdicts = {r["symbol"]: r["verdict"] for r in db.execute(
        "select symbol, verdict from watchlist_verdicts where run_id = %s", (outcome.run_id,)).fetchall()}
    assert verdicts == {"TD.TO": "buy", "ETH": "hold"}
    assert outcome.summary["picks"]["TSX"] == {"swing": 0, "position": 1}


def test_a_disabled_market_gets_verdicts_but_no_picks(db, tmp_path, tsx_model_files, monkeypatch):
    activate_tsx(db, tsx_model_files)
    db.execute("update models set metrics = metrics || '{\"picks_enabled\": false, \"picks_reason\": \"only 12 backtest picks (needs 30)\"}'::jsonb")
    db.execute("insert into watchlist (symbol, asset_type) values ('TD.TO', 'stock')")
    monkeypatch.setattr("advisor.run.predict_rows", confident)
    outcome = execute_run(make_deps(db, tmp_path), RunKind.PRE_OPEN, NOW, min_universe=SMALL)
    assert db.execute("select count(*) as n from picks").fetchone()["n"] == 0
    assert outcome.summary["picks"]["TSX"] == {"disabled": "only 12 backtest picks (needs 30)"}
    verdict = db.execute("select verdict, details from watchlist_verdicts where symbol = 'TD.TO'").fetchone()
    assert verdict["verdict"] == "buy" and verdict["details"]["market_picks_enabled"] is False


def test_a_recommender_failure_degrades_the_run_and_prices_still_publish(db, tmp_path, tsx_model_files, monkeypatch):
    activate_tsx(db, tsx_model_files)
    db.execute("update models set metrics = metrics || '{\"picks_enabled\": true}'::jsonb")
    monkeypatch.setattr("advisor.run.predict_rows", confident)

    def broken(*args, **kwargs):
        raise RuntimeError("risk frame broke")

    monkeypatch.setattr("advisor.recommend.stage.risk_levels", broken)
    outcome = execute_run(make_deps(db, tmp_path), RunKind.PRE_OPEN, NOW, min_universe=SMALL)
    assert outcome.status is RunStatus.DEGRADED
    assert outcome.summary["picks"]["TSX"]["failed"].startswith("RuntimeError")
    assert run_row(db, outcome.run_id)["published"] is True


def test_a_crashed_recommend_stage_still_records_the_verdicts_failure(db, tmp_path, tsx_model_files, monkeypatch):
    activate_tsx(db, tsx_model_files)
    db.execute("insert into watchlist (symbol, asset_type) values ('TD.TO', 'stock')")
    monkeypatch.setattr("advisor.run.predict_rows", confident)

    def crash(*args, **kwargs):
        raise RuntimeError("stage broke")

    monkeypatch.setattr("advisor.run.recommend_stage", crash)
    outcome = execute_run(make_deps(db, tmp_path), RunKind.PRE_OPEN, NOW, min_universe=SMALL)
    assert outcome.status is RunStatus.DEGRADED
    assert outcome.summary["verdicts"]["failed"].startswith("RuntimeError")
    assert outcome.summary["picks"]["TSX"]["failed"].startswith("RuntimeError")
    assert run_row(db, outcome.run_id)["published"] is True


def test_one_markets_recommender_failure_spares_the_other_market_and_the_verdicts(
    db, tmp_path, tsx_model_files, monkeypatch
):
    activate_tsx(db, tsx_model_files)
    # the TSX model's features are a subset of the US ones, so it stands in for a US model here
    repo.save_model(db, "stock_us-1", "stock_us", NOW, {"usable_horizons": [63]}, 3.0, tsx_model_files)
    repo.activate_model(db, "stock_us", "stock_us-1")
    db.execute("update models set metrics = metrics || '{\"picks_enabled\": true}'::jsonb")
    db.execute("insert into watchlist (symbol, asset_type) values ('TD.TO', 'stock'), ('AAA', 'stock')")
    monkeypatch.setattr("advisor.run.predict_rows", confident)

    def broken_for_us(frame):
        if "AAA" in frame.index:
            raise RuntimeError("US risk frame broke")
        return risk_levels(frame)

    monkeypatch.setattr("advisor.recommend.stage.risk_levels", broken_for_us)
    outcome = execute_run(make_deps(db, tmp_path), RunKind.PRE_OPEN, NOW, min_universe=SMALL)
    assert outcome.status is RunStatus.DEGRADED
    assert outcome.summary["picks"] == {
        "US": {"failed": "RuntimeError: US risk frame broke"}, "TSX": {"swing": 0, "position": 2},
    }
    rows = db.execute("select market, count(*) as n from picks group by market").fetchall()
    assert [(r["market"], r["n"]) for r in rows] == [("TSX", 2)]
    verdicts = verdict_rows(db, outcome.run_id)
    assert verdicts["TD.TO"]["verdict"] == "buy"
    # a Buy must carry a pick's fields: without them the US stock waits
    assert (verdicts["AAA"]["verdict"], verdicts["AAA"]["reasons"]) == ("hold", ["the recommender failed this run"])
    assert run_row(db, outcome.run_id)["published"] is True


def split_odds(active, features, benchmark):
    """TD.TO qualifies; RY.TO is unlikely to beat the benchmark at any horizon."""
    return [
        PredictionRow(s, 63, -0.05, 0.04, 0.10, 0.65 if s == "TD.TO" else 0.30, benchmark, active.version)
        for s in features.index
    ]


def verdict_rows(db, run_id):
    rows = db.execute(
        "select symbol, verdict, reasons, details from watchlist_verdicts where run_id = %s", (run_id,)
    ).fetchall()
    return {r["symbol"]: r for r in rows}


def test_every_verdict_of_a_disabled_market_says_its_picks_are_off(db, tmp_path, tsx_model_files, monkeypatch):
    activate_tsx(db, tsx_model_files)
    db.execute("update models set metrics = metrics || '{\"picks_enabled\": false, \"picks_reason\": \"no\"}'::jsonb")
    db.execute("insert into watchlist (symbol, asset_type) values ('TD.TO', 'stock'), ('RY.TO', 'stock'),"
               " ('AAA', 'stock')")
    monkeypatch.setattr("advisor.run.predict_rows", split_odds)
    outcome = execute_run(make_deps(db, tmp_path), RunKind.PRE_OPEN, NOW, min_universe=SMALL)
    assert outcome.status is RunStatus.SUCCESS
    verdicts = verdict_rows(db, outcome.run_id)
    assert {s: v["verdict"] for s, v in verdicts.items()} == {"TD.TO": "buy", "RY.TO": "avoid", "AAA": "hold"}
    assert all(v["details"]["market_picks_enabled"] is False for v in verdicts.values())
    assert verdicts["AAA"]["reasons"] == ["no active model"]  # the US has no model in this test
    # a buy carries the same fields as a pick, even when its market's picks are off
    buy = verdicts["TD.TO"]["details"]
    assert (buy["style"], buy["horizon_days"], buy["entry_ref_price"]) == ("position", 63, 10.0)
    assert buy["risk_level"] in {"low", "medium", "high", "very_high"} and len(buy["top_factors"]) == 3
    assert outcome.summary["picks"] == {"US": {"skipped": "no active model"}, "TSX": {"disabled": "no"}}


def test_an_enabled_markets_verdicts_say_so_and_a_watched_pick_carries_its_rank(
    db, tmp_path, tsx_model_files, monkeypatch
):
    activate_tsx(db, tsx_model_files)
    db.execute("update models set metrics = metrics || '{\"picks_enabled\": true}'::jsonb")
    db.execute("insert into watchlist (symbol, asset_type) values ('TD.TO', 'stock'), ('RY.TO', 'stock')")
    monkeypatch.setattr("advisor.run.predict_rows", split_odds)
    outcome = execute_run(make_deps(db, tmp_path), RunKind.PRE_OPEN, NOW, min_universe=SMALL)
    verdicts = verdict_rows(db, outcome.run_id)
    assert all(v["details"]["market_picks_enabled"] is True for v in verdicts.values())
    assert verdicts["TD.TO"]["details"]["rank"] == 1
    assert verdicts["RY.TO"]["reasons"] == ["P(beat XIU.TO) at most 0.30 at every horizon"]


def test_a_watched_stock_the_model_may_not_score_is_hold_with_the_reason(db, tmp_path, tsx_model_files, monkeypatch):
    activate_tsx(db, tsx_model_files)
    db.execute("update models set metrics = metrics || '{\"picks_enabled\": true}'::jsonb")
    db.execute("insert into watchlist (symbol, asset_type) values ('TD.TO', 'stock')")
    monkeypatch.setattr("advisor.run.predict_rows", confident)

    def records_for(symbols):  # TD.TO has no bar on 10-13, the TSX's last session
        return [b for s in symbols for b in history(s, 69 if s == "TD.TO" else 70, start=FRESH_START)]

    prices = FakeCollector("yfinance_bars", best_effort=True, records_for=records_for)
    outcome = execute_run(make_deps(db, tmp_path, prices=prices), RunKind.PRE_OPEN, NOW, min_universe=SMALL)
    verdict = verdict_rows(db, outcome.run_id)["TD.TO"]
    assert (verdict["verdict"], verdict["reasons"]) == (
        "hold", ["not eligible for the model (under $1, thin trading or new)"],
    )
    assert db.execute("select count(*) as n from picks").fetchone()["n"] == 1  # RY.TO still is one


def test_a_jump_in_the_last_five_sessions_is_never_a_pick(db, tmp_path, tsx_model_files, monkeypatch):
    activate_tsx(db, tsx_model_files)
    db.execute("update models set metrics = metrics || '{\"picks_enabled\": true}'::jsonb")
    db.execute("insert into watchlist (symbol, asset_type) values ('TD.TO', 'stock')")
    monkeypatch.setattr("advisor.run.predict_rows", confident)

    def records_for(symbols):  # TD.TO jumped 60% the session before last and stayed there
        jumped = {"open": 16.0, "high": 16.0, "low": 16.0, "close": 16.0}
        return [
            b.model_copy(update=jumped) if s == "TD.TO" and b.day >= date(2026, 10, 12) else b
            for s in symbols for b in history(s, 70, start=FRESH_START)
        ]

    prices = FakeCollector("yfinance_bars", best_effort=True, records_for=records_for)
    outcome = execute_run(make_deps(db, tmp_path, prices=prices), RunKind.PRE_OPEN, NOW, min_universe=SMALL)
    assert [r["symbol"] for r in db.execute("select symbol from picks").fetchall()] == ["RY.TO"]
    verdict = verdict_rows(db, outcome.run_id)["TD.TO"]
    assert (verdict["verdict"], verdict["reasons"]) == (
        "hold", ["doesn't qualify as a buy", "the model's sanity checks failed on this run"],
    )


def test_a_non_finite_forecast_never_reaches_the_rules(db, tmp_path, tsx_model_files, monkeypatch):
    activate_tsx(db, tsx_model_files)
    db.execute("update models set metrics = metrics || '{\"picks_enabled\": true}'::jsonb")
    db.execute("insert into watchlist (symbol, asset_type) values ('TD.TO', 'stock')")

    def unbounded(active, features, benchmark):  # TD.TO's range has no top: its ratio would be 0, not NaN
        return [
            PredictionRow(s, 63, -0.05, 0.04, math.inf if s == "TD.TO" else 0.10, 0.65, benchmark, active.version)
            for s in features.index
        ]

    monkeypatch.setattr("advisor.run.predict_rows", unbounded)
    outcome = execute_run(make_deps(db, tmp_path), RunKind.PRE_OPEN, NOW, min_universe=SMALL)
    assert outcome.status is RunStatus.SUCCESS
    assert [r["symbol"] for r in db.execute("select symbol from picks").fetchall()] == ["RY.TO"]
    verdict = verdict_rows(db, outcome.run_id)["TD.TO"]
    assert (verdict["verdict"], verdict["reasons"]) == ("hold", ["no forecast this run"])


def test_earnings_trial_readouts_and_recent_8ks_are_catalysts(db, tmp_path, tsx_model_files, monkeypatch):
    activate_tsx(db, tsx_model_files)
    db.execute("update models set metrics = metrics || '{\"picks_enabled\": true}'::jsonb")
    monkeypatch.setattr("advisor.run.predict_rows", confident)
    earnings = [
        EarningsReport(symbol="TD.TO", report_at=datetime(2026, 12, 4, 7, 0, tzinfo=ET)),
        EarningsReport(symbol="TD.TO", report_at=datetime(2026, 8, 28, 7, 0, tzinfo=ET)),  # already out
    ]
    trials = [
        TrialActivity(symbol="TD.TO", as_of=date(2026, 10, 14), next_completion=date(2026, 11, 30),
                      next_completion_exact=False),
        TrialActivity(symbol="RY.TO", as_of=date(2026, 10, 14), next_completion=date(2027, 9, 1)),
    ]
    filings = [
        MaterialEvent(symbol="TD.TO", accession="a-1", form="8-K", filing_date=date(2026, 10, 13),
                      items=["2.02", "9.01"]),
        MaterialEvent(symbol="TD.TO", accession="a-0", form="8-K", filing_date=date(2026, 10, 1)),
    ]
    extra = {  # the code reads any market's filings; the real 8-K source covers the US only
        name: FakeCollector(name, core=False, record_type=type(records[0]), records_for=lambda _, r=records: r)
        for name, records in (("yfinance_earnings", earnings), ("clinical_trials", trials), ("sec_8k", filings))
    }
    outcome = execute_run(make_deps(db, tmp_path, extra=extra), RunKind.PRE_OPEN, NOW, min_universe=SMALL)
    assert outcome.status is RunStatus.SUCCESS
    rows = {r["symbol"]: r for r in db.execute(
        "select symbol, catalysts, top_factors, exit_by from picks where run_id = %s", (outcome.run_id,))}
    assert rows["TD.TO"]["catalysts"] == [  # by date
        {"type": "8-K", "date": "2026-10-13", "items": ["2.02", "9.01"]},
        {"type": "trial_completion", "date": "2026-11-30", "exact": False},
        {"type": "earnings", "date": "2026-12-04"},
    ]
    assert rows["RY.TO"]["catalysts"] == []  # its readout falls after the exit-by date
    assert rows["RY.TO"]["exit_by"] == date(2027, 1, 13)  # 63 TSX sessions after 2026-10-13
    assert len(rows["TD.TO"]["top_factors"]) == 3


@pytest.mark.parametrize(
    ("kind", "now", "tonight_counts"),
    [
        # before the open the entry is 10-13's close, so a report that evening is already out
        (RunKind.PRE_OPEN, NOW, False),
        # at 15:15 on 10-13 the entry is that afternoon's price, so the report lands in the hold
        (RunKind.PRE_CLOSE, datetime(2026, 10, 13, 19, 15, tzinfo=UTC), True),
    ],
)
def test_an_earnings_report_on_the_feature_day_counts_only_at_a_pre_close_run(
    db, tmp_path, tsx_model_files, monkeypatch, kind, now, tonight_counts
):
    activate_tsx(db, tsx_model_files)
    db.execute("update models set metrics = metrics || '{\"picks_enabled\": true}'::jsonb")
    monkeypatch.setattr("advisor.run.predict_rows", confident)
    tonight = [EarningsReport(symbol="TD.TO", report_at=datetime(2026, 10, 13, 17, 0, tzinfo=ET))]
    extra = {"yfinance_earnings": FakeCollector(
        "yfinance_earnings", core=False, record_type=EarningsReport, records_for=lambda _: tonight,
    )}
    outcome = execute_run(make_deps(db, tmp_path, extra=extra), kind, now, min_universe=SMALL)
    assert outcome.status is RunStatus.SUCCESS
    row = db.execute("select catalysts from picks where symbol = 'TD.TO' and run_id = %s",
                     (outcome.run_id,)).fetchone()
    assert row["catalysts"] == ([{"type": "earnings", "date": "2026-10-13"}] if tonight_counts else [])


def test_a_watched_stock_that_is_held_keeps_its_buy_and_says_it_is_held(db, tmp_path, tsx_model_files, monkeypatch):
    activate_tsx(db, tsx_model_files)
    db.execute("update models set metrics = metrics || '{\"picks_enabled\": true}'::jsonb")
    db.execute("insert into watchlist (symbol, asset_type) values ('TD.TO', 'stock'), ('RY.TO', 'stock')")
    hold(db, "TD.TO")
    monkeypatch.setattr("advisor.run.predict_rows", confident)
    outcome = execute_run(make_deps(db, tmp_path), RunKind.PRE_OPEN, NOW, min_universe=SMALL)
    assert [r["symbol"] for r in db.execute("select symbol from picks").fetchall()] == ["RY.TO"]
    verdicts = verdict_rows(db, outcome.run_id)
    held = verdicts["TD.TO"]
    assert held["verdict"] == "buy" and held["details"]["held"] is True
    assert "rank" not in held["details"] and held["details"]["style"] == "position"  # a pick's fields, no rank
    assert "held" not in verdicts["RY.TO"]["details"] and verdicts["RY.TO"]["details"]["rank"] == 1


def test_a_verdict_failure_degrades_the_run_and_keeps_the_picks(db, tmp_path, tsx_model_files, monkeypatch):
    activate_tsx(db, tsx_model_files)
    db.execute("update models set metrics = metrics || '{\"picks_enabled\": true}'::jsonb")
    db.execute("insert into watchlist (symbol, asset_type) values ('TD.TO', 'stock')")
    monkeypatch.setattr("advisor.run.predict_rows", confident)

    def broken(*args, **kwargs):
        raise RuntimeError("verdicts broke")

    monkeypatch.setattr("advisor.recommend.stage.stock_verdict", broken)
    outcome = execute_run(make_deps(db, tmp_path), RunKind.PRE_OPEN, NOW, min_universe=SMALL)
    assert outcome.status is RunStatus.DEGRADED
    assert outcome.summary["verdicts"] == {"failed": "RuntimeError: verdicts broke"}
    assert outcome.summary["picks"]["TSX"] == {"swing": 0, "position": 2}
    assert db.execute("select count(*) as n from watchlist_verdicts").fetchone()["n"] == 0
    assert run_row(db, outcome.run_id)["published"] is True


def holding_actions(db, run_id):
    rows = db.execute("select * from holding_actions where run_id = %s", (run_id,)).fetchall()
    return {r["symbol"]: r for r in rows}


def test_holdings_get_actions_and_a_coin_gets_the_fallback(db, tmp_path, tsx_model_files, monkeypatch):
    activate_tsx(db, tsx_model_files)
    hold(db, "RY.TO")
    hold_crypto(db)
    monkeypatch.setattr("advisor.run.predict_rows", confident)
    extra = crypto_sources()

    def candles(symbols):  # a daily range, so the coin's ATR, and its stop's distance, isn't zero
        return [
            b.model_copy(update={"high": b.close * 1.02, "low": b.close * 0.98})
            for s in symbols for b in history(s, 30, 82000.0, source="coinbase", start=date(2026, 9, 14))
        ]

    extra["coinbase_candles"].records_for = candles
    outcome = execute_run(make_deps(db, tmp_path, extra=extra), RunKind.PRE_OPEN, NOW, min_universe=SMALL)
    assert outcome.status is RunStatus.SUCCESS
    rows = holding_actions(db, outcome.run_id)
    assert set(rows) == {"RY.TO", "BTC"}
    stock = rows["RY.TO"]
    assert (stock["account"], stock["asset_type"], stock["horizon_days"]) == ("tfsa", "stock", 63)
    assert (stock["feature_day"], stock["exit_by"]) == (date(2026, 10, 13), date(2027, 1, 13))
    assert (float(stock["ref_price"]), float(stock["bench_ref_price"])) == (10.0, 10.0)  # its close and XIU.TO's
    assert stock["risk_level"] in {"low", "medium", "high", "very_high"} and stock["trailing_stop"] is not None
    coin = rows["BTC"]
    assert (coin["account"], coin["action"], coin["reasons"]) == ("crypto", "hold", ["no crypto model yet"])
    assert (coin["horizon_days"], coin["exit_by"], coin["bench_ref_price"]) == (None, None, None)
    assert (float(coin["ref_price"]), coin["feature_day"]) == (82000.0, date(2026, 10, 13))
    assert float(coin["trailing_stop"]) < 82000.0
    assert (coin["risk_level"], coin["max_position_pct"]) == ("very_high", 0.5)
    assert outcome.summary["actions"]["written"] == 2


def test_an_actions_failure_degrades_the_run_and_prices_still_publish(db, tmp_path, monkeypatch):
    hold(db, "RY.TO")

    def broken(holding):
        raise RuntimeError("actions broke")

    monkeypatch.setattr("advisor.portfolio.stage.decide", broken)
    outcome = execute_run(make_deps(db, tmp_path), RunKind.PRE_OPEN, NOW, min_universe=SMALL)
    assert outcome.status is RunStatus.DEGRADED
    assert outcome.summary["actions"] == {"failed": "RuntimeError: actions broke"}
    assert holding_actions(db, outcome.run_id) == {}
    assert run_row(db, outcome.run_id)["published"] is True
    assert "RY.TO" in market_features(db, outcome.run_id)


def test_a_ledger_problem_is_reported_with_the_actions(db, tmp_path):
    hold(db, "RY.TO")
    db.execute(
        "insert into sells (account, symbol, asset_type, qty, price, currency, sold_at)"
        " values ('tfsa', 'TD.TO', 'stock', 5, 12, 'CAD', '2026-10-01')"
    )
    outcome = execute_run(make_deps(db, tmp_path), RunKind.PRE_OPEN, NOW, min_universe=SMALL)
    assert outcome.status is RunStatus.SUCCESS
    assert outcome.summary["actions"]["written"] == 1
    assert outcome.summary["actions"]["problems"] == [
        "TD.TO on 2026-10-01: a sell with nothing held, so it's left out."
    ]
