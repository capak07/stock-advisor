# Cursor task: the Invest page's "How long to hold" picker

**Do this after the order-guidance task.** It's on branch `invest-hold`, which Claude branched from `order-guidance`. Merge `order-guidance` into it first (`git merge order-guidance`); they touch different files except the Invest page.

## Already built (use, don't change)

- **`web/lib/invest/allocate.ts`:** `HOLDS` is `[{ value: 'any' | '21' | '63' | '126', label, horizons }]`. `allocate()` takes `horizons` and ranks only on those forecast horizons.
- **`web/lib/invest/inputs.ts`:** `parseInvestInputs` reads `hold` from the address. It returns `hold`, `horizons` and `holdError`, the latter "Choose how long to hold." for a bad value.

## What to build

1. **The picker** on `web/app/(app)/invest/page.tsx`:
   - A "How long to hold" `<select name="hold">` with the `HOLDS` labels: Any, ~1 month, ~3 months, ~6 months. The default is Any.
   - Show `holdError` like the other fields, and show no result while it's set.
   - Pass `inputs.horizons` to `allocate`.
   - Keep the form tidy at 390 px. The form now has five controls, so let it wrap.
2. **Two notes under the result,** in `.sub`:
   - With `hold` set to `'126'` and no TSX candidate having a 126-day forecast: "No TSX stock has a 6-month forecast this run, so only US stocks are ranked." (Check `data.candidates` for TSX rows with `horizonDays === 126`.)
   - With `hold` set to `'any'` or `'21'`: "Frequent short-term trades in a TFSA can be treated as a business, which makes the gains taxable; a longer hold avoids that (not tax advice)."
3. **Playwright, in `web/e2e/invest.spec.ts`:**
   - `holding for 3 months ranks on the 3-month forecast`. Seed a stock that's best over 10 days and another that's best over 63 days. `?hold=63` shows the second first, with "over 63 trading days".
   - `a bad hold value shows its error`.
   - The TFSA note shows for `hold=21` and not for `hold=63`.
4. **Docs:** add one line to `docs/superpowers/specs/2026-10-27-invest-page-design.md` saying the owner can pick how long to hold (owner decision 2026-10-28: exactly that horizon, not "or longer").

## Rules

- **Before committing, all of these pass** (from `web/`): `npm test`, `npm run lint`, `npm run typecheck`, `npx playwright test`.
- **Committing:**
  - Commit with the message `feat: choose how long to hold on the Invest page`.
  - Run `git commit` in its own command, never with `--no-verify`.
  - Don't push.
