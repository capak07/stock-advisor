"""FIGIs of US tickers from OpenFIGI's keyless mapping API, for finding a stock in 13F data sets.

13F filings name holdings by CUSIP, never by ticker; most filers also give the holding's FIGI.
OpenFIGI maps a ticker to its FIGIs (exchange, composite and share class), and the FIGIs filers
reported lead to the CUSIP (sec_13f). Without a key OpenFIGI answers 25 requests a minute, each
mapping up to 10 tickers. A ticker's FIGIs rarely change, so they are kept on disk and asked for
again only after REFRESH; a ticker OpenFIGI doesn't know is asked for again after RETRY.
"""

import json
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx

from advisor.collectors.base import RateLimiter, check_deadline, post_with_retries
from advisor.models import ET

OPENFIGI_URL = "https://api.openfigi.com/v3/mapping"
OPENFIGI_PER_MINUTE = 25  # without a key (ratelimit-policy: 25;w=60)
JOBS_PER_REQUEST = 10  # without a key
REFRESH = timedelta(days=180)
RETRY = timedelta(days=30)
FIGI = re.compile(r"BBG[0-9A-Z]{9}")


def openfigi_ticker(symbol: str) -> str:
    """OpenFIGI's form of a US ticker: share classes use a slash (BRK.B -> BRK/B)."""
    return symbol.replace(".", "/")


def parse_mapping(payload: object, count: int) -> list[list[str]]:
    """Each job's FIGIs (exchange, composite and share class, deduplicated), in job order.

    A job OpenFIGI can't match ("No identifier found.") has none.
    """
    if not isinstance(payload, list) or len(payload) != count:
        raise ValueError(f"OpenFIGI answered {type(payload).__name__} for {count} jobs")
    results: list[list[str]] = []
    for job in payload:
        if not isinstance(job, dict):
            raise ValueError("OpenFIGI answered a job that isn't an object")
        if "error" in job:
            raise ValueError(f"OpenFIGI: {job['error']}")
        figis: list[str] = []
        for item in job.get("data") or []:
            for key in ("figi", "compositeFIGI", "shareClassFIGI"):
                value = item.get(key)
                if isinstance(value, str) and FIGI.fullmatch(value) and value not in figis:
                    figis.append(value)
        results.append(figis)
    return results


@dataclass
class Lookup:
    figis: dict[str, list[str]]  # symbol -> FIGIs; [] when OpenFIGI doesn't know it
    failed: list[str] = field(default_factory=list)  # symbols not looked up because OpenFIGI failed
    error: str | None = None


class FigiBook:
    """Tickers' FIGIs, from a JSON file on disk, asking OpenFIGI only for new or old entries."""

    def __init__(self, client: httpx.Client, path: Path, limiter: RateLimiter | None = None) -> None:
        self._client = client
        self._path = path
        self._limiter = limiter

    def _load(self) -> dict[str, dict]:
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save(self, book: dict[str, dict]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(".tmp")
        temporary.write_text(json.dumps(book, sort_keys=True), encoding="utf-8")
        os.replace(temporary, self._path)

    def lookup(self, symbols: Sequence[str], as_of: datetime) -> Lookup:
        today = as_of.astimezone(ET).date()
        book = self._load()

        def due(symbol: str) -> bool:
            entry = book.get(symbol)
            if entry is None:
                return True
            age = today - date.fromisoformat(entry["checked"])
            return age >= (REFRESH if entry["figis"] else RETRY)

        wanted = list(dict.fromkeys(symbols))
        stale = [s for s in wanted if due(s)]
        failed: list[str] = []
        error: str | None = None
        for start in range(0, len(stale), JOBS_PER_REQUEST):
            batch = stale[start : start + JOBS_PER_REQUEST]
            jobs = [
                {"idType": "TICKER", "idValue": openfigi_ticker(s), "exchCode": "US"} for s in batch
            ]
            try:
                check_deadline()
                response = post_with_retries(
                    self._client, OPENFIGI_URL, json=jobs, limiter=self._limiter
                )
                answers = parse_mapping(response.json(), len(batch))
            except Exception as exc:
                failed = stale[start:]  # an OpenFIGI failure ends the lookups for this run
                error = f"{type(exc).__name__}: {exc}"[:300]
                break
            for symbol, figis in zip(batch, answers, strict=True):
                book[symbol] = {"figis": figis, "checked": today.isoformat()}
        if len(stale) > len(failed):
            self._save(book)
        # A symbol OpenFIGI couldn't refresh keeps its older FIGIs; only one never looked up fails.
        return Lookup(
            {s: book[s]["figis"] for s in wanted if s in book},
            [s for s in failed if s not in book],
            error,
        )
