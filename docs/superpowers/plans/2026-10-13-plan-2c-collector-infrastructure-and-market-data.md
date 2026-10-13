# Stock Advisor — Plan 2c: Collector Contract and Market-Data Sources Implementation Plan

> **Status: draft from before spec rev 2. Do not execute until it has been revised.** It was written as Plan 2b and renamed after spec rev 2. The revision must:
> - drop the Finnhub and FMP tasks (8–10) and every key-based credential;
> - add Yahoo earnings dates (source 17, core) and Bank of Canada FX (source 7);
> - make collectors market-aware, building on Plan 2b's `advisor.markets`;
> - keep the deadline, cadence cache, concurrent health check, contract, FINRA and Yahoo analyst tasks.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:**
- Finish the collector infrastructure that Plan 2a deferred (`docs/superpowers/deferred.md`, "Plan 2b, Task 0"):
  - a run deadline;
  - a cadence-window cache;
  - a concurrent health check;
  - the written collector contract.
- Add the six non-SEC fundamentals sources from spec §4.2:
  - FINRA short volume (#14) and short interest (#13);
  - yfinance analyst data (#16);
  - Finnhub recommendation trends (#17) and earnings (#18);
  - FMP ratios (#15).

**Architecture:**
- **Run deadline:** a context-variable deadline, which `get_with_retries` and long collector loops honour, bounds every source.
- **Cadence-window cache:** the runner serves DAILY and WEEKLY collectors from entries saved in the current ET day or ISO week, and fetches only the missing symbols. An optional per-collector `max_symbols` caps one call, so the rest wait for a later run (FMP's free plan allows 250 calls a day).
- **New sources:** each one is a single module behind the existing `Collector` protocol, with one shared rate limiter per provider. Their tests use real response fixtures, captured on 2026-10-12, under `pipeline/tests/fixtures/`.

**Tech Stack:** Python 3.12, uv, httpx, pydantic v2, pandas, yfinance, pandas-market-calendars, pytest, ruff, Postgres 16 (Docker), GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-10-09-stock-advisor-design.md`. Read §4.1, §4.2 (sources 13–18) and §10.
- Research notes are in `.superpowers/research/plan-2b/` (finra.md, finnhub_fmp.md, yfinance_analyst.md); they're git-ignored, so read them locally.
- The work deferred to this plan is in `docs/superpowers/deferred.md`.

## Roadmap update

| Plan | Delivers |
|---|---|
| **2b (this plan)** | Deadline, cadence cache, concurrent health check, collector contract, plus FINRA ×2, yfinance analyst, Finnhub ×2 and FMP |
| 2b-SEC (next) | SEC XBRL financials, 8-K, Form 4, 13F (quarterly data sets plus CUSIP mapping), 13D/G. The research is already in `.superpowers/research/plan-2b/sec.md`, with fixtures in `pipeline/tests/fixtures/sec/` |
| 2c | Macro, options, crypto, on-chain and catalyst sources |
| 2d | News and social sources, de-duplication and FinBERT |

## Global Constraints

- Python `>=3.12,<3.13`, managed by uv. Running cost is $0/month: free tiers only.
- **Provider terms:** Finnhub and FMP free tiers are for personal, non-commercial use only. Never redistribute their data.
- **Tests run in the Linux container:** `scripts/in-docker.sh uv run pytest ...`. Windows Application Control blocks psycopg's DLLs on the host.
- **Lint runs on the host:** `uv run --no-sync ruff check --fix .`. A `uv` re-sync can fail with "Access is denied" under OneDrive.
- Run all commands from `stock-advisor/pipeline/` unless a step says otherwise.
- **Collector contract** (Task 2 writes it into `collectors/base.py`):
  - Collectors never touch the database.
  - SYMBOLS-scope records have `symbol` equal to the canonical requested symbol (`BRK.B`). Provider formats such as `BRK/B`, `BRKB` and `BRK-B` are mapped inside the collector.
  - Collectors raise `PartialFetch` for per-request failures.
  - Long loops call `check_deadline()`.
  - HTTP goes through `get_with_retries`.
- **API keys:**
  - Send them in headers where the provider supports it (Finnhub: `X-Finnhub-Token`).
  - FMP only accepts a query parameter, so pass it via `params=`. Error text uses query-free URLs (Plan 2a F4).
  - Keys come only from environment variables or GitHub secrets.
  - A missing key fails only that source, with `MissingCredential: <ENV_NAME> is not set`.
- **Holdings first:** the runner passes symbols with priority first, and collectors keep that order.
- **Registering a source:** every new source gets a registry entry and a row in the registry test table `EXPECTED`.
- **Migrations are append-only.** This plan needs none.
- Every commit message ends with a `Co-Authored-By:` trailer naming the model that actually wrote the commit. Never bypass git hooks.

## Review Focus

1. **A missing or wrong API key** must fail only that source, with a clear message. It must not crash the run, stall it, or put the key in any stored text. Tested in Tasks 2, 8 and 10.
2. **FMP's daily cap:** symbols beyond `max_symbols` must not be marked as fetched for the window. They're served from older cache and fetched on a later run. Tested in Tasks 3 and 10.
3. **Provider symbol formats** (`BRK/B` in FINRA's volume file, `BRKB` in its short-interest file, `BRK-B` at Yahoo) must come back as `BRK.B`. Tested in Tasks 5, 6 and 7.
4. **A FINRA file that isn't published yet** (HTTP 403 on the run day, a weekend or a holiday) must fall back to the newest published file, not fail. Tested in Tasks 5 and 6.
5. **A slow source past the run budget** must end as a failed or partial source while the run still publishes. Tested in Tasks 1 and 7.

---

## File Structure

```
pipeline/src/advisor/
  collectors/base.py       MOD  deadline, DeadlineExceeded, check_deadline, MissingCredential, require,
                                collect_per_symbol, contract docstring, protocol attr max_symbols
  collectors/cache.py      MOD  DiskCache.get_entry
  collectors/runner.py     MOD  cadence windows, empty markers, max_symbols, partial backfill, use_window
  collectors/tracker.py    MOD  deadline_at
  collectors/registry.py   MOD  six new sources, shared Finnhub limiter
  collectors/finra_short_volume.py, finra_short_interest.py, yfinance_analyst.py,
  collectors/finnhub.py (shared helpers), finnhub_recommendations.py, finnhub_earnings.py, fmp_ratios.py   NEW
  symbols.py               NEW  provider-neutral symbol keys
  config.py                MOD  optional FINNHUB_API_KEY, FMP_API_KEY, SEC_USER_AGENT
  health.py                MOD  concurrent checks, per-source budget, rows written as they finish
  run.py                   MOD  run budget
pipeline/tests/fixtures/{finra,finnhub,fmp,yfinance_analyst}/   EXIST (untracked) — commit them with their task
.github/workflows/run.yml, health.yml   MOD  new secrets
pipeline/scripts/in-docker.sh           MOD  forward new env vars
README.md                               MOD  data-source keys
```

---

### Task 1: Run deadline

**Files:**
- Modify: `pipeline/src/advisor/collectors/base.py`, `pipeline/src/advisor/collectors/tracker.py`, `pipeline/src/advisor/run.py`
- Test: `pipeline/tests/unit/test_base.py`, `pipeline/tests/unit/test_tracker.py`, `pipeline/tests/integration/test_run.py`

**Interfaces:**
- Produces:
  - In `base`:
    - `DeadlineExceeded(Exception)`;
    - `deadline(at: float | None)`, a context manager;
    - `time_left(clock=time.monotonic) -> float | None`;
    - `check_deadline(clock=time.monotonic) -> None`;
    - `get_with_retries(..., clock=time.monotonic)`, which stops before a request or a retry wait that would overrun the deadline.
  - `SourceTracker(..., *, deadline_at: float | None = None)`.
  - `run.RUN_BUDGET_SECONDS = 30 * 60` and `execute_run(..., run_budget: float = RUN_BUDGET_SECONDS)`.

- [ ] **Step 1: Write the failing tests**

Append to `pipeline/tests/unit/test_base.py`. Add `DeadlineExceeded`, `check_deadline` and `deadline` to its `advisor.collectors.base` import, and `FakeClock` to its `fakes` import:
```python
def test_check_deadline_is_a_no_op_without_a_deadline():
    check_deadline()


def test_deadline_applies_only_inside_its_block():
    clock = FakeClock()
    clock.now = 100.0
    with deadline(50.0):
        with pytest.raises(DeadlineExceeded):
            check_deadline(clock)
    check_deadline(clock)


def test_requests_stop_once_the_deadline_has_passed():
    client, calls = scripted_client([httpx.Response(200, text="ok")])
    clock = FakeClock()
    clock.now = 10.0
    with deadline(5.0), pytest.raises(DeadlineExceeded):
        get_with_retries(client, "https://example.test/x", clock=clock, sleep=clock.sleep)
    assert calls == []


def test_a_retry_wait_that_would_overrun_the_deadline_stops_early():
    client, calls = scripted_client([httpx.Response(503), httpx.Response(200, text="ok")])
    clock = FakeClock()
    with deadline(0.5), pytest.raises(DeadlineExceeded) as caught:
        get_with_retries(
            client, "https://example.test/x?token=SECRET", clock=clock, sleep=clock.sleep
        )
    assert len(calls) == 1
    assert clock.sleeps == []
    assert "SECRET" not in str(caught.value)


def test_a_retry_that_fits_the_deadline_still_happens():
    client, _ = scripted_client([httpx.Response(503), httpx.Response(200, text="ok")])
    clock = FakeClock()
    with deadline(1.5):
        response = get_with_retries(client, "https://example.test/x", clock=clock, sleep=clock.sleep)
    assert response.text == "ok"
    assert clock.sleeps == [1.0]
```

Append to `pipeline/tests/unit/test_tracker.py`. Add `import time` and `from advisor.collectors.base import check_deadline` to its imports:
```python
def test_tracker_applies_its_deadline_to_every_call(tmp_path):
    slow = FakeCollector("slow", records_for=lambda syms: (check_deadline(), [])[1])
    tracker = SourceTracker(
        {"slow": slow}, DiskCache(tmp_path), NOW, {}, deadline_at=time.monotonic() - 1
    )
    result = tracker.run("slow", ["AAA"])
    assert result.status is CollectorStatus.FAILED
    assert result.error == "DeadlineExceeded: run time budget exhausted"
```

Append to `pipeline/tests/integration/test_run.py`. Add `from advisor.collectors.base import check_deadline` to its imports:
```python
def test_a_source_past_the_run_budget_fails_and_the_run_still_publishes(db, tmp_path):
    extra = {
        "slow": FakeCollector("slow", core=False, records_for=lambda syms: (check_deadline(), [])[1])
    }
    outcome = execute_run(
        make_deps(db, tmp_path, extra=extra), RunKind.PRE_OPEN, NOW, min_universe=3, run_budget=0
    )
    assert outcome.status is RunStatus.SUCCESS  # the price fakes never consult the deadline
    assert ("slow", "failed") in health(db, outcome.run_id)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `scripts/in-docker.sh uv run pytest tests/unit/test_base.py tests/unit/test_tracker.py tests/integration/test_run.py -v`
Expected: ImportError for `DeadlineExceeded`, `check_deadline` and `deadline`.

- [ ] **Step 3: Implement the deadline in `base.py`**

Add `import contextlib` and `from contextvars import ContextVar` to the imports. Change the `collections.abc` import to `from collections.abc import Callable, Iterator, Mapping, Sequence`.

Add after the `PartialFetch` class:
```python
_DEADLINE: ContextVar[float | None] = ContextVar("collector_deadline", default=None)


class DeadlineExceeded(Exception):
    """The run's time budget ran out before this source finished."""


@contextlib.contextmanager
def deadline(at: float | None) -> Iterator[None]:
    """Inside this block, collectors stop once time.monotonic() passes `at` (None = no limit)."""
    token = _DEADLINE.set(at)
    try:
        yield
    finally:
        _DEADLINE.reset(token)


def time_left(clock: Callable[[], float] = time.monotonic) -> float | None:
    """Seconds until the current deadline, or None when there is none."""
    at = _DEADLINE.get()
    return None if at is None else at - clock()


def check_deadline(clock: Callable[[], float] = time.monotonic) -> None:
    """Raise DeadlineExceeded once the current deadline has passed; long loops call this per item."""
    left = time_left(clock)
    if left is not None and left <= 0:
        raise DeadlineExceeded("run time budget exhausted")
```

In `get_with_retries`:
- add the parameter `clock: Callable[[], float] = time.monotonic` after `sleep`;
- at the top of the loop body, right after `retry_after: float | None = None`, insert:
```python
        check_deadline(clock)
        if limiter is not None:
            limiter.acquire()
            check_deadline(clock)  # a busy shared limiter may have slept past the deadline
```
  and delete the old `if limiter is not None: limiter.acquire()` lines;
- replace the end-of-loop wait block with:
```python
        if attempt < attempts - 1:
            backoff = base_delay * 2**attempt
            wait = backoff if retry_after is None else max(backoff, retry_after)
            left = time_left(clock)
            if left is not None and wait >= left:
                raise DeadlineExceeded(
                    f"run time budget exhausted while retrying {_safe_url(url)}"
                ) from last_error
            sleep(wait)
```

- [ ] **Step 4: Apply the deadline in the tracker and the orchestrator**

In `collectors/tracker.py`:
- import `deadline` from `advisor.collectors.base`;
- add the keyword-only parameter `deadline_at: float | None = None` to `__init__`, after `states` (put `*,` before it), and store it as `self._deadline_at`;
- in `run`, wrap the `run_collector(...)` call: `with deadline(self._deadline_at):` inside the existing `try`.

In `run.py`:
- add `import time`;
- add the constant `RUN_BUDGET_SECONDS = 30 * 60  # GitHub kills the job at 40 minutes` next to `MIN_PRICED_FRACTION`;
- add the keyword-only parameter `run_budget: float = RUN_BUDGET_SECONDS` to `execute_run`;
- pass `deadline_at=time.monotonic() + run_budget` to `SourceTracker(...)`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `scripts/in-docker.sh uv run pytest tests/unit/test_base.py tests/unit/test_tracker.py tests/integration/test_run.py -v`, then the full suite.
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
uv run --no-sync ruff check --fix .
git add src/advisor/collectors/base.py src/advisor/collectors/tracker.py src/advisor/run.py tests/unit/test_base.py tests/unit/test_tracker.py tests/integration/test_run.py
git commit -m "feat: bound every source by a run deadline"
```
End the message with your `Co-Authored-By:` trailer.

---

### Task 2: Collector contract, credentials, and per-symbol collection

**Files:**
- Modify: `pipeline/src/advisor/collectors/base.py`, `pipeline/src/advisor/config.py`, `.github/workflows/run.yml`, `.github/workflows/health.yml`, `pipeline/scripts/in-docker.sh`, `README.md`
- Test: `pipeline/tests/unit/test_base.py`, `pipeline/tests/unit/test_config.py`

**Interfaces:**
- Consumes: `check_deadline` and `DeadlineExceeded` (Task 1), and `PartialFetch`
- Produces:
  - In `base`:
    - `MissingCredential(RuntimeError)`;
    - `require(value: str | None, env_name: str) -> str`;
    - `collect_per_symbol(symbols, fetch_one, *, is_fatal=..., pause=None) -> list[BaseModel]`.
  - `Settings` fields `finnhub_api_key: str | None`, `fmp_api_key: str | None` and `sec_user_agent: str | None` (all default `None`; a blank env value counts as unset).

- [ ] **Step 1: Write the failing tests**

Append to `pipeline/tests/unit/test_config.py`, which already defines `FULL`:
```python
def test_source_credentials_default_to_none():
    settings = Settings.from_env(FULL)
    assert (settings.finnhub_api_key, settings.fmp_api_key, settings.sec_user_agent) == (
        None, None, None,
    )


def test_source_credentials_are_read_and_blank_means_unset():
    settings = Settings.from_env({
        **FULL,
        "FINNHUB_API_KEY": "fk-123",
        "FMP_API_KEY": "",
        "SEC_USER_AGENT": "stock-advisor me@example.com",
    })
    assert settings.finnhub_api_key == "fk-123"
    assert settings.fmp_api_key is None
    assert settings.sec_user_agent == "stock-advisor me@example.com"


def test_repr_hides_source_keys():
    settings = Settings.from_env({**FULL, "FINNHUB_API_KEY": "fk-SECRET-1", "FMP_API_KEY": "fmp-SECRET-2"})
    assert "fk-SECRET-1" not in repr(settings)
    assert "fmp-SECRET-2" not in repr(settings)
```

Append to `pipeline/tests/unit/test_base.py`. Add `MissingCredential`, `PartialFetch`, `collect_per_symbol` and `require` to the base import, and `info` to the fakes import:
```python
def test_require_returns_the_value_or_names_the_missing_setting():
    assert require("abc", "FMP_API_KEY") == "abc"
    for missing in (None, ""):
        with pytest.raises(MissingCredential, match="FMP_API_KEY is not set"):
            require(missing, "FMP_API_KEY")


def test_collect_per_symbol_fetches_each_symbol_once_in_order():
    seen, pauses = [], []

    def one(symbol):
        seen.append(symbol)
        return [info(symbol)]

    records = collect_per_symbol(["A", "B", "A", "C"], one, pause=lambda: pauses.append(1))
    assert seen == ["A", "B", "C"]
    assert [r.symbol for r in records] == ["A", "B", "C"]
    assert len(pauses) == 2


def test_collect_per_symbol_turns_symbol_failures_into_a_partial_result():
    def one(symbol):
        if symbol == "B":
            raise ValueError("bad row")
        return [info(symbol)]

    with pytest.raises(PartialFetch, match="1 of 3 symbols failed; first: B: ValueError: bad row") as caught:
        collect_per_symbol(["A", "B", "C"], one)
    assert [r.symbol for r in caught.value.records] == ["A", "C"]


def test_a_fatal_error_before_any_record_is_raised_as_is():
    def one(symbol):
        raise MissingCredential("FINNHUB_API_KEY is not set")

    with pytest.raises(MissingCredential):
        collect_per_symbol(["A", "B"], one, is_fatal=lambda exc: isinstance(exc, MissingCredential))


def test_a_fatal_error_after_some_records_stops_with_a_partial_result():
    calls = []

    def one(symbol):
        calls.append(symbol)
        if symbol == "B":
            raise RuntimeError("rate limited")
        return [info(symbol)]

    with pytest.raises(PartialFetch, match="stopped after 1 of 3 symbols") as caught:
        collect_per_symbol(["A", "B", "C"], one, is_fatal=lambda exc: isinstance(exc, RuntimeError))
    assert calls == ["A", "B"]
    assert [r.symbol for r in caught.value.records] == ["A"]


def test_the_run_deadline_stops_the_loop_like_a_fatal_error():
    def one(symbol):
        if symbol == "B":
            raise DeadlineExceeded("run time budget exhausted")
        return [info(symbol)]

    with pytest.raises(PartialFetch, match="stopped after 1 of 3 symbols"):
        collect_per_symbol(["A", "B", "C"], one)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `scripts/in-docker.sh uv run pytest tests/unit/test_base.py tests/unit/test_config.py -v`
Expected: ImportError for `MissingCredential`, and `Settings` has no `finnhub_api_key`.

- [ ] **Step 3: Write the contract and helpers in `base.py`**

Replace the module docstring of `collectors/base.py` with:
```python
"""Shared building blocks for collectors: the interface, rate limiting, HTTP retries, deadlines.

Collector contract (every source module follows it):
- `fetch(symbols, as_of)` returns validated records or raises; it never touches the database.
- SYMBOLS scope: every record has `symbol` equal to the canonical requested symbol ("BRK.B");
  map provider formats ("BRK/B", "BRKB", "BRK-B") in and out inside the collector.
- Raise PartialFetch(records, error) when some requests failed but others succeeded; an empty
  PartialFetch counts as a failure. `collect_per_symbol` does this for per-symbol APIs.
- HTTP goes through `get_with_retries`: it honours the run deadline, backs off on 429/5xx, and
  never puts query strings (where some providers require API keys) into error text.
- Long loops call `check_deadline()` between items.
- Prefer header auth. A provider that only accepts a query-param key gets it via `params=`.
- A missing key raises MissingCredential via `require(value, "ENV_NAME")`, failing only that source.
- `canary_requires_records` is True only for sources that always return data for their canary.
- DAILY/WEEKLY collectors with `freshness` are served from this window's cache, and only missing
  symbols are fetched; `max_symbols` caps one call (see runner).
"""
```

Add after `check_deadline`:
```python
class MissingCredential(RuntimeError):
    """A source's API key or contact setting is not configured."""


def require(value: str | None, env_name: str) -> str:
    """Return a configured credential, or fail this source with a clear message."""
    if not value:
        raise MissingCredential(f"{env_name} is not set")
    return value


def collect_per_symbol(
    symbols: Sequence[str],
    fetch_one: Callable[[str], Sequence[BaseModel]],
    *,
    is_fatal: Callable[[Exception], bool] = lambda exc: False,
    pause: Callable[[], None] | None = None,
) -> list[BaseModel]:
    """Fetch symbol by symbol (each once, in order), keeping going past per-symbol failures.

    Failures for single symbols end in PartialFetch with everything else. A fatal error (as
    judged by `is_fatal`) or the run deadline stops the loop: it is re-raised as-is when nothing
    was collected yet, otherwise it becomes PartialFetch with the records so far.
    """
    unique = list(dict.fromkeys(symbols))
    records: list[BaseModel] = []
    failures: list[str] = []
    for index, symbol in enumerate(unique):
        try:
            check_deadline()
            records.extend(fetch_one(symbol))
        except Exception as exc:
            stop = isinstance(exc, DeadlineExceeded) or is_fatal(exc)
            if stop and not records:
                raise
            failures.append(f"{symbol}: {type(exc).__name__}: {exc}"[:300])
            if stop:
                raise PartialFetch(
                    records, f"stopped after {index} of {len(unique)} symbols; {failures[-1]}"
                ) from exc
        if pause is not None and index < len(unique) - 1:
            pause()
    if failures:
        raise PartialFetch(
            records, f"{len(failures)} of {len(unique)} symbols failed; first: {failures[0]}"
        )
    return records
```

- [ ] **Step 4: Add the optional credentials to `Settings`**

In `config.py`, add three fields to `Settings` after `cache_dir`:
```python
    finnhub_api_key: str | None = field(default=None, repr=False)
    fmp_api_key: str | None = field(default=None, repr=False)
    sec_user_agent: str | None = None  # e.g. "stock-advisor you@example.com"; SEC requires a contact
```

In `from_env`, pass these after `cache_dir=`:
```python
            finnhub_api_key=env.get("FINNHUB_API_KEY") or None,
            fmp_api_key=env.get("FMP_API_KEY") or None,
            sec_user_agent=env.get("SEC_USER_AGENT") or None,
```

- [ ] **Step 5: Pass the new secrets to workflows, the container, and document them**

In `.github/workflows/run.yml` (the "Run pipeline" step) and `.github/workflows/health.yml` (the "Check sources" step), add these to the step's `env:` block:
```yaml
          FINNHUB_API_KEY: ${{ secrets.FINNHUB_API_KEY }}
          FMP_API_KEY: ${{ secrets.FMP_API_KEY }}
          SEC_USER_AGENT: ${{ secrets.SEC_USER_AGENT }}
```

In `pipeline/scripts/in-docker.sh`, add `-e FINNHUB_API_KEY -e FMP_API_KEY -e SEC_USER_AGENT` to the existing env-forwarding line.

In `README.md` "Deployment":
1. Insert a new step directly after the Alpaca step:
   > **Data-source keys** (free accounts): sign up at finnhub.io and financialmodelingprep.com and copy each API key. Both providers' terms allow personal, non-commercial use only and forbid redistributing their data. For SEC requests, pick a contact string such as `stock-advisor you@example.com`; SEC requires one in every request.
2. Renumber the following steps.
3. In the GitHub secrets step, add `FINNHUB_API_KEY`, `FMP_API_KEY` and `SEC_USER_AGENT` to the list.
4. In "Manual run", add the same three names to the `.env.local` example.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `scripts/in-docker.sh uv run pytest tests/unit/test_base.py tests/unit/test_config.py -v`, then the full suite.
Validate the YAML: `uv run --no-sync --with pyyaml python -c "import yaml,sys; [yaml.safe_load(open(p, encoding='utf-8')) for p in sys.argv[1:]]; print('ok')" ../.github/workflows/run.yml ../.github/workflows/health.yml`
If `--no-sync --with` is refused, use `uv run --with pyyaml ...` instead.
Expected: all pass, and `ok`.

- [ ] **Step 7: Commit**

```bash
uv run --no-sync ruff check --fix .
git add src/advisor/collectors/base.py src/advisor/config.py tests/unit/test_base.py tests/unit/test_config.py ../.github/workflows/run.yml ../.github/workflows/health.yml scripts/in-docker.sh ../README.md
git commit -m "feat: add collector contract, source credentials, and per-symbol collection helper"
```
End the message with your `Co-Authored-By:` trailer.

---

### Task 3: Cadence-window cache, per-call symbol cap, partial backfill

**Files:**
- Modify: `pipeline/src/advisor/collectors/cache.py`, `pipeline/src/advisor/collectors/runner.py` (full replacement), `pipeline/src/advisor/collectors/base.py` (protocol attribute), `collectors/nasdaq_symbols.py`, `collectors/alpaca_bars.py`, `collectors/yfinance_bars.py`, `pipeline/tests/fakes.py`
- Test: `pipeline/tests/unit/test_runner.py`, `pipeline/tests/unit/test_cache.py`

**Interfaces:**
- Produces:
  - `DiskCache.get_entry(source, key, record_type) -> tuple[datetime, list[BaseModel]] | None`
  - `runner.in_window(cadence, saved_at, as_of) -> bool`
  - `run_collector(..., use_window: bool = True)`
  - protocol attribute `max_symbols: int | None` (existing collectors and `FakeCollector` set `None`)
- Behaviour, in short:
  - DAILY/WEEKLY collectors with `freshness` skip symbols already fetched in this ET day or ISO week.
  - An OK per-symbol empty answer is remembered for the window.
  - `max_symbols` caps one call. Capped-out symbols are served from older cache and are not marked as fetched.
  - A PARTIAL per-symbol answer is backfilled from cache.

- [ ] **Step 1: Add the protocol attribute everywhere**

- In `collectors/base.py`, add to the `Collector` protocol after `canary_requires_records`:
  `max_symbols: int | None  # most symbols one call may fetch; the rest wait for a later run`
- In `nasdaq_symbols.py`, `alpaca_bars.py` and `yfinance_bars.py`, add the class attribute `max_symbols = None` after `canary_requires_records`.
- In `tests/fakes.py`, add the field `max_symbols: int | None = None` to `FakeCollector`, after `canary_requires_records`.

- [ ] **Step 2: Write the failing tests**

Append to `pipeline/tests/unit/test_cache.py`:
```python
def test_get_entry_returns_saved_time_and_records(tmp_path):
    cache = DiskCache(tmp_path, clock=lambda: T0)
    cache.put("s", "k", [info("AAPL")])
    saved_at, records = cache.get_entry("s", "k", SymbolInfo)
    assert saved_at == T0
    assert [r.symbol for r in records] == ["AAPL"]
    assert cache.get_entry("s", "missing", SymbolInfo) is None
```

In `pipeline/tests/unit/test_runner.py`:
- change `universe_collector`'s default to `cadence=Cadence.PER_RUN` (window behaviour is tested separately below);
- add `in_window` to the runner import, and add `Scope` to the base import if it's missing;
- then append:
```python
def windowed(cadence=Cadence.DAILY, **kwargs) -> FakeCollector:
    defaults = dict(
        name="win",
        records_for=lambda syms: [bar(s, TODAY, 1.0) for s in syms if s != "NONE"],
        cadence=cadence,
        freshness=timedelta(days=10),
    )
    return FakeCollector(**{**defaults, **kwargs})


def clocked_cache(tmp_path, start):
    now = [start]
    return DiskCache(tmp_path, clock=lambda: now[0]), now


def test_in_window_uses_et_days_and_iso_weeks():
    late_monday_et = datetime(2026, 10, 13, 3, 30, tzinfo=UTC)  # 23:30 ET on Monday 12 Oct
    assert in_window(Cadence.DAILY, late_monday_et, datetime(2026, 10, 12, 14, 0, tzinfo=UTC))
    assert not in_window(Cadence.DAILY, late_monday_et, datetime(2026, 10, 13, 14, 0, tzinfo=UTC))
    monday = datetime(2026, 10, 12, 14, 0, tzinfo=UTC)
    assert in_window(Cadence.WEEKLY, monday, datetime(2026, 10, 18, 14, 0, tzinfo=UTC))
    assert not in_window(Cadence.WEEKLY, monday, datetime(2026, 10, 19, 14, 0, tzinfo=UTC))
    assert not in_window(Cadence.PER_RUN, monday, monday)


def test_daily_collector_fetches_only_symbols_missing_from_todays_window(tmp_path):
    cache, now = clocked_cache(tmp_path, NOW)
    collector = windowed()
    run_collector(collector, ["AAA", "BBB"], NOW, cache=cache, state=SourceState())
    later = NOW + timedelta(hours=3)
    now[0] = later
    result = run_collector(collector, ["BBB", "CCC"], later, cache=cache, state=SourceState())
    assert collector.calls == [["AAA", "BBB"], ["CCC"]]
    assert result.status is CollectorStatus.OK
    assert sorted(r.symbol for r in result.records) == ["BBB", "CCC"]


def test_a_fully_cached_request_does_not_fetch(tmp_path):
    cache, _ = clocked_cache(tmp_path, NOW)
    collector = windowed()
    run_collector(collector, ["AAA"], NOW, cache=cache, state=SourceState())
    result = run_collector(collector, ["AAA"], NOW, cache=cache, state=SourceState())
    assert collector.calls == [["AAA"]]
    assert (result.status, result.latency_ms) == (CollectorStatus.OK, 0)
    assert [r.symbol for r in result.records] == ["AAA"]


def test_a_new_day_fetches_again(tmp_path):
    cache, now = clocked_cache(tmp_path, NOW)
    collector = windowed()
    run_collector(collector, ["AAA"], NOW, cache=cache, state=SourceState())
    tomorrow = NOW + timedelta(days=1)
    now[0] = tomorrow
    run_collector(collector, ["AAA"], tomorrow, cache=cache, state=SourceState())
    assert collector.calls == [["AAA"], ["AAA"]]


def test_weekly_collectors_reuse_the_whole_iso_week(tmp_path):
    monday = datetime(2026, 10, 12, 13, 0, tzinfo=UTC)
    cache, now = clocked_cache(tmp_path, monday)
    collector = windowed(Cadence.WEEKLY)
    for moment in (monday, monday + timedelta(days=4), monday + timedelta(days=7)):
        now[0] = moment
        run_collector(collector, ["AAA"], moment, cache=cache, state=SourceState())
    assert collector.calls == [["AAA"], ["AAA"]]


def test_symbols_without_records_are_remembered_for_the_window(tmp_path):
    cache, _ = clocked_cache(tmp_path, NOW)
    collector = windowed()
    run_collector(collector, ["AAA", "NONE"], NOW, cache=cache, state=SourceState())
    result = run_collector(collector, ["NONE"], NOW, cache=cache, state=SourceState())
    assert collector.calls == [["AAA", "NONE"]]
    assert (result.status, result.records) == (CollectorStatus.OK, [])


def test_whole_list_collectors_skip_the_fetch_within_the_window(tmp_path):
    cache, _ = clocked_cache(tmp_path, NOW)
    collector = FakeCollector(
        "macro", scope=Scope.MARKET, record_type=SymbolInfo, records_for=lambda s: [info("X")],
        cadence=Cadence.DAILY, freshness=timedelta(days=2),
    )
    run_collector(collector, [], NOW, cache=cache, state=SourceState())
    result = run_collector(collector, [], NOW, cache=cache, state=SourceState())
    assert collector.calls == [[]]
    assert [r.symbol for r in result.records] == ["X"]


def test_use_window_false_always_fetches(tmp_path):
    cache, _ = clocked_cache(tmp_path, NOW)
    collector = windowed()
    run_collector(collector, ["AAA"], NOW, cache=cache, state=SourceState())
    run_collector(collector, ["AAA"], NOW, cache=cache, state=SourceState(), use_window=False)
    assert collector.calls == [["AAA"], ["AAA"]]


def test_max_symbols_caps_a_call_and_leaves_the_rest_for_later(tmp_path):
    cache, _ = clocked_cache(tmp_path, NOW)
    collector = windowed(Cadence.WEEKLY, max_symbols=2)
    first = run_collector(collector, ["AAA", "BBB", "CCC"], NOW, cache=cache, state=SourceState())
    second = run_collector(collector, ["AAA", "BBB", "CCC"], NOW, cache=cache, state=SourceState())
    assert collector.calls == [["AAA", "BBB"], ["CCC"]]
    assert sorted(r.symbol for r in first.records) == ["AAA", "BBB"]
    assert sorted(r.symbol for r in second.records) == ["AAA", "BBB", "CCC"]


def test_capped_out_symbols_are_served_from_older_cache(tmp_path):
    cache, now = clocked_cache(tmp_path, NOW)
    collector = windowed(max_symbols=1)
    run_collector(collector, ["AAA"], NOW, cache=cache, state=SourceState())
    run_collector(collector, ["BBB"], NOW, cache=cache, state=SourceState())
    tomorrow = NOW + timedelta(days=1)
    now[0] = tomorrow
    result = run_collector(collector, ["AAA", "BBB"], tomorrow, cache=cache, state=SourceState())
    assert collector.calls[-1] == ["AAA"]
    assert sorted(r.symbol for r in result.records) == ["AAA", "BBB"]


def test_a_partial_answer_is_backfilled_from_cache(tmp_path):
    cache = DiskCache(tmp_path, clock=lambda: NOW)
    collector = bars_collector()
    run_collector(collector, ["AAA", "BBB"], NOW, cache=cache, state=SourceState())
    collector.error = PartialFetch([bar("AAA", TODAY, 2.0)], "1 of 2 requests failed")
    result = run_collector(collector, ["AAA", "BBB"], NOW, cache=cache, state=SourceState())
    assert result.status is CollectorStatus.PARTIAL
    assert sorted((r.symbol, r.close) for r in result.records) == [("AAA", 2.0), ("BBB", 10.0)]
```

- [ ] **Step 3: Run them to verify they fail**

Run: `scripts/in-docker.sh uv run pytest tests/unit/test_runner.py tests/unit/test_cache.py -v`
Expected: ImportError for `in_window`, and `DiskCache` has no `get_entry`.

- [ ] **Step 4: Add `get_entry` to `cache.py`**

Replace `DiskCache.get` with these two methods:
```python
    def get_entry(
        self, source: str, key: str, record_type: type[BaseModel]
    ) -> tuple[datetime, list[BaseModel]] | None:
        """(saved_at, records) for a cache entry, or None if it is missing or unreadable."""
        try:
            payload = json.loads(self._path(source, key).read_text(encoding="utf-8"))
            saved_at = datetime.fromisoformat(payload["saved_at"])
            return saved_at, [record_type.model_validate(raw) for raw in payload["records"]]
        except (OSError, ValueError, KeyError, TypeError):  # missing, corrupt, or wrong-shape
            return None

    def get(
        self, source: str, key: str, record_type: type[BaseModel], max_age: timedelta
    ) -> list[BaseModel] | None:
        entry = self.get_entry(source, key, record_type)
        if entry is None:
            return None
        try:
            too_old = self._clock() - entry[0] > max_age
        except TypeError:  # a naive timestamp from an older format
            return None
        return None if too_old else entry[1]
```

- [ ] **Step 5: Replace `runner.py`**

`pipeline/src/advisor/collectors/runner.py` (full replacement):
```python
"""Runs one collector safely: circuit breaker, cadence-window cache, timing, error capture.

Cache use (spec §4.1):
- DAILY and WEEKLY collectors with `freshness` are served from entries saved in the current
  window (ET day or ISO week); only symbols missing from the window are fetched.
- `max_symbols` caps one call; capped-out symbols are served from older cache and fetched later.
- Any collector with `freshness` falls back to entries younger than `freshness` when it fails,
  and a partial per-symbol answer is backfilled the same way.
- An empty answer never replaces a cached whole list; per symbol, an OK empty answer is
  remembered for the window so the symbol isn't refetched.
"""

import time
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime

from pydantic import BaseModel

from advisor.collectors.base import (
    Cadence,
    Collector,
    CollectorResult,
    CollectorStatus,
    PartialFetch,
    Scope,
)
from advisor.collectors.cache import DiskCache
from advisor.models import ET

BREAKER_THRESHOLD = 3
WHOLE = ""  # cache key for UNIVERSE and MARKET collectors, which return one list per call


@dataclass(frozen=True)
class SourceState:
    consecutive_failures: int = 0
    last_attempt_et_date: date | None = None


def breaker_open(state: SourceState, today_et: date) -> bool:
    """Open after 3 straight failures, but allow one attempt on each new ET day (half-open)."""
    return (
        state.consecutive_failures >= BREAKER_THRESHOLD
        and state.last_attempt_et_date == today_et
    )


def next_failures(state: SourceState, result: CollectorResult) -> int:
    if result.status is CollectorStatus.SKIPPED:
        return state.consecutive_failures
    if result.status in (CollectorStatus.OK, CollectorStatus.PARTIAL):
        return 0  # the source answered; gaps in a partial result don't trip the breaker
    return state.consecutive_failures + 1


def in_window(cadence: Cadence, saved_at: datetime, as_of: datetime) -> bool:
    """True when `saved_at` falls in the same cadence window (ET day / ISO week) as `as_of`."""
    saved, now = saved_at.astimezone(ET), as_of.astimezone(ET)
    if cadence is Cadence.DAILY:
        return saved.date() == now.date()
    if cadence is Cadence.WEEKLY:
        return saved.isocalendar()[:2] == now.isocalendar()[:2]
    return False


def _cache_keys(collector: Collector, symbols: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(symbols)) if collector.scope is Scope.SYMBOLS else [WHOLE]


def _symbol_of(record: BaseModel) -> str | None:
    symbol = getattr(record, "symbol", None)
    return symbol if isinstance(symbol, str) and symbol else None


def _cached(
    collector: Collector, keys: Sequence[str], cache: DiskCache
) -> list[BaseModel] | None:
    """Cached records younger than `freshness` for these keys, or None if there are none."""
    if collector.freshness is None:
        return None
    found: list[BaseModel] = []
    for key in keys:
        found.extend(
            cache.get(collector.name, key, collector.record_type, collector.freshness) or []
        )
    return found or None


def _window_hits(
    collector: Collector, keys: Sequence[str], cache: DiskCache, as_of: datetime
) -> tuple[list[BaseModel], list[str]]:
    """Records saved in this cadence window, and the keys that still need a fetch."""
    if collector.freshness is None or collector.cadence is Cadence.PER_RUN:
        return [], list(keys)
    hits: list[BaseModel] = []
    missing: list[str] = []
    for key in keys:
        entry = cache.get_entry(collector.name, key, collector.record_type)
        if entry is not None and in_window(collector.cadence, entry[0], as_of):
            hits.extend(entry[1])
        else:
            missing.append(key)
    return hits, missing


def _store(
    collector: Collector,
    records: Sequence[BaseModel],
    cache: DiskCache,
    *,
    empty_symbols: Sequence[str] = (),
) -> None:
    """Cache what came back (per symbol for SYMBOLS scope); best-effort, never raises."""
    if collector.freshness is None or (not records and not empty_symbols):
        return
    groups: dict[str, list[BaseModel]] = defaultdict(list)
    for record in records:
        if collector.scope is Scope.SYMBOLS:
            key = _symbol_of(record)
            if key is None:
                continue  # unkeyable records are returned to the caller but never cached
        else:
            key = WHOLE
        groups[key].append(record)
    for symbol in empty_symbols:
        groups.setdefault(symbol, [])  # "nothing for this symbol", remembered for the window
    for key, group in groups.items():
        try:
            cache.put(collector.name, key, group)
        except Exception:
            pass  # cache is a fallback; a failed write must not lose a good fetch


def run_collector(
    collector: Collector,
    symbols: Sequence[str],
    as_of: datetime,
    *,
    cache: DiskCache,
    state: SourceState,
    use_window: bool = True,
) -> CollectorResult:
    keys = _cache_keys(collector, symbols)
    if breaker_open(state, as_of.astimezone(ET).date()):
        return CollectorResult(
            collector.name,
            CollectorStatus.SKIPPED,
            _cached(collector, keys, cache) or [],
            0,
            "circuit breaker open",
        )

    hits, missing = _window_hits(collector, keys, cache, as_of) if use_window else ([], keys)
    if keys and not missing:
        return CollectorResult(collector.name, CollectorStatus.OK, hits, 0, None)
    deferred: list[BaseModel] = []
    if collector.scope is Scope.SYMBOLS:
        fetch_symbols = missing[: collector.max_symbols] if collector.max_symbols else missing
        later = missing[len(fetch_symbols):]
        deferred = (_cached(collector, later, cache) or []) if later else []
    else:
        fetch_symbols = list(symbols)

    started = time.perf_counter()
    status, error = CollectorStatus.OK, None
    try:
        try:
            records = list(collector.fetch(fetch_symbols, as_of))
        except PartialFetch as exc:
            if not exc.records:
                raise  # nothing usable came back: a plain failure
            records = exc.records
            status, error = CollectorStatus.PARTIAL, f"PartialFetch: {exc}"[:500]
    except Exception as exc:  # any source failure is contained here
        latency = int((time.perf_counter() - started) * 1000)
        error = f"{type(exc).__name__}: {exc}"[:500]
        fallback_keys = fetch_symbols if collector.scope is Scope.SYMBOLS else keys
        served = hits + (_cached(collector, fallback_keys, cache) or []) + deferred
        if served:
            return CollectorResult(collector.name, CollectorStatus.STALE, served, latency, error)
        return CollectorResult(collector.name, CollectorStatus.FAILED, [], latency, error)

    latency = int((time.perf_counter() - started) * 1000)
    if status is CollectorStatus.OK:
        empty: list[str] = []
        if collector.scope is Scope.SYMBOLS and collector.cadence is not Cadence.PER_RUN:
            got = {_symbol_of(r) for r in records}
            empty = [s for s in fetch_symbols if s not in got]
        _store(collector, records, cache, empty_symbols=empty)
    elif collector.scope is Scope.SYMBOLS:  # partial: keep what came, backfill the rest
        _store(collector, records, cache)
        got = {_symbol_of(r) for r in records}
        records = records + (
            _cached(collector, [s for s in fetch_symbols if s not in got], cache) or []
        )
    return CollectorResult(collector.name, status, hits + records + deferred, latency, error)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `scripts/in-docker.sh uv run pytest tests/unit/test_runner.py tests/unit/test_cache.py -v`, then the full suite.
Expected: all pass, including every existing runner, tracker, health and run test.

- [ ] **Step 7: Commit**

```bash
uv run --no-sync ruff check --fix .
git add src/advisor/collectors tests/fakes.py tests/unit/test_runner.py tests/unit/test_cache.py
git commit -m "feat: serve daily and weekly sources from the cadence window and cap symbols per call"
```
End the message with your `Co-Authored-By:` trailer.

---

### Task 4: Concurrent health check with a per-source budget

**Files:**
- Modify: `pipeline/src/advisor/health.py`
- Test: `pipeline/tests/unit/test_health.py`

**Interfaces:**
- Consumes: `deadline` (Task 1), `run_collector(..., use_window=False)` (Task 3)
- Produces:
  - `health.check_source(collector, cache, state, now, *, budget=SOURCE_BUDGET_SECONDS) -> tuple[CollectorResult, int]`
  - `health.iter_checks(collectors, cache, states, now, *, workers=HEALTH_WORKERS, budget=...)`, an iterator that yields each source's result as soon as it finishes
  - `health.check_sources(...) -> list`, which keeps the existing call shape
  - `main` writes each row as its source finishes
  - constants `HEALTH_WORKERS = 8` and `SOURCE_BUDGET_SECONDS = 120.0`

- [ ] **Step 1: Write the failing tests**

Append to `pipeline/tests/unit/test_health.py`. Add `from datetime import timedelta`, `from advisor.collectors.base import Cadence, check_deadline`, and import `CollectorStatus` if it's missing:
```python
def test_a_source_over_its_budget_fails_without_stopping_the_others(tmp_path):
    slow = FakeCollector("slow", canary=("AAPL",), records_for=lambda syms: (check_deadline(), [])[1])
    good = FakeCollector(
        "good", canary=("AAPL",), records_for=lambda syms: [bar(s, date(2026, 10, 9), 1.0) for s in syms]
    )
    rows = {
        result.name: result
        for result, _ in check_sources({"slow": slow, "good": good}, DiskCache(tmp_path), {}, NOW, budget=0)
    }
    assert rows["slow"].status is CollectorStatus.FAILED
    assert rows["slow"].error.startswith("DeadlineExceeded")
    assert rows["good"].status is CollectorStatus.OK


def test_health_checks_bypass_the_cadence_cache(tmp_path):
    daily = FakeCollector(
        "daily", canary=("AAPL",), cadence=Cadence.DAILY, freshness=timedelta(days=1),
        records_for=lambda syms: [bar(s, date(2026, 10, 9), 1.0) for s in syms],
    )
    cache = DiskCache(tmp_path, clock=lambda: NOW)
    check_sources({"daily": daily}, cache, {}, NOW)
    check_sources({"daily": daily}, cache, {}, NOW)
    assert daily.calls == [["AAPL"], ["AAPL"]]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `scripts/in-docker.sh uv run pytest tests/unit/test_health.py -v`
Expected:
- `check_sources()` got an unexpected keyword `budget`;
- the second test makes only one call, because the cadence cache served it.

- [ ] **Step 3: Rewrite the checking functions in `health.py`**

Replace the imports and `check_sources` with the following. Keep the module docstring, but add one line to it: "Sources are checked concurrently, each within its own time budget, and rows are written as they finish." Change `main` only as Step 4 says.
```python
import json
import sys
import time
from collections.abc import Iterator, Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from datetime import UTC, datetime

from advisor.collectors.base import (
    Collector,
    CollectorResult,
    CollectorStatus,
    deadline,
    make_client,
)
from advisor.collectors.cache import DiskCache
from advisor.collectors.registry import build_registry
from advisor.collectors.runner import SourceState, next_failures, run_collector
from advisor.config import Settings
from advisor.store import repo
from advisor.store.db import connect

HEALTH_WORKERS = 8
SOURCE_BUDGET_SECONDS = 120.0


def check_source(
    collector: Collector,
    cache: DiskCache,
    state: SourceState,
    now: datetime,
    *,
    budget: float = SOURCE_BUDGET_SECONDS,
) -> tuple[CollectorResult, int]:
    """One live canary fetch, bypassing the breaker and the cadence cache, within `budget` seconds.

    An empty answer fails only for collectors that must return records. A failed check never
    adds to the failure count (spec §4.1 counts failing runs); a passing one resets it.
    """
    try:
        with deadline(time.monotonic() + budget):
            result = run_collector(
                collector, list(collector.canary), now, cache=cache, state=SourceState(),
                use_window=False,
            )
    except Exception as exc:  # a broken collector must not stop the other checks
        result = CollectorResult(
            collector.name, CollectorStatus.FAILED, [], 0, f"{type(exc).__name__}: {exc}"[:500]
        )
    if (
        collector.canary_requires_records
        and result.status is CollectorStatus.OK
        and not result.records
    ):
        result = replace(result, status=CollectorStatus.FAILED, error="canary returned no records")
    failures = (
        next_failures(state, result)
        if result.status in (CollectorStatus.OK, CollectorStatus.PARTIAL)
        else state.consecutive_failures
    )
    return result, failures


def iter_checks(
    collectors: Mapping[str, Collector],
    cache: DiskCache,
    states: Mapping[str, SourceState],
    now: datetime,
    *,
    workers: int = HEALTH_WORKERS,
    budget: float = SOURCE_BUDGET_SECONDS,
) -> Iterator[tuple[CollectorResult, int]]:
    """Check every source concurrently; yield each (result, failures) as soon as it finishes."""
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(
                check_source, collector, cache, states.get(name, SourceState()), now, budget=budget
            )
            for name, collector in collectors.items()
        ]
        for future in as_completed(futures):
            yield future.result()


def check_sources(
    collectors: Mapping[str, Collector],
    cache: DiskCache,
    states: Mapping[str, SourceState],
    now: datetime,
    **kwargs: float,
) -> list[tuple[CollectorResult, int]]:
    return list(iter_checks(collectors, cache, states, now, **kwargs))
```

- [ ] **Step 4: Write rows as they finish in `main`**

Replace the body of `main` (keep its signature) with:
```python
    now = datetime.now(UTC)
    settings = Settings.from_env()
    rows: list[tuple[CollectorResult, int]] = []
    with connect(settings.database_url) as conn, make_client() as client:
        collectors = build_registry(settings, client)
        states = repo.load_source_states(conn, collectors)
        for result, failures in iter_checks(collectors, DiskCache(settings.cache_dir), states, now):
            repo.record_source_health(conn, None, result, failures, now, context="health")
            rows.append((result, failures))
    print(json.dumps({result.name: result.status.value for result, _ in rows}))
    core_failing = [
        result.name
        for result, _ in rows
        if collectors[result.name].core and result.status is not CollectorStatus.OK
    ]
    if core_failing:
        print(f"core sources failing: {', '.join(core_failing)}", file=sys.stderr)
        return 1
    return 0
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `scripts/in-docker.sh uv run pytest tests/unit/test_health.py tests/integration/test_health_cli.py -v`, then the full suite.
Expected: all pass. The existing tests build dicts keyed by source name, so completion order doesn't matter.

- [ ] **Step 6: Commit**

```bash
uv run --no-sync ruff check --fix .
git add src/advisor/health.py tests/unit/test_health.py
git commit -m "feat: check sources concurrently with a per-source budget and write rows as they finish"
```
End the message with your `Co-Authored-By:` trailer.

---

### Task 5: Provider-neutral symbol keys and FINRA short volume (source 14)

**Files:**
- Create: `pipeline/src/advisor/symbols.py`, `pipeline/src/advisor/collectors/finra_short_volume.py`
- Modify: `pipeline/src/advisor/collectors/registry.py`, `pipeline/tests/unit/test_registry.py` (rewrite as a table)
- Test: `pipeline/tests/unit/test_finra_short_volume.py`
- Commit: the existing fixture `pipeline/tests/fixtures/finra/CNMSshvol20261009.txt`

It is a real file from 2026-10-09, trimmed to 73 rows. Its trailer still holds the real row count, 12278.

**Interfaces:**
- Produces:
  - `symbols.symbol_key(symbol) -> str` (`"BRK/B"`, `"BRK-B"`, `"BRK.B"` and `"brkb"` all give `"BRKB"`)
  - `symbols.requested_by_key(symbols) -> dict[str, str]`
  - `finra_short_volume`:
    - `ShortVolume(symbol, trade_date, short_volume, short_exempt_volume, total_volume)`
    - `candidate_days(as_of) -> list[date]`
    - `parse_short_volume(text, wanted) -> list[ShortVolume]`
    - `FinraShortVolume(client, limiter=None)`: name `finra_short_volume`, DAILY, SYMBOLS, freshness 4 days, canary `("AAPL",)` (requires records), not core
    - `FINRA_SHORT_VOLUME_URL`
  - registry test table `EXPECTED`, which later tasks extend

- [ ] **Step 1: Write the failing tests**

`pipeline/tests/unit/test_finra_short_volume.py`:
```python
from datetime import UTC, date, datetime

import httpx
import pytest

from advisor.collectors.finra_short_volume import (
    FINRA_SHORT_VOLUME_URL,
    FinraShortVolume,
    candidate_days,
    parse_short_volume,
)
from advisor.symbols import requested_by_key, symbol_key

MONDAY_PRE_OPEN = datetime(2026, 10, 12, 12, 15, tzinfo=UTC)  # 08:15 ET
TUESDAY_PRE_OPEN = datetime(2026, 10, 13, 12, 15, tzinfo=UTC)


def fixture_text(fixtures_dir) -> str:
    return (fixtures_dir / "finra" / "CNMSshvol20261009.txt").read_text(encoding="utf-8")


def client_serving(responses: dict[str, httpx.Response], seen: list[str]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return responses.get(str(request.url), httpx.Response(403, text="AccessDenied"))

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_symbol_key_ignores_share_class_separators():
    assert {symbol_key(s) for s in ("BRK.B", "BRK/B", "BRK-B", "brkb")} == {"BRKB"}
    assert requested_by_key(["BRK.B", "AAPL"]) == {"BRKB": "BRK.B", "AAPL": "AAPL"}


def test_candidate_days_skip_weekends_and_wait_for_publication():
    assert candidate_days(MONDAY_PRE_OPEN) == [
        date(2026, 10, 9), date(2026, 10, 8), date(2026, 10, 7), date(2026, 10, 6), date(2026, 10, 5),
    ]
    monday_evening = datetime(2026, 10, 12, 22, 45, tzinfo=UTC)  # 18:45 ET, after publication
    assert candidate_days(monday_evening)[0] == date(2026, 10, 12)


def test_parse_maps_provider_symbols_and_skips_header_and_trailer(fixtures_dir):
    wanted = requested_by_key(["AAPL", "BRK.B", "BF.B", "NOPE"])
    rows = {r.symbol: r for r in parse_short_volume(fixture_text(fixtures_dir), wanted)}
    assert sorted(rows) == ["AAPL", "BF.B", "BRK.B"]
    aapl = rows["AAPL"]
    assert aapl.trade_date == date(2026, 10, 9)
    assert aapl.short_volume == pytest.approx(9011284.413782)
    assert aapl.total_volume == pytest.approx(15300955.899485)
    assert rows["BRK.B"].short_volume == pytest.approx(691652.708894)


def test_fetch_falls_back_from_an_unpublished_day(fixtures_dir):
    seen: list[str] = []
    published = FINRA_SHORT_VOLUME_URL.format(day=date(2026, 10, 9))
    collector = FinraShortVolume(
        client_serving({published: httpx.Response(200, text=fixture_text(fixtures_dir))}, seen)
    )
    records = collector.fetch(["AAPL"], TUESDAY_PRE_OPEN)
    assert [r.symbol for r in records] == ["AAPL"]
    assert seen == [FINRA_SHORT_VOLUME_URL.format(day=date(2026, 10, 12)), published]


def test_fetch_gives_up_after_the_lookback():
    collector = FinraShortVolume(client_serving({}, []))
    with pytest.raises(RuntimeError, match="no FINRA short volume file"):
        collector.fetch(["AAPL"], TUESDAY_PRE_OPEN)


def test_other_http_errors_are_not_treated_as_unpublished():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="bad request")

    collector = FinraShortVolume(httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(httpx.HTTPStatusError):
        collector.fetch(["AAPL"], TUESDAY_PRE_OPEN)
```

Replace `pipeline/tests/unit/test_registry.py` entirely with:
```python
from pathlib import Path

import httpx

from advisor.collectors.base import Scope
from advisor.collectors.registry import build_registry
from advisor.config import Settings

# name: (core, scope, canary_requires_records). Every new source adds a row.
EXPECTED = {
    "alpaca_bars": (True, Scope.SYMBOLS, True),
    "finra_short_volume": (False, Scope.SYMBOLS, True),
    "nasdaq_symbols": (True, Scope.UNIVERSE, True),
    "yfinance_bars": (False, Scope.SYMBOLS, True),
}


def build() -> dict:
    settings = Settings(
        "postgresql://x", "key", "secret", Path(".cache"), finnhub_api_key="fk", fmp_api_key="mk"
    )
    with httpx.Client() as client:
        return build_registry(settings, client)


def test_registry_matches_the_expected_sources():
    registry = build()
    assert {
        name: (c.core, c.scope, c.canary_requires_records) for name, c in registry.items()
    } == EXPECTED
    assert all(registry[name].name == name for name in registry)


def test_symbols_collectors_have_canaries_and_symbol_records():
    for collector in build().values():
        assert bool(collector.canary) == (collector.scope is Scope.SYMBOLS)
        if collector.scope is Scope.SYMBOLS:
            field = collector.record_type.model_fields["symbol"]
            assert field.annotation is str
            assert field.is_required()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `scripts/in-docker.sh uv run pytest tests/unit/test_finra_short_volume.py tests/unit/test_registry.py -v`
Expected: `ModuleNotFoundError` for `advisor.collectors.finra_short_volume` and `advisor.symbols`, and the registry table lacks `finra_short_volume`.

- [ ] **Step 3: Implement `symbols.py`**

`pipeline/src/advisor/symbols.py`:
```python
"""Canonical symbols ("BRK.B") and a provider-neutral key for matching other formats."""

from collections.abc import Sequence

_SEPARATORS = "./- "


def symbol_key(symbol: str) -> str:
    """Upper case with share-class separators removed: "BRK/B", "BRK-B", "BRKB" all -> "BRKB"."""
    return "".join(ch for ch in symbol.upper() if ch not in _SEPARATORS)


def requested_by_key(symbols: Sequence[str]) -> dict[str, str]:
    """Map provider-neutral keys back to the canonical symbols that were requested."""
    return {symbol_key(symbol): symbol for symbol in symbols}
```

- [ ] **Step 4: Implement the collector**

`pipeline/src/advisor/collectors/finra_short_volume.py`:
```python
"""Daily short-sale volume from FINRA's consolidated Reg SHO file (spec source 14).

One static file per trading day covers every symbol, so a run downloads one file and keeps the
requested symbols. Missing files (weekend, holiday, not published yet) answer HTTP 403.
"""

from collections.abc import Mapping, Sequence
from datetime import date, datetime, time, timedelta

import httpx
from pydantic import BaseModel, ConfigDict, Field

from advisor.collectors.base import (
    Cadence,
    Category,
    RateLimiter,
    Scope,
    check_deadline,
    get_with_retries,
)
from advisor.models import ET, AssetType
from advisor.symbols import requested_by_key, symbol_key

FINRA_SHORT_VOLUME_URL = "https://cdn.finra.org/equity/regsho/daily/CNMSshvol{day:%Y%m%d}.txt"
PUBLISHED_AFTER = time(18, 30)  # files appear around 17:15 ET; leave a margin
LOOKBACK_WEEKDAYS = 5
UNPUBLISHED = frozenset({403, 404})


class ShortVolume(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    trade_date: date
    short_volume: float = Field(ge=0)
    short_exempt_volume: float = Field(ge=0)
    total_volume: float = Field(ge=0)


def candidate_days(as_of: datetime, lookback: int = LOOKBACK_WEEKDAYS) -> list[date]:
    """Newest-first weekdays whose file may exist; today counts only after publication time."""
    now = as_of.astimezone(ET)
    day = now.date() if now.time() >= PUBLISHED_AFTER else now.date() - timedelta(days=1)
    days: list[date] = []
    while len(days) < lookback:
        if day.weekday() < 5:
            days.append(day)
        day -= timedelta(days=1)
    return days


def parse_short_volume(text: str, wanted: Mapping[str, str]) -> list[ShortVolume]:
    """Rows for the wanted symbols; the header and the row-count trailer are skipped."""
    rows: list[ShortVolume] = []
    seen: set[str] = set()
    for line in text.splitlines():
        parts = line.strip().split("|")
        if len(parts) != 6 or parts[0] == "Date":
            continue
        symbol = wanted.get(symbol_key(parts[1]))
        if symbol is None or symbol in seen:
            continue
        try:
            rows.append(ShortVolume(
                symbol=symbol,
                trade_date=datetime.strptime(parts[0], "%Y%m%d").date(),
                short_volume=float(parts[2]),
                short_exempt_volume=float(parts[3]),
                total_volume=float(parts[4]),
            ))
        except ValueError:
            continue
        seen.add(symbol)
    return rows


class FinraShortVolume:
    name = "finra_short_volume"
    category = Category.FUNDAMENTALS
    core = False
    best_effort = False
    cadence = Cadence.DAILY
    asset_types = frozenset({AssetType.STOCK})
    record_type = ShortVolume
    freshness = timedelta(days=4)
    scope = Scope.SYMBOLS
    canary = ("AAPL",)
    canary_requires_records = True
    max_symbols = None

    def __init__(self, client: httpx.Client, limiter: RateLimiter | None = None) -> None:
        self._client = client
        self._limiter = limiter

    def fetch(self, symbols: Sequence[str], as_of: datetime) -> list[ShortVolume]:
        wanted = requested_by_key(symbols)
        for day in candidate_days(as_of):
            check_deadline()
            try:
                response = get_with_retries(
                    self._client, FINRA_SHORT_VOLUME_URL.format(day=day), limiter=self._limiter
                )
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in UNPUBLISHED:
                    continue
                raise
            return parse_short_volume(response.text, wanted)
        raise RuntimeError(f"no FINRA short volume file in the last {LOOKBACK_WEEKDAYS} weekdays")
```

- [ ] **Step 5: Register it**

In `collectors/registry.py`:
- add the import `from advisor.collectors.finra_short_volume import FinraShortVolume`;
- append `FinraShortVolume(client),` to the `collectors` list;
- change the module docstring to `"""Every collector the pipeline runs, keyed by name."""`.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `scripts/in-docker.sh uv run pytest tests/unit/test_finra_short_volume.py tests/unit/test_registry.py -v`, then the full suite.
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
uv run --no-sync ruff check --fix .
git add src/advisor/symbols.py src/advisor/collectors/finra_short_volume.py src/advisor/collectors/registry.py tests/unit/test_finra_short_volume.py tests/unit/test_registry.py tests/fixtures/finra/CNMSshvol20261009.txt
git commit -m "feat: add FINRA daily short volume source"
```
End the message with your `Co-Authored-By:` trailer.

---

### Task 6: FINRA short interest (source 13)

**Files:**
- Create: `pipeline/src/advisor/collectors/finra_short_interest.py`
- Modify: `pipeline/src/advisor/collectors/registry.py`, `pipeline/tests/unit/test_registry.py` (add a row)
- Test: `pipeline/tests/unit/test_finra_short_interest.py`
- Commit: the existing fixture `pipeline/tests/fixtures/finra/shrt20260930.csv`

It is the real 2026-09-30 settlement file, trimmed. Every value is quoted, the delimiter is `|`, and it has 14 columns.

The other existing file, `fixtures/finra/consolidatedShortInterest_api_20260930.json`, is the API alternative and is not used. Delete it in this task.

**Interfaces:**
- Consumes:
  - `symbols.symbol_key` and `requested_by_key` (Task 5)
  - `schedule.previous_sessions(end, count)` (Plan 1)
- Produces:
  - `ShortInterest(symbol, settlement_date, short_interest, previous_short_interest, avg_daily_volume, days_to_cover)`
  - `settlement_dates(as_of, months=2) -> list[date]`
  - `parse_short_interest(text, wanted) -> list[ShortInterest]`
  - `FinraShortInterest(client, limiter=None)`: WEEKLY, SYMBOLS, freshness 20 days, canary `("AAPL",)` (requires records), not core
  - `FINRA_SHORT_INTEREST_URL` and `HEADER`

- [ ] **Step 1: Write the failing test**

`pipeline/tests/unit/test_finra_short_interest.py`:
```python
from datetime import UTC, date, datetime

import httpx
import pytest

from advisor.collectors.finra_short_interest import (
    FINRA_SHORT_INTEREST_URL,
    FinraShortInterest,
    parse_short_interest,
    settlement_dates,
)
from advisor.symbols import requested_by_key

AS_OF = datetime(2026, 10, 12, 12, 15, tzinfo=UTC)


def fixture_text(fixtures_dir) -> str:
    return (fixtures_dir / "finra" / "shrt20260930.csv").read_text(encoding="utf-8")


def test_settlement_dates_are_mid_month_and_month_end_sessions():
    assert settlement_dates(AS_OF) == [
        date(2026, 9, 30), date(2026, 9, 15), date(2026, 8, 31), date(2026, 8, 14),  # 15 Aug is a Saturday
    ]


def test_parse_maps_symbols_and_converts_fields(fixtures_dir):
    rows = {
        r.symbol: r
        for r in parse_short_interest(fixture_text(fixtures_dir), requested_by_key(["AAPL", "BRK.B", "NOPE"]))
    }
    assert sorted(rows) == ["AAPL", "BRK.B"]
    aapl = rows["AAPL"]
    assert (aapl.settlement_date, aapl.short_interest, aapl.previous_short_interest) == (
        date(2026, 9, 30), 120763539, 128753092,
    )
    assert aapl.avg_daily_volume == 39858260
    assert aapl.days_to_cover == pytest.approx(3.03)
    assert rows["BRK.B"].short_interest == 12370081


def test_days_to_cover_is_none_when_there_is_no_volume():
    header = (
        '"accountingYearMonthNumber"|"symbolCode"|"issueName"|"issuerServicesGroupExchangeCode"|'
        '"marketClassCode"|"currentShortPositionQuantity"|"previousShortPositionQuantity"|'
        '"stockSplitFlag"|"averageDailyVolumeQuantity"|"daysToCoverQuantity"|"revisionFlag"|'
        '"changePercent"|"changePreviousNumber"|"settlementDate"'
    )
    row = '"20260930"|"QUIET"|"Quiet Co"|"A"|"NYSE"|"100"|"90"||"0"|"999.99"||"11.1"|"10"|"2026-09-30"'
    [record] = parse_short_interest(f"{header}\n{row}\n", requested_by_key(["QUIET"]))
    assert record.days_to_cover is None
    assert record.avg_daily_volume == 0


def test_an_unexpected_header_is_rejected():
    with pytest.raises(ValueError, match="unexpected FINRA short interest header"):
        parse_short_interest('"symbol"|"shares"\n"AAPL"|"1"\n', requested_by_key(["AAPL"]))


def test_fetch_takes_the_newest_published_settlement(fixtures_dir):
    seen: list[str] = []
    published = FINRA_SHORT_INTEREST_URL.format(day=date(2026, 9, 15))

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if str(request.url) == published:
            return httpx.Response(200, text=fixture_text(fixtures_dir))
        return httpx.Response(403, text="AccessDenied")

    collector = FinraShortInterest(httpx.Client(transport=httpx.MockTransport(handler)))
    records = collector.fetch(["AAPL"], AS_OF)
    assert [r.symbol for r in records] == ["AAPL"]
    assert seen == [FINRA_SHORT_INTEREST_URL.format(day=date(2026, 9, 30)), published]
```

Add the row `"finra_short_interest": (False, Scope.SYMBOLS, True),` to `EXPECTED` in `tests/unit/test_registry.py`.

- [ ] **Step 2: Run them to verify they fail**

Run: `scripts/in-docker.sh uv run pytest tests/unit/test_finra_short_interest.py tests/unit/test_registry.py -v`
Expected: `ModuleNotFoundError`, and the registry is missing `finra_short_interest`.

- [ ] **Step 3: Implement**

`pipeline/src/advisor/collectors/finra_short_interest.py`:
```python
"""Bi-monthly short interest from FINRA's settlement files (spec source 13).

FINRA settles short interest on the 15th and the last business day of each month and publishes
about seven business days later, re-issuing files after first publication. The weekly run takes
the newest file that exists (unpublished files answer HTTP 403).
"""

import calendar
import csv
import io
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta

import httpx
from pydantic import BaseModel, ConfigDict, Field

from advisor.collectors.base import (
    Cadence,
    Category,
    RateLimiter,
    Scope,
    check_deadline,
    get_with_retries,
)
from advisor.models import ET, AssetType
from advisor.schedule import previous_sessions
from advisor.symbols import requested_by_key, symbol_key

FINRA_SHORT_INTEREST_URL = "https://cdn.finra.org/equity/otcmarket/biweekly/shrt{day:%Y%m%d}.csv"
HEADER = [
    "accountingYearMonthNumber", "symbolCode", "issueName", "issuerServicesGroupExchangeCode",
    "marketClassCode", "currentShortPositionQuantity", "previousShortPositionQuantity",
    "stockSplitFlag", "averageDailyVolumeQuantity", "daysToCoverQuantity", "revisionFlag",
    "changePercent", "changePreviousNumber", "settlementDate",
]
NO_VOLUME_DAYS_TO_COVER = "999.99"  # FINRA's placeholder when average daily volume is zero
UNPUBLISHED = frozenset({403, 404})


class ShortInterest(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    settlement_date: date
    short_interest: int = Field(ge=0)
    previous_short_interest: int | None = Field(default=None, ge=0)
    avg_daily_volume: int | None = Field(default=None, ge=0)
    days_to_cover: float | None = None  # None when there was no volume to cover with


def settlement_dates(as_of: datetime, months: int = 2) -> list[date]:
    """Newest-first settlement dates up to today: the 15th and the month's last session."""
    today = as_of.astimezone(ET).date()
    found: set[date] = set()
    year, month = today.year, today.month
    for _ in range(months + 1):
        mid = previous_sessions(date(year, month, 15), 1)[0]
        month_end = previous_sessions(date(year, month, calendar.monthrange(year, month)[1]), 1)[0]
        found.update(day for day in (mid, month_end) if day <= today)
        year, month = (year, month - 1) if month > 1 else (year - 1, 12)
    return sorted(found, reverse=True)


def _optional_int(value: str) -> int | None:
    value = value.strip()
    return int(value) if value else None


def parse_short_interest(text: str, wanted: Mapping[str, str]) -> list[ShortInterest]:
    reader = csv.reader(io.StringIO(text), delimiter="|", quotechar='"')
    header = next(reader, None)
    if header != HEADER:
        raise ValueError(f"unexpected FINRA short interest header: {header}")
    column = {name: index for index, name in enumerate(HEADER)}
    rows: list[ShortInterest] = []
    seen: set[str] = set()
    for row in reader:
        if len(row) != len(HEADER):
            continue
        symbol = wanted.get(symbol_key(row[column["symbolCode"]]))
        if symbol is None or symbol in seen:
            continue
        try:
            volume = _optional_int(row[column["averageDailyVolumeQuantity"]])
            days = row[column["daysToCoverQuantity"]].strip()
            rows.append(ShortInterest(
                symbol=symbol,
                settlement_date=date.fromisoformat(row[column["settlementDate"]]),
                short_interest=int(row[column["currentShortPositionQuantity"]]),
                previous_short_interest=_optional_int(row[column["previousShortPositionQuantity"]]),
                avg_daily_volume=volume,
                days_to_cover=(
                    None if not days or days == NO_VOLUME_DAYS_TO_COVER or not volume else float(days)
                ),
            ))
        except ValueError:
            continue
        seen.add(symbol)
    return rows


class FinraShortInterest:
    name = "finra_short_interest"
    category = Category.FUNDAMENTALS
    core = False
    best_effort = False
    cadence = Cadence.WEEKLY
    asset_types = frozenset({AssetType.STOCK})
    record_type = ShortInterest
    freshness = timedelta(days=20)
    scope = Scope.SYMBOLS
    canary = ("AAPL",)
    canary_requires_records = True
    max_symbols = None

    def __init__(self, client: httpx.Client, limiter: RateLimiter | None = None) -> None:
        self._client = client
        self._limiter = limiter

    def fetch(self, symbols: Sequence[str], as_of: datetime) -> list[ShortInterest]:
        wanted = requested_by_key(symbols)
        for day in settlement_dates(as_of):
            check_deadline()
            try:
                response = get_with_retries(
                    self._client, FINRA_SHORT_INTEREST_URL.format(day=day), limiter=self._limiter
                )
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in UNPUBLISHED:
                    continue
                raise
            return parse_short_interest(response.text, wanted)
        raise RuntimeError("no published FINRA short interest file in the last two months")
```

Register it in `collectors/registry.py`: add the import and append `FinraShortInterest(client),`.

Delete the unused fixture: `git rm --cached tests/fixtures/finra/consolidatedShortInterest_api_20260930.json 2>/dev/null; rm -f tests/fixtures/finra/consolidatedShortInterest_api_20260930.json`

- [ ] **Step 4: Run the tests to verify they pass**

Run: `scripts/in-docker.sh uv run pytest tests/unit/test_finra_short_interest.py tests/unit/test_registry.py -v`, then the full suite.
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
uv run --no-sync ruff check --fix .
git add src/advisor/collectors/finra_short_interest.py src/advisor/collectors/registry.py tests/unit/test_finra_short_interest.py tests/unit/test_registry.py tests/fixtures/finra/shrt20260930.csv
git commit -m "feat: add FINRA short interest source"
```
End the message with your `Co-Authored-By:` trailer.

---

### Task 7: yfinance analyst data (source 16)

**Files:**
- Create: `pipeline/src/advisor/collectors/yfinance_analyst.py`
- Modify: `pipeline/src/advisor/collectors/registry.py`, `pipeline/tests/unit/test_registry.py` (add a row)
- Test: `pipeline/tests/unit/test_yfinance_analyst.py`
- Commit: the existing fixtures `pipeline/tests/fixtures/yfinance_analyst/price_targets.json`, `recommendations.json` and `upgrades.json`

These are real AAPL captures from 2026-10-12. `upgrades.json` is trimmed to grades since 2026-07-01 (34 rows). The DataFrames were saved with `to_json(orient="split", date_format="iso")`.

**Interfaces:**
- Consumes:
  - `collect_per_symbol`, `DeadlineExceeded` and `PartialFetch` (base)
  - `to_yahoo` (`collectors/yfinance_bars.py`)
- Produces:
  - `AnalystView(symbol, target_mean, target_low, target_high, target_median, rec_strong_buy, rec_buy, rec_hold, rec_sell, rec_strong_sell, upgrades_30d, downgrades_30d, upgrades_90d, downgrades_90d, target_raises_30d, target_lowers_30d)`
  - `analyst_view(symbol, targets, recommendations, upgrades, as_of) -> AnalystView | None` (None means no analyst coverage at all)
  - `YFinanceAnalyst(load=None, sleep=time.sleep, pause=PAUSE_SECONDS)`: DAILY, SYMBOLS, freshness 3 days, canary `("AAPL",)` (requires records), best-effort, not core

- [ ] **Step 1: Write the failing test**

`pipeline/tests/unit/test_yfinance_analyst.py`:
```python
import json
from datetime import UTC, datetime

import pandas as pd
import pytest

from advisor.collectors.base import DeadlineExceeded, PartialFetch
from advisor.collectors.yfinance_analyst import YFinanceAnalyst, analyst_view

AS_OF = datetime(2026, 10, 12, 20, 0, tzinfo=UTC)


def aapl(fixtures_dir):
    base = fixtures_dir / "yfinance_analyst"
    targets = json.loads((base / "price_targets.json").read_text(encoding="utf-8"))
    recommendations = pd.read_json(base / "recommendations.json", orient="split")
    upgrades = pd.read_json(base / "upgrades.json", orient="split")
    upgrades.index.name = "GradeDate"
    return targets, recommendations, upgrades


def test_analyst_view_from_real_aapl_data(fixtures_dir):
    view = analyst_view("AAPL", *aapl(fixtures_dir), AS_OF)
    assert view.target_mean == pytest.approx(328.09384)
    assert (view.target_low, view.target_high, view.target_median) == (215.0, 405.0, 340.0)
    assert (view.rec_strong_buy, view.rec_buy, view.rec_hold, view.rec_sell, view.rec_strong_sell) == (
        6, 19, 13, 3, 3,
    )
    assert (view.upgrades_30d, view.downgrades_30d, view.upgrades_90d, view.downgrades_90d) == (0, 0, 2, 2)
    assert (view.target_raises_30d, view.target_lowers_30d) == (2, 1)


def test_no_coverage_yields_no_record():
    assert analyst_view("ZZZZ", {}, pd.DataFrame(), pd.DataFrame(), AS_OF) is None


def test_zero_or_missing_targets_are_treated_as_missing():
    view = analyst_view("X", {"mean": 0.0, "low": 12.5}, pd.DataFrame(), pd.DataFrame(), AS_OF)
    assert view.target_mean is None
    assert view.target_low == 12.5
    assert view.target_high is None


def test_fetch_maps_share_classes_and_pauses_between_symbols(fixtures_dir):
    data = aapl(fixtures_dir)
    loaded, sleeps = [], []

    def load(yahoo_symbol):
        loaded.append(yahoo_symbol)
        return data

    records = YFinanceAnalyst(load=load, sleep=sleeps.append).fetch(["BRK.B", "AAPL"], AS_OF)
    assert loaded == ["BRK-B", "AAPL"]
    assert [r.symbol for r in records] == ["BRK.B", "AAPL"]
    assert sleeps == [0.4]


def test_a_failing_symbol_is_a_partial_result(fixtures_dir):
    data = aapl(fixtures_dir)

    def load(yahoo_symbol):
        if yahoo_symbol == "BAD":
            raise KeyError("quoteSummary")
        return data

    with pytest.raises(PartialFetch, match="BAD") as caught:
        YFinanceAnalyst(load=load, sleep=lambda s: None).fetch(["AAPL", "BAD"], AS_OF)
    assert [r.symbol for r in caught.value.records] == ["AAPL"]


def test_rate_limiting_stops_the_loop(fixtures_dir):
    class YFRateLimitError(Exception):
        pass

    data = aapl(fixtures_dir)
    loaded = []

    def load(yahoo_symbol):
        loaded.append(yahoo_symbol)
        if yahoo_symbol == "BBB":
            raise YFRateLimitError("Too Many Requests")
        return data

    with pytest.raises(PartialFetch, match="stopped after 1 of 3 symbols"):
        YFinanceAnalyst(load=load, sleep=lambda s: None).fetch(["AAA", "BBB", "CCC"], AS_OF)
    assert loaded == ["AAA", "BBB"]


def test_the_run_deadline_ends_the_loop_with_what_was_gathered(fixtures_dir):
    data = aapl(fixtures_dir)

    def load(yahoo_symbol):
        if yahoo_symbol == "BBB":
            raise DeadlineExceeded("run time budget exhausted")
        return data

    with pytest.raises(PartialFetch, match="stopped after 1 of 3 symbols") as caught:
        YFinanceAnalyst(load=load, sleep=lambda s: None).fetch(["AAA", "BBB", "CCC"], AS_OF)
    assert [r.symbol for r in caught.value.records] == ["AAA"]
```

Add the row `"yfinance_analyst": (False, Scope.SYMBOLS, True),` to `EXPECTED` in `tests/unit/test_registry.py`.

- [ ] **Step 2: Run them to verify they fail**

Run: `scripts/in-docker.sh uv run pytest tests/unit/test_yfinance_analyst.py tests/unit/test_registry.py -v`
Expected: `ModuleNotFoundError`, and the registry is missing `yfinance_analyst`.

- [ ] **Step 3: Implement**

`pipeline/src/advisor/collectors/yfinance_analyst.py`:
```python
"""Analyst price targets, recommendation counts and rating changes via yfinance (source 16).

yfinance has no batch API for these, so the collector goes symbol by symbol with a short pause.
A symbol Yahoo doesn't cover (or doesn't know) comes back empty and yields no record.
"""

import logging
import math
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd
from pydantic import BaseModel, ConfigDict

from advisor.collectors.base import Cadence, Category, Scope, collect_per_symbol
from advisor.collectors.yfinance_bars import to_yahoo
from advisor.models import AssetType

TickerData = tuple[dict, pd.DataFrame, pd.DataFrame]  # price targets, recommendations, rating changes
Loader = Callable[[str], TickerData]
PAUSE_SECONDS = 0.4  # politeness between symbols; Yahoo publishes no limit


class AnalystView(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    target_mean: float | None = None
    target_low: float | None = None
    target_high: float | None = None
    target_median: float | None = None
    rec_strong_buy: int | None = None
    rec_buy: int | None = None
    rec_hold: int | None = None
    rec_sell: int | None = None
    rec_strong_sell: int | None = None
    upgrades_30d: int = 0
    downgrades_30d: int = 0
    upgrades_90d: int = 0
    downgrades_90d: int = 0
    target_raises_30d: int = 0
    target_lowers_30d: int = 0


def _yahoo_load(yahoo_symbol: str) -> TickerData:
    import yfinance as yf  # imported lazily: slow import, and tests inject a fake

    logging.getLogger("yfinance").setLevel(logging.CRITICAL)  # it logs an ERROR line per 404
    ticker = yf.Ticker(yahoo_symbol)
    return ticker.analyst_price_targets or {}, ticker.recommendations, ticker.upgrades_downgrades


def _price(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _graded(upgrades: pd.DataFrame | None, now: pd.Timestamp, days: int) -> tuple[int, int, int, int]:
    """(upgrades, downgrades, target raises, target lowers) graded in the last `days` days."""
    if upgrades is None or upgrades.empty:
        return 0, 0, 0, 0
    recent = upgrades[(upgrades.index >= now - pd.Timedelta(days=days)) & (upgrades.index <= now)]
    action = recent["Action"] if "Action" in recent else pd.Series(dtype=str)
    target = recent["priceTargetAction"] if "priceTargetAction" in recent else pd.Series(dtype=str)
    return (
        int((action == "up").sum()),
        int((action == "down").sum()),
        int((target == "Raises").sum()),
        int((target == "Lowers").sum()),
    )


def analyst_view(
    symbol: str,
    targets: dict | None,
    recommendations: pd.DataFrame | None,
    upgrades: pd.DataFrame | None,
    as_of: datetime,
) -> AnalystView | None:
    targets = targets or {}
    latest = None
    if recommendations is not None and not recommendations.empty and "period" in recommendations:
        current = recommendations[recommendations["period"] == "0m"]
        if not current.empty:
            latest = current.iloc[0]
    has_upgrades = upgrades is not None and not upgrades.empty
    if not targets and latest is None and not has_upgrades:
        return None

    def count(column: str) -> int | None:
        if latest is None or column not in latest or pd.isna(latest[column]):
            return None
        return int(latest[column])

    now = pd.Timestamp(as_of.astimezone(UTC).replace(tzinfo=None))  # grade dates are naive UTC
    up_30, down_30, raises_30, lowers_30 = _graded(upgrades, now, 30)
    up_90, down_90, _, _ = _graded(upgrades, now, 90)
    return AnalystView(
        symbol=symbol,
        target_mean=_price(targets.get("mean")),
        target_low=_price(targets.get("low")),
        target_high=_price(targets.get("high")),
        target_median=_price(targets.get("median")),
        rec_strong_buy=count("strongBuy"),
        rec_buy=count("buy"),
        rec_hold=count("hold"),
        rec_sell=count("sell"),
        rec_strong_sell=count("strongSell"),
        upgrades_30d=up_30,
        downgrades_30d=down_30,
        upgrades_90d=up_90,
        downgrades_90d=down_90,
        target_raises_30d=raises_30,
        target_lowers_30d=lowers_30,
    )


def _rate_limited(exc: Exception) -> bool:
    """yfinance's YFRateLimitError: stop asking Yahoo for the rest of this run."""
    return type(exc).__name__ == "YFRateLimitError"


class YFinanceAnalyst:
    name = "yfinance_analyst"
    category = Category.FUNDAMENTALS
    core = False
    best_effort = True
    cadence = Cadence.DAILY
    asset_types = frozenset({AssetType.STOCK})
    record_type = AnalystView
    freshness = timedelta(days=3)
    scope = Scope.SYMBOLS
    canary = ("AAPL",)
    canary_requires_records = True
    max_symbols = None

    def __init__(
        self,
        load: Loader | None = None,
        sleep: Callable[[float], None] = time.sleep,
        pause: float = PAUSE_SECONDS,
    ) -> None:
        self._load = load or _yahoo_load
        self._sleep = sleep
        self._pause = pause

    def fetch(self, symbols: Sequence[str], as_of: datetime) -> list[AnalystView]:
        def one(symbol: str) -> list[AnalystView]:
            view = analyst_view(symbol, *self._load(to_yahoo(symbol)), as_of)
            return [view] if view else []

        return collect_per_symbol(
            symbols, one, is_fatal=_rate_limited, pause=lambda: self._sleep(self._pause)
        )
```

Register it in `collectors/registry.py`: add the import and append `YFinanceAnalyst(),`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `scripts/in-docker.sh uv run pytest tests/unit/test_yfinance_analyst.py tests/unit/test_registry.py -v`, then the full suite.
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
uv run --no-sync ruff check --fix .
git add src/advisor/collectors/yfinance_analyst.py src/advisor/collectors/registry.py tests/unit/test_yfinance_analyst.py tests/unit/test_registry.py tests/fixtures/yfinance_analyst
git commit -m "feat: add yfinance analyst targets, ratings, and rating changes source"
```
End the message with your `Co-Authored-By:` trailer.

---

### Task 8: Finnhub helpers and recommendation trends (source 17)

**Files:**
- Create: `pipeline/src/advisor/collectors/finnhub.py`, `pipeline/src/advisor/collectors/finnhub_recommendations.py`
- Modify: `pipeline/src/advisor/collectors/registry.py`, `pipeline/tests/unit/test_registry.py` (add a row)
- Test: `pipeline/tests/unit/test_finnhub_recommendations.py`, plus a shared test helper in `pipeline/tests/fakes.py`
- Commit: the existing fixture `pipeline/tests/fixtures/finnhub/recommendation_AAPL.json`. It comes from Finnhub's documentation example; we have no live key.

**Interfaces:**
- Consumes: `get_with_retries`, `require`, `MissingCredential`, `RateLimiter` and `collect_per_symbol` (base)
- Produces:
  - In `finnhub`:
    - `FINNHUB_BASE_URL` and `FINNHUB_PER_MINUTE = 50`;
    - `finnhub_limiter() -> RateLimiter`, one per API key, shared by every Finnhub collector;
    - `finnhub_get(client, path, params, api_key, limiter)`, which sends the key in the `X-Finnhub-Token` header;
    - `finnhub_is_fatal(exc) -> bool`.
  - In `finnhub_recommendations`:
    - `RecommendationTrend(symbol, period, strong_buy, buy, hold, sell, strong_sell)`;
    - `latest_trend(symbol, rows) -> RecommendationTrend | None`;
    - `FinnhubRecommendations(client, api_key, limiter=None)` with a public `.limiter`: WEEKLY (trends change monthly), SYMBOLS, freshness 21 days, canary `("AAPL",)` (requires records), not core.
  - In `tests/fakes.py`: `route_client(routes, seen) -> httpx.Client`.

- [ ] **Step 1: Add the shared HTTP test helper**

Append to `pipeline/tests/fakes.py`, and add `import httpx` and `from typing import Any` to its imports:
```python
def route_client(routes: dict, seen: list[httpx.Request]) -> httpx.Client:
    """Mock client: `routes` maps (path, symbol param) or path to a JSON body or an httpx.Response."""

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body: Any = routes.get((request.url.path, request.url.params.get("symbol")))
        if body is None:
            body = routes.get(request.url.path)
        if body is None:
            return httpx.Response(404, json={"error": "not found"})
        return body if isinstance(body, httpx.Response) else httpx.Response(200, json=body)

    return httpx.Client(transport=httpx.MockTransport(handler))
```

- [ ] **Step 2: Write the failing test**

`pipeline/tests/unit/test_finnhub_recommendations.py`:
```python
import json
from datetime import UTC, date, datetime

import httpx
import pytest

from advisor.collectors.base import MissingCredential, RateLimiter
from advisor.collectors.finnhub_recommendations import (
    FinnhubRecommendations,
    RecommendationTrend,
    latest_trend,
)
from fakes import route_client

AS_OF = datetime(2026, 10, 14, 12, 15, tzinfo=UTC)
FAST = RateLimiter(per_minute=60_000, burst=1_000)
PATH = "/api/v1/stock/recommendation"


def rows(fixtures_dir) -> list:
    return json.loads((fixtures_dir / "finnhub" / "recommendation_AAPL.json").read_text(encoding="utf-8"))


def test_latest_trend_uses_the_newest_period(fixtures_dir):
    assert latest_trend("AAPL", rows(fixtures_dir)) == RecommendationTrend(
        symbol="AAPL", period=date(2025, 3, 1), strong_buy=13, buy=24, hold=7, sell=0, strong_sell=0
    )
    assert latest_trend("AAPL", []) is None


def test_fetch_sends_the_key_only_in_a_header(fixtures_dir):
    seen: list[httpx.Request] = []
    client = route_client({(PATH, "AAPL"): rows(fixtures_dir), (PATH, "NOREC"): []}, seen)
    records = FinnhubRecommendations(client, "key-123", FAST).fetch(["AAPL", "NOREC"], AS_OF)
    assert [r.symbol for r in records] == ["AAPL"]
    assert all(r.headers["X-Finnhub-Token"] == "key-123" for r in seen)
    assert all("key-123" not in str(r.url) for r in seen)


def test_a_missing_key_fails_before_any_request():
    seen: list[httpx.Request] = []
    with pytest.raises(MissingCredential, match="FINNHUB_API_KEY is not set"):
        FinnhubRecommendations(route_client({}, seen), None, FAST).fetch(["AAPL"], AS_OF)
    assert seen == []


def test_a_rejected_key_stops_at_the_first_symbol():
    seen: list[httpx.Request] = []
    client = route_client({PATH: httpx.Response(401, json={"error": "Invalid API key"})}, seen)
    with pytest.raises(httpx.HTTPStatusError) as caught:
        FinnhubRecommendations(client, "key-123", FAST).fetch(["AAPL", "MSFT"], AS_OF)
    assert len(seen) == 1
    assert "key-123" not in str(caught.value)
```

Add the row `"finnhub_recommendations": (False, Scope.SYMBOLS, True),` to `EXPECTED` in `tests/unit/test_registry.py`.

- [ ] **Step 3: Run them to verify they fail**

Run: `scripts/in-docker.sh uv run pytest tests/unit/test_finnhub_recommendations.py tests/unit/test_registry.py -v`
Expected: `ModuleNotFoundError`, and the registry is missing the row.

- [ ] **Step 4: Implement the shared helpers**

`pipeline/src/advisor/collectors/finnhub.py`:
```python
"""Finnhub helpers shared by its collectors: header auth, one limiter per key, error policy.

Free tier: 60 calls per minute per key, personal non-commercial use only.
"""

from collections.abc import Mapping
from typing import Any

import httpx

from advisor.collectors.base import MissingCredential, RateLimiter, get_with_retries, require

FINNHUB_BASE_URL = "https://finnhub.io/api/v1"
FINNHUB_PER_MINUTE = 50  # headroom under the free tier's 60 calls/minute per key


def finnhub_limiter() -> RateLimiter:
    return RateLimiter(per_minute=FINNHUB_PER_MINUTE, burst=5)


def finnhub_get(
    client: httpx.Client,
    path: str,
    params: Mapping[str, Any],
    api_key: str | None,
    limiter: RateLimiter,
) -> Any:
    """GET a Finnhub endpoint with the key in a header, so it never appears in a URL."""
    response = get_with_retries(
        client,
        f"{FINNHUB_BASE_URL}{path}",
        params=params,
        headers={"X-Finnhub-Token": require(api_key, "FINNHUB_API_KEY")},
        limiter=limiter,
    )
    return response.json()


def finnhub_is_fatal(exc: Exception) -> bool:
    """Errors that would hit every symbol: a missing or rejected key, or the rate limit."""
    if isinstance(exc, MissingCredential):
        return True
    return isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in (401, 403, 429)
```

- [ ] **Step 5: Implement the collector**

`pipeline/src/advisor/collectors/finnhub_recommendations.py`:
```python
"""Analyst recommendation trends from Finnhub (spec source 17). Trends change monthly."""

from collections.abc import Sequence
from datetime import date, datetime, timedelta

import httpx
from pydantic import BaseModel, ConfigDict, Field

from advisor.collectors.base import Cadence, Category, RateLimiter, Scope, collect_per_symbol, require
from advisor.collectors.finnhub import finnhub_get, finnhub_is_fatal, finnhub_limiter
from advisor.models import AssetType


class RecommendationTrend(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    period: date
    strong_buy: int = Field(ge=0)
    buy: int = Field(ge=0)
    hold: int = Field(ge=0)
    sell: int = Field(ge=0)
    strong_sell: int = Field(ge=0)


def latest_trend(symbol: str, rows: list) -> RecommendationTrend | None:
    """The newest month's counts; malformed rows are skipped."""
    trends: list[RecommendationTrend] = []
    for row in rows:
        try:
            trends.append(RecommendationTrend(
                symbol=symbol,
                period=date.fromisoformat(row["period"]),
                strong_buy=row["strongBuy"],
                buy=row["buy"],
                hold=row["hold"],
                sell=row["sell"],
                strong_sell=row["strongSell"],
            ))
        except (KeyError, TypeError, ValueError):
            continue
    return max(trends, key=lambda trend: trend.period) if trends else None


class FinnhubRecommendations:
    name = "finnhub_recommendations"
    category = Category.FUNDAMENTALS
    core = False
    best_effort = False
    cadence = Cadence.WEEKLY  # monthly data; weekly keeps it to ~300 calls a week
    asset_types = frozenset({AssetType.STOCK})
    record_type = RecommendationTrend
    freshness = timedelta(days=21)
    scope = Scope.SYMBOLS
    canary = ("AAPL",)
    canary_requires_records = True
    max_symbols = None

    def __init__(
        self, client: httpx.Client, api_key: str | None, limiter: RateLimiter | None = None
    ) -> None:
        self._client = client
        self._api_key = api_key
        self.limiter = limiter or finnhub_limiter()

    def fetch(self, symbols: Sequence[str], as_of: datetime) -> list[RecommendationTrend]:
        require(self._api_key, "FINNHUB_API_KEY")

        def one(symbol: str) -> list[RecommendationTrend]:
            rows = finnhub_get(
                self._client, "/stock/recommendation", {"symbol": symbol}, self._api_key, self.limiter
            )
            trend = latest_trend(symbol, rows if isinstance(rows, list) else [])
            return [trend] if trend else []

        return collect_per_symbol(symbols, one, is_fatal=finnhub_is_fatal)
```

- [ ] **Step 6: Register it with one shared Finnhub limiter**

In `collectors/registry.py`:
- add the imports `from advisor.collectors.finnhub import finnhub_limiter` and `from advisor.collectors.finnhub_recommendations import FinnhubRecommendations`;
- at the start of `build_registry`, add `finnhub = finnhub_limiter()  # one limiter per key, shared by every Finnhub collector`;
- append `FinnhubRecommendations(client, settings.finnhub_api_key, finnhub),` to the list.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `scripts/in-docker.sh uv run pytest tests/unit/test_finnhub_recommendations.py tests/unit/test_registry.py -v`, then the full suite.
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
uv run --no-sync ruff check --fix .
git add src/advisor/collectors/finnhub.py src/advisor/collectors/finnhub_recommendations.py src/advisor/collectors/registry.py tests/fakes.py tests/unit/test_finnhub_recommendations.py tests/unit/test_registry.py tests/fixtures/finnhub/recommendation_AAPL.json
git commit -m "feat: add Finnhub recommendation trends source with header auth"
```
End the message with your `Co-Authored-By:` trailer.

---

### Task 9: Finnhub earnings calendar and surprises (source 18, core)

**Files:**
- Create: `pipeline/src/advisor/collectors/finnhub_earnings.py`
- Modify: `pipeline/src/advisor/collectors/registry.py`, `pipeline/tests/unit/test_registry.py` (add a row and a limiter test)
- Test: `pipeline/tests/unit/test_finnhub_earnings.py`
- Commit: the existing fixtures `pipeline/tests/fixtures/finnhub/earnings_calendar.json` and `earnings_surprises_AAPL.json`. Both come from Finnhub's documentation examples.

**Interfaces:**
- Consumes:
  - `finnhub_get`, `finnhub_is_fatal` and `finnhub_limiter` (Task 8)
  - `requested_by_key` and `symbol_key` (Task 5)
  - `collect_per_symbol`, `PartialFetch` and `require` (base)
- Produces:
  - `EarningsRecord(symbol, kind: "scheduled" | "surprise", report_date, period_end, hour, year, quarter, eps_estimate, eps_actual, revenue_estimate, revenue_actual, surprise_percent)`
  - `parse_calendar(payload, wanted) -> list[EarningsRecord]`
  - `parse_surprises(symbol, rows) -> list[EarningsRecord]`
  - `FinnhubEarnings(client, api_key, limiter=None)`, with a public `.limiter`. It is DAILY, SYMBOLS, freshness 3 days, **core**, with canary `("AAPL",)` (`canary_requires_records=False`, because AAPL may have no report in the window).
  - Per run it makes one market-wide calendar call (`from` = today − 7 days, `to` = today + 21 days), plus one surprises call for each requested symbol that reported in the last 10 days.

- [ ] **Step 1: Write the failing test**

`pipeline/tests/unit/test_finnhub_earnings.py`:
```python
import json
from datetime import UTC, date, datetime

import httpx
import pytest

from advisor.collectors.base import PartialFetch, RateLimiter
from advisor.collectors.finnhub_earnings import FinnhubEarnings, parse_calendar, parse_surprises
from advisor.symbols import requested_by_key
from fakes import route_client

AS_OF = datetime(2026, 10, 14, 12, 15, tzinfo=UTC)
FAST = RateLimiter(per_minute=60_000, burst=1_000)
CALENDAR_PATH = "/api/v1/calendar/earnings"
SURPRISES_PATH = "/api/v1/stock/earnings"
CALENDAR = {"earningsCalendar": [
    {"date": "2026-10-09", "epsActual": 1.1, "epsEstimate": 1.0, "hour": "bmo", "quarter": 3,
     "revenueActual": 10, "revenueEstimate": 9, "symbol": "JUST", "year": 2026},
    {"date": "2026-10-20", "epsActual": None, "epsEstimate": 2.0, "hour": "amc", "quarter": 3,
     "revenueActual": None, "revenueEstimate": 20, "symbol": "SOON", "year": 2026},
    {"date": "2026-10-09", "epsActual": 3.0, "epsEstimate": 2.5, "hour": "amc", "quarter": 3,
     "revenueActual": 30, "revenueEstimate": 28, "symbol": "OTHER", "year": 2026},
]}


def fixture(fixtures_dir, name: str):
    return json.loads((fixtures_dir / "finnhub" / name).read_text(encoding="utf-8"))


def test_parse_calendar_from_the_docs_example(fixtures_dir):
    records = parse_calendar(fixture(fixtures_dir, "earnings_calendar.json"), requested_by_key(["AAPL"]))
    assert [(r.report_date, r.eps_actual, r.hour) for r in records] == [
        (date(2020, 1, 28), 4.99, "amc"), (date(2019, 10, 30), 3.03, "amc"),
    ]
    assert records[0].revenue_actual == 91819000000
    assert all(r.kind == "scheduled" for r in records)


def test_parse_surprises_from_the_docs_example(fixtures_dir):
    records = parse_surprises("AAPL", fixture(fixtures_dir, "earnings_surprises_AAPL.json"))
    assert len(records) == 3
    first = records[0]
    assert (first.kind, first.period_end, first.eps_actual, first.eps_estimate, first.surprise_percent) == (
        "surprise", date(2023, 3, 31), 1.88, 1.9744, -4.7812,
    )


def test_fetch_asks_one_calendar_window_and_surprises_only_for_fresh_reports(fixtures_dir):
    seen: list[httpx.Request] = []
    client = route_client({
        CALENDAR_PATH: CALENDAR,
        (SURPRISES_PATH, "JUST"): fixture(fixtures_dir, "earnings_surprises_AAPL.json"),
    }, seen)
    records = FinnhubEarnings(client, "key-123", FAST).fetch(["SOON", "JUST"], AS_OF)
    calendar_call = seen[0]
    assert (calendar_call.url.params["from"], calendar_call.url.params["to"]) == ("2026-10-07", "2026-11-04")
    assert "symbol" not in calendar_call.url.params
    assert [r.url.params.get("symbol") for r in seen[1:]] == ["JUST"]
    assert sorted((r.symbol, r.kind) for r in records) == [
        ("JUST", "scheduled"), ("JUST", "surprise"), ("JUST", "surprise"), ("JUST", "surprise"),
        ("SOON", "scheduled"),
    ]


def test_failed_surprises_keep_the_calendar_records():
    client = route_client({
        CALENDAR_PATH: CALENDAR,
        SURPRISES_PATH: httpx.Response(400, json={"error": "bad request"}),
    }, [])
    with pytest.raises(PartialFetch) as caught:
        FinnhubEarnings(client, "key-123", FAST).fetch(["JUST", "SOON"], AS_OF)
    assert sorted(r.symbol for r in caught.value.records) == ["JUST", "SOON"]
```

In `tests/unit/test_registry.py`:
- add the row `"finnhub_earnings": (True, Scope.SYMBOLS, False),` to `EXPECTED`;
- append:
```python
def test_finnhub_collectors_share_one_rate_limiter():
    registry = build()
    assert registry["finnhub_earnings"].limiter is registry["finnhub_recommendations"].limiter
```

- [ ] **Step 2: Run them to verify they fail**

Run: `scripts/in-docker.sh uv run pytest tests/unit/test_finnhub_earnings.py tests/unit/test_registry.py -v`
Expected: `ModuleNotFoundError`, and the registry is missing `finnhub_earnings`.

- [ ] **Step 3: Implement**

`pipeline/src/advisor/collectors/finnhub_earnings.py`:
```python
"""Earnings calendar and EPS surprises from Finnhub (spec source 18, a core source).

One market-wide calendar call covers every symbol for a window around today (the free tier allows
about a month per call). Surprises are fetched only for requested symbols that just reported.
"""

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict

from advisor.collectors.base import (
    Cadence,
    Category,
    PartialFetch,
    RateLimiter,
    Scope,
    collect_per_symbol,
    require,
)
from advisor.collectors.finnhub import finnhub_get, finnhub_is_fatal, finnhub_limiter
from advisor.models import ET, AssetType
from advisor.symbols import requested_by_key, symbol_key

CALENDAR_PAST_DAYS = 7
CALENDAR_FUTURE_DAYS = 21
SURPRISE_LOOKBACK_DAYS = 10


class EarningsRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    kind: Literal["scheduled", "surprise"]
    report_date: date | None = None  # scheduled: the announcement date
    period_end: date | None = None  # surprise: the fiscal period it reports
    hour: str | None = None  # "bmo" before open, "amc" after close, "dmh" during market hours
    year: int | None = None
    quarter: int | None = None
    eps_estimate: float | None = None
    eps_actual: float | None = None
    revenue_estimate: float | None = None
    revenue_actual: float | None = None
    surprise_percent: float | None = None


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def parse_calendar(payload: Any, wanted: Mapping[str, str]) -> list[EarningsRecord]:
    rows = payload.get("earningsCalendar") if isinstance(payload, dict) else None
    records: list[EarningsRecord] = []
    for row in rows or []:
        try:
            symbol = wanted.get(symbol_key(row["symbol"]))
            if symbol is None:
                continue
            records.append(EarningsRecord(
                symbol=symbol,
                kind="scheduled",
                report_date=date.fromisoformat(row["date"]),
                hour=row.get("hour") or None,
                year=row.get("year"),
                quarter=row.get("quarter"),
                eps_estimate=_number(row.get("epsEstimate")),
                eps_actual=_number(row.get("epsActual")),
                revenue_estimate=_number(row.get("revenueEstimate")),
                revenue_actual=_number(row.get("revenueActual")),
            ))
        except (KeyError, TypeError, ValueError):
            continue
    return records


def parse_surprises(symbol: str, rows: Any) -> list[EarningsRecord]:
    records: list[EarningsRecord] = []
    for row in rows if isinstance(rows, list) else []:
        try:
            records.append(EarningsRecord(
                symbol=symbol,
                kind="surprise",
                period_end=date.fromisoformat(row["period"]),
                year=row.get("year"),
                quarter=row.get("quarter"),
                eps_actual=_number(row.get("actual")),
                eps_estimate=_number(row.get("estimate")),
                surprise_percent=_number(row.get("surprisePercent")),
            ))
        except (KeyError, TypeError, ValueError):
            continue
    return records


class FinnhubEarnings:
    name = "finnhub_earnings"
    category = Category.FUNDAMENTALS
    core = True
    best_effort = False
    cadence = Cadence.DAILY
    asset_types = frozenset({AssetType.STOCK})
    record_type = EarningsRecord
    freshness = timedelta(days=3)
    scope = Scope.SYMBOLS
    canary = ("AAPL",)
    canary_requires_records = False  # AAPL may have nothing scheduled in the window
    max_symbols = None

    def __init__(
        self, client: httpx.Client, api_key: str | None, limiter: RateLimiter | None = None
    ) -> None:
        self._client = client
        self._api_key = api_key
        self.limiter = limiter or finnhub_limiter()

    def fetch(self, symbols: Sequence[str], as_of: datetime) -> list[EarningsRecord]:
        require(self._api_key, "FINNHUB_API_KEY")
        today = as_of.astimezone(ET).date()
        payload = finnhub_get(
            self._client,
            "/calendar/earnings",
            {
                "from": (today - timedelta(days=CALENDAR_PAST_DAYS)).isoformat(),
                "to": (today + timedelta(days=CALENDAR_FUTURE_DAYS)).isoformat(),
            },
            self._api_key,
            self.limiter,
        )
        scheduled = parse_calendar(payload, requested_by_key(symbols))
        just_reported = {
            r.symbol
            for r in scheduled
            if r.eps_actual is not None
            and r.report_date is not None
            and timedelta(0) <= today - r.report_date <= timedelta(days=SURPRISE_LOOKBACK_DAYS)
        }
        reported = [s for s in dict.fromkeys(symbols) if s in just_reported]  # keep priority order

        def one(symbol: str) -> list[EarningsRecord]:
            rows = finnhub_get(
                self._client, "/stock/earnings", {"symbol": symbol, "limit": 4},
                self._api_key, self.limiter,
            )
            return parse_surprises(symbol, rows)

        try:
            surprises = collect_per_symbol(reported, one, is_fatal=finnhub_is_fatal)
        except PartialFetch as exc:
            raise PartialFetch([*scheduled, *exc.records], str(exc)) from exc
        except Exception as exc:
            if not scheduled:
                raise
            raise PartialFetch(
                scheduled, f"surprises failed: {type(exc).__name__}: {exc}"[:300]
            ) from exc
        return [*scheduled, *surprises]
```

In `collectors/registry.py`, add the import and append `FinnhubEarnings(client, settings.finnhub_api_key, finnhub),`. It reuses the `finnhub` limiter variable from Task 8.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `scripts/in-docker.sh uv run pytest tests/unit/test_finnhub_earnings.py tests/unit/test_registry.py -v`, then the full suite.
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
uv run --no-sync ruff check --fix .
git add src/advisor/collectors/finnhub_earnings.py src/advisor/collectors/registry.py tests/unit/test_finnhub_earnings.py tests/unit/test_registry.py tests/fixtures/finnhub/earnings_calendar.json tests/fixtures/finnhub/earnings_surprises_AAPL.json
git commit -m "feat: add Finnhub earnings calendar and surprises source"
```
End the message with your `Co-Authored-By:` trailer.

---

### Task 10: FMP valuation ratios (source 15)

**Files:**
- Create: `pipeline/src/advisor/collectors/fmp_ratios.py`
- Modify: `pipeline/src/advisor/collectors/registry.py`, `pipeline/tests/unit/test_registry.py` (add a row)
- Test: `pipeline/tests/unit/test_fmp_ratios.py`
- Commit: the existing fixture `pipeline/tests/fixtures/fmp/ratios_ttm_AAPL.json`, which comes from FMP's documented example. Delete the unused `fixtures/fmp/ratios_annual_AMZN.json`.

**Interfaces:**
- Consumes:
  - `get_with_retries`, `require`, `MissingCredential`, `RateLimiter` and `collect_per_symbol` (base)
  - `run_collector` and `max_symbols` (Task 3)
- Produces:
  - `Valuation(symbol, pe, ps, gross_margin, operating_margin, fcf_yield, debt_to_equity, current_ratio)`
  - `parse_ratios(symbol, payload) -> Valuation | None`
  - `FmpRatios(client, api_key, limiter=None)`, with a public `.limiter`:
    - WEEKLY, SYMBOLS, freshness 21 days, canary `("AAPL",)` (requires records), not core;
    - `max_symbols = MAX_SYMBOLS_PER_RUN = 110`. The free plan allows 250 calls a day; two runs use at most 220, and the daily health check uses 1.
  - `FMP_RATIOS_TTM_URL`

- [ ] **Step 1: Write the failing test**

`pipeline/tests/unit/test_fmp_ratios.py`:
```python
import json
from datetime import UTC, datetime

import httpx
import pytest

from advisor.collectors.base import MissingCredential, RateLimiter
from advisor.collectors.cache import DiskCache
from advisor.collectors.fmp_ratios import FMP_RATIOS_TTM_URL, MAX_SYMBOLS_PER_RUN, FmpRatios, parse_ratios
from advisor.collectors.runner import SourceState, run_collector
from fakes import route_client

AS_OF = datetime(2026, 10, 14, 12, 15, tzinfo=UTC)
FAST = RateLimiter(per_minute=60_000, burst=1_000)
PATH = "/stable/ratios-ttm"


def payload(fixtures_dir) -> list:
    return json.loads((fixtures_dir / "fmp" / "ratios_ttm_AAPL.json").read_text(encoding="utf-8"))


def test_parse_ratios_from_the_documented_example(fixtures_dir):
    valuation = parse_ratios("AAPL", payload(fixtures_dir))
    assert valuation.pe == pytest.approx(36.27890581198107)
    assert valuation.ps == pytest.approx(9.652042838036241)
    assert valuation.gross_margin == pytest.approx(0.4690516410716045)
    assert valuation.operating_margin == pytest.approx(0.31970799762591884)
    assert valuation.fcf_yield == pytest.approx(1 / 40.66949284194113)
    assert valuation.debt_to_equity == pytest.approx(1.5241072518411023)
    assert valuation.current_ratio == pytest.approx(0.8932929222186667)
    assert parse_ratios("AAPL", []) is None


def test_a_non_positive_price_to_fcf_gives_no_fcf_yield():
    assert parse_ratios("X", [{"priceToFreeCashFlowRatioTTM": -12.0}]).fcf_yield is None


def test_fetch_sends_the_symbol_and_key_as_params_and_skips_unavailable_symbols(fixtures_dir):
    seen: list[httpx.Request] = []
    client = route_client({
        (PATH, "AAPL"): payload(fixtures_dir),
        (PATH, "EMPTY"): [],
        (PATH, "PAID"): httpx.Response(402, json={"message": "Premium endpoint"}),
    }, seen)
    records = FmpRatios(client, "key-123", FAST).fetch(["AAPL", "EMPTY", "PAID"], AS_OF)
    assert [r.symbol for r in records] == ["AAPL"]
    assert str(seen[0].url).startswith(FMP_RATIOS_TTM_URL)
    assert seen[0].url.params["apikey"] == "key-123"


def test_a_rejected_key_is_fatal_and_never_appears_in_the_error():
    client = route_client({PATH: httpx.Response(401, json={"Error Message": "Invalid API KEY"})}, [])
    with pytest.raises(httpx.HTTPStatusError) as caught:
        FmpRatios(client, "key-123", FAST).fetch(["AAPL", "MSFT"], AS_OF)
    assert "key-123" not in str(caught.value)


def test_a_missing_key_fails_before_any_request():
    seen: list[httpx.Request] = []
    with pytest.raises(MissingCredential, match="FMP_API_KEY is not set"):
        FmpRatios(route_client({}, seen), None, FAST).fetch(["AAPL"], AS_OF)
    assert seen == []


def test_the_daily_cap_spreads_symbols_over_later_runs_within_the_week(fixtures_dir, tmp_path):
    assert MAX_SYMBOLS_PER_RUN == 110
    seen: list[httpx.Request] = []
    body = payload(fixtures_dir)
    collector = FmpRatios(route_client({PATH: body}, seen), "key-123", FAST)
    collector.max_symbols = 2
    cache = DiskCache(tmp_path, clock=lambda: AS_OF)
    symbols = ["AAPL", "MSFT", "NVDA"]
    run_collector(collector, symbols, AS_OF, cache=cache, state=SourceState())
    run_collector(collector, symbols, AS_OF, cache=cache, state=SourceState())
    assert [r.url.params["symbol"] for r in seen] == ["AAPL", "MSFT", "NVDA"]
```

Add the row `"fmp_ratios": (False, Scope.SYMBOLS, True),` to `EXPECTED` in `tests/unit/test_registry.py`.

- [ ] **Step 2: Run them to verify they fail**

Run: `scripts/in-docker.sh uv run pytest tests/unit/test_fmp_ratios.py tests/unit/test_registry.py -v`
Expected: `ModuleNotFoundError`, and the registry is missing `fmp_ratios`.

- [ ] **Step 3: Implement**

`pipeline/src/advisor/collectors/fmp_ratios.py`:
```python
"""Trailing-twelve-month valuation ratios from Financial Modeling Prep (spec source 15).

Free plan: 250 calls per day, US symbols, personal non-commercial use. FMP accepts the key only
as a query parameter, so it is passed via `params=`; error text never includes query strings.
The weekly cadence plus `max_symbols` spreads a 300-symbol shortlist over several runs.
"""

import math
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict

from advisor.collectors.base import (
    Cadence,
    Category,
    MissingCredential,
    RateLimiter,
    Scope,
    collect_per_symbol,
    get_with_retries,
    require,
)
from advisor.models import AssetType

FMP_RATIOS_TTM_URL = "https://financialmodelingprep.com/stable/ratios-ttm"
MAX_SYMBOLS_PER_RUN = 110  # two runs a day plus the health check stay under 250 calls
FMP_PER_MINUTE = 120
NOT_ON_FREE_PLAN = 402


class Valuation(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    pe: float | None = None
    ps: float | None = None
    gross_margin: float | None = None
    operating_margin: float | None = None
    fcf_yield: float | None = None
    debt_to_equity: float | None = None
    current_ratio: float | None = None


def parse_ratios(symbol: str, payload: Any) -> Valuation | None:
    if not isinstance(payload, list) or not payload or not isinstance(payload[0], dict):
        return None
    row = payload[0]

    def number(key: str) -> float | None:
        value = row.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return float(value) if math.isfinite(value) else None

    price_to_fcf = number("priceToFreeCashFlowRatioTTM")
    return Valuation(
        symbol=symbol,
        pe=number("priceToEarningsRatioTTM"),
        ps=number("priceToSalesRatioTTM"),
        gross_margin=number("grossProfitMarginTTM"),
        operating_margin=number("operatingProfitMarginTTM"),
        fcf_yield=1 / price_to_fcf if price_to_fcf and price_to_fcf > 0 else None,
        debt_to_equity=number("debtToEquityRatioTTM"),
        current_ratio=number("currentRatioTTM"),
    )


def fmp_is_fatal(exc: Exception) -> bool:
    """Errors that would hit every symbol: a missing or rejected key, or the rate limit."""
    if isinstance(exc, MissingCredential):
        return True
    return isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in (401, 403, 429)


class FmpRatios:
    name = "fmp_ratios"
    category = Category.FUNDAMENTALS
    core = False
    best_effort = False
    cadence = Cadence.WEEKLY
    asset_types = frozenset({AssetType.STOCK})
    record_type = Valuation
    freshness = timedelta(days=21)
    scope = Scope.SYMBOLS
    canary = ("AAPL",)
    canary_requires_records = True
    max_symbols: int | None = MAX_SYMBOLS_PER_RUN

    def __init__(
        self, client: httpx.Client, api_key: str | None, limiter: RateLimiter | None = None
    ) -> None:
        self._client = client
        self._api_key = api_key
        self.limiter = limiter or RateLimiter(per_minute=FMP_PER_MINUTE, burst=5)

    def fetch(self, symbols: Sequence[str], as_of: datetime) -> list[Valuation]:
        key = require(self._api_key, "FMP_API_KEY")

        def one(symbol: str) -> list[Valuation]:
            try:
                payload = get_with_retries(
                    self._client, FMP_RATIOS_TTM_URL, params={"symbol": symbol, "apikey": key},
                    limiter=self.limiter,
                ).json()
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == NOT_ON_FREE_PLAN:
                    return []
                raise
            valuation = parse_ratios(symbol, payload)
            return [valuation] if valuation else []

        capped = list(symbols)[: self.max_symbols] if self.max_symbols else list(symbols)
        return collect_per_symbol(capped, one, is_fatal=fmp_is_fatal)
```

In `collectors/registry.py`, add the import and append `FmpRatios(client, settings.fmp_api_key),`.

Delete the unused fixture: `rm -f tests/fixtures/fmp/ratios_annual_AMZN.json`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `scripts/in-docker.sh uv run pytest tests/unit/test_fmp_ratios.py tests/unit/test_registry.py -v`, then the full suite.
Expected: all pass.

- [ ] **Step 5: Final verification**

Run: `uv run --no-sync ruff check . && scripts/in-docker.sh uv run pytest -q`
Expected: lint is clean and every test passes. Report the exact count. `git status` must show no untracked fixtures left under `tests/fixtures/`, except `tests/fixtures/sec/`, which Plan 2b-SEC commits.

- [ ] **Step 6: Commit**

```bash
git add src/advisor/collectors/fmp_ratios.py src/advisor/collectors/registry.py tests/unit/test_fmp_ratios.py tests/unit/test_registry.py tests/fixtures/fmp/ratios_ttm_AAPL.json
git commit -m "feat: add FMP valuation ratios source capped to the free daily quota"
```
End the message with your `Co-Authored-By:` trailer.
