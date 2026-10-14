# Deferred work

These are items that the Plan 1 and Plan 2a reviews deliberately pushed to later plans. Each later plan must pick up its section before it is called done. The spec stays the authority; this list only records what earlier plans did not do.

## Plan 2c, Task 0: must land before the first real enrichment source

- **Run deadline.**
  - Bound the enrichment stage and the health check, with cooperative cancellation: `get_with_retries` stops retrying past the deadline, and unfinished sources are recorded as FAILED "deadline exceeded".
  - Today a single source can take about 4 minutes in the worst case (4 × 20 s timeout plus 3 × 60 s Retry-After waits). The job is killed at 40 minutes, which leaves an abandoned, unpublished run.
- **Cadence-window cache.**
  - DAILY and WEEKLY sources serve per-symbol records cached within the current window (ET date, or ISO week) as OK, and fetch only the missing symbols.
  - A PARTIAL result is backfilled from the cache.
  - This is needed for slow or capped sources such as Yahoo analyst data and Google Trends.
- **One `RateLimiter` per provider**, built in `build_registry`. The SEC allows 10 requests per second per IP across all SEC collectors.
- **Health check:** write each row as its source finishes, and run sources concurrently with a per-source time budget. Today a timeout loses every row.
- **Written collector contract** (a docstring in `collectors/base.py`, plus `README` or docs):
  - collectors never touch the DB connection;
  - `record.symbol` is the canonical requested symbol;
  - `PartialFetch` is for per-request failures, and an empty one counts as a failure;
  - `canary_requires_records` is True only for sources that must always return data.

## Plans 2c to 2e

- **Collectors covering both stocks and crypto** (LINK, SOL and COMP exist as both): keep the asset types apart in symbol lists and cache keys before the first such collector.
- **Crypto holdings priced in phase 1:** CoinGecko is core for crypto (2e).

## Plan 3: model and features

- **Jump indicator feature** (spec §10). Plan 2b keeps flagged bars and records `unconfirmed_jump` for the latest bar of each priority symbol. Plan 3 turns flagged days into the jump feature and blocks a Buy on them (§6.1). A bad first bar in a window is never flagged, because there is no earlier close to compare.
- **Exclude non-common instruments before any pick exists:**
  - ETNs with `ETF=N` (AMUB, BDCZ, DGP and others);
  - structured trusts (GJH, JBK, KTN);
  - CHSCN (a preferred);
  - Empire State Realty OP units.

  Use yfinance `quoteType` from sector mapping. Closed-end funds are an owner decision. Run the same check on TSX symbols, for income trusts and closed-end funds whose names the TMX filter cannot recognise.
- **Partial current-day bar** at the pre-close run, from Yahoo. Features must treat today's bar as incomplete.
- **Benchmarks** (SPY, XIU.TO, sector ETFs) need a distinct asset type. Otherwise `upsert_symbols` deactivates them.
- **Data quality:** `adv20` on histories shorter than 20 bars, and clamping `DailyBar` high/low inconsistencies.

## Plans 4 and 5: recommendations and dashboard

- A table for holding-action outcomes. Spec §6.5 grades holding actions, but §8 has no table for them.
- Decide spec §7.2 ("holdings analysis survives a later failure") against "failed runs are never published".
- A `published_runs` view, so the dashboard never reads unpublished rows.
- Show missed or dropped schedule slots on the dashboard.
- Indexes on `picks.run_id` and `source_health.run_id`, added with their first readers.

## Operational and minor

- **Deploy-time probe:** check that the `advisor_pipeline` login really cannot write holdings or run DDL on Supabase, and that Supavisor accepts the `advisor_pipeline.<project-ref>` user.
- **Run sweep:** sweep abandoned runs using SQL `now()` instead of the Python clock or `--now`, and move the sweep and state loading inside `execute_run`'s try.
- **Workflows:**
  - No-op cron runs re-save an identical Actions cache.
  - The `pipeline-run` concurrency group can cancel an older pending job.
- **Migrate CLI:** refuse `--baseline` once `schema_migrations` has rows, print the names it baselined, and take an advisory lock.
- **Dev machine:** a `uv` re-sync can fail with "Access is denied" on `.venv` under OneDrive. Use `uv run --no-sync ruff check .` for lint.
