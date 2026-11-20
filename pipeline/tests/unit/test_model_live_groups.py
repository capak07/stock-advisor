from datetime import UTC, date, datetime

import numpy as np
import pandas as pd
import pytest

from advisor.collectors.base import CollectorResult, CollectorStatus
from advisor.collectors.finra_short_interest import ShortInterest
from advisor.collectors.finra_short_volume import ShortVolume
from advisor.collectors.openfda import DrugEvents
from advisor.collectors.sec_13f import HeldQuarter, InstitutionalOwnership
from advisor.collectors.sec_events import MaterialEvent
from advisor.collectors.sec_holders import LargeHolding
from advisor.collectors.sec_insiders import InsiderTrade
from advisor.collectors.yfinance_analyst import AnalystView, RatingEvent, analyst_view
from advisor.collectors.yfinance_earnings import EarningsReport, parse_earnings
from advisor.model import analyst
from advisor.model.analyst import analyst_features
from advisor.model.catalysts import catalysts_features
from advisor.model.events import events_features
from advisor.model.holders import holders_features
from advisor.model.insider import insider_features
from advisor.model.live_groups import history_from_records
from advisor.model.short import VOLUME_SESSIONS, short_features
from advisor.training import fda_history, finra_history, holders_history, sec_history, yahoo_history

AS_OF = datetime(2026, 10, 12, 12, 15, tzinfo=UTC)  # a Monday, before the open


def _ok(name: str, records: list) -> dict[str, CollectorResult]:
    return {name: CollectorResult(name, CollectorStatus.OK, records, 0)}


def _trade(symbol: str, *, code: str = "P", derivative: bool = False, filed: date = date(2026, 10, 1),
           shares: float = 100.0) -> InsiderTrade:
    return InsiderTrade(
        symbol=symbol, accession=f"{symbol}-{code}-{derivative}-{filed}", form="4", filing_date=filed,
        accepted_at=datetime(filed.year, filed.month, filed.day, 21, tzinfo=UTC), trade_date=filed,
        owners=["DOE JANE"], director=False, officer=True, ten_percent_owner=False, code=code,
        acquired=code == "P", shares=shares, price=10.0, direct=True, derivative=derivative, planned=False,
    )


def _holding(symbol: str, form: str, filed: date, *, other_issuer: bool = False) -> LargeHolding:
    return LargeHolding(
        symbol=symbol, accession=f"{symbol}-{form}-{filed}", form=form, filing_date=filed,
        accepted_at=datetime(filed.year, filed.month, filed.day, 20, tzinfo=UTC), activist="13D" in form,
        amendment=form.endswith("/A"), other_issuer=other_issuer,
    )


RECORDS = {
    "finra_short_interest": [ShortInterest(symbol="AAPL", settlement_date=date(2026, 9, 15), short_interest=10,
                                           avg_daily_volume=5, days_to_cover=2.0)],
    "finra_short_volume": [ShortVolume(symbol="AAPL", trade_date=date(2026, 10, 9), short_volume=4.0,
                                       short_exempt_volume=0.0, total_volume=10.0)],
    "sec_8k": [MaterialEvent(symbol="AAPL", accession="a", form="8-K", filing_date=date(2026, 10, 1),
                             items=["5.02"])],
    "sec_13dg": [_holding("AAPL", "SCHEDULE 13G", date(2026, 10, 1))],
    "sec_form4": [_trade("AAPL")],
    "sec_13f": [InstitutionalOwnership(
        symbol="AAPL", cusip="037833100", period=date(2026, 6, 30), shares=5, value_usd=5, holders=1,
        previous_period=date(2026, 3, 31), quarters=[HeldQuarter(period=date(2026, 6, 30),
                                                                 window_end=date(2026, 8, 31), shares=5, holders=1)])],
    "yfinance_earnings": [EarningsReport(symbol="AAPL", report_at=datetime(2026, 7, 30, 20, 30, tzinfo=UTC),
                                         eps_estimate=1.0, eps_actual=1.2)],
    "openfda": [DrugEvents(symbol="PFE", as_of=date(2026, 10, 12), approval_days=[date(2026, 9, 1)],
                           recall_days={"R1": date(2026, 9, 2)})],
    "yfinance_analyst": [AnalystView(
        symbol="AAPL", as_of=date(2026, 10, 12), oldest_event=datetime(2026, 1, 2, 15), event_count=1,
        events=[RatingEvent(graded_at=datetime(2026, 1, 2, 15), action="up")])],
}
LAYOUTS = {  # source -> (GroupHistory field, the training file's columns)
    "finra_short_interest": [("short_interest", finra_history.INTEREST_COLUMNS)],
    "finra_short_volume": [("short_volume", finra_history.VOLUME_COLUMNS)],
    "yfinance_analyst": [("analyst_events", yahoo_history.EVENT_COLUMNS), ("analyst_coverage", ["symbol", "oldest", "rows"])],
    "sec_8k": [("material_events", sec_history.EVENT_COLUMNS)],
    "sec_13dg": [("large_holders", sec_history.HOLDER_COLUMNS)],
    "sec_form4": [("insider_trades", sec_history.INSIDER_COLUMNS)],
    "sec_13f": [("holders", holders_history.HOLDERS_COLUMNS)],
    "yfinance_earnings": [("estimates", yahoo_history.REPORT_COLUMNS)],
    "openfda": [("fda_events", fda_history.EVENT_COLUMNS)],
}


@pytest.mark.parametrize("source", list(LAYOUTS))
def test_records_become_the_training_layout(source):
    history = history_from_records(_ok(source, RECORDS[source]))
    for field, columns in LAYOUTS[source]:
        frame = getattr(history, field)
        assert list(frame.columns) == list(columns), field
        assert len(frame) >= 1, field
    if source == "yfinance_analyst":  # coverage is the training helper's layout too
        assert list(history.analyst_coverage.columns) == list(analyst.coverage(history.analyst_events).columns)
    empty = history_from_records(_ok(source, []))  # an OK source with nothing to report: empty, not missing
    for field, columns in LAYOUTS[source]:
        assert list(getattr(empty, field).columns) == list(columns) and getattr(empty, field).empty


def test_a_source_that_was_not_ok_this_run_reads_missing_not_zero():
    results = {"sec_form4": CollectorResult("sec_form4", CollectorStatus.PARTIAL, [_trade("AAPL")], 0, "budget")}
    assert history_from_records(results).insider_trades is None


@pytest.mark.parametrize("status", [s for s in CollectorStatus if s is not CollectorStatus.OK])
def test_every_status_but_ok_gives_no_frame(status):
    results = {name: CollectorResult(name, status, records, 0, "x") for name, records in RECORDS.items()}
    history = history_from_records(results)
    fields = [field for pairs in LAYOUTS.values() for field, _ in pairs]
    assert all(getattr(history, field) is None for field in fields)
    assert all(getattr(history_from_records({}), field) is None for field in fields)  # not run at all


def test_live_insider_rows_are_the_non_derivative_open_market_trades():
    """Training reads NONDERIV_TRANS rows with codes P and S only (Task 5)."""
    trades = [_trade("AAPL", code="P"), _trade("AAPL", code="S", shares=50.0), _trade("AAPL", code="P", derivative=True),
              _trade("AAPL", code="M"), _trade("AAPL", code="A")]
    frame = history_from_records(_ok("sec_form4", trades)).insider_trades
    assert frame[["code", "shares"]].values.tolist() == [["P", 100.0], ["S", 50.0]]
    assert frame["filed_ticker"].isna().all() and frame["officer"].all()
    days = pd.DatetimeIndex(["2026-10-05"])
    value = pd.DataFrame({"AAPL": [1_000_000.0]}, index=days)
    out = insider_features(frame, value, {"AAPL"}, days, ["AAPL"])
    assert out["insider_net_buy_90d"]["AAPL"].iloc[0] == pytest.approx((1_000 - 500) / 1_000_000)  # no derivative P


def _upgrades(rows: list[tuple[str, str]]) -> pd.DataFrame:
    """Yahoo's `upgrades_downgrades`: (naive UTC grade time, action) rows, newest first as Yahoo sends them."""
    rows = sorted(rows, reverse=True)
    frame = pd.DataFrame({
        "Firm": "Firm", "ToGrade": "Buy", "FromGrade": "Hold", "Action": [a for _, a in rows],
        "priceTargetAction": ["Raises" if a == "up" else "Lowers" if a == "down" else "Maintains" for _, a in rows],
    }, index=pd.DatetimeIndex([pd.Timestamp(t) for t, _ in rows], name="GradeDate"))
    return frame


def _monthly(start: str, months: int, action: str) -> list[tuple[str, str]]:
    return [((pd.Timestamp(start) + pd.DateOffset(months=m)).strftime("%Y-%m-%d 14:00"), action) for m in range(months)]


SPREAD = _monthly("2023-10-20", 36, "up") + [("2024-05-01 13:00", "down"), ("2025-10-10 13:00", "down")]
# the newest downgrade is 367 days before the run: outside the kept year, so it is kept on its own
CAPPED = [((pd.Timestamp("2026-06-01") + pd.Timedelta(hours=3 * i)).strftime("%Y-%m-%d %H:%M"),
           "down" if i % 50 == 0 else "main") for i in range(1_050)]  # Yahoo's cap reached in 131 days


@pytest.mark.parametrize("grades", [SPREAD, CAPPED], ids=["three-years", "capped"])
def test_trimmed_analyst_records_give_the_full_history_features(grades):
    upgrades = _upgrades(grades)
    view = analyst_view("XYZ", {"mean": 10.0}, None, upgrades, AS_OF)
    assert view.event_count == len(grades) and view.oldest_event == pd.Timestamp(min(t for t, _ in grades))
    if grades is SPREAD:
        assert len(view.events) == 13  # the last year's twelve, and the downgrade 367 days back
    live = history_from_records(_ok("yfinance_analyst", [view]))
    full, _ = yahoo_history.analyst_history(["XYZ"], lambda symbol: upgrades, None)  # the training path
    days = pd.DatetimeIndex(["2026-10-07", "2026-10-09", "2026-10-12"])
    trimmed = analyst_features(live.analyst_events, live.analyst_coverage, days, ["XYZ"])
    expected = analyst_features(full, analyst.coverage(full), days, ["XYZ"])
    for name, frame in expected.items():
        pd.testing.assert_frame_equal(trimmed[name], frame, check_names=False)
    if grades is SPREAD:
        assert trimmed["days_since_downgrade"]["XYZ"].tolist() == [362.0, 364.0, 365.0]
    else:  # a capped list: Yahoo's oldest event is too recent for a full year, as in training
        assert trimmed["days_since_downgrade"]["XYZ"].isna().all()
        assert trimmed["net_upgrades_30d"]["XYZ"].notna().all()


def test_an_analyst_view_cached_before_the_events_reads_missing():
    old = AnalystView(symbol="XYZ", as_of=date(2026, 10, 9), upgrades_30d=3)  # no events, no coverage
    live = history_from_records(_ok("yfinance_analyst", [old]))
    out = analyst_features(live.analyst_events, live.analyst_coverage, pd.DatetimeIndex(["2026-10-12"]), ["XYZ"])
    assert all(frame["XYZ"].isna().all() for frame in out.values())


def test_live_13f_rows_use_the_training_known_date():
    record = InstitutionalOwnership(
        symbol="AAPL", cusip="037833100", period=date(2026, 6, 30), shares=500, value_usd=1, holders=5,
        previous_period=date(2026, 3, 31), previous_shares=400, previous_holders=4,
        quarters=[HeldQuarter(period=date(2026, 6, 30), window_end=date(2026, 8, 31), shares=500, holders=5),
                  HeldQuarter(period=date(2026, 3, 31), window_end=date(2026, 5, 31), shares=400, holders=4),
                  HeldQuarter(period=date(2025, 12, 31), window_end=date(2026, 2, 28), shares=200, holders=2)],
    )
    frame = history_from_records(_ok("sec_13f", [record])).holders
    assert frame["known"].tolist() == [date(2026, 9, 30), date(2026, 6, 30), date(2026, 3, 30)]
    days = pd.DatetimeIndex(["2026-09-30", "2026-10-01"])
    shares = pd.DataFrame({"AAPL": [10_000.0, 10_000.0]}, index=days)
    splits = pd.DataFrame({"Z": [1.0]}, index=pd.DatetimeIndex(["2020-01-01"]))
    out = holders_features(frame, shares, splits, days, ["AAPL"])
    assert out["holder_count_chg"]["AAPL"].tolist() == [2.0, 1.0]  # March - December, then June - March
    assert out["inst_shares_chg"]["AAPL"].tolist() == pytest.approx([0.02, 0.01])


def test_a_13f_record_cached_before_the_quarters_gives_no_rows():
    record = InstitutionalOwnership(symbol="AAPL", cusip="037833100", period=date(2026, 6, 30), shares=500,
                                    value_usd=1, holders=5, previous_period=date(2026, 3, 31))
    assert history_from_records(_ok("sec_13f", [record])).holders.empty


def test_live_13dg_counts_filings_about_other_issuers_as_training_does():
    day = pd.Timestamp("2026-10-12")
    record = _holding("PFE", "SCHEDULE 13G", (day - pd.Timedelta(days=10)).date(), other_issuer=True)
    frame = history_from_records(_ok("sec_13dg", [record])).large_holders
    out = events_features(None, frame, {"PFE"}, pd.DatetimeIndex([day]), ["PFE"])
    assert out["passive_13g_90d"]["PFE"].iloc[0] == 1
    assert out["activist_13d_180d"]["PFE"].iloc[0] == 0


def test_a_pre_open_run_reads_the_twenty_file_days_before_its_day():
    """21 files: the newest is the feature day's own (known that evening), so 20 are read (Ruling R3, F7)."""
    days = pd.bdate_range(end="2026-10-09", periods=VOLUME_SESSIONS + 1)
    records = [ShortVolume(symbol="AAPL", trade_date=d.date(), short_volume=float(i), short_exempt_volume=0.0,
                           total_volume=100.0) for i, d in enumerate(days)]
    volume = history_from_records(_ok("finra_short_volume", records)).short_volume
    feature_day = pd.DatetimeIndex([days[-1]])
    out = short_features(None, volume, pd.DataFrame({"AAPL": [np.nan]}, index=feature_day),
                         pd.DataFrame(), feature_day, ["AAPL"])
    assert out["short_vol_ratio_20d"]["AAPL"].iloc[0] == pytest.approx(np.mean(range(VOLUME_SESSIONS)) / 100)


def test_live_estimates_rows_equal_the_training_rows():
    yahoo = pd.DataFrame(
        {"EPS Estimate": [1.0, 1.1, 1.2], "Reported EPS": [1.05, 1.0, None], "Surprise(%)": [5.0, -9.1, None]},
        index=pd.DatetimeIndex(["2026-01-29 16:30", "2026-04-30 06:00", "2026-07-30 00:00"], tz="America/New_York"),
    )
    live = history_from_records(_ok("yfinance_earnings", parse_earnings("XYZ", yahoo))).estimates
    training, _ = yahoo_history.estimates_history(["XYZ"], lambda symbol: yahoo, None)
    pd.testing.assert_frame_equal(live.reset_index(drop=True), training.reset_index(drop=True), check_dtype=False)
    assert live["timing"].tolist() == ["after-close", "before-open", None]


def test_live_fda_rows_count_as_the_training_rows():
    record = DrugEvents(symbol="PFE", as_of=date(2026, 10, 12),
                        approval_days=[date(2026, 4, 20), date(2026, 4, 20), date(2026, 9, 1)],
                        recall_days={"R1": date(2026, 9, 2), "R2": date(2026, 9, 3)})
    frame = history_from_records(_ok("openfda", [record])).fda_events
    training = pd.DataFrame({
        "symbol": "PFE", "kind": ["approval", "approval", "approval", "recall", "recall"],
        "day": [date(2026, 4, 20), date(2026, 4, 20), date(2026, 9, 1), date(2026, 9, 2), date(2026, 9, 3)],
        "event_id": ["NDA1:original:20260420:0", "NDA1:new_indication:20260420:1", "BLA2:original:20260901:0",
                     "R1", "R2"],
    })
    days = pd.DatetimeIndex(["2026-10-12", "2026-10-19"])
    live = catalysts_features(frame, days, ["PFE", "LLY"])
    expected = catalysts_features(training, days, ["PFE", "LLY"])
    for name, values in expected.items():
        pd.testing.assert_frame_equal(live[name], values)
    assert live["fda_approvals_180d"]["PFE"].tolist() == [3, 3]  # two approvals on one day count twice
    assert live["fda_recalls_90d"]["LLY"].tolist() == [0, 0]  # the source ran: no events read zero


def test_history_from_records_takes_no_run_day():
    """Every known date comes from the records themselves (Ruling R3, F5)."""
    import inspect

    assert list(inspect.signature(history_from_records).parameters) == ["results"]


# A Monday pre-open run: its feature day is the previous Friday (`market_run.feature_day`), 3 days earlier.
MONDAY_RUN = datetime(2026, 10, 12, 12, 15, tzinfo=UTC)
FRIDAY = pd.Timestamp("2026-10-09")
OFFICER_BUY = b"""<ownershipDocument>
  <issuer><issuerCik>0000000042</issuerCik><issuerTradingSymbol>XYZ</issuerTradingSymbol></issuer>
  <reportingOwner>
    <reportingOwnerId><rptOwnerName>DOE JANE</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship><isOfficer>1</isOfficer><officerTitle>CFO</officerTitle></reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable><nonDerivativeTransaction>
    <transactionDate><value>2026-04-10</value></transactionDate>
    <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
    <transactionAmounts><transactionShares><value>1000</value></transactionShares>
      <transactionPricePerShare><value>20</value></transactionPricePerShare>
      <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode></transactionAmounts>
  </nonDerivativeTransaction></nonDerivativeTable>
</ownershipDocument>"""


class OneFilingSec:
    """The parts of SecEdgar SecInsiders uses: one company (CIK 42) with one Form 4."""

    def __init__(self, filing):
        self.filing = filing

    def require_contact(self):
        return "test@example.com"

    def cik_for(self, symbol):
        return 42

    def filings(self, cik):
        return [self.filing]

    def has_document(self, filing):
        return True

    def document(self, cik, filing):
        return OFFICER_BUY

    def forget(self, filing):
        pass


def test_a_monday_pre_open_run_reads_an_officer_buy_at_the_oldest_edge_of_the_window():
    """Known 179 days before Friday's feature day, so training counts it; it was filed 182 days before the
    run day, which a 180-day lookback from the run day would miss (Ruling R13)."""
    from advisor.collectors.sec import Filing
    from advisor.collectors.sec_insiders import SecInsiders
    from advisor.model.insider import OFFICER_WINDOW_DAYS

    filed = date(2026, 4, 13)  # a Monday, accepted 17:00 ET: known that day
    assert (FRIDAY - pd.Timestamp(filed)).days < OFFICER_WINDOW_DAYS < (MONDAY_RUN.date() - filed).days
    filing = Filing(accession="0000000042-26-000001", form="4", filing_date=filed,
                    accepted_at=datetime(2026, 4, 13, 21, tzinfo=UTC), report_date=None, items=(), file_number="",
                    primary_document="form4.xml")
    trades = SecInsiders(OneFilingSec(filing)).fetch(["XYZ"], MONDAY_RUN)
    live = history_from_records(_ok("sec_form4", trades)).insider_trades
    training = pd.DataFrame({
        "symbol": ["XYZ"], "accession": [filing.accession], "filing_date": [filed],
        "accepted_at": pd.to_datetime([filing.accepted_at], utc=True), "trade_date": [date(2026, 4, 10)],
        "code": ["P"], "shares": [1000.0], "price": [20.0], "owners": [["DOE JANE"]], "officer": [True],
        "director": [False], "ten_percent_owner": [False], "filed_ticker": ["XYZ"],
    })
    days = pd.DatetimeIndex([FRIDAY])
    value = pd.DataFrame({"XYZ": [1e9]}, index=days)
    got = insider_features(live, value, {"XYZ"}, days, ["XYZ"])
    want = insider_features(training, value, {"XYZ"}, days, ["XYZ"])
    assert got["officer_buy_180d"]["XYZ"].iloc[0] == want["officer_buy_180d"]["XYZ"].iloc[0] == 1.0


def test_a_monday_pre_open_run_reads_an_approval_at_the_oldest_edge_of_the_window():
    """Dated 2026-04-06: known a week later, 179 days before Friday's feature day, so training counts it;
    older than run day - 187, which a window counted from the run day would miss (Ruling R13)."""
    import httpx

    from advisor.collectors.openfda import (
        APPROVAL_WINDOW_DAYS,
        APPROVALS_URL,
        FDA_LAG_DAYS,
        RECALLS_URL,
        OpenFda,
    )
    from advisor.company_names import CompanyNames

    approved = date(2026, 4, 6)
    assert (MONDAY_RUN.date() - approved).days > APPROVAL_WINDOW_DAYS + FDA_LAG_DAYS
    application = {"application_number": "NDA000001", "sponsor_name": "ACME PHARMS", "submissions": [
        {"submission_status": "AP", "submission_status_date": "20260406", "submission_type": "ORIG",
         "submission_class_code": "TYPE 1"}]}
    answers = {
        APPROVALS_URL: {"meta": {"results": {"total": 1}}, "results": [application]},
        RECALLS_URL: {"meta": {"results": {"total": 1}}, "results": [
            {"report_date": "20261001", "recalling_firm": "Someone Else Inc", "event_id": "E9"}]},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=answers[str(request.url.copy_with(query=None))])

    names = CompanyNames({"ACME": "Acme Pharmaceuticals, Inc. Common Stock"})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        records = OpenFda(client, names=names).fetch(["ACME"], MONDAY_RUN)
    live = history_from_records(_ok("openfda", records)).fda_events
    training = pd.DataFrame({"symbol": ["ACME"], "kind": ["approval"], "day": [approved],
                             "event_id": ["NDA000001:original:20260406:0"]})
    days = pd.DatetimeIndex([FRIDAY])
    got = catalysts_features(live, days, ["ACME"])["fda_approvals_180d"]["ACME"].iloc[0]
    want = catalysts_features(training, days, ["ACME"])["fda_approvals_180d"]["ACME"].iloc[0]
    assert got == want == 1


def test_an_fda_record_cached_before_the_event_dates_reads_missing_not_zero():
    """A record cached before deploy has no `approval_days`/`recall_days`: its events are unknown, so the
    catalysts group reads NaN for that run rather than 0 approvals and recalls."""
    old = DrugEvents.model_validate({"symbol": "PFE", "as_of": "2026-10-12", "recalls_90d": 1})
    assert history_from_records(_ok("openfda", [old])).fda_events is None
    mixed = [old, DrugEvents(symbol="LLY", as_of=date(2026, 10, 12), approval_days=[], recall_days={})]
    assert history_from_records(_ok("openfda", mixed)).fda_events is None
    days = pd.DatetimeIndex(["2026-10-12"])
    out = catalysts_features(history_from_records(_ok("openfda", [old])).fda_events, days, ["PFE"])
    assert all(frame.isna().all().all() for frame in out.values())
