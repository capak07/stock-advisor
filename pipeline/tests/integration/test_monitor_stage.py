from datetime import UTC, date, datetime, timedelta

import psycopg
import pytest

from advisor.collectors.base import CollectorResult, CollectorStatus
from advisor.collectors.sec_events import MaterialEvent
from advisor.collectors.sec_insiders import InsiderTrade
from advisor.collectors.sec_xbrl import FinancialFact
from advisor.collectors.yfinance_earnings import EarningsReport
from advisor.models import AssetRef, AssetType, DailyClose
from advisor.monitor.rows import filing_rows
from advisor.monitor.stage import monitor_stage
from advisor.store import repo

NOW = datetime(2026, 10, 14, 12, 15, tzinfo=UTC)
DAY = date(2026, 10, 13)
ZEROS = {"filings": 0, "quarters": 0, "earnings": 0, "insider_trades": 0, "alerts_hit": 0}


def result(name, records):
    return CollectorResult(name, CollectorStatus.OK, list(records), 5)


def event(symbol="AAPL", accession="0000320193-26-000001"):
    return MaterialEvent(
        symbol=symbol, accession=accession, form="8-K", filing_date=date(2026, 10, 1), cik=320193,
        primary_document="a8k.htm", items=["2.02"], report_date=date(2026, 9, 30),
    )


def fact(symbol, start, end, value, metric="revenue", concept="us-gaap:Revenues"):
    return FinancialFact(
        symbol=symbol, metric=metric, concept=concept, unit="USD", start=start, end=end, value=value,
        filed=end + timedelta(days=30), form="10-Q", accession=f"{symbol}-{end}",
    )


def trade(code="P", derivative=False):
    return InsiderTrade(
        symbol="AAPL", accession="i1", form="4", filing_date=date(2026, 10, 2), trade_date=date(2026, 9, 30),
        owners=["COOK TIM"], director=False, officer=True, ten_percent_owner=False, officer_title="CEO",
        code=code, acquired=code == "P", shares=100.0, price=10.0, direct=True, derivative=derivative,
        planned=False,
    )


def earnings(symbol="AAPL"):
    return EarningsReport(
        symbol=symbol, report_at=datetime(2026, 10, 30, 20, 30, tzinfo=UTC), eps_estimate=1.5,
    )


def all_results():
    return {
        "sec_8k": result("sec_8k", [event(), event("MSFT", "0000789019-26-000002")]),
        "sec_xbrl": result("sec_xbrl", [
            fact("AAPL", date(2026, 3, 29), date(2026, 6, 27), 90.0),
            fact("AAPL", date(2025, 12, 28), date(2026, 3, 28), 95.0),
            fact("MSFT", date(2026, 4, 1), date(2026, 6, 30), 70.0),
        ]),
        "yfinance_earnings": result("yfinance_earnings", [earnings(), earnings("MSFT")]),
        "sec_form4": result("sec_form4", [trade("P"), trade("S"), trade("A"), trade("P", derivative=True)]),
    }


def seed_alert(db, symbol, direction, level, asset_type="stock"):
    return db.execute(
        "insert into price_alerts (symbol, asset_type, direction, level) values (%s, %s, %s, %s) returning id",
        (symbol, asset_type, direction, level),
    ).fetchone()["id"]


def count(db, table):
    return db.execute(f"select count(*) as n from {table}").fetchone()["n"]


def test_the_stage_writes_all_four_tables_and_marks_a_crossed_alert(db):
    aapl, btc = AssetRef("AAPL", AssetType.STOCK), AssetRef("BTC", AssetType.CRYPTO)
    repo.write_daily_closes(db, [
        DailyClose(aapl, DAY - timedelta(days=1), 150.0, "USD"), DailyClose(aapl, DAY, 210.0, "USD"),
        DailyClose(btc, DAY, 80000.0, "USD"),
    ])
    crossed = seed_alert(db, "AAPL", "above", 200)
    not_yet = seed_alert(db, "AAPL", "below", 100)
    coin = seed_alert(db, "BTC", "below", 85000, "crypto")
    no_price = seed_alert(db, "ZZZ", "above", 1)

    got = monitor_stage(db, all_results(), NOW)

    assert got == {"filings": 2, "quarters": 3, "earnings": 2, "insider_trades": 2, "alerts_hit": 2}
    assert count(db, "filings") == 2
    quarters = db.execute("select symbol, period_end from financial_quarters order by symbol, period_end").fetchall()
    assert [(r["symbol"], r["period_end"]) for r in quarters] == [
        ("AAPL", date(2026, 3, 28)), ("AAPL", date(2026, 6, 27)), ("MSFT", date(2026, 6, 30)),
    ]
    assert count(db, "earnings_reports") == 2
    codes = db.execute("select code from insider_trades order by line").fetchall()
    assert [r["code"] for r in codes] == ["P", "S"]  # the grant and the derivative are left out
    hits = {
        r["id"]: (r["hit_at"], None if r["hit_price"] is None else float(r["hit_price"]))
        for r in db.execute("select id, hit_at, hit_price from price_alerts").fetchall()
    }
    assert hits == {
        crossed: (NOW, 210.0), coin: (NOW, 80000.0), not_yet: (None, None), no_price: (None, None),
    }


def test_the_stage_runs_as_the_pipeline_role(db):
    db.execute("set role pipeline_rw")
    try:
        got = monitor_stage(db, all_results(), NOW)
    finally:
        db.execute("reset role")
    assert got["filings"] == 2 and got["insider_trades"] == 2


def test_no_results_writes_nothing_and_returns_zeros(db):
    assert monitor_stage(db, {}, NOW) == ZEROS
    assert [count(db, t) for t in ("filings", "financial_quarters", "earnings_reports", "insider_trades")] == [
        0, 0, 0, 0,
    ]


def test_old_rows_are_pruned(db):
    old = MaterialEvent(
        symbol="AAPL", accession="old", form="8-K", filing_date=date(2025, 1, 2), cik=320193,
        primary_document="old.htm", items=["8.01"],
    )
    repo.write_filings(db, filing_rows([old]))
    monitor_stage(db, {}, NOW)  # a run whose sources returned nothing still prunes
    assert count(db, "filings") == 0


def test_a_failure_inside_the_transaction_rolls_everything_back(db, monkeypatch):
    seed_alert(db, "AAPL", "above", 200)
    repo.write_daily_closes(db, [DailyClose(AssetRef("AAPL", AssetType.STOCK), DAY, 210.0, "USD")])

    def broken(conn, hits, now):
        conn.execute("select 1 / 0")  # a real SQL error, mid-transaction

    monkeypatch.setattr(repo, "mark_alerts_hit", broken)
    with pytest.raises(psycopg.errors.DivisionByZero):
        monitor_stage(db, all_results(), NOW)
    # nothing was kept, and the connection still works
    assert [count(db, t) for t in ("filings", "financial_quarters", "earnings_reports", "insider_trades")] == [
        0, 0, 0, 0,
    ]
    assert db.execute("select 1 as one").fetchone()["one"] == 1
