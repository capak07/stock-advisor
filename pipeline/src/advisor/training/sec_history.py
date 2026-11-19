"""SEC's bulk submissions reduced to the US universe's filings, for the `events` and `insider` groups.

SEC rebuilds submissions.zip nightly (about 1.5 GB): one `CIK##########.json` per company, whose
`filings.recent` holds its latest filings, plus the overflow pages (`CIK##########-submissions-NNN.json`)
its `filings.files` lists for older ones. Task 0 found the pages inside the zip, so `page` (one SEC
request each) is only a fallback for a page the zip lacks. Only the wanted forms are kept: a bank's
thousands of 424B2 notes must not fill memory (Ruling R2).

The 13D/G rows are the filing list's rows about the company (its "005-" file number); no document is
opened and no issuer is checked, and live counts the same rows (Ruling R4).
"""

import json
import logging
import zipfile
from collections.abc import Callable, Iterable, Mapping
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from advisor.collectors.base import check_deadline
from advisor.collectors.sec import Filing, parse_filings
from advisor.collectors.sec_events import EVENT_FORMS
from advisor.collectors.sec_holders import HOLDER_FORMS, SUBJECT_FILE_NUMBER

SUBMISSION_FORMS = EVENT_FORMS | HOLDER_FORMS | {"4", "4/A"}
COLUMNS = ["cik", "accession", "form", "filing_date", "accepted_at", "items", "file_number"]
EVENT_COLUMNS = ["symbol", "accession", "form", "filing_date", "accepted_at", "items"]
HOLDER_COLUMNS = ["symbol", "accession", "form", "filing_date", "accepted_at", "activist"]
CHECK_EVERY = 200  # companies between deadline checks

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
