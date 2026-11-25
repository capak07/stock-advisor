# Cursor task: Runners paper trades in dollars

**Goal:** the owner wants to see each Runners paper trade as plain money, not just R: "bought 100 shares at US$0.8500 = US$85.00, now US$0.9300, worth US$93.00". Every trade is 100 shares, a fixed paper size for reading. The R figures, the Track record and the paper gate stay exactly as they are.

**Branch:** `runners-paper-dollars` (already created from `main`; this file is its first commit). Web only: **don't touch** `pipeline/` or `supabase/`.

## Rules

- **Test-first:** write the tests below, see them fail, implement, then see them pass. Never weaken an assertion. If one looks wrong, stop and say why.
- **Exact strings:** use the strings below character for character. That includes `·` (middle dot), `−` (the real minus sign, which `fmtMoney` and `fmtPct` already produce) and `=`.
- **One line, one string:** build each line as a single template string, as `RunnerCard` already does, so a test can match the whole line.
- **From `web/`, before committing:**
  - `npx vitest run`, `npx tsc --noEmit` and `npx eslint lib components app e2e` pass.
  - With the local database up (`npm run db:start`), `npx playwright test e2e/runners.spec.ts` passes.
- **Committing:**
  - one commit: `feat(runners): show each paper trade as 100 shares in US$`;
  - `git commit` in its own command, never with `--no-verify`;
  - no `Co-Authored-By` line;
  - don't push, and don't merge.
- **When done,** reply with:
  - the commit hash;
  - the test counts;
  - anything you decided that this file didn't say.

## 1. Helpers in `web/lib/runners.ts`

```ts
/** Every paper trade is this many shares: simple to read. The R figures are what the gate judges. */
export const PAPER_SHARES = 100

export interface PaperValue { cost: number; value: number; gain: number; gainPct: number }

/** PAPER_SHARES bought at `entry` and valued at `price`, in US$ rounded to the cent; null unless both prices are there. */
export function paperValue(entry: number | null, price: number | null): PaperValue | null

export interface PaperTotal {
  trades: number; cost: number; value: number; gain: number; gainPct: number
  spread: number; gainAfterSpread: number
}

/** The finished paper trades in `rows` (status target, stop or held, with an entry and an exit price), PAPER_SHARES each. */
export function paperTotal(rows: readonly Runner[]): PaperTotal
```

- **One trade:**
  - `cost` = entry × 100 and `value` = price × 100, each rounded to the cent;
  - `gain` = value − cost, rounded to the cent;
  - `gainPct` = gain / cost × 100, not rounded.
- **Spread for one trade:** `spreadPct × entry`, rounded to the cent. `spreadPct` is a percent of the price per share, so this is the round trip for 100 shares.
- **Total:**
  - sums of the rounded per-trade figures;
  - `gainPct` = gain / cost × 100, or 0 when cost is 0;
  - `gainAfterSpread` = gain − spread.

## 2. Today's signal card (`components/runners/RunnerCard.tsx`)

Add a last `<li>` to the existing `ul.dt-lines`, after the spread line:

`Paper trade: 100 shares at the open (about US$136.00 at the signal close)`

The amount is `fmtMoney(signalClose × 100 rounded to the cent, { prefix: 'US$', digits: 2 })`.

## 3. Open runners as cards (new `components/runners/OpenRunnerCard.tsx`)

In `app/(app)/runners/page.tsx`:

- **Replace the Open runners table** with one `OpenRunnerCard` per open runner.
- **Use the same structure as Today's signals:**
  - `<section className="dt-stack enter" aria-labelledby="rn-open-h">`;
  - its `section-head`: `<h2 id="rn-open-h">Open runners</h2>` and the label `as of the last close`;
  - then `<div className="dt-cards">`.
- **Empty:** keep `No open runners.` as a `banner info`, like Today's empty state.
- Remove whatever the page no longer uses.

**The card:** `<article className="card pick dt-card" data-testid="open-runner-card" aria-label="{symbol} open runner">`, holding, in order:

1. **Header:** the same `dt-who-t` as `RunnerCard`, with the symbol link and the name, without the paper chip.
2. **`<p className="dt-line">`:** `Bought 100 shares at {price(entry)} on {shortDay(entryDay)} = {money(cost)}`. Drop ` on {day}` when `entryDay` is null.
3. **`<p className="dt-line">`:** `Now {price(lastClose)} ({shortDay(lastDay)} close) · worth {money(value)} · `, then `<span className="num {gain|loss}" data-testid="open-runner-gain">{signed(gain)} ({fmtPct(gainPct)})</span>`.
   - The tone is `rTone(gain)`.
   - If `lastClose` or `lastDay` is null, the whole line is `No close yet.`
4. **`<ul className="dt-lines">`** with two items:
   - `Stop {price(stop)} · target {price(target)} · hold by {shortDay(holdBy)}`;
   - `R so far `, then `<span className="num {tone}" data-testid="open-runner-r">{fmtR(rSoFar(r))}</span>`. Show `—` when `rSoFar` is null.

**Formats:**
- `price(x)` = `priceOf(x, 'US')`. Under US$1 it shows 4 significant figures (`US$0.8500`), otherwise 2 decimals.
- `money(x)` = `fmtMoney(x, { prefix: 'US$', digits: 2 })`.
- `signed(x)` = `fmtMoney(x, { prefix: 'US$', digits: 2, signed: true })`.

## 4. Finished paper trades (new `components/runners/FinishedRunners.tsx`)

`FinishedRunners({ closed, version }: { closed: readonly Runner[]; version: number })` goes on the page right after Open runners and before the Track record / Backtest pair.

**Which trades:**
- `closed` rows with `ruleVersion === version`, status `target`, `stop` or `held`, and both an `entry` and an `exitPrice`;
- in the loader's order, which is newest first.

**The section:** `<section className="card card-pad enter" aria-labelledby="rn-finished-h">`.
- **Head:** `section-head` with `<h2 id="rn-finished-h">Finished paper trades</h2>` and the label `100 shares each`.
- **No trades:** `<p className="sub">No finished paper trades yet.</p>`.
- **Otherwise:**
  - **Total:** `<p className="dt-line" data-testid="runners-paper-total">`, using `paperTotal` over all of those trades:

    `{n} finished {trade|trades}: put in {money(cost)}, got back {money(value)}, {signed(gain)} ({fmtPct(gainPct)}). After the estimated spread: {signed(gainAfterSpread)}.`
  - **List:** a `<ul className="dt-lines">` of the first 20 trades. Each `<li>` is the symbol link (`className="sym"`, `tickerHref(symbol, 'stock')`), then:

    ` · bought at {price(entry)} = {money(cost)} · sold at {price(exitPrice)} = {money(value)} ({how}, {shortDay(exitDay)}) · {signed(gain)} ({fmtPct(gainPct)})`
    - `how` is `target`, `stop` or `time up` (for `held`).
    - Drop `, {day}` when `exitDay` is null.

## 5. Tests

**`lib/runners.test.ts`:**
- `paperValue(0.85, 0.93)`: cost 85, value 93, gain 8, gainPct close to 9.41.
- `paperValue(1.92, 2.4)`: 192, 240, 48, 25.
- `paperValue(null, 2)` and `paperValue(1, null)` are null.
- `paperTotal` over these rows:
  - target: entry 2, exitPrice 3, spreadPct 2;
  - stop: entry 1.5, exitPrice 1.2, spreadPct 2;
  - one skipped row with entry null;
  - one open row.
  
  The result is `{ trades: 2, cost: 350, value: 420, gain: 70, gainPct: 20, spread: 7, gainAfterSpread: 63 }`.

**`components/runners/RunnerCard.test.tsx`:** the default fixture contains `Paper trade: 100 shares at the open (about US$136.00 at the signal close)`.

**New `components/runners/OpenRunnerCard.test.tsx`** (the same `runner()` fixture pattern as `RunnerCard.test.tsx`):
- **Gain case:** status `open`, entryDay `2026-11-17`, entry 0.85, lastDay `2026-11-18`, lastClose 0.93, stop 0.65, target 1.25, holdBy `2026-11-28`. The output contains:
  - `Bought 100 shares at US$0.8500 on Nov 17 = US$85.00`
  - `Now US$0.9300 (Nov 18 close) · worth US$93.00 · `
  - `+US$8.00 (+9.4%)`, in an element with class `gain`
  - `Stop US$0.6500 · target US$1.25 · hold by Nov 28`
  - `+0.40R`
- **Loss case:** lastClose 0.80 gives `−US$5.00 (−5.9%)` with class `loss`.
- **No close yet:** lastClose null gives `No close yet.`

**New `components/runners/FinishedRunners.test.tsx`** (version 1):
- **Two trades:**
  - MULN: target, entry 2, exitPrice 3, exitDay `2026-11-24`, spreadPct 2;
  - SNDL: stop, entry 1.5, exitPrice 1.2, exitDay `2026-11-24`, spreadPct 2;
  - plus one version-0 trade, which must be left out.
  
  The output contains:
  - `2 finished trades: put in US$350.00, got back US$420.00, +US$70.00 (+20.0%). After the estimated spread: +US$63.00.`
  - ` · bought at US$2.00 = US$200.00 · sold at US$3.00 = US$300.00 (target, Nov 24) · +US$100.00 (+50.0%)`
  - ` · bought at US$1.50 = US$150.00 · sold at US$1.20 = US$120.00 (stop, Nov 24) · −US$30.00 (−20.0%)`
- **Held:** a `held` trade shows `(time up, `.
- **One trade:** says `1 finished trade:`.
- **21 trades:** render 20 `<li>`.
- **None:** `No finished paper trades yet.`

**`e2e/runners.spec.ts`:**
- **First test:** the card also contains `Paper trade: 100 shares at the open (about US$136.00 at the signal close)`.
- **"Open runners show their R so far and closed ones fill the track record":** replace the table checks.
  - There is one `open-runner-card`, and it contains:
    - `Bought 100 shares at US$1.92`
    - `= US$192.00`
    - `Now US$2.40`
    - `worth US$240.00`
    - `Stop US$1.44 · target US$2.88`
  - `open-runner-gain` has the text `+US$48.00 (+25.0%)` and a class matching `/gain/`.
  - `open-runner-r` has the text `+1.00R` and a class matching `/gain/`.
  - Seed MULN with `entry: 2, exitPrice: 3` and SNDL with `entry: 1.5, exitPrice: 1.2`. Keep their other fields, so the Track record assertion is unchanged.
  - Add: `runners-paper-total` has the text `2 finished trades: put in US$350.00, got back US$420.00, +US$70.00 (+20.0%). After the estimated spread: +US$63.00.`
  - Remove the `openTable` helper.
- **"No ignition yesterday and no finished runners":** also expects `No finished paper trades yet.`
