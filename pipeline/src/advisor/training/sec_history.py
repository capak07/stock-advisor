"""SEC's bulk submissions reduced to the US universe's filings, for the `events` and `insider` groups.

SEC rebuilds submissions.zip nightly (about 1.5 GB): one `CIK##########.json` per company, whose
`filings.recent` holds its latest filings, plus the overflow pages (`CIK##########-submissions-NNN.json`)
its `filings.files` lists for older ones. Task 0 found the pages inside the zip, so `page` (one SEC
request each) is only a fallback for a page the zip lacks. Only the wanted forms are kept: a bank's
thousands of 424B2 notes must not fill memory (Ruling R2).

The 13D/G rows are the filing list's rows about the company (its "005-" file number); no document is
opened and no issuer is checked, and live counts the same rows (Ruling R4).

Insider trades come from SEC's quarterly Insider Transactions Data Sets (Forms 3, 4 and 5 filed in the
quarter, as tab-separated files), listed on INSIDER_LISTING_URL; past quarters never change. Only the
non-derivative P and S rows of Forms 4 and 4/A are kept, whatever the security: live Form 4 records carry
no security title, so neither side filters on it (Ruling R3, R8). Their acceptance times come from the
submissions frame, by accession.
"""

import json
import logging
import re
import zipfile
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import pandas as pd

from advisor.collectors.base import check_deadline
from advisor.collectors.sec import Filing, number, parse_filings
from advisor.collectors.sec_13f import _rows, sec_date
from advisor.collectors.sec_events import EVENT_FORMS
from advisor.collectors.sec_holders import HOLDER_FORMS, SUBJECT_FILE_NUMBER
from advisor.collectors.sec_insiders import INSIDER_FORMS

SUBMISSION_FORMS = EVENT_FORMS | HOLDER_FORMS | INSIDER_FORMS
COLUMNS = ["cik", "accession", "form", "filing_date", "accepted_at", "items", "file_number"]
EVENT_COLUMNS = ["symbol", "accession", "form", "filing_date", "accepted_at", "items"]
HOLDER_COLUMNS = ["symbol", "accession", "form", "filing_date", "accepted_at", "activist"]
CHECK_EVERY = 200  # companies between deadline checks

INSIDER_LISTING_URL = "https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets"
INSIDER_DATA_SET = re.compile(r'href="(?P<path>[^"]*?(?P<name>\d{4}q[1-4])_form345\.zip)"')  # Task 0 ledger
INSIDER_CODES = frozenset({"P", "S"})  # open-market purchase and sale
INSIDER_ROLES = {"officer": "Officer", "director": "Director", "ten_percent_owner": "TenPercentOwner"}
INSIDER_SET_COLUMNS = ["accession", "issuer_cik", "filed_ticker", "filing_date", "trade_date", "code", "shares",
                       "price", "owners", "officer", "director", "ten_percent_owner"]
INSIDER_COLUMNS = ["symbol", "accession", "filing_date", "accepted_at", "trade_date", "code", "shares", "price",
                   "owners", "officer", "director", "ten_percent_owner", "filed_ticker"]
CHECK_EVERY_ROWS = 100_000  # transaction rows between deadline checks

log = logging.getLogger(__name__)


def entry_name(cik: int) -> str:
    return f"CIK{cik:010d}.json"


def _pages(payload: Mapping[str, Any], since: date) -> list[str]:
    """The overflow pages a company document lists, leaving out those whose last filing is before `since`."""
    names = []
    for listed in payload["filings"].get("files") or []:
        last = listed.get("filingTo")
        if last and date.fromisoformat(last) < since:
            continue
        names.append(listed["name"])
    return names


def _company_filings(archive: zipfile.ZipFile, names: set[str], cik: int, since: date,
                     page: Callable[[str], Mapping] | None) -> list[Filing]:
    """A company's filings from its document and its overflow pages (none when the zip lacks the company)."""
    name = entry_name(cik)
    if name not in names:
        return []
    payload = json.loads(archive.read(name))
    filings = parse_filings(payload)
    for page_name in _pages(payload, since):
        if page_name in names:
            arrays = json.loads(archive.read(page_name))
        elif page is not None:
            arrays = page(page_name)
        else:
            log.warning("submissions.zip lacks %s and no fallback was given; its filings are left out", page_name)
            continue
        filings.extend(parse_filings({"filings": {"recent": arrays}}))  # a page holds the arrays at its top level
    return filings


def _frame(rows: list[tuple]) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=COLUMNS)
    frame["cik"] = frame["cik"].astype("int64")
    frame["accepted_at"] = pd.to_datetime(frame["accepted_at"], utc=True).astype("datetime64[ns, UTC]")
    for column in ("accession", "form", "file_number"):
        frame[column] = frame[column].astype("string")
    return frame.drop_duplicates(["cik", "accession"]).reset_index(drop=True)


def reduce_submissions(zip_path: Path, ciks: Iterable[int], since: date,
                       page: Callable[[str], Mapping] | None = None,
                       forms: frozenset[str] | None = None) -> pd.DataFrame:
    """The filings of the given companies filed on or after `since` (only `forms`, when given).

    Columns: `cik`, `accession`, `form`, `filing_date` (date), `accepted_at` (true acceptance time,
    datetime64[ns, UTC], NaT when SEC gives none), `items` (list of 8-K item codes) and `file_number`.
    Each company's `filings.recent` is read, then each overflow page that reaches `since`: from the zip,
    or through `page(name)` (the page's JSON) when the zip lacks it. A CIK without an entry adds nothing.
    """
    rows: list[tuple] = []
    with zipfile.ZipFile(zip_path) as archive:
        names = set(archive.namelist())
        for count, cik in enumerate(sorted(set(ciks))):
            if count % CHECK_EVERY == 0:
                check_deadline()
            for filing in _company_filings(archive, names, cik, since, page):
                if filing.filing_date < since or (forms is not None and filing.form not in forms):
                    continue
                rows.append((cik, filing.accession, filing.form, filing.filing_date, filing.accepted_at,
                             list(filing.items), filing.file_number))
    return _frame(rows)


def _per_symbol(filings: pd.DataFrame, tickers: pd.DataFrame) -> pd.DataFrame:
    """`filings` joined to every symbol of their company (share classes share a CIK)."""
    tick = tickers[["symbol", "cik"]].dropna().astype({"cik": "int64"})
    return filings.astype({"cik": "int64"}).merge(tick, on="cik", how="inner")


def material_events(filings: pd.DataFrame, tickers: pd.DataFrame) -> pd.DataFrame:
    """Each universe symbol's 8-Ks (EVENT_FORMS), in EVENT_COLUMNS; `tickers` has `symbol` and `cik`."""
    eights = filings[filings["form"].isin(EVENT_FORMS)]
    return _per_symbol(eights, tickers)[EVENT_COLUMNS].reset_index(drop=True)


def large_holder_filings(filings: pd.DataFrame, tickers: pd.DataFrame) -> pd.DataFrame:
    """Each universe symbol's Schedule 13D/Gs about it (HOLDER_FORMS under a "005-" file number), in
    HOLDER_COLUMNS; `activist` is true for a 13D. No document is opened (Ruling R4)."""
    about = filings["form"].isin(HOLDER_FORMS) & filings["file_number"].fillna("").str.startswith(
        SUBJECT_FILE_NUMBER)
    holders = _per_symbol(filings[about.astype(bool)], tickers)
    holders["activist"] = holders["form"].str.contains("13D", regex=False).astype(bool)
    return holders[HOLDER_COLUMNS].reset_index(drop=True)


def insider_data_sets(html: str) -> list[tuple[str, str]]:
    """The quarterly data sets on SEC's listing page, oldest first: ("2018q1", absolute URL). The paths are
    read from the page (they sit in two folders), never built."""
    found: dict[str, str] = {}
    for match in INSIDER_DATA_SET.finditer(html):
        found.setdefault(match["name"], urljoin(INSIDER_LISTING_URL, match["path"]))
    return sorted(found.items())


def _sec_day(text: str) -> date | None:
    """A data set date (SEC's DD-MON-YYYY), or None when it is empty or unreadable."""
    try:
        return sec_date(text)
    except ValueError:
        return None


def _insider_frame(rows: list[tuple]) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=INSIDER_SET_COLUMNS)
    frame["issuer_cik"] = frame["issuer_cik"].astype("int64")
    for column in ("accession", "filed_ticker", "code"):
        frame[column] = frame[column].astype("string")
    for column in ("shares", "price"):
        frame[column] = frame[column].astype(float)
    for column in INSIDER_ROLES:
        frame[column] = frame[column].astype(bool)
    return frame


def reduce_insider_set(zip_path: Path) -> pd.DataFrame:
    """One quarterly Insider Transactions Data Set reduced to its open-market trades, in INSIDER_SET_COLUMNS.

    One row per non-derivative transaction (NONDERIV_TRANS) of a Form 4 or 4/A (SUBMISSION's DOCUMENT_TYPE)
    with code P or S. `owners` lists the filing's reporting owners (REPORTINGOWNER's RPTOWNERNAME), and a
    role is true when any owner's RPTOWNER_RELATIONSHIP names it. `filed_ticker` is the issuer's trading
    symbol as filed; `price` is NaN when not given. A row without shares or a trade date is left out, as
    live leaves it out. Files are read by column name.
    """
    with zipfile.ZipFile(zip_path) as archive:
        filings: dict[str, tuple[int, str | None, date]] = {}
        for c, row in _rows(archive, "SUBMISSION.tsv"):
            cik, filed = row[c["ISSUERCIK"]].strip(), _sec_day(row[c["FILING_DATE"]])
            if row[c["DOCUMENT_TYPE"]].strip() in INSIDER_FORMS and cik.isdigit() and filed is not None:
                ticker = row[c["ISSUERTRADINGSYMBOL"]].strip() or None
                filings[row[c["ACCESSION_NUMBER"]].strip()] = (int(cik), ticker, filed)
        owners: dict[str, list[str]] = defaultdict(list)
        roles: dict[str, set[str]] = defaultdict(set)
        for c, row in _rows(archive, "REPORTINGOWNER.tsv"):
            accession = row[c["ACCESSION_NUMBER"]].strip()
            if accession not in filings:
                continue
            name = row[c["RPTOWNERNAME"]].strip()
            if name and name not in owners[accession]:
                owners[accession].append(name)
            relationship = row[c["RPTOWNER_RELATIONSHIP"]]
            roles[accession].update(role for role, word in INSIDER_ROLES.items() if word in relationship)
        rows: list[tuple] = []
        for index, (c, row) in enumerate(_rows(archive, "NONDERIV_TRANS.tsv")):
            if index % CHECK_EVERY_ROWS == 0:
                check_deadline()
            accession, code = row[c["ACCESSION_NUMBER"]].strip(), row[c["TRANS_CODE"]].strip()
            if accession not in filings or code not in INSIDER_CODES:
                continue
            shares, traded = number(row[c["TRANS_SHARES"]]), _sec_day(row[c["TRANS_DATE"]])
            if shares is None or traded is None:
                continue
            cik, ticker, filed = filings[accession]
            held = roles[accession]
            rows.append((accession, cik, ticker, filed, traded, code, shares, number(row[c["TRANS_PRICEPERSHARE"]]),
                         list(owners[accession]), *(role in held for role in INSIDER_ROLES)))
    return _insider_frame(rows)


def insider_history(sets: Sequence[pd.DataFrame], filings: pd.DataFrame, tickers: pd.DataFrame) -> pd.DataFrame:
    """The universe's insider trades (written as insider_trades.parquet), in INSIDER_COLUMNS.

    `sets` are `reduce_insider_set` frames; each trade goes to every symbol of its issuer's CIK (`tickers`
    has `symbol` and `cik`), and `accepted_at` is joined from `filings` (`reduce_submissions`) by accession,
    NaT when it has none.
    """
    frames = [frame for frame in sets if not frame.empty]
    trades = pd.concat(frames, ignore_index=True) if frames else _insider_frame([])
    tick = tickers[["symbol", "cik"]].dropna().astype({"cik": "int64"}).rename(columns={"cik": "issuer_cik"})
    trades = trades.astype({"issuer_cik": "int64"}).merge(tick, on="issuer_cik", how="inner")
    accepted = filings[["accession", "accepted_at"]].dropna(subset=["accepted_at"]).drop_duplicates("accession")
    trades = trades.merge(accepted.astype({"accession": "string"}), on="accession", how="left")
    trades["accepted_at"] = pd.to_datetime(trades["accepted_at"], utc=True).astype("datetime64[ns, UTC]")
    return trades[INSIDER_COLUMNS].reset_index(drop=True)
