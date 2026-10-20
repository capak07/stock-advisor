"""SEC's bulk company facts reduced to the US universe, every filing of every fact kept as filed.

SEC rebuilds companyfacts.zip nightly (about 1.4 GB), so it is downloaded whole and each company's
JSON is read from it once. Facts are keyed by CIK, so share classes (GOOG, GOOGL) share one
company. A fact repeated in a later filing (a comparative, a restatement) keeps one row per
filing with its own `filed` date, so any day's knowable value can be rebuilt. The ticker map is
current-only: companies that have since delisted are not in it.
"""

import json
import zipfile
from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from typing import Any

import pandas as pd

from advisor.collectors.base import check_deadline
from advisor.collectors.sec import parse_tickers, sec_ticker
from advisor.collectors.sec_xbrl import metric_facts

COLUMNS = ["cik", "metric", "concept", "unit", "start", "end", "value", "filed", "form", "accession"]
CHECK_EVERY = 200  # companies between deadline checks


def entry_name(cik: int) -> str:
    return f"CIK{cik:010d}.json"


def fact_rows(cik: int, payload: Mapping[str, Any], since: date) -> list[tuple]:
    """One row per filed fact for a company, for periods ending on or after `since`."""
    rows: list[tuple] = []
    for metric, concept, unit, fact in metric_facts(payload):
        end = date.fromisoformat(fact["end"])
        if end < since:
            continue
        start = date.fromisoformat(fact["start"]) if "start" in fact else None
        rows.append((
            cik, metric, concept, unit, start, end, float(fact["val"]),
            date.fromisoformat(fact["filed"]), fact["form"], fact["accn"],
        ))
    return rows


def facts_frame(rows: Iterable[tuple]) -> pd.DataFrame:
    frame = pd.DataFrame(list(rows), columns=COLUMNS)
    frame = frame.astype({"cik": "int32", "value": "float64"})
    for column in ("metric", "concept", "unit", "form", "accession"):
        frame[column] = frame[column].astype("string")
    return frame.sort_values(["cik", "metric", "end", "filed"], kind="stable").reset_index(drop=True)


def reduce_companyfacts(
    zip_path, ciks: Iterable[int], since: date
) -> tuple[pd.DataFrame, list[int]]:
    """The facts of the given companies from the bulk zip, and the CIKs with no entry in it."""
    rows: list[tuple] = []
    absent: list[int] = []
    with zipfile.ZipFile(zip_path) as archive:
        names = set(archive.namelist())
        for count, cik in enumerate(sorted(set(ciks))):
            if count % CHECK_EVERY == 0:
                check_deadline()
            name = entry_name(cik)
            if name not in names:
                absent.append(cik)
                continue
            rows.extend(fact_rows(cik, json.loads(archive.read(name)), since))
    return facts_frame(rows), absent


def universe_ciks(tickers_payload: Mapping[str, Any], symbols: Sequence[str]) -> pd.DataFrame:
    """Each universe symbol's CIK (symbol, cik), in the order given; symbols SEC doesn't list are left out."""
    by_ticker = parse_tickers(tickers_payload)
    pairs = [(symbol, by_ticker[sec_ticker(symbol)]) for symbol in symbols if sec_ticker(symbol) in by_ticker]
    frame = pd.DataFrame(pairs, columns=["symbol", "cik"])
    return frame.astype({"symbol": "string", "cik": "int32"})
