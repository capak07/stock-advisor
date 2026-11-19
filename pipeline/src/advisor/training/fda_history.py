"""openFDA drug approvals and recalls as a history table for the stock model (`fda_events.parquet`).

Read from openFDA's bulk files, the ones `download.json` lists for `drug/drugsfda` and `drug/enforcement`
(one partition each on 2026-11-19; the Task 0 ledger), not from the search API. Sponsors and recalling
firms are names, matched with `SponsorMatcher` over the directory names of the whole US universe, the
same as the live collector, so training and live agree: a name matching two companies matches none, and
two share classes of one company both get the event.

Columns: `symbol`, `kind` ("approval" | "recall"), `day` (a `date`) and `event_id`.
- Approvals are the `original` and `new_indication` kinds the live collector counts (`new_molecule` is a
  subset of `original`); the id is the application, kind, date and place among the application's counted
  submissions, so every counted submission is one row, as live counts it.
- Recalls are one row per symbol and distinct `event_id` (the recall number when there is none).
"""

import io
import json
import zipfile
from collections.abc import Mapping
from datetime import date

import httpx
import pandas as pd

from advisor.collectors.base import RateLimiter, check_deadline, get_with_retries
from advisor.collectors.openfda import approvals, fda_date
from advisor.sponsors import SponsorMatcher

DOWNLOAD_URL = "https://api.fda.gov/download.json"
EVENT_COLUMNS = ["symbol", "kind", "day", "event_id"]
COUNTED = ("original", "new_indication")


def _records(client: httpx.Client, listing: Mapping, dataset: str, limiter: RateLimiter | None) -> list[dict]:
    """Every record of the dataset's bulk files (each a zip holding one JSON document)."""
    records: list[dict] = []
    for partition in listing["results"]["drug"][dataset]["partitions"]:
        check_deadline()
        body = get_with_retries(client, partition["file"], limiter=limiter).content
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            name = next(n for n in archive.namelist() if n.endswith(".json"))
            records.extend(json.loads(archive.read(name))["results"])
    return records


def fda_history(client: httpx.Client, names: Mapping[str, str], since: date,
                limiter: RateLimiter | None) -> pd.DataFrame:
    """Approval and recall rows from `since` on, for the symbols of `names` (symbol -> directory name of
    the whole US universe), sorted by symbol, kind, day and event id."""
    listing = get_with_retries(client, DOWNLOAD_URL, limiter=limiter).json()
    matcher = SponsorMatcher(names)
    matched: dict[str, set[str]] = {}

    def symbols_for(name: str) -> set[str]:
        if name not in matched:
            matched[name] = matcher.symbols_for(name)
        return matched[name]

    rows: set[tuple[str, str, date, str]] = set()
    for application in _records(client, listing, "drugsfda", limiter):
        number = str(application.get("application_number", ""))
        counted = [item for item in approvals([application], since, date.max) if item[1] in COUNTED]
        for place, (sponsor, kind, day) in enumerate(counted):
            for symbol in symbols_for(sponsor):
                rows.add((symbol, "approval", day, f"{number}:{kind}:{day:%Y%m%d}:{place}"))
    for recall in _records(client, listing, "enforcement", limiter):
        day = fda_date(recall.get("report_date"))
        if day is None or day < since:
            continue
        event = str(recall.get("event_id") or recall.get("recall_number"))
        for symbol in symbols_for(recall.get("recalling_firm") or ""):
            rows.add((symbol, "recall", day, event))
    frame = pd.DataFrame(sorted(rows), columns=EVENT_COLUMNS)
    return frame.astype({"symbol": "string", "kind": "string", "event_id": "string"})
