# Cursor task: Plan 4b's pages (Today's Picks, "I bought this", watchlist verdicts, the Ticker forecast)

**Paste this file into Cursor's agent** (or open it and say "do this task"). Work on branch `plan-4b-dashboard`.

## Read first, in this order

1. `docs/superpowers/plans/2026-10-27-plan-4b-suggestions-dashboard.md`:
   - its **Addendum**, which overrides the text below it;
   - Global Constraints, Decisions and Review Focus;
   - the tasks named in "What to build" below.

   The plan's tests and copy are exact; use them.
2. `web/AGENTS.md`. This Next.js differs from what you know: check `web/node_modules/next/dist/docs/` before using an API you're unsure of, and copy patterns from existing pages.
3. The approved design mockups: `.superdesign/design_iterations/picks_1.html`, `watchlist_1.html` and `ticker_1.html`, their CSS in `dashboard_1.css`, and the pages' `<style>` blocks.
4. Existing pages to imitate:
   - `web/app/(app)/page.tsx` and `web/components/portfolio/Cards.tsx` (cards, chips, range bar, `section-head`, `enter`/`stagger`);
   - `web/app/(app)/invest/page.tsx`.

## Already built (use, don't change)

**`web/lib/data/picks.ts`:** `loadPicks(supabase)` returns `{ run, markets, verdicts }`.
- **`run`:** a `Run`, or null before any published run.
- **`markets`:** a `MarketPicks[]` for US then TSX. Each one has:
  - `market`;
  - `enabled`: the active model's gate;
  - `reason`: a `string` when disabled, or `null` when the market has **no model**;
  - `swing` and `position`: `PickView[]`, ranked;
  - `exitedEarly`: `ExitView[]`, the picks this run told the owner to exit;
  - `graded: { swing, position }`: picks graded live, for the paper banner.
- **`PickView`:**
  - `id, symbol, name, sector, market, style, rank, horizon`;
  - `q10, q50, q90, pBeat` (fractions; null if the prediction row is missing);
  - `exitBy, entry, stop, riskLevel, maxPositionPct`;
  - `topFactors: { feature, contribution, value }[]`;
  - `catalysts: { type, date, exact?, items? }[]`;
  - `cost` (a fraction or null), `benchmark`.
- **`ExitView`:** `id, symbol, style, horizon, exitPrice, ret, reason`. The reason is `'exit_early'` (P fell to 0.42 or below) or `'stop'` (its 3:15 price was at or under its stop).
- **`VerdictView`:** `symbol, assetType, market` (null for coins), `verdict, reasons, details`.
- **Order:** verdicts come US, then TSX, then coins, each by symbol.

**`web/lib/data/ticker.ts`:** `TickerData.forecast` is a `TickerForecast` or `null` (null for coins, or a stock with no forecast and no past picks).
- `benchmark`.
- `horizons: { horizon, q10, q50, q90, pBeat }[]`, ascending. It can be **empty** when the latest run didn't forecast the stock but it has past picks. Then show "No forecast this run" and still show the past picks.
- `advice`: `{ horizon, topFactors, catalysts, cost }` or null.
- `pastPicks: PastPick[]`, newest first. Each has:
  - `id, day, style, horizon, pBeat, exitBy`;
  - `status`: `'open' | 'exited_early' | 'graded'`;
  - `outcome`: `{ ret, benchRet, excess, beat, hitStop, exitReason }` or null.

**`web/components/LineChart.tsx`:** the new `cone?: { q10, q50, q90, label, short? }` prop.
- Quantiles are fractions.
- It draws the cone over the right quarter of the plot and morphs between horizons by itself.
- Pass `label: '+{h} trading days · if {benchmark} is flat'` and `short: '+{h}d'`.

## What to build: one commit per item, with the plan's commit messages

1. **Plan Task 2, `web/lib/advice.ts` + `web/lib/advice.test.ts` only.** The loader is already built. Use the plan's tests verbatim.
2. **Plan Task 3, Today's Picks:**
   - **Navigation order:** Portfolio, **Picks** (icon `Sparkles`), Watchlist, Invest, then Sources and Settings.
   - **The paper banner,** per market and per list, uses the Addendum's wording with `graded`:
     - Swing: "Not yet validated. {n} of 100 Swing picks graded live; treat these as a paper trial." while n < 100.
     - Position: "Validated on backtest only. {n} of 50 Position picks graded live." while n < 50.
     - No banner once validated.
   - **"Exit early" card** in the right column, above the verdicts, porting the mockup's card. One row per `exitedEarly` item: symbol, style, and either "P fell to 0.42 or below" (reason `exit_early`) or "stop hit" (reason `stop`), plus "exited at {price}" (US$ for US) and `ret` as a %. Hide the card when empty.
   - **The e2e seed helpers** (`seedModel`, `seedPrediction`, `seedPick`, `seedVerdict`) go in `web/e2e/db.ts` as the plan describes. Also seed `features_live` advice with the existing `seedFeatures(runId, symbol, 'stock', { advice: { horizon, top_factors, catalysts, round_trip_cost }, ... })`.
   - **Add one e2e test,** `an exited pick shows in the Exit early card`. Seed a pick with `status 'exited_early'` and a `pick_outcomes` row with `graded_at` after the run's `started_at`.
3. **Plan Task 4, "I bought this":** as the plan says.
4. **Plan Task 5, the Watchlist's verdict column:** as the plan says.
5. **Plan Task 6, the UI only:**
   - `web/components/ticker/ForecastCard.tsx` (a client component), and the page wiring in `web/app/(app)/ticker/[symbol]/page.tsx`. It replaces the fixed "appear here once the model runs" banner whenever `forecast` isn't null.
   - The data and the cone already exist.
   - **Past picks table:** Date, Style, Horizon, P(beat), Exit by, and Result:
     - `open` shows "open";
     - `graded` shows `ret` and "vs {benchmark} {excess}", with a ✓ or ✗ for `beat`;
     - `exited_early` shows "exited early" and `ret`.
   - **Add the e2e case** `a graded past pick shows its result`.
6. **Plan Task 7, docs:** the spec §9 and §5.2/§6.5 notes, `deferred.md` and `web/README.md`. The Addendum's items are done in 4b, so don't list them as left for 4c.

## Rules

- **Follow the approved design:** markup, classes and copy pattern from the mockups. Port only the CSS the new markup uses into `web/app/styles/pages.css`.
- **Only published runs, and only usable horizons:** never show P(beat) or a range without a row.
- **Every range says it's relative to the benchmark.**
- **Phone width (390 px):** no horizontal scroll.
- **Before each commit, all of these pass** (from `web/`): `npm test`, `npm run lint`, `npm run typecheck`, `npx playwright test`. Playwright needs the local Supabase stack (`npm run db:start`).
- **Committing:**
  - Run `git commit` in its own command; a hook mistakes any `-n` flag in the same command for `--no-verify`.
  - Never use `--no-verify`.
  - Don't push.
- **No real emails or account numbers** anywhere.

When everything is committed, tell the owner it's ready for review.
