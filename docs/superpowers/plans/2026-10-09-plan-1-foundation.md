# Stock Advisor — Plan 1: Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A scheduled, tested Python pipeline that runs before each market open and close. Each run loads the US stock universe, fetches daily prices with a fallback source, applies the hard screener filters, records each source's health, and publishes the run to Supabase. Plans 2–5 build on it.

**Architecture:**
- A `uv`-managed Python 3.12 package, `advisor`, under `pipeline/`. It is built from small, single-purpose modules:
  - a schedule guard
  - a collector framework (interface, rate limiter, retries, disk cache, circuit breaker)
  - three collectors (NASDAQ symbols, Alpaca bars, yfinance bars)
  - price fetching with cross-source validation
  - a screener
  - a Postgres store
  - a run orchestrator
- The schema and row-level-security (RLS) policies live in `supabase/migrations/`.
- GitHub Actions runs CI on every push and runs the pipeline on cron.

**Tech Stack:** Python 3.12, uv, httpx, pydantic v2, psycopg 3, pandas, pandas-market-calendars, yfinance, tzdata, pytest, ruff, Postgres 16 (Docker for tests), Supabase, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-10-09-stock-advisor-design.md`. Read §3, §4.1–§4.3, §8 and §10 before starting.

## Roadmap (this plan is 1 of 5)

| Plan | Delivers | Depends on |
|---|---|---|
| **1. Foundation** (this plan) | Repo, schema and RLS, collector framework, universe, prices, hard filters, run lifecycle, CI and cron | — |
| 2. Collectors and news | The remaining 50 sources (§4.2), news de-duplication and ticker mapping, FinBERT sentiment, `health.yml` | 1 |
| 3. Model | Parquet history in Supabase Storage, features (§5.1), screener model, base quantile models with isotonic calibration, crypto model, walk-forward backtest and promotion gates, `train.yml` | 1, 2 |
| 4. Recommendations and portfolio | Pick qualification, hold time, stops, risk (§6), watchlist verdicts, holding actions, trailing stops, tax days (§7), grader, paper-period flags | 3 |
| 5. Dashboard | Superdesign layout, then theme, then animation, then HTML (each signed off by the owner), then the Next.js pages on Vercel (§9) and Playwright tests | 1, 4 |

Each plan is written after the previous one ships, so it can build on the real code.

## Global Constraints

- Python `>=3.12,<3.13`, managed by uv. The lockfile `uv.lock` is committed.
- Running cost is **$0/month**: free tiers and free API keys only.
- Market time zone is `America/New_York` (`advisor.models.ET`). Database timestamps are `timestamptz`. Every collected record is tied to the run's `as_of`.
- The pipeline writes. The dashboard reads, and writes only to `watchlist`, `lots` and `sells`.
- Every table has RLS enabled and is readable only by the owner (`public.is_owner()`).
- Each source is one module in `pipeline/src/advisor/collectors/` with an entry in `registry.py`. Sources never call each other.
- Sanity rules:
  - every price must be greater than 0
  - a daily close-to-close move above 50% is dropped unless a second source confirms that day's close within 2%
- Failed runs are never published (`runs.published = false`).
- Secrets come only from environment variables or GitHub secrets. Never commit `.env` files or keys.
- All commands run from `stock-advisor/pipeline/` unless a step says otherwise.
- Database tests need `TEST_DATABASE_URL`. Locally this is `postgresql://postgres:postgres@localhost:54329/advisor_test`, served by the Docker container started in Task 3.
- Every commit message ends with the trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Run `uv run ruff check --fix .` before every commit. CI fails on lint errors.

### Deliberate refinements of the spec (record of decisions)

- **Collector interface.** `Collector.fetch` returns a `list` of validated records and raises on error. `run_collector()` wraps it and produces the `CollectorResult` described in spec §4.1.
- **Database access.** The pipeline connects with `DATABASE_URL`, the Supabase session-pooler Postgres URI, instead of the service-role key. It's the same trust level, held only as a GitHub secret. Table ownership bypasses RLS.
- **Circuit breaker retries.** After 3 consecutive failed runs a source is skipped, except that the first run of each new ET day tries it once (half-open). `health.yml` (Plan 2) adds the daily live ping.
- **"Recorded split or corporate action".** Bars are requested split-adjusted (`adjustment=all`). A matching close from a second source counts as the record.
- **Added schema details:** `runs.et_date` and `runs.summary`, `source_health.attempted_at`, `watchlist_verdicts.details` (holds the full pick fields for a Buy verdict, per spec §6.5), and the `app_config` table that holds the owner's user ID.
- **Test layout:** `tests/unit/` (no database), `tests/integration/` (database), `tests/fixtures/`, plus `tests/fakes.py`.

## Review Focus

1. Share-class symbols such as `BRK.B` must round-trip between Alpaca's `BRK.B` and Yahoo's `BRK-B`. Tested in Task 8.
2. A holding that isn't in the NASDAQ universe (OTC or recently delisted) must still be priced and get a `features_live` row. Tested in Task 11.
3. Manually re-running a slot that already has a published run must replace that run, not crash on the one-published-run index. Tested in Task 5.
4. Company names such as "United Airlines" or "Preferred Bank" must not be excluded as units or preferred shares. Tested in Task 6.
5. A truncated or garbled universe file with only a few symbols must fail the run and leave it unpublished, rather than silently shrinking the market. Tested in Task 11.

---

## File Structure

```
stock-advisor/
  .gitignore
  README.md
  .github/workflows/ci.yml          CI: lint + all tests with a Postgres service
  .github/workflows/run.yml         cron + manual dispatch of the pipeline
  supabase/migrations/0001_schema.sql   all tables from spec §8
  supabase/migrations/0002_rls.sql      is_owner() + owner-only policies
  pipeline/
    pyproject.toml  .python-version  uv.lock
    src/advisor/
      __init__.py
      config.py          Settings from env
      models.py          ET, enums, AssetRef, SymbolInfo, DailyBar
      schedule.py        NYSE calendar + run-window guard
      screener.py        hard filters (price, ADV, history)
      prices.py          primary/fallback bar fetch + jump validation
      run.py             orchestrator + CLI entry point
      collectors/
        __init__.py
        base.py          Collector protocol, enums, RateLimiter, get_with_retries, make_client
        cache.py         DiskCache
        runner.py        SourceState, breaker, run_collector, next_failures
        registry.py      build_registry
        nasdaq_symbols.py
        alpaca_bars.py
        yfinance_bars.py
      store/
        __init__.py
        db.py            connect, apply_migrations
        repo.py          all SQL used by the pipeline
    tests/
      conftest.py        db fixture (fresh schema per test)
      fakes.py           FakeClock, FakeCollector, bar/history/info builders
      fixtures/nasdaqlisted.txt  fixtures/otherlisted.txt
      unit/…  integration/…
```

---

### Task 1: Scaffold the pipeline package

**Files:**
- Create: `.gitignore`, `pipeline/pyproject.toml`, `pipeline/.python-version`, `pipeline/src/advisor/__init__.py`, `pipeline/src/advisor/config.py`, `pipeline/src/advisor/models.py`
- Test: `pipeline/tests/unit/test_config.py`, `pipeline/tests/unit/test_models.py`

**Interfaces:**
- Produces:
  - `advisor.config.Settings` (frozen dataclass: `database_url: str`, `alpaca_key_id: str`, `alpaca_secret_key: str`, `cache_dir: Path`; classmethod `from_env(env: Mapping[str, str] | None = None) -> Settings`)
  - `advisor.config.ConfigError`
  - `advisor.models`: `ET`, `AssetType`, `RunKind`, `RunStatus`, `AssetRef(symbol, asset_type)`, `SymbolInfo`, `DailyBar`

- [ ] **Step 1: Install uv if it's missing**

Run: `uv --version`. If the command isn't found, run this in PowerShell:
```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```
Then open a new shell and confirm that `uv --version` prints a version.

- [ ] **Step 2: Create the repo-level `.gitignore`** at `stock-advisor/.gitignore`

```gitignore
.venv/
__pycache__/
.pytest_cache/
.ruff_cache/
.cache/
.env
.env.*
*.tmp
node_modules/
.superpowers/
```

- [ ] **Step 3: Create `pipeline/.python-version` and `pipeline/pyproject.toml`**

`pipeline/.python-version`:
```
3.12
```

`pipeline/pyproject.toml`:
```toml
[project]
name = "advisor"
version = "0.1.0"
description = "Stock Advisor data pipeline"
requires-python = ">=3.12,<3.13"
dependencies = [
  "httpx>=0.27",
  "pydantic>=2.7",
  "psycopg[binary]>=3.2",
  "pandas>=2.2",
  "pandas-market-calendars>=4.4",
  "yfinance>=0.2.50",
  "tzdata>=2024.1",
]

[dependency-groups]
dev = ["pytest>=8.2", "ruff>=0.6"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/advisor"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["tests"]

[tool.ruff]
line-length = 100
target-version = "py312"
src = ["src", "tests"]

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]
ignore = ["E501"]  # long SQL strings and messages; formatting is not enforced by lint
```

Run: `uv sync`
Expected: uv downloads Python 3.12 if needed, creates `.venv`, and writes `uv.lock`.

- [ ] **Step 4: Write the failing tests**

`pipeline/tests/unit/test_config.py`:
```python
from pathlib import Path

import pytest

from advisor.config import ConfigError, Settings

FULL = {
    "DATABASE_URL": "postgresql://u:p@h/db",
    "ALPACA_KEY_ID": "k",
    "ALPACA_SECRET_KEY": "s",
}


def test_from_env_reads_required_values_and_default_cache_dir():
    settings = Settings.from_env(FULL)
    assert settings.database_url == "postgresql://u:p@h/db"
    assert settings.alpaca_key_id == "k"
    assert settings.alpaca_secret_key == "s"
    assert settings.cache_dir == Path(".cache")


def test_from_env_honours_cache_dir_override():
    settings = Settings.from_env({**FULL, "ADVISOR_CACHE_DIR": "/tmp/advisor"})
    assert settings.cache_dir == Path("/tmp/advisor")


def test_from_env_lists_every_missing_variable():
    with pytest.raises(ConfigError, match="ALPACA_KEY_ID, ALPACA_SECRET_KEY"):
        Settings.from_env({"DATABASE_URL": "x"})
```

`pipeline/tests/unit/test_models.py`:
```python
from datetime import date

import pytest
from pydantic import ValidationError

from advisor.models import AssetRef, AssetType, DailyBar


def test_daily_bar_rejects_non_positive_prices():
    with pytest.raises(ValidationError):
        DailyBar(
            symbol="X", day=date(2026, 10, 14), open=1, high=1, low=1, close=0,
            volume=10, source="test",
        )


def test_asset_ref_is_hashable_and_compares_by_value():
    assert {AssetRef("AAPL", AssetType.STOCK)} == {AssetRef("AAPL", AssetType.STOCK)}
```

- [ ] **Step 5: Run the tests to verify they fail**

Run: `uv run pytest tests/unit -v`
Expected: collection errors with `ModuleNotFoundError: No module named 'advisor.config'`.

- [ ] **Step 6: Implement the package**

`pipeline/src/advisor/__init__.py`:
```python
"""Stock Advisor pipeline."""
```

`pipeline/src/advisor/models.py`:
```python
"""Shared domain types used across the pipeline."""

from datetime import date
from enum import StrEnum
from typing import NamedTuple
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

ET = ZoneInfo("America/New_York")


class AssetType(StrEnum):
    STOCK = "stock"
    CRYPTO = "crypto"


class RunKind(StrEnum):
    PRE_OPEN = "pre_open"
    PRE_CLOSE = "pre_close"
    EARLY_CLOSE = "early_close"


class RunStatus(StrEnum):
    RUNNING = "running"
    SUCCESS = "success"
    DEGRADED = "degraded"
    FAILED = "failed"


class AssetRef(NamedTuple):
    symbol: str
    asset_type: AssetType


class SymbolInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    asset_type: AssetType = AssetType.STOCK
    name: str
    exchange: str


class DailyBar(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    day: date
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)
    volume: float = Field(ge=0)
    source: str
```

`pipeline/src/advisor/config.py`:
```python
"""Runtime settings loaded from environment variables."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Self

REQUIRED = ("DATABASE_URL", "ALPACA_KEY_ID", "ALPACA_SECRET_KEY")


class ConfigError(RuntimeError):
    """Raised when required settings are missing."""


@dataclass(frozen=True)
class Settings:
    database_url: str
    alpaca_key_id: str
    alpaca_secret_key: str
    cache_dir: Path

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Self:
        env = os.environ if env is None else env
        missing = [name for name in REQUIRED if not env.get(name)]
        if missing:
            raise ConfigError(f"Missing required environment variables: {', '.join(missing)}")
        return cls(
            database_url=env["DATABASE_URL"],
            alpaca_key_id=env["ALPACA_KEY_ID"],
            alpaca_secret_key=env["ALPACA_SECRET_KEY"],
            cache_dir=Path(env.get("ADVISOR_CACHE_DIR", ".cache")),
        )
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/unit -v`
Expected: 5 passed.

- [ ] **Step 8: Commit**

```bash
uv run ruff check --fix .
git add ../.gitignore pyproject.toml .python-version uv.lock src tests
git commit -m "feat: scaffold pipeline package with settings and domain models" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Run-window guard on the NYSE calendar

**Files:**
- Create: `pipeline/src/advisor/schedule.py`
- Test: `pipeline/tests/unit/test_schedule.py`

**Interfaces:**
- Consumes: `advisor.models.ET`, `RunKind`
- Produces:
  - `advisor.schedule.market_close_et(day: date) -> time | None` (None means the market is closed that day)
  - `advisor.schedule.resolve_run_kind(now_utc: datetime) -> RunKind | None`
  - constants `TARGETS: dict[RunKind, time]`, `EARLY_TOLERANCE`, `LATE_TOLERANCE`

- [ ] **Step 1: Write the failing test**

`pipeline/tests/unit/test_schedule.py`:
```python
from datetime import UTC, datetime, time

import pytest

from advisor.models import RunKind
from advisor.schedule import market_close_et, resolve_run_kind


def utc(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        ("2026-10-14T12:15:00", RunKind.PRE_OPEN),     # EDT 08:15 ET
        ("2026-10-14T13:15:00", None),                 # EDT 09:15 ET (the EST cron)
        ("2026-10-14T12:40:00", RunKind.PRE_OPEN),     # 25 min late: still inside window
        ("2026-10-14T12:50:00", None),                 # 35 min late: outside window
        ("2026-10-14T19:15:00", RunKind.PRE_CLOSE),    # EDT 15:15 ET
        ("2026-10-14T16:15:00", None),                 # early-close cron on a normal day
        ("2026-12-02T13:15:00", RunKind.PRE_OPEN),     # EST 08:15 ET
        ("2026-12-02T12:15:00", None),                 # EST 07:15 ET (the EDT cron)
        ("2026-12-02T20:15:00", RunKind.PRE_CLOSE),    # EST 15:15 ET
        ("2026-11-26T13:15:00", None),                 # Thanksgiving: market closed
        ("2026-10-17T12:15:00", None),                 # Saturday
        ("2026-11-27T13:15:00", RunKind.PRE_OPEN),     # early-close day still has pre-open
        ("2026-11-27T17:15:00", RunKind.EARLY_CLOSE),  # 12:15 ET before the 13:00 close
        ("2026-11-27T20:15:00", None),                 # 15:15 ET: market already closed
    ],
)
def test_resolve_run_kind(now, expected):
    assert resolve_run_kind(utc(now)) == expected


def test_market_close_et_reports_normal_early_and_closed_days():
    from datetime import date

    assert market_close_et(date(2026, 10, 14)) == time(16, 0)
    assert market_close_et(date(2026, 11, 27)) == time(13, 0)
    assert market_close_et(date(2026, 11, 26)) is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_schedule.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'advisor.schedule'`.

- [ ] **Step 3: Implement**

`pipeline/src/advisor/schedule.py`:
```python
"""Decides whether 'now' falls in a run window on an NYSE trading day.

GitHub cron is UTC-only, so each run has one cron for EDT and one for EST. This guard
accepts exactly one of them, and only on days the NYSE calendar says are right.
"""

from datetime import date, datetime, time, timedelta
from functools import cache

import pandas_market_calendars as mcal

from advisor.models import ET, RunKind

TARGETS: dict[RunKind, time] = {
    RunKind.PRE_OPEN: time(8, 15),
    RunKind.EARLY_CLOSE: time(12, 15),
    RunKind.PRE_CLOSE: time(15, 15),
}
EARLY_TOLERANCE = timedelta(minutes=10)
LATE_TOLERANCE = timedelta(minutes=30)
NORMAL_CLOSE = time(16, 0)


@cache
def _nyse() -> mcal.MarketCalendar:
    return mcal.get_calendar("NYSE")


def market_close_et(day: date) -> time | None:
    """Closing time in ET for `day`, or None when the NYSE is closed."""
    schedule = _nyse().schedule(start_date=day.isoformat(), end_date=day.isoformat())
    if schedule.empty:
        return None
    return schedule.iloc[0]["market_close"].tz_convert("America/New_York").time()


def resolve_run_kind(now_utc: datetime) -> RunKind | None:
    now_et = now_utc.astimezone(ET)
    close = market_close_et(now_et.date())
    if close is None:
        return None
    early_close_day = close < NORMAL_CLOSE
    for kind, target in TARGETS.items():
        if kind is RunKind.PRE_CLOSE and early_close_day:
            continue
        if kind is RunKind.EARLY_CLOSE and not early_close_day:
            continue
        scheduled = datetime.combine(now_et.date(), target, tzinfo=ET)
        if scheduled - EARLY_TOLERANCE <= now_et <= scheduled + LATE_TOLERANCE:
            return kind
    return None
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_schedule.py -v`
Expected: 15 passed.

- [ ] **Step 5: Commit**

```bash
uv run ruff check --fix .
git add src/advisor/schedule.py tests/unit/test_schedule.py
git commit -m "feat: add NYSE run-window guard for UTC cron schedules" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Database schema, RLS and a test database

**Files:**
- Create: `supabase/migrations/0001_schema.sql`, `supabase/migrations/0002_rls.sql`, `pipeline/src/advisor/store/__init__.py`, `pipeline/src/advisor/store/db.py`, `pipeline/tests/conftest.py`
- Test: `pipeline/tests/integration/test_schema.py`

**Interfaces:**
- Produces:
  - `advisor.store.db.connect(url: str) -> psycopg.Connection` (autocommit, `dict_row`)
  - `advisor.store.db.apply_migrations(conn, directory: Path = MIGRATIONS_DIR) -> list[str]`
  - pytest fixtures `db` (a fresh migrated schema for each test) and `fixtures_dir`

- [ ] **Step 1: Start a local Postgres for tests**

Run once (Docker is installed):
```bash
docker run -d --name advisor-pg -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=advisor_test -p 54329:5432 postgres:16
```
Expected: a container ID is printed. On later sessions, run `docker start advisor-pg`.

- [ ] **Step 2: Write the schema migration**

`supabase/migrations/0001_schema.sql`:
```sql
-- Stock Advisor core schema (spec §8). Applied once to Supabase via the SQL editor, and to test DBs.

create table app_config (
  id int primary key default 1 check (id = 1),
  owner_id uuid not null
);

create table runs (
  id bigint generated always as identity primary key,
  kind text not null check (kind in ('pre_open', 'pre_close', 'early_close')),
  et_date date not null,
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  status text not null default 'running'
    check (status in ('running', 'success', 'degraded', 'failed')),
  published boolean not null default false,
  sources_ok int,
  sources_total int,
  model_version text,
  summary jsonb not null default '{}'::jsonb
);
create unique index runs_one_published_per_slot on runs (kind, et_date) where published;

create table source_health (
  id bigint generated always as identity primary key,
  run_id bigint not null references runs (id) on delete cascade,
  source text not null,
  status text not null check (status in ('ok', 'stale', 'failed', 'skipped')),
  latency_ms int not null,
  records int not null,
  error text,
  consecutive_failures int not null,
  attempted_at timestamptz not null default now()
);
create index source_health_by_source on source_health (source, attempted_at desc);

create table symbols (
  symbol text not null,
  asset_type text not null check (asset_type in ('stock', 'crypto')),
  name text not null,
  exchange text not null,
  sector text,
  industry text,
  market_cap numeric,
  active boolean not null default true,
  updated_at timestamptz not null default now(),
  primary key (symbol, asset_type)
);

create table features_live (
  run_id bigint not null references runs (id) on delete cascade,
  symbol text not null,
  asset_type text not null check (asset_type in ('stock', 'crypto')),
  features jsonb not null,
  as_of timestamptz not null,
  primary key (run_id, symbol, asset_type)
);

create table predictions (
  run_id bigint not null references runs (id) on delete cascade,
  symbol text not null,
  asset_type text not null check (asset_type in ('stock', 'crypto')),
  horizon_days int not null check (horizon_days > 0),
  q10 double precision not null,
  q50 double precision not null,
  q90 double precision not null,
  p_beat double precision not null check (p_beat between 0 and 1),
  benchmark text not null,
  model_version text not null,
  primary key (run_id, symbol, asset_type, horizon_days)
);

create table picks (
  id bigint generated always as identity primary key,
  run_id bigint not null references runs (id) on delete cascade,
  symbol text not null,
  asset_type text not null default 'stock' check (asset_type in ('stock', 'crypto')),
  style text not null check (style in ('swing', 'position')),
  horizon_days int not null check (horizon_days > 0),
  exit_by date not null,
  entry_ref_price numeric not null check (entry_ref_price > 0),
  stop numeric not null check (stop > 0),
  risk_level text not null check (risk_level in ('low', 'medium', 'high', 'very_high')),
  risk_score double precision not null,
  max_position_pct double precision not null,
  rank int not null,
  top_factors jsonb not null default '[]'::jsonb,
  catalysts jsonb not null default '[]'::jsonb,
  status text not null default 'open' check (status in ('open', 'exited_early', 'graded')),
  created_at timestamptz not null default now()
);

create table pick_outcomes (
  pick_id bigint primary key references picks (id) on delete cascade,
  exit_price numeric not null,
  exit_reason text not null,
  ret double precision not null,
  bench_ret double precision not null,
  excess double precision not null,
  beat boolean not null,
  hit_stop boolean not null,
  graded_at timestamptz not null default now()
);

create table watchlist (
  symbol text not null,
  asset_type text not null check (asset_type in ('stock', 'crypto')),
  added_at timestamptz not null default now(),
  primary key (symbol, asset_type)
);

create table watchlist_verdicts (
  run_id bigint not null references runs (id) on delete cascade,
  symbol text not null,
  asset_type text not null check (asset_type in ('stock', 'crypto')),
  verdict text not null check (verdict in ('buy', 'hold', 'avoid')),
  reasons jsonb not null default '[]'::jsonb,
  details jsonb not null default '{}'::jsonb,
  primary key (run_id, symbol, asset_type)
);

create table lots (
  id bigint generated always as identity primary key,
  symbol text not null,
  asset_type text not null check (asset_type in ('stock', 'crypto')),
  qty numeric not null check (qty > 0),
  price numeric not null check (price > 0),
  bought_at date not null,
  pick_id bigint references picks (id) on delete set null,
  notes text,
  created_at timestamptz not null default now()
);

create table sells (
  id bigint generated always as identity primary key,
  symbol text not null,
  asset_type text not null check (asset_type in ('stock', 'crypto')),
  qty numeric not null check (qty > 0),
  price numeric not null check (price > 0),
  sold_at date not null,
  created_at timestamptz not null default now()
);

create table holding_actions (
  run_id bigint not null references runs (id) on delete cascade,
  symbol text not null,
  asset_type text not null check (asset_type in ('stock', 'crypto')),
  action text not null check (action in ('sell', 'trim', 'add', 'hold', 'data_conflict')),
  review boolean not null default false,
  reasons jsonb not null default '[]'::jsonb,
  trailing_stop numeric,
  q10 double precision,
  q50 double precision,
  q90 double precision,
  exit_by date,
  days_to_long_term int,
  primary key (run_id, symbol, asset_type)
);

create table news_items (
  id bigint generated always as identity primary key,
  symbol text not null,
  published_at timestamptz not null,
  outlet text not null,
  url text not null,
  title text not null,
  sentiment double precision,
  cluster_id text
);
create index news_items_by_symbol on news_items (symbol, published_at desc);

create table models (
  version text primary key,
  kind text not null check (kind in ('stock', 'crypto')),
  trained_at timestamptz not null,
  metrics jsonb not null default '{}'::jsonb,
  calibration_error double precision,
  active boolean not null default false
);
create unique index models_one_active_per_kind on models (kind) where active;
```

- [ ] **Step 3: Write the RLS migration**

`supabase/migrations/0002_rls.sql`:
```sql
-- Owner-only access (spec §8). The pipeline connects as the table owner, which bypasses RLS.

create or replace function public.is_owner() returns boolean
language sql stable security definer set search_path = public
as $$
  select exists (select 1 from public.app_config where id = 1 and owner_id = auth.uid());
$$;

do $$
declare
  t text;
begin
  foreach t in array array[
    'app_config', 'runs', 'source_health', 'symbols', 'features_live', 'predictions', 'picks',
    'pick_outcomes', 'watchlist', 'watchlist_verdicts', 'lots', 'sells', 'holding_actions',
    'news_items', 'models'
  ] loop
    execute format('alter table public.%I enable row level security', t);
    execute format(
      'create policy owner_read on public.%I for select to authenticated using (public.is_owner())', t);
  end loop;

  foreach t in array array['watchlist', 'lots', 'sells'] loop
    execute format(
      'create policy owner_insert on public.%I for insert to authenticated with check (public.is_owner())', t);
    execute format(
      'create policy owner_update on public.%I for update to authenticated using (public.is_owner()) with check (public.is_owner())', t);
    execute format(
      'create policy owner_delete on public.%I for delete to authenticated using (public.is_owner())', t);
  end loop;
end $$;
```

- [ ] **Step 4: Write `db.py` and the test fixtures**

`pipeline/src/advisor/store/__init__.py`:
```python
"""Postgres persistence."""
```

`pipeline/src/advisor/store/db.py`:
```python
"""Database connection and migration helpers."""

from pathlib import Path

import psycopg
from psycopg.rows import dict_row

MIGRATIONS_DIR = Path(__file__).resolve().parents[4] / "supabase" / "migrations"


def connect(url: str) -> psycopg.Connection:
    return psycopg.connect(url, autocommit=True, row_factory=dict_row)


def apply_migrations(conn: psycopg.Connection, directory: Path = MIGRATIONS_DIR) -> list[str]:
    """Run every *.sql file in name order. Used for test databases; Supabase is migrated by hand."""
    applied = []
    for path in sorted(directory.glob("*.sql")):
        conn.execute(path.read_text(encoding="utf-8"))
        applied.append(path.name)
    return applied
```

`pipeline/tests/conftest.py`:
```python
import os
from pathlib import Path

import psycopg
import pytest
from psycopg.rows import dict_row

from advisor.store.db import apply_migrations

FIXTURES = Path(__file__).parent / "fixtures"

# Mimics the parts of Supabase that the migrations rely on: roles, auth.uid(), default grants.
SUPABASE_STUB = """
do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'anon') then create role anon nologin; end if;
  if not exists (select 1 from pg_roles where rolname = 'authenticated') then
    create role authenticated nologin;
  end if;
end $$;
create schema auth;
create function auth.uid() returns uuid language sql stable as $$
  select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid
$$;
grant usage on schema auth to anon, authenticated;
"""
SUPABASE_GRANTS = """
grant usage on schema public to anon, authenticated;
grant select, insert, update, delete on all tables in schema public to anon, authenticated;
grant usage on all sequences in schema public to anon, authenticated;
"""


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture
def db():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    with psycopg.connect(url, autocommit=True, row_factory=dict_row) as conn:
        conn.execute("drop schema if exists public cascade")
        conn.execute("drop schema if exists auth cascade")
        conn.execute("create schema public")
        conn.execute(SUPABASE_STUB)
        apply_migrations(conn)
        conn.execute(SUPABASE_GRANTS)
        yield conn
```

- [ ] **Step 5: Write the failing schema tests**

`pipeline/tests/integration/test_schema.py`:
```python
import uuid
from contextlib import contextmanager

import psycopg
import pytest

OWNER = uuid.UUID("00000000-0000-0000-0000-000000000001")
STRANGER = uuid.UUID("00000000-0000-0000-0000-000000000002")


@contextmanager
def acting_as(conn, role: str, user_id: uuid.UUID | None = None):
    conn.execute(f"set role {role}")
    conn.execute(
        "select set_config('request.jwt.claim.sub', %s, false)", (str(user_id or ""),)
    )
    try:
        yield
    finally:
        conn.execute("reset role")
        conn.execute("select set_config('request.jwt.claim.sub', '', false)")


@pytest.fixture
def owned_db(db):
    db.execute("insert into app_config (id, owner_id) values (1, %s)", (OWNER,))
    db.execute("insert into runs (kind, et_date) values ('pre_open', '2026-10-14')")
    return db


def test_owner_reads_runs(owned_db):
    with acting_as(owned_db, "authenticated", OWNER):
        assert len(owned_db.execute("select * from runs").fetchall()) == 1


def test_stranger_and_anon_see_nothing(owned_db):
    with acting_as(owned_db, "authenticated", STRANGER):
        assert owned_db.execute("select * from runs").fetchall() == []
    with acting_as(owned_db, "anon"):
        assert owned_db.execute("select * from runs").fetchall() == []


def test_owner_can_write_lots_but_not_runs(owned_db):
    with acting_as(owned_db, "authenticated", OWNER):
        owned_db.execute(
            "insert into lots (symbol, asset_type, qty, price, bought_at)"
            " values ('AAPL', 'stock', 1, 100, '2026-10-01')"
        )
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            owned_db.execute("insert into runs (kind, et_date) values ('pre_close', '2026-10-14')")


def test_stranger_cannot_write_lots(owned_db):
    with acting_as(owned_db, "authenticated", STRANGER):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            owned_db.execute(
                "insert into lots (symbol, asset_type, qty, price, bought_at)"
                " values ('AAPL', 'stock', 1, 100, '2026-10-01')"
            )


def test_only_one_published_run_per_kind_and_day(db):
    db.execute("insert into runs (kind, et_date, published) values ('pre_open', '2026-10-14', true)")
    with pytest.raises(psycopg.errors.UniqueViolation):
        db.execute(
            "insert into runs (kind, et_date, published) values ('pre_open', '2026-10-14', true)"
        )
```

- [ ] **Step 6: Run the tests to verify they behave as expected**

Run: `TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:54329/advisor_test uv run pytest tests/integration/test_schema.py -v`
Expected: 5 passed. The migrations were written in Steps 2–3, so this step verifies both the schema and the policies. If any test fails, fix the SQL, not the test.

Also run `uv run pytest tests/integration/test_schema.py -v` without the variable.
Expected: 5 skipped ("TEST_DATABASE_URL not set").

- [ ] **Step 7: Commit**

```bash
uv run ruff check --fix .
git add ../supabase src/advisor/store tests/conftest.py tests/integration/test_schema.py
git commit -m "feat: add Postgres schema, owner-only RLS, and test database fixture" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Collector framework (interface, rate limiter, retries, cache, circuit breaker)

**Files:**
- Create: `pipeline/src/advisor/collectors/__init__.py`, `collectors/base.py`, `collectors/cache.py`, `collectors/runner.py`, `pipeline/tests/fakes.py`
- Test: `pipeline/tests/unit/test_base.py`, `pipeline/tests/unit/test_cache.py`, `pipeline/tests/unit/test_runner.py`

**Interfaces:**
- Consumes: `advisor.models.ET`, `AssetType`, `SymbolInfo`, `DailyBar`
- Produces:
  - `advisor.collectors.base`:
    - `Category`, `Cadence`, `CollectorStatus` (`OK`, `STALE`, `FAILED`, `SKIPPED`)
    - `CollectorResult(name, status, records, latency_ms, error=None)`
    - `Collector` protocol (attributes `name`, `category`, `core`, `best_effort`, `cadence`, `asset_types`, `record_type`, `freshness`; method `fetch(symbols: Sequence[str], as_of: datetime) -> list[BaseModel]`)
    - `RateLimiter(per_minute, burst=1, *, clock, sleep)` with method `.acquire()`
    - `make_client(timeout=20.0) -> httpx.Client`
    - `get_with_retries(client, url, *, params=None, headers=None, limiter=None, attempts=3, base_delay=1.0, sleep=time.sleep) -> httpx.Response`
  - `advisor.collectors.cache.DiskCache(root: Path, clock=...)` with `.put(source, key, records)` and `.get(source, key, record_type, max_age) -> list | None`
  - `advisor.collectors.runner`:
    - `SourceState(consecutive_failures=0, last_attempt_et_date=None)`
    - `BREAKER_THRESHOLD = 3`
    - `breaker_open(state, today_et) -> bool`
    - `run_collector(collector, symbols, as_of, *, cache, state) -> CollectorResult`
    - `next_failures(state, result) -> int`
  - `tests/fakes.py`: `FakeClock`, `FakeCollector`, `info()`, `bar()`, `history()`

- [ ] **Step 1: Write the shared test fakes**

`pipeline/tests/fakes.py`:
```python
"""Test doubles and builders shared by unit and integration tests."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from pydantic import BaseModel

from advisor.collectors.base import Cadence, Category
from advisor.models import AssetType, DailyBar, SymbolInfo


class FakeClock:
    """Monotonic clock whose sleep() advances time instantly and records the duration."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@dataclass
class FakeCollector:
    name: str
    records_for: Callable[[Sequence[str]], list[BaseModel]] = lambda symbols: []
    error: Exception | None = None
    core: bool = True
    best_effort: bool = False
    category: Category = Category.PRICES
    cadence: Cadence = Cadence.PER_RUN
    asset_types: frozenset[AssetType] = frozenset({AssetType.STOCK})
    record_type: type[BaseModel] = DailyBar
    freshness: timedelta | None = None
    calls: list[list[str]] = field(default_factory=list)

    def fetch(self, symbols: Sequence[str], as_of: datetime) -> list[BaseModel]:
        self.calls.append(list(symbols))
        if self.error is not None:
            raise self.error
        return list(self.records_for(symbols))


def info(symbol: str, exchange: str = "NYSE") -> SymbolInfo:
    return SymbolInfo(symbol=symbol, name=f"{symbol} Inc. Common Stock", exchange=exchange)


def bar(
    symbol: str, day: date, close: float, volume: float = 200_000.0, source: str = "alpaca"
) -> DailyBar:
    return DailyBar(
        symbol=symbol, day=day, open=close, high=close, low=close, close=close,
        volume=volume, source=source,
    )


def history(
    symbol: str,
    days: int,
    close: float = 10.0,
    volume: float = 200_000.0,
    source: str = "alpaca",
    start: date = date(2026, 6, 1),
) -> list[DailyBar]:
    return [bar(symbol, start + timedelta(days=i), close, volume, source) for i in range(days)]
```

- [ ] **Step 2: Write the failing tests**

`pipeline/tests/unit/test_base.py`:
```python
import httpx
import pytest
from fakes import FakeClock

from advisor.collectors.base import RateLimiter, get_with_retries


def scripted_client(script):
    """Client whose responses come from `script` in order; an Exception item is raised."""
    calls = []
    items = iter(script)

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        item = next(items)
        if isinstance(item, Exception):
            raise item
        return item

    return httpx.Client(transport=httpx.MockTransport(handler)), calls


class CountingLimiter:
    def __init__(self) -> None:
        self.count = 0

    def acquire(self) -> None:
        self.count += 1


def test_rate_limiter_allows_burst_then_waits():
    clock = FakeClock()
    limiter = RateLimiter(per_minute=60, burst=2, clock=clock, sleep=clock.sleep)
    limiter.acquire()
    limiter.acquire()
    assert clock.sleeps == []
    limiter.acquire()
    assert clock.sleeps == [pytest.approx(1.0)]


def test_rate_limiter_refills_over_time():
    clock = FakeClock()
    limiter = RateLimiter(per_minute=60, burst=1, clock=clock, sleep=clock.sleep)
    limiter.acquire()
    clock.now += 1.0
    limiter.acquire()
    assert clock.sleeps == []


def test_retries_retryable_status_then_succeeds():
    client, calls = scripted_client([httpx.Response(503), httpx.Response(200, text="ok")])
    sleeps = []
    limiter = CountingLimiter()
    response = get_with_retries(
        client, "https://example.test/x", limiter=limiter, sleep=sleeps.append
    )
    assert response.text == "ok"
    assert len(calls) == 2
    assert sleeps == [1.0]
    assert limiter.count == 2


def test_non_retryable_status_raises_immediately():
    client, calls = scripted_client([httpx.Response(403)])
    sleeps = []
    with pytest.raises(httpx.HTTPStatusError):
        get_with_retries(client, "https://example.test/x", sleep=sleeps.append)
    assert len(calls) == 1
    assert sleeps == []


def test_transport_errors_exhaust_attempts_with_backoff():
    boom = httpx.ConnectError("down")
    client, calls = scripted_client([boom, boom, boom])
    sleeps = []
    with pytest.raises(httpx.ConnectError):
        get_with_retries(client, "https://example.test/x", sleep=sleeps.append)
    assert len(calls) == 3
    assert sleeps == [1.0, 2.0]
```

`pipeline/tests/unit/test_cache.py`:
```python
from datetime import UTC, datetime, timedelta

from fakes import info

from advisor.collectors.cache import DiskCache
from advisor.models import SymbolInfo

T0 = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)


def test_put_then_get_round_trips_records(tmp_path):
    cache = DiskCache(tmp_path, clock=lambda: T0)
    cache.put("nasdaq_symbols", "", [info("AAPL"), info("MSFT")])
    got = cache.get("nasdaq_symbols", "", SymbolInfo, timedelta(days=1))
    assert [r.symbol for r in got] == ["AAPL", "MSFT"]


def test_get_returns_none_when_older_than_max_age(tmp_path):
    now = [T0]
    cache = DiskCache(tmp_path, clock=lambda: now[0])
    cache.put("s", "k", [info("AAPL")])
    now[0] = T0 + timedelta(days=2)
    assert cache.get("s", "k", SymbolInfo, timedelta(days=1)) is None


def test_get_returns_none_for_missing_or_corrupt_entries(tmp_path):
    cache = DiskCache(tmp_path, clock=lambda: T0)
    assert cache.get("s", "k", SymbolInfo, timedelta(days=1)) is None
    cache.put("s", "k", [info("AAPL")])
    for path in tmp_path.rglob("*.json"):
        path.write_text("{not json", encoding="utf-8")
    assert cache.get("s", "k", SymbolInfo, timedelta(days=1)) is None
```

`pipeline/tests/unit/test_runner.py`:
```python
from datetime import UTC, date, datetime, timedelta

import httpx
from fakes import FakeCollector, info

from advisor.collectors.base import Cadence, CollectorResult, CollectorStatus
from advisor.collectors.cache import DiskCache
from advisor.collectors.runner import SourceState, breaker_open, next_failures, run_collector
from advisor.models import SymbolInfo

NOW = datetime(2026, 10, 14, 12, 15, tzinfo=UTC)  # 08:15 ET
TODAY = date(2026, 10, 14)


def universe_collector(**kwargs) -> FakeCollector:
    defaults = dict(
        name="universe",
        records_for=lambda symbols: [info("AAPL")],
        record_type=SymbolInfo,
        cadence=Cadence.DAILY,
        freshness=timedelta(days=3),
    )
    return FakeCollector(**{**defaults, **kwargs})


def test_success_returns_ok_and_caches(tmp_path):
    cache = DiskCache(tmp_path, clock=lambda: NOW)
    result = run_collector(universe_collector(), [], NOW, cache=cache, state=SourceState())
    assert result.status is CollectorStatus.OK
    assert [r.symbol for r in result.records] == ["AAPL"]
    assert cache.get("universe", "", SymbolInfo, timedelta(days=1)) is not None


def test_failure_falls_back_to_fresh_cache_as_stale(tmp_path):
    cache = DiskCache(tmp_path, clock=lambda: NOW)
    cache.put("universe", "", [info("MSFT")])
    collector = universe_collector(error=httpx.ConnectError("down"))
    result = run_collector(collector, [], NOW, cache=cache, state=SourceState())
    assert result.status is CollectorStatus.STALE
    assert [r.symbol for r in result.records] == ["MSFT"]
    assert result.error == "ConnectError: down"


def test_failure_without_cache_is_failed(tmp_path):
    collector = universe_collector(error=ValueError("bad payload"), freshness=None)
    result = run_collector(
        collector, [], NOW, cache=DiskCache(tmp_path), state=SourceState()
    )
    assert result.status is CollectorStatus.FAILED
    assert result.records == []
    assert result.error == "ValueError: bad payload"


def test_open_breaker_skips_without_fetching(tmp_path):
    collector = universe_collector()
    state = SourceState(consecutive_failures=3, last_attempt_et_date=TODAY)
    result = run_collector(collector, [], NOW, cache=DiskCache(tmp_path), state=state)
    assert result.status is CollectorStatus.SKIPPED
    assert collector.calls == []


def test_breaker_is_half_open_on_a_new_day():
    yesterday = SourceState(consecutive_failures=5, last_attempt_et_date=date(2026, 10, 13))
    assert breaker_open(yesterday, TODAY) is False
    assert breaker_open(SourceState(2, TODAY), TODAY) is False
    assert breaker_open(SourceState(3, TODAY), TODAY) is True


def test_next_failures_counts_consecutive_failures():
    state = SourceState(consecutive_failures=2)

    def result(status: CollectorStatus) -> CollectorResult:
        return CollectorResult("s", status, [], 0)

    assert next_failures(state, result(CollectorStatus.OK)) == 0
    assert next_failures(state, result(CollectorStatus.FAILED)) == 3
    assert next_failures(state, result(CollectorStatus.STALE)) == 3
    assert next_failures(state, result(CollectorStatus.SKIPPED)) == 2
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_base.py tests/unit/test_cache.py tests/unit/test_runner.py -v`
Expected: collection errors with `ModuleNotFoundError: No module named 'advisor.collectors'`.

- [ ] **Step 4: Implement `base.py`**

`pipeline/src/advisor/collectors/__init__.py`:
```python
"""Data-source collectors: one module per source, registered in registry.py."""
```

`pipeline/src/advisor/collectors/base.py`:
```python
"""Shared building blocks for collectors: the interface, rate limiting, and HTTP retries."""

import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Protocol

import httpx
from pydantic import BaseModel

from advisor.models import AssetType

USER_AGENT = "stock-advisor/0.1 (personal research)"
RETRY_STATUS = frozenset({429, 500, 502, 503, 504})


class Category(StrEnum):
    PRICES = "prices"
    FUNDAMENTALS = "fundamentals"
    OPTIONS = "options"
    MACRO = "macro"
    NEWS = "news"
    SOCIAL = "social"
    CATALYSTS = "catalysts"
    ONCHAIN = "onchain"


class Cadence(StrEnum):
    PER_RUN = "per_run"
    DAILY = "daily"
    WEEKLY = "weekly"


class CollectorStatus(StrEnum):
    OK = "ok"
    STALE = "stale"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class CollectorResult:
    name: str
    status: CollectorStatus
    records: list[BaseModel]
    latency_ms: int
    error: str | None = None


class Collector(Protocol):
    """One data source. `fetch` returns validated records or raises; `run_collector` wraps it."""

    name: str
    category: Category
    core: bool
    best_effort: bool
    cadence: Cadence
    asset_types: frozenset[AssetType]
    record_type: type[BaseModel]
    freshness: timedelta | None  # max cache age used as a failure fallback; None = never cache

    def fetch(self, symbols: Sequence[str], as_of: datetime) -> list[BaseModel]: ...


class RateLimiter:
    """Token bucket: a steady `per_minute` rate with up to `burst` back-to-back calls."""

    def __init__(
        self,
        per_minute: float,
        burst: int = 1,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._rate = per_minute / 60.0
        self._burst = float(burst)
        self._tokens = float(burst)
        self._clock = clock
        self._sleep = sleep
        self._last = clock()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            now = self._clock()
            self._tokens = min(self._burst, self._tokens + (now - self._last) * self._rate)
            self._last = now
            if self._tokens >= 1:
                self._tokens -= 1
                return
            self._sleep((1 - self._tokens) / self._rate)
            self._last = self._clock()
            self._tokens = 0.0


def make_client(timeout: float = 20.0) -> httpx.Client:
    return httpx.Client(
        timeout=timeout, follow_redirects=True, headers={"User-Agent": USER_AGENT}
    )


def get_with_retries(
    client: httpx.Client,
    url: str,
    *,
    params: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
    limiter: RateLimiter | None = None,
    attempts: int = 3,
    base_delay: float = 1.0,
    sleep: Callable[[float], None] = time.sleep,
) -> httpx.Response:
    """GET with exponential backoff on transport errors and 429/5xx; other errors raise at once."""
    last_error: Exception | None = None
    for attempt in range(attempts):
        if limiter is not None:
            limiter.acquire()
        try:
            response = client.get(url, params=params, headers=headers)
        except httpx.TransportError as exc:
            last_error = exc
        else:
            if response.status_code not in RETRY_STATUS:
                response.raise_for_status()
                return response
            last_error = httpx.HTTPStatusError(
                f"HTTP {response.status_code} from {url}",
                request=response.request,
                response=response,
            )
        if attempt < attempts - 1:
            sleep(base_delay * 2**attempt)
    assert last_error is not None
    raise last_error
```

- [ ] **Step 5: Implement `cache.py`**

`pipeline/src/advisor/collectors/cache.py`:
```python
"""On-disk cache of collector records, used as a fallback when a source fails."""

import hashlib
import json
import os
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import BaseModel


class DiskCache:
    def __init__(
        self, root: Path, clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    ) -> None:
        self._root = Path(root)
        self._clock = clock

    def _path(self, source: str, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
        return self._root / source / f"{digest}.json"

    def put(self, source: str, key: str, records: Sequence[BaseModel]) -> None:
        path = self._path(source, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "saved_at": self._clock().isoformat(),
            "records": [record.model_dump(mode="json") for record in records],
        }
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(tmp, path)

    def get(
        self, source: str, key: str, record_type: type[BaseModel], max_age: timedelta
    ) -> list[BaseModel] | None:
        try:
            payload = json.loads(self._path(source, key).read_text(encoding="utf-8"))
            saved_at = datetime.fromisoformat(payload["saved_at"])
            if self._clock() - saved_at > max_age:
                return None
            return [record_type.model_validate(raw) for raw in payload["records"]]
        except (OSError, ValueError, KeyError):  # missing, corrupt, or schema-changed entries
            return None
```

- [ ] **Step 6: Implement `runner.py`**

`pipeline/src/advisor/collectors/runner.py`:
```python
"""Runs one collector safely: circuit breaker, timing, error capture, cache fallback."""

import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime

from advisor.collectors.base import Collector, CollectorResult, CollectorStatus
from advisor.collectors.cache import DiskCache
from advisor.models import ET

BREAKER_THRESHOLD = 3


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
    if result.status is CollectorStatus.OK:
        return 0
    return state.consecutive_failures + 1


def cache_key(symbols: Sequence[str]) -> str:
    return ",".join(sorted(symbols))


def run_collector(
    collector: Collector,
    symbols: Sequence[str],
    as_of: datetime,
    *,
    cache: DiskCache,
    state: SourceState,
) -> CollectorResult:
    if breaker_open(state, as_of.astimezone(ET).date()):
        return CollectorResult(collector.name, CollectorStatus.SKIPPED, [], 0, "circuit breaker open")

    key = cache_key(symbols)
    started = time.perf_counter()
    try:
        records = list(collector.fetch(symbols, as_of))
    except Exception as exc:  # any source failure is contained here
        latency = int((time.perf_counter() - started) * 1000)
        error = f"{type(exc).__name__}: {exc}"[:500]
        if collector.freshness is not None:
            cached = cache.get(collector.name, key, collector.record_type, collector.freshness)
            if cached is not None:
                return CollectorResult(collector.name, CollectorStatus.STALE, cached, latency, error)
        return CollectorResult(collector.name, CollectorStatus.FAILED, [], latency, error)

    latency = int((time.perf_counter() - started) * 1000)
    if collector.freshness is not None:
        cache.put(collector.name, key, records)
    return CollectorResult(collector.name, CollectorStatus.OK, records, latency)
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_base.py tests/unit/test_cache.py tests/unit/test_runner.py -v`
Expected: 14 passed.

- [ ] **Step 8: Commit**

```bash
uv run ruff check --fix .
git add src/advisor/collectors tests/fakes.py tests/unit/test_base.py tests/unit/test_cache.py tests/unit/test_runner.py
git commit -m "feat: add collector framework with rate limiting, retries, cache, and circuit breaker" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Store repository (all pipeline SQL)

**Files:**
- Create: `pipeline/src/advisor/store/repo.py`
- Test: `pipeline/tests/integration/test_repo.py`

**Interfaces:**
- Consumes: `CollectorResult`, `SourceState`, `ET`, `RunKind`, `RunStatus`, `AssetRef`, `AssetType`, `SymbolInfo`
- Produces (all take `conn: psycopg.Connection` first):
  - `create_run(conn, kind: RunKind, et_date: date) -> int`
  - `finish_run(conn, run_id: int, status: RunStatus, *, sources_ok: int, sources_total: int, summary: dict) -> None`. Publishes when status is success or degraded, replacing any earlier published run in the same slot.
  - `has_published_run(conn, kind: RunKind, et_date: date) -> bool`
  - `record_source_health(conn, run_id: int, result: CollectorResult, consecutive_failures: int, attempted_at: datetime) -> None`
  - `load_source_state(conn, source: str) -> SourceState`
  - `upsert_symbols(conn, symbols: Sequence[SymbolInfo]) -> None`. Marks stocks missing from the list as inactive.
  - `load_held_symbols(conn) -> set[AssetRef]` (net quantity > 0)
  - `load_watchlist(conn) -> set[AssetRef]`
  - `write_features_live(conn, run_id: int, rows: Sequence[tuple[AssetRef, dict]], as_of: datetime) -> None`

- [ ] **Step 1: Write the failing tests**

`pipeline/tests/integration/test_repo.py`:
```python
from datetime import UTC, date, datetime

from fakes import info

from advisor.collectors.base import CollectorResult, CollectorStatus
from advisor.models import AssetRef, AssetType, RunKind, RunStatus
from advisor.store import repo

DAY = date(2026, 10, 14)
NOW = datetime(2026, 10, 14, 12, 15, tzinfo=UTC)


def finish(db, run_id, status):
    repo.finish_run(db, run_id, status, sources_ok=2, sources_total=3, summary={"universe": 5})


def test_success_and_degraded_runs_publish_failed_does_not(db):
    for status, published in [
        (RunStatus.SUCCESS, True),
        (RunStatus.DEGRADED, True),
        (RunStatus.FAILED, False),
    ]:
        kind = {RunStatus.SUCCESS: RunKind.PRE_OPEN, RunStatus.DEGRADED: RunKind.PRE_CLOSE,
                RunStatus.FAILED: RunKind.EARLY_CLOSE}[status]
        run_id = repo.create_run(db, kind, DAY)
        finish(db, run_id, status)
        row = db.execute("select * from runs where id = %s", (run_id,)).fetchone()
        assert row["status"] == status.value
        assert row["published"] is published
        assert row["finished_at"] is not None
        assert row["summary"] == {"universe": 5}
        assert (row["sources_ok"], row["sources_total"]) == (2, 3)


def test_rerun_replaces_the_published_run_for_the_same_slot(db):
    first = repo.create_run(db, RunKind.PRE_OPEN, DAY)
    finish(db, first, RunStatus.SUCCESS)
    second = repo.create_run(db, RunKind.PRE_OPEN, DAY)
    finish(db, second, RunStatus.SUCCESS)
    published = db.execute("select id from runs where published").fetchall()
    assert [r["id"] for r in published] == [second]


def test_has_published_run(db):
    assert repo.has_published_run(db, RunKind.PRE_OPEN, DAY) is False
    run_id = repo.create_run(db, RunKind.PRE_OPEN, DAY)
    assert repo.has_published_run(db, RunKind.PRE_OPEN, DAY) is False
    finish(db, run_id, RunStatus.SUCCESS)
    assert repo.has_published_run(db, RunKind.PRE_OPEN, DAY) is True
    assert repo.has_published_run(db, RunKind.PRE_CLOSE, DAY) is False


def test_source_state_tracks_failures_and_ignores_skips_for_last_attempt(db):
    run_id = repo.create_run(db, RunKind.PRE_OPEN, DAY)
    assert repo.load_source_state(db, "alpaca_bars").consecutive_failures == 0

    failed = CollectorResult("alpaca_bars", CollectorStatus.FAILED, [], 120, "ConnectError: down")
    repo.record_source_health(db, run_id, failed, 3, datetime(2026, 10, 13, 19, 15, tzinfo=UTC))
    skipped = CollectorResult("alpaca_bars", CollectorStatus.SKIPPED, [], 0, "circuit breaker open")
    repo.record_source_health(db, run_id, skipped, 3, NOW)

    state = repo.load_source_state(db, "alpaca_bars")
    assert state.consecutive_failures == 3
    assert state.last_attempt_et_date == date(2026, 10, 13)

    row = db.execute("select * from source_health where status = 'failed'").fetchone()
    assert (row["latency_ms"], row["records"], row["error"]) == (120, 0, "ConnectError: down")


def test_upsert_symbols_inserts_updates_and_deactivates(db):
    repo.upsert_symbols(db, [info("AAPL"), info("GONE")])
    repo.upsert_symbols(db, [info("AAPL", exchange="NASDAQ"), info("MSFT")])
    rows = db.execute("select symbol, exchange, active from symbols order by symbol").fetchall()
    assert [(r["symbol"], r["exchange"], r["active"]) for r in rows] == [
        ("AAPL", "NASDAQ", True),
        ("GONE", "NYSE", False),
        ("MSFT", "NYSE", True),
    ]


def test_load_held_symbols_nets_sells(db):
    db.execute(
        "insert into lots (symbol, asset_type, qty, price, bought_at) values"
        " ('AAPL', 'stock', 10, 100, '2026-01-02'),"
        " ('SOLD', 'stock', 5, 20, '2026-01-02'),"
        " ('BTC', 'crypto', 0.5, 60000, '2026-02-01')"
    )
    db.execute(
        "insert into sells (symbol, asset_type, qty, price, sold_at) values"
        " ('AAPL', 'stock', 4, 120, '2026-05-01'), ('SOLD', 'stock', 5, 25, '2026-05-01')"
    )
    assert repo.load_held_symbols(db) == {
        AssetRef("AAPL", AssetType.STOCK),
        AssetRef("BTC", AssetType.CRYPTO),
    }


def test_load_watchlist(db):
    db.execute("insert into watchlist (symbol, asset_type) values ('NVDA', 'stock'), ('ETH', 'crypto')")
    assert repo.load_watchlist(db) == {
        AssetRef("NVDA", AssetType.STOCK),
        AssetRef("ETH", AssetType.CRYPTO),
    }


def test_write_features_live(db):
    run_id = repo.create_run(db, RunKind.PRE_OPEN, DAY)
    repo.write_features_live(
        db, run_id, [(AssetRef("AAPL", AssetType.STOCK), {"last_close": 150.0})], NOW
    )
    repo.write_features_live(db, run_id, [], NOW)
    row = db.execute("select * from features_live").fetchone()
    assert (row["symbol"], row["asset_type"], row["features"]) == (
        "AAPL", "stock", {"last_close": 150.0},
    )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:54329/advisor_test uv run pytest tests/integration/test_repo.py -v`
Expected: FAIL with `ImportError: cannot import name 'repo' from 'advisor.store'`.

- [ ] **Step 3: Implement**

`pipeline/src/advisor/store/repo.py`:
```python
"""Every SQL statement the pipeline runs. Functions take an open autocommit connection."""

from collections.abc import Sequence
from datetime import date, datetime

import psycopg
from psycopg.types.json import Jsonb

from advisor.collectors.base import CollectorResult
from advisor.collectors.runner import SourceState
from advisor.models import ET, AssetRef, AssetType, RunKind, RunStatus, SymbolInfo

PUBLISHABLE = frozenset({RunStatus.SUCCESS, RunStatus.DEGRADED})


def create_run(conn: psycopg.Connection, kind: RunKind, et_date: date) -> int:
    row = conn.execute(
        "insert into runs (kind, et_date) values (%s, %s) returning id", (kind.value, et_date)
    ).fetchone()
    return row["id"]


def finish_run(
    conn: psycopg.Connection,
    run_id: int,
    status: RunStatus,
    *,
    sources_ok: int,
    sources_total: int,
    summary: dict,
) -> None:
    publish = status in PUBLISHABLE
    with conn.transaction():
        if publish:
            conn.execute(
                "update runs set published = false"
                " where published and id <> %(id)s"
                " and (kind, et_date) = (select kind, et_date from runs where id = %(id)s)",
                {"id": run_id},
            )
        conn.execute(
            "update runs set status = %s, finished_at = now(), sources_ok = %s,"
            " sources_total = %s, summary = %s, published = %s where id = %s",
            (status.value, sources_ok, sources_total, Jsonb(summary), publish, run_id),
        )


def has_published_run(conn: psycopg.Connection, kind: RunKind, et_date: date) -> bool:
    row = conn.execute(
        "select exists (select 1 from runs where published and kind = %s and et_date = %s)"
        " as found",
        (kind.value, et_date),
    ).fetchone()
    return row["found"]


def record_source_health(
    conn: psycopg.Connection,
    run_id: int,
    result: CollectorResult,
    consecutive_failures: int,
    attempted_at: datetime,
) -> None:
    conn.execute(
        "insert into source_health (run_id, source, status, latency_ms, records, error,"
        " consecutive_failures, attempted_at) values (%s, %s, %s, %s, %s, %s, %s, %s)",
        (
            run_id, result.name, result.status.value, result.latency_ms, len(result.records),
            result.error, consecutive_failures, attempted_at,
        ),
    )


def load_source_state(conn: psycopg.Connection, source: str) -> SourceState:
    row = conn.execute(
        "select"
        " (select consecutive_failures from source_health where source = %(s)s"
        "   order by attempted_at desc, id desc limit 1) as failures,"
        " (select max(attempted_at) from source_health where source = %(s)s"
        "   and status <> 'skipped') as last_attempt",
        {"s": source},
    ).fetchone()
    last_attempt = row["last_attempt"]
    return SourceState(
        consecutive_failures=row["failures"] or 0,
        last_attempt_et_date=last_attempt.astimezone(ET).date() if last_attempt else None,
    )


def upsert_symbols(conn: psycopg.Connection, symbols: Sequence[SymbolInfo]) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            "insert into symbols (symbol, asset_type, name, exchange, active, updated_at)"
            " values (%s, %s, %s, %s, true, now())"
            " on conflict (symbol, asset_type) do update set name = excluded.name,"
            " exchange = excluded.exchange, active = true, updated_at = now()",
            [(s.symbol, s.asset_type.value, s.name, s.exchange) for s in symbols],
        )
    stock_symbols = [s.symbol for s in symbols if s.asset_type is AssetType.STOCK]
    conn.execute(
        "update symbols set active = false, updated_at = now()"
        " where asset_type = 'stock' and active and not (symbol = any(%s))",
        (stock_symbols,),
    )


def load_held_symbols(conn: psycopg.Connection) -> set[AssetRef]:
    rows = conn.execute(
        "with bought as (select symbol, asset_type, sum(qty) as qty from lots"
        "   group by symbol, asset_type),"
        " sold as (select symbol, asset_type, sum(qty) as qty from sells"
        "   group by symbol, asset_type)"
        " select b.symbol, b.asset_type from bought b left join sold s using (symbol, asset_type)"
        " where b.qty - coalesce(s.qty, 0) > 0"
    ).fetchall()
    return {AssetRef(r["symbol"], AssetType(r["asset_type"])) for r in rows}


def load_watchlist(conn: psycopg.Connection) -> set[AssetRef]:
    rows = conn.execute("select symbol, asset_type from watchlist").fetchall()
    return {AssetRef(r["symbol"], AssetType(r["asset_type"])) for r in rows}


def write_features_live(
    conn: psycopg.Connection,
    run_id: int,
    rows: Sequence[tuple[AssetRef, dict]],
    as_of: datetime,
) -> None:
    if not rows:
        return
    with conn.cursor() as cur:
        cur.executemany(
            "insert into features_live (run_id, symbol, asset_type, features, as_of)"
            " values (%s, %s, %s, %s, %s)",
            [(run_id, ref.symbol, ref.asset_type.value, Jsonb(feats), as_of) for ref, feats in rows],
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:54329/advisor_test uv run pytest tests/integration/test_repo.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
uv run ruff check --fix .
git add src/advisor/store/repo.py tests/integration/test_repo.py
git commit -m "feat: add store repository for runs, source health, symbols, and holdings" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: NASDAQ Trader universe collector (source 1)

**Files:**
- Create: `pipeline/src/advisor/collectors/nasdaq_symbols.py`, `pipeline/tests/fixtures/nasdaqlisted.txt`, `pipeline/tests/fixtures/otherlisted.txt`
- Test: `pipeline/tests/unit/test_nasdaq_symbols.py`

**Interfaces:**
- Consumes: `get_with_retries`, `RateLimiter`, `Category`, `Cadence`, `SymbolInfo`, `AssetType`
- Produces:
  - `NasdaqSymbols(client: httpx.Client, limiter: RateLimiter | None = None)`: name `nasdaq_symbols`, core, daily, freshness 3 days, `record_type=SymbolInfo`. `fetch` ignores `symbols` and returns sorted, de-duplicated `SymbolInfo` records.
  - Module functions `parse_nasdaq_listed(text) -> list[SymbolInfo]`, `parse_other_listed(text) -> list[SymbolInfo]`
  - Constants `NASDAQ_LISTED_URL`, `OTHER_LISTED_URL`

- [ ] **Step 1: Create the recorded fixtures** (same format as the live files)

`pipeline/tests/fixtures/nasdaqlisted.txt`:
```
Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares
AAPL|Apple Inc. - Common Stock|Q|N|N|100|N|N
UAL|United Airlines Holdings, Inc. - Common Stock|Q|N|N|100|N|N
PFBC|Preferred Bank - Common Stock|Q|N|N|100|N|N
ABCDW|ABCD Acquisition Corp - Warrant|G|N|N|100|N|N
ABCDU|ABCD Acquisition Corp - Units|G|N|N|100|N|N
ABCDR|ABCD Acquisition Corp - Rights|G|N|N|100|N|N
ZZZT|Test Company - Common Stock|Q|Y|N|100|N|N
QQQ|Invesco QQQ Trust, Series 1|G|N|N|100|Y|N
File Creation Time: 1009202608:00|||||||
```

`pipeline/tests/fixtures/otherlisted.txt`:
```
ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol
BRK.B|Berkshire Hathaway Inc. Class B Common Stock|N|BRK.B|N|100|N|BRK=B
JPM|JPMorgan Chase & Co. Common Stock|N|JPM|N|100|N|JPM
JPM$D|JPMorgan Chase & Co. Depositary Shares Series DD Preferred|N|JPMpD|N|100|N|JPM-D
SPY|SPDR S&P 500 ETF Trust|P|SPY|Y|100|N|SPY
TSM|Taiwan Semiconductor Manufacturing Company Ltd. American Depositary Shares|N|TSM|N|100|N|TSM
AAPL|Apple Inc. duplicate listing|N|AAPL|N|100|N|AAPL
File Creation Time: 1009202608:00|||||||
```

- [ ] **Step 2: Write the failing test**

`pipeline/tests/unit/test_nasdaq_symbols.py`:
```python
from datetime import UTC, datetime

import httpx

from advisor.collectors.nasdaq_symbols import (
    NASDAQ_LISTED_URL,
    OTHER_LISTED_URL,
    NasdaqSymbols,
    parse_nasdaq_listed,
    parse_other_listed,
)

NOW = datetime(2026, 10, 14, 12, 15, tzinfo=UTC)


def test_parse_nasdaq_listed_keeps_only_common_stocks(fixtures_dir):
    text = (fixtures_dir / "nasdaqlisted.txt").read_text(encoding="utf-8")
    assert [(s.symbol, s.exchange) for s in parse_nasdaq_listed(text)] == [
        ("AAPL", "NASDAQ"),
        ("UAL", "NASDAQ"),   # "United" must not match the "unit" exclusion
        ("PFBC", "NASDAQ"),  # "Preferred Bank" is a common stock
    ]


def test_parse_other_listed_maps_exchanges_and_excludes_etfs_and_preferreds(fixtures_dir):
    text = (fixtures_dir / "otherlisted.txt").read_text(encoding="utf-8")
    assert [(s.symbol, s.exchange) for s in parse_other_listed(text)] == [
        ("BRK.B", "NYSE"),
        ("JPM", "NYSE"),
        ("TSM", "NYSE"),  # ADRs are kept
        ("AAPL", "NYSE"),
    ]


def test_fetch_merges_both_files_sorted_and_deduplicated(fixtures_dir):
    files = {
        NASDAQ_LISTED_URL: (fixtures_dir / "nasdaqlisted.txt").read_text(encoding="utf-8"),
        OTHER_LISTED_URL: (fixtures_dir / "otherlisted.txt").read_text(encoding="utf-8"),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=files[str(request.url)])

    collector = NasdaqSymbols(httpx.Client(transport=httpx.MockTransport(handler)))
    records = collector.fetch([], NOW)
    assert [(r.symbol, r.exchange) for r in records] == [
        ("AAPL", "NASDAQ"),  # the NASDAQ listing wins over the duplicate
        ("BRK.B", "NYSE"),
        ("JPM", "NYSE"),
        ("PFBC", "NASDAQ"),
        ("TSM", "NYSE"),
        ("UAL", "NASDAQ"),
    ]
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_nasdaq_symbols.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'advisor.collectors.nasdaq_symbols'`.

- [ ] **Step 4: Implement**

`pipeline/src/advisor/collectors/nasdaq_symbols.py`:
```python
"""US-listed common stocks from the NASDAQ Trader symbol directory (source 1)."""

import csv
import io
import re
from collections.abc import Sequence
from datetime import datetime, timedelta

import httpx

from advisor.collectors.base import Cadence, Category, RateLimiter, get_with_retries
from advisor.models import AssetType, SymbolInfo

NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
OTHER_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"
OTHER_EXCHANGES = {
    "A": "NYSE American",
    "N": "NYSE",
    "P": "NYSE Arca",
    "Z": "Cboe BZX",
    "V": "IEX",
}
# Plain tickers plus one-letter share classes (BRK.B). Excludes JPM$D, ABC.WS, etc.
SYMBOL_PATTERN = re.compile(r"^[A-Z]{1,5}(\.[A-Z])?$")
# Whole-word matches only, so "United" and "Preferred Bank" survive.
EXCLUDED_NAME = re.compile(
    r"\b(warrants?|units?|rights?|notes due|debentures?)\b"
    r"|\bpreferred (stock|shares|securities)\b"
    r"|\bdepositary shares\b.*\bpreferred\b",
    re.IGNORECASE,
)


def _rows(text: str) -> list[dict[str, str]]:
    lines = [
        line for line in text.splitlines() if line and not line.startswith("File Creation Time")
    ]
    return list(csv.DictReader(io.StringIO("\n".join(lines)), delimiter="|"))


def _keep(symbol: str, name: str, etf: str, test_issue: str) -> bool:
    return (
        etf == "N"
        and test_issue == "N"
        and SYMBOL_PATTERN.match(symbol) is not None
        and EXCLUDED_NAME.search(name) is None
    )


def parse_nasdaq_listed(text: str) -> list[SymbolInfo]:
    return [
        SymbolInfo(symbol=row["Symbol"], name=row["Security Name"], exchange="NASDAQ")
        for row in _rows(text)
        if _keep(row["Symbol"], row["Security Name"], row["ETF"], row["Test Issue"])
    ]


def parse_other_listed(text: str) -> list[SymbolInfo]:
    return [
        SymbolInfo(
            symbol=row["ACT Symbol"],
            name=row["Security Name"],
            exchange=OTHER_EXCHANGES.get(row["Exchange"], row["Exchange"]),
        )
        for row in _rows(text)
        if _keep(row["ACT Symbol"], row["Security Name"], row["ETF"], row["Test Issue"])
    ]


class NasdaqSymbols:
    name = "nasdaq_symbols"
    category = Category.PRICES
    core = True
    best_effort = False
    cadence = Cadence.DAILY
    asset_types = frozenset({AssetType.STOCK})
    record_type = SymbolInfo
    freshness = timedelta(days=3)

    def __init__(self, client: httpx.Client, limiter: RateLimiter | None = None) -> None:
        self._client = client
        self._limiter = limiter

    def fetch(self, symbols: Sequence[str], as_of: datetime) -> list[SymbolInfo]:
        nasdaq = get_with_retries(self._client, NASDAQ_LISTED_URL, limiter=self._limiter).text
        other = get_with_retries(self._client, OTHER_LISTED_URL, limiter=self._limiter).text
        merged: dict[str, SymbolInfo] = {}
        for record in parse_nasdaq_listed(nasdaq) + parse_other_listed(other):
            merged.setdefault(record.symbol, record)
        return sorted(merged.values(), key=lambda record: record.symbol)
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_nasdaq_symbols.py -v`
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
uv run ruff check --fix .
git add src/advisor/collectors/nasdaq_symbols.py tests/fixtures tests/unit/test_nasdaq_symbols.py
git commit -m "feat: add NASDAQ Trader universe collector" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Alpaca daily-bars collector (source 2)

**Files:**
- Create: `pipeline/src/advisor/collectors/alpaca_bars.py`
- Test: `pipeline/tests/unit/test_alpaca_bars.py`

**Interfaces:**
- Consumes: `get_with_retries`, `RateLimiter`, `DailyBar`, `ET`
- Produces: `AlpacaBars(client, key_id: str, secret_key: str, limiter: RateLimiter | None = None)`: name `alpaca_bars`, core, per-run, `freshness=None`, `record_type=DailyBar`. `fetch(symbols, as_of)` returns split- and dividend-adjusted SIP daily bars covering `as_of - 100 days` to `as_of - 16 minutes`. Invalid rows are dropped.

- [ ] **Step 1: Write the failing test**

`pipeline/tests/unit/test_alpaca_bars.py`:
```python
from datetime import UTC, date, datetime

import httpx

from advisor.collectors.alpaca_bars import ALPACA_BARS_URL, AlpacaBars
from advisor.collectors.base import RateLimiter

AS_OF = datetime(2026, 10, 14, 19, 15, tzinfo=UTC)  # 15:15 ET
FAST = RateLimiter(per_minute=60_000, burst=1_000)


def raw(t: str, close: float) -> dict:
    return {"t": t, "o": close, "h": close, "l": close, "c": close, "v": 1000, "n": 10, "vw": close}


def test_fetch_follows_pages_and_drops_invalid_bars():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert str(request.url).startswith(ALPACA_BARS_URL)
        assert request.headers["APCA-API-KEY-ID"] == "key"
        assert request.headers["APCA-API-SECRET-KEY"] == "secret"
        if request.url.params.get("page_token") is None:
            return httpx.Response(200, json={
                "bars": {"AAPL": [raw("2026-10-12T04:00:00Z", 1.5)]},
                "next_page_token": "p2",
            })
        return httpx.Response(200, json={
            "bars": {
                "AAPL": [raw("2026-10-13T04:00:00Z", 1.6)],
                "MSFT": [raw("2026-10-13T04:00:00Z", 0)],  # invalid: close must be > 0
            },
            "next_page_token": None,
        })

    collector = AlpacaBars(
        httpx.Client(transport=httpx.MockTransport(handler)), "key", "secret", limiter=FAST
    )
    bars = collector.fetch(["MSFT", "AAPL", "AAPL"], AS_OF)

    assert [(b.symbol, b.day, b.close, b.source) for b in bars] == [
        ("AAPL", date(2026, 10, 12), 1.5, "alpaca"),
        ("AAPL", date(2026, 10, 13), 1.6, "alpaca"),
    ]
    params = seen[0].url.params
    assert params["symbols"] == "AAPL,MSFT"
    assert params["timeframe"] == "1Day"
    assert params["feed"] == "sip"
    assert params["adjustment"] == "all"
    assert params["start"] == "2026-07-06T19:15:00Z"
    assert params["end"] == "2026-10-14T18:59:00Z"
    assert seen[1].url.params["page_token"] == "p2"


def test_fetch_chunks_symbols_two_hundred_per_request():
    sizes: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sizes.append(len(request.url.params["symbols"].split(",")))
        return httpx.Response(200, json={"bars": {}, "next_page_token": None})

    collector = AlpacaBars(
        httpx.Client(transport=httpx.MockTransport(handler)), "key", "secret", limiter=FAST
    )
    symbols = [f"S{i:03d}" for i in range(250)]
    assert collector.fetch(symbols, AS_OF) == []
    assert sizes == [200, 50]


def test_fetch_with_no_symbols_makes_no_requests():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request expected")

    collector = AlpacaBars(
        httpx.Client(transport=httpx.MockTransport(handler)), "key", "secret", limiter=FAST
    )
    assert collector.fetch([], AS_OF) == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_alpaca_bars.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'advisor.collectors.alpaca_bars'`.

- [ ] **Step 3: Implement**

`pipeline/src/advisor/collectors/alpaca_bars.py`:
```python
"""Daily OHLCV bars for US stocks from Alpaca's free market-data API (source 2)."""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import httpx

from advisor.collectors.base import Cadence, Category, RateLimiter, get_with_retries
from advisor.models import ET, AssetType, DailyBar

ALPACA_BARS_URL = "https://data.alpaca.markets/v2/stocks/bars"
SYMBOLS_PER_REQUEST = 200
PAGE_LIMIT = 10_000
SIP_DELAY = timedelta(minutes=16)  # free plan: SIP data must be at least 15 minutes old
LOOKBACK = timedelta(days=100)  # about 68 trading days, enough for the 60-day history filter


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _to_bar(symbol: str, raw: dict) -> DailyBar | None:
    try:
        return DailyBar(
            symbol=symbol,
            day=datetime.fromisoformat(raw["t"]).astimezone(ET).date(),
            open=raw["o"],
            high=raw["h"],
            low=raw["l"],
            close=raw["c"],
            volume=raw["v"],
            source="alpaca",
        )
    except (KeyError, ValueError):  # pydantic ValidationError is a ValueError
        return None


class AlpacaBars:
    name = "alpaca_bars"
    category = Category.PRICES
    core = True
    best_effort = False
    cadence = Cadence.PER_RUN
    asset_types = frozenset({AssetType.STOCK})
    record_type = DailyBar
    freshness = None

    def __init__(
        self,
        client: httpx.Client,
        key_id: str,
        secret_key: str,
        limiter: RateLimiter | None = None,
    ) -> None:
        self._client = client
        self._headers = {"APCA-API-KEY-ID": key_id, "APCA-API-SECRET-KEY": secret_key}
        self._limiter = limiter or RateLimiter(per_minute=180, burst=5)

    def fetch(self, symbols: Sequence[str], as_of: datetime) -> list[DailyBar]:
        unique = sorted(set(symbols))
        base_params = {
            "timeframe": "1Day",
            "start": _iso(as_of - LOOKBACK),
            "end": _iso(as_of - SIP_DELAY),
            "limit": PAGE_LIMIT,
            "adjustment": "all",
            "feed": "sip",
        }
        bars: list[DailyBar] = []
        for i in range(0, len(unique), SYMBOLS_PER_REQUEST):
            chunk = unique[i : i + SYMBOLS_PER_REQUEST]
            page_token: str | None = None
            while True:
                params = {**base_params, "symbols": ",".join(chunk)}
                if page_token:
                    params["page_token"] = page_token
                payload = get_with_retries(
                    self._client, ALPACA_BARS_URL, params=params, headers=self._headers,
                    limiter=self._limiter,
                ).json()
                for symbol, rows in (payload.get("bars") or {}).items():
                    bars.extend(b for b in (_to_bar(symbol, r) for r in rows) if b is not None)
                page_token = payload.get("next_page_token")
                if not page_token:
                    break
        return bars
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_alpaca_bars.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
uv run ruff check --fix .
git add src/advisor/collectors/alpaca_bars.py tests/unit/test_alpaca_bars.py
git commit -m "feat: add Alpaca daily bars collector with paging and chunking" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: yfinance daily-bars collector (source 3)

**Files:**
- Create: `pipeline/src/advisor/collectors/yfinance_bars.py`
- Test: `pipeline/tests/unit/test_yfinance_bars.py`

**Interfaces:**
- Consumes: `DailyBar`, `ET`
- Produces:
  - `YFinanceBars(download: Downloader | None = None)`: name `yfinance_bars`, not core, best-effort, per-run, `freshness=None`. `fetch(symbols, as_of)` returns bars with `source="yfinance"`, using our symbol format (`BRK.B`).
  - `Downloader = Callable[[list[str], date, date], pd.DataFrame]`, called with `(tickers, start, end)` where `end` is exclusive
  - `to_yahoo(symbol) -> str`
  - `parse_frame(frame, yahoo_to_symbol: dict[str, str]) -> list[DailyBar]`

- [ ] **Step 1: Write the failing test**

`pipeline/tests/unit/test_yfinance_bars.py`:
```python
from datetime import UTC, date, datetime

import pandas as pd

from advisor.collectors.yfinance_bars import YFinanceBars, parse_frame, to_yahoo

AS_OF = datetime(2026, 10, 14, 19, 15, tzinfo=UTC)
NAN = float("nan")
FIELDS = ["Open", "High", "Low", "Close", "Volume"]


def two_ticker_frame() -> pd.DataFrame:
    index = pd.DatetimeIndex([pd.Timestamp("2026-10-12"), pd.Timestamp("2026-10-13")])
    columns = pd.MultiIndex.from_product([["AAPL", "BRK-B"], FIELDS])
    values = [
        [10, 11, 9, 10.5, 1000, NAN, NAN, NAN, NAN, NAN],
        [10.5, 12, 10, 11.5, 2000, 400, 410, 395, 405, 3000],
    ]
    return pd.DataFrame(values, index=index, columns=columns)


def test_to_yahoo_converts_share_class_separator():
    assert to_yahoo("BRK.B") == "BRK-B"
    assert to_yahoo("AAPL") == "AAPL"


def test_fetch_round_trips_share_class_symbols_and_skips_empty_rows():
    calls = []

    def fake_download(tickers, start, end):
        calls.append((tickers, start, end))
        return two_ticker_frame()

    bars = YFinanceBars(download=fake_download).fetch(["BRK.B", "AAPL"], AS_OF)

    assert calls == [(["AAPL", "BRK-B"], date(2026, 7, 6), date(2026, 10, 15))]
    assert [(b.symbol, b.day, b.close, b.source) for b in bars] == [
        ("AAPL", date(2026, 10, 12), 10.5, "yfinance"),
        ("AAPL", date(2026, 10, 13), 11.5, "yfinance"),
        ("BRK.B", date(2026, 10, 13), 405.0, "yfinance"),
    ]


def test_parse_frame_accepts_single_level_columns_for_one_ticker():
    frame = pd.DataFrame(
        [[1.0, 1.2, 0.9, 1.1, 500]],
        index=pd.DatetimeIndex([pd.Timestamp("2026-10-13")]),
        columns=FIELDS,
    )
    bars = parse_frame(frame, {"AAPL": "AAPL"})
    assert [(b.symbol, b.close) for b in bars] == [("AAPL", 1.1)]


def test_parse_frame_handles_empty_frames():
    assert parse_frame(pd.DataFrame(), {"AAPL": "AAPL"}) == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_yfinance_bars.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'advisor.collectors.yfinance_bars'`.

- [ ] **Step 3: Implement**

`pipeline/src/advisor/collectors/yfinance_bars.py`:
```python
"""Daily bars from Yahoo Finance via yfinance (source 3): fallback and cross-check for Alpaca."""

from collections.abc import Callable, Sequence
from datetime import date, datetime, timedelta

import pandas as pd

from advisor.collectors.base import Cadence, Category
from advisor.models import ET, AssetType, DailyBar

Downloader = Callable[[list[str], date, date], pd.DataFrame]
SYMBOLS_PER_DOWNLOAD = 100
LOOKBACK = timedelta(days=100)


def to_yahoo(symbol: str) -> str:
    return symbol.replace(".", "-")


def _yahoo_download(tickers: list[str], start: date, end: date) -> pd.DataFrame:
    import yfinance as yf  # imported lazily: slow import, and tests inject a fake

    return yf.download(
        tickers=tickers,
        start=start.isoformat(),
        end=end.isoformat(),
        group_by="ticker",
        auto_adjust=True,
        threads=True,
        progress=False,
    )


def parse_frame(frame: pd.DataFrame | None, yahoo_to_symbol: dict[str, str]) -> list[DailyBar]:
    if frame is None or frame.empty:
        return []
    if not isinstance(frame.columns, pd.MultiIndex):
        (only,) = yahoo_to_symbol  # yfinance returns flat columns for a single ticker
        frame = pd.concat({only: frame}, axis=1)
    bars: list[DailyBar] = []
    for ticker in frame.columns.get_level_values(0).unique():
        symbol = yahoo_to_symbol.get(ticker)
        if symbol is None:
            continue
        for stamp, row in frame[ticker].dropna(subset=["Close"]).iterrows():
            try:
                bars.append(DailyBar(
                    symbol=symbol,
                    day=stamp.date(),
                    open=float(row["Open"]),
                    high=float(row["High"]),
                    low=float(row["Low"]),
                    close=float(row["Close"]),
                    volume=float(row["Volume"]),
                    source="yfinance",
                ))
            except ValueError:  # NaN or non-positive fields fail validation
                continue
    return bars


class YFinanceBars:
    name = "yfinance_bars"
    category = Category.PRICES
    core = False
    best_effort = True
    cadence = Cadence.PER_RUN
    asset_types = frozenset({AssetType.STOCK})
    record_type = DailyBar
    freshness = None

    def __init__(self, download: Downloader | None = None) -> None:
        self._download = download or _yahoo_download

    def fetch(self, symbols: Sequence[str], as_of: datetime) -> list[DailyBar]:
        unique = sorted(set(symbols))
        start = (as_of - LOOKBACK).astimezone(ET).date()
        end = as_of.astimezone(ET).date() + timedelta(days=1)
        bars: list[DailyBar] = []
        for i in range(0, len(unique), SYMBOLS_PER_DOWNLOAD):
            mapping = {to_yahoo(s): s for s in unique[i : i + SYMBOLS_PER_DOWNLOAD]}
            bars.extend(parse_frame(self._download(list(mapping), start, end), mapping))
        return bars
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_yfinance_bars.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
uv run ruff check --fix .
git add src/advisor/collectors/yfinance_bars.py tests/unit/test_yfinance_bars.py
git commit -m "feat: add yfinance daily bars collector as price fallback" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Price fetching with fallback and jump validation

**Files:**
- Create: `pipeline/src/advisor/prices.py`
- Test: `pipeline/tests/unit/test_prices.py`

**Interfaces:**
- Consumes: `CollectorResult`, `DailyBar`
- Produces:
  - `RunFn = Callable[[Sequence[str]], CollectorResult]`
  - `PriceFetch(bars: dict[str, list[DailyBar]], results: list[CollectorResult])`. Bars are sorted ascending by day, and symbols with no bars are absent.
  - `fetch_daily_bars(symbols, *, primary_run: RunFn, fallback_run: RunFn) -> PriceFetch`
  - `group_bars(records) -> dict[str, list[DailyBar]]`
  - `find_unconfirmed_jumps(bars, reference) -> set[date]`
  - constants `JUMP_LIMIT = 0.5`, `CONFIRM_TOLERANCE = 0.02`

- [ ] **Step 1: Write the failing test**

`pipeline/tests/unit/test_prices.py`:
```python
from datetime import date

from fakes import bar, history

from advisor.collectors.base import CollectorResult, CollectorStatus
from advisor.prices import fetch_daily_bars, find_unconfirmed_jumps


def runner(name, bars_by_symbol, calls, status=CollectorStatus.OK):
    def run(symbols):
        calls.append((name, list(symbols)))
        records = [b for s in symbols for b in bars_by_symbol.get(s, [])]
        return CollectorResult(name, status, records, 5)
    return run


def jumpy(symbol, source):
    return [
        bar(symbol, date(2026, 10, 12), 10.0, source=source),
        bar(symbol, date(2026, 10, 13), 16.0, source=source),  # +60%
    ]


def test_primary_covers_everything_so_fallback_is_not_called():
    calls = []
    result = fetch_daily_bars(
        ["AAA"],
        primary_run=runner("alpaca_bars", {"AAA": history("AAA", 3)}, calls),
        fallback_run=runner("yfinance_bars", {}, calls),
    )
    assert calls == [("alpaca_bars", ["AAA"])]
    assert len(result.bars["AAA"]) == 3
    assert [r.name for r in result.results] == ["alpaca_bars"]


def test_missing_symbols_come_from_fallback():
    calls = []
    result = fetch_daily_bars(
        ["AAA", "BBB"],
        primary_run=runner("alpaca_bars", {"AAA": history("AAA", 3)}, calls),
        fallback_run=runner("yfinance_bars", {"BBB": history("BBB", 2, source="yfinance")}, calls),
    )
    assert calls[1] == ("yfinance_bars", ["BBB"])
    assert [b.source for b in result.bars["BBB"]] == ["yfinance", "yfinance"]


def test_jump_confirmed_by_fallback_is_kept_and_unconfirmed_is_dropped():
    calls = []
    result = fetch_daily_bars(
        ["CONF", "LONE"],
        primary_run=runner(
            "alpaca_bars", {"CONF": jumpy("CONF", "alpaca"), "LONE": jumpy("LONE", "alpaca")}, calls
        ),
        fallback_run=runner("yfinance_bars", {"CONF": jumpy("CONF", "yfinance")}, calls),
    )
    assert calls[1] == ("yfinance_bars", ["CONF", "LONE"])
    assert [b.day for b in result.bars["CONF"]] == [date(2026, 10, 12), date(2026, 10, 13)]
    assert [b.day for b in result.bars["LONE"]] == [date(2026, 10, 12)]


def test_primary_failure_uses_fallback_for_all():
    calls = []
    result = fetch_daily_bars(
        ["AAA", "BBB"],
        primary_run=runner("alpaca_bars", {}, calls, status=CollectorStatus.FAILED),
        fallback_run=runner(
            "yfinance_bars",
            {"AAA": history("AAA", 2, source="yfinance"), "BBB": history("BBB", 2, source="yfinance")},
            calls,
        ),
    )
    assert sorted(result.bars) == ["AAA", "BBB"]
    assert [r.status for r in result.results] == [CollectorStatus.FAILED, CollectorStatus.OK]


def test_symbol_with_no_bars_anywhere_is_absent():
    result = fetch_daily_bars(
        ["NONE"],
        primary_run=runner("alpaca_bars", {}, []),
        fallback_run=runner("yfinance_bars", {}, []),
    )
    assert result.bars == {}


def test_find_unconfirmed_jumps_uses_two_percent_tolerance():
    bars = jumpy("X", "alpaca")
    near = [bar("X", date(2026, 10, 13), 16.3, source="yfinance")]  # within 2%
    far = [bar("X", date(2026, 10, 13), 17.0, source="yfinance")]   # 6% away
    assert find_unconfirmed_jumps(bars, near) == set()
    assert find_unconfirmed_jumps(bars, far) == {date(2026, 10, 13)}
    assert find_unconfirmed_jumps(bars, []) == {date(2026, 10, 13)}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_prices.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'advisor.prices'`.

- [ ] **Step 3: Implement**

`pipeline/src/advisor/prices.py`:
```python
"""Daily bars from the primary source, filled and cross-checked by the fallback source.

Sanity rule (spec §10): a close-to-close move above 50% is dropped unless the other source
reports the same close for that day within 2%.
"""

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from itertools import pairwise

from advisor.collectors.base import CollectorResult
from advisor.models import DailyBar

JUMP_LIMIT = 0.5
CONFIRM_TOLERANCE = 0.02

RunFn = Callable[[Sequence[str]], CollectorResult]


@dataclass(frozen=True)
class PriceFetch:
    bars: dict[str, list[DailyBar]]
    results: list[CollectorResult]


def group_bars(records: Iterable[DailyBar]) -> dict[str, list[DailyBar]]:
    by_symbol: dict[str, dict[date, DailyBar]] = {}
    for record in records:
        by_symbol.setdefault(record.symbol, {})[record.day] = record
    return {s: [days[d] for d in sorted(days)] for s, days in by_symbol.items()}


def _has_jump(bars: Sequence[DailyBar]) -> bool:
    return any(abs(cur.close / prev.close - 1) > JUMP_LIMIT for prev, cur in pairwise(bars))


def find_unconfirmed_jumps(bars: Sequence[DailyBar], reference: Sequence[DailyBar]) -> set[date]:
    ref_close = {b.day: b.close for b in reference}
    bad: set[date] = set()
    for prev, cur in pairwise(bars):
        if abs(cur.close / prev.close - 1) <= JUMP_LIMIT:
            continue
        other = ref_close.get(cur.day)
        if other is None or abs(other / cur.close - 1) > CONFIRM_TOLERANCE:
            bad.add(cur.day)
    return bad


def fetch_daily_bars(
    symbols: Sequence[str], *, primary_run: RunFn, fallback_run: RunFn
) -> PriceFetch:
    wanted = sorted(set(symbols))
    first = primary_run(wanted)
    results = [first]
    primary = group_bars(first.records)

    missing = [s for s in wanted if s not in primary]
    suspects = [s for s, bars in primary.items() if _has_jump(bars)]
    need = sorted(set(missing) | set(suspects))
    reference: dict[str, list[DailyBar]] = {}
    if need:
        second = fallback_run(need)
        results.append(second)
        reference = group_bars(second.records)

    bars: dict[str, list[DailyBar]] = {}
    for symbol in wanted:
        if symbol in primary:
            own, other = primary[symbol], reference.get(symbol, [])
        elif symbol in reference:
            own, other = reference[symbol], []
        else:
            continue
        bad = find_unconfirmed_jumps(own, other)
        kept = [b for b in own if b.day not in bad]
        if kept:
            bars[symbol] = kept
    return PriceFetch(bars=bars, results=results)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_prices.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
uv run ruff check --fix .
git add src/advisor/prices.py tests/unit/test_prices.py
git commit -m "feat: fetch daily bars with fallback and cross-source jump validation" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Screener hard filters

**Files:**
- Create: `pipeline/src/advisor/screener.py`
- Test: `pipeline/tests/unit/test_screener.py`

**Interfaces:**
- Consumes: `DailyBar`
- Produces:
  - `ScreenRow(symbol, last_close, adv20, history_days, last_day)` with `.passes() -> bool` and `.as_features() -> dict`
  - `price_stats(symbol: str, bars: Sequence[DailyBar]) -> ScreenRow` (`bars` must be non-empty and sorted ascending)
  - `hard_filter(bars_by_symbol: Mapping[str, Sequence[DailyBar]]) -> list[ScreenRow]` (only passing rows, sorted by symbol)
  - constants `MIN_PRICE = 1.0`, `MIN_DOLLAR_VOLUME = 1_000_000.0`, `ADV_WINDOW = 20`, `MIN_HISTORY_DAYS = 60`

- [ ] **Step 1: Write the failing test**

`pipeline/tests/unit/test_screener.py`:
```python
from datetime import date

from fakes import history

from advisor.screener import hard_filter, price_stats


def test_price_stats_uses_last_twenty_bars_for_dollar_volume():
    bars = history("X", 50, close=10.0, volume=1_000_000) + history(
        "X", 20, close=10.0, volume=1_000, start=date(2026, 8, 1)
    )
    row = price_stats("X", bars)
    assert row.adv20 == 10_000.0
    assert row.history_days == 70
    assert row.last_close == 10.0
    assert row.last_day == date(2026, 8, 20)


def test_hard_filter_applies_price_volume_and_history_thresholds():
    universe = {
        "PASS": history("PASS", 60, close=10.0, volume=200_000),     # $2M ADV, 60 days
        "PENNY": history("PENNY", 60, close=0.9, volume=50_000_000),  # price < $1
        "THIN": history("THIN", 60, close=10.0, volume=99_999.9),     # ADV just under $1M
        "YOUNG": history("YOUNG", 59, close=10.0, volume=200_000),    # 59 days of history
        "EMPTY": [],
    }
    assert [row.symbol for row in hard_filter(universe)] == ["PASS"]


def test_as_features_is_json_friendly():
    row = price_stats("X", history("X", 60))
    assert row.as_features() == {
        "last_close": 10.0,
        "adv20": 2_000_000.0,
        "history_days": 60,
        "last_day": "2026-07-30",
    }
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_screener.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'advisor.screener'`.

- [ ] **Step 3: Implement**

`pipeline/src/advisor/screener.py`:
```python
"""Hard screener filters (spec §4.3 stage 3): price, dollar volume, and history length.

Plan 3 adds the screener model that ranks survivors down to the ~300-symbol shortlist.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from advisor.models import DailyBar

MIN_PRICE = 1.0
MIN_DOLLAR_VOLUME = 1_000_000.0
ADV_WINDOW = 20
MIN_HISTORY_DAYS = 60


@dataclass(frozen=True)
class ScreenRow:
    symbol: str
    last_close: float
    adv20: float
    history_days: int
    last_day: date

    def passes(self) -> bool:
        return (
            self.last_close >= MIN_PRICE
            and self.adv20 >= MIN_DOLLAR_VOLUME
            and self.history_days >= MIN_HISTORY_DAYS
        )

    def as_features(self) -> dict[str, float | int | str]:
        return {
            "last_close": self.last_close,
            "adv20": self.adv20,
            "history_days": self.history_days,
            "last_day": self.last_day.isoformat(),
        }


def price_stats(symbol: str, bars: Sequence[DailyBar]) -> ScreenRow:
    recent = bars[-ADV_WINDOW:]
    adv = sum(b.close * b.volume for b in recent) / len(recent)
    return ScreenRow(symbol, bars[-1].close, adv, len(bars), bars[-1].day)


def hard_filter(bars_by_symbol: Mapping[str, Sequence[DailyBar]]) -> list[ScreenRow]:
    rows = (price_stats(s, bars) for s, bars in bars_by_symbol.items() if bars)
    return sorted((row for row in rows if row.passes()), key=lambda row: row.symbol)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_screener.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
uv run ruff check --fix .
git add src/advisor/screener.py tests/unit/test_screener.py
git commit -m "feat: add screener hard filters for price, dollar volume, and history" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: Collector registry, run orchestrator and CLI

**Files:**
- Create: `pipeline/src/advisor/collectors/registry.py`, `pipeline/src/advisor/run.py`
- Test: `pipeline/tests/unit/test_registry.py`, `pipeline/tests/unit/test_run_cli.py`, `pipeline/tests/integration/test_run.py`

**Interfaces:**
- Consumes: everything from Tasks 1–10
- Produces:
  - `advisor.collectors.registry.build_registry(settings: Settings, client: httpx.Client) -> dict[str, Collector]` with keys `nasdaq_symbols`, `alpaca_bars`, `yfinance_bars`
  - `advisor.run.RunDeps(conn, cache, collectors)`
  - `advisor.run.RunOutcome(run_id, status, summary)`
  - `advisor.run.execute_run(deps, kind, now_utc, *, min_universe=MIN_UNIVERSE) -> RunOutcome`
  - `advisor.run.decide_status(...)`
  - `advisor.run.main(argv: list[str] | None = None) -> int` (CLI: `python -m advisor.run [--force-kind KIND] [--now ISO]`)
  - Run summary keys: `universe`, `priced`, `passed_filters`, `priority`, `priority_unpriced`. On an exception the summary is `error` instead.

- [ ] **Step 1: Write the failing tests**

`pipeline/tests/unit/test_registry.py`:
```python
from pathlib import Path

import httpx

from advisor.collectors.registry import build_registry
from advisor.config import Settings


def test_registry_lists_foundation_collectors_with_core_flags():
    settings = Settings("postgresql://x", "key", "secret", Path(".cache"))
    with httpx.Client() as client:
        registry = build_registry(settings, client)
    assert sorted(registry) == ["alpaca_bars", "nasdaq_symbols", "yfinance_bars"]
    assert {name: c.core for name, c in registry.items()} == {
        "alpaca_bars": True,
        "nasdaq_symbols": True,
        "yfinance_bars": False,
    }
    assert all(registry[name].name == name for name in registry)
```

`pipeline/tests/unit/test_run_cli.py`:
```python
from advisor.run import main


def test_main_exits_quietly_outside_run_windows(monkeypatch, capsys):
    for name in ("DATABASE_URL", "ALPACA_KEY_ID", "ALPACA_SECRET_KEY"):
        monkeypatch.delenv(name, raising=False)
    assert main(["--now", "2026-10-17T12:15:00+00:00"]) == 0  # Saturday
    assert "nothing to do" in capsys.readouterr().out
```

`pipeline/tests/integration/test_run.py`:
```python
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fakes import FakeCollector, history, info

from advisor.collectors.base import Cadence
from advisor.collectors.cache import DiskCache
from advisor.models import RunKind, RunStatus, SymbolInfo
from advisor.run import RunDeps, execute_run

NOW = datetime(2026, 10, 14, 12, 15, tzinfo=UTC)
UNIVERSE = ["AAA", "BBB", "CCC"]


def make_deps(db, tmp_path, *, universe=UNIVERSE, alpaca=None, universe_records=None):
    collectors = {
        "nasdaq_symbols": FakeCollector(
            "nasdaq_symbols",
            records_for=universe_records or (lambda _: [info(s) for s in universe]),
            record_type=SymbolInfo,
            cadence=Cadence.DAILY,
            freshness=timedelta(days=3),
        ),
        "alpaca_bars": alpaca or FakeCollector(
            "alpaca_bars", records_for=lambda syms: [b for s in syms for b in history(s, 70)]
        ),
        "yfinance_bars": FakeCollector(
            "yfinance_bars",
            core=False,
            best_effort=True,
            records_for=lambda syms: [b for s in syms for b in history(s, 70, source="yfinance")],
        ),
    }
    return RunDeps(db, DiskCache(tmp_path), collectors)


def run_row(db, run_id):
    return db.execute("select * from runs where id = %s", (run_id,)).fetchone()


def health(db, run_id):
    rows = db.execute(
        "select source, status from source_health where run_id = %s order by source", (run_id,)
    ).fetchall()
    return [(r["source"], r["status"]) for r in rows]


def test_successful_run_is_published_with_summary(db, tmp_path):
    deps = make_deps(db, tmp_path)
    outcome = execute_run(deps, RunKind.PRE_OPEN, NOW, min_universe=3)

    assert outcome.status is RunStatus.SUCCESS
    row = run_row(db, outcome.run_id)
    assert row["published"] is True
    assert (row["sources_ok"], row["sources_total"]) == (3, 3)
    assert row["summary"] == {
        "universe": 3, "priced": 3, "passed_filters": 3, "priority": 0, "priority_unpriced": [],
    }
    assert deps.collectors["yfinance_bars"].calls == []
    assert health(db, outcome.run_id) == [("alpaca_bars", "ok"), ("nasdaq_symbols", "ok")]
    assert db.execute("select count(*) as n from symbols where active").fetchone()["n"] == 3


def test_holding_outside_universe_is_priced_and_gets_features(db, tmp_path):
    db.execute(
        "insert into lots (symbol, asset_type, qty, price, bought_at)"
        " values ('OTCX', 'stock', 10, 5, '2026-09-01')"
    )
    db.execute("insert into watchlist (symbol, asset_type) values ('BTC', 'crypto')")
    outcome = execute_run(make_deps(db, tmp_path), RunKind.PRE_OPEN, NOW, min_universe=3)

    features = db.execute(
        "select symbol, features from features_live where run_id = %s", (outcome.run_id,)
    ).fetchall()
    assert [f["symbol"] for f in features] == ["OTCX"]
    assert features[0]["features"]["last_close"] == 10.0
    assert outcome.summary["priority"] == 1
    assert outcome.summary["priced"] == 4


def test_primary_price_outage_falls_back_and_marks_run_degraded(db, tmp_path):
    alpaca = FakeCollector("alpaca_bars", error=httpx.ConnectError("down"))
    outcome = execute_run(
        make_deps(db, tmp_path, alpaca=alpaca), RunKind.PRE_CLOSE, NOW, min_universe=3
    )

    assert outcome.status is RunStatus.DEGRADED
    row = run_row(db, outcome.run_id)
    assert row["published"] is True
    assert row["sources_ok"] == 2
    assert health(db, outcome.run_id) == [
        ("alpaca_bars", "failed"), ("nasdaq_symbols", "ok"), ("yfinance_bars", "ok"),
    ]
    assert outcome.summary["priced"] == 3


def test_truncated_universe_fails_the_run_and_stays_unpublished(db, tmp_path):
    outcome = execute_run(make_deps(db, tmp_path), RunKind.PRE_OPEN, NOW, min_universe=1000)
    assert outcome.status is RunStatus.FAILED
    assert run_row(db, outcome.run_id)["published"] is False


def test_unexpected_error_marks_run_failed_and_propagates(db, tmp_path):
    deps = make_deps(db, tmp_path, universe_records=lambda _: [object()])
    with pytest.raises(AttributeError):
        execute_run(deps, RunKind.PRE_OPEN, NOW, min_universe=1)
    row = db.execute("select * from runs").fetchone()
    assert row["status"] == "failed"
    assert row["published"] is False
    assert row["summary"]["error"].startswith("AttributeError")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:54329/advisor_test uv run pytest tests/unit/test_registry.py tests/unit/test_run_cli.py tests/integration/test_run.py -v`
Expected: FAIL with `ModuleNotFoundError` for `advisor.collectors.registry` and `advisor.run`.

- [ ] **Step 3: Implement the registry**

`pipeline/src/advisor/collectors/registry.py`:
```python
"""Every collector the pipeline runs, keyed by name. Plan 2 adds the remaining sources here."""

import httpx

from advisor.collectors.alpaca_bars import AlpacaBars
from advisor.collectors.base import Collector
from advisor.collectors.nasdaq_symbols import NasdaqSymbols
from advisor.collectors.yfinance_bars import YFinanceBars
from advisor.config import Settings


def build_registry(settings: Settings, client: httpx.Client) -> dict[str, Collector]:
    collectors: list[Collector] = [
        NasdaqSymbols(client),
        AlpacaBars(client, settings.alpaca_key_id, settings.alpaca_secret_key),
        YFinanceBars(),
    ]
    return {collector.name: collector for collector in collectors}
```

- [ ] **Step 4: Implement the orchestrator and CLI**

`pipeline/src/advisor/run.py`:
```python
"""Run orchestrator: one pre-open, pre-close, or early-close pass of the pipeline.

Usage: python -m advisor.run [--force-kind pre_open|pre_close|early_close] [--now ISO-8601]
"""

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

import psycopg

from advisor import screener
from advisor.collectors.base import Collector, CollectorResult, CollectorStatus, make_client
from advisor.collectors.cache import DiskCache
from advisor.collectors.registry import build_registry
from advisor.collectors.runner import next_failures, run_collector
from advisor.config import Settings
from advisor.models import ET, AssetRef, AssetType, RunKind, RunStatus, SymbolInfo
from advisor.prices import fetch_daily_bars
from advisor.schedule import resolve_run_kind
from advisor.store import repo
from advisor.store.db import connect

MIN_UNIVERSE = 1000  # fewer listed stocks than this means the symbol files were truncated
MIN_PRICED_FRACTION = 0.5
UNHEALTHY = frozenset({CollectorStatus.FAILED, CollectorStatus.STALE, CollectorStatus.SKIPPED})


@dataclass(frozen=True)
class RunDeps:
    conn: psycopg.Connection
    cache: DiskCache
    collectors: Mapping[str, Collector]


@dataclass(frozen=True)
class RunOutcome:
    run_id: int
    status: RunStatus
    summary: dict


def decide_status(
    results: Sequence[CollectorResult],
    collectors: Mapping[str, Collector],
    *,
    universe_ok: bool,
    prices_ok: bool,
) -> RunStatus:
    if not (universe_ok and prices_ok):
        return RunStatus.FAILED
    if any(collectors[r.name].core and r.status is not CollectorStatus.OK for r in results):
        return RunStatus.DEGRADED
    return RunStatus.SUCCESS


def count_healthy(results: Sequence[CollectorResult], collectors: Mapping[str, Collector]) -> int:
    unhealthy = {r.name for r in results if r.status in UNHEALTHY}
    return len(collectors) - len(unhealthy)


def execute_run(
    deps: RunDeps, kind: RunKind, now_utc: datetime, *, min_universe: int = MIN_UNIVERSE
) -> RunOutcome:
    conn = deps.conn
    run_id = repo.create_run(conn, kind, now_utc.astimezone(ET).date())
    results: list[CollectorResult] = []

    def run(name: str, symbols: Sequence[str]) -> CollectorResult:
        state = repo.load_source_state(conn, name)
        result = run_collector(
            deps.collectors[name], symbols, now_utc, cache=deps.cache, state=state
        )
        repo.record_source_health(conn, run_id, result, next_failures(state, result), now_utc)
        results.append(result)
        return result

    try:
        priority_refs = repo.load_held_symbols(conn) | repo.load_watchlist(conn)
        priority = {ref.symbol for ref in priority_refs if ref.asset_type is AssetType.STOCK}

        universe: list[SymbolInfo] = list(run("nasdaq_symbols", []).records)
        if universe:
            repo.upsert_symbols(conn, universe)
        symbols = sorted({record.symbol for record in universe} | priority)

        prices = fetch_daily_bars(
            symbols,
            primary_run=lambda s: run("alpaca_bars", s),
            fallback_run=lambda s: run("yfinance_bars", s),
        )

        # Holdings and watchlist first, so their data is saved before anything else can fail.
        priority_rows = [
            screener.price_stats(s, prices.bars[s]) for s in sorted(priority) if s in prices.bars
        ]
        repo.write_features_live(
            conn,
            run_id,
            [(AssetRef(r.symbol, AssetType.STOCK), r.as_features()) for r in priority_rows],
            now_utc,
        )

        passed = screener.hard_filter(prices.bars)
        summary = {
            "universe": len(universe),
            "priced": len(prices.bars),
            "passed_filters": len(passed),
            "priority": len(priority),
            "priority_unpriced": sorted(priority - prices.bars.keys()),
        }
        status = decide_status(
            results,
            deps.collectors,
            universe_ok=len(universe) >= min_universe,
            prices_ok=bool(symbols) and len(prices.bars) >= MIN_PRICED_FRACTION * len(symbols),
        )
    except Exception as exc:
        repo.finish_run(
            conn, run_id, RunStatus.FAILED,
            sources_ok=count_healthy(results, deps.collectors),
            sources_total=len(deps.collectors),
            summary={"error": f"{type(exc).__name__}: {exc}"[:500]},
        )
        raise

    repo.finish_run(
        conn, run_id, status,
        sources_ok=count_healthy(results, deps.collectors),
        sources_total=len(deps.collectors),
        summary=summary,
    )
    return RunOutcome(run_id, status, summary)


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="advisor.run")
    parser.add_argument("--force-kind", choices=[kind.value for kind in RunKind])
    parser.add_argument("--now", help="ISO-8601 timestamp to use instead of the current time")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    now = datetime.fromisoformat(args.now) if args.now else datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)

    kind = RunKind(args.force_kind) if args.force_kind else resolve_run_kind(now)
    if kind is None:
        print(f"{now.isoformat()}: outside every run window or market closed; nothing to do.")
        return 0

    settings = Settings.from_env()
    with connect(settings.database_url) as conn:
        if not args.force_kind and repo.has_published_run(conn, kind, now.astimezone(ET).date()):
            print(f"{kind.value} already published today; nothing to do.")
            return 0
        with make_client() as client:
            deps = RunDeps(conn, DiskCache(settings.cache_dir), build_registry(settings, client))
            outcome = execute_run(deps, kind, now)

    print(json.dumps({"run_id": outcome.run_id, "status": outcome.status.value, **outcome.summary}))
    return 1 if outcome.status is RunStatus.FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:54329/advisor_test uv run pytest tests/unit/test_registry.py tests/unit/test_run_cli.py tests/integration/test_run.py -v`
Expected: 7 passed.

- [ ] **Step 6: Run the full suite**

Run: `TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:54329/advisor_test uv run pytest -q`
Expected: 73 passed, 0 skipped.

- [ ] **Step 7: Commit**

```bash
uv run ruff check --fix .
git add src/advisor/collectors/registry.py src/advisor/run.py tests/unit/test_registry.py tests/unit/test_run_cli.py tests/integration/test_run.py
git commit -m "feat: add run orchestrator with holdings-first features and atomic publish" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: CI and scheduled-run workflows, plus README

**Files:**
- Create: `.github/workflows/ci.yml`, `.github/workflows/run.yml`, `README.md` (all at the `stock-advisor/` root)

**Interfaces:**
- Consumes:
  - `python -m advisor.run` (Task 11)
  - environment variables `DATABASE_URL`, `ALPACA_KEY_ID`, `ALPACA_SECRET_KEY`, `ADVISOR_CACHE_DIR`, `TEST_DATABASE_URL`
- Produces: GitHub secrets contract `DATABASE_URL`, `ALPACA_KEY_ID`, `ALPACA_SECRET_KEY`, and the cache key prefix `advisor-cache-`

- [ ] **Step 1: Write the CI workflow**

`.github/workflows/ci.yml`:
```yaml
name: ci

on:
  push:
  pull_request:

jobs:
  pipeline:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_PASSWORD: postgres
          POSTGRES_DB: advisor_test
        ports: ["5432:5432"]
        options: >-
          --health-cmd "pg_isready -U postgres"
          --health-interval 5s --health-timeout 5s --health-retries 10
    env:
      TEST_DATABASE_URL: postgresql://postgres:postgres@localhost:5432/advisor_test
    defaults:
      run:
        working-directory: pipeline
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
      - run: uv sync --locked
      - run: uv run ruff check .
      - run: uv run pytest -q
```

- [ ] **Step 2: Write the scheduled-run workflow**

`.github/workflows/run.yml`:
```yaml
name: run

# Each run has an EDT and an EST cron (GitHub cron is UTC). advisor.run checks the NYSE
# calendar and the current ET time, then does nothing unless this is the right slot.
on:
  schedule:
    - cron: "15 12 * * 1-5"  # pre-open, EDT
    - cron: "15 13 * * 1-5"  # pre-open, EST
    - cron: "15 16 * * 1-5"  # early-close days, EDT
    - cron: "15 17 * * 1-5"  # early-close days, EST
    - cron: "15 19 * * 1-5"  # pre-close, EDT
    - cron: "15 20 * * 1-5"  # pre-close, EST
  workflow_dispatch:
    inputs:
      kind:
        description: Run kind to force (ignores the schedule guard)
        type: choice
        options: [pre_open, pre_close, early_close]
        default: pre_open

concurrency:
  group: pipeline-run
  cancel-in-progress: false

jobs:
  run:
    runs-on: ubuntu-latest
    timeout-minutes: 40
    defaults:
      run:
        working-directory: pipeline
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
      - run: uv sync --locked --no-dev
      - uses: actions/cache@v4
        with:
          path: pipeline/.cache
          key: advisor-cache-${{ github.run_id }}
          restore-keys: advisor-cache-
      - name: Run pipeline
        env:
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
          ALPACA_KEY_ID: ${{ secrets.ALPACA_KEY_ID }}
          ALPACA_SECRET_KEY: ${{ secrets.ALPACA_SECRET_KEY }}
          ADVISOR_CACHE_DIR: .cache
          FORCE_KIND: ${{ inputs.kind }}
        run: |
          if [ "${{ github.event_name }}" = "workflow_dispatch" ]; then
            uv run python -m advisor.run --force-kind "$FORCE_KIND"
          else
            uv run python -m advisor.run
          fi
```

- [ ] **Step 3: Write the README**

`README.md`:
````markdown
# Stock Advisor

Personal decision-support tool: twice each trading day it gathers data from free sources,
forecasts likely ranges for US stocks and watchlist crypto, and suggests buys, hold times, and
risk levels — and grades every suggestion against reality. **Not financial advice.**

Design: `docs/superpowers/specs/2026-10-09-stock-advisor-design.md`
Plans: `docs/superpowers/plans/`

## Layout

- `pipeline/` — Python 3.12 data pipeline (uv)
- `supabase/migrations/` — Postgres schema and row-level security
- `.github/workflows/` — `ci.yml` (tests on push), `run.yml` (scheduled pipeline runs)

## Local development

```bash
# one-time
docker run -d --name advisor-pg -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=advisor_test \
  -p 54329:5432 postgres:16
cd pipeline && uv sync

# every session
docker start advisor-pg
export TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:54329/advisor_test
uv run ruff check . && uv run pytest -q
```

## Deployment (free tiers)

1. **Supabase**: create a project. In the SQL editor, run `supabase/migrations/0001_schema.sql`
   and then `0002_rls.sql`.
2. **Auth**: under Authentication → Sign In / Providers → Email, turn off "Allow new users to sign
   up". Add your user under Authentication → Users, then run:
   `insert into app_config (id, owner_id) values (1, '<your user uuid>');`
3. **Connection string**: under Connect → **Session pooler**, copy the URI (GitHub runners need
   the IPv4 pooler) and put in your database password.
4. **Alpaca**: create a free account and generate API keys (paper-trading keys work for market
   data).
5. **GitHub** (private repo): Settings → Secrets and variables → Actions. Add `DATABASE_URL`,
   `ALPACA_KEY_ID`, `ALPACA_SECRET_KEY`.
6. Actions → `run` → Run workflow → `pre_open` to test end to end.

## Manual run

```bash
cd pipeline
DATABASE_URL=... ALPACA_KEY_ID=... ALPACA_SECRET_KEY=... uv run python -m advisor.run --force-kind pre_open
```
````

- [ ] **Step 4: Verify that everything is still green**

Run: `uv run ruff check . && TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:54329/advisor_test uv run pytest -q`
Expected: no lint errors, 73 passed.

- [ ] **Step 5: Commit**

```bash
git add ../.github ../README.md
git commit -m "ci: add test and scheduled pipeline workflows with setup README" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 13: Deploy and first live run (needs the owner)

This task creates external accounts and a GitHub repository. **Stop and get the owner's go-ahead before Step 4.** The owner does Steps 1–3 and 5 themselves, because they involve their own credentials. Never ask for passwords or keys in chat. The owner pastes them straight into Supabase or GitHub.

**Files:** none (configuration only)

- [ ] **Step 1 (owner): Supabase project.** Follow README steps 1–3. Then confirm in the Supabase table editor that all 15 tables exist with RLS enabled.

- [ ] **Step 2 (owner): Alpaca keys.** Follow README step 4.

- [ ] **Step 3 (owner, optional): local smoke test.** Set the three environment variables in a shell and run:
  ```bash
  cd pipeline && uv run python -m advisor.run --force-kind pre_open
  ```
  Expected: a JSON line containing `"status": "success"` (or `"degraded"`), `"universe"` in the thousands, `"priced"` close to `"universe"`, and `"passed_filters"` in the low thousands.

- [ ] **Step 4 (with the owner's go-ahead): create the private GitHub repo and push.** Use the GitHub web UI, or the GitHub MCP tool if it's authorized. Make the repo **private** and name it `stock-advisor`. Then run:
  ```bash
  cd stock-advisor
  git remote add origin https://github.com/<owner>/stock-advisor.git
  git push -u origin main
  ```
  Expected: the `ci` workflow runs on the push and passes.

- [ ] **Step 5 (owner): GitHub secrets.** Follow README step 5.

- [ ] **Step 6: Manual dispatch.** Go to Actions → `run` → Run workflow → `pre_open`.
  Expected:
  - The job passes, and the log ends with the JSON summary.
  - In Supabase, `runs` has one row with `published = true`.
  - `source_health` has `ok` rows for `nasdaq_symbols` and `alpaca_bars`.

- [ ] **Step 7: Confirm the schedule guard.** On the next weekday, open Actions:
  - Exactly one `pre_open` and one `pre_close` run did work.
  - The other crons logged "nothing to do".
  - No run took longer than 15 minutes.
