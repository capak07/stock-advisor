# Stock Advisor — Plan 2a: Collector Stage Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn Plan 1's three-source pipeline into a collector stage that 50 sources can plug into safely:
- holdings-first two-phase price fetch;
- partial results;
- per-symbol caching;
- one health row per source;
- a concurrent enrichment stage over a shortlist;
- a daily source health check;
- tracked migrations;
- a least-privilege database role for the pipeline.

**Architecture:**
- **Collector protocol.** Collectors keep returning records or raising, with two additions:
  - they can raise `PartialFetch` to hand back what they got;
  - each declares a `scope` (universe, per-symbol or market-wide) and `canary` symbols for the health check.
- **`SourceTracker`.** Runs collectors for one pipeline run and merges repeated calls into one result per source, so the orchestrator writes exactly one `source_health` row per source.
- **Orchestrator flow:**
  1. prices holdings and the watchlist first and saves their features;
  2. prices the rest of the market;
  3. builds a shortlist (priority symbols first);
  4. runs every enrichment collector concurrently. In this plan the enrichment stage is exercised with fakes; Plans 2b–2d register the real sources.

**Tech Stack:** Python 3.12, uv, httpx, pydantic v2, psycopg 3, pandas-market-calendars, pytest, ruff, Postgres 16 (Docker), Supabase, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-10-09-stock-advisor-design.md`. Read §3 (rules 1–5), §4.1, §4.3 stages 2–4, §7.2, §10 and §11. Plan 1 (`docs/superpowers/plans/2026-10-09-plan-1-foundation.md`) built everything this plan modifies.

## Roadmap: Plan 2 is split into four sub-plans

| Sub-plan | Delivers |
|---|---|
| **2a. Collector stage** (this plan) | Protocol v2, tracker, holdings-first fetch, enrichment stage, health check, migration runner, pipeline DB role |
| 2b. Fundamentals and filings | SEC (XBRL, 8-K, Form 4, 13F, 13D/G), FINRA (short interest, Reg SHO), FMP, yfinance analyst data, Finnhub recommendation trends and earnings (11 sources) |
| 2c. Macro, options, crypto, catalysts | FRED, FOMC RSS, Fear & Greed (2), options (2), Stooq, CoinGecko, Coinbase, Kraken, DefiLlama, blockchain.com, Etherscan, openFDA, ClinicalTrials.gov, USAspending, House Clerk (17 sources) |
| 2d. News and social | 17 news feeds, 5 social sources, de-duplication, ticker mapping, FinBERT sentiment, `news_items` |

## Global Constraints

- Python `>=3.12,<3.13`, managed by uv; `uv.lock` committed. Running cost is $0/month, free tiers only.
- Market time zone is `America/New_York` (`advisor.models.ET`); timestamps are `timestamptz`.
- The pipeline writes. The dashboard reads, and writes only to `watchlist`, `lots` and `sells`.
- **Row-level security:** every table has RLS enabled and an `owner_read` policy. From this plan on, every table also needs a policy for `pipeline_rw`. Tests enforce both.
- **Migrations are append-only from this plan on.** Never edit `0001_schema.sql`, `0002_rls.sql` or any later file once it may have been applied; add a new numbered file. Migrations run only through `python -m advisor.store.migrate` with `ADMIN_DATABASE_URL`, which is never a GitHub secret.
- **Least privilege at runtime:** the pipeline connects as a login role that is a member of `pipeline_rw`. That role has data read/write, no DDL, read-only access to `lots`, `sells`, `watchlist` and `app_config`, and no access to `schema_migrations`.
- **Collectors:**
  - Each source is one module in `pipeline/src/advisor/collectors/` with a registry entry.
  - `fetch` returns validated records or raises. It raises `PartialFetch(records, error)` when some requests failed.
  - Records of `Scope.SYMBOLS` collectors have a `symbol` field.
- **Holdings first** (spec §3 rule 5, §7.2): holdings and the watchlist are priced and saved before the rest of the market, and they come first in every collector's symbol list.
- **Sanity rules:** price > 0. A >50% move is dropped unless confirmed; `prices.py` already implements this, so leave it unchanged. Price data older than one session behind the expected session counts as missing (Plan 1 F1).
- Failed runs are never published.
- Secrets come only from the environment or GitHub secrets.
- **Tests run in the Linux container:** `scripts/in-docker.sh uv run pytest ...`. Windows Application Control blocks psycopg's DLLs on the dev host. Lint runs on the host: `uv run ruff check --fix .` before every commit.
- All commands run from `stock-advisor/pipeline/` unless a step says otherwise.
- Every commit message ends with a `Co-Authored-By:` trailer naming the model that actually wrote the commit.

## Review Focus

1. **A symbol Alpaca rejects** (for example one the owner typed oddly) must cost only its own 200-symbol request. Other chunks' bars are kept, the run is degraded rather than failed, and the missing symbols are priced by yfinance. Tested in Task 4 and Task 7.
2. **A run killed by the 40-minute job timeout** leaves a `running` row. The next run must mark it failed ("abandoned"). Tested in Task 2 and Task 7.
3. **Running migrations on an up-to-date or hand-migrated database** must apply nothing (or baseline). It must never re-run DDL or half-apply a failing file. Tested in Task 1.
4. **The pipeline role** must be unable to change holdings, the watchlist, the owner config or the schema. Tested in Task 2.
5. **A source that fails in only one phase** (holdings phase OK, market phase failed) must report a single `partial` health row, not two rows or a hidden failure. Tested in Task 5 and Task 7.

---

## File Structure

```
supabase/migrations/0003_collector_stage.sql   NEW  partial status, health-check rows, pipeline_rw role + policies
pipeline/src/advisor/
  store/migrate.py        NEW  tracked migration runner + CLI
  store/db.py             MOD  drop apply_migrations (replaced by migrate)
  store/repo.py           MOD  record_source_health(context), load_source_states, sweep_abandoned_runs
  collectors/base.py      MOD  Scope, CollectorStatus.PARTIAL, PartialFetch, protocol attrs, Retry-After
  collectors/runner.py    MOD  per-scope cache keys, never cache empty, PartialFetch handling
  collectors/tracker.py   NEW  SourceTracker, merge_results
  collectors/alpaca_bars.py     MOD  chunk isolation → PartialFetch
  collectors/nasdaq_symbols.py  MOD  scope/canary attrs
  collectors/yfinance_bars.py   MOD  scope/canary attrs
  enrich.py               NEW  shortlist, EnrichTargets, symbols_for, run_enrichment
  run.py                  MOD  two-phase holdings-first flow, tracker, enrichment, sweep
  health.py               NEW  daily canary check CLI
pipeline/tests/
  conftest.py             MOD  use migrate()
  fakes.py                MOD  FakeCollector scope/canary, FRESH_START, fake_price_collectors
  unit/test_runner.py, unit/test_base.py, unit/test_alpaca_bars.py, unit/test_registry.py   MOD
  unit/test_tracker.py, unit/test_enrich.py, unit/test_health.py, unit/test_migrate_cli.py  NEW
  integration/test_migrate.py, integration/test_run_cli_db.py, integration/test_health_cli.py  NEW
  integration/test_schema.py, integration/test_repo.py, integration/test_run.py  MOD
pipeline/scripts/in-docker.sh   MOD  forward ADMIN_DATABASE_URL
.github/workflows/run.yml, ci.yml MOD; health.yml NEW
README.md                        MOD
```

---

### Task 1: Tracked migration runner

**Files:**
- Create: `pipeline/src/advisor/store/migrate.py`
- Modify: `pipeline/src/advisor/store/db.py` (remove `apply_migrations`), `pipeline/tests/conftest.py` (use `migrate`)
- Test: `pipeline/tests/integration/test_migrate.py`, `pipeline/tests/unit/test_migrate_cli.py`

**Interfaces:**
- Consumes: `advisor.store.db.MIGRATIONS_DIR`, `advisor.store.db.connect`
- Produces:
  - `advisor.store.migrate.migrate(conn, directory: Path = MIGRATIONS_DIR, *, baseline: str | None = None) -> list[str]`, which returns the names it executed
  - `applied_migrations(conn) -> set[str]`
  - `main(argv: list[str] | None = None) -> int`
  - table `public.schema_migrations(name text primary key, applied_at timestamptz)`, with RLS enabled and no policies

- [ ] **Step 1: Write the failing tests**

`pipeline/tests/integration/test_migrate.py`:
```python
from pathlib import Path

import psycopg
import pytest

from advisor.store.db import MIGRATIONS_DIR
from advisor.store.migrate import migrate


def recorded(db) -> list[str]:
    return [r["name"] for r in db.execute("select name from schema_migrations order by name")]


def write(directory: Path, name: str, sql: str) -> None:
    (directory / name).write_text(sql, encoding="utf-8")


def exists(db, table: str) -> bool:
    return db.execute("select to_regclass(%s) is not null as ok", (f"public.{table}",)).fetchone()["ok"]


def test_db_fixture_records_every_migration(db):
    assert recorded(db) == sorted(p.name for p in MIGRATIONS_DIR.glob("*.sql"))


def test_migrate_is_a_no_op_when_up_to_date(db):
    assert migrate(db) == []


def test_new_migration_is_applied_once(db, tmp_path):
    write(tmp_path, "0099_extra.sql",
          "create table extra_t (i int); alter table extra_t enable row level security;")
    assert migrate(db, tmp_path) == ["0099_extra.sql"]
    assert migrate(db, tmp_path) == []
    assert exists(db, "extra_t")


def test_failed_migration_is_rolled_back_and_not_recorded(db, tmp_path):
    write(tmp_path, "0098_bad.sql", "create table half_done (i int); select * from missing_table;")
    with pytest.raises(psycopg.errors.UndefinedTable):
        migrate(db, tmp_path)
    assert not exists(db, "half_done")
    assert "0098_bad.sql" not in recorded(db)


def test_baseline_records_older_files_without_running_them(db, tmp_path):
    write(tmp_path, "0001_a.sql", "create table should_not_exist (i int);")
    write(tmp_path, "0002_b.sql",
          "create table b_t (i int); alter table b_t enable row level security;")
    assert migrate(db, tmp_path, baseline="0001_a.sql") == ["0002_b.sql"]
    assert not exists(db, "should_not_exist")
    assert {"0001_a.sql", "0002_b.sql"} <= set(recorded(db))


def test_unknown_baseline_is_rejected(db, tmp_path):
    write(tmp_path, "0001_a.sql", "select 1;")
    with pytest.raises(ValueError, match="unknown baseline"):
        migrate(db, tmp_path, baseline="0005_nope.sql")
```

`pipeline/tests/unit/test_migrate_cli.py`:
```python
from advisor.store.migrate import main


def test_cli_requires_admin_database_url(monkeypatch, capsys):
    monkeypatch.delenv("ADMIN_DATABASE_URL", raising=False)
    assert main([]) == 2
    assert "ADMIN_DATABASE_URL" in capsys.readouterr().err
```

- [ ] **Step 2: Run them to verify they fail**

Run: `scripts/in-docker.sh uv run pytest tests/integration/test_migrate.py tests/unit/test_migrate_cli.py -v`
Expected: collection error `ModuleNotFoundError: No module named 'advisor.store.migrate'`.

- [ ] **Step 3: Implement `migrate.py`**

`pipeline/src/advisor/store/migrate.py`:
```python
"""Apply pending SQL migrations in name order, recording each one in schema_migrations.

Owner-only (never the pipeline's connection string):
    ADMIN_DATABASE_URL=... scripts/in-docker.sh uv run python -m advisor.store.migrate
Add --baseline 0002_rls.sql once if 0001/0002 were pasted into Supabase by hand.
"""

import argparse
import os
import sys
from pathlib import Path

import psycopg

from advisor.store.db import MIGRATIONS_DIR, connect

BOOTSTRAP = """
create table if not exists public.schema_migrations (
  name text primary key,
  applied_at timestamptz not null default now()
);
alter table public.schema_migrations enable row level security;
"""


def applied_migrations(conn: psycopg.Connection) -> set[str]:
    conn.execute(BOOTSTRAP)
    return {row["name"] for row in conn.execute("select name from public.schema_migrations")}


def migrate(
    conn: psycopg.Connection, directory: Path = MIGRATIONS_DIR, *, baseline: str | None = None
) -> list[str]:
    """Apply every *.sql file not yet recorded, each in its own transaction; return those run.

    `baseline` records files up to and including that name as applied without running them,
    for a database that was migrated by hand before tracking existed.
    """
    done = applied_migrations(conn)
    paths = sorted(directory.glob("*.sql"))
    if baseline is not None and baseline not in {path.name for path in paths}:
        raise ValueError(f"unknown baseline migration {baseline!r}")
    executed: list[str] = []
    for path in paths:
        if path.name in done:
            continue
        with conn.transaction():
            if baseline is None or path.name > baseline:
                conn.execute(path.read_text(encoding="utf-8"))
                executed.append(path.name)
            conn.execute("insert into public.schema_migrations (name) values (%s)", (path.name,))
    return executed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="advisor.store.migrate")
    parser.add_argument("--baseline", help="record migrations up to this file as already applied")
    args = parser.parse_args(argv)
    url = os.environ.get("ADMIN_DATABASE_URL")
    if not url:
        print("ADMIN_DATABASE_URL is not set (use an admin connection, never DATABASE_URL)",
              file=sys.stderr)
        return 2
    with connect(url) as conn:
        executed = migrate(conn, baseline=args.baseline)
    print("applied: " + (", ".join(executed) if executed else "nothing (up to date)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Switch the test fixture to `migrate` and remove `apply_migrations`**

In `pipeline/tests/conftest.py`:
- Replace `from advisor.store.db import apply_migrations` with `from advisor.store.migrate import migrate`.
- In the `db` fixture, replace `apply_migrations(conn)` with `migrate(conn)`.

In `pipeline/src/advisor/store/db.py`, delete the whole `apply_migrations` function. Keep `MIGRATIONS_DIR` and `connect`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `scripts/in-docker.sh uv run pytest tests/integration/test_migrate.py tests/unit/test_migrate_cli.py -v`
Expected: 7 passed.

Then run the full suite: `scripts/in-docker.sh uv run pytest -q`
Expected: everything passes. The existing RLS invariant test now also covers `schema_migrations`, which has RLS enabled.

- [ ] **Step 6: Commit**

```bash
uv run ruff check --fix .
git add src/advisor/store/migrate.py src/advisor/store/db.py tests/conftest.py tests/integration/test_migrate.py tests/unit/test_migrate_cli.py
git commit -m "feat: add tracked migration runner with baseline support"
```
End the message with your `Co-Authored-By:` trailer.

---

### Task 2: Migration 0003 — partial status, health-check rows, pipeline role; repo support

**Files:**
- Create: `supabase/migrations/0003_collector_stage.sql`
- Modify: `pipeline/src/advisor/store/repo.py`
- Test: `pipeline/tests/integration/test_schema.py` (add tests), `pipeline/tests/integration/test_repo.py` (add tests)

**Interfaces:**
- Consumes: `CollectorResult`, `CollectorStatus` (Task 3 adds `PARTIAL`; this task's SQL already allows `'partial'`), `SourceState`
- Produces:
  - DB:
    - `source_health.status` allows `'partial'`;
    - `source_health.run_id` is nullable;
    - `source_health.context` is `'run'` or `'health'`, and `run_id` is NULL exactly when context is `'health'`;
    - the NOLOGIN role `pipeline_rw` with policies on every table.
  - `repo.record_source_health(conn, run_id: int | None, result, consecutive_failures: int, attempted_at: datetime, *, context: str = "run") -> None`
  - `repo.load_source_states(conn, sources: Iterable[str]) -> dict[str, SourceState]`
  - `repo.sweep_abandoned_runs(conn, now: datetime, older_than: timedelta = ABANDONED_AFTER) -> int`, with `ABANDONED_AFTER = timedelta(hours=2)`

- [ ] **Step 1: Write the failing tests**

Append to `pipeline/tests/integration/test_schema.py`. It already defines `acting_as` and imports `psycopg` and `pytest`:
```python
def test_pipeline_role_writes_pipeline_tables_but_only_reads_holdings(db):
    db.execute(
        "insert into lots (symbol, asset_type, qty, price, bought_at)"
        " values ('AAPL', 'stock', 1, 100, '2026-10-01')"
    )
    with acting_as(db, "pipeline_rw"):
        db.execute("insert into runs (kind, et_date) values ('pre_open', '2026-10-14')")
        assert len(db.execute("select * from lots").fetchall()) == 1
        for statement in (
            "insert into lots (symbol, asset_type, qty, price, bought_at)"
            " values ('MSFT', 'stock', 1, 100, '2026-10-01')",
            "insert into watchlist (symbol, asset_type) values ('NVDA', 'stock')",
            "update app_config set owner_id = owner_id",
            "create table sneaky (i int)",
            "select * from schema_migrations",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                db.execute(statement)


def test_every_table_except_migrations_has_a_pipeline_policy(db):
    missing = db.execute(
        "select c.relname from pg_class c join pg_namespace n on n.oid = c.relnamespace"
        " where n.nspname = 'public' and c.relkind = 'r' and c.relname <> 'schema_migrations'"
        " and not exists (select 1 from pg_policies p where p.schemaname = 'public'"
        "   and p.tablename = c.relname and 'pipeline_rw' = any(p.roles))"
    ).fetchall()
    assert missing == []


def test_health_rows_have_no_run_and_run_rows_need_one(db):
    db.execute(
        "insert into source_health (run_id, source, status, latency_ms, records,"
        " consecutive_failures, context) values (null, 'alpaca_bars', 'partial', 5, 1, 0, 'health')"
    )
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(
            "insert into source_health (run_id, source, status, latency_ms, records,"
            " consecutive_failures, context) values (null, 'alpaca_bars', 'ok', 5, 1, 0, 'run')"
        )
```

Append to `pipeline/tests/integration/test_repo.py`. It already has `DAY`, `NOW`, `CollectorResult`, `CollectorStatus`, `RunKind`, `RunStatus` and `repo`; add `import psycopg` and `import pytest` to its imports if they're missing:
```python
def test_record_source_health_supports_health_context(db):
    ok = CollectorResult("alpaca_bars", CollectorStatus.OK, [], 7)
    repo.record_source_health(db, None, ok, 0, NOW, context="health")
    row = db.execute("select run_id, context from source_health").fetchone()
    assert (row["run_id"], row["context"]) == (None, "health")
    with pytest.raises(psycopg.errors.CheckViolation):
        repo.record_source_health(db, None, ok, 0, NOW)  # context defaults to "run"


def test_load_source_states_returns_one_state_per_source(db):
    run_id = repo.create_run(db, RunKind.PRE_OPEN, DAY)
    failed = CollectorResult("alpaca_bars", CollectorStatus.FAILED, [], 1, "down")
    repo.record_source_health(db, run_id, failed, 2, NOW)
    states = repo.load_source_states(db, ["alpaca_bars", "yfinance_bars"])
    assert states["alpaca_bars"].consecutive_failures == 2
    assert states["yfinance_bars"].consecutive_failures == 0


def test_sweep_marks_only_old_running_runs_abandoned(db):
    db.execute(
        "insert into runs (kind, et_date, started_at) values"
        " ('pre_close', '2026-10-13', '2026-10-14 08:00+00'),"
        " ('pre_open', '2026-10-14', '2026-10-14 11:30+00')"
    )
    assert repo.sweep_abandoned_runs(db, NOW) == 1  # NOW is 2026-10-14 12:15 UTC
    rows = db.execute("select kind, status, summary from runs order by started_at").fetchall()
    assert rows[0]["status"] == "failed"
    assert rows[0]["summary"]["error"].startswith("abandoned")
    assert rows[1]["status"] == "running"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `scripts/in-docker.sh uv run pytest tests/integration/test_schema.py tests/integration/test_repo.py -v`
Expected: the new tests fail. The pipeline role doesn't exist (`InvalidParameterValue` or `UndefinedObject` from `set role`), there's no `context` column, and `load_source_states` and `sweep_abandoned_runs` don't exist yet.

- [ ] **Step 3: Write the migration**

`supabase/migrations/0003_collector_stage.sql`:
```sql
-- Plan 2a: partial collector results, daily health-check rows, and a least-privilege
-- pipeline role. After applying, the owner creates the login role once (see README):
--   create role advisor_pipeline login password '<long random>'; grant pipeline_rw to advisor_pipeline;

alter table source_health drop constraint source_health_status_check;
alter table source_health add constraint source_health_status_check
  check (status in ('ok', 'partial', 'stale', 'failed', 'skipped'));
alter table source_health alter column run_id drop not null;
alter table source_health
  add column context text not null default 'run' check (context in ('run', 'health'));
alter table source_health
  add constraint source_health_run_context check ((context = 'run') = (run_id is not null));

do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'pipeline_rw') then
    create role pipeline_rw nologin;
  end if;
end $$;

grant usage on schema public to pipeline_rw;
grant select, insert, update, delete on all tables in schema public to pipeline_rw;
grant usage, select on all sequences in schema public to pipeline_rw;
alter default privileges in schema public
  grant select, insert, update, delete on tables to pipeline_rw;
alter default privileges in schema public grant usage, select on sequences to pipeline_rw;
revoke insert, update, delete on lots, sells, watchlist, app_config from pipeline_rw;
do $$ begin
  if to_regclass('public.schema_migrations') is not null then
    revoke all on public.schema_migrations from pipeline_rw;
  end if;
end $$;

-- RLS still applies to pipeline_rw (it does not own the tables), so it needs explicit policies.
do $$
declare
  t text;
begin
  foreach t in array array[
    'runs', 'source_health', 'symbols', 'features_live', 'predictions', 'picks',
    'pick_outcomes', 'watchlist_verdicts', 'holding_actions', 'news_items', 'models'
  ] loop
    execute format(
      'create policy pipeline_write on public.%I for all to pipeline_rw using (true) with check (true)', t);
  end loop;
  foreach t in array array['watchlist', 'lots', 'sells', 'app_config'] loop
    execute format('create policy pipeline_read on public.%I for select to pipeline_rw using (true)', t);
  end loop;
end $$;
```

- [ ] **Step 4: Update `repo.py`**

In `pipeline/src/advisor/store/repo.py`:

Change the imports at the top to:
```python
from collections.abc import Iterable, Sequence
from datetime import date, datetime, timedelta
```

Replace `record_source_health` with:
```python
def record_source_health(
    conn: psycopg.Connection,
    run_id: int | None,
    result: CollectorResult,
    consecutive_failures: int,
    attempted_at: datetime,
    *,
    context: str = "run",
) -> None:
    """One row per source per run (context 'run') or per daily check (context 'health', no run)."""
    conn.execute(
        "insert into source_health (run_id, source, status, latency_ms, records, error,"
        " consecutive_failures, attempted_at, context)"
        " values (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            run_id, result.name, result.status.value, result.latency_ms, len(result.records),
            result.error, consecutive_failures, attempted_at, context,
        ),
    )
```

Add directly after `load_source_state`:
```python
def load_source_states(conn: psycopg.Connection, sources: Iterable[str]) -> dict[str, SourceState]:
    return {source: load_source_state(conn, source) for source in sources}


ABANDONED_AFTER = timedelta(hours=2)  # far beyond the 40-minute job timeout


def sweep_abandoned_runs(
    conn: psycopg.Connection, now: datetime, older_than: timedelta = ABANDONED_AFTER
) -> int:
    """Mark runs still 'running' long after they started (job killed or timed out) as failed."""
    cursor = conn.execute(
        "update runs set status = 'failed', finished_at = %s, summary = summary || %s"
        " where status = 'running' and started_at < %s",
        (
            now,
            Jsonb({"error": "abandoned: no finish was recorded (job killed or timed out)"}),
            now - older_than,
        ),
    )
    return cursor.rowcount
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `scripts/in-docker.sh uv run pytest tests/integration/test_schema.py tests/integration/test_repo.py tests/integration/test_migrate.py -v`
Expected: all pass. `test_db_fixture_records_every_migration` now includes `0003_collector_stage.sql`.

Then run the full suite. Expected: all pass. Existing calls to `record_source_health(conn, run_id, result, failures, now_utc)` still work, because `context` defaults to `"run"`.

- [ ] **Step 6: Commit**

```bash
uv run ruff check --fix .
git add ../supabase/migrations/0003_collector_stage.sql src/advisor/store/repo.py tests/integration/test_schema.py tests/integration/test_repo.py
git commit -m "feat: add pipeline_rw role, partial and health-check source rows, abandoned-run sweep"
```
End the message with your `Co-Authored-By:` trailer.

---

### Task 3: Collector protocol v2 and runner (scope, partial results, per-symbol cache)

**Files:**
- Modify: `pipeline/src/advisor/collectors/base.py`, `pipeline/src/advisor/collectors/runner.py` (full replacement), `pipeline/src/advisor/collectors/nasdaq_symbols.py`, `pipeline/src/advisor/collectors/alpaca_bars.py`, `pipeline/src/advisor/collectors/yfinance_bars.py`, `pipeline/tests/fakes.py`
- Test: `pipeline/tests/unit/test_runner.py`, `pipeline/tests/unit/test_registry.py`

**Interfaces:**
- Produces:
  - `base.Scope` (`UNIVERSE`, `SYMBOLS`, `MARKET`)
  - `base.CollectorStatus.PARTIAL`
  - `base.PartialFetch(records, error)`, an exception with a `.records` list
  - `Collector` protocol attributes `scope: Scope` and `canary: tuple[str, ...]`
  - `runner.next_failures`, where PARTIAL resets to 0
  - `runner.run_collector(...)` (same signature), with per-scope caching and PARTIAL handling
  - `runner.WHOLE = ""`
  - `FakeCollector` fields `scope` (default `Scope.SYMBOLS`) and `canary` (default `()`)
- Removes: `runner.cache_key`, whose only caller was `run_collector`

- [ ] **Step 1: Update the test fake**

In `pipeline/tests/fakes.py`:
- change `from advisor.collectors.base import Cadence, Category` to `from advisor.collectors.base import Cadence, Category, Scope`;
- add two fields to `FakeCollector` right after `freshness`:
```python
    scope: Scope = Scope.SYMBOLS
    canary: tuple[str, ...] = ()
```
This fails to import until Step 3 adds `Scope`.

- [ ] **Step 2: Write the failing tests**

In `pipeline/tests/unit/test_runner.py`:
- change the base import to `from advisor.collectors.base import Cadence, CollectorResult, CollectorStatus, PartialFetch, Scope`;
- add `from fakes import FakeCollector, bar, info` (replacing the current fakes import);
- add `scope=Scope.UNIVERSE,` to the `defaults` dict in `universe_collector`;
- add this assertion to `test_next_failures_counts_consecutive_failures`:
  `assert next_failures(state, result(CollectorStatus.PARTIAL)) == 0`.

Then append:
```python
def bars_collector(**kwargs) -> FakeCollector:
    defaults = dict(
        name="bars",
        records_for=lambda symbols: [bar(s, TODAY, 10.0) for s in symbols],
        freshness=timedelta(days=1),
    )
    return FakeCollector(**{**defaults, **kwargs})


def test_symbols_scope_caches_per_symbol_and_serves_requested_symbols_on_failure(tmp_path):
    cache = DiskCache(tmp_path, clock=lambda: NOW)
    run_collector(bars_collector(), ["AAA", "BBB"], NOW, cache=cache, state=SourceState())
    failing = bars_collector(error=httpx.ConnectError("down"))
    result = run_collector(failing, ["BBB", "CCC"], NOW, cache=cache, state=SourceState())
    assert result.status is CollectorStatus.STALE
    assert [r.symbol for r in result.records] == ["BBB"]


def test_empty_results_never_overwrite_a_good_cache_entry(tmp_path):
    cache = DiskCache(tmp_path, clock=lambda: NOW)
    run_collector(universe_collector(), [], NOW, cache=cache, state=SourceState())
    empty = universe_collector(records_for=lambda symbols: [])
    assert run_collector(empty, [], NOW, cache=cache, state=SourceState()).records == []
    failing = universe_collector(error=httpx.ConnectError("down"))
    result = run_collector(failing, [], NOW, cache=cache, state=SourceState())
    assert result.status is CollectorStatus.STALE
    assert [r.symbol for r in result.records] == ["AAPL"]


def test_partial_fetch_keeps_records_and_caches_them(tmp_path):
    cache = DiskCache(tmp_path, clock=lambda: NOW)
    partial = bars_collector(error=PartialFetch([bar("AAA", TODAY, 10.0)], "1 of 2 requests failed"))
    result = run_collector(partial, ["AAA", "BBB"], NOW, cache=cache, state=SourceState())
    assert result.status is CollectorStatus.PARTIAL
    assert [r.symbol for r in result.records] == ["AAA"]
    assert result.error == "PartialFetch: 1 of 2 requests failed"
    failing = bars_collector(error=httpx.ConnectError("down"))
    stale = run_collector(failing, ["AAA"], NOW, cache=cache, state=SourceState())
    assert [r.symbol for r in stale.records] == ["AAA"]
```

In `pipeline/tests/unit/test_registry.py`, add `from advisor.collectors.base import Scope` and append these assertions to the existing test:
```python
    assert {name: c.scope for name, c in registry.items()} == {
        "alpaca_bars": Scope.SYMBOLS,
        "nasdaq_symbols": Scope.UNIVERSE,
        "yfinance_bars": Scope.SYMBOLS,
    }
    for collector in registry.values():  # SYMBOLS collectors need canaries for the health check
        assert bool(collector.canary) == (collector.scope is Scope.SYMBOLS)
```

- [ ] **Step 3: Run them to verify they fail**

Run: `scripts/in-docker.sh uv run pytest tests/unit/test_runner.py tests/unit/test_registry.py -v`
Expected: ImportError, `cannot import name 'PartialFetch'` / `'Scope'` from `advisor.collectors.base`.

- [ ] **Step 4: Extend `base.py`**

In `pipeline/src/advisor/collectors/base.py`:

Add after the `Cadence` class:
```python
class Scope(StrEnum):
    UNIVERSE = "universe"  # returns the symbol universe; `symbols` is ignored
    SYMBOLS = "symbols"  # records per requested symbol; every record has a `symbol` field
    MARKET = "market"  # market-wide data (macro, sentiment); `symbols` is ignored
```

Replace the `CollectorStatus` class with:
```python
class CollectorStatus(StrEnum):
    OK = "ok"
    PARTIAL = "partial"
    STALE = "stale"
    FAILED = "failed"
    SKIPPED = "skipped"
```

Add after the `CollectorResult` dataclass:
```python
class PartialFetch(Exception):
    """Raised by `fetch` when some requests failed but others returned usable records."""

    def __init__(self, records: Sequence[BaseModel], error: str) -> None:
        super().__init__(error)
        self.records = list(records)
```

In the `Collector` protocol, add after `freshness`:
```python
    scope: Scope
    canary: tuple[str, ...]  # symbols the daily health check fetches; () unless scope is SYMBOLS
```

- [ ] **Step 5: Replace `runner.py`**

`pipeline/src/advisor/collectors/runner.py` (full replacement):
```python
"""Runs one collector safely: circuit breaker, timing, error capture, cache fallback."""

import time
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime

from pydantic import BaseModel

from advisor.collectors.base import (
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


def _cache_keys(collector: Collector, symbols: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(symbols)) if collector.scope is Scope.SYMBOLS else [WHOLE]


def _cached(
    collector: Collector, symbols: Sequence[str], cache: DiskCache
) -> list[BaseModel] | None:
    """Fresh cached records for this request (per symbol for SYMBOLS scope), or None."""
    if collector.freshness is None:
        return None
    found: list[BaseModel] = []
    for key in _cache_keys(collector, symbols):
        found.extend(
            cache.get(collector.name, key, collector.record_type, collector.freshness) or []
        )
    return found or None


def _store(collector: Collector, records: Sequence[BaseModel], cache: DiskCache) -> None:
    """Cache non-empty results only, so an empty answer never replaces good data."""
    if collector.freshness is None or not records:
        return
    groups: dict[str, list[BaseModel]] = defaultdict(list)
    for record in records:
        groups[record.symbol if collector.scope is Scope.SYMBOLS else WHOLE].append(record)
    for key, group in groups.items():
        try:
            cache.put(collector.name, key, group)
        except (OSError, TypeError, ValueError):
            pass  # cache is a fallback; a failed write must not lose a good fetch


def run_collector(
    collector: Collector,
    symbols: Sequence[str],
    as_of: datetime,
    *,
    cache: DiskCache,
    state: SourceState,
) -> CollectorResult:
    if breaker_open(state, as_of.astimezone(ET).date()):
        return CollectorResult(
            collector.name,
            CollectorStatus.SKIPPED,
            _cached(collector, symbols, cache) or [],
            0,
            "circuit breaker open",
        )

    started = time.perf_counter()
    status, error = CollectorStatus.OK, None
    try:
        records = list(collector.fetch(symbols, as_of))
    except PartialFetch as exc:
        records = exc.records
        status, error = CollectorStatus.PARTIAL, f"PartialFetch: {exc}"[:500]
    except Exception as exc:  # any source failure is contained here
        latency = int((time.perf_counter() - started) * 1000)
        error = f"{type(exc).__name__}: {exc}"[:500]
        cached = _cached(collector, symbols, cache)
        if cached is not None:
            return CollectorResult(collector.name, CollectorStatus.STALE, cached, latency, error)
        return CollectorResult(collector.name, CollectorStatus.FAILED, [], latency, error)

    latency = int((time.perf_counter() - started) * 1000)
    _store(collector, records, cache)
    return CollectorResult(collector.name, status, records, latency, error)
```

- [ ] **Step 6: Declare `scope` and `canary` on the three collectors**

Add `Scope` to the `from advisor.collectors.base import ...` line in each file. Then add these two class attributes directly after `freshness = ...`:
- `nasdaq_symbols.py` → `scope = Scope.UNIVERSE` and `canary: tuple[str, ...] = ()`
- `alpaca_bars.py` → `scope = Scope.SYMBOLS` and `canary = ("AAPL", "MSFT")`
- `yfinance_bars.py` → `scope = Scope.SYMBOLS` and `canary = ("AAPL", "MSFT")`

- [ ] **Step 7: Run the tests to verify they pass**

Run: `scripts/in-docker.sh uv run pytest tests/unit/test_runner.py tests/unit/test_registry.py -v`
Expected: all pass.

- [ ] **Step 8: Fix the universe fake in the run tests, then run the full suite**

In `pipeline/tests/integration/test_run.py`, the `nasdaq_symbols` `FakeCollector` in `make_deps` must declare `scope=Scope.UNIVERSE`. Otherwise the new per-symbol caching would treat its `SymbolInfo` list as per-symbol records. Add the argument, and add `Scope` to that file's `advisor.collectors.base` import.

Run: `scripts/in-docker.sh uv run pytest -q`
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
uv run ruff check --fix .
git add src/advisor/collectors tests/fakes.py tests/unit/test_runner.py tests/unit/test_registry.py tests/integration/test_run.py
git commit -m "feat: add collector scope, partial results, and per-symbol caching"
```
End the message with your `Co-Authored-By:` trailer.

---

### Task 4: Honour Retry-After; isolate Alpaca requests so one bad chunk is a partial result

**Files:**
- Modify: `pipeline/src/advisor/collectors/base.py` (`get_with_retries`), `pipeline/src/advisor/collectors/alpaca_bars.py` (`fetch`)
- Test: `pipeline/tests/unit/test_base.py`, `pipeline/tests/unit/test_alpaca_bars.py`

**Interfaces:**
- Consumes: `PartialFetch` (Task 3)
- Produces:
  - `get_with_retries` waits `max(backoff, Retry-After)` on retryable responses, with Retry-After capped at `MAX_RETRY_AFTER = 60.0`.
  - `AlpacaBars.fetch` returns all bars when every request succeeds.
    - It raises `PartialFetch(bars, "<k> of <n> Alpaca requests failed; first: ...")` when some requests fail.
    - It raises `RuntimeError("all <n> Alpaca requests failed; first: ...")` when none succeed.
    - Each 200-symbol chunk is all-or-nothing across its pages.

- [ ] **Step 1: Write the failing tests**

Append to `pipeline/tests/unit/test_base.py`. It already has `scripted_client`, `httpx`, `pytest` and `get_with_retries`:
```python
@pytest.mark.parametrize(
    ("header", "expected_sleep"),
    [("7", 7.0), ("120", 60.0), ("0", 1.0), ("Wed, 21 Oct 2026 07:28:00 GMT", 1.0)],
)
def test_retry_after_header_sets_the_wait(header, expected_sleep):
    client, _ = scripted_client(
        [httpx.Response(429, headers={"Retry-After": header}), httpx.Response(200, text="ok")]
    )
    sleeps = []
    assert get_with_retries(client, "https://example.test/x", sleep=sleeps.append).text == "ok"
    assert sleeps == [expected_sleep]
```

Append to `pipeline/tests/unit/test_alpaca_bars.py`. It already has `AS_OF`, `FAST`, `raw`, `httpx`, `AlpacaBars`; add `import pytest` and `from advisor.collectors.base import PartialFetch` to its imports:
```python
def test_a_rejected_chunk_is_a_partial_result_and_other_chunks_are_kept():
    def handler(request: httpx.Request) -> httpx.Response:
        symbols = request.url.params["symbols"].split(",")
        if "S210" in symbols:  # second chunk contains a symbol Alpaca rejects
            return httpx.Response(400, json={"message": "invalid symbol: S210"})
        return httpx.Response(200, json={
            "bars": {"S000": [raw("2026-10-13T04:00:00Z", 5.0)]}, "next_page_token": None,
        })

    collector = AlpacaBars(
        httpx.Client(transport=httpx.MockTransport(handler)), "key", "secret", limiter=FAST
    )
    with pytest.raises(PartialFetch, match="1 of 2 Alpaca requests failed") as caught:
        collector.fetch([f"S{i:03d}" for i in range(250)], AS_OF)
    assert [b.symbol for b in caught.value.records] == ["S000"]


def test_every_chunk_failing_raises_with_the_first_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "unauthorized"})

    collector = AlpacaBars(
        httpx.Client(transport=httpx.MockTransport(handler)), "key", "secret", limiter=FAST
    )
    with pytest.raises(RuntimeError, match="all 2 Alpaca requests failed"):
        collector.fetch([f"S{i:03d}" for i in range(250)], AS_OF)


def test_a_chunk_failing_on_a_later_page_contributes_no_bars():
    def handler(request: httpx.Request) -> httpx.Response:
        symbols = request.url.params["symbols"].split(",")
        first_chunk = "S000" in symbols
        if first_chunk and request.url.params.get("page_token") == "p2":
            return httpx.Response(400, json={"message": "bad page"})
        rows = {"S000": [raw("2026-10-12T04:00:00Z", 5.0)]} if first_chunk else {
            "S200": [raw("2026-10-12T04:00:00Z", 6.0)]
        }
        return httpx.Response(200, json={
            "bars": rows, "next_page_token": "p2" if first_chunk else None,
        })

    collector = AlpacaBars(
        httpx.Client(transport=httpx.MockTransport(handler)), "key", "secret", limiter=FAST
    )
    with pytest.raises(PartialFetch) as caught:
        collector.fetch([f"S{i:03d}" for i in range(250)], AS_OF)
    assert [b.symbol for b in caught.value.records] == ["S200"]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `scripts/in-docker.sh uv run pytest tests/unit/test_base.py tests/unit/test_alpaca_bars.py -v`
Expected:
- The Retry-After cases fail: they sleep `[1.0]` instead of 7/60.
- The Alpaca tests fail: a single 400 currently raises `HTTPStatusError` for the whole fetch.

- [ ] **Step 3: Implement Retry-After**

In `pipeline/src/advisor/collectors/base.py`, add next to `RETRY_STATUS`:
```python
MAX_RETRY_AFTER = 60.0  # never let a server park a run for longer than this per retry
```

Add above `get_with_retries`:
```python
def _retry_after(response: httpx.Response) -> float | None:
    """Seconds from a numeric Retry-After header, clamped to [0, MAX_RETRY_AFTER]; else None."""
    try:
        seconds = float(response.headers.get("Retry-After", "").strip())
    except ValueError:
        return None
    return min(max(seconds, 0.0), MAX_RETRY_AFTER)
```

Replace the body of `get_with_retries` (keep its signature and docstring) with:
```python
    last_error: Exception | None = None
    for attempt in range(attempts):
        retry_after: float | None = None
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
            retry_after = _retry_after(response)
            last_error = httpx.HTTPStatusError(
                f"HTTP {response.status_code} from {url}",
                request=response.request,
                response=response,
            )
        if attempt < attempts - 1:
            backoff = base_delay * 2**attempt
            sleep(backoff if retry_after is None else max(backoff, retry_after))
    assert last_error is not None
    raise last_error
```

- [ ] **Step 4: Isolate Alpaca chunks**

In `pipeline/src/advisor/collectors/alpaca_bars.py`:
- add `PartialFetch` to the base import;
- replace the whole `fetch` method with these two methods:
```python
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
        chunks = [
            unique[i : i + SYMBOLS_PER_REQUEST] for i in range(0, len(unique), SYMBOLS_PER_REQUEST)
        ]
        bars: list[DailyBar] = []
        errors: list[str] = []
        for chunk in chunks:
            try:
                bars.extend(self._fetch_chunk(chunk, base_params))
            except (httpx.HTTPError, ValueError) as exc:  # one bad request must not lose the rest
                errors.append(f"{chunk[0]}..{chunk[-1]}: {type(exc).__name__}: {exc}")
        if errors and not bars:
            raise RuntimeError(f"all {len(chunks)} Alpaca requests failed; first: {errors[0]}")
        if errors:
            raise PartialFetch(
                bars, f"{len(errors)} of {len(chunks)} Alpaca requests failed; first: {errors[0]}"
            )
        return bars

    def _fetch_chunk(self, chunk: list[str], base_params: dict) -> list[DailyBar]:
        """Every page for one chunk; any failing page raises, so a chunk is all-or-nothing."""
        bars: list[DailyBar] = []
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
                parsed = (_to_bar(symbol, r) for r in rows or [])
                bars.extend(b for b in parsed if b is not None)
            page_token = payload.get("next_page_token")
            if not page_token:
                return bars
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `scripts/in-docker.sh uv run pytest tests/unit/test_base.py tests/unit/test_alpaca_bars.py -v`
Expected: all pass, including the existing paging, chunking and empty-list tests.

Then run the full suite: `scripts/in-docker.sh uv run pytest -q`. Expected: all pass.

- [ ] **Step 6: Commit**

```bash
uv run ruff check --fix .
git add src/advisor/collectors/base.py src/advisor/collectors/alpaca_bars.py tests/unit/test_base.py tests/unit/test_alpaca_bars.py
git commit -m "fix: honour Retry-After and keep good Alpaca chunks when one request fails"
```
End the message with your `Co-Authored-By:` trailer.

---

### Task 5: SourceTracker — one merged result and one health row per source

**Files:**
- Create: `pipeline/src/advisor/collectors/tracker.py`
- Test: `pipeline/tests/unit/test_tracker.py`

**Interfaces:**
- Consumes: `run_collector`, `next_failures`, `SourceState` (runner); `CollectorResult`, `CollectorStatus` (base); `DiskCache`
- Produces:
  - `merge_results(results: Sequence[CollectorResult]) -> CollectorResult`
  - `UNHEALTHY: frozenset[CollectorStatus]` (PARTIAL, STALE, FAILED, SKIPPED)
  - `SourceTracker(collectors: Mapping[str, Collector], cache: DiskCache, as_of: datetime, states: Mapping[str, SourceState])` with these methods:
    - `.run(name: str, symbols: Sequence[str]) -> CollectorResult` (thread-safe)
    - `.merged() -> list[CollectorResult]` (one per source attempted, in first-attempt order)
    - `.health_rows() -> list[tuple[CollectorResult, int]]` (merged result plus next consecutive failures)
    - `.count_healthy() -> int`

- [ ] **Step 1: Write the failing test**

`pipeline/tests/unit/test_tracker.py`:
```python
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime

import httpx
import pytest

from advisor.collectors.base import CollectorResult, CollectorStatus
from advisor.collectors.cache import DiskCache
from advisor.collectors.runner import SourceState
from advisor.collectors.tracker import SourceTracker, merge_results
from fakes import FakeCollector, bar

NOW = datetime(2026, 10, 14, 12, 15, tzinfo=UTC)
S = CollectorStatus


def result(status: CollectorStatus, n: int = 0, error: str | None = None) -> CollectorResult:
    return CollectorResult("src", status, [bar("AAA", date(2026, 10, 13), 1.0)] * n, 5, error)


@pytest.mark.parametrize(
    ("statuses", "merged"),
    [
        ([S.OK, S.OK], S.OK),
        ([S.FAILED, S.FAILED], S.FAILED),
        ([S.SKIPPED, S.SKIPPED], S.SKIPPED),
        ([S.PARTIAL], S.PARTIAL),
        ([S.OK, S.FAILED], S.PARTIAL),
        ([S.OK, S.STALE], S.PARTIAL),
        ([S.STALE, S.FAILED], S.STALE),
    ],
)
def test_merge_status_rules(statuses, merged):
    assert merge_results([result(s) for s in statuses]).status is merged


def test_merge_sums_records_and_latency_and_keeps_first_error():
    merged = merge_results([result(S.OK, 2), result(S.FAILED, 0, "down"), result(S.OK, 1)])
    assert len(merged.records) == 3
    assert merged.latency_ms == 15
    assert merged.error == "down"


def tracker_with(collectors: dict, tmp_path, states=None) -> SourceTracker:
    return SourceTracker(collectors, DiskCache(tmp_path), NOW, states or {})


def test_two_calls_to_one_source_become_one_partial_row(tmp_path):
    flaky = FakeCollector("prices", records_for=lambda syms: [bar(s, date(2026, 10, 13), 1.0) for s in syms])
    tracker = tracker_with({"prices": flaky}, tmp_path, {"prices": SourceState(2)})
    tracker.run("prices", ["OTCX"])
    flaky.error = httpx.ConnectError("down")
    tracker.run("prices", ["AAA", "BBB"])
    [(merged, failures)] = tracker.health_rows()
    assert merged.status is S.PARTIAL
    assert failures == 0  # a partial answer resets the breaker count
    assert flaky.calls == [["OTCX"], ["AAA", "BBB"]]


def test_count_healthy_counts_unneeded_sources_as_healthy(tmp_path):
    collectors = {
        "ok": FakeCollector("ok"),
        "broken": FakeCollector("broken", error=httpx.ConnectError("down")),
        "unused": FakeCollector("unused"),
    }
    tracker = tracker_with(collectors, tmp_path)
    tracker.run("ok", ["AAA"])
    tracker.run("broken", ["AAA"])
    assert tracker.count_healthy() == 2
    assert [r.name for r in tracker.merged()] == ["ok", "broken"]


def test_concurrent_runs_of_many_sources_are_all_recorded(tmp_path):
    collectors = {f"s{i}": FakeCollector(f"s{i}") for i in range(20)}
    tracker = tracker_with(collectors, tmp_path)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda name: tracker.run(name, ["AAA"]), collectors))
    assert sorted(r.name for r in tracker.merged()) == sorted(collectors)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `scripts/in-docker.sh uv run pytest tests/unit/test_tracker.py -v`
Expected: `ModuleNotFoundError: No module named 'advisor.collectors.tracker'`.

- [ ] **Step 3: Implement**

`pipeline/src/advisor/collectors/tracker.py`:
```python
"""Runs collectors for one pipeline run and keeps one merged result per source.

A source can be called more than once per run (holdings phase, market phase); its health row
must still be a single row whose status tells the truth about the whole run.
"""

import threading
from collections.abc import Mapping, Sequence
from datetime import datetime

from advisor.collectors.base import Collector, CollectorResult, CollectorStatus
from advisor.collectors.cache import DiskCache
from advisor.collectors.runner import SourceState, next_failures, run_collector

UNHEALTHY = frozenset({
    CollectorStatus.PARTIAL,
    CollectorStatus.STALE,
    CollectorStatus.FAILED,
    CollectorStatus.SKIPPED,
})


def merge_results(results: Sequence[CollectorResult]) -> CollectorResult:
    """Combine several calls to one source into the single result its health row reports."""
    statuses = {r.status for r in results}
    if len(statuses) == 1:
        status = next(iter(statuses))
    elif statuses <= {CollectorStatus.STALE, CollectorStatus.FAILED}:
        status = CollectorStatus.STALE
    else:
        status = CollectorStatus.PARTIAL
    return CollectorResult(
        name=results[0].name,
        status=status,
        records=[record for r in results for record in r.records],
        latency_ms=sum(r.latency_ms for r in results),
        error=next((r.error for r in results if r.error), None),
    )


class SourceTracker:
    def __init__(
        self,
        collectors: Mapping[str, Collector],
        cache: DiskCache,
        as_of: datetime,
        states: Mapping[str, SourceState],
    ) -> None:
        self._collectors = collectors
        self._cache = cache
        self._as_of = as_of
        self._states = dict(states)
        self._calls: dict[str, list[CollectorResult]] = {}
        self._lock = threading.Lock()

    def _state(self, name: str) -> SourceState:
        return self._states.get(name, SourceState())

    def run(self, name: str, symbols: Sequence[str]) -> CollectorResult:
        result = run_collector(
            self._collectors[name], symbols, self._as_of, cache=self._cache, state=self._state(name)
        )
        with self._lock:
            self._calls.setdefault(name, []).append(result)
        return result

    def merged(self) -> list[CollectorResult]:
        with self._lock:
            return [merge_results(calls) for calls in self._calls.values()]

    def health_rows(self) -> list[tuple[CollectorResult, int]]:
        return [(r, next_failures(self._state(r.name), r)) for r in self.merged()]

    def count_healthy(self) -> int:
        """Registered sources minus those unhealthy this run; a source this run didn't need counts as healthy."""
        unhealthy = {r.name for r in self.merged() if r.status in UNHEALTHY}
        return len(self._collectors) - len(unhealthy)
```

- [ ] **Step 4: Run it to verify it passes**

Run: `scripts/in-docker.sh uv run pytest tests/unit/test_tracker.py -v`
Expected: 11 passed.

- [ ] **Step 5: Commit**

```bash
uv run ruff check --fix .
git add src/advisor/collectors/tracker.py tests/unit/test_tracker.py
git commit -m "feat: add source tracker that merges calls into one health result per source"
```
End the message with your `Co-Authored-By:` trailer.

---

### Task 6: Enrichment stage — shortlist and concurrent collectors

**Files:**
- Create: `pipeline/src/advisor/enrich.py`
- Test: `pipeline/tests/unit/test_enrich.py`

**Interfaces:**
- Consumes: `SourceTracker` (Task 5), `Scope`, `Collector`, `CollectorResult`, `ScreenRow` (`advisor.screener`), `AssetType`
- Produces:
  - `SHORTLIST_SIZE = 300` and `ENRICH_WORKERS = 8`
  - `shortlist(passed: Sequence[ScreenRow], priority: Sequence[str], size: int = SHORTLIST_SIZE) -> list[str]`
  - `EnrichTargets(stocks: list[str], crypto: list[str])`
  - `symbols_for(collector, targets) -> list[str]`
  - `run_enrichment(tracker, collectors: Mapping[str, Collector], names: Sequence[str], targets: EnrichTargets, *, workers: int = ENRICH_WORKERS) -> dict[str, CollectorResult]`

- [ ] **Step 1: Write the failing test**

`pipeline/tests/unit/test_enrich.py`:
```python
from datetime import UTC, date, datetime

from advisor.collectors.base import Scope
from advisor.collectors.cache import DiskCache
from advisor.collectors.tracker import SourceTracker
from advisor.enrich import EnrichTargets, run_enrichment, shortlist, symbols_for
from advisor.models import AssetType
from advisor.screener import ScreenRow
from fakes import FakeCollector

NOW = datetime(2026, 10, 14, 12, 15, tzinfo=UTC)
DAY = date(2026, 10, 13)


def row(symbol: str, adv20: float) -> ScreenRow:
    return ScreenRow(symbol, 10.0, adv20, 70, DAY)


def test_shortlist_puts_priority_first_then_ranks_by_dollar_volume():
    passed = [row("LOW", 2e6), row("HIGH", 9e6), row("MID", 5e6), row("OTCX", 8e6), row("TIE", 5e6)]
    assert shortlist(passed, ["OTCX", "AAPL"], size=3) == ["OTCX", "AAPL", "HIGH", "MID", "TIE"]


def test_shortlist_with_no_priority_and_a_small_size():
    assert shortlist([row("A", 1e6), row("B", 2e6)], [], size=1) == ["B"]


TARGETS = EnrichTargets(stocks=["OTCX", "AAA"], crypto=["BTC"])


def test_symbols_for_routes_by_scope_and_asset_type():
    stock = FakeCollector("stock")
    crypto = FakeCollector("crypto", asset_types=frozenset({AssetType.CRYPTO}))
    both = FakeCollector("both", asset_types=frozenset({AssetType.STOCK, AssetType.CRYPTO}))
    market = FakeCollector("market", scope=Scope.MARKET)
    assert symbols_for(stock, TARGETS) == ["OTCX", "AAA"]
    assert symbols_for(crypto, TARGETS) == ["BTC"]
    assert symbols_for(both, TARGETS) == ["OTCX", "AAA", "BTC"]
    assert symbols_for(market, TARGETS) == []


def test_run_enrichment_runs_each_collector_once_and_skips_ones_with_no_targets(tmp_path):
    collectors = {
        "stock": FakeCollector("stock"),
        "market": FakeCollector("market", scope=Scope.MARKET),
        "crypto": FakeCollector("crypto", asset_types=frozenset({AssetType.CRYPTO})),
    }
    tracker = SourceTracker(collectors, DiskCache(tmp_path), NOW, {})
    targets = EnrichTargets(stocks=["OTCX", "AAA"], crypto=[])
    results = run_enrichment(tracker, collectors, list(collectors), targets)
    assert sorted(results) == ["market", "stock"]
    assert collectors["stock"].calls == [["OTCX", "AAA"]]
    assert collectors["market"].calls == [[]]
    assert collectors["crypto"].calls == []


def test_run_enrichment_with_nothing_to_do_returns_empty(tmp_path):
    tracker = SourceTracker({}, DiskCache(tmp_path), NOW, {})
    assert run_enrichment(tracker, {}, [], TARGETS) == {}
```

- [ ] **Step 2: Run it to verify it fails**

Run: `scripts/in-docker.sh uv run pytest tests/unit/test_enrich.py -v`
Expected: `ModuleNotFoundError: No module named 'advisor.enrich'`.

- [ ] **Step 3: Implement**

`pipeline/src/advisor/enrich.py`:
```python
"""Enrichment stage (spec §4.3 stage 4): which symbols each collector gets, run concurrently.

Holdings and watchlist symbols always come first, so collectors with daily caps spend them on
the owner's positions before the rest of the shortlist (spec §7.2).
"""

from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from advisor.collectors.base import Collector, CollectorResult, Scope
from advisor.collectors.tracker import SourceTracker
from advisor.models import AssetType
from advisor.screener import ScreenRow

SHORTLIST_SIZE = 300
ENRICH_WORKERS = 8


def shortlist(
    passed: Sequence[ScreenRow], priority: Sequence[str], size: int = SHORTLIST_SIZE
) -> list[str]:
    """Priority symbols first (as given), then up to `size` passing symbols by dollar volume.

    Interim ranking: Plan 3's screener model replaces 20-day dollar volume as the sort key.
    """
    chosen = set(priority)
    ranked = [
        r.symbol
        for r in sorted(passed, key=lambda r: (-r.adv20, r.symbol))
        if r.symbol not in chosen
    ]
    return list(priority) + ranked[:size]


@dataclass(frozen=True)
class EnrichTargets:
    stocks: list[str]  # priority stocks first, then the shortlist
    crypto: list[str]  # held and watchlist crypto, holdings first


def symbols_for(collector: Collector, targets: EnrichTargets) -> list[str]:
    if collector.scope is not Scope.SYMBOLS:
        return []
    symbols: list[str] = []
    if AssetType.STOCK in collector.asset_types:
        symbols += targets.stocks
    if AssetType.CRYPTO in collector.asset_types:
        symbols += targets.crypto
    return symbols


def run_enrichment(
    tracker: SourceTracker,
    collectors: Mapping[str, Collector],
    names: Sequence[str],
    targets: EnrichTargets,
    *,
    workers: int = ENRICH_WORKERS,
) -> dict[str, CollectorResult]:
    """Run each named collector once, concurrently; SYMBOLS collectors with no targets are skipped."""
    jobs: dict[str, list[str]] = {}
    for name in names:
        collector = collectors[name]
        symbols = symbols_for(collector, targets)
        if collector.scope is Scope.SYMBOLS and not symbols:
            continue
        jobs[name] = symbols
    if not jobs:
        return {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {name: pool.submit(tracker.run, name, symbols) for name, symbols in jobs.items()}
        return {name: future.result() for name, future in futures.items()}
```

- [ ] **Step 4: Run it to verify it passes**

Run: `scripts/in-docker.sh uv run pytest tests/unit/test_enrich.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
uv run ruff check --fix .
git add src/advisor/enrich.py tests/unit/test_enrich.py
git commit -m "feat: add shortlist and concurrent enrichment stage"
```
End the message with your `Co-Authored-By:` trailer.

---

### Task 7: Orchestrator v2 — holdings-first two-phase flow, tracker, enrichment, sweep

**Files:**
- Modify: `pipeline/src/advisor/run.py` (replace `execute_run`, add helpers; `main` and `parse_args` stay as they are), `pipeline/tests/fakes.py` (add `FRESH_START`, `fake_price_collectors`)
- Test: `pipeline/tests/integration/test_run.py` (full replacement), `pipeline/tests/integration/test_run_cli_db.py` (new)

**Interfaces:**
- Consumes:
  - `SourceTracker` (Task 5)
  - `EnrichTargets`, `shortlist`, `run_enrichment` (Task 6)
  - `repo.load_source_states`, `repo.sweep_abandoned_runs`, `repo.record_source_health` (Task 2)
  - `fetch_daily_bars`, `screener`, `freshness_floor` (Plan 1)
- Produces:
  - `run.UNIVERSE_SOURCE`, `run.PRIMARY_PRICES`, `run.FALLBACK_PRICES` and `run.PRICE_STAGE`
  - `run.priority_order(held, watch, asset_type) -> list[str]`
  - `execute_run` (same signature)
  - The run summary gains `"shortlist"`, which is the number of stock symbols sent to enrichment.
  - `run.count_healthy` and `run.UNHEALTHY` are removed; they live on the tracker now.

- [ ] **Step 1: Add the shared price fakes**

Append to `pipeline/tests/fakes.py` (`Scope`, `Sequence`, `timedelta` and `date` are already imported there):
```python
FRESH_START = date(2026, 8, 5)  # 70 daily bars from here end 2026-10-13, fresh for a 2026-10-14 run


def fake_price_collectors(universe: Sequence[str] = ("AAA", "BBB", "CCC")) -> dict[str, FakeCollector]:
    """Universe, primary and fallback price fakes that return fresh 70-day histories."""
    return {
        "nasdaq_symbols": FakeCollector(
            "nasdaq_symbols",
            records_for=lambda _: [info(s) for s in universe],
            record_type=SymbolInfo,
            cadence=Cadence.DAILY,
            scope=Scope.UNIVERSE,
            freshness=timedelta(days=3),
        ),
        "alpaca_bars": FakeCollector(
            "alpaca_bars",
            records_for=lambda syms: [b for s in syms for b in history(s, 70, start=FRESH_START)],
        ),
        "yfinance_bars": FakeCollector(
            "yfinance_bars",
            core=False,
            best_effort=True,
            records_for=lambda syms: [
                b for s in syms for b in history(s, 70, source="yfinance", start=FRESH_START)
            ],
        ),
    }
```

- [ ] **Step 2: Write the failing tests**

`pipeline/tests/integration/test_run.py` (full replacement; it keeps every existing behaviour check and adds the new ones):
```python
from datetime import UTC, datetime

import httpx
import pytest

from advisor.collectors.base import PartialFetch, Scope
from advisor.collectors.cache import DiskCache
from advisor.models import AssetType, RunKind, RunStatus
from advisor.run import RunDeps, execute_run
from fakes import FRESH_START, FakeCollector, fake_price_collectors, history

NOW = datetime(2026, 10, 14, 12, 15, tzinfo=UTC)
UNIVERSE = ["AAA", "BBB", "CCC"]


def make_deps(db, tmp_path, *, universe=UNIVERSE, alpaca=None, universe_records=None, extra=None):
    collectors = fake_price_collectors(universe)
    if universe_records is not None:
        collectors["nasdaq_symbols"].records_for = universe_records
    if alpaca is not None:
        collectors["alpaca_bars"] = alpaca
    collectors.update(extra or {})
    return RunDeps(db, DiskCache(tmp_path), collectors)


def run_row(db, run_id):
    return db.execute("select * from runs where id = %s", (run_id,)).fetchone()


def health(db, run_id):
    rows = db.execute(
        "select source, status from source_health where run_id = %s order by source", (run_id,)
    ).fetchall()
    return [(r["source"], r["status"]) for r in rows]


def hold(db, symbol="OTCX"):
    db.execute(
        "insert into lots (symbol, asset_type, qty, price, bought_at)"
        " values (%s, 'stock', 10, 5, '2026-09-01')",
        (symbol,),
    )


def test_successful_run_is_published_with_summary(db, tmp_path):
    deps = make_deps(db, tmp_path)
    outcome = execute_run(deps, RunKind.PRE_OPEN, NOW, min_universe=3)

    assert outcome.status is RunStatus.SUCCESS
    row = run_row(db, outcome.run_id)
    assert row["published"] is True
    assert (row["sources_ok"], row["sources_total"]) == (3, 3)
    assert row["summary"] == {
        "universe": 3, "priced": 3, "passed_filters": 3, "priority": 0, "priority_unpriced": [],
        "fresh": 3, "fresh_since": "2026-10-12", "shortlist": 3,
    }
    assert deps.collectors["yfinance_bars"].calls == []
    assert health(db, outcome.run_id) == [("alpaca_bars", "ok"), ("nasdaq_symbols", "ok")]
    assert db.execute("select count(*) as n from symbols where active").fetchone()["n"] == 3


def test_holdings_are_priced_first_and_get_features(db, tmp_path):
    hold(db)
    db.execute("insert into watchlist (symbol, asset_type) values ('BTC', 'crypto')")
    deps = make_deps(db, tmp_path)
    outcome = execute_run(deps, RunKind.PRE_OPEN, NOW, min_universe=3)

    assert deps.collectors["alpaca_bars"].calls == [["OTCX"], ["AAA", "BBB", "CCC"]]
    assert health(db, outcome.run_id) == [("alpaca_bars", "ok"), ("nasdaq_symbols", "ok")]
    features = db.execute(
        "select symbol, features from features_live where run_id = %s", (outcome.run_id,)
    ).fetchall()
    assert [f["symbol"] for f in features] == ["OTCX"]
    assert features[0]["features"]["last_close"] == 10.0
    assert outcome.summary["priority"] == 1
    assert outcome.summary["priced"] == 4


def test_holdings_are_saved_even_when_a_later_stage_fails(db, tmp_path):
    hold(db)
    deps = make_deps(db, tmp_path, universe_records=lambda _: [object()])
    with pytest.raises(AttributeError):
        execute_run(deps, RunKind.PRE_OPEN, NOW, min_universe=1)
    assert db.execute("select symbol from features_live").fetchone()["symbol"] == "OTCX"
    row = db.execute("select * from runs").fetchone()
    assert (row["status"], row["published"]) == ("failed", False)
    assert row["summary"]["error"].startswith("AttributeError")


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


def test_partial_primary_prices_degrade_the_run_and_fall_back_for_the_rest(db, tmp_path):
    some = [b for s in ("AAA", "BBB") for b in history(s, 70, start=FRESH_START)]
    alpaca = FakeCollector("alpaca_bars", error=PartialFetch(some, "1 of 2 Alpaca requests failed"))
    deps = make_deps(db, tmp_path, alpaca=alpaca)
    outcome = execute_run(deps, RunKind.PRE_OPEN, NOW, min_universe=3)

    assert outcome.status is RunStatus.DEGRADED
    assert deps.collectors["yfinance_bars"].calls == [["CCC"]]
    assert health(db, outcome.run_id) == [
        ("alpaca_bars", "partial"), ("nasdaq_symbols", "ok"), ("yfinance_bars", "ok"),
    ]
    assert outcome.summary["priced"] == 3


def test_enrichment_collectors_get_priority_first_then_the_shortlist(db, tmp_path):
    hold(db)
    db.execute("insert into watchlist (symbol, asset_type) values ('BTC', 'crypto')")
    extra = {
        "news": FakeCollector("news", core=False),
        "macro": FakeCollector("macro", scope=Scope.MARKET),
        "coins": FakeCollector("coins", asset_types=frozenset({AssetType.CRYPTO})),
    }
    outcome = execute_run(make_deps(db, tmp_path, extra=extra), RunKind.PRE_OPEN, NOW, min_universe=3)

    assert outcome.status is RunStatus.SUCCESS
    assert extra["news"].calls == [["OTCX", "AAA", "BBB", "CCC"]]
    assert extra["macro"].calls == [[]]
    assert extra["coins"].calls == [["BTC"]]
    assert outcome.summary["shortlist"] == 4
    assert [s for s, _ in health(db, outcome.run_id)] == [
        "alpaca_bars", "coins", "macro", "nasdaq_symbols", "news",
    ]


def test_a_failing_core_enrichment_source_degrades_the_run(db, tmp_path):
    extra = {"filings": FakeCollector("filings", core=True, error=httpx.ConnectError("down"))}
    outcome = execute_run(make_deps(db, tmp_path, extra=extra), RunKind.PRE_OPEN, NOW, min_universe=3)
    assert outcome.status is RunStatus.DEGRADED
    assert ("filings", "failed") in health(db, outcome.run_id)


def test_truncated_universe_fails_the_run_and_stays_unpublished(db, tmp_path):
    db.execute(
        "insert into symbols (symbol, asset_type, name, exchange)"
        " values ('OLD', 'stock', 'Old Co', 'NYSE')"
    )
    extra = {"news": FakeCollector("news")}
    outcome = execute_run(
        make_deps(db, tmp_path, extra=extra), RunKind.PRE_OPEN, NOW, min_universe=1000
    )
    assert outcome.status is RunStatus.FAILED
    assert outcome.summary["failed_reason"] == ["universe too small (3 < 1000)"]
    assert run_row(db, outcome.run_id)["published"] is False
    old = db.execute("select active from symbols where symbol = 'OLD'").fetchone()
    assert old["active"] is True
    assert db.execute("select count(*) as n from symbols").fetchone()["n"] == 1
    assert extra["news"].calls == []  # a run that cannot publish spends no enrichment calls


def test_stale_prices_fail_the_run_and_flag_holding_features(db, tmp_path):
    hold(db)
    alpaca = FakeCollector(  # bars end 2026-08-09: two months behind a 2026-10-14 run
        "alpaca_bars", records_for=lambda syms: [b for s in syms for b in history(s, 70)]
    )
    outcome = execute_run(
        make_deps(db, tmp_path, alpaca=alpaca), RunKind.PRE_OPEN, NOW, min_universe=3
    )

    assert outcome.status is RunStatus.FAILED
    assert run_row(db, outcome.run_id)["published"] is False
    assert outcome.summary["failed_reason"] == ["too few fresh priced symbols (0 of 4)"]
    features = db.execute(
        "select features from features_live where run_id = %s and symbol = 'OTCX'",
        (outcome.run_id,),
    ).fetchone()["features"]
    assert features["stale"] is True


def test_unexpected_error_marks_run_failed_and_propagates(db, tmp_path):
    deps = make_deps(db, tmp_path, universe_records=lambda _: [object()])
    with pytest.raises(AttributeError):
        execute_run(deps, RunKind.PRE_OPEN, NOW, min_universe=1)
    row = db.execute("select * from runs").fetchone()
    assert row["status"] == "failed"
    assert row["published"] is False
    assert row["summary"]["error"].startswith("AttributeError")


def test_abandoned_runs_are_swept_when_a_run_starts(db, tmp_path):
    db.execute(
        "insert into runs (kind, et_date, started_at)"
        " values ('pre_close', '2026-10-13', '2026-10-14 09:00+00')"
    )
    execute_run(make_deps(db, tmp_path), RunKind.PRE_OPEN, NOW, min_universe=3)
    old = db.execute("select status from runs where kind = 'pre_close'").fetchone()
    assert old["status"] == "failed"
```

`pipeline/tests/integration/test_run_cli_db.py`:
```python
import os

import pytest

from advisor.run import main
from fakes import fake_price_collectors

NOW_ARG = ["--now", "2026-10-14T12:15:00+00:00"]  # 08:15 ET, a pre-open slot


@pytest.fixture
def cli_env(db, monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    monkeypatch.setenv("ALPACA_KEY_ID", "test")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "test")
    monkeypatch.setenv("ADVISOR_CACHE_DIR", str(tmp_path))
    db.execute(
        "insert into runs (kind, et_date, status, published)"
        " values ('pre_open', '2026-10-14', 'success', true)"
    )
    return db


def test_an_already_published_slot_is_skipped(cli_env, monkeypatch, capsys):
    monkeypatch.setattr(
        "advisor.run.build_registry", lambda settings, client: pytest.fail("must not collect")
    )
    assert main(NOW_ARG) == 0
    assert "already published" in capsys.readouterr().out


def test_force_kind_runs_anyway_and_a_failed_run_exits_1(cli_env, monkeypatch, capsys):
    monkeypatch.setattr(
        "advisor.run.build_registry", lambda settings, client: fake_price_collectors()
    )
    assert main(["--force-kind", "pre_open", *NOW_ARG]) == 1  # 3-symbol universe < 1000
    assert '"status": "failed"' in capsys.readouterr().out
    assert cli_env.execute("select count(*) as n from runs").fetchone()["n"] == 2
```

- [ ] **Step 3: Run them to verify they fail**

Run: `scripts/in-docker.sh uv run pytest tests/integration/test_run.py tests/integration/test_run_cli_db.py -v`
Expected: several failures:
- the alpaca call order is one merged call, not two phases;
- the `shortlist` summary key is missing;
- enrichment fakes are never called;
- the abandoned run is still `running`.

- [ ] **Step 4: Replace `execute_run` in `run.py`**

In `pipeline/src/advisor/run.py`:

Replace the imports block (everything from `import argparse` through `from advisor.store.db import connect`) with:
```python
import argparse
import contextlib
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
from advisor.collectors.tracker import SourceTracker
from advisor.config import Settings
from advisor.enrich import EnrichTargets, run_enrichment, shortlist
from advisor.models import ET, AssetRef, AssetType, RunKind, RunStatus, SymbolInfo
from advisor.prices import PriceFetch, fetch_daily_bars
from advisor.schedule import freshness_floor, missed_run_kind, resolve_run_kind
from advisor.store import repo
from advisor.store.db import connect
```

Replace the constants (`MIN_UNIVERSE` through `UNHEALTHY`) with:
```python
MIN_UNIVERSE = 1000  # fewer listed stocks than this means the symbol files were truncated
MIN_PRICED_FRACTION = 0.5
UNIVERSE_SOURCE = "nasdaq_symbols"
PRIMARY_PRICES = "alpaca_bars"
FALLBACK_PRICES = "yfinance_bars"
PRICE_STAGE = frozenset({UNIVERSE_SOURCE, PRIMARY_PRICES, FALLBACK_PRICES})
```

Delete the `count_healthy` function. Keep `RunDeps`, `RunOutcome` and `decide_status` unchanged.

Add after `decide_status`:
```python
def priority_order(held: set[AssetRef], watch: set[AssetRef], asset_type: AssetType) -> list[str]:
    """Holdings first, then watchlist-only symbols, each alphabetical (spec §7.2)."""
    held_symbols = sorted(ref.symbol for ref in held if ref.asset_type is asset_type)
    watch_only = sorted(
        {ref.symbol for ref in watch if ref.asset_type is asset_type} - set(held_symbols)
    )
    return held_symbols + watch_only
```

Replace `execute_run` with:
```python
def execute_run(
    deps: RunDeps, kind: RunKind, now_utc: datetime, *, min_universe: int = MIN_UNIVERSE
) -> RunOutcome:
    conn = deps.conn
    floor = freshness_floor(kind, now_utc)  # spec §10: older last bars count as missing
    repo.sweep_abandoned_runs(conn, now_utc)
    run_id = repo.create_run(conn, kind, now_utc.astimezone(ET).date())
    tracker = SourceTracker(
        deps.collectors, deps.cache, now_utc, repo.load_source_states(conn, deps.collectors)
    )

    def fetch_prices(symbols: Sequence[str]) -> PriceFetch:
        return fetch_daily_bars(
            symbols,
            primary_run=lambda s: tracker.run(PRIMARY_PRICES, s),
            fallback_run=lambda s: tracker.run(FALLBACK_PRICES, s),
        )

    def record_health() -> None:
        for result, failures in tracker.health_rows():
            repo.record_source_health(conn, run_id, result, failures, now_utc)

    try:
        held, watch = repo.load_held_symbols(conn), repo.load_watchlist(conn)
        priority = priority_order(held, watch, AssetType.STOCK)
        crypto = priority_order(held, watch, AssetType.CRYPTO)

        # Phase 1: holdings and watchlist are priced and saved before anything else can fail.
        bars = fetch_prices(priority).bars if priority else {}
        priority_rows = [screener.price_stats(s, bars[s]) for s in priority if s in bars]
        repo.write_features_live(
            conn,
            run_id,
            [
                (
                    AssetRef(r.symbol, AssetType.STOCK),
                    {**r.as_features(), "stale": not r.is_fresh(floor)},
                )
                for r in priority_rows
            ],
            now_utc,
        )

        # Phase 2: the rest of the market.
        universe: list[SymbolInfo] = list(tracker.run(UNIVERSE_SOURCE, []).records)
        universe_ok = len(universe) >= min_universe
        if universe_ok:
            repo.upsert_symbols(conn, universe)
        rest = sorted({record.symbol for record in universe} - set(priority))
        if rest:
            bars = {**fetch_prices(rest).bars, **bars}
        symbols = sorted(set(priority) | set(rest))

        passed = screener.hard_filter(bars, fresh_since=floor)
        fresh = sum(1 for history in bars.values() if history[-1].day >= floor)
        prices_ok = bool(symbols) and fresh >= MIN_PRICED_FRACTION * len(symbols)

        # Phase 3: enrichment, only for a run that can still publish.
        targets = EnrichTargets(stocks=shortlist(passed, priority), crypto=crypto)
        if universe_ok and prices_ok:
            run_enrichment(
                tracker,
                deps.collectors,
                [name for name in deps.collectors if name not in PRICE_STAGE],
                targets,
            )

        summary = {
            "universe": len(universe),
            "priced": len(bars),
            "passed_filters": len(passed),
            "priority": len(priority),
            "priority_unpriced": sorted(set(priority) - bars.keys()),
            "fresh": fresh,
            "fresh_since": floor.isoformat(),
            "shortlist": len(targets.stocks),
        }
        status = decide_status(
            tracker.merged(), deps.collectors, universe_ok=universe_ok, prices_ok=prices_ok
        )
        if status is RunStatus.FAILED:
            reasons = []
            if not universe_ok:
                reasons.append(f"universe too small ({len(universe)} < {min_universe})")
            if not prices_ok:
                reasons.append(f"too few fresh priced symbols ({fresh} of {len(symbols)})")
            summary["failed_reason"] = reasons
    except Exception as exc:
        with contextlib.suppress(Exception):  # never let bookkeeping hide the real error
            record_health()
        repo.finish_run(
            conn, run_id, RunStatus.FAILED,
            sources_ok=tracker.count_healthy(),
            sources_total=len(deps.collectors),
            summary={"error": f"{type(exc).__name__}: {exc}"[:500]},
        )
        raise

    record_health()
    repo.finish_run(
        conn, run_id, status,
        sources_ok=tracker.count_healthy(),
        sources_total=len(deps.collectors),
        summary=summary,
    )
    return RunOutcome(run_id, status, summary)
```

Leave `parse_args`, `main` and the `__main__` block as they are. `CollectorResult` and `CollectorStatus` are still used by `decide_status`, and `Collector` by `RunDeps`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `scripts/in-docker.sh uv run pytest tests/integration/test_run.py tests/integration/test_run_cli_db.py tests/unit/test_run_cli.py -v`
Expected: all pass.

Then run the full suite: `scripts/in-docker.sh uv run pytest -q`. Expected: all pass.

- [ ] **Step 6: Commit**

```bash
uv run ruff check --fix .
git add src/advisor/run.py tests/fakes.py tests/integration/test_run.py tests/integration/test_run_cli_db.py
git commit -m "feat: run holdings first, merge source health, and add the enrichment stage"
```
End the message with your `Co-Authored-By:` trailer.

---

### Task 8: Daily source health check, workflow updates, README

**Files:**
- Create: `pipeline/src/advisor/health.py`, `.github/workflows/health.yml`
- Modify: `.github/workflows/run.yml`, `.github/workflows/ci.yml`, `pipeline/scripts/in-docker.sh`, `README.md`
- Test: `pipeline/tests/unit/test_health.py`, `pipeline/tests/integration/test_health_cli.py`

**Interfaces:**
- Consumes:
  - `run_collector`, `next_failures`, `SourceState`
  - `repo.load_source_states`, `repo.record_source_health(..., context="health")`
  - `build_registry`, `Settings`, `connect`, `make_client`, `DiskCache`
- Produces:
  - `advisor.health.check_sources(collectors, cache, states, now) -> list[tuple[CollectorResult, int]]`
  - `advisor.health.main(argv=None) -> int`, which returns exit 1 when any core source fails its canary
  - the `health.yml` workflow (daily at 10:30 UTC, plus manual dispatch)

- [ ] **Step 1: Write the failing tests**

`pipeline/tests/unit/test_health.py`:
```python
from datetime import UTC, date, datetime

import httpx

from advisor.collectors.base import CollectorStatus
from advisor.collectors.cache import DiskCache
from advisor.collectors.runner import SourceState
from advisor.health import check_sources
from fakes import FakeCollector, bar

NOW = datetime(2026, 10, 10, 10, 30, tzinfo=UTC)


def test_check_sources_fetches_canaries_ignoring_the_breaker(tmp_path):
    good = FakeCollector(
        "good", canary=("AAPL",), records_for=lambda syms: [bar(s, date(2026, 10, 9), 1.0) for s in syms]
    )
    empty = FakeCollector("empty", canary=("AAPL",))
    broken = FakeCollector("broken", canary=("AAPL",), error=httpx.ConnectError("down"))
    states = {"good": SourceState(5, date(2026, 10, 10)), "empty": SourceState(1)}
    rows = dict(
        (r.name, (r, failures))
        for r, failures in check_sources(
            {"good": good, "empty": empty, "broken": broken}, DiskCache(tmp_path), states, NOW
        )
    )
    assert good.calls == [["AAPL"]]  # fetched although its breaker was open today
    assert rows["good"][0].status is CollectorStatus.OK and rows["good"][1] == 0
    assert rows["empty"][0].status is CollectorStatus.FAILED
    assert rows["empty"][0].error == "canary returned no records"
    assert rows["empty"][1] == 2
    assert rows["broken"][0].status is CollectorStatus.FAILED and rows["broken"][1] == 1
```

`pipeline/tests/integration/test_health_cli.py`:
```python
import os
from datetime import date

import httpx

from advisor.health import main
from fakes import FakeCollector, bar


def test_health_cli_records_rows_without_a_run_and_fails_on_a_core_source(db, monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    monkeypatch.setenv("ALPACA_KEY_ID", "test")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "test")
    monkeypatch.setenv("ADVISOR_CACHE_DIR", str(tmp_path))
    collectors = {
        "good": FakeCollector("good", canary=("AAPL",),
                              records_for=lambda s: [bar("AAPL", date(2026, 10, 9), 1.0)]),
        "bad": FakeCollector("bad", core=True, canary=("AAPL",), error=httpx.ConnectError("down")),
    }
    monkeypatch.setattr("advisor.health.build_registry", lambda settings, client: collectors)

    assert main([]) == 1
    rows = db.execute(
        "select source, status, run_id, context from source_health order by source"
    ).fetchall()
    assert [(r["source"], r["status"], r["run_id"], r["context"]) for r in rows] == [
        ("bad", "failed", None, "health"), ("good", "ok", None, "health"),
    ]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `scripts/in-docker.sh uv run pytest tests/unit/test_health.py tests/integration/test_health_cli.py -v`
Expected: `ModuleNotFoundError: No module named 'advisor.health'`.

- [ ] **Step 3: Implement `health.py`**

`pipeline/src/advisor/health.py`:
```python
"""Daily live check of every source (spec §11): fetch each collector's canary and record it.

Usage: python -m advisor.health
Exit 1 when a core source fails, so the GitHub job fails and the owner gets an email.
This check is also the daily retry for sources whose circuit breaker is open.
"""

import json
import sys
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime

from advisor.collectors.base import Collector, CollectorResult, CollectorStatus, make_client
from advisor.collectors.cache import DiskCache
from advisor.collectors.registry import build_registry
from advisor.collectors.runner import SourceState, next_failures, run_collector
from advisor.config import Settings
from advisor.store import repo
from advisor.store.db import connect


def check_sources(
    collectors: Mapping[str, Collector],
    cache: DiskCache,
    states: Mapping[str, SourceState],
    now: datetime,
) -> list[tuple[CollectorResult, int]]:
    """Fetch every collector's canary once, ignoring the breaker; an empty answer is a failure."""
    rows = []
    for name, collector in collectors.items():
        result = run_collector(
            collector, list(collector.canary), now, cache=cache, state=SourceState()
        )
        if result.status is CollectorStatus.OK and not result.records:
            result = replace(
                result, status=CollectorStatus.FAILED, error="canary returned no records"
            )
        rows.append((result, next_failures(states.get(name, SourceState()), result)))
    return rows


def main(argv: list[str] | None = None) -> int:
    now = datetime.now(UTC)
    settings = Settings.from_env()
    with connect(settings.database_url) as conn, make_client() as client:
        collectors = build_registry(settings, client)
        states = repo.load_source_states(conn, collectors)
        rows = check_sources(collectors, DiskCache(settings.cache_dir), states, now)
        for result, failures in rows:
            repo.record_source_health(conn, None, result, failures, now, context="health")
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


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `scripts/in-docker.sh uv run pytest tests/unit/test_health.py tests/integration/test_health_cli.py -v`
Expected: 2 passed.

- [ ] **Step 5: Workflows**

`.github/workflows/health.yml` (new):
```yaml
name: health

# Daily live check of every data source (spec §11). It also retries sources whose circuit
# breaker is open. A failing core source fails this job, so GitHub emails the owner.
on:
  schedule:
    - cron: "30 10 * * *"  # every day, before the pre-open run
  workflow_dispatch:

permissions:
  contents: read

concurrency:
  group: pipeline-run  # never overlaps a pipeline run (shared cache and database)
  cancel-in-progress: false

jobs:
  health:
    runs-on: ubuntu-latest
    timeout-minutes: 20
    defaults:
      run:
        working-directory: pipeline
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@d0cc045d04ccac9d8b7881df0226f9e82c39688e # v6.8.0
      - run: uv sync --locked --no-dev
      - uses: actions/cache/restore@v4
        with:
          path: pipeline/.cache
          key: advisor-cache-${{ github.run_id }}
          restore-keys: advisor-cache-
      - name: Check sources
        env:
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
          ALPACA_KEY_ID: ${{ secrets.ALPACA_KEY_ID }}
          ALPACA_SECRET_KEY: ${{ secrets.ALPACA_SECRET_KEY }}
          ADVISOR_CACHE_DIR: .cache
        run: uv run python -m advisor.health
      - uses: actions/cache/save@v4
        if: always()
        with:
          path: pipeline/.cache
          key: advisor-cache-${{ github.run_id }}
```

In `.github/workflows/run.yml`, replace the single `actions/cache@v4` step with a restore step in the same position, plus a save step at the end of the job, after "Run pipeline":
```yaml
      - uses: actions/cache/restore@v4
        with:
          path: pipeline/.cache
          key: advisor-cache-${{ github.run_id }}
          restore-keys: advisor-cache-
```
```yaml
      - uses: actions/cache/save@v4
        if: always()  # keep what a failed run fetched, so the retry doesn't refetch it all
        with:
          path: pipeline/.cache
          key: advisor-cache-${{ github.run_id }}
```

In `.github/workflows/ci.yml`, replace the `on:` block with the following. A push already triggers CI, so drop `pull_request` to stop double runs on PR branches.
```yaml
on:
  push:
  workflow_dispatch:
```

In `pipeline/scripts/in-docker.sh`, change the forwarding line to:
```
  -e DATABASE_URL -e ADMIN_DATABASE_URL -e ALPACA_KEY_ID -e ALPACA_SECRET_KEY -e ADVISOR_CACHE_DIR \
```

Validate the YAML (from `pipeline/`):
`uv run --with pyyaml python -c "import yaml,sys; [yaml.safe_load(open(p, encoding='utf-8')) for p in sys.argv[1:]]; print('ok')" ../.github/workflows/ci.yml ../.github/workflows/run.yml ../.github/workflows/health.yml`
Expected: `ok`.

- [ ] **Step 6: README**

Replace these sections of `README.md`: "Layout", "Deployment (free tiers)" and "Manual run". Keep the title, intro and "Local development" exactly as they are.

````markdown
## Layout

- `pipeline/` — Python 3.12 data pipeline (uv)
- `supabase/migrations/` — Postgres schema, row-level security, and roles (append-only)
- `.github/workflows/` — `ci.yml` (tests on push), `run.yml` (scheduled pipeline runs),
  `health.yml` (daily live check of every data source)

## Deployment (free tiers)

1. **Supabase**: create a project. Under Connect → **Session pooler**, copy the URI for the
   `postgres` user (GitHub runners need the IPv4 pooler). Percent-encode special characters in
   the password (for example `@` → `%40`). This is your **admin** URL: keep it local and never put
   it in GitHub.
2. **Schema**: from `pipeline/`, run
   `ADMIN_DATABASE_URL='<admin url>' scripts/in-docker.sh uv run python -m advisor.store.migrate`.
   If you already pasted `0001`/`0002` into the SQL editor by hand, run it once with
   `--baseline 0002_rls.sql` added.
3. **Auth**: under Authentication → Sign In / Providers → Email, turn off "Allow new users to sign
   up". Add your user under Authentication → Users, then in the SQL editor run:
   `insert into app_config (id, owner_id) values (1, '<your user uuid>');`
4. **Pipeline login** (least privilege: no DDL, cannot edit your holdings). In the SQL editor:
   ```sql
   create role advisor_pipeline login password '<generate a long random password>';
   grant pipeline_rw to advisor_pipeline;
   ```
   The pipeline's `DATABASE_URL` is the session-pooler URI with the user
   `advisor_pipeline.<project-ref>` and that password. If the pooler rejects the custom role,
   resolve that first: the `postgres` user has full DDL rights and should not run the pipeline.
5. **Alpaca**: create a free account and generate API keys (paper-trading keys work for market
   data).
6. **GitHub** (private repo): Settings → Secrets and variables → Actions. Add `DATABASE_URL`
   (the pipeline login from step 4), `ALPACA_KEY_ID`, `ALPACA_SECRET_KEY`.
7. Actions → `health` → Run workflow, then `run` → Run workflow → `pre_open`.

## Manual run

From `pipeline/`, with secrets in a git-ignored `pipeline/.env.local`
(`DATABASE_URL=...`, `ALPACA_KEY_ID=...`, `ALPACA_SECRET_KEY=...`):

```bash
set -a; . ./.env.local; set +a
scripts/in-docker.sh uv run python -m advisor.health                       # check every source
scripts/in-docker.sh uv run python -m advisor.run --force-kind pre_open    # one pipeline run
```
````

- [ ] **Step 7: Full verification**

Run: `uv run ruff check . && scripts/in-docker.sh uv run pytest -q`
Expected: no lint errors and every test passing. Report the exact count.

- [ ] **Step 8: Commit**

```bash
git add src/advisor/health.py tests/unit/test_health.py tests/integration/test_health_cli.py ../.github/workflows ../README.md scripts/in-docker.sh
git commit -m "feat: add daily source health check, keep cache on failed runs, document pipeline role"
```
End the message with your `Co-Authored-By:` trailer.
