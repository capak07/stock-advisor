# Plan 5c: Trade List, File Import, Ticker Detail and Source Health — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The rest of the dashboard that today's data supports.
- My Portfolio gains a trade list with Delete and imports a broker's CSV.
- Every symbol gets a Ticker page with its price history, the owner's position, two days of news and the sources that cover it.
- Source health shows every source's latest result, its daily check and the database's size.
- Held coins are charted back to their first buy.

**Architecture:**
- **The pipeline** (Tasks 1 and 2).
  - Each run and each daily check writes its collector registry to a new `sources` table, which migration 0007 adds with an owner-only `database_size()` function.
  - The history stage pages Coinbase's older daily candles for coins ever bought.
- **The dashboard** (Tasks 3 to 7) follows Plan 5b's patterns:
  - server components read Supabase as the owner;
  - server actions write;
  - pure TypeScript in `web/lib/` does the maths and is unit-tested;
  - Playwright tests run against the local Supabase stack.
- **No new dependencies.** The mockups' `ticker_1.html`, `sources_1.html` and the import drawer of `portfolio_1.html` give the look; their `<style>` blocks move into `web/app/styles/pages.css`.

**Tech Stack:**
- Pipeline: Python 3.12, psycopg 3, httpx.
- Dashboard: Next.js 16.3.8, React 19.2.8, TypeScript 5.9.3, `@supabase/ssr` 0.12.7, lucide-react 1.50.0.
- Tests: Vitest 5.0.3, Playwright 1.63.0, Supabase CLI 2.119.0.
- Every version is unchanged from Plan 5b.

**Spec:** `docs/superpowers/specs/2026-10-09-stock-advisor-design.md` (rev 2):
- §7.1 Entering holdings (the file import);
- §8 Data Model;
- §9 Dashboard (Ticker Detail, Source Health).

Also read `docs/superpowers/deferred.md`, "Plans 4 and 5".

**Prototype:** every file below was built and tested on branch `plan-5c-proto` (2026-10-18):
- 666 pipeline tests;
- 111 unit tests and 41 browser tests;
- lint, typecheck and ruff clean.

Screenshots of each new page were compared with the mockups at 1360 px and 390 px. The plan transcribes those files.

**Deferred to the plans after the model (Plans 3 and 4):**
- Today's Picks, Track record and the watchlist's verdict columns;
- the Ticker page's forecast cone, top factors, catalysts and past picks (an empty card stands in their place);
- the status bar's missed-slot notice and next run time.

## Global Constraints

- **No new dependencies.** `web/package.json` and `pipeline/pyproject.toml` don't change.
- **Migrations are append-only.** This plan adds `supabase/migrations/0007_source_registry.sql`; earlier migrations are never edited.
- **Data sources stay keyless.** The coin backfill uses Coinbase's public candles endpoint, which the `coinbase_candles` collector already uses.
- **Values are shown in CAD.** A coin's chart is Coinbase's USD close at that day's Bank of Canada rate, as the portfolio values coins (spec §7.4). A stock's chart is in its own currency, the currency its price is quoted in.
- **One owner.** The dashboard writes only `watchlist`, `lots`, `sells` and the `settings` row. Deleting a trade is a delete on `lots` or `sells`, which row-level security limits to the owner.
- **Supabase is called from the server only.** No `NEXT_PUBLIC_*` variables.
- **News text is untrusted.** Titles, outlets and links come from third-party feeds. They are rendered as text, never as HTML, and only `http:` and `https:` links become anchors (deferred.md, "News text is untrusted").
- **Design:** the Ledger mockups.
  - No blue or indigo; light and dark.
  - Every page fits 390 px without horizontal scrolling.
- **Test accounts** exist only on the local stack: `owner@example.com` and `visitor@example.com`. Never put a real email in code, tests or docs.
- **Where commands run:**
  - Pipeline tests run only in Docker: `pipeline/scripts/in-docker.sh uv run pytest -q` and `pipeline/scripts/in-docker.sh uv run ruff check .`, from `pipeline/`.
  - Web commands run from `web/` on the host. Browser tests need Docker Desktop running and the local stack started with `npm run db:start`.
  - After Task 1 adds migration 0007, run `npm run db:reset` once so the local stack has it.
- **Commits:** run `git commit` in a command of its own. A plugin hook mistakes any `-n` flag in the same command (`grep -n`, `sed -n`) for `--no-verify`. Never skip hooks. Every commit message ends with the `Co-Authored-By:` trailer.

## Review Focus

1. **A coin Coinbase doesn't list, or a Coinbase outage.** The run must still publish, name the coin in `summary.history.backfill_missing` or record `coin_backfill_error`, and try again next run. Covered by Task 2, `test_a_coin_coinbase_doesnt_list_is_named_and_the_run_publishes` and `test_a_coin_coinbase_doesnt_list_has_no_backfill`.
2. **Deleting a buy that a later sell needs.** The owner is warned before the delete, because the sell would then exceed what was held. Keep leaves the buy. Covered by Task 3, `trade-list.spec.ts` "deleting a buy that a later sell needs says so first, and Keep keeps it".
3. **Importing the same broker file twice, or a file that oversells.** The second import adds nothing. A file whose sells exceed what's held is refused whole: nothing is half-imported. Covered by Task 5, `import.spec.ts` "importing the same file again adds nothing" and "a sell of more than is held refuses the whole file".
4. **A headline whose link is `javascript:…`.** It shows as plain text, never as a link. Covered by Task 7, `ticker.spec.ts`: the held stock's page shows "RBC names a new CFO" with no link.
5. **The first deploy, before a run has written `sources`, and a phone.** Source health says "No sources yet" instead of failing. The Ticker and Source health pages fit 390 px. Covered by:
   - Task 6, `sources.spec.ts` "the status bar's sources pill opens Source health, which waits for the first run";
   - Task 7, `navigation.spec.ts` "no page is wider than the screen".

## Files

| File | Task | What it is |
|---|---|---|
| `supabase/migrations/0007_source_registry.sql` | 1 | `sources`, `source_last_ok`, `database_size()`, an index on `source_health.run_id` |
| `pipeline/src/advisor/store/repo.py`, `run.py`, `health.py` + tests | 1 | `repo.write_sources`, called by each run and each daily check |
| `pipeline/src/advisor/history.py` + tests | 2 | The coin backfill from Coinbase |
| `web/lib/portfolio/{types,trade-list}.ts`, `lib/data/portfolio.ts`, `app/(app)/{trades.ts,page.tsx}`, `components/portfolio/TradeList.tsx`, `e2e/trade-list.spec.ts` | 3 | The trade list with Delete |
| `web/lib/import/{csv,rows}.ts` + tests | 4 | Reading a broker's CSV into trades |
| `web/app/(app)/import.ts`, `components/portfolio/{ImportDrawer,TradeForms}.tsx`, `e2e/import.spec.ts` | 5 | The import drawer and its server actions |
| `web/lib/{sources,dates}.ts`, `lib/data/{sources,runs}.ts`, `app/(app)/sources/page.tsx`, `components/sources/SourceTable.tsx`, `components/shell/{nav.ts,Shell.tsx}`, `e2e/{db.ts,sources.spec.ts,navigation.spec.ts}` | 6 | Source health |
| `web/lib/ticker.ts`, `lib/data/{ticker,portfolio}.ts`, `app/(app)/ticker/[symbol]/page.tsx`, `components/ticker/*`, `components/shell/{FindTicker,Navigation,Shell}.tsx`, links in `Cards.tsx` and `Watchlist.tsx`, `e2e/{db.ts,ticker.spec.ts,navigation.spec.ts}` | 7 | The Ticker page and symbol search |
| `web/app/styles/pages.css` | 3, 5, 6, 7 | One section per page, appended by each task |
| `docs/superpowers/deferred.md`, `web/README.md` | 8 | Docs |

---
### Task 1: Write the source registry and the database size for Source health

**Files:**
- Create: `supabase/migrations/0007_source_registry.sql`
- Modify: `pipeline/src/advisor/store/repo.py`, `pipeline/src/advisor/run.py`, `pipeline/src/advisor/health.py`
- Test: `pipeline/tests/integration/test_schema.py`, `test_repo.py`, `test_run.py`, `test_health_cli.py`

**Interfaces:**
- Consumes:
  - The `Collector` protocol in `advisor/collectors/base.py`: `name`, `category`, `core`, `cadence`, `asset_types`, `markets`.
  - `public.is_owner()` and the `pipeline_rw` role (migrations 0002 and 0003).
- Produces (Task 6 reads them):
  - Table `sources`:
    - `name` (primary key), `category`, `core`, `cadence`;
    - `asset_types text[]` (`stock`, `crypto`);
    - `markets text[]` (`US`, `TSX`; empty for a coin-only source);
    - `updated_at`.
    - The owner reads it; only the pipeline writes it.
  - View `source_last_ok (source, attempted_at)`: each source's newest `ok` or `partial` row. It reads with the reader's rights, so only the owner sees rows.
  - Function `public.database_size() returns bigint`: the database's bytes for the owner, null for anyone else, not callable by `anon`.
  - Index `source_health_by_run` on `source_health (run_id)`.
  - `repo.write_sources(conn, collectors: Mapping[str, Collector]) -> None`: upserts every collector and deletes the rows of collectors that left the registry, in one transaction. `execute_run` calls it after `create_run`; the daily check calls it after `build_registry`.

- [ ] **Step 1: Write the failing tests**

In `pipeline/tests/integration/test_schema.py`, replace:

```python
import uuid
from contextlib import contextmanager
```

with:

```python
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
```

Append to `pipeline/tests/integration/test_schema.py`, after two blank lines:

```python
def test_the_owner_reads_sources_and_only_the_pipeline_writes_them(owned_db):
    owned_db.execute(
        "insert into sources (name, category, core, cadence, asset_types, markets)"
        " values ('fred', 'macro', true, 'daily', '{stock}', '{US,TSX}')"
    )
    with acting_as(owned_db, "authenticated", OWNER):
        assert [r["name"] for r in owned_db.execute("select name from sources").fetchall()] == ["fred"]
        assert owned_db.execute("update sources set core = false").rowcount == 0
        assert owned_db.execute("delete from sources").rowcount == 0
    with acting_as(owned_db, "authenticated", STRANGER):
        assert owned_db.execute("select * from sources").fetchall() == []
    with acting_as(owned_db, "pipeline_rw"):
        assert owned_db.execute("update sources set core = false").rowcount == 1


@pytest.mark.parametrize(
    ("category", "cadence", "asset_types", "markets"),
    [("weather", "daily", "{stock}", "{US}"), ("macro", "hourly", "{stock}", "{US}"),
     ("macro", "daily", "{}", "{US}"), ("macro", "daily", "{bond}", "{US}"),
     ("macro", "daily", "{stock}", "{NYSE}")],
)
def test_malformed_sources_are_rejected(db, category, cadence, asset_types, markets):
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(
            "insert into sources (name, category, core, cadence, asset_types, markets)"
            " values ('x', %s, true, %s, %s, %s)",
            (category, cadence, asset_types, markets),
        )


def test_the_owner_learns_each_sources_last_good_answer(owned_db):
    for source, status, at in [
        ("fred", "partial", "2026-10-15T19:00Z"), ("fred", "failed", "2026-10-16T19:00Z"),
        ("fred", "ok", "2026-10-14T19:00Z"), ("sec_8k", "stale", "2026-10-16T19:00Z"),
    ]:
        owned_db.execute(
            "insert into source_health (source, status, latency_ms, records, consecutive_failures,"
            " attempted_at, context) values (%s, %s, 1, 1, 0, %s, 'health')",
            (source, status, at),
        )
    last_ok = "select source, attempted_at from source_last_ok"
    with acting_as(owned_db, "authenticated", OWNER):
        assert [tuple(r.values()) for r in owned_db.execute(last_ok).fetchall()] == [
            ("fred", datetime(2026, 10, 15, 19, tzinfo=UTC)),
        ]  # a stale answer served old values, so it isn't a good one
    with acting_as(owned_db, "authenticated", STRANGER):
        assert owned_db.execute(last_ok).fetchall() == []


def test_only_the_owner_learns_the_database_size(owned_db):
    size = "select public.database_size() as size"
    with acting_as(owned_db, "authenticated", OWNER):
        assert owned_db.execute(size).fetchone()["size"] > 0
    with acting_as(owned_db, "authenticated", STRANGER):
        assert owned_db.execute(size).fetchone()["size"] is None
    with acting_as(owned_db, "anon"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            owned_db.execute(size)
```

In `pipeline/tests/integration/test_repo.py`, replace:

```python
from advisor.collectors.base import CollectorResult, CollectorStatus
```

with:

```python
from advisor.collectors.base import Cadence, Category, CollectorResult, CollectorStatus
```

In `pipeline/tests/integration/test_repo.py`, replace:

```python
from fakes import info
```

with:

```python
from fakes import FakeCollector, info
```

Append to `pipeline/tests/integration/test_repo.py`, after two blank lines:

```python
def test_sources_mirror_the_registry(db):
    repo.write_sources(db, {
        "fred": FakeCollector("fred", core=True, category=Category.MACRO, cadence=Cadence.DAILY),
        "gone": FakeCollector("gone"),
    })
    repo.write_sources(db, {
        "fred": FakeCollector("fred", core=False, category=Category.MACRO, cadence=Cadence.DAILY),
        "coins": FakeCollector("coins", asset_types=frozenset({AssetType.CRYPTO}), markets=frozenset()),
        "both": FakeCollector(
            "both", asset_types=frozenset({AssetType.STOCK, AssetType.CRYPTO}), markets=frozenset({Market.US})
        ),
    })
    rows = db.execute(
        "select name, category, core, cadence, asset_types, markets from sources order by name"
    ).fetchall()
    assert [tuple(r.values()) for r in rows] == [
        ("both", "prices", True, "per_run", ["crypto", "stock"], ["US"]),
        ("coins", "prices", True, "per_run", ["crypto"], []),
        ("fred", "macro", False, "daily", ["stock"], ["TSX", "US"]),
    ]  # "gone" left the registry, so it left the table
```

Append to `pipeline/tests/integration/test_run.py`, after two blank lines:

```python
def test_a_run_writes_the_registry_to_sources(db, tmp_path):
    deps = make_deps(db, tmp_path)
    execute_run(deps, RunKind.PRE_OPEN, NOW, min_universe=SMALL)
    names = [r["name"] for r in db.execute("select name from sources order by name").fetchall()]
    assert names == sorted(deps.collectors)
```

In `pipeline/tests/integration/test_health_cli.py`, replace:

```python
    assert [(r["source"], r["status"], r["run_id"], r["context"]) for r in rows] == [
        ("bad", "failed", None, "health"), ("good", "ok", None, "health"),
    ]
```

with:

```python
    assert [(r["source"], r["status"], r["run_id"], r["context"]) for r in rows] == [
        ("bad", "failed", None, "health"), ("good", "ok", None, "health"),
    ]
    # The daily check also writes the registry, so the dashboard lists every source.
    names = [r["name"] for r in db.execute("select name from sources order by name").fetchall()]
    assert names == ["bad", "good"]
```

- [ ] **Step 2: Run them and see them fail**

Run (from `pipeline/`): `scripts/in-docker.sh uv run pytest -q tests/integration/test_schema.py tests/integration/test_repo.py tests/integration/test_run.py tests/integration/test_health_cli.py`
Expected: `11 failed, 109 passed`. The `sources` tests fail with `psycopg.errors.UndefinedTable` (no `sources` table or `source_last_ok` view yet), `test_only_the_owner_learns_the_database_size` with `psycopg.errors.UndefinedFunction`, and `test_sources_mirror_the_registry` with `AttributeError: module 'advisor.store.repo' has no attribute 'write_sources'`.

- [ ] **Step 3: Write the migration**

`supabase/migrations/0007_source_registry.sql`:

```sql
-- Plan 5c: what the dashboard's Source health page needs.
-- Each run and each daily health check writes the registry's collectors here, so the page shows
-- every source with its category, whether it's core (a core failure degrades the run), its cadence
-- and the assets and stock markets it covers. A source that leaves the registry leaves this table.
create table sources (
  name text primary key,
  category text not null
    check (category in ('prices', 'fundamentals', 'options', 'macro', 'news', 'social', 'catalysts', 'onchain')),
  core boolean not null,
  cadence text not null check (cadence in ('per_run', 'daily', 'weekly')),
  asset_types text[] not null check (asset_types <@ array['stock', 'crypto']::text[] and cardinality(asset_types) > 0),
  markets text[] not null check (markets <@ array['US', 'TSX']::text[]),  -- empty for coin-only sources
  updated_at timestamptz not null default now()
);

alter table sources enable row level security;
create policy owner_read on sources for select to authenticated using ((select public.is_owner()));
create policy pipeline_write on sources for all to pipeline_rw using (true) with check (true);
grant select, insert, update, delete on sources to pipeline_rw;

-- The Source health page reads a run's rows.
create index source_health_by_run on source_health (run_id);

-- Each source's last good answer (ok or partial), in a run or a daily check. The view reads with
-- the reader's rights, so source_health's policy applies: only the owner sees rows.
create view source_last_ok with (security_invoker = true) as
  select source, max(attempted_at) as attempted_at from source_health
  where status in ('ok', 'partial') group by source;

-- The database's size, to compare with the free tier's 500 MB; null for anyone but the owner.
create or replace function public.database_size() returns bigint
language sql stable security definer set search_path = public
as $$
  select case when public.is_owner() then pg_database_size(current_database()) end;
$$;
revoke execute on function public.database_size() from public, anon;
grant execute on function public.database_size() to authenticated;
```

- [ ] **Step 4: Write the registry to `sources` from each run and each daily check**

In `pipeline/src/advisor/store/repo.py`, replace:

```python
from collections.abc import Iterable, Sequence
```

with:

```python
from collections.abc import Iterable, Mapping, Sequence
```

In `pipeline/src/advisor/store/repo.py`, replace:

```python
from advisor.collectors.base import CollectorResult
```

with:

```python
from advisor.collectors.base import Collector, CollectorResult
```

In `pipeline/src/advisor/store/repo.py`, replace:

```python
def record_source_health(
```

with:

```python
def write_sources(conn: psycopg.Connection, collectors: Mapping[str, Collector]) -> None:
    """The registry's collectors, for the dashboard's Source health page (Plan 5c).

    A source that left the registry is removed, so the page lists what the pipeline runs.
    """
    rows = [
        (
            c.name, c.category.value, c.core, c.cadence.value,
            sorted(t.value for t in c.asset_types), sorted(m.value for m in c.markets),
        )
        for c in collectors.values()
    ]
    with conn.transaction():
        with conn.cursor() as cur:
            cur.executemany(
                "insert into sources (name, category, core, cadence, asset_types, markets, updated_at)"
                " values (%s, %s, %s, %s, %s, %s, now())"
                " on conflict (name) do update set category = excluded.category,"
                " core = excluded.core, cadence = excluded.cadence, asset_types = excluded.asset_types,"
                " markets = excluded.markets, updated_at = now()",
                rows,
            )
        conn.execute("delete from sources where not (name = any(%s))", ([r[0] for r in rows],))


def record_source_health(
```

In `pipeline/src/advisor/run.py`, replace:

```python
    run_id = repo.create_run(conn, kind, now_utc.astimezone(ET).date())
```

with:

```python
    run_id = repo.create_run(conn, kind, now_utc.astimezone(ET).date())
    repo.write_sources(conn, deps.collectors)  # what the dashboard's Source health page lists
```

In `pipeline/src/advisor/health.py`, replace:

```python
        collectors = build_registry(settings, client)
```

with:

```python
        collectors = build_registry(settings, client)
        repo.write_sources(conn, collectors)  # what the dashboard's Source health page lists
```

- [ ] **Step 5: Run the tests**

Run: `scripts/in-docker.sh uv run pytest -q tests/integration/test_schema.py tests/integration/test_repo.py tests/integration/test_run.py tests/integration/test_health_cli.py`
Expected: `120 passed`.

Run: `scripts/in-docker.sh uv run pytest -q`, then `scripts/in-docker.sh uv run ruff check .`
Expected: `661 passed` (Plan 5b's 651 and these 10), then `All checks passed!`.

- [ ] **Step 6: Give the local Supabase stack the new migration**

Run (from `web/`, with Docker Desktop running): `npm run db:start`, then `npm run db:reset`
Expected: `Finished supabase db reset on branch …`. The reset wipes the local data; the next `npm run e2e` creates the test users again.

- [ ] **Step 7: Commit**

```bash
git add supabase/migrations/0007_source_registry.sql pipeline/src/advisor/store/repo.py pipeline/src/advisor/run.py pipeline/src/advisor/health.py pipeline/tests/integration/test_schema.py pipeline/tests/integration/test_repo.py pipeline/tests/integration/test_run.py pipeline/tests/integration/test_health_cli.py
git commit -m "feat: write the source registry and the database size for Source health"
```

---

### Task 2: Backfill held coins from Coinbase, a year back or to the first buy

**Files:**
- Modify: `pipeline/src/advisor/history.py`
- Test: `pipeline/tests/unit/test_history.py`, `pipeline/tests/integration/test_run.py`

**Interfaces:**
- Consumes:
  - From `coinbase_candles`: `CANDLES_URL`, `ONE_DAY`, `parse_candles(symbol, rows, as_of)`.
  - From `coins`: `listed_as(symbol)`.
  - From `repo`: `earliest_closes(conn, refs)`.
  - Already in `history.py`: `store_closes(conn, closes)`, `HISTORY` (a year), `SLACK`, and `record()`'s `buys` (first buy per asset) and `http`.
- Produces:
  - `COIN_WINDOW = timedelta(days=300)`.
  - `coin_backfill_starts(today, first_buys, earliest) -> dict[AssetRef, date]`: for each coin ever bought, the earlier of a year ago and its first buy. A coin whose stored closes already reach that day, within `SLACK`, is left out.
  - `fetch_coin_closes(client, ref, start, end) -> list[DailyClose]`: Coinbase's daily USD closes in [start, end), 300 days a request; `[]` when Coinbase answers 404.
  - `record()`'s summary: coins join `backfilled` and `backfill_missing`, and an exception lands in `coin_backfill_error` without failing the run.

- [ ] **Step 1: Write the failing tests**

In `pipeline/tests/unit/test_history.py`, replace:

```python
from datetime import date, timedelta
```

with:

```python
from datetime import UTC, date, datetime, timedelta
```

In `pipeline/tests/unit/test_history.py`, replace:

```python
    closes_from_bars,
    currency_of,
    download_closes,
    fetch_usd_cad,
```

with:

```python
    closes_from_bars,
    coin_backfill_starts,
    currency_of,
    download_closes,
    fetch_coin_closes,
    fetch_usd_cad,
```

Append to `pipeline/tests/unit/test_history.py`, after two blank lines:

```python
def test_coins_ever_bought_reach_back_a_year_or_to_their_first_buy():
    eth = AssetRef("ETH", AssetType.CRYPTO)
    starts = coin_backfill_starts(
        TODAY,
        {BTC: date(2026, 9, 1), eth: date(2024, 3, 4), AAPL: date(2024, 1, 2)},
        {BTC: date(2025, 12, 28), eth: date(2024, 3, 6)},  # ETH's stored closes reach its first buy
    )
    assert starts == {BTC: date(2025, 10, 14)}  # stocks are Yahoo's backfill, not this one


def candle_rows(start: date, stop: date, close: float) -> list[list[float]]:
    """Coinbase's answer: [time, low, high, open, close, volume], newest first."""
    days = [start + timedelta(days=i) for i in range((stop - start).days)]
    stamp = lambda day: datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp()  # noqa: E731
    return [[stamp(d), close, close, close, close, 1.0] for d in reversed(days)]


def test_the_coin_backfill_asks_coinbase_300_days_at_a_time():
    asked = []

    def handler(request):
        start = date.fromisoformat(request.url.params["start"][:10])
        stop = date.fromisoformat(request.url.params["end"][:10])
        asked.append((request.url.path, start, stop))
        return httpx.Response(200, json=candle_rows(start, stop, 60000.0))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        closes = fetch_coin_closes(client, BTC, date(2025, 1, 1), date(2026, 1, 15))
    assert asked == [
        ("/products/BTC-USD/candles", date(2025, 1, 1), date(2025, 10, 28)),
        ("/products/BTC-USD/candles", date(2025, 10, 28), date(2026, 1, 15)),
    ]
    assert len(closes) == (date(2026, 1, 15) - date(2025, 1, 1)).days
    assert (closes[0].day, closes[-1].day) == (date(2025, 1, 1), date(2026, 1, 14))
    assert {(c.ref, c.currency) for c in closes} == {(BTC, "USD")}


def test_a_coin_coinbase_doesnt_list_has_no_backfill():
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(404))) as client:
        assert fetch_coin_closes(client, AssetRef("XYZ", AssetType.CRYPTO), date(2025, 1, 1), TODAY) == []
```

Append to `pipeline/tests/integration/test_run.py`, after two blank lines:

```python
def coinbase(asked, *, listed=True):
    """A Coinbase that answers each candle request with a close of 60,000 for every day asked."""

    def handler(request):
        if request.url.host != "api.exchange.coinbase.com":
            return httpx.Response(404)  # the Bank of Canada isn't under test here
        start = date.fromisoformat(request.url.params["start"][:10])
        stop = date.fromisoformat(request.url.params["end"][:10])
        asked.append((start, stop))
        if not listed:
            return httpx.Response(404)
        days = [start + timedelta(days=i) for i in range((stop - start).days)]
        stamp = lambda d: datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp()  # noqa: E731
        return httpx.Response(200, json=[[stamp(d), 6e4, 6e4, 6e4, 6e4, 1.0] for d in reversed(days)])

    return httpx.MockTransport(handler)


def test_a_held_coin_is_backfilled_from_coinbase_to_a_year_back(db, tmp_path):
    hold_crypto(db)  # bought 2026-09-01; the run's own candles start 2026-09-14
    asked = []
    with httpx.Client(transport=coinbase(asked)) as client:
        deps = dataclasses.replace(make_deps(db, tmp_path, extra=crypto_sources()), http=client)
        outcome = execute_run(deps, RunKind.PRE_OPEN, NOW, min_universe=SMALL)

    assert asked == [(date(2025, 10, 14), date(2026, 8, 10)), (date(2026, 8, 10), date(2026, 9, 14))]
    assert outcome.summary["history"]["backfilled"] == ["BTC"]
    row = db.execute(
        "select min(day) as first, count(*) as n from daily_closes where symbol = 'BTC' and asset_type = 'crypto'"
    ).fetchone()
    assert (row["first"], row["n"]) == (date(2025, 10, 14), 335 + 30)


def test_a_coin_coinbase_doesnt_list_is_named_and_the_run_publishes(db, tmp_path):
    hold_crypto(db)
    asked = []
    with httpx.Client(transport=coinbase(asked, listed=False)) as client:
        deps = dataclasses.replace(make_deps(db, tmp_path, extra=crypto_sources()), http=client)
        outcome = execute_run(deps, RunKind.PRE_OPEN, NOW, min_universe=SMALL)

    assert outcome.status is RunStatus.SUCCESS
    assert outcome.summary["history"]["backfill_missing"] == ["BTC"]
```

- [ ] **Step 2: Run them and see them fail**

Run: `scripts/in-docker.sh uv run pytest -q tests/unit/test_history.py`
Expected: `1 error during collection`: `ImportError: cannot import name 'coin_backfill_starts' from 'advisor.history'`.

Run: `scripts/in-docker.sh uv run pytest -q tests/integration/test_run.py`
Expected: `2 failed, 46 passed`. The held coin's test fails on `assert [] == [(…)]` (Coinbase was never asked), the unlisted coin's on `KeyError: 'backfill_missing'`.

- [ ] **Step 3: Write the coin backfill**

In `pipeline/src/advisor/history.py`, replace:

```python
  it stays short, so the next run asks again. Coins need no backfill: every run already fetches
  290 days of candles.
```

with:

```python
  it stays short, so the next run asks again.
- Every run fetches 290 days of a coin's candles. A coin ever bought reaches back a year, or to
  its first buy, through Coinbase's older candles, 300 days a request (Plan 5c).
```

In `pipeline/src/advisor/history.py`, replace:

```python
from datetime import date, timedelta
```

with:

```python
from datetime import UTC, date, datetime, time, timedelta
```

In `pipeline/src/advisor/history.py`, replace:

```python
from advisor.collectors.boc_valet import VALET_URL, parse_observations
```

with:

```python
from advisor.collectors.boc_valet import VALET_URL, parse_observations
from advisor.collectors.coinbase_candles import CANDLES_URL, ONE_DAY, parse_candles
from advisor.collectors.coins import listed_as
```

In `pipeline/src/advisor/history.py`, replace:

```python
USD_CAD = "FXUSDCAD"
```

with:

```python
USD_CAD = "FXUSDCAD"
COIN_WINDOW = timedelta(days=300)  # Coinbase answers at most 300 daily candles a request
```

In `pipeline/src/advisor/history.py`, replace:

```python
def usd_cad(records
```

with:

```python
def coin_backfill_starts(
    today: date, first_buys: Mapping[AssetRef, date], earliest: Mapping[AssetRef, date]
) -> dict[AssetRef, date]:
    """Where each coin ever bought should start, for those whose stored closes don't reach it."""
    year_ago = today - HISTORY
    starts = {
        ref: min(year_ago, day) for ref, day in first_buys.items() if ref.asset_type is AssetType.CRYPTO
    }
    return {
        ref: start
        for ref, start in starts.items()
        if ref not in earliest or earliest[ref] > start + SLACK
    }


def fetch_coin_closes(client: httpx.Client, ref: AssetRef, start: date, end: date) -> list[DailyClose]:
    """Coinbase's daily USD closes from `start` up to, not including, `end`, 300 days a request.

    A coin Coinbase doesn't list (404) has none.
    """
    product = f"{listed_as(ref.symbol)}-USD"
    closes: list[DailyClose] = []
    window = start
    while window < end:
        stop = min(window + COIN_WINDOW, end)
        try:
            response = get_with_retries(
                client,
                CANDLES_URL.format(product=product),
                params={"granularity": ONE_DAY, "start": f"{window}T00:00:00Z", "end": f"{stop}T00:00:00Z"},
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return []
            raise
        bars = parse_candles(ref.symbol, response.json(), datetime.combine(stop, time(), UTC))
        closes += [DailyClose(ref, bar.day, bar.close, "USD") for bar in bars if bar.day >= window]
        window = stop
    return closes


def usd_cad(records
```

In `pipeline/src/advisor/history.py`, replace:

```python
    rates = usd_cad(valet)
```

with:

```python
    earliest_coins = repo.earliest_closes(conn, [ref for ref in buys if ref.asset_type is AssetType.CRYPTO])
    coin_starts = coin_backfill_starts(today, buys, earliest_coins)
    if coin_starts and http is not None:
        try:
            fetched = [
                close
                for ref, start in sorted(coin_starts.items())
                for close in fetch_coin_closes(http, ref, start, earliest_coins.get(ref, today))
            ]
            store_closes(conn, fetched)
            got = {c.ref for c in fetched}
            summary["backfilled"] = sorted([*summary["backfilled"], *(ref.symbol for ref in got)])
            if missing := sorted(ref.symbol for ref in coin_starts if ref not in got):
                summary["backfill_missing"] = sorted([*summary.get("backfill_missing", []), *missing])
        except Exception as exc:  # Coinbase's history waits for the next run
            summary["coin_backfill_error"] = f"{type(exc).__name__}: {exc}"[:200]

    rates = usd_cad(valet)
```

- [ ] **Step 4: Run the tests**

Run: `scripts/in-docker.sh uv run pytest -q tests/unit/test_history.py tests/integration/test_run.py`
Expected: `64 passed`.

Run: `scripts/in-docker.sh uv run pytest -q`, then `scripts/in-docker.sh uv run ruff check .`
Expected: `666 passed`, then `All checks passed!`.

- [ ] **Step 5: Commit**

```bash
git add pipeline/src/advisor/history.py pipeline/tests/unit/test_history.py pipeline/tests/integration/test_run.py
git commit -m "feat: backfill held coins from Coinbase to a year back or the first buy"
```

---
### Task 3: List trades on My Portfolio, with Delete

**Files:**
- Create: `web/lib/portfolio/trade-list.ts`, `web/components/portfolio/TradeList.tsx`
- Modify: `web/lib/portfolio/types.ts`, `web/lib/data/portfolio.ts`, `web/app/(app)/trades.ts`, `web/app/(app)/page.tsx`, `web/app/styles/pages.css`
- Test: `web/lib/portfolio/trade-list.test.ts`, `web/e2e/trade-list.spec.ts`

**Interfaces:**
- Consumes:
  - `buildLedger(trades, fx).problems` and `tradeCad(trade, fx)` from `lib/portfolio/ledger.ts`.
  - The page's `loadPortfolio`.
  - `FormState` from `lib/trade-form.ts`.
- Produces:
  - `RecordedTrade extends Trade { id: number }` in `lib/portfolio/types.ts`. `loadTrades` and `PortfolioData.trades` return it (Task 5's import and Task 7's ticker read it).
  - `tradeList(trades: readonly RecordedTrade[], fx: FxRates): TradeLine[]`, sorted by:
    - newest day first;
    - on one day, sells before buys;
    - then the newest id.

    A buy's `strandsSells` is true when removing it would add a ledger problem (a later sell exceeding what was held).
  - `deleteTrade(side: 'buy' | 'sell', id: number): Promise<FormState>`, a server action. Its messages:
    - "Buy deleted: 10 RY.TO";
    - "That buy was already gone." when no row was deleted.
  - `<TradeList lines={…} />`:
    - table `#trades` with the latest 10 trades and "Show all N";
    - an inline Delete → "Delete" / "Keep" confirmation, which names stranded sells.

- [ ] **Step 1: Write the failing unit test**

`web/lib/portfolio/trade-list.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { FxRates } from './lookup'
import { tradeList } from './trade-list'
import type { RecordedTrade } from './types'

const FX = new FxRates([{ day: '2026-09-01', usdCad: 1.4 }])
const trade = (over: Partial<RecordedTrade>): RecordedTrade => ({
  id: 1,
  side: 'buy',
  account: 'tfsa',
  symbol: 'RY.TO',
  assetType: 'stock',
  qty: 10,
  price: 170,
  currency: 'CAD',
  fxRateCad: null,
  day: '2026-09-02',
  ...over,
})

describe('tradeList', () => {
  it("lists trades newest first, a day's sells before its buys", () => {
    const lines = tradeList(
      [
        trade({ id: 1, day: '2026-09-02' }),
        trade({ id: 2, day: '2026-09-20' }),
        trade({ id: 1, side: 'sell', qty: 5, day: '2026-09-20' }),
        trade({ id: 3, day: '2026-09-20', symbol: 'TD.TO' }),
      ],
      FX,
    )
    expect(lines.map((l) => l.key)).toEqual(['sell:1', 'buy:3', 'buy:2', 'buy:1'])
  })

  it('gives each trade its amount in CAD', () => {
    const [usd, cad] = tradeList(
      [
        trade({ id: 1 }),
        trade({ id: 2, symbol: 'AAPL', currency: 'USD', fxRateCad: 1.37, price: 200, day: '2026-09-03' }),
      ],
      FX,
    )
    expect(usd).toMatchObject({ symbol: 'AAPL', amountCad: 2740 })
    expect(cad).toMatchObject({ symbol: 'RY.TO', amountCad: 1700 })
  })

  it('marks a buy whose deletion would leave a later sell with too little held', () => {
    const lines = tradeList(
      [
        trade({ id: 1, qty: 10 }),
        trade({ id: 2, qty: 5, day: '2026-09-10' }),
        trade({ id: 1, side: 'sell', qty: 12, day: '2026-09-20' }),
        trade({ id: 3, symbol: 'TD.TO' }),
      ],
      FX,
    )
    const strands = Object.fromEntries(lines.map((l) => [l.key, l.strandsSells]))
    // Without buy 1 only 5 are held when 12 are sold; without buy 2, 10. TD.TO stands alone.
    expect(strands).toEqual({ 'sell:1': false, 'buy:2': true, 'buy:1': true, 'buy:3': false })
  })

  it('is empty without trades', () => {
    expect(tradeList([], FX)).toEqual([])
  })
})
```

- [ ] **Step 2: Run it and see it fail**

Run (from `web/`): `npm test -- lib/portfolio/trade-list.test.ts`
Expected: `Error: Cannot find module './trade-list'`, `Test Files  1 failed (1)`.

- [ ] **Step 3: Write the trade list's view**

In `web/lib/portfolio/types.ts`, replace:

```ts
/** One stored daily close (`daily_closes`). */
```

with:

```ts
/** A trade as stored: its row id in `lots` or `sells`, for the trade list's Delete (Plan 5c). */
export interface RecordedTrade extends Trade {
  id: number
}

/** One stored daily close (`daily_closes`). */
```

`web/lib/portfolio/trade-list.ts`:

```ts
import { buildLedger, tradeCad } from './ledger'
import type { FxRates } from './lookup'
import type { Account, AssetType, Currency, RecordedTrade } from './types'

/** One row of the portfolio page's trade list (Plan 5c). */
export interface TradeLine {
  /** `buy:12` or `sell:3`: ids are only unique within their table. */
  key: string
  id: number
  side: 'buy' | 'sell'
  day: string
  account: Account
  symbol: string
  assetType: AssetType
  qty: number
  price: number
  currency: Currency
  /** In CAD at the trade's own rate (or the Bank of Canada's for old USD trades); null if unknown. */
  amountCad: number | null
  /** Deleting this buy would leave a later sell with more than was held. */
  strandsSells: boolean
}

/**
 * Every trade, newest first (a day's sells before its buys, the reverse of the ledger's order).
 * A buy that later sells depend on is marked, so Delete can say what it would break.
 */
export function tradeList(trades: readonly RecordedTrade[], fx: FxRates): TradeLine[] {
  const problems = buildLedger(trades, fx).problems.length
  const lines = trades.map((t): TradeLine => {
    const strandsSells =
      t.side === 'buy' &&
      buildLedger(
        trades.filter((other) => other !== t),
        fx,
      ).problems.length > problems
    return {
      key: `${t.side}:${t.id}`,
      id: t.id,
      side: t.side,
      day: t.day,
      account: t.account,
      symbol: t.symbol,
      assetType: t.assetType,
      qty: t.qty,
      price: t.price,
      currency: t.currency,
      amountCad: tradeCad(t, fx),
      strandsSells,
    }
  })
  return lines.sort((a, b) => {
    if (a.day !== b.day) return a.day < b.day ? 1 : -1
    if (a.side !== b.side) return a.side === 'sell' ? -1 : 1
    return b.id - a.id
  })
}
```

- [ ] **Step 4: Run it**

Run: `npm test -- lib/portfolio/trade-list.test.ts`
Expected: `Test Files  1 passed (1)`, `Tests  4 passed (4)`.

- [ ] **Step 5: Write the failing browser tests**

`web/e2e/trade-list.spec.ts`:

```ts
import { expect, test, type Page } from '@playwright/test'
import { longDay } from '../lib/dates'
import { daysAgo, resetData, seedLot, seedSell, sql } from './db'

test.beforeEach(resetData)

const rows = (page: Page) => page.locator('#trades tbody tr')
const lot = (qty: number, day: string) =>
  seedLot({ account: 'tfsa', symbol: 'RY.TO', asset_type: 'stock', qty, price: 170, currency: 'CAD', bought_at: day })

test('a mistaken buy is deleted from the trade list', async ({ page }) => {
  await lot(10, daysAgo(30))
  await page.goto('/')
  await expect(rows(page)).toHaveCount(1)
  await expect(rows(page)).toContainText('RY.TO')
  await expect(rows(page)).toContainText('1,700')

  await page.getByRole('button', { name: `Delete the buy of 10 RY.TO on ${longDay(daysAgo(30))}` }).click()
  await expect(page.getByText("This can't be undone.")).toBeVisible()
  await page.getByRole('button', { name: 'Delete', exact: true }).click()

  await expect(page.getByRole('status')).toHaveText('Buy deleted: 10 RY.TO')
  await expect(page.getByText('No holdings yet. Add your first buy to start.')).toBeVisible()
  await expect(page.locator('#trades')).toHaveCount(0)
  expect(await sql`select 1 from lots`).toHaveLength(0)
})

test('deleting a buy that a later sell needs says so first, and Keep keeps it', async ({ page }) => {
  await lot(10, daysAgo(40))
  await lot(5, daysAgo(30))
  await seedSell({ account: 'tfsa', symbol: 'RY.TO', asset_type: 'stock', qty: 12, price: 180, currency: 'CAD', sold_at: daysAgo(10) })
  await page.goto('/')
  await expect(rows(page)).toHaveCount(3)
  await expect(rows(page).first()).toContainText('Sell')

  await page.getByRole('button', { name: `Delete the buy of 5 RY.TO on ${longDay(daysAgo(30))}` }).click()
  await expect(page.getByText('Later sells of RY.TO would then exceed what you held.')).toBeVisible()
  await page.getByRole('button', { name: 'Keep' }).click()
  await expect(page.getByText('Later sells of RY.TO would then exceed what you held.')).toHaveCount(0)
  expect(await sql`select 1 from lots`).toHaveLength(2)
})

test('the latest ten trades show until all are asked for', async ({ page }) => {
  for (let i = 1; i <= 12; i += 1) await lot(1, daysAgo(40 - i))
  await page.goto('/')
  await expect(rows(page)).toHaveCount(10)
  await expect(rows(page).first()).toContainText(longDay(daysAgo(28)))
  await page.getByRole('button', { name: 'Show all 12' }).click()
  await expect(rows(page)).toHaveCount(12)
})
```

- [ ] **Step 6: Run them and see them fail**

Run: `npm run e2e -- e2e/trade-list.spec.ts`
Expected: the build succeeds, then `3 failed` and `1 passed` (the setup). Each test's first check fails on `locator('#trades tbody tr')`: expected 1, 3 or 10, received 0.

- [ ] **Step 7: Load trades with their ids, and delete them**

In `web/lib/data/portfolio.ts`, replace:

```ts
import type { Account, AssetType, Close, Currency, Trade } from '../portfolio/types'
```

with:

```ts
import type { Account, AssetType, Close, Currency, RecordedTrade, Trade } from '../portfolio/types'
```

In `web/lib/data/portfolio.ts`, replace:

```ts
interface TradeRow {
  account: Account
```

with:

```ts
interface TradeRow {
  id: number
  account: Account
```

In `web/lib/data/portfolio.ts`, replace:

```ts
const toTrade = (side: Trade['side'], day: string, row: TradeRow): Trade => ({
```

with:

```ts
const toTrade = (side: Trade['side'], day: string, row: TradeRow): RecordedTrade => ({
  id: row.id,
```

In `web/lib/data/portfolio.ts`, replace:

```ts
export async function loadTrades(supabase: Supabase): Promise<Trade[]> {
```

with:

```ts
export async function loadTrades(supabase: Supabase): Promise<RecordedTrade[]> {
```

In `web/lib/data/portfolio.ts`, replace:

```ts
  trades: Trade[]
  prices: PriceBook
```

with:

```ts
  trades: RecordedTrade[]
  prices: PriceBook
```

In `web/app/(app)/trades.ts`, replace:

```ts
/** Add a sell (a `sells` row), checked against what the ledger says is held. */
```

with:

```ts
/**
 * Delete a buy or a sell (Plan 5c). Row-level security lets only the owner delete; a row that
 * isn't there (deleted in another tab) is reported, not ignored.
 */
export async function deleteTrade(side: 'buy' | 'sell', id: number): Promise<FormState> {
  if ((side !== 'buy' && side !== 'sell') || !Number.isSafeInteger(id) || id <= 0) {
    return failed("That trade can't be deleted.")
  }
  const supabase = await createClient()
  const { data, error } = await supabase
    .from(side === 'buy' ? 'lots' : 'sells')
    .delete()
    .eq('id', id)
    .select('symbol, qty')
  if (error) return failed(`The ${side} wasn't deleted: ${error.message}`)
  const row = (data as { symbol: string; qty: string | number }[] | null)?.[0]
  if (!row) return failed(`That ${side} was already gone.`)
  revalidatePath('/')
  return {
    ok: true,
    message: `${side === 'buy' ? 'Buy' : 'Sell'} deleted: ${fmtQty(Number(row.qty))} ${row.symbol}`,
    at: Date.now(),
  }
}

/** Add a sell (a `sells` row), checked against what the ledger says is held. */
```

- [ ] **Step 8: Show the list on My Portfolio**

`web/components/portfolio/TradeList.tsx`:

```tsx
'use client'

import { Trash2 } from 'lucide-react'
import { useState, useTransition } from 'react'
import { deleteTrade } from '@/app/(app)/trades'
import { useToast } from '@/components/Toast'
import { longDay } from '@/lib/dates'
import { fmtAmount, fmtPrice, fmtQty } from '@/lib/format'
import type { TradeLine } from '@/lib/portfolio/trade-list'
import { ACCOUNT_LABELS } from '@/lib/portfolio/types'

const LATEST = 10

/** Every buy and sell, newest first, each with Delete (Plan 5c). A mistaken trade is fixed by
 * deleting it and entering it again. */
export function TradeList({ lines }: { lines: TradeLine[] }) {
  const toast = useToast()
  const [all, setAll] = useState(false)
  const [asking, setAsking] = useState<string | null>(null)
  const [pending, startTransition] = useTransition()
  const shown = all ? lines : lines.slice(0, LATEST)

  const remove = (line: TradeLine) =>
    startTransition(async () => {
      const result = await deleteTrade(line.side, line.id)
      setAsking(null)
      if (result.message) toast(result.message)
    })

  return (
    <section className="card card-pad enter" aria-labelledby="trades-h">
      <div className="section-head">
        <h2 id="trades-h">Trades</h2>
        <span className="sub">
          {lines.length} recorded · newest first
        </span>
      </div>
      <div className="table-scroll">
        <table className="data-table" id="trades">
          <thead>
            <tr>
              <th>Date</th>
              <th>Account</th>
              <th>Trade</th>
              <th className="r">Quantity</th>
              <th className="r">Price</th>
              <th className="r">Amount C$</th>
              <th>
                <span className="sr-only">Delete</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {shown.map((line) => {
              const what = line.side === 'buy' ? 'Buy' : 'Sell'
              return (
                <tr key={line.key}>
                  <td className="num t-day">{longDay(line.day)}</td>
                  <td className="sub t-acct">{ACCOUNT_LABELS[line.account]}</td>
                  <td className="t-what">
                    <span className="badge">{what}</span> <span className="sym">{line.symbol}</span>
                  </td>
                  <td className="r num t-qty">{fmtQty(line.qty)}</td>
                  <td className="r num t-price">{fmtPrice(line.price, line.currency)}</td>
                  <td className="r num t-amount">{line.amountCad === null ? '—' : fmtAmount(line.amountCad)}</td>
                  <td className="sub t-meta" aria-hidden="true">
                    {longDay(line.day)} · {ACCOUNT_LABELS[line.account]} · {fmtQty(line.qty)} ×{' '}
                    {fmtPrice(line.price, line.currency)}
                  </td>
                  <td className="t-del">
                    {asking === line.key ? (
                      <span className="trade-confirm" role="group" aria-label={`Delete this ${line.side}?`}>
                        <span className="sub">
                          {line.strandsSells
                            ? `Later sells of ${line.symbol} would then exceed what you held.`
                            : "This can't be undone."}
                        </span>
                        <button type="button" className="btn btn-primary btn-sm" disabled={pending} onClick={() => remove(line)}>
                          {pending ? 'Deleting…' : 'Delete'}
                        </button>
                        <button type="button" className="btn btn-ghost btn-sm" onClick={() => setAsking(null)}>
                          Keep
                        </button>
                      </span>
                    ) : (
                      <button
                        type="button"
                        className="icon-btn"
                        aria-label={`Delete the ${line.side} of ${fmtQty(line.qty)} ${line.symbol} on ${longDay(line.day)}`}
                        onClick={() => setAsking(line.key)}
                      >
                        <Trash2 />
                      </button>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      {lines.length > LATEST && (
        <button type="button" className="btn btn-ghost btn-sm" style={{ marginTop: 8 }} onClick={() => setAll((a) => !a)}>
          {all ? `Show the latest ${LATEST}` : `Show all ${lines.length}`}
        </button>
      )}
    </section>
  )
}
```

In `web/app/(app)/page.tsx`, replace:

```tsx
import { TradeButtons } from '@/components/portfolio/TradeForms'
```

with:

```tsx
import { TradeButtons } from '@/components/portfolio/TradeForms'
import { TradeList } from '@/components/portfolio/TradeList'
```

In `web/app/(app)/page.tsx`, replace:

```tsx
import { todayInToronto } from '@/lib/dates'
```

with:

```tsx
import { todayInToronto } from '@/lib/dates'
import { tradeList } from '@/lib/portfolio/trade-list'
```

In `web/app/(app)/page.tsx`, replace:

```tsx
      <HoldingsCard holdings={view.holdings} accounts={view.accounts.length} />
```

with:

```tsx
      <HoldingsCard holdings={view.holdings} accounts={view.accounts.length} />
      {data.trades.length > 0 && <TradeList lines={tradeList(data.trades, data.fx)} />}
```

Append to `web/app/styles/pages.css`, after one blank line:

```css
/* ---------- Trade list (Plan 5c, in the portfolio page's table style) ---------- */
#trades td.t-meta { display: none; }
#trades td.t-del { width: 1%; text-align: right; }
.trade-confirm { display: inline-flex; flex-wrap: wrap; align-items: center; justify-content: flex-end; gap: 6px; white-space: normal; max-width: 340px; }
@media (max-width: 639px) {
  #trades thead { display: none; }
  #trades, #trades tbody { display: block; }
  #trades tr { display: grid; grid-template-columns: minmax(0, 1fr) auto; grid-template-areas: "what amount" "meta del"; gap: 4px 10px; align-items: center; padding: 10px 0; border-bottom: 1px solid var(--border); }
  #trades tr:last-child { border-bottom: 0; }
  #trades td { display: none; padding: 0; border: 0; white-space: normal; }
  #trades td.t-what { display: block; grid-area: what; }
  #trades td.t-amount { display: block; grid-area: amount; }
  #trades td.t-amount::before { content: "C$"; }
  #trades td.t-meta { display: block; grid-area: meta; }
  #trades td.t-del { display: block; grid-area: del; }
  .trade-confirm { justify-content: flex-start; }
}
```

- [ ] **Step 9: Run the tests**

Run: `npm test`
Expected: `Test Files  13 passed (13)`, `Tests  85 passed (85)`.

Run: `npm run e2e`
Expected: `32 passed`, with no `[WebServer] ⨯ Error` line. Then `npm run lint` and `npm run typecheck` are clean.

- [ ] **Step 10: Commit**

```bash
git add web/lib/portfolio/types.ts web/lib/portfolio/trade-list.ts web/lib/portfolio/trade-list.test.ts web/lib/data/portfolio.ts "web/app/(app)/trades.ts" "web/app/(app)/page.tsx" web/components/portfolio/TradeList.tsx web/app/styles/pages.css web/e2e/trade-list.spec.ts
git commit -m "feat: list trades on My Portfolio, with Delete"
```

---

### Task 4: Read a broker's CSV into trades

**Files:**
- Create: `web/lib/import/csv.ts`, `web/lib/import/rows.ts`
- Test: `web/lib/import/import.test.ts`

**Interfaces:**
- Consumes:
  - From `lib/symbols.ts`: `normalizeSymbol`, `isValidSymbol`, `tradeCurrency`.
  - From `lib/trade-form.ts`: `parseAmount`, `RATE_RANGE`.
  - From `lib/portfolio/types.ts`: `ACCOUNTS`.
- Produces (Task 5 uses all of them):
  - `parseCsv(input: string): string[][]`.
    - It detects a comma, semicolon or tab delimiter.
    - It handles quotes, a BOM and CRLF, and skips blank lines.
  - Column meanings:
    - `Meaning`: `'date' | 'side' | 'symbol' | 'quantity' | 'price' | 'account' | 'currency' | 'fxRate' | 'ignore'`.
    - `MEANINGS` (value and label) and `REQUIRED`.
    - `guessMeanings(headers): Meaning[]`.
    - `meaningProblems(meanings, accountFromColumn): string[]`.
  - Reading fields:
    - `DateOrder`: `'ymd' | 'mdy' | 'dmy'`.
    - `readDate(raw, order): string | null`. It checks the round trip, so 2026-02-30 is refused.
    - `readAccount(raw)` and `readSide(raw)`.
  - Rows:
    - `ImportTrade { side, account, symbol, assetType, qty, price, day, fxRate }`.
    - `ImportRow { line, status: 'ready' | 'skipped' | 'duplicate' | 'error', reason, trade }`.
    - `readRows(rows, { meanings, account, dateOrder, today, existing }): ImportRow[]`.
    - A bare stock symbol priced in CAD reads as its TSX listing: RY → RY.TO.
    - A row matching a recorded trade, or an earlier row in the file, is a duplicate.

- [ ] **Step 1: Write the failing tests**

`web/lib/import/import.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import type { Trade } from '../portfolio/types'
import { parseCsv } from './csv'
import { guessMeanings, meaningProblems, readAccount, readDate, readRows, readSide, type Meaning } from './rows'

describe('parseCsv', () => {
  it('reads quoted fields with commas, doubled quotes and line breaks', () => {
    const text = '﻿date,description,amount\r\n2026-10-03,"Bought 10 RY, ""at market""",-1840.00\r\n"2026-10-04","two\nlines",5\r\n\r\n'
    expect(parseCsv(text)).toEqual([
      ['date', 'description', 'amount'],
      ['2026-10-03', 'Bought 10 RY, "at market"', '-1840.00'],
      ['2026-10-04', 'two\nlines', '5'],
    ])
  })

  it('uses the delimiter the header uses', () => {
    expect(parseCsv('date;symbol\n2026-10-03;RY')).toEqual([['date', 'symbol'], ['2026-10-03', 'RY']])
    expect(parseCsv('date\tsymbol\n2026-10-03\tRY')).toEqual([['date', 'symbol'], ['2026-10-03', 'RY']])
  })
})

describe('column meanings', () => {
  it('guesses from the headers, each meaning once', () => {
    expect(
      guessMeanings(['Date', 'Activity Type', 'Symbol', 'Quantity', 'Price', 'Account', 'Currency', 'Net Amount', 'Date']),
    ).toEqual(['date', 'side', 'symbol', 'quantity', 'price', 'account', 'currency', 'ignore', 'ignore'])
  })

  it('names what is missing or chosen twice', () => {
    const meanings: Meaning[] = ['date', 'date', 'symbol', 'quantity', 'price']
    expect(meaningProblems(meanings, true)).toEqual([
      'Date is chosen for 2 columns.',
      'Choose the column with the buy or sell.',
      'Choose the column with the account.',
    ])
    expect(meaningProblems(['date', 'side', 'symbol', 'quantity', 'price'], false)).toEqual([])
  })
})

describe('reading values', () => {
  it('reads ISO, written-out and slashed dates, and refuses impossible ones', () => {
    expect(readDate('2026-10-03', 'ymd')).toBe('2026-10-03')
    expect(readDate('2026-10-03 09:31:00', 'mdy')).toBe('2026-10-03')
    expect(readDate('Oct 3, 2026', 'ymd')).toBe('2026-10-03')
    expect(readDate('3 October 2026', 'ymd')).toBe('2026-10-03')
    expect(readDate('10/03/2026', 'mdy')).toBe('2026-10-03')
    expect(readDate('03/10/2026', 'dmy')).toBe('2026-10-03')
    expect(readDate('2026-02-30', 'ymd')).toBeNull()
    expect(readDate('yesterday', 'ymd')).toBeNull()
  })

  it("reads sides and accounts in brokers' words", () => {
    expect([readSide('BUY'), readSide('Market sell'), readSide('Dividend'), readSide('purchase')]).toEqual([
      'buy', 'sell', null, 'buy',
    ])
    expect([readAccount('TFSA - Self-directed'), readAccount('Crypto'), readAccount('Personal'), readAccount('Chequing')]).toEqual([
      'tfsa', 'crypto', 'non_registered', null,
    ])
  })
})

describe('readRows', () => {
  const header = ['date', 'type', 'symbol', 'quantity', 'price', 'currency', 'account']
  const meanings: Meaning[] = ['date', 'side', 'symbol', 'quantity', 'price', 'currency', 'account']
  const options = { meanings, account: null, dateOrder: 'ymd' as const, today: '2026-10-16', existing: [] as Trade[] }

  it('reads buys and sells, a bare CAD symbol as TSX, and coins in the crypto account', () => {
    const rows = readRows(
      [
        header,
        ['2026-10-03', 'Buy', 'RY', '10', 'C$184.50', 'CAD', 'TFSA'],
        ['2026-10-04', 'Sell', 'aapl', '-2', '$230', 'USD', 'TFSA'],
        ['2026-10-05', 'Buy', 'BTC', '0.015', '98,000', 'CAD', 'Crypto'],
      ],
      options,
    )
    expect(rows.map((r) => [r.line, r.status, r.trade?.symbol, r.trade?.side, r.trade?.qty, r.trade?.price])).toEqual([
      [2, 'ready', 'RY.TO', 'buy', 10, 184.5],
      [3, 'ready', 'AAPL', 'sell', 2, 230],
      [4, 'ready', 'BTC', 'buy', 0.015, 98000],
    ])
    expect(rows[2].trade?.assetType).toBe('crypto')
  })

  it('leaves out what is not a trade, and says why each bad row is wrong', () => {
    const rows = readRows(
      [
        header,
        ['2026-10-03', 'Dividend', 'RY', '', '', 'CAD', 'TFSA'],
        ['2026-13-01', 'Buy', 'RY', '1', '1', 'CAD', 'TFSA'],
        ['2026-10-03', 'Buy', 'RY', '1', '1', 'CAD', 'Chequing'],
        ['2026-10-17', 'Buy', 'RY', '1', '1', 'CAD', 'TFSA'],
        ['2026-10-03', 'Buy', 'NOT A SYMBOL', '1', '1', 'USD', 'TFSA'],
        ['2026-10-03', 'Buy', 'RY', 'ten', '1', 'CAD', 'TFSA'],
      ],
      options,
    )
    expect(rows.map((r) => [r.status, r.reason])).toEqual([
      ['skipped', 'Not a buy or a sell (Dividend).'],
      ['error', 'Can\'t read the date "2026-13-01".'],
      ['error', 'Unknown account "Chequing".'],
      ['error', 'The date is after today.'],
      ['error', '"NOT A SYMBOL" isn\'t a stock symbol.'],
      ['error', 'Can\'t read the quantity "ten".'],
    ])
  })

  it('marks a trade already recorded, or twice in the file, as a duplicate', () => {
    const existing: Trade[] = [{
      side: 'buy', account: 'tfsa', symbol: 'RY.TO', assetType: 'stock', qty: 10, price: 184.5,
      currency: 'CAD', fxRateCad: null, day: '2026-10-03',
    }]
    const rows = readRows(
      [
        header,
        ['2026-10-03', 'Buy', 'RY', '10', '184.50', 'CAD', 'TFSA'],
        ['2026-10-04', 'Buy', 'TD', '5', '80', 'CAD', 'TFSA'],
        ['2026-10-04', 'Buy', 'TD', '5', '80', 'CAD', 'TFSA'],
      ],
      { ...options, existing },
    )
    expect(rows.map((r) => [r.status, r.reason])).toEqual([
      ['duplicate', 'Already recorded.'],
      ['ready', null],
      ['duplicate', 'Twice in this file.'],
    ])
  })

  it('uses one account for the whole file when there is no account column', () => {
    const rows = readRows(
      [['date', 'type', 'symbol', 'quantity', 'price'], ['2026-10-03', 'Buy', 'ETH', '1', '4000']],
      { ...options, meanings: ['date', 'side', 'symbol', 'quantity', 'price'], account: 'crypto' },
    )
    expect(rows[0].trade).toMatchObject({ account: 'crypto', assetType: 'crypto', symbol: 'ETH' })
  })

  it("keeps a US stock's rate from the file, and refuses one that isn't a rate", () => {
    const withRate = [...header, 'fx']
    const m: Meaning[] = [...meanings, 'fxRate']
    const rows = readRows(
      [withRate, ['2026-10-03', 'Buy', 'AAPL', '1', '230', 'USD', 'TFSA', '1.3918'], ['2026-10-03', 'Buy', 'MSFT', '1', '410', 'USD', 'TFSA', '139']],
      { ...options, meanings: m },
    )
    expect(rows[0].trade?.fxRate).toBe(1.3918)
    expect(rows[1]).toMatchObject({ status: 'error', reason: 'Can\'t read the USD/CAD rate "139".' })
  })
})
```

- [ ] **Step 2: Run them and see them fail**

Run: `npm test -- lib/import`
Expected: `Error: Cannot find module './csv'`, `Test Files  1 failed (1)`.

- [ ] **Step 3: Write the reader**

`web/lib/import/csv.ts`:

```ts
/** A small CSV reader for broker activity files (spec §7.1, file import). */

const DELIMITERS = [',', ';', '\t'] as const

/** The delimiter the header line uses most: comma, semicolon or tab. */
function delimiterOf(text: string): string {
  const header = text.split(/\r?\n/, 1)[0] ?? ''
  let best: string = ','
  let most = -1
  for (const d of DELIMITERS) {
    const count = header.split(d).length - 1
    if (count > most) {
      best = d
      most = count
    }
  }
  return best
}

/**
 * Rows of fields. Quoted fields may hold the delimiter, line breaks and doubled quotes (`""`).
 * A byte-order mark, CRLF line ends and blank lines are tolerated.
 */
export function parseCsv(input: string): string[][] {
  const text = input.replace(/^﻿/, '')
  const delimiter = delimiterOf(text)
  const rows: string[][] = []
  let row: string[] = []
  let field = ''
  let quoted = false
  for (let i = 0; i < text.length; i += 1) {
    const c = text[i]
    if (quoted) {
      if (c === '"' && text[i + 1] === '"') {
        field += '"'
        i += 1
      } else if (c === '"') {
        quoted = false
      } else {
        field += c
      }
    } else if (c === '"' && field === '') {
      quoted = true
    } else if (c === delimiter) {
      row.push(field)
      field = ''
    } else if (c === '\n' || c === '\r') {
      if (c === '\r' && text[i + 1] === '\n') i += 1
      row.push(field)
      if (row.some((f) => f.trim() !== '')) rows.push(row)
      row = []
      field = ''
    } else {
      field += c
    }
  }
  row.push(field)
  if (row.some((f) => f.trim() !== '')) rows.push(row)
  return rows.map((r) => r.map((f) => f.trim()))
}
```

`web/lib/import/rows.ts`:

```ts
/**
 * Turning a broker's activity file into trades (spec §7.1, file import). The owner says what each
 * column means; every row then reads as a buy, a sell, or a line with a reason it was left out.
 */

import { ACCOUNTS } from '../portfolio/types'
import type { Account, AssetType, Trade } from '../portfolio/types'
import { isValidSymbol, normalizeSymbol, tradeCurrency } from '../symbols'
import { RATE_RANGE, parseAmount } from '../trade-form'

export type Meaning = 'date' | 'side' | 'symbol' | 'quantity' | 'price' | 'account' | 'currency' | 'fxRate' | 'ignore'

export const MEANINGS: { value: Meaning; label: string }[] = [
  { value: 'date', label: 'Date' },
  { value: 'side', label: 'Buy or sell' },
  { value: 'symbol', label: 'Symbol' },
  { value: 'quantity', label: 'Quantity' },
  { value: 'price', label: 'Price' },
  { value: 'account', label: 'Account' },
  { value: 'currency', label: 'Currency' },
  { value: 'fxRate', label: 'USD/CAD rate' },
  { value: 'ignore', label: 'Ignore' },
]

export const REQUIRED: readonly Meaning[] = ['date', 'side', 'symbol', 'quantity', 'price']

const GUESSES: [Meaning, RegExp][] = [
  ['date', /^(date|tradedate|transactiondate|activitydate|processdate|settlementdate)$/],
  ['side', /^(activitytype|transactiontype|type|action|side|activity|transaction|subtype)$/],
  ['symbol', /^(symbol|ticker|security|securitysymbol)$/],
  ['quantity', /^(quantity|qty|shares|units|numberofshares)$/],
  ['price', /^(price|unitprice|priceperunit|marketprice)$/],
  ['account', /^(account|accounttype|accountname)$/],
  ['currency', /^(currency|ccy|tradecurrency)$/],
  ['fxRate', /^(exchangerate|fxrate|fx|usdcad)$/],
]

/** What each column most likely means, from its header; each meaning is used once. */
export function guessMeanings(headers: readonly string[]): Meaning[] {
  const used = new Set<Meaning>()
  return headers.map((header) => {
    const key = header.toLowerCase().replace(/[^a-z]/g, '')
    const hit = GUESSES.find(([meaning, pattern]) => !used.has(meaning) && pattern.test(key))
    if (!hit) return 'ignore'
    used.add(hit[0])
    return hit[0]
  })
}

/** Meanings chosen for more than one column, and required ones chosen for none. */
export function meaningProblems(meanings: readonly Meaning[], accountFromColumn: boolean): string[] {
  const problems: string[] = []
  for (const m of MEANINGS) {
    const count = meanings.filter((x) => x === m.value).length
    if (m.value !== 'ignore' && count > 1) problems.push(`${m.label} is chosen for ${count} columns.`)
  }
  for (const m of [...REQUIRED, ...(accountFromColumn ? (['account'] as Meaning[]) : [])]) {
    if (!meanings.includes(m)) problems.push(`Choose the column with the ${MEANINGS.find((x) => x.value === m)!.label.toLowerCase()}.`)
  }
  return problems
}

export type DateOrder = 'ymd' | 'mdy' | 'dmy'

const MONTHS = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec']
const pad = (n: number) => String(n).padStart(2, '0')

/** A date written as 2026-10-03 (a time may follow), Oct 3, 2026, 3 Oct 2026, or with slashes in `order`. */
export function readDate(raw: string, order: DateOrder): string | null {
  const text = raw.trim()
  let y: number, m: number, d: number
  let match = /^(\d{4})-(\d{1,2})-(\d{1,2})(?:[T\s].*)?$/.exec(text)
  if (match) [y, m, d] = [Number(match[1]), Number(match[2]), Number(match[3])]
  else if ((match = /^([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2}),?\s+(\d{4})$/.exec(text))) {
    ;[y, m, d] = [Number(match[3]), MONTHS.indexOf(match[1].toLowerCase()) + 1, Number(match[2])]
  } else if ((match = /^(\d{1,2})\s+([A-Za-z]{3})[a-z]*\.?,?\s+(\d{4})$/.exec(text))) {
    ;[y, m, d] = [Number(match[3]), MONTHS.indexOf(match[2].toLowerCase()) + 1, Number(match[1])]
  } else if ((match = /^(\d{1,4})[/.](\d{1,2})[/.](\d{1,4})$/.exec(text))) {
    const [a, b, c] = [Number(match[1]), Number(match[2]), Number(match[3])]
    ;[y, m, d] = order === 'ymd' ? [a, b, c] : order === 'mdy' ? [c, a, b] : [c, b, a]
  } else return null
  if (m < 1 || m > 12 || d < 1 || y < 1900) return null
  const iso = `${y}-${pad(m)}-${pad(d)}`
  // Round-trip, so 2026-02-30 isn't accepted as March 2.
  return new Date(`${iso}T00:00:00Z`).toISOString().startsWith(iso) ? iso : null
}

const ACCOUNT_WORDS: [RegExp, Account][] = [
  [/tfsa/, 'tfsa'],
  [/rrsp|rsp/, 'rrsp'],
  [/fhsa/, 'fhsa'],
  [/crypto/, 'crypto'],
  [/non.?registered|personal|cash|margin|taxable/, 'non_registered'],
]

export const readAccount = (raw: string): Account | null =>
  ACCOUNT_WORDS.find(([pattern]) => pattern.test(raw.toLowerCase()))?.[1] ?? null

export const readSide = (raw: string): Trade['side'] | null => {
  const text = raw.toLowerCase()
  if (/\b(buy|bought|purchase)/.test(text)) return 'buy'
  if (/\b(sell|sold|sale)/.test(text)) return 'sell'
  return null
}

/** A trade as the import action receives it: the server sets the currency and fills a blank rate. */
export interface ImportTrade {
  side: Trade['side']
  account: Account
  symbol: string
  assetType: AssetType
  qty: number
  price: number
  day: string
  /** For a US stock, the rate in the file, if any; null to use the Bank of Canada's. */
  fxRate: number | null
}

export type RowStatus = 'ready' | 'skipped' | 'duplicate' | 'error'

export interface ImportRow {
  /** The row's line in the file, counting the header as line 1. */
  line: number
  status: RowStatus
  reason: string | null
  trade: ImportTrade | null
}

export interface ReadOptions {
  meanings: readonly Meaning[]
  /** One account for the whole file, or null to read it from the Account column. */
  account: Account | null
  dateOrder: DateOrder
  today: string
  /** Trades already recorded, so a file imported twice adds nothing. */
  existing: readonly Trade[]
}

const sameTrade = (a: Omit<Trade, 'currency' | 'fxRateCad'>, b: Omit<Trade, 'currency' | 'fxRateCad'>) =>
  a.side === b.side &&
  a.account === b.account &&
  a.symbol === b.symbol &&
  a.assetType === b.assetType &&
  a.day === b.day &&
  Math.abs(a.qty - b.qty) < 1e-9 &&
  Math.abs(a.price - b.price) < 1e-9

/**
 * Each data row (the header is row 1) as a ready trade, a duplicate of one already recorded or
 * earlier in the file, a row that isn't a trade (dividends, deposits), or an error with its reason.
 * A stock symbol without a suffix that the file prices in CAD is read as its TSX listing (RY → RY.TO).
 */
export function readRows(rows: readonly (readonly string[])[], options: ReadOptions): ImportRow[] {
  const col = (m: Meaning) => options.meanings.indexOf(m)
  const at = (row: readonly string[], m: Meaning) => (col(m) >= 0 ? (row[col(m)] ?? '').trim() : '')
  const seen: ImportTrade[] = []
  return rows.slice(1).map((row, i): ImportRow => {
    const line = i + 2
    const skip = (reason: string): ImportRow => ({ line, status: 'skipped', reason, trade: null })
    const error = (reason: string): ImportRow => ({ line, status: 'error', reason, trade: null })

    const sideText = at(row, 'side')
    const side = readSide(sideText)
    if (!side) return skip(sideText ? `Not a buy or a sell (${sideText}).` : 'No buy or sell given.')

    const account = options.account ?? readAccount(at(row, 'account'))
    if (!account || !ACCOUNTS.includes(account)) return error(`Unknown account "${at(row, 'account')}".`)
    const assetType: AssetType = account === 'crypto' ? 'crypto' : 'stock'

    let symbol = normalizeSymbol(at(row, 'symbol'))
    const currency = at(row, 'currency').toUpperCase()
    if (assetType === 'stock' && currency === 'CAD' && /^[A-Z]{1,5}([.-][A-Z]{1,2})?$/.test(symbol)) {
      symbol = normalizeSymbol(`${symbol.replace('.', '-')}.TO`)
    }
    if (!isValidSymbol(symbol, assetType)) {
      return error(`"${at(row, 'symbol')}" isn't a ${assetType === 'crypto' ? 'coin' : 'stock'} symbol.`)
    }

    const day = readDate(at(row, 'date'), options.dateOrder)
    if (!day) return error(`Can't read the date "${at(row, 'date')}".`)
    if (day > options.today) return error('The date is after today.')

    const qty = parseAmount(at(row, 'quantity').replace(/^-/, ''))
    if (qty === null || qty <= 0) return error(`Can't read the quantity "${at(row, 'quantity')}".`)
    const price = parseAmount(at(row, 'price').replace(/^[A-Z]{0,3}\$?/i, ''))
    if (price === null || price <= 0) return error(`Can't read the price "${at(row, 'price')}".`)

    let fxRate: number | null = null
    if (tradeCurrency(assetType, symbol) === 'USD' && at(row, 'fxRate') !== '') {
      fxRate = parseAmount(at(row, 'fxRate'))
      if (fxRate === null || fxRate < RATE_RANGE[0] || fxRate > RATE_RANGE[1]) {
        return error(`Can't read the USD/CAD rate "${at(row, 'fxRate')}".`)
      }
    }

    const trade: ImportTrade = { side, account, symbol, assetType, qty, price, day, fxRate }
    if (options.existing.some((t) => sameTrade(t, trade))) {
      return { line, status: 'duplicate', reason: 'Already recorded.', trade }
    }
    if (seen.some((t) => sameTrade(t, trade))) {
      return { line, status: 'duplicate', reason: 'Twice in this file.', trade }
    }
    seen.push(trade)
    return { line, status: 'ready', reason: null, trade }
  })
}
```

- [ ] **Step 4: Run the tests**

Run: `npm test -- lib/import`
Expected: `Test Files  1 passed (1)`, `Tests  11 passed (11)`.

Run: `npm test`
Expected: `Test Files  14 passed (14)`, `Tests  96 passed (96)`. Then `npm run lint` and `npm run typecheck` are clean.

- [ ] **Step 5: Commit**

```bash
git add web/lib/import
git commit -m "feat: read a broker's CSV into trades"
```

---

### Task 5: Import a broker file from My Portfolio

**Files:**
- Create: `web/app/(app)/import.ts`, `web/components/portfolio/ImportDrawer.tsx`
- Modify: `web/components/portfolio/TradeForms.tsx`, `web/app/(app)/page.tsx`, `web/app/styles/pages.css`
- Test: `web/e2e/import.spec.ts`

**Interfaces:**
- Consumes:
  - Everything Task 4 produces.
  - `loadTrades` and `loadFx` from `lib/data/portfolio.ts`, and `buildLedger`.
  - `Drawer`, `longDay`, `fmtPrice`, `fmtQty`.
- Produces:
  - Server actions in `app/(app)/import.ts`:
    - `unlistedStocks(symbols: string[]): Promise<string[]>`: the stock symbols missing from `symbols`, sorted.
    - `importTrades(trades: ImportTrade[]): Promise<FormState>`: all or nothing, at most 5,000 trades.
      - It checks every trade again.
      - It fills the Bank of Canada rate for a USD trade without one.
      - It refuses the file when it adds a ledger problem.
      - It inserts the buys, then the sells, and deletes the new buys if the sells fail.
      - Its message is "Imported N trades".
  - `<ImportDrawer open round existing today onClose onDone />`, with three steps (file, columns, review). "Import the N not in the lists too" opts unlisted stocks in.
  - `TradeButtons` gains the prop `existing: Trade[]` and an "Import file" button.

- [ ] **Step 1: Write the failing browser tests**

`web/e2e/import.spec.ts`:

```ts
import { expect, test, type Page } from '@playwright/test'
import { daysAgo, resetData, seedFx, seedLot, seedSymbols, sql } from './db'

test.beforeEach(async () => {
  await resetData()
  await seedSymbols([
    { symbol: 'RY.TO', market: 'TSX', name: 'Royal Bank of Canada' },
    { symbol: 'AAPL', market: 'US', name: 'Apple Inc.' },
  ])
  await seedFx([daysAgo(40)], 1.37)
})

/** A Wealthsimple-style activity export: RY in CAD is the TSX listing. */
const csv = (...rows: string[]) =>
  ['Date,Activity Type,Symbol,Quantity,Price,Currency,Account', ...rows].join('\r\n')

async function upload(page: Page, text: string) {
  await page.goto('/')
  await page.getByRole('button', { name: 'Import file' }).click()
  const drawer = page.getByRole('dialog', { name: 'Import a file' })
  await drawer.getByLabel('Activity file (CSV)').setInputFiles({
    name: 'activities.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from(text),
  })
  return drawer
}

test('a broker file is imported after its columns are matched and its rows reviewed', async ({ page }) => {
  const drawer = await upload(
    page,
    csv(
      `${daysAgo(30)},Buy,RY,10,C$184.50,CAD,TFSA`,
      `${daysAgo(29)},Buy,AAPL,5,230.00,USD,TFSA`,
      `${daysAgo(20)},Sell,RY,4,190,CAD,TFSA`,
      `${daysAgo(10)},Dividend,RY,,,CAD,TFSA`,
    ),
  )
  await expect(drawer.getByText('activities.csv')).toBeVisible()
  await expect(drawer.getByLabel('What "Activity Type" means')).toHaveValue('side')
  await expect(drawer.getByLabel('What "Price" means')).toHaveValue('price')
  await drawer.getByRole('button', { name: 'Review 4 rows' }).click()

  await expect(drawer.getByText(/ready to import/)).toHaveText('3 ready to import · 1 not a trade')
  await expect(drawer.locator('#import-rows')).toContainText('RY.TO')
  await drawer.getByRole('button', { name: 'Import 3 trades' }).click()

  await expect(page.getByRole('status')).toHaveText('Imported 3 trades')
  await expect(page.locator('#holdings tbody tr')).toHaveCount(2)
  const [counts] = await sql`select (select count(*) from lots)::int as buys, (select count(*) from sells)::int as sells,
    (select fx_rate_cad::float from lots where symbol = 'AAPL') as rate`
  expect(counts).toEqual({ buys: 2, sells: 1, rate: 1.37 }) // the Bank of Canada's rate for the AAPL buy
})

test('importing the same file again adds nothing', async ({ page }) => {
  await seedLot({ account: 'tfsa', symbol: 'RY.TO', asset_type: 'stock', qty: 10, price: 184.5, currency: 'CAD', bought_at: daysAgo(30) })
  const drawer = await upload(page, csv(`${daysAgo(30)},Buy,RY,10,184.50,CAD,TFSA`))
  await drawer.getByRole('button', { name: 'Review 1 rows' }).click()
  await expect(drawer.locator('#import-rows')).toContainText('Already recorded.')
  await expect(drawer.getByRole('button', { name: 'Import 0 trades' })).toBeDisabled()
})

test('a sell of more than is held refuses the whole file', async ({ page }) => {
  const drawer = await upload(
    page,
    csv(`${daysAgo(30)},Buy,RY,10,184.50,CAD,TFSA`, `${daysAgo(20)},Sell,RY,12,190,CAD,TFSA`),
  )
  await drawer.getByRole('button', { name: 'Review 2 rows' }).click()
  await drawer.getByRole('button', { name: 'Import 2 trades' }).click()
  await expect(drawer.getByRole('alert')).toContainText('Nothing was imported.')
  await expect(drawer.getByRole('alert')).toContainText('sold 12 but held 10')
  expect(await sql`select 1 from lots`).toHaveLength(0)
})

test('a stock missing from the lists is left out unless the owner includes it', async ({ page }) => {
  const drawer = await upload(
    page,
    csv(`${daysAgo(30)},Buy,RY,10,184.50,CAD,TFSA`, `${daysAgo(30)},Buy,XEQT,20,35,CAD,TFSA`),
  )
  await drawer.getByRole('button', { name: 'Review 2 rows' }).click()
  await expect(drawer.getByText(/1 not in the stock lists/)).toBeVisible()
  await expect(drawer.getByRole('button', { name: 'Import 1 trade' })).toBeEnabled()
  await drawer.getByLabel(/Import the 1 not in the lists too/).check()
  await drawer.getByRole('button', { name: 'Import 2 trades' }).click()
  await expect(page.getByRole('status')).toHaveText('Imported 2 trades')
  expect(await sql`select symbol from lots order by symbol`).toEqual([{ symbol: 'RY.TO' }, { symbol: 'XEQT.TO' }])
})
```

- [ ] **Step 2: Run them and see them fail**

Run: `npm run e2e -- e2e/import.spec.ts`
Expected: the build succeeds, then `4 failed` and `1 passed` (the setup). Each test times out waiting for `getByRole('button', { name: 'Import file' })`.

- [ ] **Step 3: Write the server actions**

`web/app/(app)/import.ts`:

```ts
'use server'

import { revalidatePath } from 'next/cache'
import { todayInToronto } from '@/lib/dates'
import { must } from '@/lib/data/fetch'
import { loadFx, loadTrades } from '@/lib/data/portfolio'
import type { ImportTrade } from '@/lib/import/rows'
import { buildLedger } from '@/lib/portfolio/ledger'
import { ACCOUNTS } from '@/lib/portfolio/types'
import type { Trade } from '@/lib/portfolio/types'
import { createClient } from '@/lib/supabase/server'
import { isValidSymbol, tradeCurrency } from '@/lib/symbols'
import { RATE_RANGE, type FormState } from '@/lib/trade-form'

/** The most trades one file may add: years of a personal account's activity. */
const MAX_TRADES = 5000

const failed = (message: string): FormState => ({ message, at: Date.now() })

/** Stock symbols missing from the US and TSX lists (ETFs aren't listed), for the review step. */
export async function unlistedStocks(symbols: string[]): Promise<string[]> {
  const wanted = [...new Set(symbols)].filter((s) => isValidSymbol(s, 'stock')).slice(0, MAX_TRADES)
  if (wanted.length === 0) return []
  const supabase = await createClient()
  const found = new Set<string>()
  for (let i = 0; i < wanted.length; i += 200) {
    const rows = must(
      await supabase.from('symbols').select('symbol').eq('asset_type', 'stock').in('symbol', wanted.slice(i, i + 200)),
    ) as { symbol: string }[]
    for (const r of rows) found.add(r.symbol)
  }
  return wanted.filter((s) => !found.has(s)).sort()
}

const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/

/** The trade the browser sent, checked again: the server trusts nothing it didn't check. */
function checked(t: ImportTrade, today: string): string | null {
  if (t.side !== 'buy' && t.side !== 'sell') return 'a trade that is neither a buy nor a sell'
  if (!ACCOUNTS.includes(t.account)) return 'an unknown account'
  if (t.assetType !== (t.account === 'crypto' ? 'crypto' : 'stock')) return 'an asset in the wrong account'
  if (!isValidSymbol(t.symbol, t.assetType)) return `the symbol "${t.symbol}"`
  if (!(Number.isFinite(t.qty) && t.qty > 0 && Number.isFinite(t.price) && t.price > 0)) return 'a quantity or price below 0'
  if (!ISO_DAY.test(t.day) || t.day > today) return `the date "${t.day}"`
  if (t.fxRate !== null && !(t.fxRate >= RATE_RANGE[0] && t.fxRate <= RATE_RANGE[1])) return `the rate ${t.fxRate}`
  return null
}

/**
 * Add a file's trades (Plan 5c). All or nothing: every trade is checked again, sells must not
 * exceed what's held once the file's buys are in, and USD trades without a rate get the Bank of
 * Canada's for their day.
 */
export async function importTrades(trades: ImportTrade[]): Promise<FormState> {
  if (!Array.isArray(trades) || trades.length === 0) return failed('There are no trades to import.')
  if (trades.length > MAX_TRADES) return failed(`One file can add at most ${MAX_TRADES} trades.`)
  const today = todayInToronto()
  for (const t of trades) {
    const problem = checked(t, today)
    if (problem) return failed(`Nothing was imported: one trade has ${problem}.`)
  }

  const supabase = await createClient()
  const [existing, fx] = await Promise.all([loadTrades(supabase), loadFx(supabase)])
  const incoming: Trade[] = []
  for (const t of trades) {
    const currency = tradeCurrency(t.assetType, t.symbol)
    const rate = currency === 'USD' ? (t.fxRate ?? fx.on(t.day)) : null
    if (currency === 'USD' && rate === null) {
      return failed(`Nothing was imported: there's no Bank of Canada rate yet for ${t.symbol} on ${t.day}.`)
    }
    incoming.push({ ...t, currency, fxRateCad: rate })
  }

  const before = new Set(buildLedger(existing, fx).problems)
  const added = buildLedger([...existing, ...incoming], fx).problems.filter((p) => !before.has(p))
  if (added.length > 0) {
    return failed(`Nothing was imported. ${added.slice(0, 3).join(' ')}${added.length > 3 ? ` (and ${added.length - 3} more)` : ''}`)
  }

  const row = (t: Trade) => ({
    account: t.account,
    symbol: t.symbol,
    asset_type: t.assetType,
    qty: t.qty,
    price: t.price,
    currency: t.currency,
    fx_rate_cad: t.fxRateCad,
  })
  const buys = incoming.filter((t) => t.side === 'buy').map((t) => ({ ...row(t), bought_at: t.day, notes: 'Imported' }))
  const sells = incoming.filter((t) => t.side === 'sell').map((t) => ({ ...row(t), sold_at: t.day }))

  let buyIds: number[] = []
  if (buys.length > 0) {
    const { data, error } = await supabase.from('lots').insert(buys).select('id')
    if (error) return failed(`Nothing was imported: ${error.message}`)
    buyIds = (data as { id: number }[]).map((r) => r.id)
  }
  if (sells.length > 0) {
    const { error } = await supabase.from('sells').insert(sells)
    if (error) {
      // Undo the buys, so a failed file leaves nothing behind.
      if (buyIds.length > 0) await supabase.from('lots').delete().in('id', buyIds)
      return failed(`Nothing was imported: ${error.message}`)
    }
  }
  revalidatePath('/')
  const n = incoming.length
  return { ok: true, message: `Imported ${n} ${n === 1 ? 'trade' : 'trades'}`, at: Date.now() }
}
```

- [ ] **Step 4: Write the drawer and its button**

`web/components/portfolio/ImportDrawer.tsx`:

```tsx
'use client'

import { FileSpreadsheet, TriangleAlert } from 'lucide-react'
import { useEffect, useMemo, useState, useTransition } from 'react'
import { importTrades, unlistedStocks } from '@/app/(app)/import'
import { Drawer } from '@/components/Drawer'
import { longDay } from '@/lib/dates'
import { fmtPrice, fmtQty } from '@/lib/format'
import { parseCsv } from '@/lib/import/csv'
import {
  MEANINGS,
  guessMeanings,
  meaningProblems,
  readRows,
  type DateOrder,
  type ImportRow,
  type Meaning,
} from '@/lib/import/rows'
import { ACCOUNTS, ACCOUNT_LABELS } from '@/lib/portfolio/types'
import type { Account, Trade } from '@/lib/portfolio/types'
import { tradeCurrency } from '@/lib/symbols'

type Step = 'file' | 'columns' | 'review'
const STEPS: { step: Step; label: string }[] = [
  { step: 'file', label: '1 · File' },
  { step: 'columns', label: '2 · Columns' },
  { step: 'review', label: '3 · Review' },
]
const SHOWN = 50

interface Loaded {
  name: string
  rows: string[][]
}

const STATUS: Record<ImportRow['status'] | 'unlisted', string> = {
  ready: 'Ready',
  duplicate: 'Duplicate',
  skipped: 'Left out',
  error: 'Error',
  unlisted: 'Not in the lists',
}

/**
 * Import a broker's activity file (spec §7.1, the mockup's three steps): pick the CSV, say what
 * each column means, review every row, then add the ready ones in one go.
 */
function ImportForm({ existing, today, onDone }: { existing: Trade[]; today: string; onDone: (m: string) => void }) {
  const [step, setStep] = useState<Step>('file')
  const [file, setFile] = useState<Loaded | null>(null)
  const [fileError, setFileError] = useState<string | null>(null)
  const [meanings, setMeanings] = useState<Meaning[]>([])
  const [account, setAccount] = useState<Account | 'column'>('tfsa')
  const [dateOrder, setDateOrder] = useState<DateOrder>('ymd')
  const [unlisted, setUnlisted] = useState<string[] | null>(null)
  const [includeUnlisted, setIncludeUnlisted] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [pending, startTransition] = useTransition()

  const load = async (picked: File | undefined) => {
    setFileError(null)
    if (!picked) return
    const rows = parseCsv(await picked.text())
    if (rows.length < 2) {
      setFileError('That file has no rows under its header.')
      return
    }
    const guessed = guessMeanings(rows[0])
    setFile({ name: picked.name, rows })
    setMeanings(guessed)
    setAccount(guessed.includes('account') ? 'column' : 'tfsa')
    setStep('columns')
  }

  const problems = file ? meaningProblems(meanings, account === 'column') : []
  const read = useMemo(
    () =>
      file && step === 'review'
        ? readRows(file.rows, { meanings, account: account === 'column' ? null : account, dateOrder, today, existing })
        : [],
    [file, step, meanings, account, dateOrder, today, existing],
  )
  const readySymbols = useMemo(
    () => [...new Set(read.filter((r) => r.status === 'ready' && r.trade?.assetType === 'stock').map((r) => r.trade!.symbol))],
    [read],
  )

  // The review asks the server which stock symbols aren't in the lists.
  useEffect(() => {
    if (step !== 'review') return
    let live = true
    unlistedStocks(readySymbols).then((found) => {
      if (live) setUnlisted(found)
    })
    return () => {
      live = false
    }
  }, [step, readySymbols])

  const isUnlisted = (r: ImportRow) => r.status === 'ready' && r.trade?.assetType === 'stock' && (unlisted ?? []).includes(r.trade.symbol)
  const toImport = read.filter((r) => r.status === 'ready' && (includeUnlisted || !isUnlisted(r)))
  const counts = {
    ready: toImport.length,
    unlisted: read.filter(isUnlisted).length,
    duplicate: read.filter((r) => r.status === 'duplicate').length,
    skipped: read.filter((r) => r.status === 'skipped').length,
    error: read.filter((r) => r.status === 'error').length,
  }

  const submit = () =>
    startTransition(async () => {
      setMessage(null)
      const result = await importTrades(toImport.map((r) => r.trade!))
      if (result.ok && result.message) onDone(result.message)
      else setMessage(result.message ?? 'Nothing was imported.')
    })

  return (
    <>
      <div className="drawer-body">
        <div className="flex flex-wrap gap-2 sub">
          {STEPS.map((s) => (
            <span key={s.step} className={`badge ${s.step === step ? 'badge-current' : ''}`} aria-current={s.step === step ? 'step' : undefined}>
              {s.label}
            </span>
          ))}
        </div>

        {step === 'file' && (
          <>
            <label className={`field ${fileError ? 'invalid' : ''}`}>
              <span>Activity file (CSV)</span>
              <input className="input" type="file" accept=".csv,text/csv" onChange={(e) => load(e.target.files?.[0])} />
              <span className="hint">Export your activity from the broker as CSV, for example in Wealthsimple: Activity → Export.</span>
              <span className="error">{fileError}</span>
            </label>
          </>
        )}

        {step !== 'file' && file && (
          <div className="card card-pad" style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
            <FileSpreadsheet style={{ width: 18, height: 18 }} />
            <span style={{ flex: 1 }}>
              <span style={{ fontWeight: 500 }}>{file.name}</span>
              <br />
              <span className="sub">{file.rows.length - 1} rows</span>
            </span>
          </div>
        )}

        {step === 'columns' && file && (
          <>
            <span className="label">Match the columns</span>
            <div className="table-scroll">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>In the file</th>
                    <th>Means</th>
                    <th>Example</th>
                  </tr>
                </thead>
                <tbody>
                  {file.rows[0].map((header, i) => (
                    <tr key={i}>
                      <td className="num">{header || `Column ${i + 1}`}</td>
                      <td>
                        <select
                          className="select"
                          aria-label={`What "${header}" means`}
                          value={meanings[i]}
                          onChange={(e) => setMeanings((m) => m.map((x, j) => (j === i ? (e.target.value as Meaning) : x)))}
                        >
                          {MEANINGS.map((m) => (
                            <option key={m.value} value={m.value}>
                              {m.label}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td className="num sub">{file.rows[1][i] ?? ''}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <label className="field">
                <span>Account</span>
                <select className="select" value={account} onChange={(e) => setAccount(e.target.value as Account | 'column')}>
                  <option value="column">From the Account column</option>
                  {ACCOUNTS.map((a) => (
                    <option key={a} value={a}>
                      All {ACCOUNT_LABELS[a]}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span>Dates like 03/10/2026 are</span>
                <select className="select" value={dateOrder} onChange={(e) => setDateOrder(e.target.value as DateOrder)}>
                  <option value="ymd">Year, month, day</option>
                  <option value="mdy">Month/day/year</option>
                  <option value="dmy">Day/month/year</option>
                </select>
              </label>
            </div>
            {problems.length > 0 && (
              <div className="banner warn" role="alert">
                <TriangleAlert />
                <div>{problems.join(' ')}</div>
              </div>
            )}
          </>
        )}

        {step === 'review' && (
          <>
            <p className="sub" style={{ margin: 0 }}>
              <b className="num">{counts.ready}</b> ready to import
              {counts.unlisted > 0 && ` · ${counts.unlisted} not in the stock lists`}
              {counts.duplicate > 0 && ` · ${counts.duplicate} already recorded or repeated`}
              {counts.skipped > 0 && ` · ${counts.skipped} not ${counts.skipped === 1 ? 'a trade' : 'trades'}`}
              {counts.error > 0 && ` · ${counts.error} with errors`}
            </p>
            {counts.unlisted > 0 && (
              <label style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 13 }}>
                <input type="checkbox" checked={includeUnlisted} onChange={(e) => setIncludeUnlisted(e.target.checked)} />
                Import the {counts.unlisted} not in the lists too (ETFs aren&apos;t listed)
              </label>
            )}
            {message && (
              <div className="banner danger" role="alert">
                <TriangleAlert />
                <div>{message}</div>
              </div>
            )}
            <div className="table-scroll">
              <table className="data-table" id="import-rows">
                <thead>
                  <tr>
                    <th>Line</th>
                    <th>Trade</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {read.slice(0, SHOWN).map((r) => {
                    const status = isUnlisted(r) ? 'unlisted' : r.status
                    const t = r.trade
                    return (
                      <tr key={r.line}>
                        <td className="num sub">{r.line}</td>
                        <td>
                          {t ? (
                            <>
                              {t.side === 'buy' ? 'Buy' : 'Sell'} {fmtQty(t.qty)} <span className="sym">{t.symbol}</span>
                              <br />
                              <span className="sub">
                                {ACCOUNT_LABELS[t.account]} · {longDay(t.day)} · {fmtPrice(t.price, tradeCurrency(t.assetType, t.symbol))}
                              </span>
                            </>
                          ) : (
                            <span className="sub">{r.reason}</span>
                          )}
                        </td>
                        <td>
                          <span className="badge">{STATUS[status]}</span>
                          {t && r.reason && (
                            <>
                              <br />
                              <span className="sub">{r.reason}</span>
                            </>
                          )}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
            {read.length > SHOWN && <p className="sub" style={{ margin: 0 }}>The first {SHOWN} of {read.length} rows are shown.</p>}
          </>
        )}
      </div>
      <div className="drawer-foot">
        {step === 'columns' && (
          <>
            <button type="button" className="btn btn-secondary" onClick={() => setStep('file')}>
              Back
            </button>
            <button type="button" className="btn btn-primary" disabled={problems.length > 0} onClick={() => { setUnlisted(null); setStep('review') }}>
              Review {file ? file.rows.length - 1 : 0} rows
            </button>
          </>
        )}
        {step === 'review' && (
          <>
            <button type="button" className="btn btn-secondary" onClick={() => setStep('columns')}>
              Back
            </button>
            <button type="button" className="btn btn-primary" disabled={pending || unlisted === null || counts.ready === 0} onClick={submit}>
              {pending ? 'Importing…' : `Import ${counts.ready} ${counts.ready === 1 ? 'trade' : 'trades'}`}
            </button>
          </>
        )}
      </div>
    </>
  )
}

/** The drawer around the import form. Each opening starts afresh. */
export function ImportDrawer({
  open,
  round,
  existing,
  today,
  onClose,
  onDone,
}: {
  open: boolean
  round: number
  existing: Trade[]
  today: string
  onClose: () => void
  onDone: (message: string) => void
}) {
  return (
    <Drawer id="import-drawer" title="Import a file" open={open} onClose={onClose}>
      <ImportForm key={round} existing={existing} today={today} onDone={onDone} />
    </Drawer>
  )
}
```

In `web/components/portfolio/TradeForms.tsx`, replace:

```tsx
import { Minus, Plus, TriangleAlert } from 'lucide-react'
```

with:

```tsx
import { FileUp, Minus, Plus, TriangleAlert } from 'lucide-react'
```

In `web/components/portfolio/TradeForms.tsx`, replace:

```tsx
import { Drawer } from '@/components/Drawer'
```

with:

```tsx
import { Drawer } from '@/components/Drawer'
import { ImportDrawer } from '@/components/portfolio/ImportDrawer'
```

In `web/components/portfolio/TradeForms.tsx`, replace:

```tsx
import type { Account } from '@/lib/portfolio/types'
```

with:

```tsx
import type { Account, Trade } from '@/lib/portfolio/types'
```

In `web/components/portfolio/TradeForms.tsx`, replace:

```tsx
/** The Buy and Sell buttons in the page head, and their drawers. */
export function TradeButtons({ sellable, rates, today }: { sellable: SellOption[]; rates: FxRate[]; today: string }) {
  const toast = useToast()
  const [open, setOpen] = useState<'buy' | 'sell' | null>(null)
  // Each opening starts a fresh form.
  const [round, setRound] = useState(0)
  const show = (which: 'buy' | 'sell') => {
```

with:

```tsx
/** The Import, Sell and Buy buttons in the page head, and their drawers. */
export function TradeButtons({
  sellable,
  rates,
  today,
  existing,
}: {
  sellable: SellOption[]
  rates: FxRate[]
  today: string
  /** Trades already recorded, so an import can skip them. */
  existing: Trade[]
}) {
  const toast = useToast()
  const [open, setOpen] = useState<'buy' | 'sell' | 'import' | null>(null)
  // Each opening starts a fresh form.
  const [round, setRound] = useState(0)
  const show = (which: 'buy' | 'sell' | 'import') => {
```

In `web/components/portfolio/TradeForms.tsx`, replace:

```tsx
      <div className="flex flex-wrap gap-2">
```

with:

```tsx
      <div className="flex flex-wrap gap-2">
        <button type="button" className="btn btn-secondary" onClick={() => show('import')}>
          <FileUp />
          Import file
        </button>
```

In `web/components/portfolio/TradeForms.tsx`, replace:

```tsx
        <SellForm key={`sell-${round}`} options={sellable} rates={rates} today={today} onDone={done} onCancel={close} />
      </Drawer>
```

with:

```tsx
        <SellForm key={`sell-${round}`} options={sellable} rates={rates} today={today} onDone={done} onCancel={close} />
      </Drawer>
      <ImportDrawer open={open === 'import'} round={round} existing={existing} today={today} onClose={close} onDone={done} />
```

In `web/app/(app)/page.tsx`, replace:

```tsx
        <TradeButtons sellable={view.sellable} rates={[...data.fx.rates]} today={today} />
```

with:

```tsx
        <TradeButtons sellable={view.sellable} rates={[...data.fx.rates]} today={today} existing={data.trades} />
```

Append to `web/app/styles/pages.css`, after one blank line:

```css
/* ---------- File import (Plan 5c; portfolio_1.html's import drawer) ---------- */
.badge-current { border-color: var(--foreground); color: var(--foreground); }
#import-rows td { white-space: normal; }
```

- [ ] **Step 5: Run the tests**

Run: `npm test`
Expected: `Test Files  14 passed (14)`, `Tests  96 passed (96)`: this task adds no unit tests.

Run: `npm run e2e`
Expected: `36 passed`. Then `npm run lint` and `npm run typecheck` are clean.

- [ ] **Step 6: Commit**

```bash
git add "web/app/(app)/import.ts" web/components/portfolio/ImportDrawer.tsx web/components/portfolio/TradeForms.tsx "web/app/(app)/page.tsx" web/app/styles/pages.css web/e2e/import.spec.ts
git commit -m "feat: import a broker file from My Portfolio"
```

---
### Task 6: Show Source health

**Files:**
- Create: `web/lib/sources.ts`, `web/lib/data/sources.ts`, `web/components/sources/SourceTable.tsx`, `web/app/(app)/sources/page.tsx`
- Modify: `web/lib/dates.ts`, `web/lib/data/runs.ts`, `web/components/shell/nav.ts`, `web/components/shell/Shell.tsx`, `web/app/styles/pages.css`, `web/e2e/db.ts`, `web/e2e/navigation.spec.ts`
- Test: `web/lib/sources.test.ts`, `web/lib/dates.test.ts`, `web/e2e/sources.spec.ts`

**Interfaces:**
- Consumes:
  - Task 1's tables: `sources`, `source_health`, `source_last_ok`.
  - Task 1's function `database_size()`.
  - `Run` and `runWhen` from `lib/runs.ts`; `Tabs`.
- Produces (Task 7 uses the lines marked ★):
  - In `lib/sources.ts`:
    - types: `SourceStatus`, `Category`, `Source { name, category, core, cadence, assetTypes, markets }` and `Health { source, status, latencyMs, records, error, failures, attemptedAt }`;
    - `CATEGORY_LABELS` and `BREAKER_THRESHOLD = 3`;
    - ★ `answered(status)`: `ok` or `partial`;
    - ★ `Coverage { assetType, market }`, `covers(source, coverage)` and `coverageName(coverage)` ("TSX stocks", "coins");
    - ★ `SourceRow extends Source { run, check, lastOk, problem }`, built by `sourceRows(sources, run, checks, lastOk)`. Rows are sorted problems first, then core sources, then by name;
    - `tally(rows, pick)`;
    - `sentimentNotice(summary)`: why a run's headlines went unscored, or null;
    - `fmtLatency(ms)` ("from cache", "262 ms", "1.4 s", "7 min 10 s") and `fmtSize(bytes)` ("14 MB").
  - In `lib/dates.ts`: ★ `timeOrDate(iso, now?)`, on Toronto's clock: "2:53 p.m." today, "Oct 15, 5:53 p.m." on an earlier day.
  - In `lib/data/runs.ts`: `latestFinishedRun(supabase)`.
  - In `lib/data/sources.ts`:
    - ★ `loadSourceHealth(supabase): Promise<{ run, rows, checkedAt }>`;
    - `databaseSize(supabase): Promise<number | null>`.
  - The `/sources` page.
  - A "Sources" nav item, a non-primary item, so it sits under More on phones.
  - The status bar's "30/33 sources" pill links to `/sources`.
  - In `e2e/db.ts`:
    - `resetData` also empties `news_items` and `sources`;
    - `seedRun` returns the new run's id;
    - `SOURCES`, `seedSources()`, and `seedHealth(runId | null, attemptedAt, rows)`.

- [ ] **Step 1: Write the failing unit tests**

`web/lib/sources.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { covers, fmtLatency, fmtSize, sentimentNotice, sourceRows, tally, type Health, type Source } from './sources'

const source = (name: string, extra: Partial<Source> = {}): Source => ({
  name,
  category: 'prices',
  core: false,
  cadence: 'per_run',
  assetTypes: ['stock'],
  markets: ['US', 'TSX'],
  ...extra,
})
const health = (name: string, status: Health['status'], extra: Partial<Health> = {}): Health => ({
  source: name,
  status,
  latencyMs: 100,
  records: 10,
  error: null,
  failures: 0,
  attemptedAt: '2026-10-16T19:10:00Z',
  ...extra,
})

describe('coverage', () => {
  const finra = source('finra_short_volume', { markets: ['US'] })
  const coins = source('coingecko', { assetTypes: ['crypto'], markets: [] })

  it('matches a stock by its market and a coin by its asset type', () => {
    expect(covers(finra, { assetType: 'stock', market: 'US' })).toBe(true)
    expect(covers(finra, { assetType: 'stock', market: 'TSX' })).toBe(false)
    expect(covers(coins, { assetType: 'crypto', market: null })).toBe(true)
    expect(covers(coins, { assetType: 'stock', market: 'US' })).toBe(false)
  })
})

describe('sourceRows', () => {
  const sources = [
    source('yfinance_bars', { core: true }),
    source('sec_form4', { category: 'fundamentals', markets: ['US'] }),
    source('fred', { category: 'macro', core: true }),
    source('new_feed', { category: 'news' }),
  ]
  const run = [
    health('yfinance_bars', 'ok'),
    health('sec_form4', 'partial', { error: 'PartialFetch: stopped after 41 of 300 symbols' }),
    health('fred', 'ok'),
    health('gone', 'failed'), // no longer in the registry
  ]
  const checks = [
    health('fred', 'failed', { attemptedAt: '2026-10-16T19:09:00Z', failures: 3 }),
    health('fred', 'ok', { attemptedAt: '2026-10-15T19:09:00Z' }),
    health('yfinance_bars', 'ok', { attemptedAt: '2026-10-16T19:09:00Z' }),
  ]
  const rows = sourceRows(sources, run, checks, new Map([['fred', '2026-10-16T19:10:00Z']]))

  it('lists every registered source, problems first, then core sources, then by name', () => {
    expect(rows.map((r) => r.name)).toEqual(['fred', 'new_feed', 'sec_form4', 'yfinance_bars'])
    expect(rows.map((r) => r.problem)).toEqual([true, true, true, false])
  })

  it("joins each source's run result, its newest daily check and its last good answer", () => {
    const fred = rows[0]
    expect(fred.run?.status).toBe('ok')
    expect(fred.check).toMatchObject({ status: 'failed', failures: 3 }) // the newest check, not the older ok
    expect(fred.lastOk).toBe('2026-10-16T19:10:00Z')
    expect(rows[1]).toMatchObject({ name: 'new_feed', run: null, check: null, lastOk: null }) // not run yet
  })

  it('counts a run or a check by status', () => {
    expect(tally(rows, (r) => r.run)).toEqual({ total: 4, ok: 2, partial: 1, stale: 0, failed: 0, skipped: 0, missing: 1 })
    expect(tally(rows, (r) => r.check)).toMatchObject({ total: 4, ok: 1, failed: 1, missing: 2 })
  })
})

describe('sentimentNotice', () => {
  it("says why a run's headlines went unscored, and nothing when FinBERT scored them", () => {
    const news = (sentiment: string) => ({ news: { items: 40, sentiment } })
    expect(sentimentNotice(news('finbert'))).toBeNull()
    expect(sentimentNotice({})).toBeNull() // a run from before Plan 2f
    expect(sentimentNotice(news('unavailable'))).toMatch(/^FinBERT couldn't be loaded/)
    expect(sentimentNotice(news('skipped: run budget'))).toMatch(/^The run ran out of time/)
    expect(sentimentNotice(news('failed: OSError: no space left'))).toBe(
      "Scoring headlines failed (OSError: no space left), so this run's headlines have no sentiment.",
    )
    expect(sentimentNotice(news('no items'))).toBe('No news source returned a headline in this run.')
  })
})

describe('formats', () => {
  it('writes latency the way the mockup does', () => {
    expect([fmtLatency(0), fmtLatency(262), fmtLatency(1356), fmtLatency(430383)]).toEqual([
      'from cache',
      '262 ms',
      '1.4 s',
      '7 min 10 s',
    ])
  })

  it('writes database sizes in MB, or GB past 1,000 MB', () => {
    expect([fmtSize(14_200_000), fmtSize(3_400_000), fmtSize(1_250_000_000)]).toEqual(['14 MB', '3.4 MB', '1.25 GB'])
  })
})
```

`web/lib/dates.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { timeOrDate } from './dates'

describe('timeOrDate', () => {
  it("shows today's time alone and an earlier day's with its date, on Toronto's clock", () => {
    const now = new Date('2026-10-16T20:00:00Z')
    expect(timeOrDate('2026-10-16T18:53:00Z', now)).toMatch(/^2:53\sp\.m\.$/)
    expect(timeOrDate('2026-10-15T21:53:00Z', now)).toMatch(/^Oct 15, 5:53\sp\.m\.$/)
    expect(timeOrDate('2026-10-16T03:30:00Z', now)).toMatch(/^Oct 15, 11:30\sp\.m\.$/) // still Oct 15 in Toronto
  })
})
```

- [ ] **Step 2: Run them and see them fail**

Run: `npm test -- lib/sources.test.ts lib/dates.test.ts`
Expected: `Test Files  2 failed (2)`: `Error: Cannot find module './sources'`, and `TypeError: timeOrDate is not a function`.

- [ ] **Step 3: Write the source helpers and the Toronto clock**

`web/lib/sources.ts`:

```ts
/** How the Source health and Ticker pages describe the pipeline's sources (spec §9, Plan 5c). */

import type { AssetType, Market } from './portfolio/types'

export type SourceStatus = 'ok' | 'partial' | 'stale' | 'failed' | 'skipped'
export type Category = 'prices' | 'fundamentals' | 'options' | 'macro' | 'news' | 'social' | 'catalysts' | 'onchain'

/** A collector in the pipeline's registry, as each run writes it to `sources`. */
export interface Source {
  name: string
  category: Category
  core: boolean
  cadence: 'per_run' | 'daily' | 'weekly'
  assetTypes: AssetType[]
  /** The stock markets it covers; empty for a coin-only source. */
  markets: Market[]
}

/** One `source_health` row: a source's result in a run or a daily check. */
export interface Health {
  source: string
  status: SourceStatus
  latencyMs: number
  records: number
  error: string | null
  /** Failures in a row; the pipeline skips a source for the rest of the day after 3. */
  failures: number
  attemptedAt: string
}

export const CATEGORY_LABELS: Record<Category, string> = {
  prices: 'Prices',
  fundamentals: 'Fundamentals',
  options: 'Options',
  macro: 'Macro',
  news: 'News',
  social: 'Social',
  catalysts: 'Catalysts',
  onchain: 'On-chain',
}

/** The pipeline's circuit breaker opens after this many failures in a row (runner.py). */
export const BREAKER_THRESHOLD = 3

/** A source answered when it returned fresh records, all of them or some; a stale one served old values. */
export const answered = (status: SourceStatus | undefined): boolean => status === 'ok' || status === 'partial'

export interface Coverage {
  assetType: AssetType
  /** Null for a coin. */
  market: Market | null
}

export const covers = (source: Source, asset: Coverage): boolean =>
  source.assetTypes.includes(asset.assetType) && (asset.market === null || source.markets.includes(asset.market))

/** "US stocks", "TSX stocks", "coins" */
export const coverageName = (asset: Coverage): string => (asset.market === null ? 'coins' : `${asset.market} stocks`)

export interface SourceRow extends Source {
  /** Its result in the latest run; null when that run didn't call it. */
  run: Health | null
  /** Its newest daily check. */
  check: Health | null
  /** When it last answered, in a run or a check. */
  lastOk: string | null
  problem: boolean
}

/**
 * Every registered source with its result in the latest run, its newest daily check and its last
 * good answer. A source with anything but "ok" in either is a problem. Problems come first, then
 * core sources, then by name.
 */
export function sourceRows(
  sources: readonly Source[],
  run: readonly Health[],
  checks: readonly Health[],
  lastOk: ReadonlyMap<string, string>,
): SourceRow[] {
  const inRun = new Map(run.map((h) => [h.source, h]))
  const newestCheck = new Map<string, Health>()
  for (const h of checks) {
    const seen = newestCheck.get(h.source)
    if (!seen || h.attemptedAt > seen.attemptedAt) newestCheck.set(h.source, h)
  }
  return sources
    .map((s) => {
      const r = inRun.get(s.name) ?? null
      const check = newestCheck.get(s.name) ?? null
      return {
        ...s,
        run: r,
        check,
        lastOk: lastOk.get(s.name) ?? null,
        problem: r?.status !== 'ok' || (check !== null && check.status !== 'ok'),
      }
    })
    .sort(
      (a, b) =>
        Number(b.problem) - Number(a.problem) || Number(b.core) - Number(a.core) || (a.name < b.name ? -1 : 1),
    )
}

export interface Tally extends Record<SourceStatus, number> {
  total: number
  /** Sources without a result. */
  missing: number
}

export function tally(rows: readonly SourceRow[], pick: (row: SourceRow) => Health | null): Tally {
  const counts: Tally = { total: rows.length, ok: 0, partial: 0, stale: 0, failed: 0, skipped: 0, missing: 0 }
  for (const row of rows) {
    const h = pick(row)
    if (h) counts[h.status] += 1
    else counts.missing += 1
  }
  return counts
}

/**
 * Why the run's headlines have no sentiment, from its summary's `news.sentiment` (Plan 2f): null
 * when FinBERT scored them, or for a run from before news was collected.
 */
export function sentimentNotice(summary: Record<string, unknown>): string | null {
  const news = summary.news as { sentiment?: unknown } | undefined
  const status = typeof news?.sentiment === 'string' ? news.sentiment : null
  if (status === null || status === 'finbert') return null
  if (status === 'unavailable') return "FinBERT couldn't be loaded (is the nlp extra installed?), so this run's headlines have no sentiment."
  if (status === 'skipped: run budget') return "The run ran out of time before scoring, so this run's headlines have no sentiment."
  if (status === 'no items') return 'No news source returned a headline in this run.'
  if (status === 'not run') return 'The run has no news sources, so it collected no headlines.'
  return `Scoring headlines failed (${status.replace(/^failed: /, '')}), so this run's headlines have no sentiment.`
}

/** "from cache" when the source made no request, then "262 ms", "1.4 s", "7 min 10 s". */
export function fmtLatency(ms: number): string {
  if (ms === 0) return 'from cache'
  if (ms < 1000) return `${ms} ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`
  const s = Math.round(ms / 1000)
  return `${Math.floor(s / 60)} min ${s % 60} s`
}

/** "3.4 MB", "14 MB", "1.25 GB" (decimal units, as Supabase's 500 MB limit). */
export function fmtSize(bytes: number): string {
  const mb = bytes / 1e6
  if (mb >= 1000) return `${(mb / 1000).toFixed(2)} GB`
  return `${mb < 10 ? mb.toFixed(1) : Math.round(mb)} MB`
}
```

Append to `web/lib/dates.ts`, after one blank line:

```ts
const clock = new Intl.DateTimeFormat('en-CA', { hour: 'numeric', minute: '2-digit', timeZone: 'America/Toronto' })
const dated = new Intl.DateTimeFormat('en-CA', {
  month: 'short',
  day: 'numeric',
  hour: 'numeric',
  minute: '2-digit',
  timeZone: 'America/Toronto',
})

/** A moment on Toronto's clock: "2:53 p.m." today, "Oct 15, 5:53 p.m." on an earlier day. */
export const timeOrDate = (iso: string, now: Date = new Date()): string => {
  const at = new Date(iso)
  return todayInToronto(at) === todayInToronto(now) ? clock.format(at) : dated.format(at)
}
```

- [ ] **Step 4: Run them**

Run: `npm test -- lib/sources.test.ts lib/dates.test.ts`
Expected: `Test Files  2 passed (2)`, `Tests  8 passed (8)`.

- [ ] **Step 5: Write the failing browser tests and their seeding helpers**

In `web/e2e/db.ts`, replace:

```ts
  await sql`truncate lots, sells, watchlist, runs, daily_closes, fx_rates, symbols restart identity cascade`
```

with:

```ts
  // runs cascades to source_health and features_live
  await sql`truncate lots, sells, watchlist, runs, daily_closes, fx_rates, symbols, news_items, sources
            restart identity cascade`
```

In `web/e2e/db.ts`, replace:

```ts
  const finished = new Date(run.finished)
  await sql`insert into runs (kind, et_date, started_at, finished_at, status, published, sources_ok, sources_total, summary)
            values (${run.kind}, ${todayInToronto(finished)}, ${new Date(finished.getTime() - 15 * 60_000)}, ${finished},
                    ${run.status}, ${run.published}, 30, 33, ${sql.json(run.summary ?? {})})`
}
```

with:

```ts
  const finished = new Date(run.finished)
  const [row] = await sql`insert into runs (kind, et_date, started_at, finished_at, status, published, sources_ok, sources_total, summary)
            values (${run.kind}, ${todayInToronto(finished)}, ${new Date(finished.getTime() - 15 * 60_000)}, ${finished},
                    ${run.status}, ${run.published}, 30, 33, ${sql.json(run.summary ?? {})}) returning id`
  return row.id as number
}

/** A small registry like the pipeline's: US-only filings, a source for both markets, a coin source. */
export const SOURCES = [
  { name: 'yfinance_bars', category: 'prices', core: true, cadence: 'per_run', asset_types: ['stock'], markets: ['TSX', 'US'] },
  { name: 'google_news', category: 'news', core: true, cadence: 'per_run', asset_types: ['crypto', 'stock'], markets: ['TSX', 'US'] },
  { name: 'sec_form4', category: 'fundamentals', core: false, cadence: 'daily', asset_types: ['stock'], markets: ['US'] },
  { name: 'sec_8k', category: 'catalysts', core: false, cadence: 'daily', asset_types: ['stock'], markets: ['US'] },
  { name: 'coingecko', category: 'prices', core: true, cadence: 'per_run', asset_types: ['crypto'], markets: [] },
]

export async function seedSources() {
  await sql`insert into sources ${sql(SOURCES, 'name', 'category', 'core', 'cadence', 'asset_types', 'markets')}`
}

/** Health rows for a run, or for a daily check when `runId` is null. */
export async function seedHealth(
  runId: number | null,
  attemptedAt: string,
  rows: { source: string; status: string; latency_ms?: number; records?: number; error?: string; consecutive_failures?: number }[],
) {
  for (const r of rows) {
    await sql`insert into source_health ${sql({
      run_id: runId,
      context: runId === null ? 'health' : 'run',
      latency_ms: 100,
      records: 10,
      error: null,
      consecutive_failures: 0,
      attempted_at: attemptedAt,
      ...r,
    })}`
  }
}
```

`web/e2e/sources.spec.ts`:

```ts
import { expect, test } from '@playwright/test'
import { resetData, seedHealth, seedRun, seedSources } from './db'

test.beforeEach(resetData)

test("every source shows this run's result, its daily check and its last answer, problems first", async ({ page }) => {
  const finished = new Date(Date.now() - 3_600_000)
  const runId = await seedRun({
    kind: 'pre_close',
    status: 'degraded',
    published: true,
    finished: finished.toISOString(),
    summary: { news: { items: 120, sentiment: 'unavailable' } },
  })
  await seedSources()
  const checkedAt = new Date(finished.getTime() - 60_000).toISOString()
  await seedHealth(null, checkedAt, [
    { source: 'yfinance_bars', status: 'ok' },
    { source: 'google_news', status: 'ok' },
    { source: 'sec_form4', status: 'ok' },
    { source: 'sec_8k', status: 'failed', error: 'HTTPStatusError: 503', consecutive_failures: 2 },
    { source: 'coingecko', status: 'ok' },
  ])
  await seedHealth(runId, finished.toISOString(), [
    { source: 'yfinance_bars', status: 'ok', latency_ms: 185_484, records: 472_845 },
    { source: 'google_news', status: 'ok', latency_ms: 0, records: 7612 },
    { source: 'sec_form4', status: 'partial', error: 'PartialFetch: stopped after 41 of 300 symbols' },
    { source: 'sec_8k', status: 'failed', error: 'HTTPStatusError: 503', consecutive_failures: 3 },
    { source: 'coingecko', status: 'ok' },
  ])

  await page.goto('/sources')
  await expect(page.getByRole('heading', { name: 'Source health', level: 1 })).toBeVisible()
  const summary = page.getByRole('region', { name: 'Summary' })
  await expect(summary.locator('.card').nth(0)).toContainText('3/5 OK1 partial · 1 failed')
  await expect(summary.locator('.card').nth(1)).toContainText('4/5 OK1 failed')
  await expect(summary.locator('.card').nth(2)).toContainText('3/3 OK')
  await expect(summary.locator('.card').nth(3)).toContainText(/\d+(\.\d)? MB/)
  await expect(page.getByRole('note')).toHaveText(/^News sentiment: FinBERT couldn't be loaded/)

  const rows = page.locator('#sources tbody tr')
  await expect(rows.locator('td:first-child .sym')).toHaveText(['sec_8k', 'sec_form4', 'coingecko', 'google_news', 'yfinance_bars'])
  await expect(rows.nth(0)).toContainText('open · 3 fails in a row')
  await expect(rows.nth(0)).toContainText('never') // it has never answered
  await expect(rows.nth(3)).toContainText('from cache')
  await expect(rows.nth(4)).toContainText('3 min 5 s')
  await expect(rows.nth(4)).toContainText('472,845')

  await rows.nth(1).getByRole('button', { name: 'partial' }).click()
  await expect(page.locator('#err-sec_form4')).toHaveText('This run: PartialFetch: stopped after 41 of 300 symbols')
  await page.getByRole('tab', { name: 'Problems 2' }).click()
  await expect(rows.locator('td:first-child .sym')).toHaveText(['sec_8k', 'sec_form4'])
  await page.getByRole('tab', { name: 'Core 3' }).click()
  await expect(rows.locator('td:first-child .sym')).toHaveText(['coingecko', 'google_news', 'yfinance_bars'])
})

test("the status bar's sources pill opens Source health, which waits for the first run", async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('link', { name: /sources$/ })).toHaveCount(0) // no run, no pill
  await seedRun({ kind: 'pre_open', status: 'success', published: true, finished: new Date(Date.now() - 3_600_000).toISOString() })
  await page.reload()
  await page.getByRole('link', { name: '30/33 sources' }).click()
  await expect(page).toHaveURL(/\/sources$/)
  await expect(page.getByText('No sources yet. The next run or daily check lists them here.')).toBeVisible()
})
```

In `web/e2e/navigation.spec.ts`, replace:

```ts
  await sidebar.getByRole('link', { name: 'Settings' }).click()
  await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible()
})
```

with:

```ts
  await sidebar.getByRole('link', { name: 'Sources' }).click()
  await expect(page.getByRole('heading', { name: 'Source health' })).toBeVisible()
  await sidebar.getByRole('link', { name: 'Settings' }).click()
  await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible()
})
```

- [ ] **Step 6: Run them and see them fail**

Run: `npm run e2e -- e2e/sources.spec.ts e2e/navigation.spec.ts`
Expected: the build succeeds, then `3 failed` and `3 passed` (the setup and the two phone tests). The sidebar has no Sources link, `/sources` is a 404 with no "Source health" heading, and the status bar's pill isn't a link.

- [ ] **Step 7: Write the loaders**

Append to `web/lib/data/runs.ts`, after one blank line:

```ts
/** The newest run that finished, published or not, for the Source health page. */
export async function latestFinishedRun(supabase: Supabase): Promise<Run | null> {
  const rows = must(
    await supabase.from('runs').select(COLUMNS).neq('status', 'running').order('id', { ascending: false }).limit(1),
  ) as Run[]
  return rows[0] ?? null
}
```

`web/lib/data/sources.ts`:

```ts
import 'server-only'
import type { AssetType, Market } from '../portfolio/types'
import type { Run } from '../runs'
import { sourceRows, type Category, type Health, type Source, type SourceRow, type SourceStatus } from '../sources'
import type { Supabase } from '../supabase/server'
import { must } from './fetch'
import { latestFinishedRun } from './runs'

interface HealthRow {
  source: string
  status: SourceStatus
  latency_ms: number
  records: number
  error: string | null
  consecutive_failures: number
  attempted_at: string
}

const HEALTH_COLUMNS = 'source, status, latency_ms, records, error, consecutive_failures, attempted_at'

const toHealth = (r: HealthRow): Health => ({
  source: r.source,
  status: r.status,
  latencyMs: r.latency_ms,
  records: r.records,
  error: r.error,
  failures: r.consecutive_failures,
  attemptedAt: r.attempted_at,
})

/** Each daily check writes one row per source, so a month of checks reaches every source's newest. */
const CHECK_ROWS = 1000

export interface SourceHealth {
  /** The newest finished run; its rows are the "This run" column. */
  run: Run | null
  rows: SourceRow[]
  /** When the newest daily check ran. */
  checkedAt: string | null
}

/** The registry, with each source's latest run result, newest daily check and last good answer. */
export async function loadSourceHealth(supabase: Supabase): Promise<SourceHealth> {
  const [registry, run, checks, lastOk] = await Promise.all([
    supabase.from('sources').select('name, category, core, cadence, asset_types, markets').order('name'),
    latestFinishedRun(supabase),
    supabase
      .from('source_health')
      .select(HEALTH_COLUMNS)
      .eq('context', 'health')
      .order('attempted_at', { ascending: false })
      .limit(CHECK_ROWS),
    supabase.from('source_last_ok').select('source, attempted_at'),
  ])
  const runRows = run
    ? (must(
        await supabase.from('source_health').select(HEALTH_COLUMNS).eq('context', 'run').eq('run_id', run.id),
      ) as HealthRow[])
    : []
  const sources = (
    must(registry) as {
      name: string
      category: Category
      core: boolean
      cadence: Source['cadence']
      asset_types: AssetType[]
      markets: Market[]
    }[]
  ).map((r) => ({ name: r.name, category: r.category, core: r.core, cadence: r.cadence, assetTypes: r.asset_types, markets: r.markets }))
  const checkRows = (must(checks) as HealthRow[]).map(toHealth)
  return {
    run,
    rows: sourceRows(
      sources,
      runRows.map(toHealth),
      checkRows,
      new Map((must(lastOk) as { source: string; attempted_at: string }[]).map((r) => [r.source, r.attempted_at])),
    ),
    checkedAt: checkRows[0]?.attemptedAt ?? null,
  }
}

/** The database's size in bytes; null when Postgres won't say (anyone but the owner). */
export async function databaseSize(supabase: Supabase): Promise<number | null> {
  const size = must(await supabase.rpc('database_size')) as number | string | null
  return size === null ? null : Number(size)
}
```

- [ ] **Step 8: Write the page, and link it from the nav and the status bar**

`web/components/sources/SourceTable.tsx`:

```tsx
'use client'

import { Fragment, useState } from 'react'
import { Tabs } from '@/components/Tabs'

export interface SourceLine {
  name: string
  kind: string
  core: boolean
  problem: boolean
  /** The run's status, or null when the run didn't call it. */
  status: string | null
  time: string
  records: string
  /** The records under the time on phones: "1 record", "5,575 records". */
  recordsMeta: string
  breaker: string
  check: string | null
  lastOk: string
  errors: string[]
}

type Filter = 'all' | 'problems' | 'core'

/** Every source, filterable as in sources_1.html; a problem's errors open under its row. */
export function SourceTable({ lines }: { lines: SourceLine[] }) {
  const [filter, setFilter] = useState<Filter>('all')
  const [open, setOpen] = useState<string | null>(null)
  const problems = lines.filter((l) => l.problem).length
  const core = lines.filter((l) => l.core).length
  const shown = lines.filter((l) => filter === 'all' || (filter === 'problems' ? l.problem : l.core))

  return (
    <>
      <div className="section-head">
        <h2>All sources</h2>
        <Tabs
          items={[
            { value: 'all', label: `All ${lines.length}` },
            { value: 'problems', label: `Problems ${problems}` },
            { value: 'core', label: `Core ${core}` },
          ]}
          value={filter}
          onChange={setFilter}
          label="Show"
        />
      </div>
      <div className="table-scroll">
        <table className="data-table" id="sources">
          <thead>
            <tr>
              <th>Source</th>
              <th>Kind</th>
              <th>This run</th>
              <th className="r">Time</th>
              <th className="r">Records</th>
              <th>Breaker</th>
              <th>Daily check</th>
              <th>Last answered</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((l) => {
              const expanded = open === l.name
              const badge = (
                <>
                  <span className={`dot ${l.status ?? 'skipped'}`} />
                  {l.status ?? 'not run'}
                </>
              )
              return (
                <Fragment key={l.name}>
                  <tr>
                    <td>
                      <span className="sym">{l.name}</span>
                      {l.core && <span className="core">core</span>}
                    </td>
                    <td className="sub">{l.kind}</td>
                    <td>
                      {l.errors.length ? (
                        <button
                          type="button"
                          className="badge"
                          aria-expanded={expanded}
                          aria-controls={`err-${l.name}`}
                          title="Show the error"
                          onClick={() => setOpen(expanded ? null : l.name)}
                        >
                          {badge}
                        </button>
                      ) : (
                        <span className="badge">{badge}</span>
                      )}
                    </td>
                    <td className="r num" data-meta={` · ${l.recordsMeta}`}>
                      {l.time}
                    </td>
                    <td className="r num">{l.records}</td>
                    <td className="sub">{l.breaker}</td>
                    <td>
                      {l.check ? (
                        <span className="badge">
                          <span className={`dot ${l.check}`} />
                          {l.check}
                        </span>
                      ) : (
                        <span className="sub">—</span>
                      )}
                    </td>
                    <td className="sub">{l.lastOk}</td>
                  </tr>
                  {expanded && (
                    <tr className="err" id={`err-${l.name}`}>
                      <td colSpan={8}>
                        {l.errors.map((e) => (
                          <div key={e}>{e}</div>
                        ))}
                      </td>
                    </tr>
                  )}
                </Fragment>
              )
            })}
          </tbody>
        </table>
      </div>
      <p className="sub" style={{ margin: '12px 0 0' }}>
        &quot;From cache&quot; means the source&apos;s daily or weekly window was still fresh, so the run reused it. A problem&apos;s
        status opens its error. After 3 failures in a row, the breaker skips a source until the next day.
      </p>
    </>
  )
}
```

`web/app/(app)/sources/page.tsx`:

```tsx
import { TriangleAlert } from 'lucide-react'
import type { Metadata } from 'next'
import { SourceTable, type SourceLine } from '@/components/sources/SourceTable'
import { ownerClient } from '@/lib/auth'
import { databaseSize, loadSourceHealth } from '@/lib/data/sources'
import { timeOrDate } from '@/lib/dates'
import { runWhen } from '@/lib/runs'
import { BREAKER_THRESHOLD, CATEGORY_LABELS, fmtLatency, fmtSize, sentimentNotice, tally, type SourceRow, type Tally } from '@/lib/sources'

export const metadata: Metadata = { title: 'Source health' }

/** Supabase's free plan allows a 500 MB database. */
const FREE_DATABASE_BYTES = 500e6

/** "2 partial · 1 stale · none failed", or "every source answered". */
function details(t: Tally): string {
  const parts = [
    t.partial && `${t.partial} partial`,
    t.stale && `${t.stale} stale`,
    t.skipped && `${t.skipped} skipped`,
    t.missing && `${t.missing} not run`,
  ].filter(Boolean)
  if (parts.length === 0 && t.failed === 0) return 'every source answered'
  return [...parts, t.failed ? `${t.failed} failed` : 'none failed'].join(' · ')
}

/** The breaker follows the source's newest result, in a run or a check. */
function breaker(row: SourceRow): string {
  const newest = [row.run, row.check].filter((h) => h !== null).sort((a, b) => (a.attemptedAt < b.attemptedAt ? 1 : -1))[0]
  const fails = newest?.failures ?? 0
  const state = fails >= BREAKER_THRESHOLD ? 'open' : 'closed'
  return fails === 0 ? state : `${state} · ${fails} ${fails === 1 ? 'fail' : 'fails'} in a row`
}

const line = (row: SourceRow): SourceLine => ({
  name: row.name,
  kind: CATEGORY_LABELS[row.category],
  core: row.core,
  problem: row.problem,
  status: row.run?.status ?? null,
  time: row.run ? fmtLatency(row.run.latencyMs) : '—',
  records: row.run ? row.run.records.toLocaleString('en-CA') : '—',
  recordsMeta: row.run ? `${row.run.records.toLocaleString('en-CA')} ${row.run.records === 1 ? 'record' : 'records'}` : 'not run',
  breaker: breaker(row),
  check: row.check?.status ?? null,
  lastOk: row.lastOk ? timeOrDate(row.lastOk) : 'never',
  errors: [
    row.run?.error && `This run: ${row.run.error}`,
    row.check?.error && `Daily check (${timeOrDate(row.check.attemptedAt)}): ${row.check.error}`,
  ].filter((e): e is string => Boolean(e)),
})

/** Source health (spec §9): every source's latest result, its daily check, and the database's size. */
export default async function SourcesPage() {
  const supabase = await ownerClient()
  if (!supabase) return null // the layout is showing the not-the-owner notice
  const [health, size] = await Promise.all([loadSourceHealth(supabase), databaseSize(supabase)])
  const { rows, run, checkedAt } = health
  const inRun = tally(rows, (r) => r.run)
  const checked = tally(rows, (r) => r.check)
  const core = rows.filter((r) => r.core)
  const coreOk = core.filter((r) => r.run?.status === 'ok').length
  const when = [run && `the ${runWhen(run)} run`, checkedAt && `the daily check at ${timeOrDate(checkedAt)}`].filter(Boolean)
  const sentiment = run ? sentimentNotice(run.summary) : null

  return (
    <main className="page">
      <div className="enter">
        <h1>Source health</h1>
        <p className="sub">
          The {rows.length} keyless sources behind each run{when.length > 0 && ` · from ${when.join(' and ')}`}
        </p>
      </div>
      <section className="summary stagger" aria-label="Summary">
        <div className="card">
          <span className="label">This run</span>
          <b>
            {inRun.ok}
            <span className="muted" style={{ fontSize: 15 }}>
              /{inRun.total} OK
            </span>
          </b>
          <span className="sub">{run ? details(inRun) : 'no run has finished yet'}</span>
        </div>
        <div className="card">
          <span className="label">Daily check</span>
          <b className={checkedAt && checked.ok === checked.total ? 'gain' : undefined}>
            {checked.ok}
            <span className="muted" style={{ fontSize: 15 }}>
              /{checked.total} OK
            </span>
          </b>
          <span className="sub">{checkedAt ? details(checked) : 'no daily check yet'}</span>
        </div>
        <div className="card">
          <span className="label">Core sources</span>
          <b>
            {coreOk}
            <span className="muted" style={{ fontSize: 15 }}>
              /{core.length} OK
            </span>
          </b>
          <span className="sub">a core failure degrades the run</span>
        </div>
        <div className="card">
          <span className="label">Database</span>
          <b>{size === null ? '—' : fmtSize(size)}</b>
          <span className="sub">of Supabase&apos;s free 500 MB</span>
          {size !== null && (
            <div className="usage" role="img" aria-label={`${Math.round((size / FREE_DATABASE_BYTES) * 100)}% used`}>
              <span style={{ width: `${Math.min(100, (size / FREE_DATABASE_BYTES) * 100)}%` }} />
            </div>
          )}
        </div>
      </section>
      {sentiment && (
        <div className="banner warn enter" role="note">
          <TriangleAlert />
          <div>
            <strong>News sentiment:</strong> {sentiment}
          </div>
        </div>
      )}
      <section className="card card-pad enter sources-card">
        {rows.length === 0 ? (
          <p className="sub" style={{ margin: 0 }}>
            No sources yet. The next run or daily check lists them here.
          </p>
        ) : (
          <SourceTable lines={rows.map(line)} />
        )}
      </section>
    </main>
  )
}
```

`web/components/shell/nav.ts`:

```ts
import { Activity, Eye, Settings, Wallet, type LucideIcon } from 'lucide-react'

export interface NavItem {
  href: string
  label: string
  icon: LucideIcon
  /** Primary pages are phone tabs; the rest sit in the More sheet. */
  primary: boolean
}

/** The pages built so far. Picks and Track record join with the model (Plans 3 and 4). */
export const NAV: readonly NavItem[] = [
  { href: '/', label: 'Portfolio', icon: Wallet, primary: true },
  { href: '/watchlist', label: 'Watchlist', icon: Eye, primary: true },
  { href: '/sources', label: 'Sources', icon: Activity, primary: false },
  { href: '/settings', label: 'Settings', icon: Settings, primary: false },
]

export const isCurrent = (href: string, pathname: string): boolean =>
  href === '/' ? pathname === '/' : pathname === href || pathname.startsWith(`${href}/`)
```

In `web/components/shell/Shell.tsx`, replace:

```tsx
              <span className="pill hide-sm">
                <span className="num">{sources}</span>&nbsp;sources
              </span>
```

with:

```tsx
              <Link className="pill hide-sm" href="/sources">
                <span className="num">{sources}</span>&nbsp;sources
              </Link>
```

Append to `web/app/styles/pages.css`, after one blank line:

```css
/* ---------- sources_1.html ---------- */
.summary { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
@media (max-width: 767px) { .summary { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
.summary .card { padding: 14px 16px; display: grid; gap: 4px; align-content: start; }
.summary b { font: 600 22px/1.1 var(--font-mono) !important; }
.usage { height: 8px; border-radius: 999px; background: var(--muted); overflow: hidden; margin-top: 6px; }
.usage span { display: block; height: 100%; background: var(--chart-1); transform-origin: left; animation: band-grow 400ms ease-out both; }
#sources tr.err td { white-space: normal; padding-top: 0; color: var(--muted-foreground); font: 12px/1.5 var(--font-mono) !important; background: var(--muted); overflow-wrap: anywhere; }
.core { font: 500 10px/1 var(--font-mono); text-transform: uppercase; letter-spacing: 0.06em; padding: 3px 5px; border-radius: 4px; border: 1px solid var(--border); color: var(--muted-foreground); margin-left: 6px; }
@media (max-width: 639px) {
  #sources thead { display: none; }
  #sources, #sources tbody { display: block; }
  #sources tr:not(.err) { display: grid; grid-template-columns: minmax(0, 1fr) auto; grid-template-areas: "name status" "meta meta"; gap: 4px 10px; padding: 11px 0; border-bottom: 1px solid var(--border); }
  #sources td { display: none; padding: 0; border: 0; }
  #sources td:nth-child(1) { display: block; grid-area: name; }
  #sources td:nth-child(3) { display: block; grid-area: status; }
  #sources td:nth-child(4) { display: block; grid-area: meta; text-align: left !important; }
  #sources td:nth-child(4)::after { content: attr(data-meta); color: var(--muted-foreground); }
  #sources tr.err { display: block; }
  #sources tr.err td { display: block; padding: 8px 10px; }
  .sources-card .table-scroll { overflow: visible; margin: 0; padding: 0; }
}
```

- [ ] **Step 9: Run the tests**

Run: `npm test`
Expected: `Test Files  16 passed (16)`, `Tests  104 passed (104)`.

Run: `npm run e2e`
Expected: `38 passed`. Then `npm run lint` and `npm run typecheck` are clean.

- [ ] **Step 10: Commit**

```bash
git add web/lib/sources.ts web/lib/sources.test.ts web/lib/dates.ts web/lib/dates.test.ts web/lib/data/runs.ts web/lib/data/sources.ts web/components/sources/SourceTable.tsx "web/app/(app)/sources/page.tsx" web/components/shell/nav.ts web/components/shell/Shell.tsx web/app/styles/pages.css web/e2e/db.ts web/e2e/sources.spec.ts web/e2e/navigation.spec.ts
git commit -m "feat: show Source health"
```

---

### Task 7: Show a Ticker page for any symbol

**Files:**
- Create:
  - `web/lib/ticker.ts`, `web/lib/data/ticker.ts`
  - `web/components/ticker/PriceCard.tsx`, `web/components/ticker/NewsCard.tsx`, `web/components/ticker/WatchToggle.tsx`
  - `web/components/shell/FindTicker.tsx`, `web/app/(app)/ticker/[symbol]/page.tsx`
- Modify:
  - `web/lib/data/portfolio.ts`, `web/app/(app)/watchlist/actions.ts`
  - `web/components/shell/Shell.tsx`, `web/components/shell/Navigation.tsx`
  - `web/components/portfolio/Cards.tsx`, `web/components/watchlist/Watchlist.tsx`
  - `web/app/styles/pages.css`, `web/e2e/db.ts`, `web/e2e/navigation.spec.ts`
- Test: `web/lib/ticker.test.ts`, `web/e2e/ticker.spec.ts`

**Interfaces:**
- Consumes:
  - From Task 6, the ★ items: `loadSourceHealth`, `answered`, `covers`, `coverageName` and `timeOrDate`.
  - From Task 3, `RecordedTrade` and `buildLedger`.
  - The watchlist's `addWatch` and `removeWatch` actions.
  - `LineChart`, `Tabs`, `useToast`, `isListedStock`, `lastPublishedRun`.
- Produces:
  - In `lib/ticker.ts`:
    - `RANGES` (1M, 3M, 6M and 1Y are 21, 63, 126 and 252 trading days);
    - `priceSeries(closes, assetType, fx)`: a coin in CAD at each day's rate; a stock in its own currency;
    - `inRange(series, range)` and `lastMove(series)`;
    - `tickerHref(symbol, assetType)` (`/ticker/RY.TO`, `/ticker/BTC?asset=crypto`);
    - `safeLink(url)`: only `http:` and `https:`;
    - `fmtScore(v)` ("+0.25", "−0.22") and `tone(v)` (beyond ±0.2 is `pos` or `neg`).
  - `loadTrades(supabase, only?: AssetRef)`: one asset's trades when `only` is given.
  - In `lib/data/ticker.ts`:
    - `resolveAssetType(supabase, symbol)`: a symbol only one asset type allows, else a listed stock, else a coin the pipeline prices, else a stock;
    - `loadTicker(supabase, ref)`: name, market, exchange, 400 days of closes, the 48-hour headlines, the latest published run's news features, whether the asset is watched, and its positions.
  - The `/ticker/[symbol]` page:
    - `?asset=crypto` picks the coin;
    - an invalid symbol is a 404;
    - an unknown valid symbol shows "No prices yet" and Watch.
  - `<FindTicker onGo? />`, a search box in the sidebar and the More sheet.
  - Symbols in Holdings and on the Watchlist link to their Ticker pages.
  - In `e2e/db.ts`: `seedNews(rows)` and `seedFeatures(runId, symbol, assetType, features)`.

- [ ] **Step 1: Write the failing unit test**

`web/lib/ticker.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { FxRates } from './portfolio/lookup'
import type { Close } from './portfolio/types'
import { fmtScore, inRange, lastMove, priceSeries, safeLink, tickerHref, tone } from './ticker'

const FX = new FxRates([
  { day: '2026-10-01', usdCad: 1.4 },
  { day: '2026-10-05', usdCad: 1.5 },
])
const closes = (currency: 'USD' | 'CAD', points: [string, number][]): Close[] =>
  points.map(([day, close]) => ({ day, close, currency }))

describe('priceSeries', () => {
  it('keeps a stock in its own currency', () => {
    expect(priceSeries(closes('USD', [['2026-10-01', 200], ['2026-10-02', 210]]), 'stock', FX)).toEqual({
      days: ['2026-10-01', '2026-10-02'],
      values: [200, 210],
      currency: 'USD',
    })
    expect(priceSeries(closes('CAD', [['2026-10-01', 180]]), 'stock', FX).currency).toBe('CAD')
  })

  it("converts a coin to CAD at each day's rate, leaving out days before any rate", () => {
    const series = priceSeries(closes('USD', [['2026-09-30', 1], ['2026-10-01', 100], ['2026-10-06', 100]]), 'crypto', FX)
    expect(series).toEqual({ days: ['2026-10-01', '2026-10-06'], values: [140, 150], currency: 'CAD' })
  })
})

describe('ranges and the last move', () => {
  const series = { days: Array.from({ length: 30 }, (_, i) => `d${i}`), values: Array.from({ length: 30 }, (_, i) => 100 + i), currency: 'CAD' as const }

  it('keeps the last 21 trading days plus the close before', () => {
    const month = inRange(series, '1m')
    expect(month.days).toHaveLength(22)
    expect(month.days[0]).toBe('d8')
    expect(inRange(series, '1y').days).toHaveLength(30)
  })

  it('gives the latest close and its move from the one before', () => {
    expect(lastMove(series)).toEqual({ price: 129, day: 'd29', change: 1, pct: (1 / 128) * 100 })
    expect(lastMove({ ...series, days: ['d0'], values: [100] })).toEqual({ price: 100, day: 'd0', change: null, pct: null })
    expect(lastMove({ ...series, days: [], values: [] })).toBeNull()
  })
})

describe('tickerHref', () => {
  it('links a stock by its symbol and a coin with its asset type', () => {
    expect(tickerHref('RY.TO', 'stock')).toBe('/ticker/RY.TO')
    expect(tickerHref('BTC', 'crypto')).toBe('/ticker/BTC?asset=crypto')
  })
})

describe('news', () => {
  it('only links to web pages', () => {
    expect(safeLink('https://finance.yahoo.com/news/x.html')).toBe('https://finance.yahoo.com/news/x.html')
    expect(safeLink('javascript:alert(1)')).toBeNull()
    expect(safeLink('not a url')).toBeNull()
  })

  it('writes scores with a sign and colours them past ±0.2', () => {
    expect([fmtScore(0.25), fmtScore(-0.224), fmtScore(0), fmtScore(-0.001)]).toEqual(['+0.25', '−0.22', '+0.00', '+0.00'])
    expect([tone(0.25), tone(-0.22), tone(0.08), tone(null)]).toEqual(['pos', 'neg', 'neu', 'neu'])
  })
})
```

- [ ] **Step 2: Run it and see it fail**

Run: `npm test -- lib/ticker.test.ts`
Expected: `Error: Cannot find module './ticker'`, `Test Files  1 failed (1)`.

- [ ] **Step 3: Write the ticker helpers**

`web/lib/ticker.ts`:

```ts
/** What the Ticker page shows before the model exists (spec §9, Plan 5c). */

import type { FxRates } from './portfolio/lookup'
import type { AssetType, Close, Currency } from './portfolio/types'

export type Range = '1m' | '3m' | '6m' | '1y'
export const RANGES: { value: Range; label: string; days: number }[] = [
  { value: '1m', label: '1M', days: 21 },
  { value: '3m', label: '3M', days: 63 },
  { value: '6m', label: '6M', days: 126 },
  { value: '1y', label: '1Y', days: 252 },
]

export interface PriceSeries {
  days: string[]
  values: number[]
  currency: Currency
}

/**
 * The price history to chart: a stock in its own currency, a coin in CAD at each day's Bank of
 * Canada rate (Coinbase prices coins in USD), as the portfolio values them. Days without a rate yet
 * are left out.
 */
export function priceSeries(closes: readonly Close[], assetType: AssetType, fx: FxRates): PriceSeries {
  const days: string[] = []
  const values: number[] = []
  for (const close of closes) {
    const value = assetType === 'crypto' ? fx.toCad(close) : close.close
    if (value === null) continue
    days.push(close.day)
    values.push(value)
  }
  const currency: Currency = assetType === 'crypto' || closes[0]?.currency !== 'USD' ? 'CAD' : 'USD'
  return { days, values, currency }
}

/** The last `range` of trading days, plus the close before, so the first move shows. */
export function inRange(series: PriceSeries, range: Range): PriceSeries {
  const days = RANGES.find((r) => r.value === range)!.days
  const start = Math.max(0, series.days.length - 1 - days)
  return { ...series, days: series.days.slice(start), values: series.values.slice(start) }
}

export interface LastMove {
  price: number
  day: string
  change: number | null
  pct: number | null
}

/** The latest close and its move from the close before. */
export function lastMove(series: PriceSeries): LastMove | null {
  const n = series.values.length
  if (n === 0) return null
  const price = series.values[n - 1]
  const before = n > 1 ? series.values[n - 2] : null
  return {
    price,
    day: series.days[n - 1],
    change: before === null ? null : price - before,
    pct: before === null || before === 0 ? null : ((price - before) / before) * 100,
  }
}

/** The Ticker page of an asset: a coin says so, since a coin and a stock can share a symbol. */
export const tickerHref = (symbol: string, assetType: AssetType): string =>
  `/ticker/${encodeURIComponent(symbol)}${assetType === 'crypto' ? '?asset=crypto' : ''}`

/** Only web links: a headline's link is never allowed to run script. */
export function safeLink(url: string): string | null {
  try {
    const parsed = new URL(url)
    return parsed.protocol === 'http:' || parsed.protocol === 'https:' ? parsed.href : null
  } catch {
    return null
  }
}

/** FinBERT's score, −1 to +1, as the mockup shows it: "+0.25", "−0.22". */
export const fmtScore = (value: number): string => {
  const rounded = Number(value.toFixed(2))
  return `${rounded > 0 ? '+' : rounded < 0 ? '−' : '+'}${Math.abs(rounded).toFixed(2)}`
}

/** The sentiment chip's tone: beyond ±0.2 reads as positive or negative. */
export const tone = (value: number | null): 'pos' | 'neg' | 'neu' =>
  value === null ? 'neu' : value > 0.2 ? 'pos' : value < -0.2 ? 'neg' : 'neu'
```

- [ ] **Step 4: Run it**

Run: `npm test -- lib/ticker.test.ts`
Expected: `Test Files  1 passed (1)`, `Tests  7 passed (7)`.

- [ ] **Step 5: Write the failing browser tests and their seeding helpers**

In `web/e2e/db.ts`, replace:

```ts
/** RY.TO and AAPL in the TFSA, ETH in the crypto account (part sold at a loss 5 days ago). */
```

with:

```ts
export async function seedNews(
  rows: { symbol: string; asset_type: 'stock' | 'crypto'; hoursAgo: number; outlet: string; url: string; title: string; sentiment: number | null }[],
) {
  for (const [i, { hoursAgo, ...r }] of rows.entries()) {
    await sql`insert into news_items ${sql({
      ...r,
      published_at: new Date(Date.now() - hoursAgo * 3_600_000),
      cluster_id: `story-${i}`,
      story_key: `key-${i}`,
    })}`
  }
}

export async function seedFeatures(runId: number, symbol: string, assetType: 'stock' | 'crypto', features: JSONValue) {
  await sql`insert into features_live (run_id, symbol, asset_type, features, as_of)
            values (${runId}, ${symbol}, ${assetType}, ${sql.json(features)}, now())`
}

/** RY.TO and AAPL in the TFSA, ETH in the crypto account (part sold at a loss 5 days ago). */
```

`web/e2e/ticker.spec.ts`:

```ts
import { expect, test } from '@playwright/test'
import { daysAgo, resetData, seedFeatures, seedHealth, seedNews, seedPortfolio, seedRun, seedSources, sql, weekdays } from './db'

test.beforeEach(async () => {
  await resetData()
  await seedPortfolio()
})

test("a held stock's page shows its price, the position, the last two days of news and its sources", async ({ page }) => {
  const runId = await seedRun({ kind: 'pre_close', status: 'success', published: true, finished: new Date(Date.now() - 3_600_000).toISOString() })
  await seedSources()
  await seedHealth(runId, new Date().toISOString(), [
    { source: 'yfinance_bars', status: 'ok' },
    { source: 'google_news', status: 'stale' },
    { source: 'sec_form4', status: 'ok' },
  ])
  await seedFeatures(runId, 'RY.TO', 'stock', {
    news_stories_48h: 2,
    news_outlets_48h: 2,
    news_sentiment_mean: 0.31,
    news_sentiment_trend: -0.05,
  })
  await seedNews([
    { symbol: 'RY.TO', asset_type: 'stock', hoursAgo: 3, outlet: 'BNN Bloomberg', url: 'https://www.bnnbloomberg.ca/ry', title: 'RBC raises its dividend', sentiment: 0.62 },
    { symbol: 'RY.TO', asset_type: 'stock', hoursAgo: 30, outlet: 'Globe', url: 'javascript:alert(1)', title: 'RBC names a new CFO', sentiment: -0.01 },
    { symbol: 'RY.TO', asset_type: 'stock', hoursAgo: 72, outlet: 'Globe', url: 'https://example.com/old', title: 'An older RBC story', sentiment: 0.1 },
    { symbol: 'TD.TO', asset_type: 'stock', hoursAgo: 2, outlet: 'Globe', url: 'https://example.com/td', title: 'TD story', sentiment: 0.1 },
  ])

  await page.goto('/')
  await page.locator('#holdings').getByRole('link', { name: 'RY.TO' }).click()
  await expect(page).toHaveURL(/\/ticker\/RY\.TO$/)
  await expect(page.getByRole('heading', { name: 'RY.TO', level: 1 })).toBeVisible()
  await expect(page.getByText('Royal Bank of Canada · TSX', { exact: true })).toBeVisible() // the exchange only when it differs
  const days = weekdays(daysAgo(60))
  await expect(page.locator('#last-price')).toHaveText(`C$${(170 + 0.25 * (days.length - 1)).toFixed(2)}`)
  await expect(page.getByText('You hold 10 · TFSA')).toBeVisible()
  await expect(page.getByRole('img', { name: 'RY.TO closes over 6M' })).toBeVisible()
  await page.getByRole('tab', { name: '1M' }).click()
  await expect(page.getByRole('img', { name: 'RY.TO closes over 1M' })).toBeVisible()

  const news = page.getByRole('region', { name: 'News' })
  await expect(news.locator('.kpi')).toHaveText(['Stories2', 'Outlets2', 'Sentiment+0.31', 'Trend−0.05'])
  await expect(news.locator('.news-item')).toHaveCount(2) // not the 3-day-old story, nor TD's
  await expect(news.getByRole('link', { name: 'RBC raises its dividend' })).toHaveAttribute('href', 'https://www.bnnbloomberg.ca/ry')
  await expect(news.getByText('RBC names a new CFO')).toBeVisible()
  await expect(news.getByRole('link', { name: 'RBC names a new CFO' })).toHaveCount(0) // a script link is shown as text

  const sources = page.getByRole('region', { name: 'Sources' })
  await expect(sources.getByText(/^1 of the 2 sources that cover TSX stocks answered/)).toBeVisible()
  await expect(sources.locator('#ticker-sources > span')).toHaveText(['google_newsstale', 'yfinance_bars'])
  await expect(sources.getByText('Not available for TSX stocks: sec_8k, sec_form4.')).toBeVisible()
})

test("a coin's page is in CAD, and the coin can be watched and unwatched from it", async ({ page }) => {
  await page.goto('/')
  await page.getByRole('complementary', { name: 'Main' }).getByRole('searchbox').fill('eth')
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(/\/ticker\/ETH$/) // the page works out that ETH is a coin
  await expect(page.getByText('Crypto · priced in CAD')).toBeVisible()
  const [{ close }] = await sql`select close::float from daily_closes where symbol = 'ETH' order by day desc limit 1`
  await expect(page.locator('#last-price')).toHaveText(`C$${(close * 1.4).toLocaleString('en-CA', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`)
  await expect(page.getByText('You hold 1 · Crypto')).toBeVisible()

  await page.getByRole('button', { name: 'Watch', exact: true }).click()
  await expect(page.getByRole('status')).toHaveText('ETH added to the watchlist')
  await expect(page.getByRole('button', { name: 'Watching' })).toHaveAttribute('aria-pressed', 'true')
  expect(await sql`select symbol, asset_type from watchlist`).toEqual([{ symbol: 'ETH', asset_type: 'crypto' }])
  await page.getByRole('button', { name: 'Watching' }).click()
  await expect(page.getByRole('status')).toHaveText('ETH removed from the watchlist')
  await expect(page.getByRole('button', { name: 'Watch', exact: true })).toHaveAttribute('aria-pressed', 'false')
})

test('any symbol has a page, with no data until a run collects it', async ({ page }) => {
  await page.goto('/')
  const search = page.getByRole('complementary', { name: 'Main' }).getByRole('searchbox')
  await search.fill('not a symbol!')
  await page.keyboard.press('Enter')
  await expect(page.getByText('Try a symbol like NVDA, SHOP.TO or BTC.')).toBeVisible()
  await search.fill('shop.to')
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(/\/ticker\/SHOP\.TO$/)
  await expect(page.getByRole('heading', { name: 'SHOP.TO', level: 1 })).toBeVisible()
  await expect(page.getByText('Not in the stock lists · TSX')).toBeVisible()
  await expect(page.getByText(/^No prices yet/)).toBeVisible()
  await expect(page.getByText('No headlines in the last 48 hours.')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Watch', exact: true })).toBeVisible()

  await page.goto('/ticker/AAPL')
  await expect(page.getByText('Apple Inc. · US · NYSE', { exact: true })).toBeVisible()

  await page.goto('/ticker/not-valid')
  await expect(page.getByText('This page could not be found.')).toBeVisible()
})
```

In `web/e2e/navigation.spec.ts`, replace:

```ts
import { resetData, seedPortfolio, seedRun, sql } from './db'
```

with:

```ts
import { resetData, seedHealth, seedNews, seedPortfolio, seedRun, seedSources, sql } from './db'
```

In `web/e2e/navigation.spec.ts`, replace:

```ts
    await seedRun({ kind: 'pre_open', status: 'success', published: true, finished: new Date(Date.now() - 3_600_000).toISOString() })
    for (const [path, heading] of [['/', 'My Portfolio'], ['/watchlist', 'Watchlist'], ['/settings', 'Settings']]) {
```

with:

```ts
    const runId = await seedRun({ kind: 'pre_open', status: 'success', published: true, finished: new Date(Date.now() - 3_600_000).toISOString() })
    await seedSources()
    await seedHealth(runId, new Date().toISOString(), [
      { source: 'sec_form4', status: 'partial', error: `PartialFetch: ${'DocumentBudgetExhausted; '.repeat(12)}` },
    ])
    await seedNews([
      { symbol: 'RY.TO', asset_type: 'stock', hoursAgo: 2, outlet: 'finance.yahoo.com', url: 'https://finance.yahoo.com/x', title: `RBC ${'quarterly-results-'.repeat(8)}beat`, sentiment: 0.4 },
    ])
    const pages = [
      ['/', 'My Portfolio'],
      ['/watchlist', 'Watchlist'],
      ['/ticker/RY.TO', 'RY.TO'],
      ['/sources', 'Source health'],
      ['/settings', 'Settings'],
    ]
    for (const [path, heading] of pages) {
```

- [ ] **Step 6: Run them and see them fail**

Run: `npm run e2e -- e2e/ticker.spec.ts e2e/navigation.spec.ts`
Expected: the build succeeds, then `4 failed` and `3 passed` (the setup and the first two navigation tests). `/ticker/RY.TO` is a 404, so the phone-width test finds no `RY.TO` heading; Holdings has no `RY.TO` link; and the sidebar has no searchbox.

- [ ] **Step 7: Write the loaders**

In `web/lib/data/portfolio.ts`, replace:

```ts
/** Every buy (`lots`) and sell (`sells`). Postgres numerics arrive as strings. */
export async function loadTrades(supabase: Supabase): Promise<RecordedTrade[]> {
  const [lots, sells] = await Promise.all([
    fetchAll((from, to) => supabase.from('lots').select(`${TRADE_COLUMNS}, bought_at`).order('id').range(from, to)),
    fetchAll((from, to) => supabase.from('sells').select(`${TRADE_COLUMNS}, sold_at`).order('id').range(from, to)),
  ])
```

with:

```ts
/** Every buy (`lots`) and sell (`sells`), or only one asset's. Postgres numerics arrive as strings. */
export async function loadTrades(supabase: Supabase, only?: AssetRef): Promise<RecordedTrade[]> {
  const lotsQuery = () => {
    const query = supabase.from('lots').select(`${TRADE_COLUMNS}, bought_at`)
    return only ? query.eq('symbol', only.symbol).eq('asset_type', only.assetType) : query
  }
  const sellsQuery = () => {
    const query = supabase.from('sells').select(`${TRADE_COLUMNS}, sold_at`)
    return only ? query.eq('symbol', only.symbol).eq('asset_type', only.assetType) : query
  }
  const [lots, sells] = await Promise.all([
    fetchAll((from, to) => lotsQuery().order('id').range(from, to)),
    fetchAll((from, to) => sellsQuery().order('id').range(from, to)),
  ])
```

`web/lib/data/ticker.ts`:

```ts
import 'server-only'
import { addDays, todayInToronto } from '../dates'
import { buildLedger } from '../portfolio/ledger'
import type { FxRates } from '../portfolio/lookup'
import type { AssetType, Close, Currency, Market, Position } from '../portfolio/types'
import type { Run } from '../runs'
import { isValidSymbol, marketOf } from '../symbols'
import type { Supabase } from '../supabase/server'
import { fetchAll, must } from './fetch'
import { loadFx, loadTrades, type AssetRef } from './portfolio'
import { lastPublishedRun } from './runs'
import { isListedStock } from './symbols'

/** A year of trading days and the close before it, with room for holidays. */
const HISTORY_DAYS = 400
/** The news stage reads two days of feeds (spec §4.2). */
const NEWS_HOURS = 48
const MAX_HEADLINES = 200

export interface Headline {
  id: number
  publishedAt: string
  outlet: string
  url: string
  title: string
  sentiment: number | null
}

/** The news features the latest published run computed for this asset (Plan 2f). */
export interface NewsStats {
  stories: number
  outlets: number
  sentiment: number | null
  trend: number | null
}

export interface TickerData {
  name: string | null
  /** Null for a coin. */
  market: Market | null
  exchange: string | null
  closes: Close[]
  fx: FxRates
  /** The last 48 hours' headlines, newest first. */
  headlines: Headline[]
  news: { stats: NewsStats; run: Run } | null
  watched: boolean
  positions: Position[]
}

/**
 * The asset a symbol in the address means when the link doesn't say: a symbol only one asset type
 * allows, else a listed stock, else a coin the pipeline prices, else a stock.
 */
export async function resolveAssetType(supabase: Supabase, symbol: string): Promise<AssetType | null> {
  const stock = isValidSymbol(symbol, 'stock')
  const coin = isValidSymbol(symbol, 'crypto')
  if (!stock || !coin) return stock ? 'stock' : coin ? 'crypto' : null
  if (await isListedStock(supabase, symbol)) return 'stock'
  const priced = must(
    await supabase.from('daily_closes').select('symbol').eq('asset_type', 'crypto').eq('symbol', symbol).limit(1),
  ) as unknown[]
  return priced.length > 0 ? 'crypto' : 'stock'
}

const toNumber = (value: unknown): number | null => (typeof value === 'number' && Number.isFinite(value) ? value : null)

/** Everything the Ticker page shows for one asset. */
export async function loadTicker(supabase: Supabase, ref: AssetRef): Promise<TickerData> {
  const since = addDays(todayInToronto(), -HISTORY_DAYS)
  const newsSince = new Date(Date.now() - NEWS_HOURS * 3_600_000).toISOString()
  const [info, closes, fx, headlines, run, watch, trades] = await Promise.all([
    ref.assetType === 'stock'
      ? supabase.from('symbols').select('name, market, exchange').eq('asset_type', 'stock').eq('symbol', ref.symbol).limit(1)
      : null,
    fetchAll((from, to) =>
      supabase
        .from('daily_closes')
        .select('day, close, currency')
        .eq('asset_type', ref.assetType)
        .eq('symbol', ref.symbol)
        .gte('day', since)
        .order('day')
        .range(from, to),
    ),
    loadFx(supabase),
    supabase
      .from('news_items')
      .select('id, published_at, outlet, url, title, sentiment')
      .eq('asset_type', ref.assetType)
      .eq('symbol', ref.symbol)
      .gte('published_at', newsSince)
      .order('published_at', { ascending: false })
      .order('id', { ascending: false })
      .limit(MAX_HEADLINES),
    lastPublishedRun(supabase),
    supabase.from('watchlist').select('symbol').eq('asset_type', ref.assetType).eq('symbol', ref.symbol).limit(1),
    loadTrades(supabase, ref),
  ])

  const features = run
    ? (must(
        await supabase
          .from('features_live')
          .select('features')
          .eq('run_id', run.id)
          .eq('asset_type', ref.assetType)
          .eq('symbol', ref.symbol)
          .limit(1),
      ) as { features: Record<string, unknown> }[])
    : []
  const f = features[0]?.features
  const stories = toNumber(f?.news_stories_48h)
  const listed = info ? (must(info) as { name: string; market: Market; exchange: string }[])[0] : undefined

  return {
    name: listed?.name ?? null,
    market: ref.assetType === 'crypto' ? null : (listed?.market ?? marketOf(ref.symbol)),
    exchange: listed?.exchange ?? null,
    closes: (closes as { day: string; close: string | number; currency: Currency }[]).map((c) => ({
      day: c.day,
      close: Number(c.close),
      currency: c.currency,
    })),
    fx,
    headlines: (
      must(headlines) as {
        id: number
        published_at: string
        outlet: string
        url: string
        title: string
        sentiment: number | null
      }[]
    ).map((h) => ({ id: h.id, publishedAt: h.published_at, outlet: h.outlet, url: h.url, title: h.title, sentiment: h.sentiment })),
    news:
      run && stories !== null
        ? {
            run,
            stats: {
              stories,
              outlets: toNumber(f?.news_outlets_48h) ?? 0,
              sentiment: toNumber(f?.news_sentiment_mean),
              trend: toNumber(f?.news_sentiment_trend),
            },
          }
        : null,
    watched: (must(watch) as unknown[]).length > 0,
    positions: buildLedger(trades, fx).positions,
  }
}
```

- [ ] **Step 8: Write the page and its parts**

`web/components/ticker/PriceCard.tsx`:

```tsx
'use client'

import { useState } from 'react'
import { LineChart } from '@/components/LineChart'
import { Tabs } from '@/components/Tabs'
import { fmtPrice } from '@/lib/format'
import { RANGES, inRange, type PriceSeries, type Range } from '@/lib/ticker'

/** The price history with the mockup's range tabs. The forecast cone joins it with the model. */
export function PriceCard({ symbol, series, coin }: { symbol: string; series: PriceSeries; coin: boolean }) {
  const [range, setRange] = useState<Range>('6m')
  const shown = inRange(series, range)
  const label = RANGES.find((r) => r.value === range)!.label
  return (
    <section className="card card-pad enter" aria-labelledby="chart-h">
      <div className="section-head">
        <h2 id="chart-h">Price</h2>
        {series.values.length > 1 && <Tabs items={RANGES} value={range} onChange={setRange} label="Range" />}
      </div>
      {series.values.length > 1 ? (
        <>
          <LineChart
            series={shown.values}
            dates={shown.days}
            height={280}
            format={(v) => fmtPrice(v, series.currency)}
            label={`${symbol} closes over ${label}`}
          />
          <div className="legend" style={{ marginTop: 8 }}>
            <span>
              <i style={{ background: 'var(--chart-1)' }} />
              {coin ? "Close in CAD: Coinbase's USD close at that day's Bank of Canada rate" : `Close in ${series.currency}`}
            </span>
          </div>
        </>
      ) : (
        <p className="sub" style={{ margin: 0 }}>
          {series.values.length === 0
            ? 'No prices yet. The next run collects a year of closes for held and watched symbols.'
            : 'One close so far; the chart starts with the second.'}
        </p>
      )}
    </section>
  )
}
```

`web/components/ticker/NewsCard.tsx`:

```tsx
'use client'

import { useState } from 'react'

export interface HeadlineView {
  id: number
  title: string
  /** Null when the stored link isn't a web page. */
  link: string | null
  outlet: string
  when: string
  score: string
  tone: 'pos' | 'neg' | 'neu'
}

export interface NewsKpi {
  label: string
  value: string
  tone: 'gain' | 'loss' | ''
}

const SHOWN = 12

/** The last 48 hours of headlines with FinBERT scores, and the run's news numbers (ticker_1.html). */
export function NewsCard({ headlines, kpis, source }: { headlines: HeadlineView[]; kpis: NewsKpi[] | null; source: string | null }) {
  const [all, setAll] = useState(false)
  const shown = all ? headlines : headlines.slice(0, SHOWN)
  return (
    <section className="card card-pad enter" aria-labelledby="news-h">
      <div className="section-head" style={{ marginBottom: 4 }}>
        <h2 id="news-h">News</h2>
        <span className="sub">48 hours</span>
      </div>
      {kpis && (
        <div className="kpis" style={{ margin: '6px 0 4px' }}>
          {kpis.map((k) => (
            <div key={k.label} className="kpi">
              <span className="label">{k.label}</span>
              <b className={k.tone}>{k.value}</b>
            </div>
          ))}
        </div>
      )}
      {headlines.length === 0 ? (
        <p className="sub" style={{ margin: '6px 0 0' }}>
          No headlines in the last 48 hours.
        </p>
      ) : (
        <div className="stagger" id="headlines">
          {shown.map((h) => (
            <div key={h.id} className="news-item">
              <span className={`sent ${h.tone}`}>{h.score}</span>
              {h.link ? (
                <a href={h.link} target="_blank" rel="noopener noreferrer">
                  {h.title}
                </a>
              ) : (
                <span>{h.title}</span>
              )}
              <span />
              <span className="sub">
                {h.outlet} · {h.when}
              </span>
            </div>
          ))}
        </div>
      )}
      {headlines.length > SHOWN && (
        <button type="button" className="btn btn-ghost btn-sm" style={{ marginTop: 8, width: '100%' }} onClick={() => setAll((a) => !a)}>
          {all ? 'Show fewer' : `Show all ${headlines.length} headlines`}
        </button>
      )}
      <p className="sub" style={{ margin: '8px 0 0' }}>
        Headlines link to the publisher. Google News links open Google&apos;s redirect page. Sentiment is FinBERT, from
        −1 to +1.{source && ` The counts are from the ${source} run.`}
      </p>
    </section>
  )
}
```

`web/components/ticker/WatchToggle.tsx`:

```tsx
'use client'

import { Check, Eye } from 'lucide-react'
import { useTransition } from 'react'
import { addWatch, removeWatch } from '@/app/(app)/watchlist/actions'
import { useToast } from '@/components/Toast'
import type { AssetType } from '@/lib/portfolio/types'
import { marketOf } from '@/lib/symbols'

/** Watch or stop watching the asset on its own page, through the watchlist's actions. */
export function WatchToggle({ symbol, assetType, watched }: { symbol: string; assetType: AssetType; watched: boolean }) {
  const toast = useToast()
  const [pending, startTransition] = useTransition()

  const toggle = () =>
    startTransition(async () => {
      let message: string | undefined
      if (watched) {
        message = (await removeWatch(symbol, assetType)).message
      } else {
        const form = new FormData()
        form.set('symbol', symbol)
        form.set('type', assetType === 'crypto' ? 'crypto' : marketOf(symbol) === 'TSX' ? 'tsx' : 'us')
        const result = await addWatch({}, form)
        message = result.message ?? result.errors?.symbol
      }
      if (message) toast(message)
    })

  return (
    <button
      type="button"
      className={`btn btn-sm ${watched ? 'btn-secondary' : 'btn-primary'}`}
      aria-pressed={watched}
      disabled={pending}
      onClick={toggle}
    >
      {watched ? <Check /> : <Eye />}
      {watched ? 'Watching' : 'Watch'}
    </button>
  )
}
```

`web/app/(app)/ticker/[symbol]/page.tsx`:

```tsx
import { ArrowLeft, Info } from 'lucide-react'
import type { Metadata } from 'next'
import Link from 'next/link'
import { notFound } from 'next/navigation'
import { NewsCard, type HeadlineView, type NewsKpi } from '@/components/ticker/NewsCard'
import { PriceCard } from '@/components/ticker/PriceCard'
import { WatchToggle } from '@/components/ticker/WatchToggle'
import { ownerClient } from '@/lib/auth'
import { loadSourceHealth } from '@/lib/data/sources'
import { loadTicker, resolveAssetType } from '@/lib/data/ticker'
import { shortDay, timeOrDate } from '@/lib/dates'
import { fmtMoney, fmtPct, fmtPrice, fmtQty } from '@/lib/format'
import { ACCOUNT_LABELS } from '@/lib/portfolio/types'
import type { AssetType } from '@/lib/portfolio/types'
import { runWhen } from '@/lib/runs'
import { answered, covers, coverageName, type Coverage } from '@/lib/sources'
import { isValidSymbol, normalizeSymbol } from '@/lib/symbols'
import { fmtScore, lastMove, priceSeries, safeLink, tone } from '@/lib/ticker'

interface Props {
  params: Promise<{ symbol: string }>
  searchParams: Promise<{ asset?: string | string[] }>
}

const symbolOf = (raw: string): string | null => {
  try {
    return normalizeSymbol(decodeURIComponent(raw))
  } catch {
    return null // a malformed %-escape
  }
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  return { title: symbolOf((await params).symbol) ?? 'Ticker' }
}

const signedScore = (value: number | null): NewsKpi['value'] => (value === null ? '—' : fmtScore(value))
const scoreTone = (value: number | null): NewsKpi['tone'] => (value === null || value === 0 ? '' : value > 0 ? 'gain' : 'loss')

/**
 * Ticker detail (spec §9) before the model: the price history, the owner's position, the last two
 * days of news, and which sources cover the asset. The forecast, factors, catalysts and past
 * picks join with the model.
 */
export default async function TickerPage({ params, searchParams }: Props) {
  const supabase = await ownerClient()
  if (!supabase) return null // the layout is showing the not-the-owner notice
  const symbol = symbolOf((await params).symbol)
  const asked = (await searchParams).asset
  if (!symbol) notFound()
  const assetType: AssetType | null =
    asked === 'crypto' || asked === 'stock' ? asked : await resolveAssetType(supabase, symbol)
  if (!assetType || !isValidSymbol(symbol, assetType)) notFound()

  const [data, health] = await Promise.all([loadTicker(supabase, { symbol, assetType }), loadSourceHealth(supabase)])
  const coin = assetType === 'crypto'
  const series = priceSeries(data.closes, assetType, data.fx)
  const move = lastMove(series)
  // A TSX stock trades on the TSX; a US stock names its exchange (NYSE, Nasdaq…).
  const exchange = data.exchange === data.market ? null : data.exchange
  const about = coin ? ['Crypto', 'priced in CAD'] : [data.name ?? 'Not in the stock lists', data.market, exchange]

  const coverage: Coverage = { assetType, market: data.market }
  const covering = health.rows.filter((r) => covers(r, coverage))
  const answeredCount = covering.filter((r) => answered(r.run?.status)).length
  // Stock sources that skip this market: TSX stocks have no SEC filings or FINRA short data.
  const elsewhere = coin
    ? []
    : health.rows.filter((r) => r.assetTypes.includes('stock') && !covers(r, coverage)).map((r) => r.name).sort()

  const headlines: HeadlineView[] = data.headlines.map((h) => ({
    id: h.id,
    title: h.title,
    link: safeLink(h.url),
    outlet: h.outlet,
    when: timeOrDate(h.publishedAt),
    score: h.sentiment === null ? '—' : fmtScore(h.sentiment),
    tone: tone(h.sentiment),
  }))
  const kpis: NewsKpi[] | null = data.news && [
    { label: 'Stories', value: String(data.news.stats.stories), tone: '' },
    { label: 'Outlets', value: String(data.news.stats.outlets), tone: '' },
    { label: 'Sentiment', value: signedScore(data.news.stats.sentiment), tone: scoreTone(data.news.stats.sentiment) },
    { label: 'Trend', value: signedScore(data.news.stats.trend), tone: scoreTone(data.news.stats.trend) },
  ]

  return (
    <main className="page">
      <div className="enter">
        <Link href="/" className="sub inline-flex items-center gap-1">
          <ArrowLeft style={{ width: 14, height: 14 }} />
          My Portfolio
        </Link>
        <div className="flex flex-wrap items-end justify-between gap-4" style={{ marginTop: 10 }}>
          <div>
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <h1 className="num ticker-symbol">{symbol}</h1>
              <span className="sub">{about.filter(Boolean).join(' · ')}</span>
            </div>
            {move && (
              <div className="flex flex-wrap items-baseline gap-3" style={{ marginTop: 8 }}>
                <span className="price-big" id="last-price">
                  {fmtPrice(move.price, series.currency)}
                </span>
                {move.change !== null && move.pct !== null && (
                  <span className={`num ${move.change < 0 ? 'loss' : 'gain'}`}>
                    {fmtMoney(move.change, { prefix: '', digits: 2, signed: true })} · {fmtPct(move.pct)}
                  </span>
                )}
                <span className="sub">at the {shortDay(move.day)} close</span>
              </div>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {data.positions.map((p) => (
              <span key={p.account} className="badge">
                You hold {fmtQty(p.qty)} · {ACCOUNT_LABELS[p.account]}
              </span>
            ))}
            <WatchToggle symbol={symbol} assetType={assetType} watched={data.watched} />
          </div>
        </div>
      </div>

      <PriceCard symbol={symbol} series={series} coin={coin} />

      <section className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_420px]" style={{ alignItems: 'start' }}>
        <div className="grid gap-4">
          <section className="card card-pad enter" aria-labelledby="forecast-h">
            <h2 id="forecast-h" style={{ marginBottom: 10 }}>
              Forecast
            </h2>
            <div className="banner info">
              <Info />
              <div>
                The forecast cone, its top factors, catalysts and past picks for {symbol} appear here once the model runs.
              </div>
            </div>
          </section>
          <section className="card card-pad enter" aria-labelledby="sources-h">
            <div className="section-head" style={{ marginBottom: 10 }}>
              <h2 id="sources-h">Sources</h2>
              <span className="sub">
                {health.run
                  ? `${answeredCount} of the ${covering.length} sources that cover ${coverageName(coverage)} answered in the ${runWhen(health.run)} run`
                  : 'No run has finished yet'}
              </span>
            </div>
            <div className="source-grid" id="ticker-sources">
              {covering.map((r) => (
                <span key={r.name}>
                  <span className={`dot ${r.run?.status ?? 'skipped'}`} />
                  <span className="num">{r.name}</span>
                  {r.run?.status !== 'ok' && <span className="sub">{r.run?.status ?? 'not run'}</span>}
                </span>
              ))}
            </div>
            {elsewhere.length > 0 && (
              <p className="sub" style={{ margin: '10px 0 0' }}>
                Not available for {coverageName(coverage)}: {elsewhere.join(', ')}.
              </p>
            )}
            <p className="sub" style={{ margin: '10px 0 0' }}>
              <Link className="text-link" href="/sources">
                Source health
              </Link> has every source&apos;s errors and daily checks.
            </p>
          </section>
        </div>
        <NewsCard
          headlines={headlines}
          kpis={kpis}
          source={data.news ? runWhen(data.news.run) : null}
        />
      </section>
    </main>
  )
}
```

Watching or unwatching from the Ticker page must refresh it too.

In `web/app/(app)/watchlist/actions.ts`, replace:

```ts
  revalidatePath('/watchlist')
  const listed
```

with:

```ts
  revalidatePath('/watchlist')
  revalidatePath('/ticker/[symbol]', 'page')
  const listed
```

In `web/app/(app)/watchlist/actions.ts`, replace:

```ts
  revalidatePath('/watchlist')
  return { ok: true, message: `${symbol} removed from the watchlist`, at: Date.now() }
```

with:

```ts
  revalidatePath('/watchlist')
  revalidatePath('/ticker/[symbol]', 'page')
  return { ok: true, message: `${symbol} removed from the watchlist`, at: Date.now() }
```

Append to `web/app/styles/pages.css`, after one blank line:

```css
/* ---------- ticker_1.html (no factor bars until the model, Plan 3) ---------- */
.ticker-symbol { font-size: 26px !important; } /* inline in the mockup, which React can't mark !important */
.price-big { font: 600 30px/1 var(--font-mono) !important; letter-spacing: -0.02em; }
.news-item { display: grid; grid-template-columns: 52px 1fr; gap: 3px 12px; padding: 11px 0; border-bottom: 1px solid var(--border); }
.news-item:last-child { border-bottom: 0; }
.news-item a { overflow-wrap: anywhere; }
.news-item a:hover { text-decoration: underline !important; }
.sent { font: 600 11.5px/1 var(--font-mono) !important; padding: 5px 6px; border-radius: var(--radius-sm); text-align: center; align-self: start; }
.sent.pos { color: var(--gain); background: var(--gain-soft); }
.sent.neg { color: var(--loss); background: var(--loss-soft); }
.sent.neu { color: var(--hold); background: var(--hold-soft); }
.source-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 6px 14px; font-size: 13px; }
.source-grid > span { display: flex; align-items: center; gap: 7px; }
.kpis { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
@media (max-width: 639px) { .kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
.kpi { display: grid; gap: 4px; }
.kpi b { font: 600 17px/1.1 var(--font-mono) !important; }
a.sym:hover, .sym a:hover { text-decoration: underline !important; }
.text-link { text-decoration: underline !important; text-underline-offset: 2px; }
.find { position: relative; }
.find svg { position: absolute; left: 10px; top: 50%; width: 15px; height: 15px; transform: translateY(-50%); color: var(--muted-foreground); pointer-events: none; }
.find .input { padding-left: 32px; }
```

- [ ] **Step 9: Find any symbol from the sidebar, and link symbols to their pages**

`web/components/shell/FindTicker.tsx`:

```tsx
'use client'

import { Search } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { useState, type FormEvent } from 'react'
import { isValidSymbol, normalizeSymbol } from '@/lib/symbols'

/** Go to any symbol's Ticker page; the page works out whether it's a stock or a coin. */
export function FindTicker({ onGo }: { onGo?: () => void }) {
  const router = useRouter()
  const [value, setValue] = useState('')
  const [error, setError] = useState<string | null>(null)

  const submit = (event: FormEvent) => {
    event.preventDefault()
    const symbol = normalizeSymbol(value)
    if (!symbol) return
    if (!isValidSymbol(symbol, 'stock') && !isValidSymbol(symbol, 'crypto')) {
      setError('Try a symbol like NVDA, SHOP.TO or BTC.')
      return
    }
    setError(null)
    setValue('')
    onGo?.()
    router.push(`/ticker/${encodeURIComponent(symbol)}`)
  }

  return (
    <form role="search" className={`field ${error ? 'invalid' : ''}`} onSubmit={submit} noValidate>
      <label className="find">
        <span className="sr-only">Find a symbol</span>
        <Search aria-hidden="true" />
        <input
          type="search"
          className="input num-input"
          placeholder="Find a symbol"
          autoCapitalize="characters"
          enterKeyHint="go"
          value={value}
          onChange={(e) => {
            setValue(e.target.value)
            setError(null)
          }}
        />
      </label>
      <span className="error">{error}</span>
    </form>
  )
}
```

In `web/components/shell/Shell.tsx`, replace:

```tsx
import { BottomTabs, SidebarLinks } from './Navigation'
```

with:

```tsx
import { FindTicker } from './FindTicker'
import { BottomTabs, SidebarLinks } from './Navigation'
```

In `web/components/shell/Shell.tsx`, replace:

```tsx
          <SidebarLinks />
```

with:

```tsx
          <FindTicker />
          <SidebarLinks />
```

In `web/components/shell/Navigation.tsx`, replace:

```tsx
import { Drawer } from '../Drawer'
```

with:

```tsx
import { Drawer } from '../Drawer'
import { FindTicker } from './FindTicker'
```

In `web/components/shell/Navigation.tsx`, replace:

```tsx
        <div className="drawer-body">
```

with:

```tsx
        <div className="drawer-body">
          <FindTicker onGo={close} />
```

In `web/components/portfolio/Cards.tsx`, replace:

```tsx
import { Info, Sparkles, TriangleAlert } from 'lucide-react'
```

with:

```tsx
import { Info, Sparkles, TriangleAlert } from 'lucide-react'
import Link from 'next/link'
```

In `web/components/portfolio/Cards.tsx`, replace:

```tsx
import type { Warning } from '@/lib/portfolio/warnings'
```

with:

```tsx
import type { Warning } from '@/lib/portfolio/warnings'
import { tickerHref } from '@/lib/ticker'
```

In `web/components/portfolio/Cards.tsx`, replace:

```tsx
                      <span className="sym">{h.symbol}</span>
```

with:

```tsx
                      <Link className="sym" href={tickerHref(h.symbol, h.market === null ? 'crypto' : 'stock')}>
                        {h.symbol}
                      </Link>
```

In `web/components/watchlist/Watchlist.tsx`, replace:

```tsx
import { useActionState, useEffect, useState, useTransition } from 'react'
```

with:

```tsx
import Link from 'next/link'
import { useActionState, useEffect, useState, useTransition } from 'react'
```

In `web/components/watchlist/Watchlist.tsx`, replace:

```tsx
import type { FormState } from '@/lib/trade-form'
```

with:

```tsx
import { tickerHref } from '@/lib/ticker'
import type { FormState } from '@/lib/trade-form'
```

In `web/components/watchlist/Watchlist.tsx`, replace:

```tsx
              <span className="sym">{row.symbol}</span>
```

with:

```tsx
              <Link className="sym" href={tickerHref(row.symbol, row.assetType)}>
                {row.symbol}
              </Link>
```

- [ ] **Step 10: Run the tests**

Run: `npm test`
Expected: `Test Files  17 passed (17)`, `Tests  111 passed (111)`.

Run: `npm run e2e`
Expected: `41 passed`. Then `npm run lint` and `npm run typecheck` are clean.

- [ ] **Step 11: Look at the pages**

Start the app (`npm run build && npm start`) and sign in as `owner@example.com` / `local-owner-password`.
- Open a held stock's Ticker page from Holdings, a coin's from the Watchlist, and `/sources`, at full width and at 390 px.
- Compare them with `.superdesign/design_iterations/ticker_1.html` and `sources_1.html`. Compare the trade list and the import drawer with `portfolio_1.html`.

Expected:
- The Ledger look, in light and dark.
- No horizontal scrolling at 390 px.
- On phones, the bottom tabs stay fixed and Sources sits under More.

- [ ] **Step 12: Commit**

```bash
git add web/lib/ticker.ts web/lib/ticker.test.ts web/lib/data/ticker.ts web/lib/data/portfolio.ts web/components/ticker web/components/shell/FindTicker.tsx web/components/shell/Shell.tsx web/components/shell/Navigation.tsx web/components/portfolio/Cards.tsx web/components/watchlist/Watchlist.tsx "web/app/(app)/ticker" "web/app/(app)/watchlist/actions.ts" web/app/styles/pages.css web/e2e/db.ts web/e2e/ticker.spec.ts web/e2e/navigation.spec.ts
git commit -m "feat: show a Ticker page for any symbol, with symbol search"
```

---
### Task 8: Document what Plan 5c built and what it left

**Files:**
- Modify: `docs/superpowers/deferred.md`, `web/README.md`

**Interfaces:**
- Consumes: what Tasks 1 to 7 built.
- Produces:
  - `deferred.md`:
    - records the coin backfill, the import's duplicate rule, and the Ticker page's "answered" wording;
    - records what still waits for the model;
    - drops the items this plan finished.
  - `web/README.md`:
    - "Fix a mistaken trade" points at Delete;
    - a new "Import a broker file" section;
    - the deploy grants cover the new table.

- [ ] **Step 1: Update the docs**

In `docs/superpowers/deferred.md`, replace:

```markdown
- **Crypto history:** Coinbase gives 290 finished daily USD candles per coin in one request. 12-month momentum needs 365, so fetch a second window when the crypto model needs it. Altcoins are measured against BTC (spec §5.4), so price BTC whenever any crypto is held or watched.
```

with:

```markdown
- **Crypto history:** Coinbase gives 290 finished daily USD candles per coin in one request. Since Plan 5c the history stage pages back a year (and to the first buy) for held coins with `history.fetch_coin_closes`; watched coins still get 290 days. 12-month momentum needs 365, so page watched coins too when the crypto model needs it. Altcoins are measured against BTC (spec §5.4), so price BTC whenever any crypto is held or watched.
```

In `docs/superpowers/deferred.md`, replace:

```markdown
  - The status bar's Paper badges are static until picks are graded live (Plan 4). The missed-slot notice and the next run's time need the schedule in TypeScript (Plan 5c).
  - Plan 5c: Picks, Ticker detail, Track record, Source health, file import, and the watchlist's verdict columns.
  - No way to edit or delete a trade in the dashboard yet. Plan 5c adds a list of recent trades with Delete; deleting avoids the NOT VALID `*_usd_needs_fx_rate` check that blocks updating old USD rows. Until then, `web/README.md` ("Fix a mistaken trade") explains the table-editor workaround.
- **Portfolio returns (Plan 5b):** time-weighted. A day's buys count from the start of that day and its sells at the close, so a buy at the close dilutes that day's return slightly; counting buys at the close instead would let a large buy into a small position show a huge return. Trades on days without a close count on the next trading day, an asset with no closes at all is valued at cost, and before its first close (a coin bought more than 290 days ago) at that first close, so its early gain lands on the buy day.
```

with:

```markdown
  - The status bar's Paper badges are static until picks are graded live (Plan 4). The missed-slot notice and the next run's time need the schedule in TypeScript; Plan 5c left them for the dashboard plan after the model.
  - Waiting for the model (Plans 3 and 4): Today's Picks, Track record, the watchlist's verdict columns, and the Ticker page's forecast cone, top factors, catalysts and past picks (Plan 5c shows an empty card in their place).
  - Trades are corrected by deleting them in the trade list and adding them again (Plan 5c); there is no edit. Deleting also sidesteps the NOT VALID `*_usd_needs_fx_rate` check that blocks updating old USD rows.
- **Portfolio returns (Plan 5b):** time-weighted. A day's buys count from the start of that day and its sells at the close, so a buy at the close dilutes that day's return slightly; counting buys at the close instead would let a large buy into a small position show a huge return. Trades on days without a close count on the next trading day, an asset with no closes at all is valued at cost, and before its first close (a coin bought before Coinbase listed it) at that first close, so its early gain lands on the buy day.
```

In `docs/superpowers/deferred.md`, replace:

```markdown
- **Unlisted stocks (Plan 5b):** a held stock Yahoo can't price leaves every run degraded, so the buy form asks for confirmation when a stock isn't in the US or TSX lists (ETFs aren't). The watchlist accepts them with a note.
```

with:

```markdown
- **Unlisted stocks (Plan 5b):** a held stock Yahoo can't price leaves every run degraded, so the buy form asks for confirmation when a stock isn't in the US or TSX lists (ETFs aren't). The watchlist accepts them with a note, and a file import leaves them out unless the owner ticks them in (Plan 5c).
- **File import (Plan 5c):** one broker CSV at a time, all or nothing, at most 5,000 trades. Rows are matched against recorded trades by side, account, symbol, day, quantity and price, so re-importing a file adds nothing, but two identical trades on one day in one file count once. Dividends, transfers and fees are left out: the ledger has no cash.
- **Ticker sources (Plan 5c):** `source_health` has one row per source per run, not per symbol, so the Ticker page says which sources that cover the asset *answered* in the run, not which returned records for that symbol. Per-symbol contribution needs the collectors to report symbols.
```

In `docs/superpowers/deferred.md`, replace:

```markdown
- **`runs.summary`** gained `crypto` (held and watched coins) and `crypto_unquoted` in Plan 2e, and `news` (items, stories, rows, assets, sentiment status) in Plan 2f.
- **Ticker Detail news:** read `news_items` by symbol and asset type, newest first. Google News links are Google's own redirect pages; show the outlet beside each title.
```

with:

```markdown
- **`runs.summary`** gained `crypto` (held and watched coins) and `crypto_unquoted` in Plan 2e, and `news` (items, stories, rows, assets, sentiment status) in Plan 2f.
```

In `docs/superpowers/deferred.md`, replace:

```markdown
- **Sentiment status:** the scheduled run installs the `nlp` extra. So `summary.news.sentiment` reading `unavailable` means a broken install, and `failed: …` a model or scoring error. The run still publishes in both cases, so show them on the health view.
```

with:

```markdown
- **Sentiment status:** the scheduled run installs the `nlp` extra. So `summary.news.sentiment` reading `unavailable` means a broken install, and `failed: …` a model or scoring error. The run still publishes in both cases; Source health shows the reason (Plan 5c).
```

In `docs/superpowers/deferred.md`, replace:

```markdown
- Indexes on `picks.run_id` and `source_health.run_id`, added with their first readers.
```

with:

```markdown
- An index on `picks.run_id`, added with its first reader (`source_health.run_id` got one in Plan 5c).
```

In `docs/superpowers/deferred.md`, replace:

```markdown
- **yfinance cache lock:** yfinance's timezone cache sometimes reports "database is locked" during a threaded download and drops a symbol. It hit RY.TO in phase 1 of the 2026-10-16 live run (phase 2's retry priced it) and SPY in Plan 5a's backfill (the next run fetched it). If it recurs, give yfinance a per-run cache folder or download without threads.
- **Coin history** reaches 290 days, one Coinbase request. A coin bought earlier has no closes before then; the portfolio chart values such a coin at its first close until then; fetch older candles in more requests, back to the first buy, to chart that stretch.
```

with:

```markdown
- **yfinance cache lock:** yfinance's timezone cache sometimes reports "database is locked" during a threaded download and drops a symbol. It hit RY.TO in phase 1 of the 2026-10-16 live run (phase 2's retry priced it) and SPY in Plan 5a's backfill (the next run fetched it). If it recurs, give yfinance a per-run cache folder or download without threads.
```

In `web/README.md`, replace:

```markdown
warnings, buys and sells), the watchlist and settings. Picks, Ticker detail, Track record, Source
health and file import come in Plan 5c; actions, ranges and verdicts once the model exists (Plan 4).
```

with:

```markdown
warnings, buys and sells), the watchlist and settings. Plan 5c added the trade list with Delete,
file import, a Ticker page for any symbol (price, the owner's position, two days of news and the
sources that cover it) and Source health. Picks, Track record, verdicts, actions and the
forecast come with the model (Plans 3 and 4).
```

In `web/README.md`, replace:

```markdown
The dashboard adds buys and sells but doesn't edit or delete them yet (Plan 5c adds a list of
trades with Delete). Until then, in the Supabase dashboard, open Table Editor → `lots` (buys) or
`sells`, find the row by symbol and date, and edit or delete it. The next page load recomputes
values, returns and warnings.
```

with:

```markdown
Delete it under Trades on My Portfolio (the latest ten show; "Show all" lists the rest), then add
it again with the right values. Deleting a buy that a later sell needs warns first, because the
sell would then exceed what was held.
```

In `web/README.md`, replace:

```markdown
An old USD row from before spec rev 2 can't be edited until it has an `fx_rate_cad`. Fill one
in, or delete the row and add the trade again.
```

with:

```markdown
## Import a broker file

My Portfolio → Import file takes a CSV of the broker's activity (in Wealthsimple: Activity →
Export). Match each column to its meaning (the usual names are recognised), say how the file
writes dates, then review every row: buys and sells are imported, dividends and transfers are left
out, and trades already recorded are skipped, so importing the same file twice adds nothing. A
file whose sells would exceed what was held is refused whole. Stocks missing from the US and TSX
lists (ETFs) are left out unless ticked in. USD trades take the Bank of Canada rate of their day.
```

In `web/README.md`, replace:

```markdown
   Row-level security still limits every row to the owner.
```

with:

```markdown
   Row-level security still limits every row to the owner. `on all tables` covers only the tables
   that exist, so run it again after a migration adds one (Plan 5c added `sources` and the
   `source_last_ok` view).
```

- [ ] **Step 2: Run every suite**

Run (from `pipeline/`): `scripts/in-docker.sh uv run pytest -q`, then `scripts/in-docker.sh uv run ruff check .`
Expected: `666 passed`, then `All checks passed!`.

Run (from `web/`): `npm run lint`, `npm run typecheck`, `npm test`, then `npm run e2e`
Expected: lint and typecheck are clean; `Test Files  17 passed (17)`, `Tests  111 passed (111)`; then `41 passed`.

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/deferred.md web/README.md
git commit -m "docs: record what Plan 5c built and what waits for the model"
```
