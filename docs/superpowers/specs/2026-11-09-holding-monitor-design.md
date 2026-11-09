# Holding monitor — design

**Status:** draft, 2026-11-09. The owner asked for "the holding part" of the day-trader skill pack
(github.com/Jakeschincariol/day-trader-skill, MIT) inside stock-advisor, and left the design calls to
Claude ("go with recommended approach and what suits best"). Calls Claude made are marked *(call)*.

## Why

The owner holds stocks for weeks to months. Between runs they want to know what happened to the stocks
they own or watch: news, company filings, earnings, insiders trading, and whether a price they care
about was reached. Today the pipeline already fetches almost all of this on every run (8-Ks, XBRL
financials, earnings dates, Form 4 insider trades), but apart from news it keeps none of it and the app
shows none of it. This design stores what is already fetched and shows it.

## Goals

1. **What's new on your stocks** — a card on My Portfolio listing, for held and watched stocks, what
   arrived since the previous published run, newest first, New York time:
   - headlines (from `news_items`, at most 3 per stock);
   - 8-K filings, each item in plain words ("2.02 → earnings results", "5.02 → director or officer
     change"), with the important items flagged: 1.03, 1.05, 2.02, 2.04, 2.06, 3.01, 4.02, 5.01, 5.02
     (the skill's list);
   - insider open-market buys and sells (Form 4 codes P and S), with "under a 10b5-1 plan" shown;
   - earnings reports due within the next 14 calendar days;
   - price alerts that were hit.
   An empty card says "Nothing new since the last run."
2. **Earnings on the ticker page** (US stocks) — a card with the last 6 quarters: revenue, gross,
   operating and net margin, net income and diluted EPS, each beside the same quarter a year earlier,
   plus the trailing twelve months, and up to 3 plain sentences on what changed (revenue growth, a
   margin moving 1 point or more, EPS growth). It names the latest filing (10-Q/10-K, filed date).
3. **Earnings dates on the ticker page** (US and TSX) — the next report date with the EPS estimate, and
   the last 4 reports with actual EPS and surprise.
4. **Filings and insiders on the ticker page** (US) — the 8-Ks of the last 90 days (date, items in words,
   a link to the document on sec.gov) and insider buys/sells of the last 90 days (date, who and role,
   buy or sell, shares, price, value, plan flag).
5. **Price alerts** — on the ticker page of any stock or coin the owner can add an alert: above or
   below a price, with an optional note. The run marks an alert hit when the latest price it fetched
   crosses the level; the owner dismisses it. Alerts are listed on the ticker page and hits appear in
   goal 1. *(call)* In-app only: spec R8 and its non-goals rule out push, email and chat notifications,
   and the app only looks at prices on its runs (about 3 a day), so a hit means "crossed by the last
   run", which the card says.

## Non-goals

- Day-trading pieces of the pack: scanner, entry, exit, time machine, budget, risk, broker. Spec
  non-goals already exclude intraday signals and order execution.
- Congress trades. Deferred to Plan 2j in `docs/superpowers/deferred.md` with a personal-use-only
  constraint; not part of this design.
- New data sources, analyst ratings, 13F/13D holders. *(call)* Not in the skill's holding part; the
  data is fetched but adds a lot of page for little.
- Any change to forecasts, picks, verdicts or holding actions. This is display only; the model's
  features are untouched.
- TSX filings, financials and insiders: SEDAR+ and SEDI have no free API (spec R7). TSX stocks get
  news, earnings dates and alerts.
- Push, email or chat notifications (spec R8).

## Data

One migration, `0012_holding_monitor.sql`. Pipeline tables follow the `0006`/`0007` pattern: RLS on,
`owner_read`, `pipeline_write`, explicit grants to `pipeline_rw`.

| table | key | columns | written | kept |
| --- | --- | --- | --- | --- |
| `filings` | `accession` | `symbol, form, filed_at (timestamptz, accepted time or filing date), report_date, items text[], url, added_at (first stored; kept on rewrite)` | every run, from `sec_8k` records, every enriched US symbol | 400 days |
| `financial_quarters` | `(symbol, period_end)` | `period_start, fiscal_year, fiscal_period, revenue, gross_profit, operating_income, net_income, eps_diluted, form, filed, accession, derived bool` | every run, from `sec_xbrl` records, every enriched US symbol | the latest 12 per symbol |
| `earnings_reports` | `(symbol, report_date)` | `report_at, eps_estimate, eps_actual, surprise_pct` | every run, from `yfinance_earnings` records; a written symbol's reports without an actual that the fetch no longer lists (a moved date) are deleted | 3 years |
| `insider_trades` | `(accession, line)` | `symbol, filed_at, trade_date, owner, role, code (P/S), shares, price, value, planned, added_at (first stored; kept on rewrite)` | every run, from `sec_form4` records with code P or S and not derivative | 400 days |
| `price_alerts` (owner table) | `id` | `symbol, asset_type, direction (above/below), level, note, created_at, hit_at, hit_price, dismissed_at` | the owner inserts, edits, dismisses and deletes; the pipeline sets only `hit_at` and `hit_price` | until deleted |

- `filings.url`: `https://www.sec.gov/Archives/edgar/data/<cik>/<accession without dashes>/<primary
  document>`. `MaterialEvent` gains `cik` and `primary_document` (both already on `Filing`).
- `price_alerts` grants: owner insert/update/delete like `watchlist`; `pipeline_rw` gets select and a
  column-level `update (hit_at, hit_price)` only.
- Quarters: a pure function turns a symbol's `FinancialFact`s into single quarters. A quarter is a
  duration of 80–100 days; a fiscal Q4 is derived as the annual (350–380 days) value minus the three
  quarters inside it (EPS is derived the same way and marked `derived`); when a period was reported
  more than once, the latest `filed` wins; gross profit falls back to revenue − cost of revenue. This
  follows the skill's `trader-analyst/facts.py` (MIT, credited in the module docstring).

## Pipeline

- A new stage, **holding monitor**, runs right after the news stage (stage 5) in `execute_run`. It reads
  `results` (already collected), writes the four pipeline tables in one transaction and prunes them.
  Like the other late stages it is wrapped in try/except: a failure is recorded in the run summary
  (`holding_monitor_error`) and the run still publishes.
- **Alerts** are checked in the same stage against the latest price the run has for each alert's
  symbol (the phase-1 price for held and watched assets, else the latest `daily_closes` close).
  An undismissed, unhit alert whose level was crossed gets `hit_at = now`, `hit_price`.
- `priority_order` adds symbols that have an active alert, so their prices are fetched.
- All SQL lives in `store/repo.py` (project rule).

## Web

- `web/lib/data/monitor.ts` — loader for the portfolio card: held + watched symbols, items since the
  previous published run's start (or the last 48 hours when there is no previous run). Filings and
  insider trades count from `added_at` (a daily source or a failed fetch stores them late), and only
  those filed in the last 14 days, so a first backfill doesn't flood the card.
- `web/lib/earnings.ts` — pure: year-ago matching (same period end ± 10 days a year earlier), margins,
  TTM (4 quarters spanning under 300 days), "what changed" sentences. Unit-tested with Vitest.
- `web/lib/filings.ts` — pure: 8-K item labels and the important set.
- Components: `MonitorCard` on My Portfolio (after the Actions card); `EarningsCard`, `FilingsCard`,
  `InsidersCard`, `AlertsCard` on the ticker page (after the Forecast card; US-only cards are hidden
  for TSX and crypto).
- Server actions for alerts: add, dismiss, delete, validated with the existing input patterns.
- Wording rules (as on Picks and Invest): facts, no "buy"/"sell" advice from this data; insider buying
  is described, not interpreted.

## Testing

- Pipeline unit: quarter derivation (Q4 derivation, restatement, gross-profit fallback, EPS), 8-K URL,
  insider filter (P/S only, derivatives out), alert crossing (above/below, dismissed, already hit),
  stage error handling.
- Pipeline integration (db fixture): migration applies; RLS and grants (owner cannot write pipeline
  tables; pipeline can update only `hit_at`, `hit_price` on `price_alerts`); repo upserts are idempotent;
  prunes keep the right rows.
- Web: Vitest for `earnings.ts`, `filings.ts` and the monitor feed ordering; Playwright for the portfolio
  card, the ticker cards and adding/dismissing an alert. `e2e/db.ts` `resetData` lists the new tables.

## Builder's latitude

Exact card layout and copy within the wording rules; component split; how many headlines to show on
the portfolio card beyond the cap of 3 per stock.
