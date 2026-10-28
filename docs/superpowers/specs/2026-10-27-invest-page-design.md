# Invest page — design

**Status:** draft for the owner's approval, 2026-10-27.

**Builder:** the owner will hand the build to Cursor.

## Why

The owner wants to type an amount (say C$1,000) and get a concrete split. In the owner's own words: "invest 600 in A which has 5% return in the next months and invest 300 in B which is volatile with likely return of 2%". The page answers "where would this money go today, and why", using the forecasts every run already makes.

## What the owner decided (2026-10-27)

- **Five stocks plus crypto,** with an amount and the details for each.
- **Ranking and sizing follow the approach proposed in chat:**
  - rank with the picks' own rule;
  - weight by risk, giving less to volatile stocks;
  - cap any single stock;
  - show the costs.
- **When no stock qualifies** (true today, since picks are off in both markets): show the 5 best-ranked anyway, under a clear "Not validated" warning.
- **Crypto is a share the owner chooses** on the page. It goes to BTC, labelled "no forecast", because there is no crypto model (spec §5.4).

## Goals

- **One page, "Invest", in the left navigation.** It has an amount box (CAD) and a crypto-share box (%, default 10).
- **The result:**
  - up to 5 stocks and one BTC line;
  - each line has a dollar amount, an approximate number of shares, and why;
  - totals add up to the amount entered.
- **For each stock:**
  - the amount (C$) and approximate shares;
  - the expected return over its hold time, as a middle value with the likely range, for example "+2.1% (likely −4% to +9%) over 21 trading days vs SPY";
  - its chance of beating the benchmark;
  - 60-day volatility, in words and as a number;
  - hold time and exit-by date;
  - sector;
  - round-trip cost (US stocks show the currency fee);
  - a link to its Ticker page.
- **An honest frame:**
  - the page always states that returns are **relative to the benchmark** (SPY or XIU.TO), not absolute gains;
  - it shows the "Not validated" warning whenever fewer than 5 of the stocks shown pass the bar;
  - it carries the app's standing disclaimer.

## Non-goals

- No orders and no broker connection (spec non-goal).
- No new pipeline work: the page reads what runs already store.
- No crypto forecasts.
- No change to Today's Picks or the backtest gate.

## Anti-goals (a failure even if it works)

- Presenting excess return as plain return ("+2%" with no "vs SPY").
- Hiding that nothing passed the bar.
- Recommending a stock the model expects to lag, as if it were a buy.
- Totals that don't add up to the amount.

## How it works

**Data:** the latest published run that has `predictions`, from the same sources the dashboard already reads.
- `predictions`: per stock and horizon, `q10`/`q50`/`q90` (fractions, excess over benchmark), `p_beat` and `benchmark`.
- `features_live` (model features for forecast stocks):
  - `vol_60` (annualised 60-day volatility);
  - `log_adv20` (log of 20-day dollar volume);
  - `jump_5d`;
  - `model_eligible`.
- `symbols`: name, sector and market.
- `settings.usd_fx_fee_pct`, plus the latest `fx_rates`, `daily_closes` and the stored stock price for share counts.
- Held positions, to leave out (see the ranking rules).

**Ranking each stock.** These rules mirror the pipeline's picks (`pipeline/src/advisor/recommend/picks.py`) and must stay the same.
- **Round-trip cost:**
  - spread: 0.10% if 20-day dollar volume ≥ 10M, else 0.30%;
  - plus `2 × usd_fx_fee_pct / 100` for US stocks.
- **The ratio** for a horizon row is `q50 / (q90 − q10)`, and only when `q90 > q10`.
- **A row qualifies** when `p_beat ≥ 0.58` and `q50 > cost`.
- **Choosing the horizon:** a stock's chosen horizon is its qualifying row with the best ratio (ties go to the shorter horizon).
- **Stocks with no qualifying row** are used only when fewer than 5 stocks qualify. Then the stock's best-ratio row with `q50 > 0` is used. A stock whose every row has `q50 ≤ 0` is never shown, because the model expects it to lag.
- **Excluded:**
  - stocks with `jump_5d` not equal to 0 (a recent unconfirmed jump);
  - stocks you already hold (they get holding actions on My Portfolio instead).
- **Order:** qualifying stocks first, then the rest, each group by ratio, best first.
- **Sector cap:** at most 2 per sector. A stock with no sector counts alone.
- **Take the first 5.**

**Splitting the money.**
- The crypto share comes off first, as the amount × crypto %, and goes to BTC.
- The stock amount is split in proportion to `1 / vol_60`, with each stock capped at 40% of the stock amount. A missing or zero `vol_60` takes the median of the stocks shown. Anything over the cap is spread over the others, repeated until nothing is over.
- With fewer than 3 stocks the cap can't hold. Say so, and split evenly.
- Amounts are rounded to whole dollars. The rounding difference goes to the largest line, so the totals match exactly.
- **Shares** are the amount ÷ the latest price in CAD (USD prices × the latest USD/CAD rate). Show 2 decimals marked "≈", with a note that Wealthsimple allows fractional shares for many stocks.
- **The BTC line:**
  - shows its price only when the run has one (that is, when BTC is held or watched);
  - otherwise it shows the amount and "add BTC to your watchlist to see its price".

**Volatility in words:** by `vol_60` percentile among the run's forecast stocks: under 30 "low", 30–65 "medium", 65–90 "high", 90 and over "very high". This is not the spec's §6.4 risk level, which isn't stored for these stocks, so the page says "volatility", never "risk level".

**Hold time and exit-by:** the chosen horizon in trading days. Exit-by is that many sessions after the run's market day. It may be approximated as weekdays, labelled "≈".

**The URL carries the inputs** (`/invest?amount=1000&crypto=10`), so a result can be bookmarked and the page stays server-rendered. Inputs are validated:
- amount: 1 to 10,000,000;
- crypto: 0 to 100.
- A bad input shows a field error, never a crash.

## Layout (approved Ledger look: `.superdesign/design_iterations/`, theme already in `web/app/styles/`)

```
┌ Invest ──────────────────────────────────────────────────────────┐
│ Amount  [ C$ 1,000 ]   Crypto share [ 10 % ]   [ Split it ]      │
│ From the run of Oct 27, 8:15 AM · returns are vs SPY / XIU.TO     │
├──────────────────────────────────────────────────────────────────┤
│ ⚠ Not validated: none of these meets the bar today (picks are    │
│   off). They're the model's best-ranked, not recommendations.    │
├──────────────────────────────────────────────────────────────────┤
│ C$ 320  AAA  Example Corp · US · Technology        ≈ 4.27 sh     │
│         +2.1% (likely −4% to +9%) over 21 days vs SPY · P 54%    │
│         Volatility medium (31%/yr) · exit by Nov 25 · cost 3.1%  │
│ C$ 250  BBB.TO …                                                 │
│ … (up to 5)                                                      │
│ C$ 100  BTC  Bitcoin · crypto · no forecast (no crypto model)    │
├──────────────────────────────────────────────────────────────────┤
│ Total C$ 1,000 · Not financial or tax advice. Forecasts are      │
│ probabilistic and can be wrong.                                  │
└──────────────────────────────────────────────────────────────────┘
```

- **Phones:** each line stacks.
- **Empty states:**
  - **no published run with forecasts:** "No forecasts yet. They appear after the next run."
  - **nothing with a positive expected return:** "No stock is expected to beat its benchmark today", and the whole amount is shown as uninvested. The crypto line still shows.
- **Animation:** the existing `enter` / `stagger` classes only.

## Where it lives (web only)

- Navigation: add `{ href: '/invest', label: 'Invest', icon: <a lucide icon such as PiggyBank or CircleDollarSign>, primary: true }` to `web/components/shell/nav.ts`.
- `web/lib/invest/allocate.ts`: pure ranking and splitting, with no I/O, unit-tested with Vitest.
- `web/lib/data/invest.ts`: a server-only loader in the style of `web/lib/data/ticker.ts`.
- `web/app/(app)/invest/page.tsx`: a server component reading `searchParams`, with a plain GET form.
- Tests:
  - Vitest for `allocate.ts`: ranking, the sector cap, the fallback, the 40% cap, rounding to the exact total, crypto 0% and 100%, and the empty states;
  - one Playwright spec seeding a run with predictions and features, in the style of `web/e2e/*.spec.ts`.

## Left to the builder

- Exact copy beyond the strings above.
- The icon.
- Component split.
- How the stagger animation is applied.
