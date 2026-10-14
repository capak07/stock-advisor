# Deferred work

These are items that the Plan 1, Plan 2a and Plan 2b reviews deliberately pushed to later plans. Each later plan must pick up its section before it is called done. The spec stays the authority; this list only records what earlier plans did not do.

## Plan 2d: SEC

- **One shared limiter for every SEC collector,** built in `build_registry`, the same way as FINRA and Yahoo. SEC allows 10 requests per second per IP.
- **The SEC contact string:** add `SEC_USER_AGENT` (an optional setting; SEC requires a contact in every request) with `MissingCredential`, which fails only the SEC sources when it is unset.
- **Recorded fixtures:** the SEC fixtures are in `.superpowers/research/plan-2c-fixtures/sec/` (git-ignored). Copy the ones the plan uses into `pipeline/tests/fixtures/sec/`.

## Plan 2e

- **Collectors covering both stocks and crypto** (LINK, SOL and COMP exist as both): keep the asset types apart in symbol lists and cache keys before the first such collector.
- **Crypto holdings priced in phase 1:** CoinGecko is core for crypto (2e).

## Plan 3: model and features

- **Unconfirmed jumps in the wild:** the first live run flagged an unconfirmed jump somewhere in the 100-day window for about 4.7% of priced symbols. Check what they are (microcaps, biotech, bad data) before building the jump feature.
- **TSX universe size:** the live TMX filter keeps about 675 TSX symbols, while spec §4.3 says about 1,500. Update the spec's number.
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
- **Old USD lots and sells:** pre-rev-2 USD lots and sells have no `fx_rate_cad`, and the `*_usd_needs_fx_rate` check (NOT VALID) still applies on UPDATE. Editing such a row fails until a rate is backfilled. Backfill from Bank of Canada rates first.
- **`settings.updated_at`** has no trigger. The Settings page must set it, or add a trigger.
- **`runs.summary` shape:** it changed in Plan 2b, from flat keys to `{"markets": {"US": …, "TSX": …}, …}`. The dashboard must read both shapes, or ignore runs from before the change.
- **Run summary `shortlist`:** the per-market `shortlist` excludes priority symbols but the top-level `shortlist` includes them. Rename one before the dashboard shows them side by side.

## Operational and minor

- **Old shortlist default:** remove the `SHORTLIST_SIZE = 300` default and the unused `shortlist()` helper in `enrich.py`, or require an explicit size.

- **Deploy-time probe:** check that the `advisor_pipeline` login really cannot write holdings or run DDL on Supabase, and that Supavisor accepts the `advisor_pipeline.<project-ref>` user.
- **Run sweep:** sweep abandoned runs using SQL `now()` instead of the Python clock or `--now`, and move the sweep and state loading inside `execute_run`'s try.
- **Workflows:**
  - No-op cron runs re-save an identical Actions cache.
  - The `pipeline-run` concurrency group can cancel an older pending job.
- **Migrate CLI:** refuse `--baseline` once `schema_migrations` has rows, print the names it baselined, and take an advisory lock.
- **Dev machine:** a `uv` re-sync can fail with "Access is denied" on `.venv` under OneDrive. Use `uv run --no-sync ruff check .` for lint.
