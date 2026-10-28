# Cursor task: "How to place it" lines

**Paste this file into Cursor's agent.** Work on branch `order-guidance`.

## Read first

1. `docs/superpowers/specs/2026-10-28-order-guidance-design.md`: what and why.
2. `web/lib/orders.ts` and `web/lib/orders.test.ts`: the rules, already built and tested. Don't change them.
3. `web/AGENTS.md` (this Next.js differs from what you know), and the pages you'll touch.

## Already built (use, don't change)

- **`web/lib/orders.ts`:** `isMarketHours(now)`, `planBuy`, `planSell`, `planTrim`, `planStop` and `planRecurring`.
  - Each returns an `OrderPlan { steps: { text, kind, … }[]; notes: string[] }`. Show `steps[].text` in order, then `notes` as small print.
  - An `Instrument` is `{ assetType, currency, price, atrPct, dollarVolume20 }`.
  - **Coins trade in CAD in Wealthsimple:** for a coin, pass `currency: 'CAD'` and a CAD price, and convert any USD stop with the latest USD/CAD rate.
- **The data on each item:**
  - `PickView.atrPct`, `PickView.dollarVolume20` (`web/lib/data/picks.ts`). The price is `entry`, the stop is `stop`, and the currency is US→USD, TSX→CAD.
  - `HoldingAction.refPrice`, `atrPct`, `dollarVolume20` and `previousStop` (`web/lib/portfolio/actions.ts`). A coin's `refPrice`, `trailingStop` and `previousStop` are USD (Coinbase): convert them to CAD.
  - `StoredVerdict.atrPct` and `dollarVolume20` (`web/lib/data/watchlist.ts`). A Buy's price is `details.entry_ref_price` and its stop is `details.stop`.
  - `StockLine.price`, `currency`, `atrPct`, `dollarVolume20` (`web/lib/invest/allocate.ts`). The BTC line has `crypto.priceCad`.
- **The USD/CAD rate:** the latest from `loadFx(supabase).latest()?.usdCad`. Without one, skip the guidance for US stocks rather than guess.
- **`now`:** the server's `new Date()` when the page renders.

## What to build

1. **`web/components/OrderGuide.tsx`:** renders one `OrderPlan` as a compact block.
   - A label "How to place it", then each step's text on its own line.
   - Then the notes, in `.sub`.
   - Follow the Ledger look (`.sub`, `.num`, small type, no new colours).
   - It must fit at 390 px.
   - If the plan has no steps, render nothing.
2. **Today's Picks cards** (`web/components/picks/PickCard.tsx`): `planBuy` with the pick's instrument and `stop`.
   - `amountCad` is the card's max size in CAD (`maxPositionPct × portfolioCad / 100`).
   - Without a portfolio value, use C$1,000 and say "for C$1,000".
3. **Watchlist Buy verdicts** (`web/components/watchlist/Watchlist.tsx`): the same as a pick, from the verdict's details. Show it under the Buy's "why", only for Buy rows.
4. **My Portfolio:**
   - **Action cards** (`web/components/portfolio/Cards.tsx` `ActionsCard`):
     - Sell: `planSell` (qty = the position's quantity);
     - Trim: `planTrim`;
     - Add: `planBuy`, with `amountCad` = max size CAD − the position's CAD value (skip it if that's ≤ 0) and `stop` = the holding's trailing stop;
     - Hold: no order.
   - **Every held stock with a trailing stop** gets `planStop({ qty, stop: trailingStop, previousStop })`:
     - on its action card, unless the action is Sell;
     - in the holdings table's Notes, as a short line.
   - **A coin** gets `planStop`'s alert line the same way.
   - The quantity is the position's quantity per account. The page already has it in `view.sellable` (`qty`, keyed like the actions by account:assetType:symbol).
5. **The Invest page** (`web/app/(app)/invest/page.tsx`):
   - each stock line gets `planBuy` for its `amount` (no stop);
   - the BTC line gets `planBuy` for the crypto instrument at `crypto.priceCad`, and `planRecurring({ amountCad, symbol: 'BTC' })` under it;
   - without a BTC price, show only the recurring line.
6. **A disclaimer line, once per page** where guidance shows: "Order guidance is a rule of thumb for Wealthsimple's order types, not a price forecast."
7. **Tests:**
   - **Playwright:** extend the existing specs (`picks.spec.ts`, `watchlist-settings.spec.ts`, `portfolio.spec.ts`, `invest.spec.ts`). Assert:
     - a pick card shows "Limit buy" and "stop-limit sell";
     - a watchlist Buy shows "Limit buy";
     - a seeded Sell action shows "Limit sell";
     - a held stock's note shows "Stop-limit sell", and "raise it from" when an earlier published run's action had a lower trailing stop (seed two runs);
     - an Invest stock line shows "Limit buy", and the BTC line shows "recurring buy".
   - **Time of day:** the duration words depend on it ("Day order" vs "end of the next trading day"), so match either with a regex. Seed `features_live` with `atr_14_pct` and `log_adv20` where a test needs exact prices.
8. **Docs:**
   - spec §9: one line per page saying it shows "How to place it" (see the design);
   - `web/README.md`: a line under the pages list.

## Rules

- **Don't change** `web/lib/orders.ts` or the loaders. If something is missing, say so instead of working around it.
- **Before each commit, all of these pass** (from `web/`): `npm test`, `npm run lint`, `npm run typecheck`, `npx playwright test`. Playwright needs the local Supabase stack, `npm run db:start`.
- **If a run stalls for a long time, the PC probably slept.** Re-run it.
- **Committing:**
  - Run `git commit` in its own command. A hook mistakes any `-n` flag in the same command for `--no-verify`.
  - Never use `--no-verify`.
  - Don't push.
  - Use one commit per numbered item, or group 2–5 as `feat: show how to place each trade`, and 7 and 8 with their item.

When done, tell the owner it's ready for review.
