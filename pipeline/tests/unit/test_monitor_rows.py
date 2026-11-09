from datetime import UTC, date, datetime

from advisor.collectors.sec_events import MaterialEvent
from advisor.collectors.sec_insiders import InsiderTrade
from advisor.collectors.yfinance_earnings import EarningsReport
from advisor.models import ET
from advisor.monitor.rows import PriceAlert, alert_hits, earnings_rows, filing_rows, insider_rows


def _event(**kw) -> MaterialEvent:
    base = dict(
        symbol="AAPL",
        accession="0000320193-26-000001",
        form="8-K",
        filing_date=date(2026, 5, 1),
        cik=320193,
        primary_document="a8k.htm",
        items=["2.02"],
        report_date=date(2026, 4, 30),
    )
    return MaterialEvent(**{**base, **kw})


def _trade(**kw) -> InsiderTrade:
    base = dict(
        symbol="AAPL",
        accession="acc1",
        form="4",
        filing_date=date(2026, 5, 1),
        trade_date=date(2026, 4, 29),
        owners=["COOK TIM"],
        director=False,
        officer=True,
        ten_percent_owner=False,
        officer_title="CEO",
        code="S",
        acquired=False,
        shares=100.0,
        price=10.0,
        direct=True,
        derivative=False,
        planned=False,
    )
    return InsiderTrade(**{**base, **kw})


def test_filing_row_uses_accepted_at_and_url():
    acc = datetime(2026, 5, 1, 20, 5, tzinfo=UTC)
    [row] = filing_rows([_event(accepted_at=acc)])
    assert row.filed_at == acc
    assert row.url == "https://www.sec.gov/Archives/edgar/data/320193/000032019326000001/a8k.htm"
    assert row.items == ["2.02"]
    assert row.report_date == date(2026, 4, 30)


def test_filing_row_falls_back_to_midnight_et():
    [row] = filing_rows([_event()])
    assert row.filed_at == datetime(2026, 5, 1, tzinfo=ET)


def test_filing_without_primary_document_skipped_and_dedup():
    rows = filing_rows([_event(primary_document=None), _event(accession="b"), _event(accession="b")])
    assert [r.accession for r in rows] == ["b"]


def test_insider_filters_grants_and_derivatives():
    rows = insider_rows([_trade(code="A"), _trade(derivative=True), _trade(code="P")])
    assert [r.code for r in rows] == ["P"]
    assert rows[0].line == 0


def test_insider_line_per_accession_and_value():
    rows = insider_rows(
        [_trade(), _trade(code="A"), _trade(price=None), _trade(accession="acc2")]
    )
    assert [(r.accession, r.line) for r in rows] == [("acc1", 0), ("acc1", 1), ("acc2", 0)]
    assert rows[0].value == 1000.0
    assert rows[1].value is None


def test_insider_owner_role_planned_filed_at():
    [r] = insider_rows([_trade(owners=["A B", "C D"], planned=True)])
    assert r.owner == "A B & C D"
    assert r.planned is True
    assert r.role == "CEO"
    assert r.filed_at == datetime(2026, 5, 1, tzinfo=ET)


def test_role_preference():
    def role(**kw):
        return insider_rows([_trade(**kw)])[0].role

    assert role(officer_title="", director=True) == "Director"
    assert role(officer_title=None, director=False, ten_percent_owner=True) == "10% owner"
    assert role(officer_title=None, director=False) == "Officer"
    assert role(officer_title=None, director=False, officer=False) == "Insider"


def test_earnings_rows_et_date_last_wins():
    first = EarningsReport(symbol="AAPL", report_at=datetime(2026, 5, 1, 16, 30, tzinfo=ET))
    last = EarningsReport(
        symbol="AAPL", report_at=datetime(2026, 5, 1, 17, 0, tzinfo=ET), eps_actual=1.5
    )
    [row] = earnings_rows([first, last])
    assert row.report_date == date(2026, 5, 1)
    assert row.eps_actual == 1.5


def test_alert_hits():
    alerts = [
        PriceAlert(1, "AAPL", "stock", "above", 100.0),
        PriceAlert(2, "AAPL", "stock", "below", 90.0),
        PriceAlert(3, "BTC", "crypto", "above", 5.0),
        PriceAlert(4, "AAPL", "stock", "above", 101.0),
        PriceAlert(5, "AAPL", "crypto", "above", 1.0),
    ]
    prices = {("AAPL", "stock"): 100.0, ("BTC", "crypto"): 4.0}
    assert alert_hits(alerts, prices) == [(1, 100.0)]
    assert alert_hits(alerts, {("AAPL", "stock"): 90.0}) == [(2, 90.0)]
