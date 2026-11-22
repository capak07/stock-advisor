# Liquid-glass Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the web app the approved cold, dark liquid-glass look, a new Today home page, and the new layouts for Portfolio, Day trade, Picks, Invest, Watchlist and the stock page.

**Architecture:** Restyle and recompose in place (spec §3, approach A). The theme is a token swap (same token names), the glass and motion are CSS applied to the existing class names, and the new layouts reuse the existing cards and data loaders. Three small read-only loaders and a few pure helpers in `web/lib/` are new; nothing in `pipeline/` or `supabase/` changes.

**Tech Stack:** Next.js 16 (App Router), React 19, Tailwind 4 + plain CSS, Supabase JS, lucide-react, Vitest (node, `renderToStaticMarkup`), Playwright (Edge on Windows, local Supabase stack).

**Spec:** `docs/superpowers/specs/2026-11-21-liquid-glass-redesign-design.md`. Mockups: `.superdesign/design_iterations/` (`today_1`, `portfolio_2`, `daytrade_1`, `picks_2`, `invest_1`, `watchlist_2`, `ticker_2` `.html`; `theme_2.css`, `glass_ui.css`, `glass_ui.js`). Read the spec, then open the mockup for your task in Edge (`?theme=dark` forces dark).

## Global Constraints

- Work on branch `liquid-glass`. Run `git commit` as its own command; never `--no-verify`. Commit trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Next.js 16 is not the Next.js you know: read `web/AGENTS.md` and the relevant guide in `web/node_modules/next/dist/docs/` before writing routing, layout or transition code.
- No new dependencies. Icons stay `lucide-react`.
- No change under `pipeline/` or `supabase/`. New web loaders are read-only.
- Theme token names stay as in today's `theme.css`; new tokens: `--brand`, `--brand-soft`, `--glass-*`, `--aurora-*`.
- Dark mode stays the `dark` class on `<html>` with the existing `ThemeToggle`.
- Colour only for meaning; the "you are here" accent is `--brand`. No saturated blue or indigo.
- Animate only `transform` and `opacity`; never animate `backdrop-filter` on cards (the sheet backdrop is the one exception).
- `prefers-reduced-motion`: 120 ms fades, the aurora still, chart lines appear without drawing. `prefers-reduced-transparency`: glass becomes solid.
- Pick cards never show a chance of beating the market (owner, 2026-11-07). Weak forecasts read "No clear edge" in words, with the chance as a number; no big arrows.
- Keep the Capacitor safe-area padding (`--safe-area-inset-*`) on the top bar and tab bar.
- Every page fits a 390 px phone with no horizontal scroll.
- Tests: `cd web && npx vitest run`, `npm run typecheck`, `npm run lint`, and Playwright (`npm run db:start` first; Docker Desktop must be running — it stops on its own on this machine, restart it if the stack fails). Run `npx playwright test` for the full suite at the end of each task that touches pages.

## Review Focus

1. **An empty portfolio (no trades) on Today** — the summary card shows C$0 without a chart, and "Needs your attention" says nothing needs attention, no crash. Test in Task 5.
2. **No published run yet (fresh database)** — Today's Picks card and the Picks page say there is no run yet instead of a best-chance line. Test in Task 5 and Task 8.
3. **A weekend or holiday (no day-trade row)** — Today says "markets closed" and its Day trade card says "No session today". Test in Task 5.
4. **Local storage unavailable or corrupt** (private window, a blocked WebView, a hand-edited value) — recent searches are empty and nothing throws. Test in Task 4.
5. **A browser without liquid support (Firefox, Safari) or without `backdrop-filter`** — no `liquid` class, glass still blurred or solid, text readable. Test in Task 1.

## File Structure

| File | Responsibility |
|---|---|
| `web/app/styles/theme.css` (modify) | Tokens from `theme_2.css` (both modes + aliases). |
| `web/app/styles/glass.css` (create) | Aurora, `.glass` recipes, liquid gating by `html.liquid`, fallbacks. |
| `web/app/styles/ledger.css`, `pages.css` (modify) | Components, layouts and motion from `glass_ui.css` on the existing class names. |
| `web/lib/glass.ts` (create) | `supportsLiquidGlass()`. |
| `web/components/GlassBackdrop.tsx` (create) | The aurora element, the `#liquid` SVG filter, the `liquid` class, aurora pause. |
| `web/lib/scroll.ts` (create) | `nextHidden()` for the hiding tab bar. |
| `web/components/shell/*` (modify) | New nav model, sidebar pill, tab bar, Search and More sheets, top bar. |
| `web/app/(app)/page.tsx` (rewrite) | Today. |
| `web/app/(app)/portfolio/page.tsx` (create, moved) | Portfolio. |
| `web/lib/recent.ts` (create) | Recent searches in local storage. |
| `web/lib/today.ts` (create) | `needsAttention()`, `todayLine()`, `bestChanceLine()`, `PICK_P_FLOOR`. |
| `web/lib/data/best-chance.ts` (create) | `loadBestChances()`. |
| `web/components/today/*` (create) | Today's cards. |
| `web/lib/outlook.ts` (create) | `nearestHorizon()`, `outlookFor()`, `edgeWords()`. |
| `web/lib/data/watch-outlook.ts` (create) | `loadWatchOutlooks()`. |

---

### Task 1: Glass theme and recipes

**Files:**
- Modify: `web/app/styles/theme.css`, `web/app/globals.css`, `web/app/layout.tsx`
- Create: `web/app/styles/glass.css`, `web/lib/glass.ts`, `web/components/GlassBackdrop.tsx`
- Test: `web/lib/glass.test.ts`

**Interfaces:**
- Produces: `supportsLiquidGlass(brands: readonly { brand: string }[] | undefined, userAgent: string): boolean`; CSS classes `.aurora`, `.aurora.paused`, `.glass`, `.glass-strong`, `.glass-liquid`; `html.liquid`; SVG filter id `liquid`; tokens listed in Global Constraints.

- [ ] **Step 1: Write the failing test** `web/lib/glass.test.ts`

```ts
describe('supportsLiquidGlass', () => {
  it('is true for Chrome, Edge and the Android WebView', () => {
    expect(supportsLiquidGlass([{ brand: 'Chromium' }, { brand: 'Google Chrome' }], '')).toBe(true)
    expect(supportsLiquidGlass([{ brand: 'Microsoft Edge' }, { brand: 'Chromium' }], '')).toBe(true)
    expect(supportsLiquidGlass(undefined, 'Mozilla/5.0 (Linux; Android 14; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/131.0 Mobile Safari/537.36')).toBe(true)
  })
  it('is false for Firefox, Safari and Chrome on iOS (WebKit underneath)', () => {
    expect(supportsLiquidGlass(undefined, 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0')).toBe(false)
    expect(supportsLiquidGlass(undefined, 'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15')).toBe(false)
    expect(supportsLiquidGlass(undefined, 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/131.0 Mobile/15E148 Safari/604.1')).toBe(false)
  })
})
```

- [ ] **Step 2: Run it to see it fail** — `cd web && npx vitest run lib/glass.test.ts` → FAIL (module not found).

- [ ] **Step 3: Implement `supportsLiquidGlass` in `web/lib/glass.ts`** — true when `brands` names `Chromium`, else when the user agent has `Chrome/` and none of `Firefox/`, `CriOS/`, `FxiOS/`, `EdgiOS/`.

- [ ] **Step 4: Run it to see it pass** — same command → PASS.

- [ ] **Step 5: Port the theme.** Replace the `:root`, `.dark` and alias blocks of `web/app/styles/theme.css` with those of `.superdesign/design_iterations/theme_2.css` (the cold, darker version, everything above "The two recipes"). Keep the header comment style; say the source is `theme_2.css`. Create `web/app/styles/glass.css` from that file's recipes section, with one change: the liquid rule is `html.liquid .glass-liquid { backdrop-filter: url(#liquid) blur(var(--glass-blur)) saturate(var(--glass-saturate)); }` (plus the `-webkit-` line) instead of `@supports (backdrop-filter: url(#liquid))`. Import it in `globals.css` right after `theme.css`.

- [ ] **Step 6: Create `GlassBackdrop`** (`'use client'`, no props) in `web/components/GlassBackdrop.tsx`: renders `<div className="aurora" aria-hidden="true" />` and the zero-size SVG with `<filter id="liquid">` copied from `today_1.html`; on mount toggles `liquid` on `document.documentElement` from `supportsLiquidGlass(navigator.userAgentData?.brands, navigator.userAgent)`, and toggles `paused` on the aurora on `visibilitychange`. Render it first inside `<body>` in `web/app/layout.tsx`, so Login gets the aurora too.

- [ ] **Step 7: Verify** — `npx vitest run`, `npm run typecheck`, `npm run lint` pass; `npx playwright test e2e/shell.spec.ts e2e/auth.spec.ts` pass. Open `/` in Edge light and dark: the aurora and the token colours show; in Firefox (if installed) `html` has no `liquid` class and cards are still frosted.

- [ ] **Step 8: Commit** — `git add web/app web/lib/glass.ts web/lib/glass.test.ts web/components/GlassBackdrop.tsx`, then `git commit -m "feat(web): cold liquid-glass theme, aurora and the liquid filter"`.

### Task 2: Glass components and motion on the existing classes

**Files:**
- Modify: `web/app/styles/ledger.css`, `web/app/styles/pages.css`

**Interfaces:**
- Consumes: Task 1's tokens and `.glass` recipe values.
- Produces: the motion classes later tasks use: `.enter` (stagger by `--i`), `.dot.live`, `.chip.flip`, `.tick-up`, `.tick-down`, `.skeleton`, `.draw` with `path.line` and `.cone`, `.rim`, `.hero`; component classes `.range`, `.stat`/`.stats`, `.empty .halo`, `.seg`, `.count`, `.verdict`.

This task changes CSS only; the DOM stays as it is, so every existing test keeps passing.

- [ ] **Step 1: Apply the glass recipe to the existing surfaces.** In `ledger.css`, give these the `.glass` look (fill, blur, rim, highlight, edge, sheen via `::before`): `.card`, `.popover`, `.combo-list`; the `.glass-strong` look: `.sidebar`, `.drawer`, `.bottom-tabs`, the search field inside `.statusbar`. Radii: `.card` `--radius-lg`, `.drawer` top corners `--radius-xl`, `.bottom-tabs` and the hero `--radius-xl`. Map the rest of `glass_ui.css` onto today's names:

| `glass_ui.css` | existing class |
|---|---|
| `.topbar`, `.searchbar` | `.statusbar` (transparent, sticky), its `.field` search input (44 px pill) |
| `.tabbar`, `.tab`, `.tab-pill` | `.bottom-tabs` (floating pill, `bottom: 14px + safe area`, width `min(440px, 100% - 24px)`), `.bottom-tab`, `.tab-pill` |
| `.nav-link`, `.nav-pill`, `.nav-sep` | same names |
| `.sheet`, `.scrim`, `.grabber` | `.drawer`, `.backdrop` (`.open` dims and blurs 8 px), `.grab` |
| `.btn-primary`, `.btn-glass`, `.btn-ghost` | `.btn-primary`, `.btn-secondary`, `.btn-ghost` |
| `.input`, `.select` | `.field input`, `.field select`, `.with-unit input` |
| `.table` | the existing table classes in `pages.css` (`.dt-table`, the holdings table) |

- [ ] **Step 2: Add the motion section** at the end of `ledger.css` from `glass_ui.css` "Motion": aurora drift 60 s; `.enter` rise-and-fade 320 ms with `animation-delay: calc(var(--i, 0) * 40ms)`, and set `--i` with `.page > .enter:nth-child(1..6) { --i: 0..5 }` (no script); `.dot.live`; `.chip.flip`; `.tick-up` / `.tick-down`; `.draw`; `.skeleton`; press scale `0.97`/release overshoot on `.btn`, `.icon-btn`, `.bottom-tab`; desktop hover lift on `.card.rim`, `.card.lift`; the rim-light `::after` driven by `--mx`/`--my`; the full reduced-motion block.

- [ ] **Step 3: Port the shared pieces** used by later tasks into `ledger.css` (`.range`, `.stats`/`.stat`, `.big`, `.empty .halo`, `.seg`, `.count`, `.verdict`, `.edge`, `.page-head`, `.section-head`), with the grid rule from the mockup: every grid gets `grid-template-columns: minmax(0, 1fr)` and `main.page` keeps `minmax(0, 1fr)`.

- [ ] **Step 4: Verify** — full suite: `npx vitest run`, `npm run typecheck`, `npm run lint`, `npx playwright test` all pass (no DOM change). Screenshot `/`, `/picks` and `/daytrade` at 1440×900 and 390×844, light and dark, with Playwright and compare by eye with the mockups' surfaces (layouts still differ until later tasks).

- [ ] **Step 5: Commit** — `git add web/app/styles`, then `git commit -m "feat(web): glass surfaces and motion on every existing component"`.

### Task 3: Routes, navigation and the top bar

**Files:**
- Move: `web/app/(app)/page.tsx` → `web/app/(app)/portfolio/page.tsx` (`git mv`)
- Create: `web/app/(app)/page.tsx` (Today, first version), `web/lib/scroll.ts`, `web/components/shell/useHideOnScroll.ts`, `web/components/shell/NavPill.tsx`
- Modify: `web/components/shell/nav.ts`, `Navigation.tsx`, `Shell.tsx`, `FindTicker.tsx`
- Test: `web/lib/scroll.test.ts`, `web/e2e/navigation.spec.ts`, and every e2e spec that opens `/` for Portfolio content
- Read first: the Next 16 routing guide in `web/node_modules/next/dist/docs/01-app/`.

**Interfaces:**
- Produces: `NavItem { href: string; label: string; icon: LucideIcon; tab: boolean; group: 'main' | 'more' }`; `NAV` in this order — Today `/` (tab), Portfolio `/portfolio` (tab), Day trade `/daytrade` (tab), Picks `/picks`, Invest `/invest`, Watchlist `/watchlist`, Sources `/sources`, Settings `/settings`; the last five are `group: 'more'` on a phone, the last two sit under the divider on desktop. `nextHidden(prevY: number, y: number, hidden: boolean): boolean`. The phone Search sheet is a `Drawer` with id `search-sheet` and title `Search`; the More sheet keeps id `more-sheet`, title `More`.

- [ ] **Step 1: Write the failing test** `web/lib/scroll.test.ts`

```ts
describe('nextHidden', () => {
  it('hides only when scrolling down past 120 px', () => {
    expect(nextHidden(100, 110, false)).toBe(false) // still near the top
    expect(nextHidden(200, 260, false)).toBe(true)
    expect(nextHidden(260, 200, true)).toBe(false) // scrolling up shows it
  })
  it('ignores moves under 6 px', () => {
    expect(nextHidden(300, 304, false)).toBe(false)
    expect(nextHidden(300, 296, true)).toBe(true)
  })
})
```

- [ ] **Step 2: Run it to see it fail** — `npx vitest run lib/scroll.test.ts` → FAIL.

- [ ] **Step 3: Implement `nextHidden` in `web/lib/scroll.ts`** and `useHideOnScroll(): boolean` in `components/shell/useHideOnScroll.ts` (passive scroll listener, `requestAnimationFrame`-throttled). Run the test → PASS.

- [ ] **Step 4: Move Portfolio and start Today.** `git mv` the page to `portfolio/page.tsx`, set its metadata title to `My Portfolio` (unchanged), and remove its `MonitorCard` (news moves to Today). New `app/(app)/page.tsx`: metadata title `Today`, a `.page-head` with the label line and `<h1>Today</h1>`, then `<MonitorCard items={await loadMonitorFeed(supabase)} />`. (Task 5 fills in the rest.)

- [ ] **Step 5: Navigation.** Rewrite `nav.ts` to the interface above. `SidebarLinks`: the links with a `NavPill` (absolutely positioned, moves to the current link's `offsetTop`, transition `300ms cubic-bezier(.3,1.3,.5,1)`), a `.nav-sep` before Sources. `BottomTabs`: Today, Portfolio, Day trade links, a Search button (opens `search-sheet` with `<FindTicker onGo={close} autoFocus />`), a More button (opens `more-sheet`: Picks, Invest, Watchlist, Sources, Settings as `.nav-link`s, then a row with `ThemeToggle`, the "US Paper · TSX Paper" note and the sign-out form). A sliding `.tab-pill` sits under the current tab and is hidden when no tab is current; the bar gets `hidden` from `useHideOnScroll()`. More is `aria-current="page"` when a More page is open (as today).

- [ ] **Step 6: Top bar.** In `Shell.tsx`: the sidebar holds the brand, `SidebarLinks` and a foot (sources count link, the Paper note, sign out); the sidebar no longer holds `FindTicker`. The `.statusbar` holds the brand (phone only), one `FindTicker` for every width (placeholder `Search any stock…`), `RefreshPrices`, `RunsPill` (desktop), `ThemeToggle`. The two Paper pills leave the top bar. In `FindTicker`, add an optional `autoFocus` prop and a document `keydown` listener (desktop only) that focuses the search on `/` unless the focus is already in a field. Keep its accessible name `Find a symbol`, which the e2e tests use.

- [ ] **Step 7: Update the e2e tests.**
  - `navigation.spec.ts`: on `/`, the sidebar marks Today current; phone tabs are `toHaveText(['Today', 'Portfolio', 'Day trade'])` as links plus the Search and More buttons; the More dialog lists Picks, Invest, Watchlist, Sources and Settings. Add `/` (heading `Today`) and `/portfolio` (heading `My Portfolio`) to the "no page is wider than the screen" list. Add: the Search button opens a dialog named `Search` holding the `Find a symbol` combobox.
  - Every spec that opens `/` to test Portfolio content (holdings, value, trades, import, live prices, alerts on holdings) opens `/portfolio` instead; `monitor.spec.ts` and `shell.spec.ts` keep `/`. Find them with `grep -n "goto('/')" e2e/*.ts` and read each test.

- [ ] **Step 8: Verify** — `npx vitest run`, `npm run typecheck`, `npm run lint`, `npx playwright test` all pass.

- [ ] **Step 9: Commit** — `git add -A web/app web/components/shell web/lib/scroll.ts web/lib/scroll.test.ts web/e2e`, then `git commit -m "feat(web): Today at /, Portfolio at /portfolio, glass sidebar, tab bar and top-bar search"`.

### Task 4: Recent searches

**Files:**
- Create: `web/lib/recent.ts`, `web/components/ticker/RememberVisit.tsx`
- Modify: `web/components/shell/Navigation.tsx` (the Search sheet), `web/app/(app)/ticker/[symbol]/page.tsx`
- Test: `web/lib/recent.test.ts`, `web/e2e/navigation.spec.ts`

**Interfaces:**
- Produces: `RECENT_KEY = 'advisor.recent-symbols'`; `pushRecent(list: readonly string[], symbol: string, max?: number): string[]` (default max 8); `readRecent(storage: Pick<Storage, 'getItem'> | null): string[]`; `writeRecent(storage: Pick<Storage, 'setItem'> | null, list: readonly string[]): void`.

- [ ] **Step 1: Write the failing test** `web/lib/recent.test.ts`

```ts
const store = (value: string | null) => ({ getItem: () => value })
it('puts the newest first, without repeats, at most 8', () => {
  expect(pushRecent(['AAPL', 'RY.TO'], 'RY.TO')).toEqual(['RY.TO', 'AAPL'])
  expect(pushRecent(['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H'], 'NVDA')).toHaveLength(8)
})
it('reads nothing when storage is missing, throws, or holds junk (Review Focus 4)', () => {
  expect(readRecent(null)).toEqual([])
  expect(readRecent({ getItem: () => { throw new Error('blocked') } })).toEqual([])
  expect(readRecent(store('not json'))).toEqual([])
  expect(readRecent(store('[1, "<script>", "SHOP.TO"]'))).toEqual(['SHOP.TO'])
})
it('never throws on write', () => {
  expect(() => writeRecent({ setItem: () => { throw new Error('quota') } }, ['AAPL'])).not.toThrow()
})
```

- [ ] **Step 2: Run it to see it fail** — `npx vitest run lib/recent.test.ts` → FAIL.

- [ ] **Step 3: Implement `web/lib/recent.ts`** — `readRecent` keeps only strings that pass `isValidSymbol(s, 'stock') || isValidSymbol(s, 'crypto')` (from `lib/symbols`), at most 8. Run the test → PASS.

- [ ] **Step 4: Wire it.** `RememberVisit({ symbol }: { symbol: string })` (`'use client'`, renders nothing) writes `pushRecent(readRecent(localStorage), symbol)` on mount, guarding `typeof window`; render it on the ticker page. The Search sheet shows a `Recent` label and the recent symbols as links to `tickerHref(...)` under the search field, read when the sheet opens; nothing when empty.

- [ ] **Step 5: e2e** — in `navigation.spec.ts` (phone): open `/ticker/RY.TO`, then the Search tab; the dialog has a link named `RY.TO`.

- [ ] **Step 6: Verify and commit** — `npx vitest run`, `npm run typecheck`, `npm run lint`, `npx playwright test e2e/navigation.spec.ts` pass; `git add web/lib/recent.ts web/lib/recent.test.ts web/components web/app web/e2e`, then `git commit -m "feat(web): recent searches in the phone Search sheet"`.

### Task 5: Today

**Files:**
- Create: `web/lib/today.ts`, `web/lib/data/best-chance.ts`, `web/components/today/PortfolioSummary.tsx`, `AttentionCard.tsx`, `DaytradeTop.tsx`, `PicksStatus.tsx`, `web/components/Sparkline.tsx`
- Modify: `web/app/(app)/page.tsx`
- Test: `web/lib/today.test.ts`, `web/components/today/PortfolioSummary.test.tsx`, `AttentionCard.test.tsx`, `PicksStatus.test.tsx`, `web/e2e/today.spec.ts` (create)

**Interfaces:**
- Consumes: `portfolioView` (`HoldingView`, `Warning`), `loadHoldingActions`, `loadMonitorFeed`, `loadDaytrade(supabase, day)`, `isLive(day, now)`, `nyTime(now)`, `skillSignals`/the after-costs ranking already used by the Day trade page, `loadPicks(supabase)`, `lastPublishedRun(supabase)`.
- Produces:
  - `PICK_P_FLOOR = 0.58` (reuse an existing constant if `grep -rn "0\.58" web/lib` finds one).
  - `needsAttention(holdings: readonly HoldingView[]): { items: HoldingView[]; onHold: number }` — items are holdings whose action is `sell`, `trim` or `add`, or `hold` with `review`; ordered sell, trim, review, add; `onHold` counts the rest.
  - `todayLine(day: DayRow | null, now: string): string` — e.g. `Saturday, Nov 21 · markets closed` / `Monday, Nov 23 · market open`, the date in New York time, open only when `isLive(day, now)`.
  - `type BestChance = { benchmark: 'SPY' | 'XIU.TO'; pBeat: number }`; `loadBestChances(supabase: Supabase, runId: number): Promise<BestChance[]>` — per benchmark, the run's highest non-null `p_beat` for `asset_type = 'stock'` (one `order('p_beat', { ascending: false }).limit(1)` query per benchmark).
  - `bestChanceLine(chances: readonly BestChance[]): string | null` — `US 52.7% vs SPY · TSX 55.1% vs XIU.TO` (one decimal, US first), null when empty.
  - `Sparkline({ values, compare, label }: { values: number[]; compare?: number[]; label: string })` — an SVG with class `draw` and a `path.line`.

- [ ] **Step 1: Write the failing tests** `web/lib/today.test.ts`

```ts
it('lists what needs action, in order, and counts the rest (Review Focus 1)', () => {
  const r = needsAttention([holding('add'), holding('hold'), holding('sell'), holding('hold', true), holding('trim')])
  expect(r.items.map((h) => h.action?.action + (h.action?.review ? '+review' : ''))).toEqual(['sell', 'trim', 'hold+review', 'add'])
  expect(r.onHold).toBe(1)
  expect(needsAttention([])).toEqual({ items: [], onHold: 0 })
})
it('says markets closed without a live session (Review Focus 3)', () => {
  expect(todayLine(null, '2026-11-21T15:00:00Z')).toBe('Saturday, Nov 21 · markets closed')
})
it('formats the best chance per market, US first', () => {
  expect(bestChanceLine([{ benchmark: 'XIU.TO', pBeat: 0.5512 }, { benchmark: 'SPY', pBeat: 0.527 }])).toBe('US 52.7% vs SPY · TSX 55.1% vs XIU.TO')
  expect(bestChanceLine([])).toBeNull()
})
```

`holding(kind, review?)` is a local factory returning a minimal `HoldingView` with that action. Component tests (`renderToStaticMarkup`):
- `PortfolioSummary` with zero totals and no holdings renders `C$0.00` and `No holdings yet`, and no `svg` (Review Focus 1).
- `AttentionCard` with no items renders `Nothing needs your attention`; with warnings renders the warning text.
- `PicksStatus` with `run: null` renders `No run yet` (Review Focus 2); with zero picks and a best-chance line renders `None today`, the line, `needs 58%` and `Nothing has enough evidence to buy`; with picks renders the count per market and no best-chance line.

- [ ] **Step 2: Run them to see them fail** — `npx vitest run lib/today.test.ts components/today` → FAIL.

- [ ] **Step 3: Implement** `lib/today.ts`, `lib/data/best-chance.ts`, `Sparkline`, and the four cards, following `today_1.html`:
  - `PortfolioSummary` (a `.card.hero.rim.lift` link to `/portfolio`): total value (`.big .num`), today's change, all time, vs SPY 1Y, and the `Sparkline` of the 3M series ValueCard charts against SPY. No cash figure. An empty portfolio shows C$0.00 and "No holdings yet" without a chart.
  - `AttentionCard`: rows of chip, symbol, name/headline reason, P/L; then `N more on Hold ›` linking to `/portfolio`; then the warnings.
  - `DaytradeTop`: the Day trade page's day (`nyTime(now).day`) and its after-costs top 3; the first shows entry, target and stop tiles; each shows the status chip, the same verdict line `SignalCard` shows, and net history R; with no session: `No session today`.
  - `PicksStatus`: as in the tests, with buttons `Why none?` → `/picks` and `Watchlist verdicts` → `/watchlist`.

- [ ] **Step 4: Compose** `app/(app)/page.tsx`: `.page-head` with `todayLine` and `<h1>Today</h1>`, `PortfolioSummary`, then a two-column `.today-grid` (desktop `minmax(0,1.12fr) minmax(0,1fr)`): left `AttentionCard`, `MonitorCard`; right `DaytradeTop`, `PicksStatus`. `MonitorCard` shows the latest 3 and a `Show all` that expands in place (ruling: Portfolio has no news card any more, so "all" opens in place).

- [ ] **Step 5: Run the tests to see them pass** — same command → PASS.

- [ ] **Step 6: e2e** `web/e2e/today.spec.ts`, seeding with the helpers in `e2e/db.ts` as `monitor.spec.ts` does: a Sell holding shows under "Needs your attention" with the Sell chip; with no run, the Picks card says `No run yet`; with no day-trade row, the Day trade card says `No session today` and the header says `markets closed`.

- [ ] **Step 7: Verify and commit** — `npx vitest run`, `npm run typecheck`, `npm run lint`, `npx playwright test` pass; `git add web/lib web/components web/app web/e2e`, then `git commit -m "feat(web): the Today home page"`.

### Task 6: Portfolio layout

**Files:**
- Modify: `web/app/(app)/portfolio/page.tsx`, `web/components/portfolio/ValueCard.tsx`, `Cards.tsx`, `web/app/styles/pages.css`
- Test: `web/e2e/portfolio.spec.ts`

- [ ] **Step 1: Recompose** per `portfolio_2.html`: `.page-head` (accounts line, `<h1>My Portfolio</h1>`, `TradeButtons` with Buy as `btn-primary`, Sell and Import as `btn-secondary`); `ValueCard` as the hero (`.hero`, the `.seg` period control, the legend You / SPY / XIU.TO); a `.portfolio-grid` (desktop `minmax(0,1fr) 330px`): left the holdings card (the `ActionsCard` holdings with action chip, shares, value CAD, P/L, weight bar) then `TradeList`; right `BreakdownCard` and `WarningsCard`. Keep `id="holdings"` and the table rows the e2e tests count.
- [ ] **Step 2: Weight bar** — a `.weight` bar per row; it is orange (`--trim`) when the holding's action is Trim (ruling: Trim already means "too big", so no new cap source is needed).
- [ ] **Step 3: Phone** — below 760 px the holdings table becomes compact rows (CSS only, same DOM), the Shares column hides below 1360 px.
- [ ] **Step 4: e2e** — `portfolio.spec.ts` passes against the new layout; add: at 390 px `#holdings` has no horizontal scroll of the page.
- [ ] **Step 5: Verify and commit** — full suite passes; `git commit -m "feat(web): Portfolio layout with the value hero, holdings table and breakdown"` (after `git add` of the touched files).

### Task 7: Day trade layout

**Files:**
- Modify: `web/app/(app)/daytrade/page.tsx`, `web/components/daytrade/SignalCard.tsx`, `SignalTable.tsx`, `TrackRecord.tsx`, `web/app/styles/pages.css`
- Test: `web/e2e/daytrade.spec.ts`, `web/components/daytrade/SignalCard.test.tsx` (create)

**Interfaces:**
- Produces: `SignalCard` gains `compact?: boolean` (the skill's top 3: entry → target / stop, distance above the range high, net R, verdict; no tiles).

- [ ] **Step 1: Write the failing test** — `SignalCard.test.tsx`: the full card renders `Entry`, `Target`, `Stop`, the cost in R and the verdict line; `compact` renders the verdict but not `Target` as a tile label.
- [ ] **Step 2: Run it to see it fail**, implement `compact`, run it to see it pass (`npx vitest run components/daytrade`).
- [ ] **Step 3: Recompose** per `daytrade_1.html`: the header with a live pill (`.dot.live`) only when `isLive(day, now)`; "Top 3 after your costs" as a 3-column grid (stacked on a phone); "The skill's top 3" as compact cards; `SignalTable` inside a collapsed `<details>` titled `All signals`; `TrackRecord` and the Notes card side by side on desktop. A status chip gets `flip` when its status differs from the previous render (keyed by status).
- [ ] **Step 4: e2e and commit** — `daytrade.spec.ts` passes (update selectors for the `<details>` table); full suite passes; `git commit -m "feat(web): Day trade layout with side-by-side top 3"`.

### Task 8: Picks layout

**Files:**
- Modify: `web/app/(app)/picks/page.tsx`, `web/components/picks/MarketPicks.tsx`, `PickCard.tsx`, `web/app/styles/pages.css`
- Test: `web/components/picks/MarketPicks.test.tsx` (create), existing `PickCard.test.tsx`

**Interfaces:**
- Consumes: `loadBestChances`, `bestChanceLine`, `PICK_P_FLOOR` (Task 5).

- [ ] **Step 1: Write the failing test** — the empty state with a best-chance line renders `No picks today`, the line, `needs 58%`, `Nothing has enough evidence to buy` and the `Why?` block text `a pick needs a chance of at least 58%`; with no run it renders `No run yet` (Review Focus 2). `PickCard.test.tsx` keeps asserting `No chance of beating SPY is shown`.
- [ ] **Step 2: Run it to see it fail**, implement, run to see it pass.
- [ ] **Step 3: Recompose** per `picks_2.html` (its first half is the real empty state; its second half is the pick-card layout): the `.empty` card with `.halo`, the three stat tiles (best chance, 58%, 30 backtest picks) and the explanation; the US | TSX `.seg`; pick cards in a 3-column grid, restyled, with the same content `PickCard` has today (Chosen by, the no-chance note, range bar, entry, stop, exit by, backtest record, cost line, Bought).
- [ ] **Step 4: Verify and commit** — `npx playwright test e2e/picks.spec.ts` and the full suite pass; `git commit -m "feat(web): Picks empty state with the run's best chance, glass pick cards"`.

### Task 9: Invest layout

**Files:**
- Modify: `web/app/(app)/invest/page.tsx`, `web/components/invest/SplitForm.tsx`, `web/components/OrderGuide.tsx`, `web/app/styles/pages.css`
- Test: `web/e2e/invest.spec.ts`

- [ ] **Step 1: Recompose** per `invest_1.html`: an `.invest-grid` (desktop `minmax(0,0.9fr) minmax(0,1.3fr)`, the form card `position: sticky; top: 76px`), stacked on a phone; each result line with a weight bar, the existing "likely a to b vs benchmark" line and its `OrderGuide` in a `<details>` (open by default for the first line); the no-picks warning and the order disclaimer stay.
- [ ] **Step 2: Verify and commit** — `invest.spec.ts` (update selectors for `<details>`) and the full suite pass; `git commit -m "feat(web): Invest two-column layout"`.

### Task 10: Watchlist outlook and layout

**Files:**
- Create: `web/lib/outlook.ts`, `web/lib/data/watch-outlook.ts`
- Modify: `web/app/(app)/watchlist/page.tsx`, `web/components/watchlist/Watchlist.tsx`, `web/app/styles/pages.css`
- Test: `web/lib/outlook.test.ts`, `web/components/watchlist/Watchlist.test.tsx` (create), `web/e2e/watchlist-settings.spec.ts`

**Interfaces:**
- Consumes: `ForecastHorizon` from `lib/data/ticker.ts`; `RangeBar` from `components/picks/RangeBar.tsx`.
- Produces: `nearestHorizon(horizons: readonly number[], target?: number): number | null` (default 21, ties to the shorter); `outlookFor(rows: readonly ForecastHorizon[], horizon: number | null): ForecastHorizon | null` (the row at `horizon`, else at `nearestHorizon`); `edgeWords(verdict: 'buy' | 'hold' | 'avoid' | null): string` → `Buy` / `Avoid` / `No clear edge`; `loadWatchOutlooks(supabase: Supabase, runId: number, items: readonly AssetRef[]): Promise<Map<string, { benchmark: string; horizons: ForecastHorizon[] }>>` keyed by `assetKey`, reading `predictions` (`symbol, asset_type, horizon_days, q10, q50, q90, p_beat, benchmark`) for the run with `.in('symbol', symbols)`; `WatchRow` gains `outlook: { benchmark: string; horizon: number; pBeat: number; q10: number; q50: number; q90: number } | null`.

- [ ] **Step 1: Write the failing tests** `web/lib/outlook.test.ts`

```ts
it('picks 21, else the closest, ties to the shorter', () => {
  expect(nearestHorizon([5, 10, 20, 21, 63])).toBe(21)
  expect(nearestHorizon([7, 14, 30, 90])).toBe(14)
  expect(nearestHorizon([18, 24])).toBe(18)
  expect(nearestHorizon([])).toBeNull()
})
it('uses the verdict horizon when the run has it', () => {
  expect(outlookFor([h(21), h(63)], 63)?.horizon).toBe(63)
  expect(outlookFor([h(21), h(63)], 10)?.horizon).toBe(21)
})
it('words the edge plainly', () => {
  expect(edgeWords('hold')).toBe('No clear edge')
  expect(edgeWords(null)).toBe('No clear edge')
})
```

`Watchlist.test.tsx`: a hold row with an outlook renders `No clear edge`, `54% to beat XIU.TO over 21 days` and a range bar; a held row renders its Portfolio action and no `% to beat`.

- [ ] **Step 2: Run them to see them fail**, implement, run to see them pass (`npx vitest run lib/outlook.test.ts components/watchlist`).
- [ ] **Step 3: Load and lay out.** The page reads `loadWatchOutlooks` for the latest published run (the run `loadVerdicts` uses) and fills `outlook` for rows that are not held, at the verdict's `details.horizon_days` when present. Rows per `watchlist_2.html`: symbol and name, price and today's move, the verdict chip (`edgeWords`) with `{p}% to beat {benchmark} over {n} days` for every verdict, the range bar, the order guide in a `<details>`. A row with no outlook (coin not forecast, new symbol) shows its verdict as today.
- [ ] **Step 4: Verify and commit** — `watchlist-settings.spec.ts` and the full suite pass; `git commit -m "feat(web): Watchlist rows with the chance, horizon and likely range"`.

### Task 11: Stock page layout

**Files:**
- Modify: `web/app/(app)/ticker/[symbol]/page.tsx`, `web/components/ticker/AlertsCard.tsx`, `EarningsCard.tsx`, `web/components/portfolio/ExitPlan.tsx` (layout only), `web/app/styles/pages.css`
- Test: `web/e2e/ticker.spec.ts`

**Interfaces:**
- Consumes: `edgeWords` (Task 10), `TickerForecast`, `ExitPlan`.

- [ ] **Step 1: Recompose** per `ticker_2.html`: desktop `.ticker-grid` (`minmax(0,1.45fr) minmax(0,1fr)`): left the header card (symbol, name, exchange · currency, price with `data-price`, today's move) with the price chart and its forecast range and 1W–1Y `.seg`, then News and filings; right the Outlook card (`edgeWords` headline, `{p}% chance to beat the market over {n} days`, the 5/21/63 `.seg` limited to the usable horizons, `A coin flip is 50%. Picks need 58%.`, the likely range), Your position (only when held: shares, value, average cost, P/L, action chip, `ExitPlan` summary with its existing sell-at rules), Earnings, then Watch / Alerts / Sources. Phone order: header with a one-line outlook link, chart, Outlook, Your position, News, Earnings, actions. Alerts open in a `Drawer` titled `Alerts`.
- [ ] **Step 2: Verify and commit** — `ticker.spec.ts` (update for the Alerts drawer) and the full suite pass; `git commit -m "feat(web): stock page layout around outlook, position, news and earnings"`.

### Task 12: Motion behaviours

**Files:**
- Modify: `web/components/LineChart.tsx`, `web/components/shell/RefreshPrices.tsx`, `web/components/shell/Shell.tsx`, `web/app/styles/ledger.css`, `web/next.config.*` (only if Step 3 finds view transitions supported)
- Create: `web/components/shell/RimLight.tsx`
- Test: `web/e2e/shell.spec.ts`
- Read first: the Next 16 docs on view transitions in `web/node_modules/next/dist/docs/`.

- [ ] **Step 1: Chart draw** — `LineChart` adds class `draw` to its SVG and sets `--len` on each line path from `getTotalLength()` after mount; forecast ranges carry `cone`.
- [ ] **Step 2: Price ticks and rim light** — after a successful Refresh, `RefreshPrices` adds `tick-up` / `tick-down` once to elements with `data-price="up" | "down"`. `RimLight` (`'use client'`, rendered once in `Shell`, desktop pointers only) sets `--mx`/`--my` on the hovered `.card.rim` through one delegated `pointermove` listener.
- [ ] **Step 3: Route crossfade** — if the docs show a supported way in this Next version, enable it and add a 220 ms `::view-transition-old/new(root)` crossfade; otherwise skip and note it in the commit message.
- [ ] **Step 4: e2e** — in `shell.spec.ts`, with `page.emulateMedia({ reducedMotion: 'reduce' })`, the aurora's `::before` has `animation-name` `none` (`getComputedStyle(el, '::before')`); with reduced transparency emulated where Playwright supports it, `.card` has no `backdrop-filter`.
- [ ] **Step 5: Verify and commit** — full suite passes; `git commit -m "feat(web): chart draw, price ticks, rim light and route crossfade"`.

### Task 13: Sources, Settings, Login and the phone pass

**Files:**
- Modify: `web/app/(app)/sources/page.tsx`, `web/app/(app)/settings/page.tsx`, `web/app/login/page.tsx`, `web/app/styles/pages.css` (look only; no layout change)

- [ ] **Step 1: Restyle check** — these pages use the glass cards, buttons and fields with no layout change; fix any surface that still looks like Ledger (solid white cards, square inputs).
- [ ] **Step 2: Contrast** — check text on glass at WCAG AA in both modes over the brightest aurora spot on `/`, `/portfolio`, `/daytrade` (Edge DevTools contrast picker); raise `--glass-bg` alpha if any body text fails.
- [ ] **Step 3: Full verification** — `npx vitest run`, `npm run typecheck`, `npm run lint`, `npm run build`, `npx playwright test` all pass.
- [ ] **Step 4: Android** — `npm run android:sync`; the owner opens the app on their phone and checks the tab bar, the glass, scrolling and the Search and More sheets. Record what they report in the commit message or a follow-up.
- [ ] **Step 5: Commit** — `git commit -m "feat(web): glass look for Sources, Settings and Login; contrast pass"`.
