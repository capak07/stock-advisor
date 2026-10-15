# Deferred work

These are items that the Plan 1, Plan 2a, Plan 2b, Plan 2c and Plan 2d reviews deliberately pushed to later plans. Each later plan must pick up its section before it is called done. The spec stays the authority; this list only records what earlier plans did not do.

## Plan 2g: 13F institutional ownership

- **Source 11 (SEC 13F data sets plus OpenFIGI CUSIP mapping) moved out of Plan 2d.** It needs a persistent CUSIP → ticker map (about 6,500 CUSIPs, roughly 27 minutes at OpenFIGI's keyless 25 requests a minute, then only new CUSIPs each quarter) and about 100 MB of quarterly SEC data sets. Research: `.superpowers/research/plan-2b/sec.md` §5. Fixtures: `.superpowers/research/plan-2c-fixtures/sec/13f_*` and `openfigi_cusip_mapping_sample.json` (git-ignored).

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
- **Analyst rotation:** `max_symbols` always takes the head of the missing list. Rotate the rest oldest-first, so the bottom of the analyst shortlist isn't left unfetched forever.
- **Earnings failure rate:** measure the first live run's per-symbol failure rate for `yfinance_earnings`.
- **Yahoo analyst throttling.** Three local full runs on 2026-10-14 got analyst data for 39 of 200, then 199 of 200, then none (`SilentFailure`, served stale). Each came right after the bulk price download from one busy IP. Fetched alone, 40 of 40 large caps had data, and earnings data was unaffected. If GitHub Actions runs show the same, fetch analyst data apart from the price download: in the 06:30 ET health job, or for priority symbols before prices.
- **XBRL facts are raw.** `sec_xbrl` keeps every listed concept and every re-reported or restated duplicate with its `filed` date. Features pick a concept per period by `METRICS` priority, take the latest fact filed on or before `as_of`, derive Q4 as FY minus 9M, and compute single quarters of cash-flow items from year-to-date facts (research `sec.md` §2.4–2.5).
- **Insider and holder signals.** Count only codes P and S from non-derivative rows for insider buying and selling, and treat `planned` (10b5-1) sales as weaker. For 13D/G, a 0-share 13G/A can be an index giant's entity realignment rather than an exit.
- **Amendments:** a Form 4/A restates trades already in the original Form 4, and both are stored (`form` tells them apart; the XML doesn't name the original's accession). Count a trade once: for the same owners, trade date, code and shares, keep the latest `accepted_at`. Do the same for 13D/G amendments of one reporting person.

## Plans 4 and 5: recommendations and dashboard

- A table for holding-action outcomes. Spec §6.5 grades holding actions, but §8 has no table for them.
- Decide spec §7.2 ("holdings analysis survives a later failure") against "failed runs are never published".
- A `published_runs` view, so the dashboard never reads unpublished rows.
- Show missed or dropped schedule slots on the dashboard.
- Indexes on `picks.run_id` and `source_health.run_id`, added with their first readers.
- **Old USD lots and sells:** pre-rev-2 USD lots and sells have no `fx_rate_cad`, and the `*_usd_needs_fx_rate` check (NOT VALID) still applies on UPDATE. Editing such a row fails until a rate is backfilled. Backfill from Bank of Canada rates first.
- **`settings.updated_at`** has no trigger. The Settings page must set it, or add a trigger.
- **Failed-run counts:** a failed run's per-market `priced` and `fresh` count only priority symbols.
- **`runs.summary` shape:** it changed in Plan 2b, from flat keys to `{"markets": {"US": …, "TSX": …}, …}`. The dashboard must read both shapes, or ignore runs from before the change.
- **Run summary `shortlist`:** the per-market `shortlist` excludes priority symbols but the top-level `shortlist` includes them. Rename one before the dashboard shows them side by side.

## Operational and minor

- **Breaker and deadlines:** a `DeadlineExceeded` failure counts toward the circuit breaker.
- **Stale versus partial:** a call whose fetched symbols all fail while the window served the rest reports STALE, not PARTIAL, and counts toward the breaker.
- **Run deadline:** it starts in `execute_run`, after job setup. Consider a 28-minute budget if runs approach the 40-minute kill.
- **FINRA symbol-key twins:** `BRK.B` and a plain `BRKB` share one key, and the later request wins silently.
- **No markers on PARTIAL:** a PARTIAL result writes no empty markers, so uncovered symbols are refetched while any symbol keeps failing. This costs capped slots.
- **Old shortlist default:** remove the `SHORTLIST_SIZE = 300` default and the unused `shortlist()` helper in `enrich.py`, or require an explicit size.

- **Deploy-time probe:** check that the `advisor_pipeline` login really cannot write holdings or run DDL on Supabase, and that Supavisor accepts the `advisor_pipeline.<project-ref>` user.
- **Run sweep:** sweep abandoned runs using SQL `now()` instead of the Python clock or `--now`, and move the sweep and state loading inside `execute_run`'s try.
- **Workflows:**
  - No-op cron runs re-save an identical Actions cache.
  - The `pipeline-run` concurrency group can cancel an older pending job.
- **Migrate CLI:** refuse `--baseline` once `schema_migrations` has rows, print the names it baselined, and take an advisory lock.
- **Dev machine:** a `uv` re-sync can fail with "Access is denied" on `.venv` under OneDrive. Use `uv run --no-sync ruff check .` for lint.
- **SEC document cache** (`<cache>/sec-documents/`) grows by roughly 1 MB a day of Form 4 and 13D/G XML; prune files older than 400 days.
- **XBRL bandwidth:** company facts are downloaded daily for every US symbol in the enrichment list (about 300 KB compressed each). If time or bandwidth becomes a problem, refresh a company only when its submissions show a new 10-K or 10-Q.
- **8-K bodies** (Exhibit 99.1 earnings text) are not downloaded; only the item codes are used.
- **SEC first fill:** the first live run fetched Form 4 documents for 42 of 299 US symbols (budget 1,000) and 13D/G for 122 (budget 500), so those two sources stay PARTIAL for about 5 and 3 runs (a second run added 67 and 110 symbols). Raise the budgets for the first deployment if that is too slow.
- **Unparseable SEC documents** are skipped and dropped from the cache, so every run downloads them again (one budget unit each) and nothing records the skip. Count skips into the source-health detail if they ever appear.
- **SEC client polish:** `filings()` returns the shared list (return a tuple); untested: a 403 through `get()` end to end and `DocumentBudget`'s deadline check. `sec_xbrl` copies every fact even for a company's first share class, and one malformed fact fails that symbol rather than being skipped.
- **Form 4 details:** a reporting owner's name can be empty; `acquired` is False when the A/D code is missing; no unit test covers rows skipped for a missing code, share count or date.
- **Runner coverage:** no runner-level test of a PER_RUN source (such as `sec_8k`) falling back to its cache within `freshness`.
