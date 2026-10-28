# Cursor task: the Invest page UI

**Paste this file into Cursor's agent** (or open it there and say "do this task"). The work goes on branch `invest-page`, which already holds the design, the engine and the data loader.

## Read first

1. `docs/superpowers/specs/2026-10-27-invest-page-design.md`: what the page is and why. Its "Layout" section is the target.
2. `web/AGENTS.md`: this Next.js version differs from what you know, so read `web/node_modules/next/dist/docs/` before using any Next API you're unsure of. Copy patterns from the existing pages rather than from memory.
3. `web/app/(app)/watchlist/page.tsx` and `web/app/(app)/page.tsx`: how a page in this app is built (server component, `ownerClient()`, cards, `section-head`, `.sub`, `enter`/`stagger` classes).

## Already built (don't change these files)

- **`web/lib/invest/allocate.ts`:** `allocate(input: InvestInput): Allocation`.
  - `Allocation` holds:
    - `stocks: StockLine[]`;
    - `crypto { symbol: 'BTC', amount, priceCad, units }`;
    - `uninvested`, `notValidated`, `evenSplit`.
  - A `StockLine` holds:
    - `symbol`, `name`, `market`, `sector`;
    - `amount`: whole C$;
    - `shares`: a number or null;
    - `horizonDays`;
    - `q10`, `q50`, `q90`: fractions of excess return vs `benchmark`;
    - `pBeat`, `benchmark`, `qualifies`;
    - `cost`: a fraction;
    - `vol60`: an annual fraction;
    - `volatility`: `'low' | 'medium' | 'high' | 'very high'` or null.
- **`web/lib/data/invest.ts`:** `loadInvestData(supabase): Promise<InvestData | null>`. It returns `{ run, candidates, held, usdFxFeePct, btcPriceCad }`, or null before any run has forecasts.
- Build the `InvestInput` as `{ amount, cryptoPct, usdFxFeePct, candidates, held, btcPriceCad }` from the loader's result and the URL.

## What to build

1. **Navigation:** in `web/components/shell/nav.ts`, add `{ href: '/invest', label: 'Invest', icon: PiggyBank, primary: true }` (from `lucide-react`) after Watchlist.
2. **The page, `web/app/(app)/invest/page.tsx`**, a server component:
   - Read `searchParams.amount` and `searchParams.crypto`. Validate them:
     - amount: a number from 1 to 10,000,000, allowing commas and a `$`;
     - crypto: 0 to 100, default 10.
   - With no amount, show only the form.
   - A bad value shows the form with a field error. It never throws.
   - The form is a plain `<form method="get">` with the two inputs and a "Split it" button, using the existing field classes (`field`, `input`, `hint`, `error`).
   - Set `export const metadata = { title: 'Invest' }`.
3. **Under the form** (match the design's Layout section, using existing classes):
   - **A sub line:** "From the {KIND_LABEL} run of {shortDay(run.et_date)} · returns are vs SPY (US) or XIU.TO (TSX), not plain gains". `KIND_LABEL` is in `web/lib/runs.ts`.
   - **When `notValidated`,** a `banner warn` with this exact text: "Not validated: none of these meets the picks' bar today (picks are off). They're the model's best-ranked, not recommendations." If some lines qualify and others don't, show the same banner, and mark each line that passes with a small "passes the bar" chip.
   - **When `evenSplit`,** a line under the list: "Too few stocks for the 40% cap, so the money is split evenly."
   - **One row per stock**, in a card or table like the holdings table. Show:
     - `fmtMoney(amount)` with "≈ {shares to 2 decimals} sh" when shares is not null;
     - the symbol, linked to `/ticker/{symbol}`, with its name, market and sector;
     - the expected return: "{fmtPct(q50 × 100)} (likely {fmtPct(q10 × 100)} to {fmtPct(q90 × 100)}) over {horizonDays} trading days vs {benchmark}";
     - "P(beat) {round(pBeat × 100)}%";
     - "Volatility {volatility} ({round(vol60 × 100)}%/yr)";
     - "exit by ≈ {date}", where the date is `horizonDays` weekdays after `run.et_date`, shown with `shortDay`;
     - "round-trip cost {fmtPct(cost × 100)}", adding "(incl. currency fee)" for US.
   - **The BTC row:**
     - "C$ {amount} · BTC · Bitcoin · crypto · no forecast (no crypto model yet)";
     - with "≈ {units to 6 decimals} BTC" when units is not null;
     - otherwise the hint "add BTC to your watchlist to see its price".
     - Hide the row when the crypto amount is 0.
   - **When `uninvested` > 0:** "C$ {uninvested} not invested: no stock is expected to beat its benchmark today."
   - **The footer:** "Total C$ {amount}" and the disclaimer "Not financial or tax advice. Forecasts are probabilistic and can be wrong."
   - **With `loadInvestData` null:** "No forecasts yet. They appear after the next run."
4. **Layout:**
   - It must look right at phone width (390 px): rows stack, with no horizontal scroll.
   - Use the existing `enter` and `stagger` classes for motion.
   - Add no new CSS files. If a style is truly missing, add a few rules to `web/app/styles/pages.css` following its patterns.

## Tests

**Playwright, `web/e2e/invest.spec.ts`,** in the style of `web/e2e/portfolio.spec.ts`. Use `resetData`, `seedRun` and `sql` from `web/e2e/db.ts`, and `seedSymbols` for names and sectors. Seed one published run, then insert directly:
- **`predictions`:** `(run_id, symbol, asset_type 'stock', horizon_days, q10, q50, q90, p_beat, benchmark, model_version)` for 6 stocks:
  - 2 qualifying, e.g. TSX with `p_beat` 0.62 and `q50` 0.03;
  - 3 not qualifying but with a positive `q50`;
  - 1 negative at every horizon.
- **`features_live`:** `(run_id, symbol, asset_type, features jsonb, as_of)` with `{"vol_60": 0.3, "log_adv20": 17, "jump_5d": 0}` per stock.

Assert that:
1. The nav shows Invest, and `/invest` shows the form.
2. `/invest?amount=1000&crypto=10` shows 5 stock rows. The negative stock isn't among them. The banner is visible. A BTC row of C$100 shows the watchlist hint. The amounts on the page add up to C$1,000.
3. `/invest?amount=abc` shows a field error.
4. With no runs, the page shows "No forecasts yet".

## Done means

From `web/`, all of these pass: `npm test`, `npm run lint`, `npm run typecheck` and `npx playwright test`. Playwright needs the local Supabase stack: `npm run db:start`.

**Commit** on branch `invest-page`:
- Use the message `feat: the Invest page`.
- Don't push.
- Never use `--no-verify`.
- Run `git commit` in its own command; a hook mistakes any `-n` flag in the same command for `--no-verify`.

Then tell the owner it's ready for review.
