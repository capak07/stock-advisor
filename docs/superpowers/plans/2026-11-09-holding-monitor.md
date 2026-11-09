# Holding Monitor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store the 8-Ks, quarterly financials, earnings dates and insider trades the pipeline already fetches, add owner price alerts, and show them on My Portfolio and the ticker page.

**Architecture:** One migration adds four pipeline tables and one owner table. A new pipeline stage (`monitor_stage`) turns the enrichment `results` into rows with pure builders in `advisor/monitor/`, writes them via `store/repo.py`, and marks price alerts hit. The web app reads them with server-only loaders and renders new cards; pure TS helpers do the earnings math and the feed.

**Tech Stack:** Python 3.12, psycopg 3, pydantic, pytest; Supabase Postgres + RLS; Next.js (App Router, server components, server actions), Vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-11-09-holding-monitor-design.md`

## Global Constraints

- Display only: no change to forecasts, picks, verdicts, holding actions or model features.
- No new data sources; no push/email/chat notifications (spec R8).
- US-only cards (earnings financials, filings, insiders) are hidden for TSX stocks and crypto.
- All SQL in `pipeline/src/advisor/store/repo.py`; web data access only in `web/lib/data/*.ts` (`'server-only'`).
- New pipeline tables: RLS on, `owner_read`, `pipeline_write`, `grant select, insert, update, delete ... to pipeline_rw` (pattern of `0006_price_history.sql`).
- `price_alerts`: owner insert/update/delete (like `watchlist` in `0002_rls.sql`); `pipeline_rw` gets `select` and `update (hit_at, hit_price)` only.
- Retention: `filings` and `insider_trades` 400 days; `earnings_reports` 3 years; `financial_quarters` latest 12 per symbol.
- Important 8-K items: `1.03, 1.05, 2.02, 2.04, 2.06, 3.01, 4.02, 5.01, 5.02`. Item 9.01 (exhibits) is never shown.
- A monitor-stage failure never fails the run: it lands in the summary as `holding_monitor_error`.
- Wording: facts only; never "buy"/"sell" advice from this data. Alerts say "crossed by the last run".
- Python tests only via `pipeline/scripts/in-docker.sh uv run pytest ...`; lint `uv run ruff check .`. Files LF line endings.
- Credit the skill in `advisor/monitor/quarters.py`'s docstring: "Quarter logic follows trader-analyst/facts.py from github.com/Jakeschincariol/day-trader-skill (MIT)."

## Review Focus

1. A company whose fiscal year doesn't end in December (e.g. AAPL, September): Q4 derivation must use the three quarters inside that fiscal year, and year-ago matching must use period ends, not calendar quarters.
2. A restated quarter (same period, two filings): the later `filed` wins, and the upsert replaces the row.
3. An alert whose symbol has no close in `daily_closes` (new listing, failed fetch): left unhit, no error.
4. The monitor card when there is no previous published run (first run): falls back to the last 48 hours, no crash.
5. A run where `sec_8k`/`sec_form4`/`sec_xbrl` failed (no `results[name]`): the stage writes what it has and skips the rest without error.

---

### Task 1: Migration and schema tests

**Files:**
- Create: `supabase/migrations/0012_holding_monitor.sql`
- Modify: `pipeline/tests/integration/test_schema.py` (add tests), `web/e2e/db.ts` (`resetData` truncates the five new tables)

**Interfaces:**
- Produces tables (all `symbol text not null`):
  - `filings(accession text primary key, symbol, form text not null, filed_at timestamptz not null, report_date date, items text[] not null default '{}', url text not null)`, index `(symbol, filed_at desc)`.
  - `financial_quarters(symbol, period_end date, period_start date not null, fiscal_year int, fiscal_period text, revenue numeric, gross_profit numeric, operating_income numeric, net_income numeric, eps_diluted numeric, form text not null, filed date not null, accession text not null, derived boolean not null default false, primary key (symbol, period_end))`.
  - `earnings_reports(symbol, report_date date, report_at timestamptz not null, eps_estimate numeric, eps_actual numeric, surprise_pct numeric, primary key (symbol, report_date))`.
  - `insider_trades(accession text, line int, symbol, filed_at timestamptz not null, trade_date date not null, owner text not null, role text not null, code text not null check (code in ('P','S')), shares numeric not null, price numeric, value numeric, planned boolean not null, primary key (accession, line))`, index `(symbol, trade_date desc)`.
  - `price_alerts(id bigint generated always as identity primary key, symbol, asset_type text not null check (asset_type in ('stock','crypto')), direction text not null check (direction in ('above','below')), level numeric not null check (level > 0), note text check (char_length(note) <= 200), created_at timestamptz not null default now(), hit_at timestamptz, hit_price numeric, dismissed_at timestamptz)`.

- [ ] **Step 1: Write failing tests** in `test_schema.py` using the existing `db` / `owned_db` fixtures and their helpers:
  - `test_holding_monitor_tables_exist` — the five tables are present.
  - `test_owner_cannot_write_pipeline_monitor_tables` — an owner-session insert into `filings` fails.
  - `test_owner_manages_price_alerts` — owner can insert, update `dismissed_at`, delete.
  - `test_pipeline_may_only_set_alert_hits` — as `pipeline_rw`: `update price_alerts set hit_at = now(), hit_price = 1` succeeds; `update price_alerts set level = 2` fails with insufficient privilege; insert fails.
  (The existing whole-schema RLS/pipeline-policy checks must also pass.)
- [ ] **Step 2: Run** `pipeline/scripts/in-docker.sh uv run pytest -q tests/integration/test_schema.py` — Expected: the four new tests FAIL (tables missing).
- [ ] **Step 3: Write the migration** per Interfaces and Global Constraints.
- [ ] **Step 4: Run** the same command — Expected: all pass.
- [ ] **Step 5: Add the five tables to `resetData`** in `web/e2e/db.ts`.
- [ ] **Step 6: Commit** `feat: holding monitor tables`.

### Task 2: 8-K document URL

**Files:**
- Modify: `pipeline/src/advisor/collectors/sec_events.py`
- Test: `pipeline/tests/unit/test_sec_events.py`

**Interfaces:**
- Produces: `MaterialEvent` gains `cik: int | None = None`, `primary_document: str | None = None` (filled from the `Filing` the record is built from); module function `filing_url(event: MaterialEvent) -> str | None` → `https://www.sec.gov/Archives/edgar/data/{cik}/{accession without dashes}/{primary_document}`, `None` if either is missing.

- [ ] **Step 1: Failing tests:** an existing fixture's events carry `cik` and `primary_document`; `filing_url` of a known event equals the exact expected URL; `filing_url` with `primary_document=None` is `None`.
- [ ] **Step 2: Run** `... pytest -q tests/unit/test_sec_events.py` — Expected: FAIL.
- [ ] **Step 3: Implement.** Defaults keep old cached records loadable.
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** `feat: keep each 8-K's document link`.

### Task 3: Single quarters from XBRL facts

**Files:**
- Create: `pipeline/src/advisor/monitor/__init__.py`, `pipeline/src/advisor/monitor/quarters.py`
- Test: `pipeline/tests/unit/test_monitor_quarters.py`

**Interfaces:**
- Consumes: `FinancialFact` (`collectors/sec_xbrl.py`).
- Produces:
  ```python
  @dataclass(frozen=True)
  class QuarterRow:
      symbol: str
      period_start: date
      period_end: date
      fiscal_year: int | None
      fiscal_period: str | None  # "Q1".."Q4"
      revenue: float | None
      gross_profit: float | None
      operating_income: float | None
      net_income: float | None
      eps_diluted: float | None
      form: str
      filed: date
      accession: str
      derived: bool
  def single_quarters(facts: Sequence[FinancialFact], keep: int = 12) -> list[QuarterRow]  # one symbol's facts; newest `keep`, oldest first
  ```
  Rules: quarter = duration 80–100 days; annual = 350–380 days; for each annual period whose three quarters inside it exist, derive Q4 = annual − sum(three) for every metric (EPS too), `derived=True`, `period_start` = day after the third quarter's end; duplicates of a (metric, start, end) keep the latest `filed`; `gross_profit` falls back to `revenue − cost_of_revenue`; `fiscal_period` counts quarters from the fiscal year start (annual period's start); `form/filed/accession` from the latest fact used.

- [ ] **Step 1: Failing tests** (build `FinancialFact`s inline):
  - `test_quarters_from_10q_durations_ignore_year_to_date` — a 10-Q with 3-month and 9-month revenue gives one row with the 3-month value.
  - `test_q4_is_annual_minus_three_quarters` — Sept fiscal year: Q1–Q3 revenue 10, 11, 12 and annual 50 → Q4 revenue 17, `derived` True, `fiscal_period` "Q4".
  - `test_restated_quarter_keeps_latest_filing` — same period filed twice (values 10 then 12) → 12.
  - `test_gross_profit_falls_back_to_revenue_minus_cost` — revenue 100, cost 60, no GrossProfit → 40.
  - `test_keeps_newest_twelve_oldest_first`.
- [ ] **Step 2: Run** `... pytest -q tests/unit/test_monitor_quarters.py` — Expected: FAIL (module missing).
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** `feat: single quarters from XBRL facts`.

### Task 4: Row builders and alert crossing

**Files:**
- Create: `pipeline/src/advisor/monitor/rows.py`
- Test: `pipeline/tests/unit/test_monitor_rows.py`

**Interfaces:**
- Consumes: `MaterialEvent`, `filing_url` (Task 2), `InsiderTrade` (`collectors/sec_insiders.py`), `EarningsReport` (`collectors/yfinance_earnings.py`).
- Produces (frozen dataclasses mirroring the Task 1 columns):
  - `FilingRow(accession, symbol, form, filed_at, report_date, items, url)`; `filing_rows(events: Iterable[MaterialEvent]) -> list[FilingRow]` — skips events with no URL; `filed_at` = `accepted_at` or the filing date at 00:00 ET; one row per accession.
  - `InsiderRow(accession, line, symbol, filed_at, trade_date, owner, role, code, shares, price, value, planned)`; `insider_rows(trades: Iterable[InsiderTrade]) -> list[InsiderRow]` — only `code in {"P","S"}` and `not derivative`; `line` = order within the accession (0-based); `owner` = owners joined with " & "; `role` = officer title, else "Director", "10% owner", "Officer" in that order of preference, else "Insider"; `value = shares * price` when price known.
  - `EarningsRow(symbol, report_date, report_at, eps_estimate, eps_actual, surprise_pct)`; `earnings_rows(reports: Iterable[EarningsReport]) -> list[EarningsRow]` — `report_date` = `report_at`'s ET date; one per (symbol, date), last wins.
  - `PriceAlert(id, symbol, asset_type, direction, level)`; `alert_hits(alerts: Iterable[PriceAlert], prices: Mapping[tuple[str, str], float]) -> list[tuple[int, float]]` — (id, price) for alerts with a price where `above`: price ≥ level, `below`: price ≤ level. Callers pass only active (unhit, undismissed) alerts.

- [ ] **Step 1: Failing tests** — one per rule above, including: an `A` (grant) code and a derivative trade are dropped; a joint filing owner string; 10b5-1 `planned` carried; event without `primary_document` skipped; `above` at exactly the level hits; alert with no price is not in the result.
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** `feat: holding monitor rows and alert crossing`.

### Task 5: Repo functions

**Files:**
- Modify: `pipeline/src/advisor/store/repo.py`
- Test: `pipeline/tests/integration/test_repo.py`

**Interfaces:**
- Consumes: Task 3/4 row types.
- Produces:
  - `write_filings(conn, rows: Sequence[FilingRow]) -> None` — upsert on `accession`.
  - `write_financial_quarters(conn, rows: Sequence[QuarterRow]) -> None` — upsert on `(symbol, period_end)`, replacing every column; then delete each written symbol's rows beyond its newest 12 `period_end`s.
  - `write_earnings_reports(conn, rows: Sequence[EarningsRow]) -> None` — upsert on `(symbol, report_date)`.
  - `write_insider_trades(conn, rows: Sequence[InsiderRow]) -> None` — insert, `on conflict do nothing`.
  - `prune_holding_monitor(conn, now: datetime) -> None` — filings `filed_at` and insider trades `filed_at` older than 400 days; earnings reports older than 3 years.
  - `active_price_alerts(conn) -> list[PriceAlert]` — `hit_at is null and dismissed_at is null`.
  - `alert_symbols(conn) -> set[AssetRef]` — symbols of active alerts.
  - `latest_closes(conn, refs: Iterable[AssetRef]) -> dict[tuple[str, str], float]` — each asset's newest `daily_closes.close`, keyed `(symbol, asset_type)`.
  - `mark_alerts_hit(conn, hits: Sequence[tuple[int, float]], now: datetime) -> None` — sets `hit_at`, `hit_price` only where `hit_at is null`.

- [ ] **Step 1: Failing tests** (db fixture): each writer twice is idempotent; a restated quarter replaces values; 13 quarters keep 12; prune removes a 401-day filing and keeps a 399-day one; `latest_closes` returns the newest day; `mark_alerts_hit` does not overwrite an earlier hit; all run as the pipeline role where the fixture supports it.
- [ ] **Step 2: Run** `... pytest -q tests/integration/test_repo.py -k "filing or quarter or earnings or insider or alert or latest_closes"` — Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** `feat: repo for the holding monitor`.

### Task 6: The monitor stage in the run

**Files:**
- Create: `pipeline/src/advisor/monitor/stage.py`
- Modify: `pipeline/src/advisor/run.py`
- Test: `pipeline/tests/integration/test_run.py` (or a new `tests/integration/test_monitor_stage.py` following `test_run.py`'s fixtures)

**Interfaces:**
- Consumes: Tasks 2–5; `results: Mapping[str, CollectorResult]` with names `sec_8k`, `sec_xbrl`, `yfinance_earnings`, `sec_form4` (check the registry for the exact names and use those).
- Produces: `monitor_stage(conn, results, now_utc) -> dict` — groups XBRL facts by symbol → `single_quarters`; builds the other rows; in one `conn.transaction()` writes all four, prunes, then checks alerts (`active_price_alerts` → `latest_closes` → `alert_hits` → `mark_alerts_hit`). Returns `{"filings": n, "quarters": n, "earnings": n, "insider_trades": n, "alerts_hit": n}`; a missing collector result is skipped silently.
- `run.py`: priority stocks and crypto also include `repo.alert_symbols(conn)` (after holdings and watchlist, deduplicated, alphabetical); call `monitor_stage` right after `record_history` inside `if enriched:`, wrapped in try/except → `summary["holding_monitor_error"] = f"{type(exc).__name__}: {exc}"[:200]`; on success `summary["holding_monitor"] = <dict>`.

- [ ] **Step 1: Failing tests:** a stage call with fake `CollectorResult`s writes rows to all four tables and marks a crossed alert; a stage call with `results={}` returns zeros; `execute_run` with a stage that raises still publishes and records `holding_monitor_error` (monkeypatch `monitor_stage`); a stock with only an active alert is in the priority list.
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the new tests, then the full suite `... uv run pytest -q` (about 25 min) and `uv run ruff check .` — Expected: all pass.
- [ ] **Step 5: Commit** `feat: holding monitor stage in the run`.

### Task 7: Web pure helpers

**Files:**
- Create: `web/lib/filings.ts`, `web/lib/earnings.ts`, `web/lib/monitor.ts` and their `*.test.ts`

**Interfaces:**
- Produces:
  - `filings.ts`: `ITEM_LABELS: Record<string, string>` (the skill's `ITEMS_8K` list), `IMPORTANT_ITEMS: ReadonlySet<string>`, `itemLabels(items: string[]): string[]` (drops 9.01, unknown → "item X.XX"), `isImportant(items: string[]): boolean`.
  - `earnings.ts`: `type Quarter = { periodEnd: string; fiscalPeriod: string | null; revenue: number | null; grossProfit: number | null; operatingIncome: number | null; netIncome: number | null; epsDiluted: number | null }`; `yearAgo(q: Quarter, all: Quarter[]): Quarter | null` (period end 365 ± 10 days earlier); `margins(q)` → `{ gross, operating, net }` fractions or null; `ttm(all: Quarter[])` → sums of the newest 4 if they span < 300 days, else null; `changes(all: Quarter[]): string[]` — at most 3 sentences, e.g. "Revenue up 12% on the same quarter a year earlier", "Operating margin 18.0%, up 2.1 points", "Diluted EPS $1.42, up from $1.10".
  - `monitor.ts`: `type FeedItem = { kind: 'news'|'filing'|'insider'|'earnings'|'alert'; symbol: string; at: string; title: string; detail?: string; url?: string; important?: boolean }`; `buildFeed(parts: {...}, opts: { since: string; now: string }): FeedItem[]` — news capped at 3 per symbol, earnings only within the next 14 days, sorted by `at` descending (upcoming earnings first).
- [ ] **Step 1: Failing Vitest tests** for each function, incl. Sept fiscal year year-ago matching, ttm null when quarters are missing, 9.01 dropped, the news cap.
- [ ] **Step 2: Run** `node node_modules/vitest/vitest.mjs run lib/filings lib/earnings lib/monitor` (from `web/`) — Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** — Expected: PASS; also `node node_modules/typescript/bin/tsc --noEmit`.
- [ ] **Step 5: Commit** `feat: earnings, filings and feed helpers`.

### Task 8: Loaders and cards

**Files:**
- Create: `web/lib/data/monitor.ts`, `web/components/portfolio/MonitorCard.tsx`, `web/components/ticker/EarningsCard.tsx`, `web/components/ticker/FilingsCard.tsx`, `web/components/ticker/InsidersCard.tsx`
- Modify: `web/app/(app)/page.tsx` (MonitorCard after the ActionsCard), `web/app/(app)/ticker/[symbol]/page.tsx` (cards after the Forecast card; US stocks only for the three US cards), `web/lib/data/ticker.ts` or a new loader for ticker monitor data
- Test: `web/e2e/monitor.spec.ts`, seed helpers in `web/e2e/db.ts` (`seedFiling`, `seedQuarter`, `seedEarnings`, `seedInsider`, `seedAlert`)

**Interfaces:**
- Consumes: Task 7 helpers; tables from Task 1.
- Produces: `loadMonitorFeed(supabase): Promise<FeedItem[]>` (held + watched symbols; since = previous published run's `started_at`, else now − 48 h); `loadHoldingData(supabase, symbol): Promise<{ quarters: Quarter[]; latestFiling: {form: string; filed: string} | null; earnings: {...}[]; filings: {...}[]; insiders: {...}[]; alerts: {...}[] }>`.
- Copy: card titles "What's new on your stocks", "Earnings", "Filings (8-K)", "Insider trades"; empty states "Nothing new since the last run.", "No 8-K stored for the last 90 days. Filings are collected for stocks you hold, watch or that a run shortlists.", "No insider buys or sells stored for the last 90 days. They are collected for stocks you hold, watch or that a run shortlists."; insider rows say "bought"/"sold" and "(10b5-1 plan)".
- [ ] **Step 1: Failing e2e** (`monitor.spec.ts`): seeded holding with a news item, an important 8-K, an insider buy and an earnings date in 5 days shows all four on My Portfolio; the ticker page of a US stock shows the Earnings table with a year-ago column and the Filings and Insider cards; a TSX stock's ticker page has no Filings card.
- [ ] **Step 2: Run** `npx playwright test e2e/monitor.spec.ts` from the main checkout (the worktree junction breaks Turbopack) — Expected: FAIL.
- [ ] **Step 3: Implement** loaders and cards following `NewsCard.tsx` / `Cards.tsx` styles.
- [ ] **Step 4: Run** the spec, then vitest, tsc and `node node_modules/eslint/bin/eslint.js lib components app e2e` — Expected: all pass.
- [ ] **Step 5: Commit** `feat: holding monitor cards`.

### Task 9: Price alerts

**Files:**
- Create: `web/lib/alert-form.ts` (+ `alert-form.test.ts`), `web/app/(app)/ticker/[symbol]/alerts.ts` (server actions), `web/components/ticker/AlertsCard.tsx`
- Modify: ticker page (AlertsCard for every asset), `web/lib/data/monitor.ts` (hit, undismissed alerts in the feed as `kind: 'alert'`, title "TSLA crossed above $400.00 by the last run", detail the hit price)
- Test: `web/e2e/alerts.spec.ts`

**Interfaces:**
- Produces: `parseAlert(input: { symbol: string; assetType: string; direction: string; level: string; note?: string }): { ok: true; value: {...} } | { ok: false; errors: Record<string, string> }` — level a positive number with at most 8 decimals; note ≤ 200 chars; direction above/below. Server actions `addAlert(...)`, `dismissAlert(id)`, `deleteAlert(id)` returning `FormState` like `watchlist/actions.ts`, then `revalidatePath('/')` and the ticker page.
- AlertsCard copy: "Alerts are checked on each run (about 3 a day), not live, and appear only here and on My Portfolio."
- [ ] **Step 1: Failing tests:** Vitest for `parseAlert` (bad level, zero, long note, good input); e2e: add an alert on a ticker page, see it listed; a seeded hit alert appears on My Portfolio and disappears after Dismiss.
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** vitest, tsc, eslint and the full e2e suite `npx playwright test` — Expected: all pass.
- [ ] **Step 5: Commit** `feat: price alerts`.
