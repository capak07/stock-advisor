"""Institutional ownership from SEC's Form 13F data sets (spec source 11, US only).

Managers with over $100 million in US equities report their holdings each quarter on Form 13F,
due 45 days after the quarter ends. SEC publishes every 13F filed in a three-month window as one
ZIP of about 100 MB, a few weeks after the window closes, and lists them on LISTING_URL. A
window's filings are mostly one quarter's reports, plus late and amended ones for older quarters.

Each fetch reads the listing (one request). The two newest data sets give the latest quarter and
the one before. Each is downloaded once, reduced to totals per CUSIP and kept on disk, so a ZIP
is downloaded about four times a year. A quarter counts only the reports filed in its own window,
so late filers are left out of both quarters alike.

The totals follow the research (.superpowers/research/plan-2b/sec.md §5.3):
- only the quarter's own reports (PERIODOFREPORT), never 13F-NT notices;
- per filer, the latest RESTATEMENT amendment replaces the original report, and NEW HOLDINGS
  amendments filed after the report it amends add rows;
- shares only (SSHPRNAMTTYPE SH), no options (PUTCALL) and no debt (PRN);
- holders are distinct filers (CIK).

13F rows name a holding by CUSIP, never by ticker; most filers also give its FIGI. A stock's
FIGIs come from OpenFIGI (openfigi.FigiBook), and its CUSIP is the one most rows reported with
them.
"""

import csv
import gzip
import io
import json
import os
import re
import zipfile
from collections import Counter, defaultdict
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin

from pydantic import BaseModel, ConfigDict, Field

from advisor.collectors.base import Cadence, Category, PartialFetch, Scope, check_deadline
from advisor.collectors.openfigi import FIGI, FigiBook
from advisor.collectors.sec import SecEdgar
from advisor.models import AssetType, Market

LISTING_URL = "https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets"
DATA_SET = re.compile(
    r'href="(?P<path>[^"]*?(?P<name>\d{2}[a-z]{3}\d{4}-\d{2}[a-z]{3}\d{4})_form13f\.zip)"'
)
QUARTERS = 2  # the latest quarter and the one before
CHECK_EVERY = 100_000  # INFOTABLE rows between deadline checks (a data set has about 3.8 million)
ORIGINAL, RESTATEMENT, NEW_HOLDINGS = "13F-HR", "RESTATEMENT", "NEW HOLDINGS"

csv.field_size_limit(10_000_000)  # some ADDITIONALINFORMATION cells are long


class InstitutionalOwnership(BaseModel):
    """What 13F filers held of one stock at the end of the latest quarter, and the quarter before."""

    model_config = ConfigDict(frozen=True)

    symbol: str
    cusip: str
    period: date  # the quarter's last day
    shares: int = Field(ge=0)
    value_usd: int = Field(ge=0)
    holders: int = Field(ge=1)
    previous_period: date
    previous_shares: int | None = Field(default=None, ge=0)  # None: no filer reported it then
    previous_holders: int | None = Field(default=None, ge=1)


@dataclass(frozen=True)
class DataSet:
    name: str  # the filing window, e.g. "01jun2026-31aug2026"
    url: str
    end: date


def parse_listing(html: str) -> list[DataSet]:
    """The data sets on SEC's listing page, newest window first."""
    found: dict[str, DataSet] = {}
    for match in DATA_SET.finditer(html):
        name = match["name"]
        end = datetime.strptime(name.split("-")[1], "%d%b%Y").date()
        found.setdefault(name, DataSet(name, urljoin(LISTING_URL, match["path"]), end))
    return sorted(found.values(), key=lambda d: d.end, reverse=True)


def sec_date(text: str) -> date:
    """SEC's DD-MON-YYYY: "31-MAR-2026"."""
    return datetime.strptime(text.strip(), "%d-%b-%Y").date()


@dataclass(frozen=True)
class Holding:
    shares: int
    value_usd: int
    holders: int


@dataclass(frozen=True)
class Quarter:
    period: date
    holdings: Mapping[str, Holding]  # by CUSIP
    figis: Mapping[str, tuple[str, int]]  # FIGI -> (the CUSIP most rows gave it, those rows)

    def cusip_for(self, figis: Sequence[str]) -> str | None:
        """The CUSIP these FIGIs were reported with most often, or None if no row gave one."""
        votes: Counter[str] = Counter()
        for figi in figis:
            if figi in self.figis:
                cusip, rows = self.figis[figi]
                votes[cusip] += rows
        return votes.most_common(1)[0][0] if votes else None


def _rows(archive: zipfile.ZipFile, name: str) -> Iterator[tuple[dict[str, int], list[str]]]:
    with archive.open(name) as raw:
        reader = csv.reader(io.TextIOWrapper(raw, encoding="utf-8", newline=""), delimiter="\t")
        column = {heading: index for index, heading in enumerate(next(reader))}
        for row in reader:
            if len(row) == len(column):
                yield column, row


@dataclass(frozen=True)
class _Report:
    accession: str
    cik: str
    kind: str  # ORIGINAL, RESTATEMENT or NEW_HOLDINGS
    filed: date


def counted_reports(reports: Sequence[_Report]) -> dict[str, str]:
    """Accession -> filer CIK, for the reports whose rows count: per filer, the latest restatement
    (or else the latest original report) and the NEW HOLDINGS amendments filed after it."""
    by_filer: dict[str, list[_Report]] = defaultdict(list)
    for report in reports:
        by_filer[report.cik].append(report)
    counted: dict[str, str] = {}
    for cik, filed in by_filer.items():
        filed.sort(key=lambda r: (r.filed, r.accession))
        restated = [r for r in filed if r.kind == RESTATEMENT]
        bases = restated or [r for r in filed if r.kind == ORIGINAL]
        if not bases:
            continue  # an amendment whose report was filed in another window
        base = bases[-1]
        counted[base.accession] = cik
        for report in filed:
            later = (report.filed, report.accession) > (base.filed, base.accession)
            if report.kind == NEW_HOLDINGS and later:
                counted[report.accession] = cik
    return counted


def aggregate(archive: zipfile.ZipFile) -> Quarter:
    """Totals per CUSIP for the quarter most of this data set's reports are for."""
    fields = ("ACCESSION_NUMBER", "SUBMISSIONTYPE", "CIK", "PERIODOFREPORT", "FILING_DATE")
    submissions = [tuple(row[c[f]] for f in fields) for c, row in _rows(archive, "SUBMISSION.tsv")]
    periods = Counter(period for _, kind, _, period, _ in submissions if kind == ORIGINAL)
    if not periods:
        raise ValueError("the 13F data set has no 13F-HR reports")
    period = periods.most_common(1)[0][0]
    amendments = {
        row[c["ACCESSION_NUMBER"]]: row[c["AMENDMENTTYPE"]].strip()
        for c, row in _rows(archive, "COVERPAGE.tsv")
        if row[c["ISAMENDMENT"]].strip() == "Y"
    }
    reports = [
        _Report(
            accession, cik, ORIGINAL if kind == ORIGINAL else amendments.get(accession, ""), sec_date(filed)
        )
        for accession, kind, cik, report_period, filed in submissions
        if report_period == period and kind in (ORIGINAL, "13F-HR/A")
    ]
    filer_of = counted_reports(reports)

    shares: dict[str, int] = defaultdict(int)
    value: dict[str, int] = defaultdict(int)
    holders: dict[str, set[str]] = defaultdict(set)
    votes: Counter[tuple[str, str]] = Counter()
    for index, (c, row) in enumerate(_rows(archive, "INFOTABLE.tsv")):
        if index % CHECK_EVERY == 0:
            check_deadline()
        cusip = row[c["CUSIP"]].strip().upper()
        if not cusip:
            continue
        figi = row[c["FIGI"]].strip().upper()
        if FIGI.fullmatch(figi):
            votes[(figi, cusip)] += 1  # every row votes, whatever its quarter
        cik = filer_of.get(row[c["ACCESSION_NUMBER"]])
        if cik is None or row[c["PUTCALL"]].strip() or row[c["SSHPRNAMTTYPE"]].strip() != "SH":
            continue
        try:
            amount = int(float(row[c["SSHPRNAMT"]]))
            dollars = int(float(row[c["VALUE"]] or 0))
        except ValueError:
            continue
        shares[cusip] += amount
        value[cusip] += dollars
        holders[cusip].add(cik)

    figis: dict[str, tuple[str, int]] = {}
    for (figi, cusip), rows in votes.items():
        if figi not in figis or rows > figis[figi][1]:
            figis[figi] = (cusip, rows)
    return Quarter(
        sec_date(period),
        {cusip: Holding(shares[cusip], value[cusip], len(holders[cusip])) for cusip in shares},
        figis,
    )


def save_quarter(path: Path, quarter: Quarter) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "period": quarter.period.isoformat(),
        "holdings": {c: [h.shares, h.value_usd, h.holders] for c, h in quarter.holdings.items()},
        "figis": {f: list(pair) for f, pair in quarter.figis.items()},
    }
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(gzip.compress(json.dumps(payload).encode("utf-8")))
    os.replace(temporary, path)


def load_quarter(path: Path) -> Quarter:
    payload = json.loads(gzip.decompress(path.read_bytes()))
    return Quarter(
        date.fromisoformat(payload["period"]),
        {c: Holding(*values) for c, values in payload["holdings"].items()},
        {f: (cusip, rows) for f, (cusip, rows) in payload["figis"].items()},
    )


class Sec13f:
    name = "sec_13f"
    category = Category.FUNDAMENTALS
    core = False
    best_effort = False
    cadence = Cadence.WEEKLY
    asset_types = frozenset({AssetType.STOCK})
    markets = frozenset({Market.US})
    record_type = InstitutionalOwnership
    freshness = timedelta(days=120)  # a quarter's numbers stand until the next quarter's
    scope = Scope.SYMBOLS
    canary = ("AAPL",)
    canary_requires_records = True
    max_symbols = None

    def __init__(self, sec: SecEdgar, figis: FigiBook, folder: Path) -> None:
        self._sec = sec
        self._figis = figis
        self._folder = folder

    def fetch(self, symbols: Sequence[str], as_of: datetime) -> list[InstitutionalOwnership]:
        data_sets = parse_listing(self._sec.get(LISTING_URL).text)[:QUARTERS]
        if len(data_sets) < QUARTERS:
            raise ValueError(f"SEC's 13F listing names {len(data_sets)} data sets, not {QUARTERS}")
        latest, previous = (self._quarter(data_set) for data_set in data_sets)
        self._prune(data_sets)
        lookup = self._figis.lookup(symbols, as_of)
        records: list[InstitutionalOwnership] = []
        for symbol in dict.fromkeys(symbols):
            cusip = latest.cusip_for(lookup.figis.get(symbol, []))
            held = latest.holdings.get(cusip) if cusip else None
            if cusip is None or held is None:
                continue
            before = previous.holdings.get(cusip)
            records.append(InstitutionalOwnership(
                symbol=symbol,
                cusip=cusip,
                period=latest.period,
                shares=held.shares,
                value_usd=held.value_usd,
                holders=held.holders,
                previous_period=previous.period,
                previous_shares=before.shares if before else None,
                previous_holders=before.holders if before else None,
            ))
        if lookup.failed:
            raise PartialFetch(
                records, f"OpenFIGI failed for {len(lookup.failed)} symbols; {lookup.error}"
            )
        return records

    def _quarter(self, data_set: DataSet) -> Quarter:
        """The data set's totals from disk, or downloaded and reduced once."""
        path = self._folder / f"{data_set.name}.json.gz"
        try:
            return load_quarter(path)
        except (OSError, ValueError, KeyError):
            pass  # not reduced yet, or a damaged file: download again
        response = self._sec.get(data_set.url)
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            quarter = aggregate(archive)
        save_quarter(path, quarter)
        return quarter

    def _prune(self, kept: Sequence[DataSet]) -> None:
        """Drop the totals of data sets that are no longer among the newest."""
        names = {f"{data_set.name}.json.gz" for data_set in kept}
        for path in self._folder.glob("*.json.gz"):
            if path.name not in names:
                path.unlink(missing_ok=True)
