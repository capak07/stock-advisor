# Plan 4b: The Suggestions Dashboard — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The owner can see what the model suggests. The plan adds:
- a **Today's Picks** page: US and TSX tabs, Swing and Position cards, watchlist verdicts, and states for "no picks" and "model check failed";
- an **"I bought this"** button that pre-fills a buy linked to its pick;
- a **verdict column** on the Watchlist;
- a **Forecast card** on each Ticker page: the cone on the price chart, horizon tabs, top factors, catalysts and past picks.

**Architecture:**
- **Pipeline (Task 1):** stage 8 also stores an `advice` entry in `features_live` for every forecast stock. It holds the stock's representative horizon, its top factors at that horizon, its catalysts and its round-trip cost. A Ticker page can then explain any forecast stock, not only today's picks.
- **Web, server side:** pages load the latest published run's data. Loaders live in `web/lib/data/picks.ts`. The pure formatting goes in `web/lib/advice.ts` (factor labels, hold and cost text) and is unit-tested with vitest.
- **Web, components:** components port the approved "Ledger" design: `.superdesign/design_iterations/picks_1.html`, `watchlist_1.html`, `ticker_1.html`, and their CSS in `dashboard_1.css` and the page `<style>` blocks.

**Tech Stack:** Next.js 16 (server components and server actions), Supabase (RLS: the owner reads everything), vitest, Playwright against the local Supabase stack; Python pipeline for Task 1.

**Spec:** `docs/superpowers/specs/2026-10-09-stock-advisor-design.md` §9 (Today's Picks, Ticker Detail, Watchlist rows), §6.5 (what a pick shows), §6.6 (paper period, disabled markets), §7.1 ("I bought this").

**Builds on:**
- **Plan 4a** (merged at `e75a486`), which writes `picks`, `watchlist_verdicts`, `predictions` and `features_live` (the model features, `model_eligible`).
- **The active model's** `metrics.picks_enabled` and `metrics.picks_reason`.

**No prototype.** The approved Ledger mockups are the prototype: they fix the layout, the copy pattern and the states. This plan wires them to real data.

## Addendum (2026-10-27, after Plan 4c merged)

**Plan 4c changed these points; they replace the text below.**
- **Task 1:** `recommend_market` already returns four values (4c added the risk frame), so the advice is a fifth value: `explanations`.
- **Decision 6 (exit early):** Plan 4c marks early exits with `picks.status = 'exited_early'`. Today's Picks shows the "Exit early" card for picks of the run's market that exited early in this run.
- **Decision 7 (past picks):** `pick_outcomes` exists. A past pick shows its status, plus `ret`, `bench_ret`, `excess` and `beat` once graded.
- **The paper banner (§6.6) counts graded picks per market:**
  - Swing shows "Not yet validated. {n} of 100 Swing picks graded live; treat these as a paper trial." while n < 100.
  - Position shows "Validated on backtest only. {n} of 50 Position picks graded live." while n < 50.
- **Navigation:** Invest now exists. Picks goes after Portfolio.

**Execution split, at the owner's request (60% to Cursor):**
- **Claude:**
  - Task 1 (pipeline);
  - Task 2's loader `web/lib/data/picks.ts`, including graded counts, exit-early and past-pick outcomes;
  - Task 6's data (`TickerData.forecast`);
  - the `LineChart` cone.
- **Cursor:** through `docs/superpowers/plans/2026-10-27-plan-4b-cursor-task.md`.
  - Task 2's `web/lib/advice.ts`;
  - Tasks 3, 4 and 5;
  - Task 6's `ForecastCard` and the page wiring;
  - Task 7.
- **Then Claude reviews Cursor's work.**

## Global Constraints

- **The design is approved; follow it.** Port the markup, classes and copy pattern from the mockups. Port only the CSS the new markup uses (`pick`, `pick-*`, `list-head`, `verdict`, `factor`, `range` variants) into `web/app/styles/pages.css`, with `!important` where Tailwind would override it. Don't restyle.
- **Only published runs.** Pages read the latest published run (`lastPublishedRun`). Nothing from an unpublished run is shown.
- **Usable horizons only.** P(beat) and quantiles come from `predictions` rows, which exist only for usable horizons. Never invent a horizon or show P(beat) without a row.
- **Honest labels.** Quantiles are returns relative to the market's benchmark (SPY or XIU.TO), so every range says so ("relative to SPY"). The cone on a price chart shows `close × (1 + q)` and is labelled "if SPY is flat".
- **Money in CAD.** A pick's max size shows `max_position_pct` and, when the portfolio has a value, that share of the portfolio's total CAD value. US stop prices show in USD (`US$`), as the design does.
- **Paper period (§6.6).** Until picks are graded (Plan 4c), each market's picks carry the banner: "Not yet validated. No picks have been graded live yet; treat these as a paper trial."
- **Tests:**
  - **Web:** run `npx vitest run`, `npm run lint` and `npm run typecheck` from `web/`. Playwright runs against the local Supabase stack (`npm run db:start` if it isn't running) with `npx playwright test`.
  - **Pipeline:** `scripts/in-docker.sh uv run pytest -q` and `scripts/in-docker.sh uv run ruff check .`, from `pipeline/`.
- **Commits:** `git commit` in a command of its own (a hook misreads `-n`); never skip hooks; end messages with the `Co-Authored-By:` trailer.
- **Never put a real email address** in code, tests or docs.

## Decisions this plan makes

1. **Ticker explanations for any forecast stock.**
   - Stage 8 stores `features_live.features.advice` for every stock in a market's forecast population:
     - `horizon` (the chosen horizon, else the best-ratio one);
     - `top_factors` (the q50 contributions at that horizon, top 3);
     - `catalysts` (events inside that hold, plus 8-Ks from the last 3 days);
     - `round_trip_cost`.
   - Picks keep their own copies.
2. **Factor wording.** `web/lib/advice.ts` maps each model feature to a label and a formatter, and the value shown comes from the stock's `features_live` row. The arrow and colour follow the contribution's sign: positive raises the forecast (gain colour), negative lowers it (loss colour). The bar width is `|contribution| / max |contribution|` of the stock's three factors, capped at 50%.
3. **Hold text.**
   - 5, 10, 20 and 21 days read "~N trading days".
   - 63 days reads "~3 months" and 126 days "~6 months".
   - The exit date is followed by "exit by Mon D".
4. **Round-trip text.**
   - US: "{cost}% round trip · USD conversion {fee}% each way + spread".
   - TSX: "{cost}% round trip · spread".
   - The cost is the pick's `advice.round_trip_cost`, so it matches the gate.
5. **TFSA note on a card:**
   - Swing: "Adds 1 to your TFSA round-trip count".
   - Position: "A long hold keeps TFSA trades low".
6. **Exit early.** The sidebar's "Exit early" card is left out. It arrives with Plan 4c.
7. **Past picks on the Ticker page.** The last 10 `picks` rows for the symbol across published runs, showing date, style, horizon, P(beat) from that run's prediction, and exit by, with the status "open". Return, benchmark and result columns arrive with grading in Plan 4c.
8. **"I bought this"** opens the existing buy drawer, pre-filled:
   - symbol;
   - account `tfsa`;
   - price: the pick's `entry_ref_price`;
   - the buy saves `lots.pick_id`.

## Review Focus

1. **No published run, or no model yet.** Every page shows its "before the model" state, never an error. Covered by Task 3, `picks page before any run says picks appear once the model runs`, and Task 6, `a ticker without forecasts keeps the empty forecast card`.
2. **A disabled market.** The picks page shows "No {market} picks today" with the stored `picks_reason`, while verdicts still show. Covered by Task 3, `a disabled market shows its gate reason and still lists verdicts`.
3. **A horizon the model can't use.** The Ticker horizon tabs list only horizons with `predictions` rows. Covered by Task 6, `horizon tabs list only the usable horizons`.
4. **A pick's buy pre-fill links the pick.** Covered by Task 4, `I bought this saves a buy linked to the pick`.
5. **A held, watched Buy.** It shows "held" instead of a rank. Covered by Task 5, `a held watched stock's verdict says it is held`.

## Files

| File | Task | What it is |
|---|---|---|
| `pipeline/src/advisor/recommend/stage.py` + `pipeline/tests/integration/test_run.py` | 1 | `advice` in features_live |
| `web/lib/advice.ts` + `web/lib/advice.test.ts`; `web/lib/data/picks.ts` | 2 | Factor labels, hold and cost text; picks loaders |
| `web/app/(app)/picks/page.tsx`, `web/components/picks/*.tsx`, `web/components/shell/nav.ts`, `web/app/styles/pages.css`, `web/e2e/db.ts`, `web/e2e/picks.spec.ts` | 3 | Today's Picks |
| `web/lib/trade-form.ts`, `web/app/(app)/trades.ts`, `web/components/portfolio/TradeForms.tsx`, `web/components/picks/BoughtButton.tsx` + tests | 4 | "I bought this" |
| `web/app/(app)/watchlist/page.tsx`, `web/components/watchlist/Watchlist.tsx`, `web/lib/data/watchlist.ts`, `web/e2e/watchlist-settings.spec.ts` | 5 | Verdict column |
| `web/components/LineChart.tsx`, `web/components/ticker/ForecastCard.tsx`, `web/lib/data/ticker.ts`, `web/app/(app)/ticker/[symbol]/page.tsx`, `web/e2e/ticker.spec.ts` | 6 | Forecast cone, factors, catalysts, past picks |
| spec, `docs/superpowers/deferred.md`, `web/README.md` | 7 | Docs |

---

### Task 1: Store each forecast stock's advice

**Files:**
- Modify: `pipeline/src/advisor/recommend/stage.py`
- Test: `pipeline/tests/integration/test_run.py`

**Interfaces:**
- Consumes:
  - in `recommend_market`: `population`, `horizon` (representative per stock), `in_hold`, `inputs.cost`;
  - `model.active.model.contributions(x, h)`;
  - `recent_filings`;
  - `repo.merge_features_live(conn, run_id, rows, as_of)`.
- Produces: after a market's picks are written, `features_live.features.advice = {"horizon": int, "top_factors": [{"feature", "contribution"}], "catalysts": [...], "round_trip_cost": float}` for every stock in the market's forecast population that has a representative horizon. It is JSON-safe: non-finite contributions are dropped. A failure here is part of the market's picks-stage `try`.

- [ ] **Step 1: Write the failing test**

Append to `pipeline/tests/integration/test_run.py`. Reuse the Plan 4a helpers `confident`, `activate_tsx`, `hold` and `tsx_model_files`:

```python
def test_every_forecast_stock_gets_advice_for_its_ticker_page(db, tmp_path, tsx_model_files, monkeypatch):
    activate_tsx(db, tsx_model_files)
    db.execute("update models set metrics = metrics || '{\"picks_enabled\": true}'::jsonb")
    hold(db, "RY.TO")  # held: never a pick, but still forecast
    monkeypatch.setattr("advisor.run.predict_rows", confident)
    outcome = execute_run(make_deps(db, tmp_path), RunKind.PRE_OPEN, NOW, min_universe=SMALL)
    rows = {r["symbol"]: r["features"] for r in db.execute(
        "select symbol, features from features_live where run_id = %s and asset_type = 'stock'", (outcome.run_id,)).fetchall()}
    for symbol in ("RY.TO", "TD.TO"):
        advice = rows[symbol]["advice"]
        assert advice["horizon"] == 63
        assert len(advice["top_factors"]) == 3 and all("feature" in f for f in advice["top_factors"])
        assert advice["round_trip_cost"] == pytest.approx(0.003)  # TSX spread: the fakes trade $2M a day, under $10M
        assert isinstance(advice["catalysts"], list)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `scripts/in-docker.sh uv run pytest -q tests/integration/test_run.py -k advice`
Expected: FAIL with `KeyError: 'advice'`.

- [ ] **Step 3: Implement**

In `recommend_market`, compute the contributions per representative horizon for every population stock with one, not only for the chosen stocks; the picks keep using these. Build each stock's advice, and return it as a fourth value. `recommend_stage` merges the advice rows with `repo.merge_features_live` inside the same per-market transaction as the picks. A disabled market still stores advice.

- [ ] **Step 4: Run the tests to verify they pass, with a mutation check**

Run: `scripts/in-docker.sh uv run pytest -q && scripts/in-docker.sh uv run ruff check .`
Expected: all pass, ruff clean.

Then temporarily store advice only for picked stocks, confirm the test fails (RY.TO is held), and restore.

- [ ] **Step 5: Commit**

```bash
git add pipeline/src/advisor/recommend/stage.py pipeline/tests/integration/test_run.py
```
```bash
git commit -m "feat: store each forecast stock's factors, catalysts and cost for its ticker page"
```

---

### Task 2: Advice text and the picks loaders

**Files:**
- Create: `web/lib/advice.ts`, `web/lib/advice.test.ts`, `web/lib/data/picks.ts`

**Interfaces:**
- Produces, in `web/lib/advice.ts`:
  - `type Formatter = 'pct' | 'signedPct' | 'number' | 'ratio' | 'percentile' | 'dollars' | 'flag'`;
  - `FACTORS: Record<string, { label: string; format: Formatter }>`, with one entry for every model feature:
    - price: `ret_5, ret_21, ret_63, ret_126, mom_12_1, rsi_14, atr_14_pct, vol_20, vol_60, dist_52w_high, dist_52w_low, volume_z, gap, jump_5d, log_adv20`;
    - relative strength: `ex_bench_21, ex_bench_63, ex_sector_21, ex_sector_63, sector_rank_63`;
    - fundamentals: `rev_growth, gross_margin, op_margin, gross_margin_trend, op_margin_trend, eps_growth, earnings_yield, sales_yield, fcf_yield, debt_to_equity, log_mcap`;
  - `describeFactor(feature: string, value: number | undefined, benchmark: string) -> string`. `ex_bench_*` labels name the benchmark. A value that is `undefined` gives the label alone. An unknown feature gives the feature name.
  - `factorBars(factors: {feature: string; contribution: number}[]) -> {feature: string; up: boolean; width: number}[]`, with width in percent, at most 50 (decision 2);
  - `holdText(horizon: number, exitBy: string) -> string` (decision 3);
  - `costText(market: 'US' | 'TSX', cost: number, usdFxFeePct: number) -> string` (decision 4);
  - `tfsaNote(style: 'swing' | 'position') -> string` (decision 5).
- Produces, in `web/lib/data/picks.ts` (server-only):
  - `interface PickView`, with:
    - `id, symbol, name, sector, market, style, rank, horizon`;
    - `q10, q50, q90, pBeat` (from `predictions`);
    - `exitBy, entry, stop, riskLevel, maxPositionPct`;
    - `topFactors: {feature, contribution, value}[]` (values from `features_live`);
    - `catalysts`, `cost` (the stock's `advice.round_trip_cost`);
    - `benchmark`.
  - `interface MarketPicks`, with `market`, `enabled: boolean`, `reason: string | null`, `swing: PickView[]`, `position: PickView[]`.
  - `interface VerdictView`, with `symbol, assetType, market: 'US' | 'TSX' | null, verdict: 'buy' | 'hold' | 'avoid', reasons: string[], details: Record<string, unknown>`.
  - `loadPicks(supabase) -> Promise<{ run: Run | null; markets: MarketPicks[]; verdicts: VerdictView[] }>`. It reads the latest published run, with each market's active model gate (`models` where `active`, `kind` `stock_us` / `stock_tsx`). A market with no model gets `enabled: false` and `reason: null`.

- [ ] **Step 1: Write the failing tests**

`web/lib/advice.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { costText, describeFactor, factorBars, FACTORS, holdText, tfsaNote } from './advice'

describe('advice text', () => {
  it('labels every model feature', () => {
    const features = ['ret_5', 'ret_21', 'ret_63', 'ret_126', 'mom_12_1', 'rsi_14', 'atr_14_pct', 'vol_20', 'vol_60',
      'dist_52w_high', 'dist_52w_low', 'volume_z', 'gap', 'jump_5d', 'log_adv20', 'ex_bench_21', 'ex_bench_63',
      'ex_sector_21', 'ex_sector_63', 'sector_rank_63', 'rev_growth', 'gross_margin', 'op_margin', 'gross_margin_trend',
      'op_margin_trend', 'eps_growth', 'earnings_yield', 'sales_yield', 'fcf_yield', 'debt_to_equity', 'log_mcap']
    expect(features.filter((f) => !(f in FACTORS))).toEqual([])
  })

  it('describes a factor with its value and the benchmark', () => {
    expect(describeFactor('ex_bench_63', 0.098, 'SPY')).toBe('Return vs SPY over 63 days +9.8%')
    expect(describeFactor('rev_growth', 0.31, 'SPY')).toBe('Revenue growth, year over year +31.0%')
    expect(describeFactor('sector_rank_63', 0.88, 'SPY')).toBe("Sector's 63-day rank 88th percentile")
    expect(describeFactor('ret_21', undefined, 'SPY')).toBe('Return over 21 days')
    expect(describeFactor('mystery', 1, 'SPY')).toBe('mystery')
  })

  it('sizes factor bars by contribution, at most half the bar', () => {
    expect(factorBars([{ feature: 'a', contribution: 0.02 }, { feature: 'b', contribution: -0.01 }])).toEqual([
      { feature: 'a', up: true, width: 50 }, { feature: 'b', up: false, width: 25 },
    ])
  })

  it('says how long to hold and what it costs', () => {
    expect(holdText(10, '2026-10-30')).toBe('~10 trading days · exit by Oct 30')
    expect(holdText(63, '2027-01-19')).toBe('~3 months · exit by Jan 19')
    expect(holdText(126, '2027-04-26')).toBe('~6 months · exit by Apr 26')
    expect(costText('US', 0.031, 1.5)).toBe('3.1% round trip · USD conversion 1.5% each way + spread')
    expect(costText('TSX', 0.001, 1.5)).toBe('0.1% round trip · spread')
    expect(tfsaNote('swing')).toBe('Adds 1 to your TFSA round-trip count')
    expect(tfsaNote('position')).toBe('A long hold keeps TFSA trades low')
  })
})
```

- [ ] **Step 2: Run them to verify they fail**

Run (from `web/`): `npx vitest run lib/advice.test.ts`
Expected: FAIL, because `./advice` doesn't exist.

- [ ] **Step 3: Implement** `advice.ts` (interfaces above) and `data/picks.ts`

`loadPicks` makes a few queries, not one per pick:
- picks of the run;
- the run's `predictions`, matched on (symbol, horizon);
- the run's `features_live` for those symbols;
- `symbols` for names and sectors;
- the run's `watchlist_verdicts`;
- the active `models` rows.

Order: picks by market, style (swing first), then rank. Verdicts by market (US, TSX, coins) then symbol. `loadPicks` is exercised through the pages' Playwright tests in Tasks 3 and 5.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npx vitest run && npm run lint && npm run typecheck`
Expected: all pass, clean.

- [ ] **Step 5: Commit**

```bash
git add web/lib/advice.ts web/lib/advice.test.ts web/lib/data/picks.ts
```
```bash
git commit -m "feat: words for factors, holds and costs, and the picks loaders"
```

---

### Task 3: Today's Picks

**Files:**
- Create:
  - `web/app/(app)/picks/page.tsx`;
  - `web/components/picks/PickCard.tsx`, `RangeBar.tsx`, `VerdictList.tsx`, `MarketPicks.tsx`;
  - `web/e2e/picks.spec.ts`.
- Modify:
  - `web/components/shell/nav.ts`: add `{ href: '/picks', label: 'Picks', icon: Sparkles, primary: true }` after Portfolio;
  - `web/app/styles/pages.css`;
  - `web/e2e/db.ts`: add seed helpers.

**Interfaces:**
- Consumes: Task 2's `loadPicks` and `advice` helpers; `ownerClient`, `loadSettings`, and the portfolio total (`portfolioView(...).totals` from `lib/portfolio/view.ts`, as the Portfolio page computes it) for "Max size C$…".
- Produces, in `web/e2e/db.ts`:
  - `seedModel(kind: 'stock_us' | 'stock_tsx', metrics: JSONValue)`, which inserts an active `models` row;
  - `seedPrediction(runId, symbol, horizon, q: {q10, q50, q90, p})`, with the benchmark derived from the symbol (`.TO` gives XIU.TO);
  - `seedPick(runId, pick: {symbol, market, style, horizon, rank, exitBy, entry, stop, riskLevel, maxPct, topFactors?, catalysts?}) -> number` (the pick id);
  - `seedVerdict(runId, v: {symbol, assetType, verdict, reasons, details?})`.

**Page structure** (from `picks_1.html`):
- The heading "Today's Picks", with the sub-line "From the {time} {run kind} run · at most 10 Swing and 10 Position picks per market, 3 per sector".
- US and TSX tabs, using the existing `Tabs` component.
- Per market:
  - the paper banner;
  - the Swing and Position lists, with `list-head` counts;
  - `PickCard`s;
  - or the empty or failed card.
- A right column with the "Watchlist verdicts" card. Each row shows the symbol, the market or "Crypto", a chip, and a short why.
  - For a Buy: "{Style} · ~N days · exit by … · P%".
  - Otherwise: the first reason.

**States:**
- **No published run:** an empty card, "Picks appear once the model runs."
- **Market disabled with a reason:** "No {market} picks today: model check failed" with the reason, plus "Watchlist verdicts and holding actions still run."
- **Market without a model:** "No {market} picks yet", with "{market} has no trained model yet."
- **Enabled with zero picks:** "No {market} picks today", with "Nothing cleared the bar this run: P(beat) at least 58% and an expected return above costs."

- [ ] **Step 1: Write the failing Playwright tests**

`web/e2e/picks.spec.ts`. Follow `ticker.spec.ts` for login and seeding. Use `resetData` and `seedPortfolio` (so there is a portfolio value), then seed a published run, a US model with `picks_enabled: true`, predictions and picks for AAPL, and a TSX model with `picks_enabled: false` and `picks_reason: "only 12 backtest picks (needs 30)"`. Tests:
- `picks page before any run says picks appear once the model runs`: no runs, and the page shows "Picks appear once the model runs".
- `a US pick card shows its range, odds, hold, stop, size and cost`. The AAPL card shows:
  - "#1" and "Beats SPY" with "62%";
  - "~3 months · exit by";
  - "US$" with the stop;
  - "Max size", the "%" and "C$";
  - "round trip";
  - three factor lines;
  - the paper banner text.
- `a disabled market shows its gate reason and still lists verdicts`: on the TSX tab, "No TSX picks today", "only 12 backtest picks (needs 30)" and the TD.TO verdict row "Hold".
- `the nav links to Picks`: on desktop and in the phone tabs.

- [ ] **Step 2: Run them to verify they fail**

Run (from `web/`): `npx playwright test e2e/picks.spec.ts`
Expected: FAIL, because `/picks` is a 404.

- [ ] **Step 3: Implement** the page, the components, the nav entry and the ported CSS

`RangeBar` draws the design's `range wide` bar from q10, q50 and q90, with a span of at least 10 points and wide enough for the card's own range. Pick-card factor lines use `describeFactor` with the up or down icon from `factorBars`. Catalyst lines read, for example:
- "Earnings Oct 28, inside the hold";
- "Phase 2/3 trial completion Nov 3, inside the hold";
- "8-K Oct 15";
- or "No catalysts inside the hold".

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npx playwright test e2e/picks.spec.ts && npx vitest run && npm run lint && npm run typecheck`
Expected: all pass, clean.

Then mutation-check: show picks for a disabled market, and drop the paper banner. Confirm a test fails each time, then restore.

- [ ] **Step 5: Commit**

```bash
git add web/app web/components web/e2e
```
```bash
git commit -m "feat: Today's Picks with pick cards, watchlist verdicts and honest empty states"
```

---

### Task 4: "I bought this"

**Files:**
- Modify: `web/lib/trade-form.ts` (`parseBuy` reads an optional `pick_id`), `web/app/(app)/trades.ts` (writes `lots.pick_id`), `web/components/portfolio/TradeForms.tsx` (the buy form accepts initial values and a hidden `pick_id`)
- Create: `web/components/picks/BoughtButton.tsx`
- Test: `web/lib/forms.test.ts`, `web/e2e/picks.spec.ts`

**Interfaces:**
- `BuyInput` gains `pickId: number | null`. `parseBuy` reads `form.pick_id`: a positive integer, else `null`. A malformed value is `null`, never an error.
- Buy form `initial?: { symbol: string; account: Account; price: string; pickId: number }`.
- `BoughtButton({ pick }: { pick: PickView })` opens the buy drawer with `initial`.

- [ ] **Step 1: Write the failing tests**

In `web/lib/forms.test.ts`, test that `parseBuy` passes `pick_id` "42" through as `42`, and that it gives `null` for "", "abc" and "-3".

In `web/e2e/picks.spec.ts`, add `I bought this saves a buy linked to the pick`:
1. Click "I bought this" on the AAPL card.
2. Check the drawer shows symbol AAPL, account TFSA, and price equal to the pick's entry.
3. Enter a quantity and save.
4. Check the database: `select pick_id from lots where symbol = 'AAPL' order by id desc limit 1` equals the seeded pick's id.

- [ ] **Step 2: Run them to verify they fail**

Run: `npx vitest run lib/forms.test.ts && npx playwright test e2e/picks.spec.ts -g "I bought this"`
Expected: FAIL.

- [ ] **Step 3: Implement** (interfaces above). The insert includes `pick_id`. The RLS owner policy on `lots` already allows the column.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npx vitest run && npx playwright test e2e/picks.spec.ts e2e/trades.spec.ts && npm run lint && npm run typecheck`
Expected: all pass. The existing trade tests are unaffected.

- [ ] **Step 5: Commit**

```bash
git add web/lib web/app web/components web/e2e
```
```bash
git commit -m "feat: I bought this pre-fills a buy linked to its pick"
```

---

### Task 5: The Watchlist's verdict column

**Files:**
- Modify: `web/app/(app)/watchlist/page.tsx`, `web/components/watchlist/Watchlist.tsx`, `web/lib/data/watchlist.ts` (verdicts of the latest published run)
- Test: `web/e2e/watchlist-settings.spec.ts`

**Interfaces:**
- `WatchRow` gains `verdict: 'buy' | 'hold' | 'avoid' | null` and `why: string | null`.
- The why text, from `watchlist_1.html`:
  - **Buy:** "{Style} · hold {holdText} · {P}% to beat {benchmark}". It ends with " · also today's #{rank} {market} pick" when `details.rank` exists, or " · you hold it" when `details.held`.
  - **Hold or Avoid:** the first reason, plus " · picks off for {market} this run" when `details.market_picks_enabled` is false.

The column heading "Verdict" and the sub "verdicts from the {time} run" appear only when the run has verdicts. Otherwise the existing "Verdicts appear once the model runs" banner stays.

- [ ] **Step 1: Write the failing tests**

In `watchlist-settings.spec.ts`:
- `watchlist rows show each verdict and why`: seed a run with a Buy for AAPL (details with style, horizon, exit_by, rank 2) and an Avoid for TD.TO. Check:
  - the "Buy" chip and "also today's #2 US pick";
  - the "Avoid" chip with its reason;
  - the "verdicts from" sub-line.
- `a held watched stock's verdict says it is held`: a Buy with `details.held = true` shows "you hold it".

- [ ] **Step 2: Run them to verify they fail**

Run: `npx playwright test e2e/watchlist-settings.spec.ts`
Expected: FAIL, because there is no verdict column.

- [ ] **Step 3: Implement** (interfaces above), porting the design's `w-verdict` and `w-detail` cells and their phone layout

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npx playwright test e2e/watchlist-settings.spec.ts && npx vitest run && npm run lint && npm run typecheck`
Expected: all pass. The existing watchlist tests keep passing.

- [ ] **Step 5: Commit**

```bash
git add web/app web/components web/lib web/e2e
```
```bash
git commit -m "feat: watchlist verdicts with the reason for each"
```

---

### Task 6: The Ticker page's forecast

**Files:**
- Modify:
  - `web/components/LineChart.tsx`: an optional `cone?: { q10: number; q50: number; q90: number; label: string }`, ported from `dashboard_1.js` `lineChart`'s cone (the history takes 76% of the width, the polygon fill is `var(--chart-5)`, the median line is `var(--chart-4)`);
  - `web/lib/data/ticker.ts`: `TickerData` gains `forecast`;
  - `web/app/(app)/ticker/[symbol]/page.tsx`: replaces the empty Forecast card.
- Create: `web/components/ticker/ForecastCard.tsx`
- Test: `web/e2e/ticker.spec.ts`, plus a vitest test of any pure cone helper you extract

**Interfaces:**
- `TickerData.forecast` is either `null` or:
  - `benchmark: string`;
  - `horizons: { horizon, q10, q50, q90, pBeat }[]` from the latest published run's `predictions`, ascending;
  - `advice: { horizon, topFactors: {feature, contribution, value}[], catalysts, cost } | null`;
  - `pastPicks: { day, style, horizon, pBeat, exitBy }[]`, the last 10 across published runs.

**Rendering (from `ticker_1.html`):**
- Horizon tabs show only `horizons`, and the default tab is `advice.horizon`.
- The price chart gains the cone for the selected tab: `close × (1 + q)`, labelled "+{h} trading days · if {benchmark} is flat".
- KPIs: P(beat), the median, and the likely range.
- The "Top factors" card uses `describeFactor` and `factorBars`.
- The "Catalysts" card, or "No catalysts inside the hold".
- The "Past picks" table (decision 7).

For a coin, or a stock without forecasts, the existing empty Forecast card stays.

- [ ] **Step 1: Write the failing tests**

In `ticker.spec.ts`:
- `a forecast stock shows its cone, odds, factors and catalysts`: seed predictions for RY.TO at 21 and 63, and `features_live` advice with horizon 63, 3 factors and an earnings catalyst. Check:
  - tabs "21d" and "63d" only, with 63d selected;
  - the cone polygon is present in the chart;
  - "Beats XIU.TO" shows the 63-day probability;
  - three factor rows;
  - the catalyst line.
- `horizon tabs list only the usable horizons`: only the predictions' horizons appear.
- `a ticker without forecasts keeps the empty forecast card`: the existing message stays.
- `past picks list the stock's earlier picks`: seed one pick in an earlier published run, and its row shows the date, style and "open".

- [ ] **Step 2: Run them to verify they fail**

Run: `npx playwright test e2e/ticker.spec.ts`
Expected: FAIL.

- [ ] **Step 3: Implement** (interfaces above)

The cone redraws when the tab changes; it is a client component. The chart's accessible label names the cone.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npx playwright test e2e/ticker.spec.ts && npx vitest run && npm run lint && npm run typecheck`
Expected: all pass.

Mutation-check: show all six horizons regardless of the rows. Confirm a test fails, then restore.

- [ ] **Step 5: Commit**

```bash
git add web/components web/lib web/app web/e2e
```
```bash
git commit -m "feat: the ticker page's forecast cone, factors, catalysts and past picks"
```

---

### Task 7: Docs

**Files:**
- Modify: `docs/superpowers/specs/2026-10-09-stock-advisor-design.md`, `docs/superpowers/deferred.md`, `web/README.md`

- [ ] **Step 1: Spec**

- **Revision history:** add a 2026-10-27 Plan 4b line.
- **§9:** Today's Picks, Ticker Detail and Watchlist as built. Record:
  - the range is relative to the benchmark, and the cone reads "if {benchmark} is flat";
  - factor wording;
  - the paper banner.
- **§5.2 / §6.5:** every forecast stock's `advice` in `features_live`.

- [ ] **Step 2: deferred.md**

Move what's done out of "Plan 4" and "Plans 4 and 5". Keep for Plan 4c:
- the Exit early card;
- graded columns in Past picks;
- the Track Record page;
- live-graded counts in the paper banner.

- [ ] **Step 3: README**

Add the Picks page to the pages list.

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-10-09-stock-advisor-design.md docs/superpowers/deferred.md web/README.md
```
```bash
git commit -m "docs: record Plan 4b's suggestions dashboard"
```
