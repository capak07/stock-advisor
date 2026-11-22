# Liquid-glass redesign of the web app

**Status:** draft for the owner's approval · 2026-11-21
**Replaces:** the "Ledger" look (`.superdesign/design_iterations/theme_1.css`, `dashboard_1.css`) and the current page layouts.
**Mockups (approved by the owner, 2026-11-21):** `.superdesign/design_iterations/`
`today_1.html`, `portfolio_2.html`, `daytrade_1.html`, `picks_2.html`, `invest_1.html`, `watchlist_2.html`, `ticker_2.html`,
built from `theme_2.css` (tokens), `glass_ui.css` (components and motion) and `glass_ui.js` (mockup behaviour only).
Open them in Chrome or Edge; `?theme=dark` forces dark mode.

## 1. Intent

The owner finds the app plain. They want it new and stylish in a liquid-glass style: frosted, see-through panels
floating over a faint glow, with soft light edges and calm motion. They asked for both a new look and new layouts.

The new layouts follow how the owner actually uses the app every day, in this order:
1. Do any holdings need action? Should I sell anything?
2. Are there good day trades today?
3. Are there any picks?
4. Look up a stock: will it grow or lose, its news, its earnings.

Today those answers are spread over three tabs and search is a small box. The redesign puts 1–3 on one home
screen, makes search the first thing on every page, and reorders the stock page around forecast, news and earnings.

## 2. Goals, non-goals, anti-goals

**Goals**
- One glass look (theme, surfaces, motion) on every page, in light and dark mode, on desktop and the Android app.
- A new home page, **Today**, that answers the daily questions at a glance.
- New layouts for Portfolio, Day trade, Picks, Invest, Watchlist and the stock page, as in the mockups.
- Search reachable from every page, and as its own phone tab.

**Non-goals**
- No change to what the pipeline computes or stores. No new data, no schema change. New **read-only** web
  loaders over tables that already exist are fine (Today and the Watchlist need two, §7.1 and §7.6).
- No change to the rules behind actions, picks, exit plans or day-trade signals.
- Sources, Settings and Login keep their layouts; they only take the new look.
- No new UI or animation library.

**Anti-goals (a failure even if it works)**
- **The gloss must not make weak forecasts look confident.** Most forecasts sit near 50%. Say "No clear edge"
  in words and show the chance as a number; never a big green "UP" arrow. Day-trade verdicts keep their plain
  lines ("Close to a coin flip"). (Owner, 2026-11-21.)
- **Pick cards never show a chance of beating the market.** A pick shows how it was chosen and its model's
  backtest record. (Owner's decision 2026-11-07, already in `components/picks/PickCard.tsx`; it stands.)
- Too much colour. The owner rejected a warm, colourful version: the look is **cold and dark**. (Owner, 2026-11-21.)
- Stutter on the phone. The glass must stay smooth in the Android app.

## 3. Approaches

| | Approach | Trade-off |
|---|---|---|
| **A (chosen by the owner)** | Restyle and recompose in place: keep the components and data code, swap the theme and surface CSS, build Today and the new layouts from the existing cards, motion in plain CSS. | Smallest and safest; logic and most tests untouched; light on the phone. Motion is fades, slides and lifts, not spring physics. |
| B | Rebuild the components on a UI kit plus a motion library. | Richer motion and ready-made parts, but rewrites every component and most tests, adds weight and dependencies. |
| C (dropped) | A brand-new frontend. | Throws away working code for no visible gain. |

## 4. The look

The tokens are in `.superdesign/design_iterations/theme_2.css`; port it as the app's `web/app/styles/theme.css`.
**The token names are the same as today's**, so components that use them pick the look up unchanged. New tokens:
`--brand`, `--brand-soft`, `--glass-*`, `--aurora-*`.

- **Light mode, "frost":** cool white and silver with a faint ice tint.
- **Dark mode, "cold night":** almost black (`oklch(0.095 0.006 250)`) with a trace of steel and a barely-there glow.
- **Aurora:** a fixed layer behind the page: four large blurred radial blobs on the base colour, low in colour,
  carrying no meaning.
- **Glass:** `.glass` = translucent fill, `backdrop-filter: blur() saturate()`, a bright 1px rim, a top inner
  highlight, a faint outer hairline and a soft diagonal sheen. `.glass-strong` (more opaque) for the top bar, the
  sidebar, the tab bar, sheets and menus. Glass goes on cards, bars, sheets and controls only, never on text blocks
  inside a card.
- **Liquid refraction:** the top bar, sidebar and phone tab bar also bend what is behind them through an SVG
  displacement filter (`#liquid` in the mockups) — only in Chrome-based browsers (the Android app, Chrome, Edge).
  Safari and Firefox get the plain frosted glass. **Detect Chromium in script, not with
  `@supports (backdrop-filter: url(#liquid))`**: a browser that parses the `url()` but cannot draw it would lose
  the blur entirely. (My call; the mockup uses `@supports` only because it is a mockup.)
- **Colour only for meaning:** gain green, loss red, Trim orange, Review amber, Hold grey, the four risk levels and
  source status, all as today. One accent, ice (dark) / steel (light), marks "you are here" (active nav item, active
  tab, focus ring) and is never a gain or a loss. Cool steel and ice are used because the owner asked for cold; no
  saturated blue or indigo.
- **Type:** Geist for text, Geist Mono for every number (unchanged fonts, loaded by `next/font` as now).
- **Shape:** cards 20px corners, hero card and tab bar 28px, inputs 14px, buttons and chips pill-shaped.
- **Buttons:** the main button is solid ink (white in dark mode); the others are glass.
- **Accessibility:** `prefers-reduced-transparency` makes glass solid; text contrast must stay at WCAG AA on glass in
  both modes, checked over the brightest part of the aurora.

## 5. Motion

Defined in `glass_ui.css` (bottom section). All CSS, plus small scripts where noted. Animate only `transform` and
`opacity`.

- **Background:** the aurora drifts over 60 s, alternate, transform only; it pauses when the page is hidden.
- **Pages:** cards enter with a 320 ms rise-and-fade, staggered 40 ms for the first six. Between routes, a 220 ms
  crossfade using the browser's view transitions where supported, otherwise instant (check how Next 16 supports
  this before building; see §8).
- **Glass:** desktop hover lifts a clickable card 2px; press scales to 0.98 and springs back. On desktop a highlight
  follows the pointer along the card rim (small script).
- **Navigation:** the active-tab pill slides to the tapped tab and stretches mid-way (the "liquid" move); the icon
  bumps. The phone tab bar hides while scrolling down and returns on scroll up. The desktop sidebar has the same
  sliding pill.
- **Numbers:** values count up (the existing `TweenNumber`); prices flash gain-soft or loss-soft once after Refresh.
- **Day trade:** a pulsing live dot while the market is open; a status chip pops when it changes.
- **Sheets and menus:** sheets slide up 340 ms while the page behind dims and blurs (the only animated blur);
  menus and search results drop in 180 ms.
- **Charts:** the line draws left to right in 700 ms; the forecast range fades in after it.
- **Loading:** skeletons with a sheen sweeping across the glass.
- **Reduced motion:** with `prefers-reduced-motion`, everything becomes a 120 ms fade, the aurora stands still and
  chart lines appear without drawing.
- **Performance budget:** never animate `backdrop-filter` on cards. Test scrolling on the owner's Android phone.

## 6. Navigation and routes

- **`/` becomes Today** (new page). **Portfolio moves to `/portfolio`.** Every other route stays.
- **Phone tab bar** (floating glass pill): Today · Portfolio · Day trade · Search · More.
  - **Search** opens a full-screen search with recent stocks; picking one goes to the stock page. "Recent" is kept
    per device in the browser's local storage, updated when a stock page opens, and is simply empty when storage
    is unavailable. (My call: no new stored data; the phone and the desktop each keep their own list.)
  - **More** opens a sheet: Picks, Invest, Watchlist, Sources, Settings, and the light/dark switch.
  - This replaces today's tabs (Portfolio, Picks, Invest, Day trade) and supersedes the 2026-11-15 note in
    `components/shell/nav.ts` that put Watchlist first under More. The More sheet lists the pages in the mockup's
    order: Picks, Invest, Watchlist, Sources, Settings.
- **Desktop:** a floating glass sidebar: Today, Portfolio, Day trade, Picks, Invest, Watchlist, then Sources and
  Settings below a divider; the run-freshness note at the bottom.
- **Top bar on every page:** a large glass search field first, then Refresh prices, the run pill (desktop) and the
  light/dark button. `/` focuses search on desktop.
- The Android app keeps its safe-area padding (`--safe-area-inset-*`) on the top bar and the tab bar.

## 7. Pages

Each page uses the data it uses today; where a page gains a section, its data comes from an existing loader.

### 7.1 Today (`/`, new) — mockup `today_1.html`
- **Header:** the date and market state ("Saturday, Nov 21 · markets closed") and the time of the last run.
  "Market open" means today's day-trade session row exists and `isLive` (in `lib/daytrade.ts`) says it is live;
  otherwise "markets closed". This follows the day-trade job, so holidays read as closed without a holiday list.
  (My call.)
- **Portfolio summary card** (links to `/portfolio`): total value, today's change, all-time return, the return against
  SPY over 1Y, and a small sparkline of the portfolio against SPY. Data: `loadPortfolio` + `portfolioView`.
  **No cash figure:** the app has no cash balance (the portfolio is built from trades, prices and FX), so the
  mockups' "Cash" numbers are dropped. Tracking cash would be new data and is out of scope. (My call.)
- **Needs your attention:** holdings whose latest action is Sell, Trim, Review or Add, each with its chip, symbol,
  one-line reason and P/L; then "N more on Hold" linking to `/portfolio`; then the portfolio warnings (e.g. TFSA
  round trips). Data: `loadHoldingActions`, `portfolioView().warnings`. If nothing needs action, say so in one line.
- **News on your holdings:** the latest 3 items of the monitor feed, with a link to all of them. Data: `loadMonitorFeed`.
- **Day trade · top 3 after costs:** today's top 3 with status chip; the first one shows entry, target and stop
  tiles; each shows its verdict line and net history R. Links to `/daytrade`. It shows **the same day the Day trade
  page shows**, with the same data and live logic (`loadDaytrade`, `isLive`); when that page has no session, the
  card says "No session today". (My call.)
- **Picks:** if there are picks, their count per market and a link. If none: "None today", the best chance of
  beating the market in the latest run against the 58% bar, "Nothing has enough evidence to buy", and links to
  Picks ("Why none?") and Watchlist verdicts.
  - **The best chance, per market:** the highest P(beat) among the latest published run's predictions for that
    market, over all its horizons, against that market's own benchmark, e.g. "US 52.7% vs SPY · TSX 55.1% vs
    XIU.TO". A new read-only loader. The number is a fact about today's run, not a promise about a stock, and it
    never appears on a pick card. (My call.)
- **Phone:** one column in the order above. **Desktop:** the summary card full width, then two columns: left =
  Needs your attention, News; right = Day trade, Picks.

### 7.2 Portfolio (`/portfolio`) — mockup `portfolio_2.html`
- Header with the accounts and the Buy (main button), Sell and Import (glass) buttons; Buy, Sell and Import open
  as glass sheets.
- **Value hero:** total value, all-time gain, today's change, the 1D–All period control, and the chart of the
  portfolio against SPY and XIU.TO in CAD (the existing `ValueCard` and `LineChart`).
- **Holdings:** every holding with account, action chip, shares, value in CAD, P/L and weight (a weight bar, orange
  when over the cap). A table on desktop, compact rows on a phone. No cash line (see §7.1).
- **Breakdown** (by risk, market, account) and **Warnings** in a right column on desktop.
- **Trades**, newest first, with "Show all".
- The monitor feed moves to Today; Portfolio keeps no news card.

### 7.3 Day trade (`/daytrade`) — mockup `daytrade_1.html`
- Header with the date and a live pill ("updates every minute") while the market is open.
- **Top 3 after your costs:** three cards side by side on desktop, stacked on a phone. Each: rank, symbol and name,
  status chip, entry/target/stop tiles, cost in R, net history R, net replay R, the verdict line, opening range,
  flat-by time and the top headline.
- **The skill's top 3:** the same information, in smaller cards.
- **All signals:** a collapsed table.
- **Track record** and **Notes** (costs, rules, limits) side by side on desktop. The track record says plainly when
  the record is too short to judge.

### 7.4 Picks (`/picks`, under More) — mockup `picks_2.html`
- **No picks:** an empty-state card: "No picks today", the best chance against the 58% bar, "Nothing has enough
  evidence to buy", buttons to the watchlist verdicts and "Why?", and the short explanation block.
- **With picks:** US | TSX tabs; each pick card shows "Chosen by" (the rule, or the rank for a rank policy), the
  note that no chance of beating the benchmark is shown, the expected range bar, entry, stop, exit-by, the model's
  backtest record, the cost line and the Bought button — what `PickCard` shows today, restyled.

### 7.5 Invest (`/invest`, under More) — mockup `invest_1.html`
- The amount form on the left (sticky on desktop), "Where $X would go" on the right; stacked on a phone.
- Each line: symbol and name, amount, shares, a weight bar, the existing "likely a to b vs benchmark" line, and its
  order guide in an expandable block. The no-picks warning and the order disclaimer as today.

### 7.6 Watchlist (`/watchlist`, under More) — mockup `watchlist_2.html`
- A glass search field with Add on top.
- Rows: symbol and name, price, today's move, the verdict chip with its chance as a number and horizon, a range
  bar, the order guide when there is one. A stock the owner holds shows its Portfolio action instead of a verdict
  (as the app does today).
- **New on this page:** today only a Buy row shows its chance (inside its details text). The approved mockup shows
  the chance, horizon and likely range on every row, with "No clear edge" in words for most of them. The data
  comes from the latest published run's predictions for the watched symbols (q10, q50, q90, P(beat)) at the
  verdict's horizon, or the 21-day horizon when the verdict has none — a new read-only loader, like the one the
  stock page uses. (My call on the horizon.)

### 7.7 Stock page (`/ticker/[symbol]`) — mockup `ticker_2.html`
- **Phone order:** header (back, symbol, name, price, today's move) with a one-line outlook; the price chart with
  the forecast range ahead and a 1W–1Y control; Outlook; Your position (only if held); News and filings; Earnings;
  Watch / Alerts / Sources.
- **Desktop:** left = header, chart, News and filings; right = Outlook, Your position, Earnings, actions.
- **Outlook card:** "No clear edge" (or the verdict) in words as the headline, the chance as a number
  ("52% chance to beat the market over 21 days"), a 5/21/63-day control, and the likely range at that horizon.
  The stock page shows this chance today. After the redesign the chance appears on the stock page, the watchlist
  rows (§7.6) and, as the best of the run, in the no-picks message; never on a pick card.
- **Your position:** shares, value, average cost, P/L, the action chip, and the exit plan summary (sell-at line,
  break-even, stop, plan status) with a link to the full plan — what `ExitPlan` shows today, including its rules
  for when a sell-at price is shown.
- Alerts open as a glass sheet.

### 7.8 Sources, Settings, Login
Layouts unchanged; they take the new theme, glass cards, buttons and fields.

## 8. Constraints

- **Next.js 16 differs from older versions.** Read `web/AGENTS.md` and the guides in `web/node_modules/next/dist/docs/`
  before writing code, in particular for routing, layouts and any view-transition support.
- **No new dependencies.** Icons stay `lucide-react`.
- **Tests:** Vitest unit tests and Playwright e2e must pass. Moving Portfolio to `/portfolio` touches many e2e tests
  that open `/` (43 `goto('/')` calls today); update them to the new routes rather than keeping Portfolio at `/`.
- **Android app:** the Capacitor shell (`components/NativeShell.tsx`) and safe areas keep working; check the glass,
  the tab bar and scrolling on the owner's phone.
- **Dark mode** stays the `dark` class on `<html>` with the existing `ThemeToggle`.
- **Copy rules** already in the app stay: plain words, CAD values, "Not financial advice" where it is today.

## 9. Left to the builder

- How the mockup classes map onto the existing CSS files (`theme.css`, `ledger.css`, `pages.css`) and component
  class names (e.g. `statusbar` → top bar, `bottom-tabs` → tab bar), and whether to rename or keep them.
- Component structure for Today (new components vs reusing `Cards.tsx`, `MonitorCard`, `SignalCard`).
- How the full-screen phone search reuses `FindTicker` / `SymbolSearch`.
- Empty and loading states for every new section, in the same plain voice.
- Sample texts in the mockups are illustrative; real text comes from the existing components and data.

## 10. Owner's decisions in this design (2026-11-21)

- New look **and** new layouts.
- **Today** is the home page; Portfolio becomes a tab; Picks moves under More.
- Phone tabs Today · Portfolio · Day trade · Search · More.
- Approach A (restyle and recompose in place).
- Layouts, theme (cold, dark; "more dark"), motion and all seven mockups approved.
