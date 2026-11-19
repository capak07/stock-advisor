"""The US data groups' history, downloaded weekly into a cache that training and the benchmark copy from.

Ruling R0: only the weekly `history.yml` downloads group history (`build --history-only`), into an
actions cache. `benchmark.yml` and `train.yml` restore that cache and copy what is fresh
(`build --no-history-download`), so neither pays the Yahoo download (about 98 minutes). A group whose
files are missing or were written more than MAX_HISTORY_AGE_DAYS ago is recorded unavailable and not
copied: its rows fail closed rather than train on stale history.

A history run (`build_history`) writes each wanted group's files into `HistoryCache.groups_dir` and its
time into `written.json`. A group that fails is recorded in the manifest and keeps its previous files
and time; the others go on. The groups run in two threads: the Yahoo groups (`analyst`, `estimates`,
limiter-bound), and the others in the spec's priority order with `catalysts` last.
"""

import calendar
import json
import logging
import os
import shutil
import tempfile
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pandas as pd
import pyarrow.parquet as pq

from advisor.collectors.base import RateLimiter
from advisor.collectors.openfigi import FigiBook
from advisor.collectors.sec import SUBMISSIONS_ZIP_URL, SecEdgar
from advisor.model.groups import GROUP_FILES
from advisor.model.variants import ModelConfig, data_groups
from advisor.models import ET
from advisor.schedule import previous_sessions
from advisor.training.fda_history import fda_history
from advisor.training.finra_history import (
    FINRA_CACHE_AFTER_DAYS,
    settlement_dates,
    short_interest_history,
    short_volume_history,
)
from advisor.training.holders_history import holders_build
from advisor.training.sec_history import (
    INSIDER_LISTING_URL,
    SUBMISSION_FORMS,
    insider_data_sets,
    insider_history,
    large_holder_filings,
    material_events,
    reduce_insider_set,
    reduce_submissions,
)
from advisor.training.yahoo_history import (
    analyst_history,
    estimates_history,
    yahoo_earnings,
    yahoo_grades,
)

MAX_HISTORY_AGE_DAYS = 21  # a group written longer ago than this is unavailable, not trained on
YAHOO_GROUPS = ("analyst", "estimates")
OTHER_GROUPS = ("short", "insider", "events", "holders", "catalysts")  # the spec's priority, catalysts last
SEC_GROUPS = frozenset({"events", "insider"})  # both read the one submissions.zip reduce (Ruling R2, F14)
FIRST_SHORT_VOLUME_DAY = date(2018, 8, 1)  # FINRA's CDN answers 403 before it (Task 0 ledger)
SETTLED_AFTER_DAYS = FINRA_CACHE_AFTER_DAYS  # an insider quarter that ended longer ago than this is cached
SUBMISSIONS_PAGE_URL = "https://data.sec.gov/submissions/{name}"
WRITTEN = "written.json"

log = logging.getLogger(__name__)


class EmptyHistory(Exception):
    """A group's download gave no rows at all: an outage or a changed source, never a real answer."""


class HistoryCache:
    """The group-history cache: one folder that the history workflow saves and the others restore.

    `get`/`put` keep pieces that never change as zstd Parquet under `root/kind/key.parquet`: FINRA files
    older than 90 days (kinds `finra_interest` and `finra_volume`, the full parse keyed by FINRA symbol)
    and past insider quarters (kind `insider`, key `2018q1`). Two pieces live outside `get`/`put`, in
    their owners' own formats (Ruling R2, F3): `figi_path`, the OpenFIGI `FigiBook` file, and
    `sec13f_folder`, the 13F totals per data set (`*.json.gz`). `groups_dir` holds each group's newest
    files and `written.json`, {group: ISO UTC time its files were written}. submissions.zip, Yahoo and
    openFDA are fetched on every history run.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self.figi_path = root / "openfigi.json"
        self.sec13f_folder = root / "sec_13f"
        self.groups_dir = root / "groups"

    def _path(self, kind: str, key: str) -> Path:
        return self.root / kind / f"{key}.parquet"

    def get(self, kind: str, key: str) -> pd.DataFrame | None:
        """The frame put under `kind` and `key`, or None when there is none or it cannot be read (a run
        killed while writing it): it is then fetched again."""
        path = self._path(kind, key)
        if not path.exists():
            return None
        try:
            return pd.read_parquet(path)
        except Exception as exc:  # pyarrow raises several types for a damaged file
            log.warning("history cache: %s/%s unreadable, fetching it again: %s", kind, key, type(exc).__name__)
            return None

    def put(self, kind: str, key: str, frame: pd.DataFrame) -> None:
        path = self._path(kind, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        _write_parquet(frame, path)

    def written(self) -> dict[str, str]:
        """{group: ISO UTC time its files were written}; empty when nothing was."""
        try:
            return json.loads((self.groups_dir / WRITTEN).read_text())
        except (OSError, ValueError):
            return {}


@dataclass
class HistoryDeps:
    """What a history run talks to. FINRA and openFDA may share one client; OpenFIGI's is in `figis`
    (a `FigiBook` at `cache.figi_path`). `names` is the whole US symbol directory (symbol -> company
    name) that openFDA sponsors are matched against, as live does."""

    finra: httpx.Client
    fda: httpx.Client
    sec: SecEdgar
    figis: FigiBook
    cache: HistoryCache
    names: Mapping[str, str]
    finra_limiter: RateLimiter | None = None
    yahoo_limiter: RateLimiter | None = None
    fda_limiter: RateLimiter | None = None
    grades: Callable[[str], pd.DataFrame | None] = field(default=yahoo_grades)
    earnings: Callable[[str], pd.DataFrame | None] = field(default=yahoo_earnings)


def wanted_groups(choice: str) -> frozenset[str]:
    """`all` -> every group, `none` -> no group, or a comma list of groups. An unknown name raises ValueError."""
    choice = choice.strip()
    if choice == "all":
        return frozenset(GROUP_FILES)
    if choice == "none":
        return frozenset()
    names = frozenset(name.strip() for name in choice.split(",") if name.strip())
    unknown = sorted(names - GROUP_FILES.keys())
    if unknown or not names:
        raise ValueError(f"unknown data groups: {', '.join(unknown) or choice!r} (known: {', '.join(GROUP_FILES)})")
    return names


def accepted_groups(stored: Mapping[str, Any] | None) -> frozenset[str]:
    """The data groups with history files that the stored US config trains on (`--groups accepted`).
    Empty without a config; `earnings` has no files, so it is never among them."""
    if stored is None:
        return frozenset()
    return frozenset(data_groups(ModelConfig.from_json(stored))) & GROUP_FILES.keys()


def _write_parquet(frame: pd.DataFrame, path: Path) -> None:
    """Write under a temporary name, then rename: a killed run never leaves half a file at `path`."""
    temporary = path.with_name(f"{path.name}.tmp")
    frame.to_parquet(temporary, compression="zstd", index=False)
    os.replace(temporary, path)


@dataclass
class _Run:
    """One history run's inputs and its shared, locked manifest."""

    cache: HistoryCache
    deps: HistoryDeps
    tickers: pd.DataFrame  # unique (symbol, cik) pairs
    symbols: list[str]
    names: Mapping[str, str]
    since: date
    today: date
    now: datetime
    manifest: dict
    lock: threading.Lock = field(default_factory=threading.Lock)
    filings: pd.DataFrame | None = None
    filings_error: str | None = None

    def record(self, key: str, value: Any, inner: str | None = None) -> None:
        with self.lock:
            if inner is None:
                self.manifest[key] = value
            else:
                self.manifest.setdefault(key, {})[inner] = value

    def submissions(self) -> pd.DataFrame:
        if self.filings_error is not None:
            raise SubmissionsFailed(self.filings_error)
        assert self.filings is not None, "submissions are reduced before the SEC groups run"
        return self.filings


class SubmissionsFailed(Exception):
    """submissions.zip could not be downloaded or reduced, so neither `events` nor `insider` can be built."""


def _sec_page(sec: SecEdgar) -> Callable[[str], Mapping]:
    """An overflow page the zip lacks, from SEC (one request), so a company's older filings are never
    silently left out. Task 0 found every page in the zip, so this should not be needed."""

    def fetch(name: str) -> Mapping:
        log.warning("submissions.zip lacks %s: asking SEC for it", name)
        return sec.get(SUBMISSIONS_PAGE_URL.format(name=name)).json()

    return fetch


def _reduce_submissions(run: _Run) -> None:
    """Download submissions.zip once, reduce it to the wanted forms of the universe's companies, delete it."""
    began = time.monotonic()
    try:
        with tempfile.TemporaryDirectory(prefix="submissions-") as folder:
            path = Path(folder) / "submissions.zip"
            log.info("history: submissions.zip download")
            run.deps.sec.download(SUBMISSIONS_ZIP_URL, path)
            log.info("history: submissions.zip reduce for %d companies", run.tickers["cik"].nunique())
            run.filings = reduce_submissions(path, run.tickers["cik"], run.since, page=_sec_page(run.deps.sec),
                                             forms=SUBMISSION_FORMS)
    except Exception as exc:
        run.filings_error = f"submissions.zip: {type(exc).__name__}: {exc}"
        log.warning("history: %s", run.filings_error)
    run.record("seconds", round(time.monotonic() - began, 1), "history_submissions")


def _short(run: _Run) -> dict[str, pd.DataFrame]:
    deps = run.deps
    dates = [day for day in settlement_dates(deps.finra) if run.since <= day <= run.today]
    first = max(run.since, FIRST_SHORT_VOLUME_DAY)
    days = [day for day in previous_sessions(run.today, (run.today - first).days + 1) if day >= first]
    interest = short_interest_history(deps.finra, dates, run.symbols, run.cache, deps.finra_limiter, run.today)
    volume = short_volume_history(deps.finra, days, run.symbols, run.cache, deps.finra_limiter, run.today)
    return {"short_interest.parquet": interest, "short_volume.parquet": volume}


def _analyst(run: _Run) -> dict[str, pd.DataFrame]:
    events, empty = analyst_history(run.symbols, run.deps.grades, run.deps.yahoo_limiter)
    run.record("empty", empty, "analyst")
    return {"analyst_events.parquet": events}


def _estimates(run: _Run) -> dict[str, pd.DataFrame]:
    reports, empty = estimates_history(run.symbols, run.deps.earnings, run.deps.yahoo_limiter)
    run.record("empty", empty, "estimates")
    # a column of only None would be written as Parquet's null type; keep it a string column
    return {"earnings_estimates.parquet": reports.assign(timing=reports["timing"].astype("string"))}


def _events(run: _Run) -> dict[str, pd.DataFrame]:
    filings = run.submissions()
    return {
        "material_events.parquet": material_events(filings, run.tickers),
        "large_holders.parquet": large_holder_filings(filings, run.tickers),
    }


def _quarter_end(name: str) -> date:
    """The last day of a data set's quarter: "2018q1" -> 2018-03-31."""
    year, quarter = int(name[:4]), int(name[5])
    month = 3 * quarter
    return date(year, month, calendar.monthrange(year, month)[1])


def _insider(run: _Run) -> dict[str, pd.DataFrame]:
    filings = run.submissions()
    sec, cache = run.deps.sec, run.cache
    data_sets = [(name, url) for name, url in insider_data_sets(sec.get(INSIDER_LISTING_URL).text)
                 if _quarter_end(name) >= run.since]
    if not data_sets:
        raise EmptyHistory(f"SEC's insider listing names no data set since {run.since}")
    sets: list[pd.DataFrame] = []
    for name, url in data_sets:
        frame = cache.get("insider", name)
        if frame is None:
            with tempfile.TemporaryDirectory(prefix="insider-") as folder:
                path = Path(folder) / f"{name}_form345.zip"
                sec.download(url, path)
                frame = reduce_insider_set(path)
            if (run.today - _quarter_end(name)).days > SETTLED_AFTER_DAYS:
                cache.put("insider", name, frame)
        # rows per quarter, so a TRANS_DATE format that drops rows silently shows as a short quarter
        run.record("insider_rows", len(frame), name)
        sets.append(frame)
    return {"insider_trades.parquet": insider_history(sets, filings, run.tickers)}


def _holders(run: _Run) -> dict[str, pd.DataFrame]:
    counts: dict[str, int] = {}
    frame, gaps = holders_build(run.deps.sec, run.deps.figis, run.cache.sec13f_folder, run.symbols, run.now,
                                run.since, counts=counts)
    run.record("holders", {**counts, "gaps": gaps})
    return {"holders.parquet": frame}


def _catalysts(run: _Run) -> dict[str, pd.DataFrame]:
    if not run.names:
        raise ValueError("no company names to match openFDA sponsors against")
    return {"fda_events.parquet": fda_history(run.deps.fda, run.names, run.since, run.deps.fda_limiter)}


READERS: dict[str, Callable[[_Run], dict[str, pd.DataFrame]]] = {
    "short": _short,
    "analyst": _analyst,
    "insider": _insider,
    "events": _events,
    "holders": _holders,
    "estimates": _estimates,
    "catalysts": _catalysts,
}


def _store(run: _Run, group: str, frames: Mapping[str, pd.DataFrame]) -> None:
    """Write a group's files (each under a temporary name, then renamed), then set its time."""
    if set(frames) != set(GROUP_FILES[group]):
        raise ValueError(f"{group} gave {sorted(frames)}, not {sorted(GROUP_FILES[group])}")
    if all(frame.empty for frame in frames.values()):
        raise EmptyHistory(f"{group}: no rows")
    folder = run.cache.groups_dir
    folder.mkdir(parents=True, exist_ok=True)
    for name, frame in frames.items():
        _write_parquet(frame, folder / name)
    with run.lock:
        times = run.cache.written()
        times[group] = run.now.astimezone(UTC).isoformat()
        temporary = folder / f"{WRITTEN}.tmp"
        temporary.write_text(json.dumps(times, indent=2, sort_keys=True))
        os.replace(temporary, folder / WRITTEN)


def _run_group(run: _Run, group: str) -> None:
    began = time.monotonic()
    log.info("history %s: start", group)
    try:
        frames = READERS[group](run)
        _store(run, group, frames)
        log.info("history %s: %s", group, ", ".join(f"{name} {len(frame)} rows" for name, frame in frames.items()))
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"[:500]
        run.record("unavailable", message, group)  # merged with macro's entry, never assigned over it
        log.warning("history %s: unavailable, earlier files kept: %s", group, message)
    run.record("seconds", round(time.monotonic() - began, 1), f"history_{group}")


def build_history(cache: HistoryCache, groups: frozenset[str], deps: HistoryDeps, tickers: pd.DataFrame,
                  symbols: Sequence[str], names: Mapping[str, str], since: date, now: datetime,
                  manifest: dict) -> None:
    """Download each wanted group's history from `since` on and write it into `cache.groups_dir`.

    `tickers` (`symbol`, `cik`) is tickers.parquet; `symbols` the US universe; `names` the whole US
    directory. Records `manifest["seconds"]["history_<group>"]`, `manifest["empty"]` for the Yahoo groups,
    `manifest["insider_rows"]` per quarter, `manifest["holders"]` and, for a group that failed,
    `manifest["unavailable"][group]`. No facts are needed: the covered set is applied at feature time.
    """
    unknown = sorted(groups - GROUP_FILES.keys())
    if unknown:
        raise ValueError(f"unknown data groups: {', '.join(unknown)}")
    unique = tickers[["symbol", "cik"]].dropna().astype({"cik": "int64"}).drop_duplicates().reset_index(drop=True)
    run = _Run(cache, deps, unique, list(symbols), names, since, now.astimezone(ET).date(), now, manifest)
    manifest.setdefault("seconds", {})

    def yahoo_thread() -> None:
        for group in YAHOO_GROUPS:
            if group in groups:
                _run_group(run, group)

    def other_thread() -> None:
        if groups & SEC_GROUPS:
            _reduce_submissions(run)
        for group in OTHER_GROUPS:
            if group in groups:
                _run_group(run, group)
        run.filings = None  # free the reduced submissions

    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="history") as pool:
        for future in [pool.submit(yahoo_thread), pool.submit(other_thread)]:
            future.result()


def copy_history(cache: HistoryCache, out: Path, groups: frozenset[str], now: datetime,
                 manifest: dict) -> frozenset[str]:
    """Copy each wanted group's cached files into `out` when they were written at most
    MAX_HISTORY_AGE_DAYS before `now`; return the groups copied.

    A group without a time or with a missing file is `manifest["unavailable"][group] = "no cached
    history"`; an older one is "cached history is N days old". Neither is copied, so the dataset leaves
    it out and its rows fail closed. A copied group that this run failed to download (a local build) is
    moved from `unavailable` to `manifest["history_failed"]`: the earlier, still fresh, files are used.
    """
    times = cache.written()
    unavailable: dict[str, str] = manifest.setdefault("unavailable", {})
    copied: set[str] = set()
    for group in sorted(groups):
        stamp = times.get(group)
        paths = [cache.groups_dir / name for name in GROUP_FILES[group]]
        if stamp is None or not all(path.exists() for path in paths):
            unavailable[group] = "no cached history"
            continue
        age = now - datetime.fromisoformat(stamp)
        if age > timedelta(days=MAX_HISTORY_AGE_DAYS):
            unavailable[group] = f"cached history is {age.days} days old"
            continue
        for path in paths:
            target = out / path.name
            shutil.copyfile(path, target)
            manifest.setdefault("files", {})[path.name] = {
                "rows": pq.ParquetFile(target).metadata.num_rows, "bytes": target.stat().st_size,
            }
        manifest.setdefault("history_age_days", {})[group] = round(age / timedelta(days=1), 1)
        if group in unavailable:
            manifest.setdefault("history_failed", {})[group] = unavailable.pop(group)
        copied.add(group)
    if not unavailable:
        manifest.pop("unavailable")
    return frozenset(copied)
