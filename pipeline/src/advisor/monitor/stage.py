"""The holding monitor stage: store the run's 8-Ks, quarters, earnings dates and insider trades,
then mark the price alerts the latest stored closes crossed. Display only; nothing here feeds the
model, picks, verdicts or holding actions.
"""

from collections import defaultdict
from collections.abc import Mapping
from datetime import datetime

import psycopg

from advisor.collectors.base import CollectorResult
from advisor.collectors.sec_events import MaterialEvent
from advisor.collectors.sec_insiders import InsiderTrade
from advisor.collectors.sec_xbrl import FinancialFact
from advisor.collectors.yfinance_earnings import EarningsReport
from advisor.models import AssetRef, AssetType
from advisor.monitor.quarters import QuarterRow, single_quarters
from advisor.monitor.rows import alert_hits, earnings_rows, filing_rows, insider_rows
from advisor.store import repo


def _records(results: Mapping[str, CollectorResult], name: str, kind: type) -> list:
    """A source's records of one type; none when the source didn't run this time."""
    result = results.get(name)
    return [r for r in (result.records if result is not None else []) if isinstance(r, kind)]


def _quarters(facts: list[FinancialFact]) -> list[QuarterRow]:
    by_symbol: dict[str, list[FinancialFact]] = defaultdict(list)
    for fact in facts:
        by_symbol[fact.symbol].append(fact)
    return [row for symbol in sorted(by_symbol) for row in single_quarters(by_symbol[symbol])]


def monitor_stage(
    conn: psycopg.Connection, results: Mapping[str, CollectorResult], now_utc: datetime
) -> dict:
    """Write the four monitor tables, prune them and check the alerts, all in one transaction.

    Alerts are checked against each asset's newest close in `daily_closes`, so this runs after the
    run's own closes are stored. Returns the row counts for `summary["holding_monitor"]`.
    """
    filings = filing_rows(_records(results, "sec_8k", MaterialEvent))
    quarters = _quarters(_records(results, "sec_xbrl", FinancialFact))
    earnings = earnings_rows(_records(results, "yfinance_earnings", EarningsReport))
    insiders = insider_rows(_records(results, "sec_form4", InsiderTrade))
    with conn.transaction():  # all of it or none: a failure leaves the tables as they were
        repo.write_filings(conn, filings)
        repo.write_financial_quarters(conn, quarters)
        repo.write_earnings_reports(conn, earnings)
        repo.write_insider_trades(conn, insiders)
        repo.prune_holding_monitor(conn, now_utc)
        alerts = repo.active_price_alerts(conn)
        refs = {AssetRef(a.symbol, AssetType(a.asset_type)) for a in alerts}
        hits = alert_hits(alerts, repo.latest_closes(conn, refs))
        repo.mark_alerts_hit(conn, hits, now_utc)
    return {
        "filings": len(filings),
        "quarters": len(quarters),
        "earnings": len(earnings),
        "insider_trades": len(insiders),
        "alerts_hit": len(hits),
    }
