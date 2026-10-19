# Plan 2g: 13F Institutional Ownership — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A new `sec_13f` collector gives each US stock what institutions held of it at the end of the latest quarter and the quarter before. It reads SEC's Form 13F data sets and finds each stock through OpenFIGI (spec source 11).

**Architecture:**
- **SEC's data sets.** SEC publishes every 13F filed in a three-month window as one ZIP of about 100 MB, a few weeks after the window closes, and lists them on a web page.
  - Each fetch reads that listing (one request).
  - The two newest data sets give the latest quarter and the one before.
  - Each is downloaded once, reduced to totals per CUSIP, and kept in the run cache (`pipeline/.cache/sec-13f`), so a ZIP is downloaded about four times a year.
- **Finding a stock.** 13F rows name holdings by CUSIP, never by ticker, but most filers also give the holding's FIGI.
  - OpenFIGI's keyless mapping API turns the run's tickers into FIGIs, 10 per request.
  - A stock's CUSIP is the one most rows reported with those FIGIs.
  - The FIGIs are kept on disk too, so only new tickers are asked for.
- **Records** are cached per symbol like every other enrichment source, for the model to use (Plan 3). Nothing is written to the database.

**Tech Stack:** Python 3.12, httpx, pydantic 2, the standard library's `zipfile`, `csv` and `gzip`; pytest; ruff. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-10-09-stock-advisor-design.md` (rev 2), §4.1 Collector protocol and §4.2 Sources (row 11). Also read:
- `docs/superpowers/deferred.md`, "Plan 2g";
- the research, `.superpowers/research/plan-2b/sec.md` §5 (git-ignored, on the owner's machine).

**Prototype:** every file below was built and tested on branch `plan-2g-proto` (2026-10-19), with 686 pipeline tests passing and ruff clean. A live run against SEC and OpenFIGI fetched AAPL, MSFT, NVDA, BRK.B, GOOGL, GOOG, TSM, PLTR, SPY, RY, BF.B and SOFI:
- the first fetch took 41 s, for two 100 MB downloads and their totals;
- the next took 0.7 s, from the totals on disk;
- AAPL's Q1 2026 total (9,359,437,941 shares) matched the research.

The plan transcribes those files.

## Global Constraints

- **Keyless** (spec §4.2): no source needs an API key or an account. OpenFIGI's keyless limits are 25 requests a minute and 10 tickers a request.
- **SEC's fair access:**
  - SEC requests send the owner's contact string from `SEC_USER_AGENT`, through the shared `SecEdgar` and its rate limiter.
  - Without the contact string, only SEC collectors fail (`MissingCredential`).
- **OpenFIGI's answers stay internal.** They may be cached for our own use but not redistributed, so the repository never contains real OpenFIGI answers: the tests build OpenFIGI-shaped answers with made-up FIGIs. SEC data is public domain, so a trimmed copy of SEC's listing page is a test fixture.
- **Collector contract** (`pipeline/src/advisor/collectors/base.py`):
  - `fetch(symbols, as_of)` returns validated records or raises, and never touches the database;
  - records carry the requested symbol;
  - HTTP goes through the retry helpers, and long loops honour the run deadline.
- **Pipeline tests run only in Docker**, from `pipeline/`:
  - `scripts/in-docker.sh uv run pytest -q`;
  - `scripts/in-docker.sh uv run ruff check .`.
- **Commits:**
  - Run `git commit` in a command of its own: a plugin hook mistakes any `-n` flag in the same command (`grep -n`, `sed -n`) for `--no-verify`.
  - Never skip hooks.
  - Every commit message ends with the `Co-Authored-By:` trailer.
- **Never put a real email address** in code, tests or docs. The tests' SEC contact is `stock-advisor test@example.com`.

## Review Focus

1. **A stock no filer reported, or a ticker OpenFIGI doesn't know.** It gets no record, and the source stays healthy. Covered by Task 2, `test_symbols_get_the_latest_quarter_and_the_one_before`: BRK.B has no filer FIGIs, and ZZZZ isn't known.
2. **OpenFIGI down or rate-limiting.** Tickers already in the book keep their FIGIs, the rest are named in `PartialFetch`, and nothing wrong is saved. Covered by:
   - Task 1, `test_an_openfigi_failure_names_the_symbols_it_left_unknown_and_keeps_older_entries`;
   - Task 2, `test_an_openfigi_failure_keeps_the_symbols_it_could_match`.
3. **Amended 13F reports.** A restatement replaces its report and NEW HOLDINGS amendments add to it, so no holding is counted twice. Covered by Task 2:
   - `test_a_restatement_replaces_the_report_and_later_new_holdings_add_to_it`;
   - `test_a_data_set_totals_the_quarters_shares_per_cusip`.
4. **A damaged totals file in the cache, or the run's deadline in the middle of a 100 MB data set.** The totals are rebuilt from the data set, and the deadline stops the work cleanly. Covered by Task 2:
   - `test_damaged_totals_on_disk_are_rebuilt_from_the_data_set`;
   - `test_the_run_deadline_stops_a_long_aggregation`.
5. **SEC moves the data sets, or lists fewer than two.**
   - SEC moved them once (`structureddata` became `datastandardsinnovation`), so URLs are read from the listing, not built.
   - Fewer than two data sets is a clear error.

   Covered by Task 2, `test_the_listing_gives_the_data_sets_newest_window_first` (a trimmed real listing) and `test_a_listing_with_fewer_than_two_data_sets_fails`.

## Files

| File | Task | What it is |
|---|---|---|
| `pipeline/src/advisor/collectors/base.py` + `tests/unit/test_base.py` | 1 | `post_with_retries`, sharing the GET helper's retry loop |
| `pipeline/src/advisor/collectors/openfigi.py` + `tests/unit/test_openfigi.py` | 1 | `FigiBook`: tickers' FIGIs from OpenFIGI, kept on disk |
| `pipeline/src/advisor/collectors/sec_13f.py` + `tests/unit/test_sec_13f.py`, `tests/fixtures/sec/form13f_listing.html` | 2 | The listing, the totals per CUSIP, and the `Sec13f` collector |
| `pipeline/src/advisor/collectors/registry.py` + `tests/unit/test_registry.py` | 2 | `sec_13f` joins the registry |
| `docs/superpowers/specs/2026-10-09-stock-advisor-design.md`, `docs/superpowers/deferred.md` | 3 | Docs |

---

### Task 1: Look up tickers' FIGIs on OpenFIGI

**Files:**
- Modify: `pipeline/src/advisor/collectors/base.py`
- Create: `pipeline/src/advisor/collectors/openfigi.py`
- Test: `pipeline/tests/unit/test_base.py`, `pipeline/tests/unit/test_openfigi.py`

**Interfaces:**
- Consumes: `get_with_retries`'s retry loop, `RateLimiter`, `check_deadline` (`base.py`); `ET` (`advisor.models`).
- Produces (Task 2 uses them):
  - `post_with_retries(client, url, *, json, headers=None, limiter=None, ...) -> httpx.Response`: a POST retried like a GET. `get_with_retries` keeps its signature, and both share one loop, `_send_with_retries`.
  - In `openfigi.py`:
    - `OPENFIGI_PER_MINUTE = 25`, `JOBS_PER_REQUEST = 10`, `REFRESH = 180 days`, `RETRY = 30 days`;
    - `FIGI`, a regex for `BBG` and nine characters;
    - `openfigi_ticker(symbol)`: BRK.B becomes BRK/B;
    - `parse_mapping(payload, count) -> list[list[str]]`.
  - `FigiBook(client, path, limiter=None).lookup(symbols, as_of) -> Lookup`:
    - `Lookup` has `figis: dict[str, list[str]]` (`[]` for a ticker OpenFIGI doesn't know), `failed: list[str]` and `error: str | None`.
    - The book is a JSON file at `path`.

- [ ] **Step 1: Write the failing tests**

In `pipeline/tests/unit/test_base.py`, replace:

```python
    get_with_retries,
)
```

with:

```python
    get_with_retries,
    post_with_retries,
)
```

In `pipeline/tests/unit/test_base.py`, replace:

```python
def test_non_retryable_status_raises_immediately():
```

with:

```python
def test_a_post_sends_its_json_and_is_retried_like_a_get():
    client, calls = scripted_client([httpx.Response(429), httpx.Response(200, json=[{"data": []}])])
    sleeps = []
    response = post_with_retries(
        client, "https://example.test/map", json=[{"idValue": "AAPL"}], sleep=sleeps.append
    )
    assert response.json() == [{"data": []}]
    assert [(c.method, c.read()) for c in calls] == [("POST", b'[{"idValue":"AAPL"}]')] * 2
    assert sleeps == [1.0]


def test_non_retryable_status_raises_immediately():
```

`pipeline/tests/unit/test_openfigi.py`:

```python
import json
from datetime import UTC, datetime

import httpx
import pytest

from advisor.collectors.openfigi import FigiBook, openfigi_ticker, parse_mapping

NOW = datetime(2026, 10, 19, 14, tzinfo=UTC)


def figi(n: int) -> str:
    return f"BBG{n:09d}"


def known(ticker: str) -> dict:
    """OpenFIGI's answer for a ticker it knows, with made-up FIGIs derived from the ticker."""
    n = sum(ord(ch) for ch in ticker)
    return {"data": [{
        "ticker": ticker, "figi": figi(n), "compositeFIGI": figi(n), "shareClassFIGI": figi(n + 1),
        "securityType": "Common Stock", "marketSector": "Equity",
    }]}


def openfigi(asked, *, unknown=(), fail=False):
    """A MockTransport playing OpenFIGI: it records each request's tickers."""

    def handler(request):
        jobs = json.loads(request.read())
        asked.append([job["idValue"] for job in jobs])
        if fail:
            return httpx.Response(400, text="bad request")
        return httpx.Response(200, json=[
            {"warning": "No identifier found."} if job["idValue"] in unknown else known(job["idValue"])
            for job in jobs
        ])

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_tickers_use_openfigis_class_form():
    assert [openfigi_ticker(s) for s in ("AAPL", "BRK.B", "BF.B")] == ["AAPL", "BRK/B", "BF/B"]


def test_a_mapping_gives_each_jobs_figis_once_and_none_for_unknown_tickers():
    payload = [known("AAPL"), {"warning": "No identifier found."}]
    n = sum(ord(ch) for ch in "AAPL")
    assert parse_mapping(payload, 2) == [[figi(n), figi(n + 1)], []]
    with pytest.raises(ValueError, match="for 3 jobs"):
        parse_mapping(payload, 3)
    with pytest.raises(ValueError, match="Invalid idType"):
        parse_mapping([{"error": "Invalid idType."}], 1)


def test_tickers_are_asked_for_ten_at_a_time_and_then_kept(tmp_path):
    asked = []
    symbols = [f"T{i:02d}" for i in range(23)] + ["BRK.B"]
    with openfigi(asked) as client:
        book = FigiBook(client, tmp_path / "figis.json")
        first = book.lookup(symbols, NOW)
        again = book.lookup(symbols, NOW)
    assert [len(batch) for batch in asked] == [10, 10, 4]  # nothing asked the second time
    assert "BRK/B" in asked[-1]
    assert first.figis == again.figis and len(first.figis) == 24 and first.failed == []


def test_known_tickers_are_asked_again_after_half_a_year_and_unknown_ones_after_a_month(tmp_path):
    asked = []
    with openfigi(asked, unknown={"GONE"}) as client:
        book = FigiBook(client, tmp_path / "figis.json")
        assert book.lookup(["AAPL", "GONE"], NOW).figis["GONE"] == []
        book.lookup(["AAPL", "GONE"], NOW.replace(month=11, day=17))  # 29 days later
        book.lookup(["AAPL", "GONE"], NOW.replace(month=11, day=18))  # 30 days later
        book.lookup(["AAPL", "GONE"], datetime(2027, 4, 17, 14, tzinfo=UTC))  # 180 days later
    assert asked == [["AAPL", "GONE"], ["GONE"], ["AAPL", "GONE"]]


def test_an_openfigi_failure_names_the_symbols_it_left_unknown_and_keeps_older_entries(tmp_path):
    with openfigi([]) as client:
        FigiBook(client, tmp_path / "figis.json").lookup(["AAPL"], NOW)
    asked = []
    with openfigi(asked, fail=True) as client:
        later = FigiBook(client, tmp_path / "figis.json").lookup(["AAPL", "MSFT"], datetime(2027, 6, 1, tzinfo=UTC))
    assert asked == [["AAPL", "MSFT"]]  # AAPL was due again, and both failed
    assert list(later.figis) == ["AAPL"]  # its older FIGIs still serve
    assert later.failed == ["MSFT"]
    assert later.error.startswith("HTTPStatusError: HTTP 400")
```

- [ ] **Step 2: Run them and see them fail**

Run (from `pipeline/`): `scripts/in-docker.sh uv run pytest -q tests/unit/test_base.py tests/unit/test_openfigi.py`
Expected: `2 errors during collection`: `ImportError: cannot import name 'post_with_retries' from 'advisor.collectors.base'` and `ModuleNotFoundError: No module named 'advisor.collectors.openfigi'`.

- [ ] **Step 3: Add the POST helper**

In `pipeline/src/advisor/collectors/base.py`, replace:

```python
def get_with_retries(
    client: httpx.Client,
    url: str,
    *,
    params: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
    limiter: RateLimiter | None = None,
    attempts: int = 4,  # spec §4.1: 3 retries
    base_delay: float = 1.0,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> httpx.Response:
    """GET with exponential backoff on transport errors and 429/5xx; other errors raise at once."""
    last_error: Exception | None = None
```

with:

```python
def get_with_retries(
    client: httpx.Client,
    url: str,
    *,
    params: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
    limiter: RateLimiter | None = None,
    attempts: int = 4,  # spec §4.1: 3 retries
    base_delay: float = 1.0,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> httpx.Response:
    """GET with exponential backoff on transport errors and 429/5xx; other errors raise at once."""
    return _send_with_retries(
        client, "GET", url, params=params, headers=headers, limiter=limiter, attempts=attempts,
        base_delay=base_delay, sleep=sleep, clock=clock,
    )


def post_with_retries(
    client: httpx.Client,
    url: str,
    *,
    json: Any,
    headers: Mapping[str, str] | None = None,
    limiter: RateLimiter | None = None,
    attempts: int = 4,
    base_delay: float = 1.0,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> httpx.Response:
    """POST a JSON body, retried like `get_with_retries` (for APIs that only take POST)."""
    return _send_with_retries(
        client, "POST", url, json=json, headers=headers, limiter=limiter, attempts=attempts,
        base_delay=base_delay, sleep=sleep, clock=clock,
    )


def _send_with_retries(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    params: Mapping[str, Any] | None = None,
    json: Any = None,
    headers: Mapping[str, str] | None,
    limiter: RateLimiter | None,
    attempts: int,
    base_delay: float,
    sleep: Callable[[float], None],
    clock: Callable[[], float],
) -> httpx.Response:
    last_error: Exception | None = None
```

In `pipeline/src/advisor/collectors/base.py`, replace:

```python
            response = client.get(url, params=params, headers=headers)
```

with:

```python
            response = client.request(method, url, params=params, json=json, headers=headers)
```

- [ ] **Step 4: Write the FIGI book**

`pipeline/src/advisor/collectors/openfigi.py`:

```python
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
```

- [ ] **Step 5: Run the tests**

Run: `scripts/in-docker.sh uv run pytest -q tests/unit/test_base.py tests/unit/test_openfigi.py`
Expected: `30 passed`.

Run: `scripts/in-docker.sh uv run pytest -q`, then `scripts/in-docker.sh uv run ruff check .`
Expected: `676 passed` (670 before this plan, plus this task's six), then `All checks passed!`.

- [ ] **Step 6: Commit**

```bash
git add pipeline/src/advisor/collectors/base.py pipeline/src/advisor/collectors/openfigi.py pipeline/tests/unit/test_base.py pipeline/tests/unit/test_openfigi.py
git commit -m "feat: look up tickers' FIGIs on OpenFIGI, kept on disk"
```

---

### Task 2: Collect institutional ownership from SEC's 13F data sets

**Files:**
- Create: `pipeline/src/advisor/collectors/sec_13f.py`, `pipeline/tests/fixtures/sec/form13f_listing.html`
- Modify: `pipeline/src/advisor/collectors/registry.py`
- Test: `pipeline/tests/unit/test_sec_13f.py`, `pipeline/tests/unit/test_registry.py`

**Interfaces:**
- Consumes:
  - From Task 1: `FIGI`, `FigiBook`, `Lookup` and `OPENFIGI_PER_MINUTE` (`openfigi.py`).
  - `SecEdgar.get(url)`, which sends the contact User-Agent, rate-limits, retries and counts outages (`sec.py`).
  - `PartialFetch`, `check_deadline`, `Cadence`, `Category` and `Scope` (`base.py`).
  - `fake_sec(routes, seen=...)` (`tests/fakes.py`).
- Produces:
  - `sec_13f.py`:
    - `LISTING_URL`;
    - `parse_listing(html) -> list[DataSet]` (`name`, `url`, `end`), newest window first;
    - `sec_date("31-MAR-2026")`;
    - `counted_reports(reports) -> dict[accession, cik]`;
    - `aggregate(zipfile) -> Quarter`, with `period`, `holdings: {cusip: Holding(shares, value_usd, holders)}` and `figis: {figi: (cusip, rows)}`, plus `Quarter.cusip_for(figis)`;
    - `save_quarter(path, quarter)` and `load_quarter(path)`.
  - The collector, `Sec13f(sec, figis, folder)`:
    - `name = "sec_13f"`, FUNDAMENTALS, not core, WEEKLY;
    - SYMBOLS scope, US stocks only;
    - `freshness` 120 days, canary AAPL.
    - Its records are `InstitutionalOwnership(symbol, cusip, period, shares, value_usd, holders, previous_period, previous_shares, previous_holders)`. The two `previous_*` counts are None when no filer reported the stock the quarter before.
  - The registry builds it with `settings.cache_dir / "sec-13f"` and a FIGI book at `figis.json` there, with OpenFIGI's limiter.

- [ ] **Step 1: Write the failing tests**

`pipeline/tests/fixtures/sec/form13f_listing.html` (trimmed from SEC's page, which is public domain):

```html
<!-- Trimmed from https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets (2026-10-19): the three newest data sets and one older, quarter-named one. -->
<table>
<tbody>
<tr>
                                                                                                        <td headers="view-field-display-title-table-column" class="views-field views-field-field-display-title">  <a href="/files/datastandardsinnovation/data/form-13f-data-sets/01jun2026-31aug2026_form13f.zip" download>2026 June July August 13F</a>
            </td>
                                                                                                        <td headers="view-extension-table-column" class="views-field views-field-extension">ZIP             </td>
                                                                                                        <td headers="view-filesize-table-column" class="views-field views-field-filesize">96.05 MB            </td>
                  </tr>
<tr>
                                                                                                        <td headers="view-field-display-title-table-column" class="views-field views-field-field-display-title">  <a href="/files/structureddata/data/form-13f-data-sets/01mar2026-31may2026_form13f.zip" download>2026 March April May 13F</a>
            </td>
                                                                                                        <td headers="view-extension-table-column" class="views-field views-field-extension">ZIP             </td>
                                                                                                        <td headers="view-filesize-table-column" class="views-field views-field-filesize">94.81 MB            </td>
                  </tr>
<tr>
                                                                                                        <td headers="view-field-display-title-table-column" class="views-field views-field-field-display-title">  <a href="/files/structureddata/data/form-13f-data-sets/01dec2025-28feb2026_form13f.zip" download>2025 December 2026 January February 13F</a>
            </td>
                                                                                                        <td headers="view-extension-table-column" class="views-field views-field-extension">ZIP             </td>
                                                                                                        <td headers="view-filesize-table-column" class="views-field views-field-filesize">86.08 MB            </td>
                  </tr>
<tr>
                                                                                                        <td headers="view-field-display-title-table-column" class="views-field views-field-field-display-title">  <a href="/files/structureddata/data/form-13f-data-sets/2023q4_form13f.zip" download>2023 Q4 13F</a>
            </td>
                                                                                                        <td headers="view-extension-table-column" class="views-field views-field-extension">ZIP             </td>
                                                                                                        <td headers="view-filesize-table-column" class="views-field views-field-filesize">69.64 MB            </td>
                  </tr>
</tbody>
</table>
```

`pipeline/tests/unit/test_sec_13f.py`:

```python
import io
import json
import time
import zipfile
from datetime import UTC, date, datetime

import httpx
import pytest

from advisor.collectors.base import DeadlineExceeded, PartialFetch, deadline
from advisor.collectors.openfigi import FigiBook
from advisor.collectors.sec_13f import (
    LISTING_URL,
    DataSet,
    Holding,
    InstitutionalOwnership,
    Quarter,
    Sec13f,
    _Report,
    aggregate,
    counted_reports,
    load_quarter,
    parse_listing,
    save_quarter,
)
from fakes import fake_sec

AS_OF = datetime(2026, 10, 19, 14, tzinfo=UTC)
AAPL, MSFT, BRKB = "037833100", "594918104", "084670702"
AAPL_FIGIS = ("BBG000B9XRY4", "BBG001S5N8V8")  # composite and share class
MSFT_FIGIS = ("BBG000BPH459", "BBG001S5TD05")
BRKB_FIGIS = ("BBG000DWG505", "BBG001S90346")

SUBMISSION = ["ACCESSION_NUMBER", "FILING_DATE", "SUBMISSIONTYPE", "CIK", "PERIODOFREPORT"]
COVERPAGE = ["ACCESSION_NUMBER", "REPORTCALENDARORQUARTER", "ISAMENDMENT", "AMENDMENTNO", "AMENDMENTTYPE",
             "FILINGMANAGER_NAME", "REPORTTYPE"]
INFOTABLE = ["ACCESSION_NUMBER", "INFOTABLE_SK", "NAMEOFISSUER", "TITLEOFCLASS", "CUSIP", "FIGI", "VALUE",
             "SSHPRNAMT", "SSHPRNAMTTYPE", "PUTCALL", "INVESTMENTDISCRETION", "OTHERMANAGER",
             "VOTING_AUTH_SOLE", "VOTING_AUTH_SHARED", "VOTING_AUTH_NONE"]


def tsv(header, rows) -> str:
    return "\n".join("\t".join(r) for r in [header, *rows]) + "\n"


def data_set(submissions, amendments, holdings) -> bytes:
    """A 13F data set ZIP.

    submissions: (accession, filed, type, cik, period); amendments: accession -> type;
    holdings: (accession, cusip, figi, shares, value, kind, put_call).
    """
    covers = [
        (a, p, "Y" if a in amendments else "N", "1" if a in amendments else "", amendments.get(a, ""),
         f"Manager {c}", "13F HOLDINGS REPORT")
        for a, _, _, c, p in submissions
    ]
    infos = [
        (a, str(i), "ISSUER", "COM", cusip, figi, str(value), str(shares), kind, put_call, "SOLE", "",
         str(shares), "0", "0")
        for i, (a, cusip, figi, shares, value, kind, put_call) in enumerate(holdings)
    ]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("SUBMISSION.tsv", tsv(SUBMISSION, submissions))
        archive.writestr("COVERPAGE.tsv", tsv(COVERPAGE, covers))
        archive.writestr("INFOTABLE.tsv", tsv(INFOTABLE, infos))
    return buffer.getvalue()


def quarter_zip(period: str, aapl_shares: int, *, msft_holders: int = 1) -> bytes:
    """A plain quarter: filer 1 holds AAPL, and `msft_holders` filers hold 10 MSFT each."""
    submissions = [("0000000001-26-000001", "14-AUG-2026", "13F-HR", "0000000001", period)]
    holdings = [("0000000001-26-000001", AAPL, AAPL_FIGIS[1], aapl_shares, aapl_shares * 250, "SH", "")]
    for n in range(2, 2 + msft_holders):
        accession = f"00000000{n:02d}-26-000001"
        submissions.append((accession, "14-AUG-2026", "13F-HR", f"00000000{n:02d}", period))
        holdings.append((accession, MSFT, MSFT_FIGIS[0], 10, 5000, "SH", ""))
    return data_set(submissions, {}, holdings)


def test_the_listing_gives_the_data_sets_newest_window_first(fixtures_dir):
    html = (fixtures_dir / "sec" / "form13f_listing.html").read_text(encoding="utf-8")
    assert parse_listing(html) == [  # the quarter-named 2023q4 file isn't a window and is skipped
        DataSet(
            "01jun2026-31aug2026",
            "https://www.sec.gov/files/datastandardsinnovation/data/form-13f-data-sets/01jun2026-31aug2026_form13f.zip",
            date(2026, 8, 31),
        ),
        DataSet(
            "01mar2026-31may2026",
            "https://www.sec.gov/files/structureddata/data/form-13f-data-sets/01mar2026-31may2026_form13f.zip",
            date(2026, 5, 31),
        ),
        DataSet(
            "01dec2025-28feb2026",
            "https://www.sec.gov/files/structureddata/data/form-13f-data-sets/01dec2025-28feb2026_form13f.zip",
            date(2026, 2, 28),
        ),
    ]


def report(accession, cik, kind, day):
    return _Report(accession, cik, kind, date(2026, 8, day))


def test_a_restatement_replaces_the_report_and_later_new_holdings_add_to_it():
    counted = counted_reports([
        report("a1", "A", "13F-HR", 10), report("a2", "A", "NEW HOLDINGS", 11),  # A: both count
        report("b1", "B", "13F-HR", 10), report("b2", "B", "NEW HOLDINGS", 11),
        report("b3", "B", "RESTATEMENT", 12), report("b4", "B", "NEW HOLDINGS", 13),  # B: b3 and b4
        report("c1", "C", "13F-HR", 10), report("c2", "C", "13F-HR", 12),  # C filed twice: the latest
        report("d1", "D", "NEW HOLDINGS", 12),  # D's report was filed in another window
    ])
    assert counted == {"a1": "A", "a2": "A", "b3": "B", "b4": "B", "c2": "C"}


def test_a_data_set_totals_the_quarters_shares_per_cusip():
    archive = data_set(
        [
            ("acc-a", "10-AUG-2026", "13F-HR", "A", "30-JUN-2026"),
            ("acc-b", "11-AUG-2026", "13F-HR", "B", "30-JUN-2026"),
            ("acc-b2", "20-AUG-2026", "13F-HR/A", "B", "30-JUN-2026"),  # restates B's report
            ("acc-c", "12-AUG-2026", "13F-HR", "C", "31-MAR-2026"),  # a late report for Q1
            ("acc-d", "13-AUG-2026", "13F-NT", "D", "30-JUN-2026"),  # a notice: no holdings
        ],
        {"acc-b2": "RESTATEMENT"},
        [
            ("acc-a", AAPL, AAPL_FIGIS[1], 100, 25_000, "SH", ""),
            ("acc-a", AAPL, AAPL_FIGIS[0], 50, 12_500, "SH", ""),  # the same filer again: one holder
            ("acc-a", AAPL, "", 1_000, 1, "SH", "Call"),  # an option: left out
            ("acc-a", MSFT, "US5949181045", 7, 3_500, "SH", ""),  # an ISIN in the FIGI column: no vote
            ("acc-a", "88160RAG6", "", 5_000, 5_000, "PRN", ""),  # debt: left out
            ("acc-b", AAPL, AAPL_FIGIS[1], 999, 1, "SH", ""),  # restated away
            ("acc-b2", AAPL, AAPL_FIGIS[1], 40, 10_000, "SH", ""),
            ("acc-c", AAPL, AAPL_FIGIS[1], 70, 17_500, "SH", ""),  # another quarter
            ("acc-c", MSFT, AAPL_FIGIS[1], 70, 17_500, "SH", ""),  # a filer's wrong FIGI: outvoted
        ],
    )
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        quarter = aggregate(z)
    assert quarter.period == date(2026, 6, 30)
    assert quarter.holdings == {AAPL: Holding(190, 47_500, 2), MSFT: Holding(7, 3_500, 1)}
    assert quarter.figis == {AAPL_FIGIS[1]: (AAPL, 4), AAPL_FIGIS[0]: (AAPL, 1)}
    assert quarter.cusip_for([*AAPL_FIGIS, "BBG000NOTSEEN"]) == AAPL
    assert quarter.cusip_for(["BBG000NOTSEEN"]) is None


def test_the_run_deadline_stops_a_long_aggregation():
    with zipfile.ZipFile(io.BytesIO(quarter_zip("30-JUN-2026", 120))) as z, deadline(time.monotonic() - 1):
        with pytest.raises(DeadlineExceeded):
            aggregate(z)


def test_a_quarters_totals_survive_the_trip_to_disk(tmp_path):
    quarter = Quarter(date(2026, 6, 30), {AAPL: Holding(190, 47_500, 2)}, {AAPL_FIGIS[1]: (AAPL, 4)})
    save_quarter(tmp_path / "q.json.gz", quarter)
    assert load_quarter(tmp_path / "q.json.gz") == quarter


LATEST = "https://www.sec.gov/files/datastandardsinnovation/data/form-13f-data-sets/01jun2026-31aug2026_form13f.zip"
PREVIOUS = "https://www.sec.gov/files/structureddata/data/form-13f-data-sets/01mar2026-31may2026_form13f.zip"


def openfigi_client(asked, *, fail=False):
    figis = {"AAPL": AAPL_FIGIS, "MSFT": MSFT_FIGIS, "BRK/B": BRKB_FIGIS}

    def handler(request):
        jobs = json.loads(request.read())
        asked.append([job["idValue"] for job in jobs])
        if fail:
            return httpx.Response(400, text="bad request")
        return httpx.Response(200, json=[
            {"data": [{"figi": figis[j["idValue"]][0], "compositeFIGI": figis[j["idValue"]][0],
                       "shareClassFIGI": figis[j["idValue"]][1]}]}
            if j["idValue"] in figis else {"warning": "No identifier found."}
            for j in jobs
        ])

    return httpx.Client(transport=httpx.MockTransport(handler))


def collector(fixtures_dir, folder, seen, asked, *, fail=False):
    routes = {
        LISTING_URL: (fixtures_dir / "sec" / "form13f_listing.html").read_bytes(),
        LATEST: quarter_zip("30-JUN-2026", 120, msft_holders=3),
        PREVIOUS: quarter_zip("31-MAR-2026", 100),
    }
    figis = FigiBook(openfigi_client(asked, fail=fail), folder / "figis.json")
    return Sec13f(fake_sec(routes, seen=seen), figis, folder)


def test_symbols_get_the_latest_quarter_and_the_one_before(fixtures_dir, tmp_path):
    seen, asked = [], []
    records = collector(fixtures_dir, tmp_path, seen, asked).fetch(["AAPL", "MSFT", "BRK.B", "ZZZZ"], AS_OF)
    assert records == [
        InstitutionalOwnership(
            symbol="AAPL", cusip=AAPL, period=date(2026, 6, 30), shares=120, value_usd=30_000, holders=1,
            previous_period=date(2026, 3, 31), previous_shares=100, previous_holders=1,
        ),
        InstitutionalOwnership(
            symbol="MSFT", cusip=MSFT, period=date(2026, 6, 30), shares=30, value_usd=15_000, holders=3,
            previous_period=date(2026, 3, 31), previous_shares=10, previous_holders=1,
        ),
    ]  # no filer gave BRK.B's FIGIs, and OpenFIGI doesn't know ZZZZ
    assert asked == [["AAPL", "MSFT", "BRK/B", "ZZZZ"]]
    assert [str(r.url) for r in seen] == [LISTING_URL, LATEST, PREVIOUS]
    assert all(r.headers["User-Agent"] == "stock-advisor test@example.com" for r in seen)


def test_a_data_set_is_downloaded_once_and_old_totals_are_dropped(fixtures_dir, tmp_path):
    (tmp_path / "01sep2025-30nov2025.json.gz").write_bytes(b"an older quarter")
    seen, asked = [], []
    collector(fixtures_dir, tmp_path, seen, asked).fetch(["AAPL"], AS_OF)
    seen.clear()
    assert collector(fixtures_dir, tmp_path, seen, asked).fetch(["AAPL"], AS_OF)[0].shares == 120
    assert [str(r.url) for r in seen] == [LISTING_URL]  # the listing only
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "01jun2026-31aug2026.json.gz", "01mar2026-31may2026.json.gz", "figis.json",
    ]


def test_damaged_totals_on_disk_are_rebuilt_from_the_data_set(fixtures_dir, tmp_path):
    (tmp_path / "01jun2026-31aug2026.json.gz").write_bytes(b"cut short by a full disk")
    seen = []
    records = collector(fixtures_dir, tmp_path, seen, []).fetch(["AAPL"], AS_OF)
    assert records[0].shares == 120
    assert LATEST in [str(r.url) for r in seen]


def test_an_openfigi_failure_keeps_the_symbols_it_could_match(fixtures_dir, tmp_path):
    collector(fixtures_dir, tmp_path, [], []).fetch(["AAPL"], AS_OF)
    with pytest.raises(PartialFetch, match="OpenFIGI failed for 1 symbols") as raised:
        collector(fixtures_dir, tmp_path, [], [], fail=True).fetch(["AAPL", "MSFT"], AS_OF)
    assert [r.symbol for r in raised.value.records] == ["AAPL"]


def test_a_listing_with_fewer_than_two_data_sets_fails(tmp_path):
    sec = fake_sec({LISTING_URL: b'<a href="/files/x/01jun2026-31aug2026_form13f.zip">'})
    with pytest.raises(ValueError, match="names 1 data sets"):
        Sec13f(sec, FigiBook(openfigi_client([]), tmp_path / "figis.json"), tmp_path).fetch(["AAPL"], AS_OF)
```

In `pipeline/tests/unit/test_registry.py`, replace:

```python
    "sec_13dg": (False, Scope.SYMBOLS, True, US),
```

with:

```python
    "sec_13dg": (False, Scope.SYMBOLS, True, US),
    "sec_13f": (False, Scope.SYMBOLS, True, US),
```

- [ ] **Step 2: Run them and see them fail**

Run: `scripts/in-docker.sh uv run pytest -q tests/unit/test_sec_13f.py`
Expected: `1 error during collection`: `ModuleNotFoundError: No module named 'advisor.collectors.sec_13f'`.

Run: `scripts/in-docker.sh uv run pytest -q tests/unit/test_registry.py`
Expected: `1 failed, 2 passed`: the expected registry has `sec_13f` and the built one doesn't.

- [ ] **Step 3: Write the collector**

`pipeline/src/advisor/collectors/sec_13f.py`:

```python
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
```

- [ ] **Step 4: Run its tests**

Run: `scripts/in-docker.sh uv run pytest -q tests/unit/test_sec_13f.py`
Expected: `10 passed`.

- [ ] **Step 5: Register it**

In `pipeline/src/advisor/collectors/registry.py`, replace:

```python
from advisor.collectors.news_feeds import FEED_PER_MINUTE, FEEDS, FeedNews
```

with:

```python
from advisor.collectors.news_feeds import FEED_PER_MINUTE, FEEDS, FeedNews
from advisor.collectors.openfigi import OPENFIGI_PER_MINUTE, FigiBook
```

In `pipeline/src/advisor/collectors/registry.py`, replace:

```python
from advisor.collectors.sec import SEC_PER_MINUTE, SecEdgar
```

with:

```python
from advisor.collectors.sec import SEC_PER_MINUTE, SecEdgar
from advisor.collectors.sec_13f import Sec13f
```

In `pipeline/src/advisor/collectors/registry.py`, replace:

```python
        SecHolders(sec),
```

with:

```python
        SecHolders(sec),
        Sec13f(
            sec,
            FigiBook(
                client,
                settings.cache_dir / "sec-13f" / "figis.json",
                RateLimiter(per_minute=OPENFIGI_PER_MINUTE),
            ),
            settings.cache_dir / "sec-13f",
        ),
```

- [ ] **Step 6: Run every test**

Run: `scripts/in-docker.sh uv run pytest -q tests/unit/test_registry.py`
Expected: `3 passed`.

Run: `scripts/in-docker.sh uv run pytest -q`, then `scripts/in-docker.sh uv run ruff check .`
Expected: `686 passed`, then `All checks passed!`.

- [ ] **Step 7: Check it against SEC and OpenFIGI**

This step makes real requests, about 200 MB from SEC and two from OpenFIGI. It needs a contact string in the environment; `in-docker.sh` passes `SEC_USER_AGENT` through. Write a throwaway script, which isn't committed.

`pipeline/check_13f.py` (throwaway):

```python
"""Live check of sec_13f: run it twice; the second run reads the totals from disk."""

import os
import time
from datetime import UTC, datetime
from pathlib import Path

from advisor.collectors.base import RateLimiter, make_client
from advisor.collectors.openfigi import OPENFIGI_PER_MINUTE, FigiBook
from advisor.collectors.sec import SEC_PER_MINUTE, SecEdgar
from advisor.collectors.sec_13f import Sec13f

folder = Path(".cache-check/sec-13f")
symbols = ["AAPL", "MSFT", "BRK.B", "GOOGL", "GOOG", "TSM", "SPY", "BF.B", "ZZZZ"]
with make_client() as client:
    sec = SecEdgar(client, os.environ["SEC_USER_AGENT"], RateLimiter(per_minute=SEC_PER_MINUTE, burst=5))
    book = FigiBook(client, folder / "figis.json", RateLimiter(per_minute=OPENFIGI_PER_MINUTE))
    for attempt in (1, 2):
        started = time.perf_counter()
        records = Sec13f(sec, book, folder).fetch(symbols, datetime.now(UTC))
        print(f"run {attempt}: {time.perf_counter() - started:.1f}s, {len(records)} records")
for r in records:
    print(r.symbol, r.cusip, r.period, f"{r.shares:,}", r.holders, r.previous_period, r.previous_holders)
```

Run: `SEC_USER_AGENT="stock-advisor-dev research@example.com" scripts/in-docker.sh uv run python check_13f.py`
Expected: run 1 takes about 40 seconds (two downloads and their totals), run 2 under a second, and both give `8 records` (OpenFIGI doesn't know ZZZZ). Then one line per stock: its CUSIP, the quarter's last day, the shares and holders, and the quarter before. With the data sets published by 2026-10-19 the first line was `AAPL 037833100 2026-06-30 9,695,713,598 6112 2026-03-31 6013`; once SEC publishes the September–November data set (about mid-December) the quarters move on to 2026-09-30 and 2026-06-30.

Then delete the script and its cache: `rm -rf check_13f.py .cache-check`.

- [ ] **Step 8: Commit**

```bash
git add pipeline/src/advisor/collectors/sec_13f.py pipeline/src/advisor/collectors/registry.py pipeline/tests/fixtures/sec/form13f_listing.html pipeline/tests/unit/test_sec_13f.py pipeline/tests/unit/test_registry.py
git commit -m "feat: collect institutional ownership from SEC's 13F data sets"
```

---

### Task 3: Record what Plan 2g built

**Files:**
- Modify: `docs/superpowers/specs/2026-10-09-stock-advisor-design.md`, `docs/superpowers/deferred.md`

**Interfaces:**
- Consumes: what Tasks 1 and 2 built.
- Produces:
  - The spec's row 11 names the OpenFIGI ticker lookup.
  - `deferred.md` drops its Plan 2g section and tells Plan 3 how to use the 13F records.

- [ ] **Step 1: Update the docs**

In `docs/superpowers/specs/2026-10-09-stock-advisor-design.md`, replace:

```markdown
| 11 | fundamentals | SEC 13F data sets (+ OpenFIGI CUSIP mapping) | US | weekly | Institutional ownership change |
```

with:

```markdown
| 11 | fundamentals | SEC 13F data sets (+ OpenFIGI ticker → FIGI lookup) | US | weekly | Institutional ownership change, quarterly. Filers' FIGIs link a ticker to its CUSIP |
```

In `docs/superpowers/deferred.md`, replace:

```markdown
These are items that the Plan 1, Plan 2a, Plan 2b, Plan 2c, Plan 2d, Plan 2e and Plan 2f reviews deliberately pushed to later plans.
```

with:

```markdown
These are items that the Plan 1, Plan 2a, Plan 2b, Plan 2c, Plan 2d, Plan 2e, Plan 2f and Plan 2g reviews deliberately pushed to later plans.
```

In `docs/superpowers/deferred.md`, replace:

```markdown
## Plan 2g: 13F institutional ownership

- **Source 11 (SEC 13F data sets plus OpenFIGI CUSIP mapping) moved out of Plan 2d.** It needs a persistent CUSIP → ticker map (about 6,500 CUSIPs, roughly 27 minutes at OpenFIGI's keyless 25 requests a minute, then only new CUSIPs each quarter) and about 100 MB of quarterly SEC data sets. Research: `.superpowers/research/plan-2b/sec.md` §5. Fixtures: `.superpowers/research/plan-2c-fixtures/sec/13f_*` and `openfigi_cusip_mapping_sample.json` (git-ignored).

## Plan 2h
```

with:

```markdown
## Plan 2h
```

In `docs/superpowers/deferred.md`, replace:

```markdown
- **Benchmarks** (SPY, XIU.TO, sector ETFs) need a distinct asset type. Otherwise `upsert_symbols` deactivates them.
```

with:

```markdown
- **Benchmarks** (SPY, XIU.TO, sector ETFs) need a distinct asset type. Otherwise `upsert_symbols` deactivates them.
- **13F holder change (Plan 2g):** `sec_13f` gives each US stock the latest quarter's 13F shares, value and holder count, and the quarter before's.
  - Use changes, not levels: each quarter counts only the reports filed in its own window (late filers are left out of both), and combination reports can count a holding twice.
  - The institutional share of shares outstanding needs `sec_xbrl`'s share count.
  - The data lag: a quarter's data set appears about two and a half months after the quarter ends (Q2 ended June 30; its data set was published September 14). Treat the feature as slow-moving.
  - A stock without a record is missing, not zero: no filer reported its FIGIs (small caps, recent listings).
```

- [ ] **Step 2: Run every test**

Run: `scripts/in-docker.sh uv run pytest -q`, then `scripts/in-docker.sh uv run ruff check .`
Expected: `686 passed`, then `All checks passed!`.

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs/2026-10-09-stock-advisor-design.md docs/superpowers/deferred.md
git commit -m "docs: record the 13F collector and how Plan 3 should use it"
```
