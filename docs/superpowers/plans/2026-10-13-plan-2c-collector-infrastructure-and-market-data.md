# Stock Advisor — Plan 2c: Collector Infrastructure and Market Data Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:**
- Finish the collector infrastructure that earlier plans deferred (`docs/superpowers/deferred.md`, "Plan 2c, Task 0" and "Plan 2c"):
  - a run deadline;
  - a written collector contract, with stock-market coverage;
  - a cadence-window cache;
  - a concurrent health check;
  - lean failing runs.
- Add five keyless sources:
  - FINRA short volume (#14) and short interest (#13);
  - Yahoo analyst data (#16);
  - Yahoo earnings dates and surprises (#17, core);
  - Bank of Canada Valet (#7).

**Architecture:**
- **Run deadline.** A context-variable deadline bounds every source. `get_with_retries`, long collector loops and the Yahoo price download loop all honour it.
- **Market coverage.** Each collector declares the stock markets it covers. The enrichment stage only sends it symbols of those markets, so TSX symbols never reach US-only FINRA files.
- **Cadence-window cache.** The runner serves DAILY and WEEKLY collectors from entries saved in the current ET day or ISO week, and fetches only missing symbols. An optional `max_symbols` caps one call; the rest wait for a later run, holdings first.
- **New sources.** Each is one module behind the `Collector` protocol, with one shared rate limiter per provider. Each is tested against real responses recorded on 2026-10-12 to 2026-10-14. Those fixtures are already committed under `pipeline/tests/fixtures/`.

**Tech Stack:** Python 3.12, uv, httpx, pydantic v2, pandas, yfinance 1.7, pandas-market-calendars, pytest, ruff, Postgres 16 (Docker), GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-10-09-stock-advisor-design.md` (rev 2). Read:
- §2 R7;
- §3 Scheduling (the 30-minute deadline);
- §4.1;
- §4.2 sources 7 and 13–17;
- §5.1 (the Ownership and flow, Earnings and Macro regime rows);
- §7.2;
- §10.

Plans 1, 2a and 2b built everything this plan modifies. The work deferred to this plan is in `docs/superpowers/deferred.md`.

## Roadmap

| Plan | Delivers |
|---|---|
| 2a, 2b | Done |
| **2c (this plan)** | Deadline, contract and market coverage, cadence cache, concurrent health check, lean failing runs; FINRA ×2, Yahoo analyst, Yahoo earnings, Bank of Canada |
| 2d | SEC: XBRL facts, 8-K, Form 4, 13F, 13D/G. The research is in `.superpowers/research/plan-2b/sec.md` and the fixtures in `.superpowers/research/plan-2c-fixtures/sec/` (both git-ignored) |
| 2e | Macro, options, crypto, on-chain, catalysts, and Canadian short positions |
| 2f | News and social sources, de-duplication, ticker mapping, FinBERT |

## Plan-level decisions

These refine the spec without changing what it asks for. The spec edit that goes with them is in the same commit as this plan.

- **`markets` on the collector protocol.** Each collector declares `markets: frozenset[Market]`, the stock markets it covers, and `enrich.symbols_for` sends it only those markets' stock symbols. Spec §4.1 gains this attribute. Universe and market-wide collectors declare it too, as documentation; it only filters SYMBOLS-scope stock symbols.
- **No credentials in this plan.** No source here needs one (R7). `MissingCredential` and the SEC contact setting arrive with Plan 2d, which is the only plan that uses them.
- **One rate limiter per provider**, built in `build_registry`:
  - FINRA's two collectors share 60 requests/minute.
  - Yahoo's per-symbol collectors (analyst and earnings) share 120/minute.
  - The Yahoo price download is a bulk `yf.download` and is bounded by the deadline instead.
- **Yahoo analyst data is capped at 200 symbols per call** (spec §7.2 lists it as a capped source). With two runs a day and holdings first, about 400 symbols a day are refreshed, and anything not refetched is served from a cache up to 3 days old.
- **Earnings: one record per report** (date, EPS estimate, actual, surprise). Plan 3 derives "days to the next report" and "last EPS surprise" (spec §5.1).
  - When Yahoo lists one date twice, the reported row wins.
  - Symbols Yahoo doesn't cover return `None`, which means no records, not a failure. Verified live on 2026-10-14 for SPY, XIU.TO and an unknown ticker.
  - The source is core (spec §4.2).
- **Bank of Canada:**
  - The source is named `boc_valet`. It is market-wide and fetched once a day with a 120-day lookback, enough for a 63-session trend.
  - It reads four series:
    - `FXUSDCAD`, the daily USD/CAD rate;
    - `V39079`, the policy rate;
    - `BD.CDN.2YR.DQ.YLD`, the 2-year benchmark yield;
    - `BD.CDN.10YR.DQ.YLD`, the 10-year benchmark yield.
  - It is not core.
- **Lean failing runs.** When any market's universe is too small to publish, the run skips the bulk price fetch: about 7,400 Yahoo requests during a TMX outage. It still retries the owner's unpriced holdings. Failure reasons then name only the universes.
- **Run budget:** 30 minutes (spec §3), measured from the start of the run. GitHub kills the job at 40.

## Global Constraints

- Python `>=3.12,<3.13`, managed by uv, with `uv.lock` committed. Running cost is $0/month.
- **R7:** "Free data sources only, with no API keys and no accounts." No collector, setting or secret may need one.
- **Collector contract.** Task 2 writes it into `collectors/base.py`:
  - Collectors never touch the database.
  - Records of SYMBOLS-scope collectors carry the canonical requested symbol (`BRK.B`, `RCI-B.TO`). Provider formats (`BRK/B`, `BRKB`, `BRK-B`) are mapped inside the collector.
  - A collector raises `PartialFetch` for per-request failures. An empty one counts as a failure.
  - HTTP goes through `get_with_retries`. Error text never contains query strings.
  - Long loops honour the run deadline.
  - A collector is sent only symbols of the markets it declares.
- **Holdings first (spec §3 rule 5, §7.2):** symbol lists keep their priority order, and capped sources spend their quota on holdings first.
- **Registering a source:** every new source gets a registry entry and a row in `EXPECTED` in `pipeline/tests/unit/test_registry.py`.
- **Migrations are append-only.** This plan needs none.
- **Tests use the recorded real responses** under `pipeline/tests/fixtures/{finra,yfinance_analyst,yfinance_earnings,boc}/`, which were committed with this plan. Tests make no live network calls.
- **Tests and lint run in Docker,** from the repo root. Windows Application Control blocks psycopg's DLLs on the host, and the host `.venv` under OneDrive is fragile.
  - Tests: `pipeline/scripts/in-docker.sh uv run pytest -q`.
  - Lint: `pipeline/scripts/in-docker.sh uv run ruff check .`.
- **Stage explicit file paths only.** Never use `git add -A`, `git add .`, or a bare directory.
- Never bypass git hooks: no `--no-verify`, no `-n`.
- Every commit message ends with a `Co-Authored-By:` trailer naming the model that actually wrote the commit.

## Review Focus

These are the five inputs most likely to hurt the owner that no earlier test exercises. Each has a test in its owning task.

1. **A slow source, or a slow Yahoo, past the 30-minute budget.** The source ends FAILED or PARTIAL and the run still finishes and publishes, instead of the job being killed with an abandoned run. *Tests: Task 1 (tracker, run, and the Yahoo download loop).*
2. **A FINRA file that isn't published yet** (HTTP 403 on the run day, a weekend or a holiday) falls back to the newest published file instead of failing. *Tests: Tasks 6 and 7.*
3. **Provider symbol formats come back canonical, and TSX symbols never reach US-only sources.** `BRK/B`, `BRKB` and `BRK-B` must come back as `BRK.B`. Without the market filter, a FINRA key collision like `RY.TO` → `RYTO` could even attach another company's data. *Tests: Tasks 2, 6, 7 and 8.*
4. **Yahoo lists one earnings date twice, or has no coverage for a symbol.** The result is one report per date with the reported row winning. No coverage means no records, so the core earnings source doesn't degrade every run over an ETF on the watchlist. *Tests: Task 9.*
5. **The capped analyst source.** Symbols past `max_symbols` are not marked as fetched for the window. They are served from older cache and fetched on a later run, holdings first. *Tests: Tasks 3 and 8.*

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `collectors/base.py` | Deadline (`deadline`, `time_left`, `check_deadline`, `DeadlineExceeded`); contract docstring; `collect_per_symbol`; protocol attributes `markets` and `max_symbols` | 1, 2, 3 |
| `collectors/tracker.py` | Runs every call inside the run deadline | 1 |
| `collectors/yfinance_bars.py` | Stops the download loop at the deadline; `markets`, `max_symbols` | 1, 2, 3 |
| `collectors/nasdaq_symbols.py`, `collectors/tmx_symbols.py` | `markets`, `max_symbols` | 2, 3 |
| `enrich.py` | Market filter in `symbols_for` | 2 |
| `collectors/cache.py`, `collectors/runner.py` | Cadence windows, empty markers, `max_symbols`, partial backfill, `use_window` | 3 |
| `health.py` | Concurrent checks with a per-source budget; rows written as they finish | 4 |
| `run.py` | Run budget; lean failing runs | 1, 5 |
| `symbols.py` (new) | Provider-neutral symbol keys | 6 |
| `collectors/finra_short_volume.py`, `collectors/finra_short_interest.py` (new) | Sources 14 and 13 | 6, 7 |
| `collectors/yahoo.py` (new) | Shared Yahoo helpers: `YAHOO_PER_MINUTE`, `rate_limited` | 8 |
| `collectors/yfinance_analyst.py`, `collectors/yfinance_earnings.py` (new) | Sources 16 and 17 | 8, 9 |
| `collectors/boc_valet.py` (new) | Source 7 | 10 |
| `collectors/registry.py` | New sources and one limiter per provider | 6–10 |
| `pipeline/tests/fakes.py` | `FakeCollector.markets`, `FakeCollector.max_symbols` | 2, 3 |
| `docs/superpowers/deferred.md` | Plan 2c items resolved; items left for later recorded | 10 |

All paths above are under `pipeline/src/advisor/` unless they start with `pipeline/` or `docs/`.

---

### Task 1: Run deadline

**Files:**
- Modify: `pipeline/src/advisor/collectors/base.py`, `pipeline/src/advisor/collectors/tracker.py`, `pipeline/src/advisor/collectors/yfinance_bars.py`, `pipeline/src/advisor/run.py`
- Test: `pipeline/tests/unit/test_base.py`, `pipeline/tests/unit/test_tracker.py`, `pipeline/tests/unit/test_yfinance_bars.py`, `pipeline/tests/integration/test_run.py`

**Interfaces:**
- Produces in `base`:
  - `BUDGET_EXHAUSTED = "run time budget exhausted"`;
  - `DeadlineExceeded(Exception)`;
  - `deadline(at: float | None)`, a context manager;
  - `time_left(clock=time.monotonic) -> float | None`;
  - `check_deadline(clock=time.monotonic) -> None`;
  - `get_with_retries(..., clock=time.monotonic)`, which stops before a request, or a retry wait, that would overrun the deadline.
- Produces elsewhere:
  - `SourceTracker(..., *, deadline_at: float | None = None)`;
  - `run.RUN_BUDGET_SECONDS = 30 * 60`;
  - `execute_run(..., run_budget: float = RUN_BUDGET_SECONDS)`.

- [ ] **Step 1: Write the failing tests**

Append to `pipeline/tests/unit/test_base.py`, and change its base import to `from advisor.collectors.base import DeadlineExceeded, RateLimiter, check_deadline, deadline, get_with_retries`:

```python
def test_check_deadline_is_a_no_op_without_a_deadline():
    check_deadline()


def test_deadline_applies_only_inside_its_block():
    clock = FakeClock()
    clock.now = 100.0
    with deadline(50.0):
        with pytest.raises(DeadlineExceeded, match="run time budget exhausted"):
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

Append to `pipeline/tests/unit/test_tracker.py`, and add `import time` and `from advisor.collectors.base import check_deadline` to its imports:

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

Append to `pipeline/tests/unit/test_yfinance_bars.py`, and change its base import to `from advisor.collectors.base import DeadlineExceeded, PartialFetch`:

```python
def test_fetch_stops_at_the_run_deadline_with_what_it_has(monkeypatch):
    monkeypatch.setattr("advisor.collectors.yfinance_bars.SYMBOLS_PER_DOWNLOAD", 5)
    lefts = iter([60.0, 0.0])  # time left before the first and the second download
    monkeypatch.setattr("advisor.collectors.yfinance_bars.time_left", lambda: next(lefts))
    calls = []

    def fake_download(tickers, start, end):
        calls.append(tickers)
        return two_ticker_frame()

    symbols = ["AAPL", "BRK.B", "C", "D", "E", "F", "G", "H", "I", "J"]
    with pytest.raises(PartialFetch, match="run time budget exhausted; 1 of 2 not tried") as caught:
        YFinanceBars(download=fake_download).fetch(symbols, AS_OF)
    assert len(calls) == 1
    assert {b.symbol for b in caught.value.records} == {"AAPL", "BRK.B"}


def test_fetch_past_the_deadline_before_any_download_raises(monkeypatch):
    monkeypatch.setattr("advisor.collectors.yfinance_bars.time_left", lambda: 0.0)

    def must_not_download(tickers, start, end):
        raise AssertionError("downloaded past the deadline")

    with pytest.raises(DeadlineExceeded, match="run time budget exhausted; 1 of 1 not tried"):
        YFinanceBars(download=must_not_download).fetch(["AAPL"], AS_OF)
```

Append to `pipeline/tests/integration/test_run.py`, and change its base import to `from advisor.collectors.base import PartialFetch, Scope, check_deadline`:

```python
def test_a_source_past_the_run_budget_fails_and_the_run_still_publishes(db, tmp_path):
    extra = {
        "slow": FakeCollector("slow", core=False, records_for=lambda syms: (check_deadline(), [])[1])
    }
    outcome = execute_run(
        make_deps(db, tmp_path, extra=extra), RunKind.PRE_OPEN, NOW, min_universe=SMALL, run_budget=0
    )
    assert outcome.status is RunStatus.SUCCESS  # the price fakes never consult the deadline
    assert run_row(db, outcome.run_id)["published"] is True
    assert ("slow", "failed") in health(db, outcome.run_id)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `pipeline/scripts/in-docker.sh uv run pytest tests/unit/test_base.py tests/unit/test_tracker.py tests/unit/test_yfinance_bars.py tests/integration/test_run.py -q`
Expected: ImportError for `DeadlineExceeded`, `check_deadline` and `deadline`.

- [ ] **Step 3: Implement the deadline in `base.py`**

Add `import contextlib` and `from contextvars import ContextVar` to the imports. Change the `collections.abc` import to `from collections.abc import Callable, Iterator, Mapping, Sequence`.

Add this after the `PartialFetch` class:

```python
BUDGET_EXHAUSTED = "run time budget exhausted"
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
        raise DeadlineExceeded(BUDGET_EXHAUSTED)
```

In `get_with_retries`:
1. Add the parameter `clock: Callable[[], float] = time.monotonic` after `sleep`.
2. At the top of the loop body, right after `retry_after: float | None = None`, replace the existing `if limiter is not None: limiter.acquire()` lines with:

```python
        check_deadline(clock)
        if limiter is not None:
            limiter.acquire()
            check_deadline(clock)  # a busy shared limiter may have slept past the deadline
```

3. Replace the end-of-loop wait block (`if attempt < attempts - 1: ... sleep(...)`) with:

```python
        if attempt < attempts - 1:
            backoff = base_delay * 2**attempt
            wait = backoff if retry_after is None else max(backoff, retry_after)
            left = time_left(clock)
            if left is not None and wait >= left:
                raise DeadlineExceeded(
                    f"{BUDGET_EXHAUSTED} while retrying {_safe_url(url)}"
                ) from last_error
            sleep(wait)
```

- [ ] **Step 4: Stop the Yahoo download loop at the deadline**

In `collectors/yfinance_bars.py`, change the base import to `from advisor.collectors.base import BUDGET_EXHAUSTED, Cadence, Category, DeadlineExceeded, PartialFetch, Scope, time_left`. Then replace `YFinanceBars.fetch` with:

```python
    def fetch(self, symbols: Sequence[str], as_of: datetime) -> list[DailyBar]:
        unique = sorted(set(symbols))
        start = (as_of - LOOKBACK).astimezone(ET).date()
        end = as_of.astimezone(ET).date() + timedelta(days=1)
        chunks = [
            unique[i : i + SYMBOLS_PER_DOWNLOAD] for i in range(0, len(unique), SYMBOLS_PER_DOWNLOAD)
        ]
        bars: list[DailyBar] = []
        empty = streak = not_tried = 0
        stopped = ""
        for done, chunk in enumerate(chunks):
            left = time_left()
            if left is not None and left <= 0:  # yfinance sends one request per ticker
                stopped, not_tried = BUDGET_EXHAUSTED, len(chunks) - done
                break
            mapping = {to_yahoo(s): s for s in chunk}
            got = parse_frame(self._download(list(mapping), start, end), mapping)
            if got:
                streak = 0
            elif len(chunk) >= MIN_SYMBOLS_FOR_EMPTY_CHECK:
                empty += 1
                streak += 1
            bars.extend(got)
            if streak >= MAX_CONSECUTIVE_EMPTY and done + 1 < len(chunks):
                stopped = f"stopped after {MAX_CONSECUTIVE_EMPTY} consecutive empty Yahoo downloads"
                not_tried = len(chunks) - done - 1
                break
        if stopped:
            message = f"{stopped}; {not_tried} of {len(chunks)} not tried"
            if bars:
                raise PartialFetch(bars, message)
            if stopped == BUDGET_EXHAUSTED:
                raise DeadlineExceeded(message)
            raise RuntimeError(message)
        if empty and not bars:
            raise RuntimeError(
                f"yfinance returned no bars for {len(unique)} symbols (blocked or rate-limited?)"
            )
        if empty:
            raise PartialFetch(bars, f"{empty} of {len(chunks)} Yahoo downloads returned no bars")
        return bars
```

The existing tests for the empty-download and consecutive-empty rules must keep passing unchanged.

- [ ] **Step 5: Apply the deadline in the tracker and the orchestrator**

In `collectors/tracker.py`:
- import `deadline` from `advisor.collectors.base`;
- add a keyword-only parameter to `__init__`, after `states`: put `*,` before it, and declare `deadline_at: float | None = None`. Store it as `self._deadline_at`;
- in `run`, wrap the `run_collector(...)` call inside the existing `try` with `with deadline(self._deadline_at):`.

In `run.py`:
- add `import time`;
- add `RUN_BUDGET_SECONDS = 30 * 60  # spec §3; GitHub kills the job at 40 minutes` after `MIN_PRICED_FRACTION`;
- add the keyword-only parameter `run_budget: float = RUN_BUDGET_SECONDS` to `execute_run`, after `min_universe`;
- pass `deadline_at=time.monotonic() + run_budget` to `SourceTracker(...)`.

- [ ] **Step 6: Run the tests and lint**

Run: `pipeline/scripts/in-docker.sh uv run pytest -q`
Expected: every test passes.

Run: `pipeline/scripts/in-docker.sh uv run ruff check .`
Expected: `All checks passed!`

- [ ] **Step 7: Commit**

```bash
git add pipeline/src/advisor/collectors/base.py pipeline/src/advisor/collectors/tracker.py \
  pipeline/src/advisor/collectors/yfinance_bars.py pipeline/src/advisor/run.py \
  pipeline/tests/unit/test_base.py pipeline/tests/unit/test_tracker.py \
  pipeline/tests/unit/test_yfinance_bars.py pipeline/tests/integration/test_run.py
git commit -m "feat: bound every source and the Yahoo price loop by a run deadline"
```

End the message with your `Co-Authored-By:` trailer.

---

### Task 2: Collector contract, market coverage and per-symbol collection

**Files:**
- Modify: `pipeline/src/advisor/collectors/base.py`, `pipeline/src/advisor/enrich.py`, `pipeline/src/advisor/collectors/nasdaq_symbols.py`, `pipeline/src/advisor/collectors/tmx_symbols.py`, `pipeline/src/advisor/collectors/yfinance_bars.py`, `pipeline/tests/fakes.py`
- Test: `pipeline/tests/unit/test_base.py`, `pipeline/tests/unit/test_enrich.py`, `pipeline/tests/unit/test_registry.py` (rewrite as a table)

**Interfaces:**
- Consumes: `check_deadline` and `DeadlineExceeded` (Task 1), and `PartialFetch`.
- Produces:
  - protocol attribute `markets: frozenset[Market]`;
  - `base.collect_per_symbol(symbols, fetch_one, *, is_fatal=..., pause=None) -> list[BaseModel]`;
  - `FakeCollector.markets`, which defaults to both markets;
  - the registry test table `EXPECTED`, keyed by name with values `(core, scope, canary_requires_records, markets)`. Later tasks add rows.

- [ ] **Step 1: Write the failing tests**

Append to `pipeline/tests/unit/test_base.py`. Add `PartialFetch` and `collect_per_symbol` to its base import, and change the fakes import to `from fakes import FakeClock, info`:

```python
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


class Throttled(Exception):
    pass


def test_a_fatal_error_before_any_record_is_raised_as_is():
    def one(symbol):
        raise Throttled("Too Many Requests")

    with pytest.raises(Throttled):
        collect_per_symbol(["A", "B"], one, is_fatal=lambda exc: isinstance(exc, Throttled))


def test_a_fatal_error_after_some_records_stops_with_a_partial_result():
    calls = []

    def one(symbol):
        calls.append(symbol)
        if symbol == "B":
            raise Throttled("Too Many Requests")
        return [info(symbol)]

    with pytest.raises(PartialFetch, match="stopped after 1 of 3 symbols") as caught:
        collect_per_symbol(["A", "B", "C"], one, is_fatal=lambda exc: isinstance(exc, Throttled))
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

Append to `pipeline/tests/unit/test_enrich.py`, and change its models import to `from advisor.models import AssetType, Market`:

```python
TWO_MARKETS = EnrichTargets(
    priority_stocks=["OTCX", "SHOP.TO"], crypto=["BTC"], ranked_stocks=["AAA", "RY.TO"]
)


def test_symbols_for_sends_only_the_markets_a_collector_covers():
    us_only = FakeCollector("us_only", markets=frozenset({Market.US}))
    tsx_only = FakeCollector("tsx_only", markets=frozenset({Market.TSX}))
    both = FakeCollector("both")
    mixed = FakeCollector(
        "mixed",
        asset_types=frozenset({AssetType.STOCK, AssetType.CRYPTO}),
        markets=frozenset({Market.US}),
    )
    assert symbols_for(us_only, TWO_MARKETS) == ["OTCX", "AAA"]
    assert symbols_for(tsx_only, TWO_MARKETS) == ["SHOP.TO", "RY.TO"]
    assert symbols_for(both, TWO_MARKETS) == ["OTCX", "SHOP.TO", "AAA", "RY.TO"]
    assert symbols_for(mixed, TWO_MARKETS) == ["OTCX", "BTC", "AAA"]  # crypto is never filtered
```

Replace `pipeline/tests/unit/test_registry.py` entirely with:

```python
from pathlib import Path

import httpx

from advisor.collectors.base import Scope
from advisor.collectors.registry import build_registry
from advisor.config import Settings
from advisor.models import Market

US = frozenset({Market.US})
TSX = frozenset({Market.TSX})
BOTH = frozenset({Market.US, Market.TSX})

# name: (core, scope, canary_requires_records, markets). Every new source adds a row.
EXPECTED = {
    "nasdaq_symbols": (True, Scope.UNIVERSE, True, US),
    "tmx_symbols": (True, Scope.UNIVERSE, True, TSX),
    "yfinance_bars": (True, Scope.SYMBOLS, True, BOTH),
}


def build() -> dict:
    with httpx.Client() as client:
        return build_registry(Settings("postgresql://x", Path(".cache")), client)


def test_registry_matches_the_expected_sources():
    registry = build()
    assert {
        name: (c.core, c.scope, c.canary_requires_records, c.markets)
        for name, c in registry.items()
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

Run: `pipeline/scripts/in-docker.sh uv run pytest tests/unit/test_base.py tests/unit/test_enrich.py tests/unit/test_registry.py -q`
Expected:
- ImportError for `collect_per_symbol`;
- `FakeCollector` has no `markets` field;
- the collectors have no `markets` attribute.

- [ ] **Step 3: Write the contract, the protocol attribute and the helper in `base.py`**

Replace the module docstring of `collectors/base.py` with:

```python
"""Shared building blocks for collectors: the interface, rate limiting, HTTP retries, deadlines.

Collector contract (every source module follows it):
- `fetch(symbols, as_of)` returns validated records or raises; it never touches the database.
- No source needs an API key or an account (spec R7).
- SYMBOLS scope: every record has `symbol` equal to the canonical requested symbol ("BRK.B",
  "RCI-B.TO"); map provider formats ("BRK/B", "BRKB", "BRK-B") in and out inside the collector.
- `markets` names the stock markets a source covers; it is only sent symbols of those markets.
- Raise PartialFetch(records, error) when some requests failed but others succeeded; an empty
  PartialFetch counts as a failure. `collect_per_symbol` does this for per-symbol APIs.
- HTTP goes through `get_with_retries`: it honours the run deadline, backs off on 429/5xx, and
  never puts query strings into error text.
- Long loops honour the run deadline (`check_deadline()` or `time_left()`) between items.
- A provider's collectors share one RateLimiter, built in the registry.
- `canary_requires_records` is True only for sources that always return data for their canary.
"""
```

Add `Market` to the models import (`from advisor.models import AssetType, Market`). In the `Collector` protocol, add this after `asset_types`:

```python
    markets: frozenset[Market]  # stock markets covered; only their stock symbols are sent
```

Add this after `check_deadline`:

```python
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

- [ ] **Step 4: Declare markets on every collector and the fake, and filter in `symbols_for`**

Add a class attribute after `asset_types` in each collector, and import `Market` from `advisor.models` where it isn't already imported:
- `nasdaq_symbols.py`: `markets = frozenset({Market.US})`
- `tmx_symbols.py`: `markets = frozenset({Market.TSX})`
- `yfinance_bars.py`: `markets = frozenset({Market.US, Market.TSX})`

In `pipeline/tests/fakes.py`, add this field to `FakeCollector` after `asset_types`. `Market` is already imported there.

```python
    markets: frozenset[Market] = frozenset(Market)
```

In `enrich.py`:
- add `from advisor.markets import market_of`;
- replace `symbols_for` with the code below;
- extend the module docstring with this sentence: "A collector only gets stock symbols of the markets it covers."

```python
def symbols_for(collector: Collector, targets: EnrichTargets) -> list[str]:
    if collector.scope is not Scope.SYMBOLS:
        return []

    def covered(stocks: Sequence[str]) -> list[str]:
        return [s for s in stocks if market_of(s) in collector.markets]

    symbols: list[str] = []
    stocks = AssetType.STOCK in collector.asset_types
    if stocks:
        symbols += covered(targets.priority_stocks)
    if AssetType.CRYPTO in collector.asset_types:
        symbols += targets.crypto  # held and watched crypto outrank the stock shortlist
    if stocks:
        symbols += covered(targets.ranked_stocks)
    return symbols
```

- [ ] **Step 5: Run the tests and lint**

Run: `pipeline/scripts/in-docker.sh uv run pytest -q`
Expected: every test passes, including the existing `symbols_for` and run tests: the fakes cover both markets by default.

Run: `pipeline/scripts/in-docker.sh uv run ruff check .`
Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add pipeline/src/advisor/collectors/base.py pipeline/src/advisor/enrich.py \
  pipeline/src/advisor/collectors/nasdaq_symbols.py pipeline/src/advisor/collectors/tmx_symbols.py \
  pipeline/src/advisor/collectors/yfinance_bars.py pipeline/tests/fakes.py \
  pipeline/tests/unit/test_base.py pipeline/tests/unit/test_enrich.py pipeline/tests/unit/test_registry.py
git commit -m "feat: write the collector contract, declare market coverage, add per-symbol collection"
```

End the message with your `Co-Authored-By:` trailer.

---

### Task 3: Cadence-window cache, per-call symbol cap, partial backfill

**Files:**
- Modify: `pipeline/src/advisor/collectors/cache.py`, `pipeline/src/advisor/collectors/runner.py` (full replacement), `pipeline/src/advisor/collectors/base.py` (protocol attribute and docstring line), `pipeline/src/advisor/collectors/nasdaq_symbols.py`, `pipeline/src/advisor/collectors/tmx_symbols.py`, `pipeline/src/advisor/collectors/yfinance_bars.py`, `pipeline/tests/fakes.py`
- Test: `pipeline/tests/unit/test_runner.py`, `pipeline/tests/unit/test_cache.py`

**Interfaces:**
- Produces:
  - `DiskCache.get_entry(source, key, record_type) -> tuple[datetime, list[BaseModel]] | None`;
  - `runner.in_window(cadence, saved_at, as_of) -> bool`;
  - `run_collector(..., use_window: bool = True)`;
  - protocol attribute `max_symbols: int | None`. Existing collectors and `FakeCollector` set `None`.
- Behaviour:
  - DAILY and WEEKLY collectors with `freshness` skip symbols already fetched in this ET day or ISO week.
  - An OK per-symbol empty answer is remembered for the window.
  - `max_symbols` caps one call. Capped-out symbols are served from older cache and are not marked as fetched.
  - A PARTIAL per-symbol answer is backfilled from cache.

- [ ] **Step 1: Add the protocol attribute everywhere**

- In `collectors/base.py`:
  - add to the `Collector` protocol, after `canary_requires_records`: `max_symbols: int | None  # most symbols one call may fetch; the rest wait for a later run`;
  - append to the module docstring's contract list: `- DAILY/WEEKLY collectors with freshness are served from this window's cache, and only missing symbols are fetched; max_symbols caps one call (see runner).`
- In `nasdaq_symbols.py`, `tmx_symbols.py` and `yfinance_bars.py`, add the class attribute `max_symbols = None` after `canary_requires_records`.
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
- change `universe_collector`'s default to `cadence=Cadence.PER_RUN`; window behaviour is tested separately below;
- add `in_window` to the runner import;
- append:

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

Run: `pipeline/scripts/in-docker.sh uv run pytest tests/unit/test_runner.py tests/unit/test_cache.py -q`
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

Replace `pipeline/src/advisor/collectors/runner.py` in full:

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

- [ ] **Step 6: Run the tests and lint**

Run: `pipeline/scripts/in-docker.sh uv run pytest -q`
Expected: every test passes, including all existing runner, tracker, health and run tests.

Run: `pipeline/scripts/in-docker.sh uv run ruff check .`
Expected: `All checks passed!`

- [ ] **Step 7: Commit**

```bash
git add pipeline/src/advisor/collectors/cache.py pipeline/src/advisor/collectors/runner.py \
  pipeline/src/advisor/collectors/base.py pipeline/src/advisor/collectors/nasdaq_symbols.py \
  pipeline/src/advisor/collectors/tmx_symbols.py pipeline/src/advisor/collectors/yfinance_bars.py \
  pipeline/tests/fakes.py pipeline/tests/unit/test_runner.py pipeline/tests/unit/test_cache.py
git commit -m "feat: serve daily and weekly sources from the cadence window and cap symbols per call"
```

End the message with your `Co-Authored-By:` trailer.

---

### Task 4: Concurrent health check with a per-source budget

**Files:**
- Modify: `pipeline/src/advisor/health.py`
- Test: `pipeline/tests/unit/test_health.py`

**Interfaces:**
- Consumes: `deadline` (Task 1); `run_collector(..., use_window=False)` (Task 3).
- Produces:
  - `health.check_source(collector, cache, state, now, *, budget=SOURCE_BUDGET_SECONDS) -> tuple[CollectorResult, int]`;
  - `health.iter_checks(collectors, cache, states, now, *, workers=HEALTH_WORKERS, budget=...)`, which yields each source's result as soon as it finishes;
  - `health.check_sources(...) -> list`, keeping the existing call shape;
  - `main`, which writes each row as its source finishes;
  - `HEALTH_WORKERS = 8` and `SOURCE_BUDGET_SECONDS = 120.0`.

- [ ] **Step 1: Write the failing tests**

Append to `pipeline/tests/unit/test_health.py`. Change its datetime import to `from datetime import UTC, date, datetime, timedelta`, and its base import to `from advisor.collectors.base import Cadence, CollectorStatus, check_deadline`:

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

Run: `pipeline/scripts/in-docker.sh uv run pytest tests/unit/test_health.py -q`
Expected:
- `check_sources()` got an unexpected keyword `budget`;
- the second test makes only one call, because the cadence cache served it.

- [ ] **Step 3: Rewrite the checking functions in `health.py`**

Keep the module docstring, and add this line to it: "Sources are checked concurrently, each within its own time budget, and rows are written as they finish." Replace the imports and `check_sources` with the code below. Change `main` only as Step 4 says.

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

Replace the body of `main`, keeping its signature:

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

- [ ] **Step 5: Run the tests and lint**

Run: `pipeline/scripts/in-docker.sh uv run pytest -q`
Expected: every test passes. The existing health tests key their rows by source name, so completion order doesn't matter.

Run: `pipeline/scripts/in-docker.sh uv run ruff check .`
Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add pipeline/src/advisor/health.py pipeline/tests/unit/test_health.py
git commit -m "feat: check sources concurrently with a per-source budget and write rows as they finish"
```

End the message with your `Co-Authored-By:` trailer.

---

### Task 5: Lean failing runs

**Files:**
- Modify: `pipeline/src/advisor/run.py`
- Test: `pipeline/tests/integration/test_run.py`

**Interfaces:**
- Consumes: `execute_run`, `MarketPass` and `check_market` (Plan 2b).
- Produces:
  - `MarketPass.failed_reasons(self, *, prices_checked: bool = True) -> list[str]`, which leaves out the price reason when prices were not checked;
  - in `execute_run`, a run whose universe check fails skips the bulk price fetch but still retries unpriced priority symbols.

- [ ] **Step 1: Write the failing tests**

In `pipeline/tests/integration/test_run.py`, in `test_a_truncated_universe_fails_the_run_and_keeps_that_markets_symbols`:
- replace `outcome = execute_run(make_deps(db, tmp_path, extra=extra), ...)` with `deps = make_deps(db, tmp_path, extra=extra)`, followed by `outcome = execute_run(deps, ...)` with the same remaining arguments;
- add this line at the end of the test:

```python
    assert deps.collectors["yfinance_bars"].calls == []  # no bulk Yahoo fetch for a run that cannot publish
```

Then append:

```python
def test_a_run_that_cannot_publish_still_retries_unpriced_holdings(db, tmp_path):
    hold(db)

    def records_for(symbols):  # phase 1 misses the holding; the retry finds it
        if list(symbols) == ["OTCX"] and not prices.calls[:-1]:
            return []
        return [b for s in symbols for b in history(s, 70, start=FRESH_START)]

    prices = FakeCollector("yfinance_bars", best_effort=True, records_for=records_for)
    deps = make_deps(db, tmp_path, prices=prices)
    outcome = execute_run(
        deps, RunKind.PRE_OPEN, NOW, min_universe={Market.US: 3, Market.TSX: 300}
    )

    assert prices.calls == [["OTCX"], ["OTCX"]]  # the retry, but no bulk fetch
    assert outcome.status is RunStatus.FAILED
    assert outcome.summary["failed_reason"] == ["TSX: universe too small (2 < 300)"]
    assert outcome.summary["priority_unpriced"] == []
    assert "OTCX" in market_features(db, outcome.run_id)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `pipeline/scripts/in-docker.sh uv run pytest tests/integration/test_run.py -q`
Expected:
- the truncated-universe test fails: Yahoo was called with the US and TSX universes;
- the new test fails, because the second call included the whole universe.

- [ ] **Step 3: Skip the bulk fetch when a universe is too small**

In `run.py`, replace `MarketPass.failed_reasons` with:

```python
    def failed_reasons(self, *, prices_checked: bool = True) -> list[str]:
        reasons = []
        if not self.universe_ok:
            reasons.append(
                f"{self.market}: universe too small ({self.universe} < {self.min_universe})"
            )
        empty = self.symbols == 0  # an empty market has no prices to report on
        if prices_checked and not self.prices_ok and not (empty and not self.universe_ok):
            reasons.append(
                f"{self.market}: too few fresh priced symbols ({self.fresh} of {self.symbols})"
            )
        return reasons
```

In `execute_run`, phase 2:
1. Right after the universes loop, add:

```python
        # A run that cannot publish skips the bulk fetch (about 7,400 Yahoo requests during a
        # TMX outage) but still retries the owner's unpriced holdings.
        universe_ok = all(len(universes[m]) >= limits[m] for m in Market)
```

2. Change the `rest = ...` line to:

```python
        rest = (
            sorted({r.symbol for u in universes.values() for r in u} - set(priority))
            if universe_ok
            else []
        )
```

3. Delete the later line `universe_ok = all(p.universe_ok for p in passes.values())`. `prices_ok` stays as it is.
4. In the failure branch, change the list comprehension to `p.failed_reasons(prices_checked=universe_ok)`.

- [ ] **Step 4: Run the tests and lint**

Run: `pipeline/scripts/in-docker.sh uv run pytest -q`
Expected: every test passes. `test_default_minimums_come_from_the_markets_table` and `test_an_empty_market_reports_only_its_universe_reason` still get exactly the universe reasons.

Run: `pipeline/scripts/in-docker.sh uv run ruff check .`
Expected: `All checks passed!`

- [ ] **Step 5: Commit**

```bash
git add pipeline/src/advisor/run.py pipeline/tests/integration/test_run.py
git commit -m "feat: skip the bulk price fetch for a run that cannot publish"
```

End the message with your `Co-Authored-By:` trailer.

---

### Task 6: Provider-neutral symbol keys and FINRA short volume (source 14)

**Files:**
- Create: `pipeline/src/advisor/symbols.py`, `pipeline/src/advisor/collectors/finra_short_volume.py`
- Modify: `pipeline/src/advisor/collectors/registry.py`, `pipeline/tests/unit/test_registry.py` (add a row)
- Test: `pipeline/tests/unit/test_finra_short_volume.py`
- Fixture (already committed): `pipeline/tests/fixtures/finra/CNMSshvol20261009.txt`. This is the real 2026-10-09 file trimmed to 73 rows; its trailer still holds the real row count, 12278.

**Interfaces:**
- Produces:
  - `symbols.symbol_key(symbol) -> str` (`"BRK/B"`, `"BRK-B"`, `"BRK.B"` and `"brkb"` all give `"BRKB"`);
  - `symbols.requested_by_key(symbols) -> dict[str, str]`.
- Produces in `finra_short_volume`:
  - `ShortVolume(symbol, trade_date, short_volume, short_exempt_volume, total_volume)`;
  - `candidate_days(as_of) -> list[date]`;
  - `parse_short_volume(text, wanted) -> list[ShortVolume]`;
  - `FINRA_SHORT_VOLUME_URL`;
  - `FinraShortVolume(client, limiter=None)`, with:
    - name `finra_short_volume`, DAILY, SYMBOLS, markets US;
    - freshness 4 days;
    - canary `("AAPL",)` (requires records);
    - not core.
- Produces in the registry: `FINRA_PER_MINUTE = 60` and one FINRA limiter shared by both FINRA collectors.

- [ ] **Step 1: Write the failing tests**

Create `pipeline/tests/unit/test_finra_short_volume.py`:

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
from advisor.models import Market
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


def test_finra_covers_only_us_stocks():
    assert FinraShortVolume.markets == frozenset({Market.US})


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

In `pipeline/tests/unit/test_registry.py`, add this row to `EXPECTED`:

```python
    "finra_short_volume": (False, Scope.SYMBOLS, True, US),
```

- [ ] **Step 2: Run them to verify they fail**

Run: `pipeline/scripts/in-docker.sh uv run pytest tests/unit/test_finra_short_volume.py tests/unit/test_registry.py -q`
Expected: `ModuleNotFoundError` for `advisor.collectors.finra_short_volume` and `advisor.symbols`, and the registry lacks `finra_short_volume`.

- [ ] **Step 3: Implement `symbols.py`**

Create `pipeline/src/advisor/symbols.py`:

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

Create `pipeline/src/advisor/collectors/finra_short_volume.py`:

```python
"""Daily short-sale volume from FINRA's consolidated Reg SHO file (spec source 14, US only).

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
from advisor.models import ET, AssetType, Market
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
    markets = frozenset({Market.US})
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

- [ ] **Step 5: Register it with a shared FINRA limiter**

In `collectors/registry.py`:
- change the module docstring to `"""Every collector the pipeline runs, keyed by name, with one rate limiter per provider."""`;
- change the base import to `from advisor.collectors.base import Collector, RateLimiter`, and add `from advisor.collectors.finra_short_volume import FinraShortVolume`;
- add the constant `FINRA_PER_MINUTE = 60` below the imports;
- in `build_registry`, create the limiter and add the collector after `YFinanceBars()`. Lay the list out one collector per line:

```python
def build_registry(settings: Settings, client: httpx.Client) -> dict[str, Collector]:
    finra = RateLimiter(per_minute=FINRA_PER_MINUTE, burst=2)  # shared by FINRA's collectors
    collectors: list[Collector] = [
        NasdaqSymbols(client),
        TmxSymbols(client),
        YFinanceBars(),
        FinraShortVolume(client, finra),
    ]
    return {collector.name: collector for collector in collectors}
```

- [ ] **Step 6: Run the tests and lint**

Run: `pipeline/scripts/in-docker.sh uv run pytest -q`
Expected: every test passes.

Run: `pipeline/scripts/in-docker.sh uv run ruff check .`
Expected: `All checks passed!`

- [ ] **Step 7: Commit**

```bash
git add pipeline/src/advisor/symbols.py pipeline/src/advisor/collectors/finra_short_volume.py \
  pipeline/src/advisor/collectors/registry.py pipeline/tests/unit/test_finra_short_volume.py \
  pipeline/tests/unit/test_registry.py
git commit -m "feat: add FINRA daily short volume source"
```

End the message with your `Co-Authored-By:` trailer.

---

### Task 7: FINRA short interest (source 13)

**Files:**
- Create: `pipeline/src/advisor/collectors/finra_short_interest.py`
- Modify: `pipeline/src/advisor/collectors/registry.py`, `pipeline/tests/unit/test_registry.py` (add a row)
- Test: `pipeline/tests/unit/test_finra_short_interest.py`
- Fixture (already committed): `pipeline/tests/fixtures/finra/shrt20260930.csv`. This is the real 2026-09-30 settlement file, trimmed. Every value is quoted, the delimiter is `|`, and there are 14 columns.

**Interfaces:**
- Consumes: `symbols.symbol_key` and `requested_by_key` (Task 6); `schedule.previous_sessions(end, count)`, which defaults to the NYSE; the registry's FINRA limiter (Task 6).
- Produces:
  - `ShortInterest(symbol, settlement_date, short_interest, previous_short_interest, avg_daily_volume, days_to_cover)`;
  - `settlement_dates(as_of, months=2) -> list[date]`;
  - `parse_short_interest(text, wanted) -> list[ShortInterest]`;
  - `FINRA_SHORT_INTEREST_URL` and `HEADER`;
  - `FinraShortInterest(client, limiter=None)`, with:
    - WEEKLY, SYMBOLS, markets US;
    - freshness 20 days;
    - canary `("AAPL",)` (requires records);
    - not core.

- [ ] **Step 1: Write the failing test**

Create `pipeline/tests/unit/test_finra_short_interest.py`:

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

In `pipeline/tests/unit/test_registry.py`, add this row to `EXPECTED`:

```python
    "finra_short_interest": (False, Scope.SYMBOLS, True, US),
```

- [ ] **Step 2: Run them to verify they fail**

Run: `pipeline/scripts/in-docker.sh uv run pytest tests/unit/test_finra_short_interest.py tests/unit/test_registry.py -q`
Expected: `ModuleNotFoundError`, and the registry lacks `finra_short_interest`.

- [ ] **Step 3: Implement**

Create `pipeline/src/advisor/collectors/finra_short_interest.py`:

```python
"""Bi-monthly short interest from FINRA's settlement files (spec source 13, US only).

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
from advisor.models import ET, AssetType, Market
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
    markets = frozenset({Market.US})
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

Register it in `collectors/registry.py`: import `FinraShortInterest`, and add `FinraShortInterest(client, finra),` after `FinraShortVolume(client, finra),`.

- [ ] **Step 4: Run the tests and lint**

Run: `pipeline/scripts/in-docker.sh uv run pytest -q`
Expected: every test passes.

Run: `pipeline/scripts/in-docker.sh uv run ruff check .`
Expected: `All checks passed!`

- [ ] **Step 5: Commit**

```bash
git add pipeline/src/advisor/collectors/finra_short_interest.py pipeline/src/advisor/collectors/registry.py \
  pipeline/tests/unit/test_finra_short_interest.py pipeline/tests/unit/test_registry.py
git commit -m "feat: add FINRA short interest source"
```

End the message with your `Co-Authored-By:` trailer.

---

### Task 8: Yahoo analyst data (source 16) and the shared Yahoo limiter

**Files:**
- Create: `pipeline/src/advisor/collectors/yahoo.py`, `pipeline/src/advisor/collectors/yfinance_analyst.py`
- Modify: `pipeline/src/advisor/collectors/registry.py`, `pipeline/tests/unit/test_registry.py` (add a row)
- Test: `pipeline/tests/unit/test_yfinance_analyst.py`
- Fixtures (already committed): `pipeline/tests/fixtures/yfinance_analyst/price_targets.json`, `recommendations.json` and `upgrades.json`. These are real AAPL captures from 2026-10-12. `upgrades.json` is trimmed to grades since 2026-07-01 (34 rows). The DataFrames were saved with `to_json(orient="split", date_format="iso")`.

**Interfaces:**
- Consumes: `collect_per_symbol` and `PartialFetch` (base); `to_yahoo` (`collectors/yfinance_bars.py`).
- Produces:
  - `yahoo.YAHOO_PER_MINUTE = 120` and `yahoo.rate_limited(exc) -> bool`;
  - `AnalystView(symbol, target_mean, target_low, target_high, target_median, rec_strong_buy, rec_buy, rec_hold, rec_sell, rec_strong_sell, upgrades_30d, downgrades_30d, upgrades_90d, downgrades_90d, target_raises_30d, target_lowers_30d)`;
  - `analyst_view(symbol, targets, recommendations, upgrades, as_of) -> AnalystView | None`. `None` means no analyst coverage at all;
  - `YFinanceAnalyst(load=None, limiter=None)`, with:
    - DAILY, SYMBOLS, markets US and TSX;
    - freshness 3 days, `max_symbols = 200`;
    - canary `("AAPL", "RY.TO")` (requires records);
    - best-effort, not core;
  - a shared Yahoo limiter in the registry, which Task 9 reuses.

- [ ] **Step 1: Write the failing tests**

Create `pipeline/tests/unit/test_yfinance_analyst.py`:

```python
import json
from datetime import UTC, datetime

import pandas as pd
import pytest

from advisor.collectors.base import DeadlineExceeded, PartialFetch
from advisor.collectors.yahoo import rate_limited
from advisor.collectors.yfinance_analyst import YFinanceAnalyst, analyst_view
from advisor.models import Market

AS_OF = datetime(2026, 10, 12, 20, 0, tzinfo=UTC)


class CountingLimiter:
    def __init__(self) -> None:
        self.count = 0

    def acquire(self) -> None:
        self.count += 1


class YFRateLimitError(Exception):  # same name as yfinance's, which `rate_limited` matches
    pass


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
    assert analyst_view("SPY", {}, pd.DataFrame(), pd.DataFrame(), AS_OF) is None


def test_zero_or_missing_targets_are_treated_as_missing():
    view = analyst_view("X", {"mean": 0.0, "low": 12.5}, pd.DataFrame(), pd.DataFrame(), AS_OF)
    assert view.target_mean is None
    assert view.target_low == 12.5
    assert view.target_high is None


def test_yahoo_analyst_covers_both_markets_and_is_capped():
    collector = YFinanceAnalyst()
    assert collector.markets == frozenset({Market.US, Market.TSX})
    assert collector.max_symbols == 200


def test_fetch_maps_symbols_and_takes_one_limiter_token_per_symbol(fixtures_dir):
    data = aapl(fixtures_dir)
    loaded = []
    limiter = CountingLimiter()

    def load(yahoo_symbol):
        loaded.append(yahoo_symbol)
        return data

    records = YFinanceAnalyst(load=load, limiter=limiter).fetch(["BRK.B", "AAPL", "RY.TO"], AS_OF)
    assert loaded == ["BRK-B", "AAPL", "RY.TO"]
    assert [r.symbol for r in records] == ["BRK.B", "AAPL", "RY.TO"]
    assert limiter.count == 3


def test_a_failing_symbol_is_a_partial_result(fixtures_dir):
    data = aapl(fixtures_dir)

    def load(yahoo_symbol):
        if yahoo_symbol == "BAD":
            raise KeyError("quoteSummary")
        return data

    with pytest.raises(PartialFetch, match="BAD") as caught:
        YFinanceAnalyst(load=load).fetch(["AAPL", "BAD"], AS_OF)
    assert [r.symbol for r in caught.value.records] == ["AAPL"]


def test_rate_limiting_stops_the_loop(fixtures_dir):
    data = aapl(fixtures_dir)
    loaded = []

    def load(yahoo_symbol):
        loaded.append(yahoo_symbol)
        if yahoo_symbol == "BBB":
            raise YFRateLimitError("Too Many Requests")
        return data

    assert rate_limited(YFRateLimitError("x")) and not rate_limited(KeyError("x"))
    with pytest.raises(PartialFetch, match="stopped after 1 of 3 symbols"):
        YFinanceAnalyst(load=load).fetch(["AAA", "BBB", "CCC"], AS_OF)
    assert loaded == ["AAA", "BBB"]


def test_the_run_deadline_ends_the_loop_with_what_was_gathered(fixtures_dir):
    data = aapl(fixtures_dir)

    def load(yahoo_symbol):
        if yahoo_symbol == "BBB":
            raise DeadlineExceeded("run time budget exhausted")
        return data

    with pytest.raises(PartialFetch, match="stopped after 1 of 3 symbols") as caught:
        YFinanceAnalyst(load=load).fetch(["AAA", "BBB", "CCC"], AS_OF)
    assert [r.symbol for r in caught.value.records] == ["AAA"]
```

In `pipeline/tests/unit/test_registry.py`, add this row to `EXPECTED`:

```python
    "yfinance_analyst": (False, Scope.SYMBOLS, True, BOTH),
```

- [ ] **Step 2: Run them to verify they fail**

Run: `pipeline/scripts/in-docker.sh uv run pytest tests/unit/test_yfinance_analyst.py tests/unit/test_registry.py -q`
Expected: `ModuleNotFoundError`, and the registry lacks `yfinance_analyst`.

- [ ] **Step 3: Implement the shared Yahoo helpers**

Create `pipeline/src/advisor/collectors/yahoo.py`:

```python
"""Helpers shared by the Yahoo (yfinance) per-symbol collectors."""

YAHOO_PER_MINUTE = 120  # one shared budget for Yahoo's per-symbol calls (analyst, earnings)


def rate_limited(exc: Exception) -> bool:
    """yfinance's YFRateLimitError: stop asking Yahoo for the rest of this run."""
    return type(exc).__name__ == "YFRateLimitError"
```

- [ ] **Step 4: Implement the collector**

Create `pipeline/src/advisor/collectors/yfinance_analyst.py`:

```python
"""Analyst price targets, recommendation counts and rating changes via yfinance (source 16).

yfinance has no batch API for these, so the collector goes symbol by symbol through the shared
Yahoo limiter. A symbol Yahoo doesn't cover comes back empty and yields no record. The source
is capped per call (spec §7.2): holdings come first and the rest wait for a later run.
"""

import logging
import math
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd
from pydantic import BaseModel, ConfigDict

from advisor.collectors.base import Cadence, Category, RateLimiter, Scope, collect_per_symbol
from advisor.collectors.yahoo import rate_limited
from advisor.collectors.yfinance_bars import to_yahoo
from advisor.models import AssetType, Market

TickerData = tuple[dict, pd.DataFrame, pd.DataFrame]  # price targets, recommendations, rating changes
Loader = Callable[[str], TickerData]


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


class YFinanceAnalyst:
    name = "yfinance_analyst"
    category = Category.FUNDAMENTALS
    core = False
    best_effort = True
    cadence = Cadence.DAILY
    asset_types = frozenset({AssetType.STOCK})
    markets = frozenset({Market.US, Market.TSX})
    record_type = AnalystView
    freshness = timedelta(days=3)
    scope = Scope.SYMBOLS
    canary = ("AAPL", "RY.TO")
    canary_requires_records = True
    max_symbols = 200  # about 400 a day over two runs; older views are served from cache

    def __init__(self, load: Loader | None = None, limiter: RateLimiter | None = None) -> None:
        self._load = load or _yahoo_load
        self._limiter = limiter

    def fetch(self, symbols: Sequence[str], as_of: datetime) -> list[AnalystView]:
        def one(symbol: str) -> list[AnalystView]:
            if self._limiter is not None:
                self._limiter.acquire()
            view = analyst_view(symbol, *self._load(to_yahoo(symbol)), as_of)
            return [view] if view else []

        return collect_per_symbol(symbols, one, is_fatal=rate_limited)
```

- [ ] **Step 5: Register it with a shared Yahoo limiter**

In `collectors/registry.py`:
- import `YAHOO_PER_MINUTE` from `advisor.collectors.yahoo`, and `YFinanceAnalyst`;
- in `build_registry`, add `yahoo = RateLimiter(per_minute=YAHOO_PER_MINUTE, burst=2)  # shared by Yahoo's per-symbol collectors` after the FINRA limiter;
- add `YFinanceAnalyst(limiter=yahoo),` after `FinraShortInterest(client, finra),`.

- [ ] **Step 6: Run the tests and lint**

Run: `pipeline/scripts/in-docker.sh uv run pytest -q`
Expected: every test passes.

Run: `pipeline/scripts/in-docker.sh uv run ruff check .`
Expected: `All checks passed!`

- [ ] **Step 7: Commit**

```bash
git add pipeline/src/advisor/collectors/yahoo.py pipeline/src/advisor/collectors/yfinance_analyst.py \
  pipeline/src/advisor/collectors/registry.py pipeline/tests/unit/test_yfinance_analyst.py \
  pipeline/tests/unit/test_registry.py
git commit -m "feat: add Yahoo analyst targets, ratings and rating changes for both markets"
```

End the message with your `Co-Authored-By:` trailer.

---

### Task 9: Yahoo earnings dates and surprises (source 17, core)

**Files:**
- Create: `pipeline/src/advisor/collectors/yfinance_earnings.py`
- Modify: `pipeline/src/advisor/collectors/registry.py`, `pipeline/tests/unit/test_registry.py` (add a row)
- Test: `pipeline/tests/unit/test_yfinance_earnings.py`
- Fixtures (already committed): `pipeline/tests/fixtures/yfinance_earnings/earnings_dates_AAPL.json`, `earnings_dates_RY_TO.json` and `earnings_dates_BRK_B.json`.
  - These are real `Ticker.get_earnings_dates()` frames captured on 2026-10-14, 25 rows each. They were saved with `to_json(orient="split", date_format="iso")`, so the index reads back as UTC.
  - BRK-B lists 2026-08-08 twice: a scheduled row at 16:00 ET with no actual, and the reported row at 08:00 ET.

**Interfaces:**
- Consumes: `collect_per_symbol` (base), `rate_limited` (Task 8), `to_yahoo`, and the registry's Yahoo limiter (Task 8).
- Produces:
  - `EarningsReport(symbol, report_at, eps_estimate, eps_actual, surprise_pct)`;
  - `parse_earnings(symbol, frame) -> list[EarningsReport]`;
  - `YFinanceEarnings(load=None, limiter=None)`, with:
    - name `yfinance_earnings`, DAILY, SYMBOLS, markets US and TSX;
    - freshness 7 days;
    - canary `("AAPL", "RY.TO")` (requires records);
    - **core**, best-effort.

- [ ] **Step 1: Write the failing tests**

Create `pipeline/tests/unit/test_yfinance_earnings.py`:

```python
from datetime import UTC, date, datetime

import pandas as pd
import pytest

from advisor.collectors.base import PartialFetch
from advisor.collectors.yfinance_earnings import YFinanceEarnings, parse_earnings
from advisor.models import ET, Market

AS_OF = datetime(2026, 10, 14, 12, 15, tzinfo=UTC)


class CountingLimiter:
    def __init__(self) -> None:
        self.count = 0

    def acquire(self) -> None:
        self.count += 1


class YFRateLimitError(Exception):
    pass


def frame(fixtures_dir, name: str) -> pd.DataFrame:
    path = fixtures_dir / "yfinance_earnings" / f"earnings_dates_{name}.json"
    return pd.read_json(path, orient="split")


def test_parse_gives_one_report_per_date_oldest_first(fixtures_dir):
    reports = parse_earnings("AAPL", frame(fixtures_dir, "AAPL"))
    assert len(reports) == 25
    assert reports == sorted(reports, key=lambda r: r.report_at)
    last, upcoming = reports[-2], reports[-1]
    assert last.report_at == datetime(2026, 7, 30, 16, 0, tzinfo=ET)
    assert last.eps_estimate == pytest.approx(1.89)
    assert (last.eps_actual, last.surprise_pct) == (pytest.approx(2.02), pytest.approx(6.74))
    assert upcoming.report_at == datetime(2026, 11, 2, 15, 0, tzinfo=ET)
    assert upcoming.eps_estimate == pytest.approx(1.98)
    assert (upcoming.eps_actual, upcoming.surprise_pct) == (None, None)


def test_tsx_reports_parse_the_same_way(fixtures_dir):
    reports = parse_earnings("RY.TO", frame(fixtures_dir, "RY_TO"))
    assert len(reports) == 25
    assert reports[-1].report_at == datetime(2026, 12, 3, 7, 0, tzinfo=ET)
    assert reports[-1].eps_actual is None
    assert reports[-2].eps_actual == pytest.approx(4.28)
    assert {r.symbol for r in reports} == {"RY.TO"}


def test_a_date_listed_twice_keeps_the_reported_row(fixtures_dir):
    reports = parse_earnings("BRK.B", frame(fixtures_dir, "BRK_B"))
    assert len(reports) == 24  # 25 rows; 2026-08-08 is listed twice
    [august] = [r for r in reports if r.report_at.date() == date(2026, 8, 8)]
    assert august.report_at.hour == 8
    assert (august.eps_actual, august.surprise_pct) == (pytest.approx(6.03), pytest.approx(17.4))


def test_no_coverage_yields_no_reports():
    assert parse_earnings("SPY", None) == []
    assert parse_earnings("SPY", pd.DataFrame()) == []


def test_earnings_are_core_and_cover_both_markets():
    collector = YFinanceEarnings()
    assert collector.core is True
    assert collector.markets == frozenset({Market.US, Market.TSX})


def test_fetch_maps_symbols_and_takes_one_limiter_token_per_symbol(fixtures_dir):
    loaded = []
    limiter = CountingLimiter()

    def load(yahoo_symbol):
        loaded.append(yahoo_symbol)
        return frame(fixtures_dir, "AAPL") if yahoo_symbol == "AAPL" else None  # others: no coverage

    records = YFinanceEarnings(load=load, limiter=limiter).fetch(["BRK.B", "AAPL", "RY.TO"], AS_OF)
    assert loaded == ["BRK-B", "AAPL", "RY.TO"]
    assert limiter.count == 3
    assert {r.symbol for r in records} == {"AAPL"}
    assert len(records) == 25


def test_rate_limiting_stops_the_loop(fixtures_dir):
    def load(yahoo_symbol):
        if yahoo_symbol == "BBB":
            raise YFRateLimitError("Too Many Requests")
        return frame(fixtures_dir, "AAPL")

    with pytest.raises(PartialFetch, match="stopped after 1 of 3 symbols") as caught:
        YFinanceEarnings(load=load).fetch(["AAA", "BBB", "CCC"], AS_OF)
    assert {r.symbol for r in caught.value.records} == {"AAA"}
```

In `pipeline/tests/unit/test_registry.py`, add this row to `EXPECTED`:

```python
    "yfinance_earnings": (True, Scope.SYMBOLS, True, BOTH),
```

- [ ] **Step 2: Run them to verify they fail**

Run: `pipeline/scripts/in-docker.sh uv run pytest tests/unit/test_yfinance_earnings.py tests/unit/test_registry.py -q`
Expected: `ModuleNotFoundError`, and the registry lacks `yfinance_earnings`.

- [ ] **Step 3: Implement**

Create `pipeline/src/advisor/collectors/yfinance_earnings.py`:

```python
"""Earnings report dates, EPS estimates, actuals and surprises via yfinance (source 17, core).

One record per report: past reports carry the actual EPS and the surprise, upcoming ones only
the estimate. Yahoo sometimes lists one report twice (a scheduled and a reported row for the
same day); the reported row wins. Symbols Yahoo doesn't cover (ETFs, unknown tickers) come back
as None and yield no records. Plan 3 derives days to the next report and the last surprise.
"""

import logging
import math
from collections.abc import Callable, Sequence
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd
from pydantic import BaseModel, ConfigDict

from advisor.collectors.base import Cadence, Category, RateLimiter, Scope, collect_per_symbol
from advisor.collectors.yahoo import rate_limited
from advisor.collectors.yfinance_bars import to_yahoo
from advisor.models import ET, AssetType, Market

Loader = Callable[[str], pd.DataFrame | None]
REPORTS = 12  # about three years of quarters plus the next one; Yahoo may send more


class EarningsReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    report_at: datetime  # scheduled or actual report time, in ET
    eps_estimate: float | None = None
    eps_actual: float | None = None  # None until reported
    surprise_pct: float | None = None


def _yahoo_load(yahoo_symbol: str) -> pd.DataFrame | None:
    import yfinance as yf  # imported lazily: slow import, and tests inject a fake

    logging.getLogger("yfinance").setLevel(logging.CRITICAL)  # it logs an ERROR line per 404
    return yf.Ticker(yahoo_symbol).get_earnings_dates(limit=REPORTS)


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def parse_earnings(symbol: str, frame: pd.DataFrame | None) -> list[EarningsReport]:
    """One report per ET date, oldest first; a reported row beats a scheduled one."""
    if frame is None or frame.empty:
        return []
    by_day: dict[date, EarningsReport] = {}
    for stamp, row in frame.iterrows():
        at = pd.Timestamp(stamp)
        if at.tzinfo is None:
            at = at.tz_localize("UTC")
        report = EarningsReport(
            symbol=symbol,
            report_at=at.tz_convert(ET).to_pydatetime(),
            eps_estimate=_number(row.get("EPS Estimate")),
            eps_actual=_number(row.get("Reported EPS")),
            surprise_pct=_number(row.get("Surprise(%)")),
        )
        day = report.report_at.date()
        kept = by_day.get(day)
        if kept is None or (kept.eps_actual is None and report.eps_actual is not None):
            by_day[day] = report
    return sorted(by_day.values(), key=lambda report: report.report_at)


class YFinanceEarnings:
    name = "yfinance_earnings"
    category = Category.FUNDAMENTALS
    core = True  # spec §4.2: the earnings catalyst feeds event risk and the Review badge
    best_effort = True
    cadence = Cadence.DAILY
    asset_types = frozenset({AssetType.STOCK})
    markets = frozenset({Market.US, Market.TSX})
    record_type = EarningsReport
    freshness = timedelta(days=7)
    scope = Scope.SYMBOLS
    canary = ("AAPL", "RY.TO")
    canary_requires_records = True
    max_symbols = None

    def __init__(self, load: Loader | None = None, limiter: RateLimiter | None = None) -> None:
        self._load = load or _yahoo_load
        self._limiter = limiter

    def fetch(self, symbols: Sequence[str], as_of: datetime) -> list[EarningsReport]:
        def one(symbol: str) -> list[EarningsReport]:
            if self._limiter is not None:
                self._limiter.acquire()
            return parse_earnings(symbol, self._load(to_yahoo(symbol)))

        return collect_per_symbol(symbols, one, is_fatal=rate_limited)
```

Register it in `collectors/registry.py`: import `YFinanceEarnings`, and add `YFinanceEarnings(limiter=yahoo),` after `YFinanceAnalyst(limiter=yahoo),`.

- [ ] **Step 4: Run the tests and lint**

Run: `pipeline/scripts/in-docker.sh uv run pytest -q`
Expected: every test passes.

Run: `pipeline/scripts/in-docker.sh uv run ruff check .`
Expected: `All checks passed!`

- [ ] **Step 5: Commit**

```bash
git add pipeline/src/advisor/collectors/yfinance_earnings.py pipeline/src/advisor/collectors/registry.py \
  pipeline/tests/unit/test_yfinance_earnings.py pipeline/tests/unit/test_registry.py
git commit -m "feat: add Yahoo earnings dates and surprises as a core source"
```

End the message with your `Co-Authored-By:` trailer.

---

### Task 10: Bank of Canada Valet (source 7) and the deferred list

**Files:**
- Create: `pipeline/src/advisor/collectors/boc_valet.py`
- Modify: `pipeline/src/advisor/collectors/registry.py`, `pipeline/tests/unit/test_registry.py` (add a row), `docs/superpowers/deferred.md`
- Test: `pipeline/tests/unit/test_boc_valet.py`
- Fixture (already committed): `pipeline/tests/fixtures/boc/valet_observations_recent10.json`.
  - This is the real answer to `observations/FXUSDCAD,V39079,BD.CDN.2YR.DQ.YLD,BD.CDN.10YR.DQ.YLD/json?recent=10`, captured on 2026-10-14.
  - It holds 10 observations per series across 12 dates.
  - On 2026-10-12 (Canadian Thanksgiving) only the policy rate has a value.

**Interfaces:**
- Consumes: `get_with_retries` and `PartialFetch` (base).
- Produces:
  - `SeriesObservation(series, day, value)`;
  - `SERIES`, a dict of series name to description;
  - `VALET_URL` and `LOOKBACK = timedelta(days=120)`;
  - `parse_observations(payload, series) -> list[SeriesObservation]`;
  - `BankOfCanadaValet(client, limiter=None)`, with:
    - name `boc_valet`, category PRICES, DAILY, MARKET scope, markets US and TSX;
    - freshness 7 days;
    - no canary (requires records);
    - not core.

- [ ] **Step 1: Write the failing tests**

Create `pipeline/tests/unit/test_boc_valet.py`:

```python
import json
from datetime import UTC, date, datetime

import httpx
import pytest

from advisor.collectors.base import PartialFetch
from advisor.collectors.boc_valet import SERIES, BankOfCanadaValet, parse_observations

AS_OF = datetime(2026, 10, 14, 12, 15, tzinfo=UTC)  # 120-day lookback starts 2026-06-16


def payload(fixtures_dir) -> dict:
    path = fixtures_dir / "boc" / "valet_observations_recent10.json"
    return json.loads(path.read_text(encoding="utf-8"))


def serving(handler) -> BankOfCanadaValet:
    return BankOfCanadaValet(httpx.Client(transport=httpx.MockTransport(handler)))


def test_parse_reads_every_series_and_skips_days_without_a_value(fixtures_dir):
    records = parse_observations(payload(fixtures_dir), list(SERIES))
    by_series: dict[str, list] = {}
    for record in records:
        by_series.setdefault(record.series, []).append(record)
    assert {name: len(rows) for name, rows in by_series.items()} == {name: 10 for name in SERIES}
    fx = by_series["FXUSDCAD"]
    assert (fx[-1].day, fx[-1].value) == (date(2026, 10, 13), 1.4222)
    assert date(2026, 10, 12) not in {r.day for r in fx}  # Canadian Thanksgiving: no FX rate
    assert [r.value for r in by_series["V39079"] if r.day == date(2026, 10, 12)] == [2.25]
    assert by_series["BD.CDN.10YR.DQ.YLD"][-1].value == 3.87


def test_fetch_asks_once_for_every_series_since_the_lookback(fixtures_dir):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url)
        return httpx.Response(200, json=payload(fixtures_dir))

    records = serving(handler).fetch([], AS_OF)
    [url] = seen
    assert url.path == "/valet/observations/FXUSDCAD,V39079,BD.CDN.2YR.DQ.YLD,BD.CDN.10YR.DQ.YLD/json"
    assert url.params["start_date"] == "2026-06-16"
    assert len(records) == 40


def test_a_series_with_no_observations_is_a_partial_result(fixtures_dir):
    data = payload(fixtures_dir)
    for observation in data["observations"]:
        observation.pop("BD.CDN.2YR.DQ.YLD", None)
    with pytest.raises(PartialFetch, match="no observations for BD.CDN.2YR.DQ.YLD") as caught:
        serving(lambda request: httpx.Response(200, json=data)).fetch([], AS_OF)
    assert len(caught.value.records) == 30


def test_an_unknown_series_fails_the_source():
    collector = serving(lambda request: httpx.Response(404, json={"message": "Series NOPE not found."}))
    with pytest.raises(httpx.HTTPStatusError, match="HTTP 404"):
        collector.fetch([], AS_OF)
```

In `pipeline/tests/unit/test_registry.py`, add this row to `EXPECTED`:

```python
    "boc_valet": (False, Scope.MARKET, True, BOTH),
```

- [ ] **Step 2: Run them to verify they fail**

Run: `pipeline/scripts/in-docker.sh uv run pytest tests/unit/test_boc_valet.py tests/unit/test_registry.py -q`
Expected: `ModuleNotFoundError`, and the registry lacks `boc_valet`.

- [ ] **Step 3: Implement**

Create `pipeline/src/advisor/collectors/boc_valet.py`:

```python
"""USD/CAD, the policy rate and Government of Canada yields from the Bank of Canada Valet API
(spec source 7).

One keyless JSON call returns every series since the lookback. A day a series has no value (a
holiday, or today's rate before publication) simply lacks it.
"""

import math
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict

from advisor.collectors.base import (
    Cadence,
    Category,
    PartialFetch,
    RateLimiter,
    Scope,
    get_with_retries,
)
from advisor.models import ET, AssetType, Market

VALET_URL = "https://www.bankofcanada.ca/valet/observations/{series}/json"
SERIES = {
    "FXUSDCAD": "USD/CAD, daily average",
    "V39079": "target for the overnight rate (policy rate)",
    "BD.CDN.2YR.DQ.YLD": "2-year Government of Canada benchmark bond yield",
    "BD.CDN.10YR.DQ.YLD": "10-year Government of Canada benchmark bond yield",
}
LOOKBACK = timedelta(days=120)  # enough for a 63-session trend


class SeriesObservation(BaseModel):
    model_config = ConfigDict(frozen=True)

    series: str
    day: date
    value: float


def parse_observations(
    payload: Mapping[str, Any], series: Sequence[str]
) -> list[SeriesObservation]:
    rows: list[SeriesObservation] = []
    for observation in payload["observations"]:
        day = date.fromisoformat(observation["d"])
        for name in series:
            raw = (observation.get(name) or {}).get("v")
            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue
            if math.isfinite(value):
                rows.append(SeriesObservation(series=name, day=day, value=value))
    return sorted(rows, key=lambda row: (row.series, row.day))


class BankOfCanadaValet:
    name = "boc_valet"
    category = Category.PRICES  # spec §4.2 lists it with the price sources
    core = False
    best_effort = False
    cadence = Cadence.DAILY
    asset_types = frozenset({AssetType.STOCK})
    markets = frozenset({Market.US, Market.TSX})
    record_type = SeriesObservation
    freshness = timedelta(days=7)
    scope = Scope.MARKET
    canary: tuple[str, ...] = ()
    canary_requires_records = True
    max_symbols = None

    def __init__(self, client: httpx.Client, limiter: RateLimiter | None = None) -> None:
        self._client = client
        self._limiter = limiter

    def fetch(self, symbols: Sequence[str], as_of: datetime) -> list[SeriesObservation]:
        start = as_of.astimezone(ET).date() - LOOKBACK
        response = get_with_retries(
            self._client,
            VALET_URL.format(series=",".join(SERIES)),
            params={"start_date": start.isoformat()},
            limiter=self._limiter,
        )
        records = parse_observations(response.json(), list(SERIES))
        missing = sorted(set(SERIES) - {record.series for record in records})
        if missing:
            message = f"Bank of Canada sent no observations for {', '.join(missing)}"
            if records:
                raise PartialFetch(records, message)
            raise ValueError(message)
        return records
```

Register it in `collectors/registry.py`: import `BankOfCanadaValet`, and add `BankOfCanadaValet(client),` as the last entry in the list.

- [ ] **Step 4: Update the deferred list**

In `docs/superpowers/deferred.md`:
- Delete the whole `## Plan 2c, Task 0: must land before the first real enrichment source` section and the whole `## Plan 2c` section. This plan resolves them.
- Add this section before `## Plans 2c to 2e`:

```markdown
## Plan 2d: SEC

- **One shared limiter for every SEC collector,** built in `build_registry`, the same way as FINRA and Yahoo. SEC allows 10 requests per second per IP.
- **The SEC contact string:** add `SEC_USER_AGENT` (an optional setting; SEC requires a contact in every request) with `MissingCredential`, which fails only the SEC sources when it is unset.
- **Recorded fixtures:** the SEC fixtures are in `.superpowers/research/plan-2c-fixtures/sec/` (git-ignored). Copy the ones the plan uses into `pipeline/tests/fixtures/sec/`.
```

- Rename `## Plans 2c to 2e` to `## Plan 2e`.

- [ ] **Step 5: Run the tests and lint**

Run: `pipeline/scripts/in-docker.sh uv run pytest -q`
Expected: every test passes.

Run: `pipeline/scripts/in-docker.sh uv run ruff check .`
Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add pipeline/src/advisor/collectors/boc_valet.py pipeline/src/advisor/collectors/registry.py \
  pipeline/tests/unit/test_boc_valet.py pipeline/tests/unit/test_registry.py docs/superpowers/deferred.md
git commit -m "feat: add Bank of Canada USD/CAD, policy rate and yields; close Plan 2c deferrals"
```

End the message with your `Co-Authored-By:` trailer.

---

## After this plan

- **Live check.** On the owner's machine, against a scratch database, run the health check and then a forced pre-open run:

  ```bash
  pipeline/scripts/in-docker.sh uv run python -m advisor.health
  pipeline/scripts/in-docker.sh uv run python -m advisor.run --force-kind pre_open
  ```

  - All eight sources should be `ok`.
  - The run should finish well inside the 30-minute budget.
  - A second run the same day should skip the daily sources' fetches, because they are served from the cadence window.
- **Next:** Plan 2d (SEC).
