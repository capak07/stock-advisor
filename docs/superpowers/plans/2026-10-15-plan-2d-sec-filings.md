# Stock Advisor — Plan 2d: SEC Filings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add four keyless SEC EDGAR sources for US stocks:
- XBRL company financials (#8, core);
- 8-K material events (#9);
- Form 4 insider trades (#10);
- Schedule 13D/13G large holders (#12).

They share one SEC access layer that respects SEC's fair-access rules. A missing contact setting fails only these sources, with a clear message.

**Architecture:**
- **`collectors/sec.py`** holds a `SecEdgar` object. The registry builds one per process and shares it with every SEC collector. It owns:
  - the contact User-Agent that SEC requires;
  - one rate limiter at half of SEC's 10-per-second cap;
  - the ticker → CIK map, loaded once per process;
  - one submissions fetch per company per run (the filing list the 8-K, Form 4 and 13D/G collectors all read);
  - an on-disk cache of filing documents, which never change once filed.
- **The four collectors** follow the existing `Collector` protocol and `collect_per_symbol`:
  - XBRL keeps every relevant fact with its filed date, so Plan 3 can select point-in-time values.
  - Form 4 and 13D/G download only documents they haven't seen, within a per-run document budget.
- **Tests** run against SEC responses recorded on 2026-10-12, already committed under `pipeline/tests/fixtures/sec/`. Every expected value below was produced by running this plan's code on those fixtures on 2026-10-15.

**Tech Stack:** Python 3.12, uv, httpx, pydantic v2, `xml.etree.ElementTree`, pytest, ruff, Docker.

**Spec:** `docs/superpowers/specs/2026-10-09-stock-advisor-design.md` (rev 2). Read §2 R7, §4.1 (the `MissingCredential` contract line), §4.2 sources 8–12 and the SEC note under the table, §5.1 (the Fundamentals and Ownership and flow rows), and §10. The research behind this plan is `.superpowers/research/plan-2b/sec.md`, git-ignored and local.

## Roadmap

| Plan | Delivers |
|---|---|
| 2a–2c | Done |
| **2d (this plan)** | SEC access layer, XBRL financials (core), 8-K events, Form 4 insider trades, 13D/G large holders |
| 2e | Macro, options, crypto, on-chain, catalysts, Canadian short positions |
| 2f | News and social sources, de-duplication, ticker mapping, FinBERT |
| 2g | SEC 13F institutional ownership (moved out of 2d, see below) |

## Plan-level decisions

- **`SEC_USER_AGENT` is the one data-source setting.** It is a contact string, the owner's name or app name plus an email (for example `stock-advisor you@example.com`), not a key or an account, so R7 holds.
  - Without it, or without an `@` in it, every SEC source fails at once with `MissingCredential`. No request is sent.
  - The other sources are unaffected.
  - Because `sec_xbrl` is core, the run is degraded and the daily health check emails the owner.
  - The owner sets it; code, tests and docs only ever show `you@example.com` or `test@example.com`.
- **13F moves to its own plan (2g).** Source 11 needs:
  - a persistent CUSIP → ticker map, about 6,500 CUSIPs, which takes about 27 minutes at OpenFIGI's keyless 25 requests/minute;
  - about 100 MB of quarterly SEC data sets per quarter.

  That is a different shape of work from the per-company sources here. The research and fixtures are kept for it.
- **One `SecEdgar` per process.**
  - The rate limiter is 300 per minute with a burst of 5, half the fair-access cap.
  - Submissions are fetched once per company per run and shared.
  - Documents are cached forever under `<cache dir>/sec-documents/`, which the Actions cache persists between runs.
  - A 403 (SEC's "request rate threshold exceeded" block) stops a collector's loop at once instead of failing 300 more requests.
- **XBRL financials.**
  - Fetched daily, one `companyfacts` download per company. Share classes (GOOG/GOOGL, BRK.A/BRK.B) share one download.
  - Facts from 10-K, 10-K/A, 10-Q, 10-Q/A and 10-KT, for periods ending within the last 3 years.
  - **Every** listed concept and every duplicate is kept with its `filed` date. Plan 3 picks a concept per period by priority and takes the latest filing known at `as_of` (research §2.5).
  - Facts filed after `as_of` are excluded, so a `--now` backtest sees only what was knowable.
  - 8-K XBRL facts, foreign filers (20-F, IFRS) and segment or dimensional values are out of scope.
- **Lookbacks:**
  - 8-K events: 120 days, fetched every run, since 8-Ks cluster around the close.
  - Form 4 insider trades: 90 days, daily (spec §5.1: "insider net buys over 90d").
  - 13D/13G: 365 days, daily.

  Filings dated after `as_of` are excluded.
- **Document budgets per collector call:** Form 4 1,000 and 13D/G 500.
  - A first run over the whole shortlist (thousands of documents) finishes over a few runs, holdings first.
  - Symbols cut off by the budget are left out whole and retried next run. No half-read symbol is cached.
- **13D/G scope.**
  - Only filings *about* the company count, identified by an SEC file number starting `005-`. The company's own filings about other issuers (Pfizer's 13D on Allogene, for example) are ignored.
  - Structured `SCHEDULE 13D/G` documents (from December 2024) are parsed, and their issuer CIK must match the company.
  - Legacy `SC 13D/G` filings are kept as metadata only.
- **Form 4.** A document whose issuer CIK isn't the company (the company as the reporting owner, for example Berkshire's Form 4 on Lennar) is ignored. Holdings rows without a transaction are skipped.
- **Names and roles:** `sec_xbrl` (core, DAILY), `sec_8k` (PER_RUN), `sec_form4` (DAILY), `sec_13dg` (DAILY). All are FUNDAMENTALS, US only, with canary `("AAPL",)` requiring records.
- **Rough time cost:**
  - First full run: about 2,100 SEC requests, roughly 7 minutes. They share the SEC limiter only, and run alongside Yahoo's enrichment.
  - Later pre-open runs: about 700 requests.
  - Pre-close runs: about 300, the 8-K submissions only.

## Global Constraints

- Python `>=3.12,<3.13`, managed by uv, with `uv.lock` committed. Running cost is $0/month.
- **R7:** "Free data sources only, with no API keys and no accounts." The SEC contact string is neither. Never put a real email address in code, tests or docs; use `you@example.com` and `test@example.com`.
- **Collector contract** (`collectors/base.py`):
  - Collectors never touch the database.
  - Records carry the canonical requested symbol (`BRK.B`).
  - HTTP goes through `get_with_retries`.
  - Long loops honour the run deadline.
  - `PartialFetch` is raised for per-symbol failures.
  - A collector is sent only its markets' symbols.
- **Holdings first:** symbol lists keep their priority order, and budgets are spent on holdings first.
- **Point in time (spec design rule 3):** a record is only produced if it was knowable on `as_of`'s ET date, judged by its filing date (or `filed` for XBRL).
- **Registering a source:** a registry entry and a row in `EXPECTED` in `pipeline/tests/unit/test_registry.py`.
- **Migrations:** none.
- **Tests use the committed fixtures** in `pipeline/tests/fixtures/sec/` through `fakes.fake_sec` (an `httpx.MockTransport`). No live network.
- **Tests and lint run in Docker,** from the repo root:
  - tests: `pipeline/scripts/in-docker.sh uv run pytest -q`;
  - lint: `pipeline/scripts/in-docker.sh uv run ruff check .`.
- **Stage explicit paths only.** Never bypass git hooks.
- Every commit message ends with a `Co-Authored-By:` trailer naming the model that wrote it.

## Review Focus

1. **The owner hasn't set `SEC_USER_AGENT`, or set it without an email.** Every SEC source fails at once with `MissingCredential: SEC_USER_AGENT must name you and give a contact email…`. SEC is sent no request, and every other source runs normally. *Tests: Tasks 1, 2 and 3.*
2. **A company's own filings about *other* companies.** Examples are Pfizer's 13D on Allogene and Berkshire's Form 4 on Lennar. They must never be attributed to it, and the self-filed 13D/G documents must not even be downloaded. *Tests: Tasks 5 and 6.*
3. **A backtest with `--now` in the past.** It must see only what was knowable then. XBRL facts filed later, and 8-K, Form 4 and 13D/G filings dated later, are excluded. *Tests: Tasks 3, 4, 5 and 6.*
4. **SEC blocks the IP (HTTP 403).** The collector stops after the first refusal instead of sending hundreds more. A second collector in the same run reuses the company's submissions instead of fetching them again. *Tests: Tasks 2 and 4.*
5. **The first run over a whole shortlist needs thousands of documents.** The collector stops at its document budget with the symbols done so far (PARTIAL, not FAILED, and not half a symbol). Later runs read the documents already downloaded from disk at no cost. *Tests: Tasks 5 and 6.*

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `pipeline/src/advisor/collectors/base.py` | `MissingCredential`; contract docstring line | 1 |
| `pipeline/src/advisor/config.py` | `Settings.sec_user_agent` | 1 |
| `.github/workflows/run.yml`, `health.yml`, `pipeline/scripts/in-docker.sh`, `README.md` | Pass and document `SEC_USER_AGENT` | 1 |
| `pipeline/src/advisor/collectors/sec.py` (new) | `SecEdgar`, URLs, `Filing`, parsers, `DocumentBudget`, `sec_stop` | 2 |
| `pipeline/tests/fakes.py` | `SEC_CONTACT`, `fake_sec`, `sec_routes` | 2 |
| `pipeline/src/advisor/collectors/sec_xbrl.py` (new) | Source 8, core | 3 |
| `pipeline/src/advisor/collectors/sec_events.py` (new) | Source 9 | 4 |
| `pipeline/src/advisor/collectors/sec_insiders.py` (new) | Source 10 | 5 |
| `pipeline/src/advisor/collectors/sec_holders.py` (new) | Source 12 | 6 |
| `pipeline/src/advisor/collectors/registry.py` | One `SecEdgar` and the four collectors | 3–6 |
| `docs/superpowers/deferred.md` | Plan 2d items resolved; 13F and follow-ups recorded | 6 |

---

### Task 1: The SEC contact setting

**Files:**
- Modify: `pipeline/src/advisor/collectors/base.py`, `pipeline/src/advisor/config.py`, `.github/workflows/run.yml`, `.github/workflows/health.yml`, `pipeline/scripts/in-docker.sh`, `README.md`
- Test: `pipeline/tests/unit/test_config.py`

**Interfaces:**
- Produces:
  - `base.MissingCredential(RuntimeError)`;
  - `Settings.sec_user_agent: str | None = None`, read from `SEC_USER_AGENT`, where a blank value means unset.

- [ ] **Step 1: Write the failing test**

Append to `pipeline/tests/unit/test_config.py`:

```python
def test_the_sec_contact_is_optional_and_blank_means_unset():
    assert Settings.from_env({"DATABASE_URL": "x"}).sec_user_agent is None
    assert Settings.from_env({"DATABASE_URL": "x", "SEC_USER_AGENT": ""}).sec_user_agent is None
    contact = "stock-advisor you@example.com"
    assert Settings.from_env({"DATABASE_URL": "x", "SEC_USER_AGENT": contact}).sec_user_agent == contact
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pipeline/scripts/in-docker.sh uv run pytest tests/unit/test_config.py -q`
Expected: FAIL, because `Settings` has no attribute `sec_user_agent`.

- [ ] **Step 3: Implement**

In `pipeline/src/advisor/config.py`, add the field after `cache_dir`:

```python
    sec_user_agent: str | None = None  # "<name> <email>": SEC requires a contact; not a key
```

In `from_env`, pass `sec_user_agent=env.get("SEC_USER_AGENT") or None,` after `cache_dir=...`.

In `pipeline/src/advisor/collectors/base.py`:
- add after the `PartialFetch` class:

```python
class MissingCredential(RuntimeError):
    """A source's required setting is missing: only the SEC contact string (spec §4.1)."""
```

- append this bullet to the contract list in the module docstring, after the "No source needs an API key or an account" bullet: `- SEC sources need the owner's contact string (SEC_USER_AGENT); without it they raise MissingCredential and only they fail.`

In `.github/workflows/run.yml` (step "Run pipeline") and `.github/workflows/health.yml` (step "Check sources"), add this line to the step's `env:` block, right after the `DATABASE_URL` line:

```yaml
          SEC_USER_AGENT: ${{ secrets.SEC_USER_AGENT }}
```

In `pipeline/scripts/in-docker.sh`, change the env line to:

```bash
  -e DATABASE_URL -e ADMIN_DATABASE_URL -e ADVISOR_CACHE_DIR -e SEC_USER_AGENT \
```

In `README.md`:
- replace deployment step 5's two lines with:

```markdown
5. **GitHub** (private repo): Settings → Secrets and variables → Actions. Add `DATABASE_URL`
   (the pipeline login from step 4) and `SEC_USER_AGENT`: a name plus your contact email, such
   as `stock-advisor you@example.com`. SEC requires a contact in every request; it is not an
   account or a key, and no data source needs one.
```

- change the "Manual run" line `` (`DATABASE_URL=...`): `` to `` (`DATABASE_URL=...`, `SEC_USER_AGENT=...`): ``.

- [ ] **Step 4: Run the tests and lint**

Run: `pipeline/scripts/in-docker.sh uv run pytest -q`, then `pipeline/scripts/in-docker.sh uv run ruff check .`
Expected: every test passes, and ruff reports `All checks passed!`.

- [ ] **Step 5: Commit**

```bash
git add pipeline/src/advisor/collectors/base.py pipeline/src/advisor/config.py \
  .github/workflows/run.yml .github/workflows/health.yml pipeline/scripts/in-docker.sh README.md \
  pipeline/tests/unit/test_config.py
git commit -m "feat: add the SEC contact setting and MissingCredential"
```

End the message with your `Co-Authored-By:` trailer.

---

### Task 2: Shared SEC access

**Files:**
- Create: `pipeline/src/advisor/collectors/sec.py`, `pipeline/tests/unit/test_sec.py`
- Modify: `pipeline/tests/fakes.py`

**Interfaces:**
- Consumes: `MissingCredential` (Task 1); `RateLimiter`, `check_deadline` and `get_with_retries` (base); `ET` (models).
- Produces in `advisor.collectors.sec`:
  - `SEC_PER_MINUTE = 300`;
  - `TICKERS_URL`, `SUBMISSIONS_URL` and `COMPANYFACTS_URL` (format with `cik=`), and `CONTACT_EXAMPLE`;
  - `sec_ticker(symbol)`, `archive_url(cik, accession, name)`, `true_acceptance(raw)`, `parse_tickers(payload)`, `parse_filings(payload)` and `number(text)`;
  - `Filing` (a frozen dataclass: `accession, form, filing_date, accepted_at, report_date, items, file_number, primary_document`);
  - `DocumentBudgetExhausted`, `sec_stop(exc)` and `DocumentBudget(sec, limit, kind)` with `.fetch(cik, filing) -> bytes`;
  - `SecEdgar(client, user_agent, limiter=None, *, documents=None)` with `require_contact()`, `get(url)`, `cik_for(symbol)`, `filings(cik)`, `has_document(filing)` and `document(cik, filing)`.
- Produces in `fakes`: `SEC_CONTACT`, `fake_sec(routes, *, documents=None, seen=None, user_agent=SEC_CONTACT) -> SecEdgar`, and `sec_routes(fixtures_dir) -> dict[str, bytes]`.

The fixture routes map each SEC URL to a recorded response:
- AAPL and PFE submissions; AAPL and GOOGL company facts (GOOGL served at Alphabet's CIK 1652044);
- AAPL's five recent Form 4 documents: one officer sale, one CEO multi-transaction filing, one RSU grant, and two that are really Boeing documents, standing in for filings about another issuer;
- AAPL's two Schedule 13G documents;
- the two subject 13G documents in PFE's list, which hold Apple's 13G and so fail the issuer check.

Any URL not in the table answers 404.

- [ ] **Step 1: Add the test helpers to `fakes.py`**

In `pipeline/tests/fakes.py`, add `import httpx` and `from pathlib import Path` to the imports, plus `from advisor.collectors.sec import COMPANYFACTS_URL, SUBMISSIONS_URL, TICKERS_URL, SecEdgar, archive_url`. Then append:

```python
SEC_CONTACT = "stock-advisor test@example.com"


def fake_sec(
    routes: dict[str, bytes | int],
    *,
    documents: Path | None = None,
    seen: list[httpx.Request] | None = None,
    user_agent: str | None = SEC_CONTACT,
) -> SecEdgar:
    """A SecEdgar answering from `routes` (URL -> body, or an HTTP status); other URLs get 404."""

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        answer = routes.get(str(request.url), 404)
        if isinstance(answer, int):
            return httpx.Response(answer)
        return httpx.Response(200, content=answer)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    return SecEdgar(client, user_agent, documents=documents)


def sec_routes(fixtures_dir: Path) -> dict[str, bytes]:
    """Recorded SEC answers for AAPL, PFE and GOOGL (see pipeline/tests/fixtures/sec)."""
    sec = fixtures_dir / "sec"

    def read(name: str) -> bytes:
        return (sec / name).read_bytes()

    form4 = {
        "0001140361-26-039158": "form4_sample.xml",  # officer sale under a 10b5-1 plan
        "0001140361-26-038674": "form4_sample_multi_MFSG_derivative.xml",  # CEO: M, F, S, G
        "0001140361-26-038672": "form4_sample_rsu_grant_A_derivative.xml",  # RSU grants
        "0001140361-26-038669": "form4_sample_director_open_market_buy_P.xml",  # a Boeing document
        "0001140361-26-038667": "form4_sample_director_open_market_buy_P.xml",  # a Boeing document
    }
    schedules = {
        (320193, "0002100119-26-000139"), (320193, "0000102909-26-000630"),
        (78003, "0002100119-26-001294"), (78003, "0000102909-26-002101"),  # Apple's 13G: wrong issuer
    }
    routes = {
        TICKERS_URL: read("company_tickers.json"),
        SUBMISSIONS_URL.format(cik=320193): read("submissions_AAPL_trimmed.json"),
        SUBMISSIONS_URL.format(cik=78003): read("submissions_PFE_trimmed_13dg_self_vs_subject.json"),
        COMPANYFACTS_URL.format(cik=320193): read("companyfacts_AAPL_trimmed.json"),
        COMPANYFACTS_URL.format(cik=1652044): read("companyfacts_GOOGL_trimmed.json"),
    }
    for accession, name in form4.items():
        routes[archive_url(320193, accession, "form4.xml")] = read(name)
    for cik, accession in schedules:
        routes[archive_url(cik, accession, "primary_doc.xml")] = read("schedule13g_A_sample_primary_doc.xml")
    return routes
```

- [ ] **Step 2: Write the failing tests**

Create `pipeline/tests/unit/test_sec.py`:

```python
import json
from datetime import UTC, date, datetime

import httpx
import pytest

from advisor.collectors.base import MissingCredential
from advisor.collectors.sec import (
    SUBMISSIONS_URL,
    TICKERS_URL,
    DocumentBudget,
    DocumentBudgetExhausted,
    archive_url,
    parse_filings,
    parse_tickers,
    sec_stop,
    sec_ticker,
    true_acceptance,
)
from fakes import SEC_CONTACT, fake_sec, sec_routes


def aapl_filings(fixtures_dir):
    return parse_filings(json.loads((fixtures_dir / "sec" / "submissions_AAPL_trimmed.json").read_text()))


def test_sec_tickers_use_a_hyphen_for_share_classes():
    assert sec_ticker("BRK.B") == "BRK-B"
    assert sec_ticker("aapl") == "AAPL"


def test_parse_tickers_maps_every_listed_ticker_to_its_cik(fixtures_dir):
    ciks = parse_tickers(json.loads((fixtures_dir / "sec" / "company_tickers.json").read_text()))
    assert len(ciks) == 19
    assert ciks["AAPL"] == 320193
    assert ciks["BRK-B"] == ciks["BRK-A"] == 1067983
    assert ciks["GOOG"] == ciks["GOOGL"] == 1652044


def test_true_acceptance_undoes_secs_double_eastern_shift():
    assert true_acceptance("2026-10-09T02:30:32.000Z") == datetime(2026, 10, 8, 22, 30, 32, tzinfo=UTC)
    assert true_acceptance("2026-01-30T02:30:33.000Z") == datetime(2026, 1, 29, 21, 30, 33, tzinfo=UTC)
    assert true_acceptance("") is None


def test_parse_filings_turns_secs_parallel_arrays_into_filings(fixtures_dir):
    filings = aapl_filings(fixtures_dir)
    assert len(filings) == 30
    first = filings[0]
    assert (first.accession, first.form, first.filing_date) == (
        "0001140361-26-039158", "4", date(2026, 10, 8),
    )
    assert first.accepted_at == datetime(2026, 10, 8, 22, 30, 32, tzinfo=UTC)
    assert first.report_date == date(2026, 10, 6)
    assert (first.items, first.primary_document) == ((), "xslF345X06/form4.xml")
    earnings = next(f for f in filings if f.form == "8-K")
    assert earnings.items == ("2.02", "9.01")
    assert earnings.file_number == "001-36743"


def test_requests_carry_the_contact_user_agent(fixtures_dir):
    seen: list[httpx.Request] = []
    fake_sec(sec_routes(fixtures_dir), seen=seen).cik_for("AAPL")
    assert [r.headers["User-Agent"] for r in seen] == [SEC_CONTACT]


@pytest.mark.parametrize("user_agent", [None, "", "stock-advisor"])
def test_a_missing_or_emailless_contact_fails_before_any_request(user_agent):
    seen: list[httpx.Request] = []
    with pytest.raises(MissingCredential, match="SEC_USER_AGENT must name you and give a contact email"):
        fake_sec({}, seen=seen, user_agent=user_agent).cik_for("AAPL")
    assert seen == []


def test_the_ticker_map_and_each_companys_filings_are_fetched_once(fixtures_dir):
    seen: list[httpx.Request] = []
    sec = fake_sec(sec_routes(fixtures_dir), seen=seen)
    assert [sec.cik_for(s) for s in ("AAPL", "BRK.B", "NOPE")] == [320193, 1067983, None]
    assert len(sec.filings(320193)) == 30
    assert sec.filings(320193) is sec.filings(320193)
    assert [str(r.url) for r in seen] == [TICKERS_URL, SUBMISSIONS_URL.format(cik=320193)]


def test_documents_are_fetched_once_and_kept_on_disk(fixtures_dir, tmp_path):
    filing = aapl_filings(fixtures_dir)[0]
    first_seen: list[httpx.Request] = []
    first = fake_sec(sec_routes(fixtures_dir), documents=tmp_path, seen=first_seen)
    assert not first.has_document(filing)
    body = first.document(320193, filing)
    assert body.startswith(b"<?xml")
    assert first.has_document(filing)
    assert str(first_seen[0].url) == archive_url(320193, "0001140361-26-039158", "form4.xml")
    second_seen: list[httpx.Request] = []
    second = fake_sec(sec_routes(fixtures_dir), documents=tmp_path, seen=second_seen)
    assert second.document(320193, filing) == body
    assert second_seen == []


def test_a_document_budget_counts_only_downloads(fixtures_dir, tmp_path):
    filings = [f for f in aapl_filings(fixtures_dir) if f.form == "4"]
    sec = fake_sec(sec_routes(fixtures_dir), documents=tmp_path)
    sec.document(320193, filings[0])  # already on disk: free
    budget = DocumentBudget(sec, 1, "Form 4")
    budget.fetch(320193, filings[0])
    budget.fetch(320193, filings[1])
    with pytest.raises(DocumentBudgetExhausted, match="fetched 1 Form 4 documents this run"):
        budget.fetch(320193, filings[2])


def test_sec_stop_recognises_a_missing_contact_a_block_and_a_spent_budget():
    request = httpx.Request("GET", "https://www.sec.gov/x")
    assert sec_stop(MissingCredential("x"))
    assert sec_stop(DocumentBudgetExhausted("x"))
    assert sec_stop(httpx.HTTPStatusError("x", request=request, response=httpx.Response(403)))
    assert not sec_stop(httpx.HTTPStatusError("x", request=request, response=httpx.Response(404)))
    assert not sec_stop(ValueError("x"))
```

- [ ] **Step 3: Run them to verify they fail**

Run: `pipeline/scripts/in-docker.sh uv run pytest tests/unit/test_sec.py -q`
Expected: `ModuleNotFoundError: No module named 'advisor.collectors.sec'`, raised from `fakes.py`.

- [ ] **Step 4: Implement `collectors/sec.py`**

Create `pipeline/src/advisor/collectors/sec.py`:

```python
"""Shared SEC EDGAR access for the SEC collectors (spec sources 8, 9, 10 and 12).

SEC asks every client to name itself and give a contact email in the User-Agent, and to stay
under 10 requests per second per IP (fair-access policy). One SecEdgar per process is shared by
every SEC collector: one rate limiter, one ticker -> CIK map, one submissions fetch per company per
run, and an on-disk cache of filing documents, which never change once filed.
"""

import math
import os
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import httpx

from advisor.collectors.base import MissingCredential, RateLimiter, check_deadline, get_with_retries
from advisor.models import ET

SEC_PER_MINUTE = 300  # half of SEC's 10-per-second cap, shared by every SEC collector
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
CONTACT_EXAMPLE = "stock-advisor you@example.com"


def sec_ticker(symbol: str) -> str:
    """SEC's ticker form: share classes use a hyphen (BRK.B -> BRK-B)."""
    return symbol.upper().replace(".", "-")


def archive_url(cik: int, accession: str, name: str) -> str:
    """A filing document's URL; the folder is the accession number without dashes."""
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/{name}"


def true_acceptance(raw: str) -> datetime | None:
    """SEC's acceptanceDateTime converts Eastern wall time to UTC twice; undo the second shift."""
    if not raw:
        return None
    reported = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    return reported + reported.astimezone(ET).utcoffset()


def parse_tickers(payload: Mapping[str, Any]) -> dict[str, int]:
    """SEC's company_tickers.json (an object keyed by row number) as ticker -> CIK."""
    ciks: dict[str, int] = {}
    for row in payload.values():
        ciks.setdefault(str(row["ticker"]).upper(), int(row["cik_str"]))
    return ciks


@dataclass(frozen=True)
class Filing:
    accession: str
    form: str
    filing_date: date
    accepted_at: datetime | None  # true UTC acceptance time
    report_date: date | None
    items: tuple[str, ...]  # 8-K item codes, e.g. ("2.02", "9.01")
    file_number: str  # "005-..." marks a 13D/G about this company
    primary_document: str


def parse_filings(payload: Mapping[str, Any]) -> list[Filing]:
    """The most recent filings (newest first) from a submissions document's parallel arrays."""
    recent = payload["filings"]["recent"]
    filings: list[Filing] = []
    for values in zip(*recent.values(), strict=True):
        row = dict(zip(recent, values, strict=True))
        filings.append(Filing(
            accession=row["accessionNumber"],
            form=row["form"],
            filing_date=date.fromisoformat(row["filingDate"]),
            accepted_at=true_acceptance(row.get("acceptanceDateTime") or ""),
            report_date=date.fromisoformat(row["reportDate"]) if row.get("reportDate") else None,
            items=tuple(item for item in (row.get("items") or "").split(",") if item),
            file_number=row.get("fileNumber") or "",
            primary_document=row.get("primaryDocument") or "",
        ))
    return filings


def number(text: str | None) -> float | None:
    try:
        value = float(text)  # None raises TypeError
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


class DocumentBudgetExhausted(Exception):
    """A collector downloaded its share of filing documents this run; the rest wait."""


def sec_stop(exc: Exception) -> bool:
    """Errors that end an SEC collector's loop: no contact, SEC blocking us (403), budget spent."""
    if isinstance(exc, MissingCredential | DocumentBudgetExhausted):
        return True
    return isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 403


class SecEdgar:
    """SEC access shared by every SEC collector in one process; safe to use from several threads."""

    def __init__(
        self,
        client: httpx.Client,
        user_agent: str | None,
        limiter: RateLimiter | None = None,
        *,
        documents: Path | None = None,
    ) -> None:
        self._client = client
        self._user_agent = user_agent
        self._limiter = limiter
        self._documents = documents
        self._lock = threading.Lock()
        self._ciks: dict[str, int] | None = None
        self._filings: dict[int, list[Filing]] = {}

    def require_contact(self) -> str:
        if not self._user_agent or "@" not in self._user_agent:
            raise MissingCredential(
                f"SEC_USER_AGENT must name you and give a contact email, e.g. '{CONTACT_EXAMPLE}'"
            )
        return self._user_agent

    def get(self, url: str) -> httpx.Response:
        return get_with_retries(
            self._client, url, headers={"User-Agent": self.require_contact()}, limiter=self._limiter
        )

    def cik_for(self, symbol: str) -> int | None:
        with self._lock:
            ciks = self._ciks
        if ciks is None:
            ciks = parse_tickers(self.get(TICKERS_URL).json())
            with self._lock:
                self._ciks = ciks
        return ciks.get(sec_ticker(symbol))

    def filings(self, cik: int) -> list[Filing]:
        """A company's recent filings, fetched once per process and shared by every collector."""
        with self._lock:
            known = self._filings.get(cik)
        if known is None:
            known = parse_filings(self.get(SUBMISSIONS_URL.format(cik=cik)).json())
            with self._lock:
                known = self._filings.setdefault(cik, known)
        return known

    def _document_path(self, filing: Filing) -> Path | None:
        return None if self._documents is None else self._documents / f"{filing.accession}.xml"

    def has_document(self, filing: Filing) -> bool:
        path = self._document_path(filing)
        return path is not None and path.exists()

    def document(self, cik: int, filing: Filing) -> bytes:
        """The filing's raw XML document, read from disk when it was fetched before."""
        path = self._document_path(filing)
        if path is not None and path.exists():
            return path.read_bytes()
        name = filing.primary_document.rsplit("/", 1)[-1]  # drop the xsl... rendering folder
        body = self.get(archive_url(cik, filing.accession, name)).content
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_bytes(body)
            os.replace(temporary, path)
        return body


class DocumentBudget:
    """At most `limit` document downloads per collector call; documents on disk are free."""

    def __init__(self, sec: SecEdgar, limit: int, kind: str) -> None:
        self._sec = sec
        self._limit = limit
        self._left = limit
        self._kind = kind

    def fetch(self, cik: int, filing: Filing) -> bytes:
        check_deadline()
        if not self._sec.has_document(filing):
            if self._left <= 0:
                raise DocumentBudgetExhausted(
                    f"fetched {self._limit} {self._kind} documents this run; the rest wait for the next run"
                )
            self._left -= 1
        return self._sec.document(cik, filing)
```

- [ ] **Step 5: Run the tests and lint**

Run: `pipeline/scripts/in-docker.sh uv run pytest -q`, then `pipeline/scripts/in-docker.sh uv run ruff check .`
Expected: every test passes, and ruff reports `All checks passed!`.

- [ ] **Step 6: Commit**

```bash
git add pipeline/src/advisor/collectors/sec.py pipeline/tests/fakes.py pipeline/tests/unit/test_sec.py
git commit -m "feat: add shared SEC EDGAR access with a contact UA, one limiter and a document cache"
```

End the message with your `Co-Authored-By:` trailer.

---

### Task 3: XBRL financials (source 8, core)

**Files:**
- Create: `pipeline/src/advisor/collectors/sec_xbrl.py`, `pipeline/tests/unit/test_sec_xbrl.py`
- Modify: `pipeline/src/advisor/collectors/registry.py`, `pipeline/tests/unit/test_registry.py`

**Interfaces:**
- Consumes: `SecEdgar`, `COMPANYFACTS_URL`, `sec_stop` and `SEC_PER_MINUTE` (Task 2); `collect_per_symbol` (base).
- Produces:
  - `FinancialFact(symbol, metric, concept, unit, start, end, value, filed, form, accession)`;
  - `METRICS`, `FORMS`, `LOOKBACK`;
  - `extract_facts(symbol, payload, as_of: date) -> list[FinancialFact]`;
  - `SecXbrl(sec)`, named `sec_xbrl`. It is core, DAILY, SYMBOLS and US, with freshness 14 days and canary `("AAPL",)`;
  - in the registry, a `sec` object (one `SecEdgar`) that Tasks 4–6 reuse.

- [ ] **Step 1: Write the failing tests**

Create `pipeline/tests/unit/test_sec_xbrl.py`:

```python
import json
from datetime import UTC, date, datetime

import httpx
import pytest

from advisor.collectors.base import MissingCredential
from advisor.collectors.sec_xbrl import SecXbrl, extract_facts
from advisor.models import Market
from fakes import fake_sec, sec_routes

AS_OF = datetime(2026, 10, 14, 12, 15, tzinfo=UTC)
TODAY = date(2026, 10, 14)


def companyfacts(fixtures_dir, name: str) -> dict:
    return json.loads((fixtures_dir / "sec" / f"companyfacts_{name}_trimmed.json").read_text())


def test_extract_keeps_10k_and_10q_facts_of_the_last_three_years(fixtures_dir):
    facts = extract_facts("AAPL", companyfacts(fixtures_dir, "AAPL"), TODAY)
    assert len(facts) == 148
    assert {f.metric for f in facts} == {
        "revenue", "gross_profit", "operating_income", "net_income", "eps_diluted",
        "operating_cash_flow", "capex", "long_term_debt", "long_term_debt_noncurrent",
        "commercial_paper", "equity", "diluted_shares", "shares_outstanding",
    }
    assert {f.form for f in facts} <= {"10-K", "10-K/A", "10-Q", "10-Q/A", "10-KT"}
    [quarter] = [
        f for f in facts
        if f.metric == "revenue" and (f.start, f.end) == (date(2026, 3, 29), date(2026, 6, 27))
    ]
    assert quarter.concept == "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
    assert (quarter.value, quarter.filed, quarter.form) == (109417000000.0, date(2026, 7, 31), "10-Q")
    latest_shares = max((f for f in facts if f.metric == "shares_outstanding"), key=lambda f: f.end)
    assert latest_shares.concept == "dei:EntityCommonStockSharesOutstanding"
    assert (latest_shares.start, latest_shares.end, latest_shares.value) == (
        None, date(2026, 7, 17), 14594180000.0,
    )


def test_facts_filed_after_as_of_are_left_out(fixtures_dir):
    facts = extract_facts("AAPL", companyfacts(fixtures_dir, "AAPL"), date(2026, 7, 30))
    assert len(facts) == 108
    assert max(f.filed for f in facts) == date(2026, 5, 1)


def test_fallback_concepts_cover_banks_and_multi_class_issuers(fixtures_dir):
    jpm = {(f.metric, f.concept) for f in extract_facts("JPM", companyfacts(fixtures_dir, "JPM"), TODAY)}
    assert ("revenue", "us-gaap:RevenuesNetOfInterestExpense") in jpm
    googl = extract_facts("GOOGL", companyfacts(fixtures_dir, "GOOGL"), TODAY)
    assert {f.concept for f in googl if f.metric == "shares_outstanding"} == {
        "us-gaap:CommonStockSharesOutstanding"
    }
    brk = extract_facts("BRK.B", companyfacts(fixtures_dir, "BRK_B"), TODAY)
    assert "eps_diluted" not in {f.metric for f in brk}


def test_share_classes_share_one_download(fixtures_dir):
    seen: list[httpx.Request] = []
    facts = SecXbrl(fake_sec(sec_routes(fixtures_dir), seen=seen)).fetch(["GOOG", "GOOGL", "AAPL"], AS_OF)
    assert sum("companyfacts" in str(r.url) for r in seen) == 2
    counts = {symbol: sum(f.symbol == symbol for f in facts) for symbol in ("GOOG", "GOOGL", "AAPL")}
    assert counts == {"GOOG": 15, "GOOGL": 15, "AAPL": 148}


def test_symbols_without_a_cik_or_any_xbrl_yield_no_facts(fixtures_dir):
    # NOPE has no CIK; BRK.B's company facts answer 404 in the fake.
    assert SecXbrl(fake_sec(sec_routes(fixtures_dir))).fetch(["NOPE", "BRK.B"], AS_OF) == []


def test_xbrl_is_the_core_us_fundamentals_source():
    assert SecXbrl.core is True
    assert SecXbrl.markets == frozenset({Market.US})


def test_a_missing_contact_fails_the_source():
    with pytest.raises(MissingCredential):
        SecXbrl(fake_sec({}, user_agent=None)).fetch(["AAPL"], AS_OF)
```

In `pipeline/tests/unit/test_registry.py`, add this row to `EXPECTED`:

```python
    "sec_xbrl": (True, Scope.SYMBOLS, True, US),
```

- [ ] **Step 2: Run them to verify they fail**

Run: `pipeline/scripts/in-docker.sh uv run pytest tests/unit/test_sec_xbrl.py tests/unit/test_registry.py -q`
Expected: `ModuleNotFoundError: No module named 'advisor.collectors.sec_xbrl'`, and the registry lacks `sec_xbrl`.

- [ ] **Step 3: Implement**

Create `pipeline/src/advisor/collectors/sec_xbrl.py`:

```python
"""Point-in-time financials from SEC XBRL company facts (spec source 8, core; US only).

One companyfacts download per company covers every share class. Every listed concept and every
duplicate (a value re-reported in later filings, restatements) is kept with its `filed` date, so
Plan 3 can pick a concept per period by priority and the latest value knowable on any day.
"""

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict

from advisor.collectors.base import Cadence, Category, Scope, collect_per_symbol
from advisor.collectors.sec import COMPANYFACTS_URL, SecEdgar, sec_stop
from advisor.models import ET, AssetType, Market

FORMS = frozenset({"10-K", "10-K/A", "10-Q", "10-Q/A", "10-KT"})  # 8-K XBRL is often partial
LOOKBACK = timedelta(days=3 * 365)  # 12 quarters: growth, margins and their trend
USD, PER_SHARE, SHARES = "USD", "USD/shares", "shares"
# metric -> (taxonomy, concept, unit) in priority order; companies switch concepts over time
METRICS: dict[str, tuple[tuple[str, str, str], ...]] = {
    "revenue": (
        ("us-gaap", "Revenues", USD),
        ("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax", USD),
        ("us-gaap", "RevenueFromContractWithCustomerIncludingAssessedTax", USD),
        ("us-gaap", "SalesRevenueNet", USD),
        ("us-gaap", "SalesRevenueGoodsNet", USD),
        ("us-gaap", "RevenuesNetOfInterestExpense", USD),  # banks
    ),
    "cost_of_revenue": (
        ("us-gaap", "CostOfRevenue", USD),
        ("us-gaap", "CostOfGoodsAndServicesSold", USD),
    ),
    "gross_profit": (("us-gaap", "GrossProfit", USD),),
    "operating_income": (("us-gaap", "OperatingIncomeLoss", USD),),
    "net_income": (
        ("us-gaap", "NetIncomeLoss", USD),
        ("us-gaap", "ProfitLoss", USD),
        ("us-gaap", "NetIncomeLossAvailableToCommonStockholdersBasic", USD),
    ),
    "eps_diluted": (
        ("us-gaap", "EarningsPerShareDiluted", PER_SHARE),
        ("us-gaap", "EarningsPerShareBasicAndDiluted", PER_SHARE),
    ),
    "operating_cash_flow": (  # year-to-date durations only
        ("us-gaap", "NetCashProvidedByUsedInOperatingActivities", USD),
        ("us-gaap", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations", USD),
    ),
    "capex": (
        ("us-gaap", "PaymentsToAcquirePropertyPlantAndEquipment", USD),
        ("us-gaap", "PaymentsToAcquireProductiveAssets", USD),
        ("us-gaap", "PaymentsForCapitalImprovements", USD),
    ),
    "long_term_debt": (("us-gaap", "LongTermDebt", USD),),  # total, including the current part
    "long_term_debt_noncurrent": (
        ("us-gaap", "LongTermDebtNoncurrent", USD),
        ("us-gaap", "LongTermDebtAndCapitalLeaseObligations", USD),
    ),
    "debt_current": (
        ("us-gaap", "LongTermDebtCurrent", USD),
        ("us-gaap", "DebtCurrent", USD),
    ),
    "commercial_paper": (("us-gaap", "CommercialPaper", USD),),
    "short_term_borrowings": (("us-gaap", "ShortTermBorrowings", USD),),
    "equity": (
        ("us-gaap", "StockholdersEquity", USD),
        ("us-gaap", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest", USD),
    ),
    "cash": (("us-gaap", "CashAndCashEquivalentsAtCarryingValue", USD),),
    "diluted_shares": (("us-gaap", "WeightedAverageNumberOfDilutedSharesOutstanding", SHARES),),
    "shares_outstanding": (  # multi-class issuers lack the dei cover-page count
        ("dei", "EntityCommonStockSharesOutstanding", SHARES),
        ("us-gaap", "CommonStockSharesOutstanding", SHARES),
    ),
}


class FinancialFact(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    metric: str
    concept: str  # "taxonomy:Concept", e.g. "us-gaap:Revenues"
    unit: str
    start: date | None = None  # None for balance-sheet (instant) facts
    end: date
    value: float
    filed: date  # not knowable before this day
    form: str
    accession: str


def extract_facts(symbol: str, payload: Mapping[str, Any], as_of: date) -> list[FinancialFact]:
    """Facts for METRICS from 10-K/10-Q filings, periods ending within LOOKBACK, filed by `as_of`."""
    cutoff = as_of - LOOKBACK
    facts = payload.get("facts", {})
    rows: list[FinancialFact] = []
    for metric, concepts in METRICS.items():
        for taxonomy, concept, unit in concepts:
            for fact in facts.get(taxonomy, {}).get(concept, {}).get("units", {}).get(unit, []):
                if fact.get("form") not in FORMS:
                    continue
                end, filed = date.fromisoformat(fact["end"]), date.fromisoformat(fact["filed"])
                if end < cutoff or filed > as_of:
                    continue
                rows.append(FinancialFact(
                    symbol=symbol,
                    metric=metric,
                    concept=f"{taxonomy}:{concept}",
                    unit=unit,
                    start=date.fromisoformat(fact["start"]) if "start" in fact else None,
                    end=end,
                    value=float(fact["val"]),
                    filed=filed,
                    form=fact["form"],
                    accession=fact["accn"],
                ))
    return rows


class SecXbrl:
    name = "sec_xbrl"
    category = Category.FUNDAMENTALS
    core = True
    best_effort = False
    cadence = Cadence.DAILY
    asset_types = frozenset({AssetType.STOCK})
    markets = frozenset({Market.US})
    record_type = FinancialFact
    freshness = timedelta(days=14)
    scope = Scope.SYMBOLS
    canary = ("AAPL",)
    canary_requires_records = True
    max_symbols = None

    def __init__(self, sec: SecEdgar) -> None:
        self._sec = sec

    def _companyfacts(self, cik: int) -> Mapping[str, Any] | None:
        try:
            return self._sec.get(COMPANYFACTS_URL.format(cik=cik)).json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:  # a registrant with no XBRL financials
                return None
            raise

    def fetch(self, symbols: Sequence[str], as_of: datetime) -> list[FinancialFact]:
        self._sec.require_contact()
        today = as_of.astimezone(ET).date()
        by_company: dict[int, list[FinancialFact]] = {}

        def one(symbol: str) -> list[FinancialFact]:
            cik = self._sec.cik_for(symbol)
            if cik is None:
                return []
            if cik not in by_company:  # share classes (GOOG, GOOGL) are one company
                payload = self._companyfacts(cik)
                by_company[cik] = extract_facts(symbol, payload, today) if payload else []
            return [fact.model_copy(update={"symbol": symbol}) for fact in by_company[cik]]

        return collect_per_symbol(symbols, one, is_fatal=sec_stop)
```

In `collectors/registry.py`:
- import `SEC_PER_MINUTE` and `SecEdgar` from `advisor.collectors.sec`, and `SecXbrl` from `advisor.collectors.sec_xbrl`;
- in `build_registry`, after the Yahoo limiter, add:

```python
    sec = SecEdgar(  # shared by every SEC collector
        client,
        settings.sec_user_agent,
        RateLimiter(per_minute=SEC_PER_MINUTE, burst=5),
        documents=settings.cache_dir / "sec-documents",
    )
```

- add `SecXbrl(sec),` after `BankOfCanadaValet(client),`.

- [ ] **Step 4: Run the tests and lint**

Run: `pipeline/scripts/in-docker.sh uv run pytest -q`, then `pipeline/scripts/in-docker.sh uv run ruff check .`
Expected: every test passes, and ruff reports `All checks passed!`.

- [ ] **Step 5: Commit**

```bash
git add pipeline/src/advisor/collectors/sec_xbrl.py pipeline/src/advisor/collectors/registry.py \
  pipeline/tests/unit/test_sec_xbrl.py pipeline/tests/unit/test_registry.py
git commit -m "feat: add SEC XBRL point-in-time financials as a core source"
```

End the message with your `Co-Authored-By:` trailer.

---

### Task 4: 8-K material events (source 9)

**Files:**
- Create: `pipeline/src/advisor/collectors/sec_events.py`, `pipeline/tests/unit/test_sec_events.py`
- Modify: `pipeline/src/advisor/collectors/registry.py`, `pipeline/tests/unit/test_registry.py`

**Interfaces:**
- Consumes: `SecEdgar`, `Filing` and `sec_stop` (Task 2); the registry's `sec` object (Task 3).
- Produces:
  - `MaterialEvent(symbol, accession, form, filing_date, accepted_at, report_date, items)`;
  - `EVENT_FORMS`, `LOOKBACK = timedelta(days=120)`;
  - `material_events(symbol, filings, as_of: date)`;
  - `SecEvents(sec)`, named `sec_8k`: PER_RUN, freshness 3 days, SYMBOLS, US, not core, canary `("AAPL",)` requiring records.

- [ ] **Step 1: Write the failing tests**

Create `pipeline/tests/unit/test_sec_events.py`:

```python
from datetime import UTC, date, datetime

import httpx
import pytest

from advisor.collectors.sec import TICKERS_URL
from advisor.collectors.sec_events import SecEvents
from fakes import fake_sec, sec_routes

AS_OF = datetime(2026, 10, 14, 12, 15, tzinfo=UTC)


def test_8k_filings_of_the_last_120_days_with_their_items(fixtures_dir):
    events = SecEvents(fake_sec(sec_routes(fixtures_dir))).fetch(["AAPL"], AS_OF)
    assert [(e.form, e.filing_date, e.items) for e in events] == [
        ("8-K/A", date(2026, 9, 1), ["5.02"]),
        ("8-K", date(2026, 7, 30), ["2.02", "9.01"]),
    ]
    earnings = events[1]
    assert earnings.accepted_at == datetime(2026, 7, 30, 20, 30, 28, tzinfo=UTC)  # 16:30 ET
    assert {e.symbol for e in events} == {"AAPL"}


def test_filings_dated_after_as_of_are_left_out(fixtures_dir):
    events = SecEvents(fake_sec(sec_routes(fixtures_dir))).fetch(
        ["AAPL"], datetime(2026, 8, 15, 12, 0, tzinfo=UTC)
    )
    assert [(e.form, e.filing_date) for e in events] == [
        ("8-K", date(2026, 7, 30)), ("8-K", date(2026, 4, 30)), ("8-K", date(2026, 4, 20)),
    ]


def test_a_block_stops_after_the_first_refused_request():
    seen: list[httpx.Request] = []
    sec = fake_sec({TICKERS_URL: 403}, seen=seen)  # SEC's fair-access block answers 403
    with pytest.raises(httpx.HTTPStatusError, match="HTTP 403"):
        SecEvents(sec).fetch(["AAPL", "MSFT", "NVDA"], AS_OF)
    assert len(seen) == 1


def test_two_sec_collectors_in_one_run_share_the_submissions(fixtures_dir):
    seen: list[httpx.Request] = []
    sec = fake_sec(sec_routes(fixtures_dir), seen=seen)
    SecEvents(sec).fetch(["AAPL"], AS_OF)
    SecEvents(sec).fetch(["AAPL"], AS_OF)
    assert sum("submissions" in str(r.url) for r in seen) == 1
```

In `pipeline/tests/unit/test_registry.py`, add this row to `EXPECTED`:

```python
    "sec_8k": (False, Scope.SYMBOLS, True, US),
```

- [ ] **Step 2: Run them to verify they fail**

Run: `pipeline/scripts/in-docker.sh uv run pytest tests/unit/test_sec_events.py tests/unit/test_registry.py -q`
Expected: `ModuleNotFoundError: No module named 'advisor.collectors.sec_events'`, and the registry lacks `sec_8k`.

- [ ] **Step 3: Implement**

Create `pipeline/src/advisor/collectors/sec_events.py`:

```python
"""8-K material events from each company's SEC filing list (spec source 9; US only).

The item codes say what happened: 2.02 earnings, 5.02 an officer or director change, 1.01 a
material agreement, 4.02 a restatement, and so on. Every run reads the shared submissions list;
8-K bodies are not downloaded.
"""

from collections.abc import Sequence
from datetime import date, datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field

from advisor.collectors.base import Cadence, Category, Scope, collect_per_symbol
from advisor.collectors.sec import Filing, SecEdgar, sec_stop
from advisor.models import ET, AssetType, Market

EVENT_FORMS = frozenset({"8-K", "8-K/A"})
LOOKBACK = timedelta(days=120)


class MaterialEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    accession: str
    form: str
    filing_date: date
    accepted_at: datetime | None = None  # true UTC acceptance time
    report_date: date | None = None
    items: list[str] = Field(default_factory=list)  # e.g. ["2.02", "9.01"]


def material_events(symbol: str, filings: Sequence[Filing], as_of: date) -> list[MaterialEvent]:
    cutoff = as_of - LOOKBACK
    return [
        MaterialEvent(
            symbol=symbol,
            accession=filing.accession,
            form=filing.form,
            filing_date=filing.filing_date,
            accepted_at=filing.accepted_at,
            report_date=filing.report_date,
            items=list(filing.items),
        )
        for filing in filings
        if filing.form in EVENT_FORMS and cutoff <= filing.filing_date <= as_of
    ]


class SecEvents:
    name = "sec_8k"
    category = Category.FUNDAMENTALS
    core = False
    best_effort = False
    cadence = Cadence.PER_RUN  # 8-Ks cluster around the close; read the list every run
    asset_types = frozenset({AssetType.STOCK})
    markets = frozenset({Market.US})
    record_type = MaterialEvent
    freshness = timedelta(days=3)
    scope = Scope.SYMBOLS
    canary = ("AAPL",)
    canary_requires_records = True
    max_symbols = None

    def __init__(self, sec: SecEdgar) -> None:
        self._sec = sec

    def fetch(self, symbols: Sequence[str], as_of: datetime) -> list[MaterialEvent]:
        self._sec.require_contact()
        today = as_of.astimezone(ET).date()

        def one(symbol: str) -> list[MaterialEvent]:
            cik = self._sec.cik_for(symbol)
            return [] if cik is None else material_events(symbol, self._sec.filings(cik), today)

        return collect_per_symbol(symbols, one, is_fatal=sec_stop)
```

Register it: import `SecEvents`, and add `SecEvents(sec),` after `SecXbrl(sec),`.

- [ ] **Step 4: Run the tests and lint**

Run: `pipeline/scripts/in-docker.sh uv run pytest -q`, then `pipeline/scripts/in-docker.sh uv run ruff check .`
Expected: every test passes, and ruff reports `All checks passed!`.

- [ ] **Step 5: Commit**

```bash
git add pipeline/src/advisor/collectors/sec_events.py pipeline/src/advisor/collectors/registry.py \
  pipeline/tests/unit/test_sec_events.py pipeline/tests/unit/test_registry.py
git commit -m "feat: add SEC 8-K material events"
```

End the message with your `Co-Authored-By:` trailer.

---

### Task 5: Form 4 insider trades (source 10)

**Files:**
- Create: `pipeline/src/advisor/collectors/sec_insiders.py`, `pipeline/tests/unit/test_sec_insiders.py`
- Modify: `pipeline/src/advisor/collectors/registry.py`, `pipeline/tests/unit/test_registry.py`

**Interfaces:**
- Consumes: `SecEdgar`, `Filing`, `DocumentBudget`, `DocumentBudgetExhausted`, `number` and `sec_stop` (Task 2); the registry's `sec`.
- Produces:
  - `InsiderTrade(symbol, accession, filing_date, trade_date, owners, director, officer, ten_percent_owner, officer_title, code, acquired, shares, price, owned_after, direct, derivative, planned)`;
  - `INSIDER_FORMS`, `LOOKBACK = timedelta(days=90)`, `MAX_DOCUMENTS = 1000`;
  - `parse_form4(symbol, filing, xml, cik) -> list[InsiderTrade]`;
  - `SecInsiders(sec, *, max_documents=MAX_DOCUMENTS)`, named `sec_form4`: DAILY, freshness 3 days, SYMBOLS, US, not core, canary `("AAPL",)` requiring records.

- [ ] **Step 1: Write the failing tests**

Create `pipeline/tests/unit/test_sec_insiders.py`:

```python
from datetime import UTC, date, datetime

import httpx
import pytest

from advisor.collectors.sec import DocumentBudgetExhausted, Filing
from advisor.collectors.sec_insiders import SecInsiders, parse_form4
from fakes import fake_sec, sec_routes

AS_OF = datetime(2026, 10, 14, 12, 15, tzinfo=UTC)
FILING = Filing(
    accession="0001140361-26-039158", form="4", filing_date=date(2026, 10, 8), accepted_at=None,
    report_date=None, items=(), file_number="", primary_document="xslF345X06/form4.xml",
)


def document(fixtures_dir, name: str) -> bytes:
    return (fixtures_dir / "sec" / name).read_bytes()


def test_an_officer_sale_under_a_trading_plan(fixtures_dir):
    [trade] = parse_form4("AAPL", FILING, document(fixtures_dir, "form4_sample.xml"), 320193)
    assert (trade.code, trade.acquired, trade.shares, trade.price) == ("S", False, 2399.0, 332.01)
    assert (trade.owned_after, trade.direct, trade.derivative, trade.planned) == (39593.0, True, False, True)
    assert trade.owners == ["Newstead Jennifer"]
    assert (trade.officer, trade.director, trade.officer_title) == (True, False, "SVP, GC and Government Affairs")
    assert (trade.trade_date, trade.filing_date, trade.accession) == (
        date(2026, 10, 6), date(2026, 10, 8), "0001140361-26-039158",
    )


def test_a_director_open_market_buy_with_one_zero_flags(fixtures_dir):
    [trade] = parse_form4("BA", FILING, document(fixtures_dir, "form4_sample_director_open_market_buy_P.xml"), 12927)
    assert (trade.code, trade.acquired, trade.shares, trade.price) == ("P", True, 1370.0, 218.5)
    assert (trade.director, trade.officer, trade.planned) == (True, False, False)


def test_derivative_rows_are_kept_and_marked(fixtures_dir):
    trades = parse_form4("AAPL", FILING, document(fixtures_dir, "form4_sample_multi_MFSG_derivative.xml"), 320193)
    assert [t.code for t in trades] == ["M", "F", "S", "S", "S", "S", "G", "M"]
    assert [t.derivative for t in trades] == [False] * 7 + [True]
    assert trades[0].price is None  # an exercise has no price, only a footnote
    grants = parse_form4("AAPL", FILING, document(fixtures_dir, "form4_sample_rsu_grant_A_derivative.xml"), 320193)
    assert [(t.code, t.derivative, t.price) for t in grants] == [("A", True, 0.0), ("A", True, 0.0)]


def test_a_document_about_another_issuer_is_ignored(fixtures_dir):
    boeing = document(fixtures_dir, "form4_sample_director_open_market_buy_P.xml")
    assert parse_form4("AAPL", FILING, boeing, 320193) == []


def test_fetch_reads_the_last_90_days_of_form_4s(fixtures_dir):
    seen: list[httpx.Request] = []
    trades = SecInsiders(fake_sec(sec_routes(fixtures_dir), seen=seen)).fetch(["AAPL"], AS_OF)
    assert len(trades) == 11  # 1 + 8 + 2; the two Boeing documents are ignored
    assert sorted({t.code for t in trades}) == ["A", "F", "G", "M", "S"]
    assert sum("Archives" in str(r.url) for r in seen) == 5


def test_filings_dated_after_as_of_are_left_out(fixtures_dir):
    trades = SecInsiders(fake_sec(sec_routes(fixtures_dir))).fetch(
        ["AAPL"], datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
    )
    assert len(trades) == 10  # the 2026-10-08 sale isn't filed yet
    assert "0001140361-26-039158" not in {t.accession for t in trades}


def test_documents_on_disk_cost_nothing_on_later_runs(fixtures_dir, tmp_path):
    SecInsiders(fake_sec(sec_routes(fixtures_dir), documents=tmp_path)).fetch(["AAPL"], AS_OF)
    seen: list[httpx.Request] = []
    again = SecInsiders(fake_sec(sec_routes(fixtures_dir), documents=tmp_path, seen=seen), max_documents=0)
    assert len(again.fetch(["AAPL"], AS_OF)) == 11
    assert not any("Archives" in str(r.url) for r in seen)


def test_the_document_budget_stops_the_run(fixtures_dir):
    with pytest.raises(DocumentBudgetExhausted, match="fetched 2 Form 4 documents this run"):
        SecInsiders(fake_sec(sec_routes(fixtures_dir)), max_documents=2).fetch(["AAPL"], AS_OF)
```

In `pipeline/tests/unit/test_registry.py`, add this row to `EXPECTED`:

```python
    "sec_form4": (False, Scope.SYMBOLS, True, US),
```

- [ ] **Step 2: Run them to verify they fail**

Run: `pipeline/scripts/in-docker.sh uv run pytest tests/unit/test_sec_insiders.py tests/unit/test_registry.py -q`
Expected: `ModuleNotFoundError: No module named 'advisor.collectors.sec_insiders'`, and the registry lacks `sec_form4`.

- [ ] **Step 3: Implement**

Create `pipeline/src/advisor/collectors/sec_insiders.py`:

```python
"""Insider trades from SEC Form 4 filings (spec source 10; US only).

The filing list comes from the shared submissions document; each Form 4's raw XML is downloaded
once ever (documents are cached on disk). A Form 4 in a company's list whose issuer is someone
else (the company as the reporting owner) is ignored. Codes: P open-market purchase, S sale,
A award, M exercise, F tax withholding, G gift; Plan 3 counts P and S as the signal.
"""

import xml.etree.ElementTree as ElementTree
from collections.abc import Sequence
from datetime import date, datetime, timedelta

from pydantic import BaseModel, ConfigDict

from advisor.collectors.base import Cadence, Category, Scope, collect_per_symbol
from advisor.collectors.sec import DocumentBudget, Filing, SecEdgar, number, sec_stop
from advisor.models import ET, AssetType, Market

INSIDER_FORMS = frozenset({"4", "4/A"})
LOOKBACK = timedelta(days=90)  # spec §5.1: insider net buys over 90 days
MAX_DOCUMENTS = 1000  # per run; a first run over the whole shortlist finishes on later runs


class InsiderTrade(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    accession: str
    filing_date: date
    trade_date: date
    owners: list[str]  # reporting owners ("LAST FIRST"); joint filings list several
    director: bool
    officer: bool
    ten_percent_owner: bool
    officer_title: str | None = None
    code: str
    acquired: bool  # A (acquired) vs D (disposed)
    shares: float
    price: float | None = None
    owned_after: float | None = None
    direct: bool
    derivative: bool  # options and RSUs, not common stock
    planned: bool  # filed under a Rule 10b5-1 trading plan


def _flag(node: ElementTree.Element | None) -> bool:
    return node is not None and (node.text or "").strip().lower() in {"1", "true"}


def _value(element: ElementTree.Element, path: str) -> str | None:
    node = element.find(f"{path}/value")
    text = (node.text or "").strip() if node is not None else ""
    return text or None


def parse_form4(symbol: str, filing: Filing, xml: bytes, cik: int) -> list[InsiderTrade]:
    """Transactions in a Form 4 about `cik`; a document about another issuer yields none."""
    root = ElementTree.fromstring(xml)
    issuer = (root.findtext("issuer/issuerCik") or "").strip()
    if not issuer.isdigit() or int(issuer) != cik:
        return []
    owners = root.findall("reportingOwner")
    roles = [role for o in owners if (role := o.find("reportingOwnerRelationship")) is not None]
    titles = [(role.findtext("officerTitle") or "").strip() for role in roles]
    shared = dict(
        symbol=symbol,
        accession=filing.accession,
        filing_date=filing.filing_date,
        owners=[(o.findtext("reportingOwnerId/rptOwnerName") or "").strip() for o in owners],
        director=any(_flag(role.find("isDirector")) for role in roles),
        officer=any(_flag(role.find("isOfficer")) for role in roles),
        ten_percent_owner=any(_flag(role.find("isTenPercentOwner")) for role in roles),
        officer_title=next((title for title in titles if title), None),
        planned=_flag(root.find("aff10b5One")),
    )
    trades: list[InsiderTrade] = []
    for path, derivative in (
        ("nonDerivativeTable/nonDerivativeTransaction", False),
        ("derivativeTable/derivativeTransaction", True),
    ):
        for row in root.findall(path):
            shares = number(_value(row, "transactionAmounts/transactionShares"))
            day = _value(row, "transactionDate")
            code = (row.findtext("transactionCoding/transactionCode") or "").strip()
            if shares is None or day is None or not code:
                continue
            trades.append(InsiderTrade(
                **shared,
                trade_date=date.fromisoformat(day[:10]),
                code=code,
                acquired=_value(row, "transactionAmounts/transactionAcquiredDisposedCode") == "A",
                shares=shares,
                price=number(_value(row, "transactionAmounts/transactionPricePerShare")),
                owned_after=number(_value(row, "postTransactionAmounts/sharesOwnedFollowingTransaction")),
                direct=_value(row, "ownershipNature/directOrIndirectOwnership") != "I",
                derivative=derivative,
            ))
    return trades


class SecInsiders:
    name = "sec_form4"
    category = Category.FUNDAMENTALS
    core = False
    best_effort = False
    cadence = Cadence.DAILY
    asset_types = frozenset({AssetType.STOCK})
    markets = frozenset({Market.US})
    record_type = InsiderTrade
    freshness = timedelta(days=3)
    scope = Scope.SYMBOLS
    canary = ("AAPL",)
    canary_requires_records = True
    max_symbols = None

    def __init__(self, sec: SecEdgar, *, max_documents: int = MAX_DOCUMENTS) -> None:
        self._sec = sec
        self._max_documents = max_documents

    def fetch(self, symbols: Sequence[str], as_of: datetime) -> list[InsiderTrade]:
        self._sec.require_contact()
        today = as_of.astimezone(ET).date()
        cutoff = today - LOOKBACK
        budget = DocumentBudget(self._sec, self._max_documents, "Form 4")

        def one(symbol: str) -> list[InsiderTrade]:
            cik = self._sec.cik_for(symbol)
            if cik is None:
                return []
            trades: list[InsiderTrade] = []
            for filing in self._sec.filings(cik):
                if filing.form in INSIDER_FORMS and cutoff <= filing.filing_date <= today:
                    trades.extend(parse_form4(symbol, filing, budget.fetch(cik, filing), cik))
            return trades

        return collect_per_symbol(symbols, one, is_fatal=sec_stop)
```

Register it: import `SecInsiders`, and add `SecInsiders(sec),` after `SecEvents(sec),`.

- [ ] **Step 4: Run the tests and lint**

Run: `pipeline/scripts/in-docker.sh uv run pytest -q`, then `pipeline/scripts/in-docker.sh uv run ruff check .`
Expected: every test passes, and ruff reports `All checks passed!`.

- [ ] **Step 5: Commit**

```bash
git add pipeline/src/advisor/collectors/sec_insiders.py pipeline/src/advisor/collectors/registry.py \
  pipeline/tests/unit/test_sec_insiders.py pipeline/tests/unit/test_registry.py
git commit -m "feat: add SEC Form 4 insider trades with a per-run document budget"
```

End the message with your `Co-Authored-By:` trailer.

---

### Task 6: Schedule 13D/13G large holders (source 12) and the deferred list

**Files:**
- Create: `pipeline/src/advisor/collectors/sec_holders.py`, `pipeline/tests/unit/test_sec_holders.py`
- Modify: `pipeline/src/advisor/collectors/registry.py`, `pipeline/tests/unit/test_registry.py`, `docs/superpowers/deferred.md`

**Interfaces:**
- Consumes: `SecEdgar`, `Filing`, `DocumentBudget`, `number` and `sec_stop` (Task 2); the registry's `sec`.
- Produces:
  - `ReportingPerson(name, shares, percent)`;
  - `LargeHolding(symbol, accession, form, filing_date, activist, amendment, event_date, reporting_persons)`;
  - `HOLDER_FORMS`, `SUBJECT_FILE_NUMBER = "005-"`, `LOOKBACK = timedelta(days=365)`, `MAX_DOCUMENTS = 500`;
  - `holding_header(symbol, filing)` and `parse_schedule(symbol, filing, xml, cik) -> LargeHolding | None`;
  - `SecHolders(sec, *, max_documents=MAX_DOCUMENTS)`, named `sec_13dg`: DAILY, freshness 7 days, SYMBOLS, US, not core, canary `("AAPL",)` requiring records.

- [ ] **Step 1: Write the failing tests**

Create `pipeline/tests/unit/test_sec_holders.py`:

```python
from datetime import UTC, date, datetime

import httpx
import pytest

from advisor.collectors.sec import DocumentBudgetExhausted, Filing
from advisor.collectors.sec_holders import SecHolders, parse_schedule
from fakes import fake_sec, sec_routes

AS_OF = datetime(2026, 10, 14, 12, 15, tzinfo=UTC)


def filing(form: str) -> Filing:
    return Filing(
        accession="0000102909-26-000630", form=form, filing_date=date(2026, 3, 26), accepted_at=None,
        report_date=None, items=(), file_number="005-33632", primary_document="primary_doc.xml",
    )


def document(fixtures_dir, name: str) -> bytes:
    return (fixtures_dir / "sec" / name).read_bytes()


def test_a_passive_13g_amendment(fixtures_dir):
    holding = parse_schedule(
        "AAPL", filing("SCHEDULE 13G/A"), document(fixtures_dir, "schedule13g_A_sample_primary_doc.xml"), 320193
    )
    assert (holding.activist, holding.amendment, holding.event_date) == (False, True, date(2026, 3, 13))
    assert [(p.name, p.shares, p.percent) for p in holding.reporting_persons] == [
        ("The Vanguard Group", 0.0, 0.0),  # a realignment: the successor entity reports separately
    ]


def test_an_activist_13d_amendment(fixtures_dir):
    holding = parse_schedule(
        "ALLO", filing("SCHEDULE 13D/A"), document(fixtures_dir, "schedule13d_A_sample_primary_doc.xml"), 1737287
    )
    assert (holding.activist, holding.amendment, holding.event_date) == (True, True, date(2025, 11, 6))
    assert [(p.name, p.shares, p.percent) for p in holding.reporting_persons] == [
        ("Pfizer Inc.", 22032040.0, 9.0),
    ]


def test_a_document_about_another_issuer_is_ignored(fixtures_dir):
    vanguard_on_apple = document(fixtures_dir, "schedule13g_A_sample_primary_doc.xml")
    assert parse_schedule("PFE", filing("SCHEDULE 13G/A"), vanguard_on_apple, 78003) is None


def test_only_filings_about_the_company_are_read(fixtures_dir):
    seen: list[httpx.Request] = []
    holdings = SecHolders(fake_sec(sec_routes(fixtures_dir), seen=seen)).fetch(["AAPL", "PFE"], AS_OF)
    assert [(h.symbol, h.accession, h.form) for h in holdings] == [
        ("AAPL", "0002100119-26-000139", "SCHEDULE 13G"),
        ("AAPL", "0000102909-26-000630", "SCHEDULE 13G/A"),
    ]  # PFE's two subject documents name Apple as issuer, so they're dropped
    documents = [str(r.url) for r in seen if "Archives" in str(r.url)]
    assert len(documents) == 4
    assert not any("/0000078003" in url for url in documents)  # Pfizer's own 13D/Gs on others


def test_legacy_filings_are_kept_as_metadata_only(fixtures_dir):
    seen: list[httpx.Request] = []
    holdings = SecHolders(fake_sec(sec_routes(fixtures_dir), seen=seen)).fetch(
        ["AAPL"], datetime(2024, 6, 1, 12, 0, tzinfo=UTC)
    )
    assert [(h.accession, h.form, h.reporting_persons) for h in holdings] == [
        ("0001193125-24-036431", "SC 13G/A", []),
        ("0001104659-24-020009", "SC 13G/A", []),
    ]
    assert not any("Archives" in str(r.url) for r in seen)


def test_the_document_budget_stops_the_run(fixtures_dir):
    with pytest.raises(DocumentBudgetExhausted, match="fetched 1 Schedule 13D/G documents this run"):
        SecHolders(fake_sec(sec_routes(fixtures_dir)), max_documents=1).fetch(["AAPL"], AS_OF)
```

In `pipeline/tests/unit/test_registry.py`, add this row to `EXPECTED`:

```python
    "sec_13dg": (False, Scope.SYMBOLS, True, US),
```

- [ ] **Step 2: Run them to verify they fail**

Run: `pipeline/scripts/in-docker.sh uv run pytest tests/unit/test_sec_holders.py tests/unit/test_registry.py -q`
Expected: `ModuleNotFoundError: No module named 'advisor.collectors.sec_holders'`, and the registry lacks `sec_13dg`.

- [ ] **Step 3: Implement**

Create `pipeline/src/advisor/collectors/sec_holders.py`:

```python
"""Large holders from Schedule 13D/13G filings about each company (spec source 12; US only).

Only filings about the company count: SEC files them under the company's "005-" file number. The
company's own 13D/Gs about other issuers (empty file number) are ignored. Structured SCHEDULE
13D/G documents (from December 2024) are parsed, and their issuer CIK must match; legacy SC 13D/G
filings are HTML only and kept as metadata. 13D signals possible activist or control intent.
"""

import xml.etree.ElementTree as ElementTree
from collections.abc import Sequence
from datetime import date, datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field

from advisor.collectors.base import Cadence, Category, Scope, collect_per_symbol
from advisor.collectors.sec import DocumentBudget, Filing, SecEdgar, number, sec_stop
from advisor.models import ET, AssetType, Market

HOLDER_FORMS = frozenset({
    "SCHEDULE 13D", "SCHEDULE 13D/A", "SCHEDULE 13G", "SCHEDULE 13G/A",
    "SC 13D", "SC 13D/A", "SC 13G", "SC 13G/A",  # legacy, before 2024-12-18
})
SUBJECT_FILE_NUMBER = "005-"
LOOKBACK = timedelta(days=365)
MAX_DOCUMENTS = 500  # per run; a first run over the whole shortlist finishes on later runs


class ReportingPerson(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    shares: float | None = None
    percent: float | None = None


class LargeHolding(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    accession: str
    form: str
    filing_date: date
    activist: bool  # Schedule 13D (possible control intent) rather than passive 13G
    amendment: bool
    event_date: date | None = None
    reporting_persons: list[ReportingPerson] = Field(default_factory=list)  # empty for legacy forms


def _text(root: ElementTree.Element, *names: str) -> str | None:
    """The first non-empty element with one of these names, in any namespace."""
    for name in names:
        node = root.find(f".//{{*}}{name}")
        if node is not None and (node.text or "").strip():
            return node.text.strip()
    return None


def _us_date(text: str | None) -> date | None:
    try:
        return datetime.strptime(text or "", "%m/%d/%Y").date()
    except ValueError:
        return None


def holding_header(symbol: str, filing: Filing) -> LargeHolding:
    return LargeHolding(
        symbol=symbol,
        accession=filing.accession,
        form=filing.form,
        filing_date=filing.filing_date,
        activist="13D" in filing.form,
        amendment=filing.form.endswith("/A"),
    )


def parse_schedule(symbol: str, filing: Filing, xml: bytes, cik: int) -> LargeHolding | None:
    """A structured 13D/G about `cik`, or None when the document's issuer is someone else."""
    root = ElementTree.fromstring(xml)
    issuer = _text(root, "issuerCik", "issuerCIK")  # 13G and 13D spell it differently
    if issuer is None or not issuer.isdigit() or int(issuer) != cik:
        return None
    people = root.findall(".//{*}coverPageHeaderReportingPersonDetails")  # 13G
    people += root.findall(".//{*}reportingPersonInfo")  # 13D
    persons = [
        ReportingPerson(
            name=_text(node, "reportingPersonName") or "",
            shares=number(_text(
                node, "reportingPersonBeneficiallyOwnedAggregateNumberOfShares", "aggregateAmountOwned"
            )),
            percent=number(_text(node, "classPercent", "percentOfClass")),
        )
        for node in people
    ]
    return holding_header(symbol, filing).model_copy(update={
        "event_date": _us_date(_text(root, "eventDateRequiresFilingThisStatement", "dateOfEvent")),
        "reporting_persons": persons,
    })


class SecHolders:
    name = "sec_13dg"
    category = Category.FUNDAMENTALS
    core = False
    best_effort = False
    cadence = Cadence.DAILY
    asset_types = frozenset({AssetType.STOCK})
    markets = frozenset({Market.US})
    record_type = LargeHolding
    freshness = timedelta(days=7)
    scope = Scope.SYMBOLS
    canary = ("AAPL",)
    canary_requires_records = True
    max_symbols = None

    def __init__(self, sec: SecEdgar, *, max_documents: int = MAX_DOCUMENTS) -> None:
        self._sec = sec
        self._max_documents = max_documents

    def fetch(self, symbols: Sequence[str], as_of: datetime) -> list[LargeHolding]:
        self._sec.require_contact()
        today = as_of.astimezone(ET).date()
        cutoff = today - LOOKBACK
        budget = DocumentBudget(self._sec, self._max_documents, "Schedule 13D/G")

        def one(symbol: str) -> list[LargeHolding]:
            cik = self._sec.cik_for(symbol)
            if cik is None:
                return []
            holdings: list[LargeHolding] = []
            for filing in self._sec.filings(cik):
                if (
                    filing.form not in HOLDER_FORMS
                    or not filing.file_number.startswith(SUBJECT_FILE_NUMBER)
                    or not cutoff <= filing.filing_date <= today
                ):
                    continue
                if not filing.form.startswith("SCHEDULE"):  # legacy HTML: no structured data
                    holdings.append(holding_header(symbol, filing))
                    continue
                holding = parse_schedule(symbol, filing, budget.fetch(cik, filing), cik)
                if holding is not None:
                    holdings.append(holding)
            return holdings

        return collect_per_symbol(symbols, one, is_fatal=sec_stop)
```

Register it: import `SecHolders`, and add `SecHolders(sec),` after `SecInsiders(sec),`.

- [ ] **Step 4: Update the deferred list**

In `docs/superpowers/deferred.md`:
- Change the intro sentence so it also names Plan 2d.
- Delete the whole `## Plan 2d: SEC` section; this plan resolves it.
- Add this section before `## Plan 2e`:

```markdown
## Plan 2g: 13F institutional ownership

- **Source 11 (SEC 13F data sets plus OpenFIGI CUSIP mapping) moved out of Plan 2d.** It needs a persistent CUSIP → ticker map (about 6,500 CUSIPs, roughly 27 minutes at OpenFIGI's keyless 25 requests a minute, then only new CUSIPs each quarter) and about 100 MB of quarterly SEC data sets. Research: `.superpowers/research/plan-2b/sec.md` §5. Fixtures: `.superpowers/research/plan-2c-fixtures/sec/13f_*` and `openfigi_cusip_mapping_sample.json` (git-ignored).
```

- Add these bullets under `## Plan 3: model and features`:

```markdown
- **XBRL facts are raw.** `sec_xbrl` keeps every listed concept and every re-reported or restated duplicate with its `filed` date. Features pick a concept per period by `METRICS` priority, take the latest fact filed on or before `as_of`, derive Q4 as FY minus 9M, and compute single quarters of cash-flow items from year-to-date facts (research `sec.md` §2.4–2.5).
- **Insider and holder signals.** Count only codes P and S from non-derivative rows for insider buying and selling, and treat `planned` (10b5-1) sales as weaker. For 13D/G, a 0-share 13G/A can be an index giant's entity realignment rather than an exit.
```

- Add these bullets under `## Operational and minor`:

```markdown
- **SEC document cache** (`<cache>/sec-documents/`) grows by roughly 1 MB a day of Form 4 and 13D/G XML; prune files older than 400 days.
- **XBRL bandwidth:** company facts are downloaded daily for every US symbol in the enrichment list (about 300 KB compressed each). If time or bandwidth becomes a problem, refresh a company only when its submissions show a new 10-K or 10-Q.
- **8-K bodies** (Exhibit 99.1 earnings text) are not downloaded; only the item codes are used.
```

- [ ] **Step 5: Run the tests and lint**

Run: `pipeline/scripts/in-docker.sh uv run pytest -q`, then `pipeline/scripts/in-docker.sh uv run ruff check .`
Expected: every test passes, and ruff reports `All checks passed!`.

- [ ] **Step 6: Commit**

```bash
git add pipeline/src/advisor/collectors/sec_holders.py pipeline/src/advisor/collectors/registry.py \
  pipeline/tests/unit/test_sec_holders.py pipeline/tests/unit/test_registry.py docs/superpowers/deferred.md
git commit -m "feat: add SEC Schedule 13D/G large holders; record 13F and SEC follow-ups"
```

End the message with your `Co-Authored-By:` trailer.

---

## After this plan

- **Live check:** run a health check and a forced pre-open run against a scratch database, with `SEC_USER_AGENT` set to a placeholder contact such as `stock-advisor-dev research@example.com` (never the owner's address unless they choose it).
  - All twelve sources should be `ok`.
  - Note the first run's SEC request count and time; expect about 2,100 requests and about 7 minutes.
  - The Form 4 and 13D/G document budgets may make those two sources PARTIAL on the first run, and a second run should finish them.
- **Deployment:** the owner adds the `SEC_USER_AGENT` secret in GitHub.
- **Next:** Plan 2e (macro, options, crypto, catalysts).
