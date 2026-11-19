"""SEC's 13F data sets as a history of institutional holdings per universe symbol (`holders.parquet`).

Each data set on SEC's listing is reduced to totals per CUSIP once (`sec_13f.quarter_totals`, the live
collector's download, reduce and save path) and kept in a folder of the history cache, which nothing
prunes: past data sets never change (Ruling R2, F3). A data set that cannot be read (not published, a
damaged archive, a missing file or column) is logged and recorded as a gap, never raised.

13F rows name a holding by CUSIP. Every data set before 2023q1 has an empty FIGI column, and later ones
fill it on 7 to 12% of rows (Task 0 ledger), so the symbol -> CUSIP map comes from the newest data set
with FIGIs and is used for every quarter (Ruling R6). A symbol without a CUSIP has no rows.
"""

import logging
import zipfile
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from pathlib import Path

import httpx
import pandas as pd

from advisor.collectors.base import check_deadline
from advisor.collectors.openfigi import FigiBook
from advisor.collectors.sec import SecEdgar
from advisor.collectors.sec_13f import LISTING_URL, DataSet, Quarter, parse_listing, quarter_totals
from advisor.model.holders import quarter_known

HOLDERS_COLUMNS = ["symbol", "cusip", "period", "known", "shares", "holders"]

log = logging.getLogger(__name__)


def cusip_map(quarters: Sequence[tuple[DataSet, Quarter]], figis: Mapping[str, Sequence[str]]) -> dict[str, str]:
    """Symbol -> CUSIP, through `Quarter.cusip_for` of the newest data set (by window end) whose FIGI
    votes are not empty. `figis` is each symbol's FIGIs (`FigiBook.lookup`); a symbol none of whose
    FIGIs was reported is left out."""
    voted = [(data_set, quarter) for data_set, quarter in quarters if quarter.figis]
    if not voted:
        return {}
    _, newest = max(voted, key=lambda pair: pair[0].end)
    found = {symbol: newest.cusip_for(list(symbol_figis)) for symbol, symbol_figis in figis.items()}
    return {symbol: cusip for symbol, cusip in found.items() if cusip is not None}


def holders_history(quarters: Sequence[tuple[DataSet, Quarter]], cusips: Mapping[str, str]) -> pd.DataFrame:
    """One row per symbol and data set holding its CUSIP, in HOLDERS_COLUMNS, with `known` =
    `quarter_known(quarter.period, data_set.end)`. Dates are `date` values."""
    rows = [
        (symbol, cusip, quarter.period, quarter_known(quarter.period, data_set.end), held.shares, held.holders)
        for data_set, quarter in quarters
        for symbol, cusip in cusips.items()
        if (held := quarter.holdings.get(cusip)) is not None
    ]
    frame = pd.DataFrame(rows, columns=HOLDERS_COLUMNS)
    frame = frame.astype({"symbol": "string", "cusip": "string", "shares": "int64", "holders": "int64"})
    return frame.sort_values(["symbol", "period", "known"], kind="stable").reset_index(drop=True)


def read_quarters(sec: SecEdgar, folder: Path, data_sets: Sequence[DataSet]
                  ) -> tuple[list[tuple[DataSet, Quarter]], dict[str, str]]:
    """Each data set's totals (cached in `folder`), and the gaps: data set name -> why it was left out."""
    quarters: list[tuple[DataSet, Quarter]] = []
    gaps: dict[str, str] = {}
    for data_set in data_sets:
        check_deadline()
        try:
            quarters.append((data_set, quarter_totals(sec, folder, data_set)))
        except (httpx.HTTPStatusError, zipfile.BadZipFile, KeyError, ValueError) as exc:
            gaps[data_set.name] = f"{type(exc).__name__}: {exc}"[:300]
            log.warning("13F data set %s left out: %s", data_set.name, gaps[data_set.name])
    return quarters, gaps


def holders_build(sec: SecEdgar, figis: FigiBook, folder: Path, symbols: Sequence[str], as_of: datetime,
                  since: date, counts: dict[str, int] | None = None) -> tuple[pd.DataFrame, dict[str, str]]:
    """`holders.parquet` for `symbols` from every data set whose window ends on or after `since`, and the
    gaps. The totals stay in `folder` and the FIGIs in `figis`' file, for the next history run. A symbol
    OpenFIGI could not look up has no CUSIP, so no rows. The counts are logged and, when `counts` is
    given, put in it: `asked`, `figi_failed` (OpenFIGI failed before looking them up), `mapped` (to a
    CUSIP), `with_holdings`, `data_sets` (read) and `gaps`."""
    data_sets = [d for d in parse_listing(sec.get(LISTING_URL).text) if d.end >= since]
    quarters, gaps = read_quarters(sec, folder, data_sets)
    lookup = figis.lookup(symbols, as_of)
    if lookup.failed:
        log.warning("OpenFIGI failed for %d symbols: %s", len(lookup.failed), lookup.error)
    cusips = cusip_map(quarters, lookup.figis)
    frame = holders_history(quarters, cusips)
    found = {
        "asked": len(dict.fromkeys(symbols)), "figi_failed": len(lookup.failed), "mapped": len(cusips),
        "with_holdings": int(frame["symbol"].nunique()), "data_sets": len(quarters), "gaps": len(gaps),
    }
    if counts is not None:
        counts.update(found)
    log.info("13F: %(mapped)d of %(asked)d symbols mapped to a CUSIP, %(with_holdings)d with holdings, "
             "%(figi_failed)d not looked up (OpenFIGI failed); %(data_sets)d data sets, %(gaps)d gaps", found)
    return frame, gaps
