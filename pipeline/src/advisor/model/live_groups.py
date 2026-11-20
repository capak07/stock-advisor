"""The US data groups' history frames for a live run, built from the run's collector records.

`history_from_records` turns each source's records into the frame its training history file holds
(`groups.GROUP_FILES`, the same columns), so a live forecast goes through `feature_frames` and the
same feature functions as a training row, with the same known dates and windows (Ruling R3). It takes
no run day: every known date comes from the records under the training rules. A source whose result
is missing or not `CollectorStatus.OK` gives None, and its features read NaN, never zero.
"""

from collections.abc import Callable, Mapping, Sequence

import pandas as pd
from pydantic import BaseModel

from advisor.collectors.base import CollectorResult, CollectorStatus
from advisor.collectors.finra_short_interest import ShortInterest
from advisor.collectors.finra_short_volume import ShortVolume
from advisor.collectors.openfda import DrugEvents
from advisor.collectors.sec_13f import InstitutionalOwnership
from advisor.collectors.sec_events import MaterialEvent
from advisor.collectors.sec_holders import LargeHolding
from advisor.collectors.sec_insiders import InsiderTrade
from advisor.collectors.yfinance_analyst import AnalystView
from advisor.collectors.yfinance_earnings import EarningsReport
from advisor.model.analyst import coverage_from
from advisor.model.estimates import report_timing
from advisor.model.groups import GroupHistory
from advisor.model.holders import quarter_known
from advisor.model.insider import BUY, SELL
from advisor.models import ET

# The training history files' columns (training.finra_history, yahoo_history, sec_history,
# holders_history and fda_history); the tests pin them to those modules.
INTEREST_COLUMNS = ["symbol", "settlement", "short_interest", "avg_daily_volume", "days_to_cover"]
VOLUME_COLUMNS = ["symbol", "day", "short_volume", "total_volume"]
EVENT_COLUMNS = ["symbol", "graded_at", "firm", "action", "from_grade", "to_grade", "price_target_action"]
EIGHT_K_COLUMNS = ["symbol", "accession", "form", "filing_date", "accepted_at", "items"]
HOLDER_COLUMNS = ["symbol", "accession", "form", "filing_date", "accepted_at", "activist"]
INSIDER_COLUMNS = ["symbol", "accession", "filing_date", "accepted_at", "trade_date", "code", "shares", "price",
                   "owners", "officer", "director", "ten_percent_owner", "filed_ticker"]
HOLDERS_COLUMNS = ["symbol", "cusip", "period", "known", "shares", "holders"]
REPORT_COLUMNS = ["symbol", "report_day", "timing", "eps_estimate", "eps_actual"]
FDA_COLUMNS = ["symbol", "kind", "day", "event_id"]


def _records[R: BaseModel](results: Mapping[str, CollectorResult], name: str, kind: type[R]) -> list[R] | None:
    """The source's records of `kind`, or None when it did not run cleanly this run."""
    result = results.get(name)
    if result is None or result.status is not CollectorStatus.OK:
        return None
    return [record for record in result.records if isinstance(record, kind)]


def _utc(values: Sequence) -> pd.Series:
    """Times as datetime64[ns, UTC] (NaT for None), whatever offsets they carry."""
    return pd.to_datetime(pd.Series(list(values), dtype=object), utc=True).astype("datetime64[ns, UTC]")


def _frame(rows: list[tuple], columns: list[str]) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=columns)
    frame["symbol"] = frame["symbol"].astype("string")
    return frame


def _short_interest(records: list[ShortInterest]) -> pd.DataFrame:
    frame = _frame([
        (r.symbol, r.settlement_date, r.short_interest,
         float("nan") if r.avg_daily_volume is None else float(r.avg_daily_volume),
         float("nan") if r.days_to_cover is None else r.days_to_cover)
        for r in records
    ], INTEREST_COLUMNS)
    return frame.astype({"short_interest": "int64", "avg_daily_volume": "float64", "days_to_cover": "float64"})


def _short_volume(records: list[ShortVolume]) -> pd.DataFrame:
    frame = _frame([(r.symbol, r.trade_date, r.short_volume, r.total_volume) for r in records], VOLUME_COLUMNS)
    return frame.astype({"short_volume": "float64", "total_volume": "float64"})


def _analyst(views: list[AnalystView]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(`analyst_events`, `analyst_coverage`): the kept rating changes, and the coverage of Yahoo's whole
    list through `analyst.coverage_from`, the helper training uses (Ruling R3, F19). A view without
    changes is left out of both, as a symbol Yahoo has nothing for is in training."""
    covered = {view.symbol: view for view in views if view.oldest_event is not None}  # the latest view wins
    events = _frame([
        (symbol, e.graded_at, e.firm, e.action, e.from_grade, e.to_grade, e.price_target_action)
        for symbol, view in covered.items() for e in view.events
    ], EVENT_COLUMNS)
    events["graded_at"] = pd.to_datetime(events["graded_at"]).astype("datetime64[ns]")
    symbols = list(covered)
    oldest = pd.Series([covered[s].oldest_event for s in symbols], index=symbols, dtype="datetime64[ns]")
    rows = pd.Series([covered[s].event_count for s in symbols], index=symbols, dtype="int64")
    return events, coverage_from(oldest, rows)


def _material_events(records: list[MaterialEvent]) -> pd.DataFrame:
    frame = _frame([
        (r.symbol, r.accession, r.form, r.filing_date, None, list(r.items)) for r in records
    ], EIGHT_K_COLUMNS)
    frame["accepted_at"] = _utc([r.accepted_at for r in records])
    return frame


def _large_holders(records: list[LargeHolding]) -> pd.DataFrame:
    """Every filing, those about another issuer too: the filing list is counted as training counts it,
    with no document check (Ruling R4)."""
    frame = _frame([
        (r.symbol, r.accession, r.form, r.filing_date, None, r.activist) for r in records
    ], HOLDER_COLUMNS)
    frame["accepted_at"] = _utc([r.accepted_at for r in records])
    return frame.astype({"activist": bool})


def _insider_trades(records: list[InsiderTrade]) -> pd.DataFrame:
    """The non-derivative open-market trades (codes P and S), as the training data sets give them. The live
    record does not keep the ticker as filed, and no feature reads it."""
    kept = [r for r in records if not r.derivative and r.code in (BUY, SELL)]
    frame = _frame([
        (r.symbol, r.accession, r.filing_date, None, r.trade_date, r.code, r.shares,
         float("nan") if r.price is None else r.price, list(r.owners), r.officer, r.director,
         r.ten_percent_owner, None)
        for r in kept
    ], INSIDER_COLUMNS)
    frame["accepted_at"] = _utc([r.accepted_at for r in kept])
    frame = frame.astype({"shares": "float64", "price": "float64", "officer": bool, "director": bool,
                          "ten_percent_owner": bool})
    for column in ("accession", "code", "filed_ticker"):
        frame[column] = frame[column].astype("string")
    return frame


def _holders(records: list[InstitutionalOwnership]) -> pd.DataFrame:
    """One row per fetched data set that holds the stock, known at `holders.quarter_known`, the training
    rule (Ruling R3, F5). A record cached before `quarters` existed gives none."""
    frame = _frame([
        (r.symbol, r.cusip, q.period, quarter_known(q.period, q.window_end), q.shares, q.holders)
        for r in records for q in r.quarters if q.shares is not None and q.holders is not None
    ], HOLDERS_COLUMNS)
    frame["cusip"] = frame["cusip"].astype("string")
    return frame.astype({"shares": "int64", "holders": "int64"})


def _estimates(records: list[EarningsReport]) -> pd.DataFrame:
    """Reports as `yahoo_history.estimates_history` writes them: the ET report date and its timing."""
    at = _utc([r.report_at for r in records]).dt.tz_convert(ET)
    frame = _frame([(r.symbol, None, None, r.eps_estimate, r.eps_actual) for r in records], REPORT_COLUMNS)
    frame["report_day"] = at.dt.tz_localize(None).dt.normalize().astype("datetime64[ns]")
    frame["timing"] = report_timing(at)
    return frame.astype({"eps_estimate": "float64", "eps_actual": "float64"})


def _fda_events(records: list[DrugEvents]) -> pd.DataFrame | None:
    """One approval row per counted approval date and one recall row per event, as `fda_history` has them.
    An approval's id only has to tell the symbol's approvals apart. None when any record lacks the dates
    (cached before they existed): its events are unknown, so the group reads NaN this run, never 0."""
    if any(r.approval_days is None or r.recall_days is None for r in records):
        return None
    rows = [
        (r.symbol, "approval", day, f"live:{place}") for r in records for place, day in enumerate(r.approval_days)
    ] + [
        (r.symbol, "recall", day, event) for r in records for event, day in r.recall_days.items()
    ]
    frame = _frame(rows, FDA_COLUMNS)
    return frame.astype({"kind": "string", "event_id": "string"})


def _maybe[R: BaseModel](records: list[R] | None,
                         build: Callable[[list[R]], pd.DataFrame | None]) -> pd.DataFrame | None:
    return None if records is None else build(records)


def history_from_records(results: Mapping[str, CollectorResult]) -> GroupHistory:
    """The group history frames of this run's records (see the module docstring)."""
    views = _records(results, "yfinance_analyst", AnalystView)
    events, coverage = _analyst(views) if views is not None else (None, None)
    return GroupHistory(
        short_interest=_maybe(_records(results, "finra_short_interest", ShortInterest), _short_interest),
        short_volume=_maybe(_records(results, "finra_short_volume", ShortVolume), _short_volume),
        analyst_events=events,
        analyst_coverage=coverage,
        material_events=_maybe(_records(results, "sec_8k", MaterialEvent), _material_events),
        large_holders=_maybe(_records(results, "sec_13dg", LargeHolding), _large_holders),
        insider_trades=_maybe(_records(results, "sec_form4", InsiderTrade), _insider_trades),
        holders=_maybe(_records(results, "sec_13f", InstitutionalOwnership), _holders),
        estimates=_maybe(_records(results, "yfinance_earnings", EarningsReport), _estimates),
        fda_events=_maybe(_records(results, "openfda", DrugEvents), _fda_events),
    )
