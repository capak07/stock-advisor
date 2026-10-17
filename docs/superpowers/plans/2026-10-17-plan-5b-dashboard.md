# Plan 5b: Dashboard Foundation, My Portfolio, Watchlist and Settings — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The owner signs in to a Next.js dashboard on Vercel and sees My Portfolio in CAD, with returns against XIU.TO and SPY, the tax warnings that need no model, buys and sells, the watchlist and the settings.

**Architecture:**
- `web/` is a Next.js 16 App Router app.
  - Pages are server components that read Supabase as the signed-in owner through `@supabase/ssr`.
  - Forms post to server actions.
  - Row-level security (spec §8) decides what the owner can read and write. Supabase is only ever called from the server.
- The portfolio maths (average cost, CAD values, time-weighted returns, TFSA and superficial-loss warnings) is plain TypeScript in `web/lib/`, unit-tested with Vitest.
- The look is the approved "Ledger" design from `.superdesign/design_iterations/`. Its CSS is ported verbatim, and its JavaScript widgets (tabs, drawers, line chart) are ported as React components.
- Browser tests (Playwright) run against the local Supabase stack, which `supabase/config.toml` defines. The stack is Postgres, Auth and PostgREST in Docker, with every migration applied.

**Tech Stack:** Next.js 16.3.8, React 19.2.8, TypeScript 5.9.3, Tailwind CSS 4.3.3 (layout utilities only), `@supabase/ssr` 0.12.7, `@supabase/supabase-js` 2.117.2, zod 4.6.5, lucide-react 1.50.0, Vitest 5.0.3, Playwright 1.63.0, Supabase CLI 2.119.0.

**Spec:** `docs/superpowers/specs/2026-10-09-stock-advisor-design.md` (rev 2; §7 My Portfolio, §8 Data Model, §9 Dashboard). Also read `docs/superpowers/deferred.md`, "Plans 4 and 5".

**Prototype:** every file below was built and tested on branch `plan-5b-proto` (2026-10-17): 80 unit tests, 25 browser tests, lint and typecheck clean. Screenshots were compared with the mockups at 1440 px and 390 px, light and dark. The plan transcribes those files.

## Global Constraints

- **Versions are exact** and at least two weeks old on 2026-10-17. They are listed in `web/package.json` (Task 1). Node 24.
- **Next.js 16 changed.** Middleware is `proxy.ts`, and `cookies()` and `params` are async. `web/AGENTS.md` says to read `node_modules/next/dist/docs/` before writing Next code that differs from this plan.
- **The disclaimer text is fixed** (spec §9): `Not financial or tax advice. Forecasts are probabilistic and can be wrong.`
- **Values are shown in CAD.** USD positions convert at the latest Bank of Canada rate (spec §7.4).
- **Cost basis is average cost** (adjusted cost base) per account and asset, in CAD (spec §7.1).
- **One owner, no sign-ups.** Only the owner named in `app_config` sees data. The dashboard writes only `watchlist`, `lots`, `sells` and the `settings` row (spec §3, design rule 1; spec §8).
- **Supabase is called from the server only.** The env vars are `SUPABASE_URL` and `SUPABASE_PUBLISHABLE_KEY`, never `NEXT_PUBLIC_*`.
- **Design:** the Ledger mockups. No blue or indigo; Geist and Geist Mono; light and dark; phone width with no horizontal scroll.
- **Test accounts** exist only on the local stack: `owner@example.com` and `visitor@example.com`. Never put a real email in code, tests or docs.
- **Where commands run:**
  - Web commands run from `web/` on the host. The pipeline's Docker-only rule exists because of Python's DLLs.
  - Browser tests need Docker Desktop running and `npm run db:start`. On Windows, Playwright uses the installed Microsoft Edge.
- **Every commit message ends with** the `Co-Authored-By:` trailer.

## Review Focus

1. **A USD buy recorded before spec rev 2 has no `fx_rate_cad`.** It must be costed at the Bank of Canada rate of its day, not dropped. Covered by Task 2, `tradeCad` "uses the Bank of Canada rate of the day when a USD trade has none".
2. **Someone other than the owner signs in.** They see "This account isn't the owner", no data, and the server logs no error (pages skip loading when the layout shows the notice). Covered by Task 4, `auth.spec.ts` "someone who is not the owner sees no data".
3. **The server rejects a buy.** What the owner typed must stay in the form. React resets uncontrolled fields after every action, so every field is controlled. Covered by Task 6, `trades.spec.ts` "mistakes are named and what was typed stays".
4. **A large buy into a small position, or a coin bought on a Saturday.** Neither may distort the returns chart. Covered by Task 3, `returns.test.ts` "doesn't let a big buy into a small position inflate the day's return" and "counts a weekend coin buy on the next trading day…".
5. **A phone.** Every page must fit 390 px without horizontal scrolling. Holdings stack into rows, and Settings sits under More. Covered by Task 7, `navigation.spec.ts`.

## Files

| File | Task | What it is |
|---|---|---|
| `web/package.json`, `tsconfig.json`, `next.config.ts`, `postcss.config.mjs`, `eslint.config.mjs`, `vitest.config.mts`, `.gitignore`, `.env.example`, `AGENTS.md`, `CLAUDE.md` | 1 | The app's configuration; `package-lock.json` comes from `npm install` |
| `web/app/layout.tsx`, `app/globals.css`, `app/icon.svg`, `app/styles/{theme,ledger,pages}.css` | 1 | Root layout and the Ledger CSS (`theme_1.css`, `dashboard_1.css` and the pages' `<style>` blocks) |
| `web/lib/{theme,copy,dates,format,symbols}.ts` + tests | 1 | Theme script, fixed copy, dates, number formats, symbol rules |
| `supabase/config.toml`, `supabase/.gitignore` | 1 | The local Supabase stack |
| `web/lib/portfolio/{types,lookup,ledger,valuation}.ts` + tests | 2 | Average cost, rates and closes by day, CAD values |
| `web/lib/portfolio/{returns,warnings,view}.ts` + tests | 3 | Returns against the benchmarks, TFSA and superficial-loss warnings, the page's view model |
| `web/lib/{supabase/server,auth,runs}.ts`, `lib/data/{fetch,runs}.ts`, `proxy.ts` | 4 | Server client, owner check, run labels, session proxy |
| `web/app/login/*`, `app/(app)/{layout,actions,page}.tsx`, `components/{ThemeToggle,Toast,Drawer}.tsx`, `components/shell/*` | 4 | Sign-in, the owner gate and the app frame |
| `web/playwright.config.ts`, `e2e/{stack,db,auth.setup}.ts`, `e2e/{auth,shell}.spec.ts` | 4 | Browser tests and their seeding helpers |
| `web/lib/chart.ts`, `lib/data/{settings,symbols,portfolio}.ts`, `components/{Tabs,TweenNumber,LineChart}.tsx`, `components/portfolio/{ValueCard,Cards}.tsx`, `e2e/portfolio.spec.ts` | 5 | The portfolio page |
| `web/lib/trade-form.ts`, `app/(app)/trades.ts`, `components/portfolio/TradeForms.tsx`, `e2e/trades.spec.ts` | 6 | Buys and sells |
| `web/lib/{watch-form,settings-form}.ts`, `lib/data/watchlist.ts`, `app/(app)/{watchlist,settings}/*`, `components/{watchlist,settings}/*`, `e2e/{watchlist-settings,navigation}.spec.ts` | 7 | Watchlist and Settings |
| `.github/workflows/ci.yml`, `web/README.md`, `README.md`, spec, `deferred.md` | 8 | CI job, docs |

---

### Task 1: Scaffold the dashboard, the Ledger theme and the local Supabase stack

**Files:**
- Create: `web/package.json`, `web/tsconfig.json`, `web/next.config.ts`, `web/postcss.config.mjs`, `web/eslint.config.mjs`, `web/vitest.config.mts`, `web/.gitignore`, `web/.env.example`, `web/AGENTS.md`, `web/CLAUDE.md`
- Create: `web/app/layout.tsx`, `web/app/globals.css`, `web/app/icon.svg`, `web/app/styles/theme.css`, `web/app/styles/ledger.css`, `web/app/styles/pages.css`
- Create: `web/lib/theme.ts`, `web/lib/copy.ts`, `web/lib/dates.ts`, `web/lib/format.ts`, `web/lib/symbols.ts`
- Test: `web/lib/format.test.ts`, `web/lib/symbols.test.ts`
- Create: `supabase/config.toml`, `supabase/.gitignore`

**Interfaces:**
- Produces:
  - `lib/dates.ts`: `addDays(day, n)`, `daysBetween(from, to)`, `todayInToronto(now?)`, `shortDay(day)` ("Oct 16"), `longDay(day)` ("Oct 16, 2026"). Days are ISO strings.
  - `lib/format.ts`: `fmtPct(v, digits?)`, `fmtMoney(v, {prefix, digits, signed}?)`, `fmtAmount(v, {digits, signed}?)`, `fmtPrice(v, currency)`, `fmtQty(v)`. Each uses a real minus sign.
  - `lib/symbols.ts`: `US_STOCK`, `TSX_STOCK`, `COIN` (the database's CHECK formats), `normalizeSymbol(raw)`, `isValidSymbol(symbol, assetType)`, `marketOf(symbol)`, `tradeCurrency(assetType, symbol)`.
  - `lib/theme.ts`: `THEME_SCRIPT`, `THEME_KEY`, `savedTheme()`, `applyTheme(choice)`.
  - `lib/copy.ts`: `DISCLAIMER`, `CREDITS`.
  - `npm` scripts: `test`, `e2e`, `lint`, `typecheck`, `build`, and `db:start`, `db:stop`, `db:status`, `db:reset` (the local stack).

- [ ] **Step 1: Write the configuration**

`web/package.json`:

```json
{
  "name": "web",
  "version": "0.1.0",
  "private": true,
  "scripts": {
    "dev": "next dev",
    "build": "next build",
    "start": "next start",
    "lint": "eslint",
    "typecheck": "next typegen && tsc --noEmit",
    "test": "vitest run",
    "e2e": "playwright test",
    "db:start": "supabase start --workdir .. -x realtime,storage-api,imgproxy,mailpit,postgres-meta,studio,edge-runtime,logflare,vector,supavisor",
    "db:stop": "supabase stop --workdir ..",
    "db:status": "supabase status --workdir ..",
    "db:reset": "supabase db reset --workdir .."
  },
  "dependencies": {
    "@supabase/ssr": "0.12.7",
    "@supabase/supabase-js": "2.117.2",
    "lucide-react": "1.50.0",
    "next": "16.3.8",
    "react": "19.2.8",
    "react-dom": "19.2.8",
    "server-only": "0.0.1",
    "zod": "4.6.5"
  },
  "devDependencies": {
    "@playwright/test": "1.63.0",
    "@tailwindcss/postcss": "4.3.3",
    "@types/node": "24.19.1",
    "@types/react": "19.2.18",
    "@types/react-dom": "19.2.7",
    "eslint": "9.39.5",
    "eslint-config-next": "16.3.8",
    "postgres": "3.4.9",
    "supabase": "2.119.0",
    "tailwindcss": "4.3.3",
    "typescript": "5.9.3",
    "vitest": "5.0.3"
  }
}
```

`web/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2017",
    "lib": ["dom", "dom.iterable", "esnext"],
    "allowJs": true,
    "skipLibCheck": true,
    "strict": true,
    "noEmit": true,
    "esModuleInterop": true,
    "module": "esnext",
    "moduleResolution": "bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "jsx": "react-jsx",
    "incremental": true,
    "plugins": [
      {
        "name": "next"
      }
    ],
    "paths": {
      "@/*": ["./*"]
    }
  },
  "include": [
    "next-env.d.ts",
    "**/*.ts",
    "**/*.tsx",
    ".next/types/**/*.ts",
    ".next/dev/types/**/*.ts",
    "**/*.mts"
  ],
  "exclude": ["node_modules"]
}
```

`web/next.config.ts`:

```ts
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
};

export default nextConfig;
```

`web/postcss.config.mjs`:

```js
const config = {
  plugins: {
    "@tailwindcss/postcss": {},
  },
};

export default config;
```

`web/eslint.config.mjs`:

```js
import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
  ]),
]);

export default eslintConfig;
```

`web/vitest.config.mts`:

```ts
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vitest/config'

// Unit tests cover the pure logic in lib/. The browser tests in e2e/ run with Playwright.
export default defineConfig({
  resolve: { alias: { '@': fileURLToPath(new URL('.', import.meta.url)) } },
  test: { include: ['lib/**/*.test.ts'], environment: 'node' },
})
```

`web/.gitignore`:

```gitignore
# See https://help.github.com/articles/ignoring-files/ for more about ignoring files.

# dependencies
/node_modules
/.pnp
.pnp.*
.yarn/*
!.yarn/patches
!.yarn/plugins
!.yarn/releases
!.yarn/versions

# testing
/coverage

# next.js
/.next/
/out/

# production
/build

# misc
.DS_Store
*.pem

# debug
npm-debug.log*
yarn-debug.log*
yarn-error.log*
.pnpm-debug.log*

# env files (can opt-in for committing if needed)
.env*
!.env.example

# vercel
.vercel

# typescript
*.tsbuildinfo
next-env.d.ts

# playwright
/test-results/
/playwright-report/
/e2e/.auth/
```

`web/.env.example`:

```bash
# Copy to .env.local for `npm run dev`. Values for the local stack come from `npm run db:status`
# (API URL and Publishable key). On Vercel, use the hosted project's URL and publishable key.
SUPABASE_URL=http://127.0.0.1:54321
SUPABASE_PUBLISHABLE_KEY=
```

`web/AGENTS.md` (what `next dev` writes; committing it keeps the tree clean):

```markdown
<!-- BEGIN:nextjs-agent-rules -->

# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->
```

`web/CLAUDE.md`:

```markdown
@AGENTS.md
```

- [ ] **Step 2: Install**

Run: `cd web && npm install`
Expected: `added 4xx packages`, plus a deprecation warning for `eslint@9.39.5`. It creates `web/package-lock.json`, which is committed. The `supabase` package downloads its CLI binary during install.

- [ ] **Step 3: Write the failing tests**

`web/lib/format.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { addDays, daysBetween, longDay, shortDay, todayInToronto } from './dates'
import { fmtAmount, fmtMoney, fmtPct, fmtPrice, fmtQty } from './format'

describe('formats', () => {
  it('writes percentages with a sign and a real minus', () => {
    expect(fmtPct(6)).toBe('+6.0%')
    expect(fmtPct(-16.14)).toBe('−16.1%')
    expect(fmtPct(-0.04)).toBe('0.0%')
  })

  it('writes money in en-CA with an optional sign', () => {
    expect(fmtMoney(34237.4)).toBe('C$34,237')
    expect(fmtMoney(-405)).toBe('−C$405')
    expect(fmtMoney(1950, { signed: true })).toBe('+C$1,950')
    expect(fmtMoney(-0.2, { signed: true })).toBe('C$0')
    expect(fmtAmount(-405, { signed: true })).toBe('−405')
  })

  it('writes prices in their currency and quantities without trailing zeros', () => {
    expect(fmtPrice(163.4, 'USD')).toBe('US$163.40')
    expect(fmtPrice(0.4321, 'CAD')).toBe('C$0.4321')
    expect(fmtQty(10)).toBe('10')
    expect(fmtQty(0.12345678)).toBe('0.12345678')
  })
})

describe('dates', () => {
  it('shifts and compares ISO days', () => {
    expect(addDays('2026-10-16', 30)).toBe('2026-11-15')
    expect(addDays('2026-03-01', -1)).toBe('2026-02-28')
    expect(daysBetween('2026-09-02', '2026-09-12')).toBe(10)
  })

  it('writes short and long days', () => {
    expect(shortDay('2026-10-16')).toBe('Oct 16')
    expect(longDay('2025-05-12')).toBe('May 12, 2025')
  })

  it("gives today's date in Toronto", () => {
    // 02:30 UTC on Oct 17 is still Oct 16 in Toronto (EDT, UTC−4).
    expect(todayInToronto(new Date('2026-10-17T02:30:00Z'))).toBe('2026-10-16')
  })
})
```

`web/lib/symbols.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { isValidSymbol, marketOf, normalizeSymbol, tradeCurrency } from './symbols'

describe('symbols', () => {
  it("normalizes case, spaces and a dotted TSX class to Yahoo's form", () => {
    expect(normalizeSymbol('  ry.to ')).toBe('RY.TO')
    expect(normalizeSymbol('rci.b.to')).toBe('RCI-B.TO')
    expect(normalizeSymbol('brk.b')).toBe('BRK.B')
  })

  it("accepts the database's formats and nothing else", () => {
    for (const ok of ['AAPL', 'BRK.B', 'RY.TO', 'RCI-B.TO', 'REI-UN.TO']) expect(isValidSymbol(ok, 'stock')).toBe(true)
    for (const bad of ['', 'TOOLONG', 'RY.VN', 'BRK.BB', 'RY-.TO']) expect(isValidSymbol(bad, 'stock')).toBe(false)
    expect(isValidSymbol('BTC', 'crypto')).toBe(true)
    expect(isValidSymbol('1INCH', 'crypto')).toBe(true)
    expect(isValidSymbol('B', 'crypto')).toBe(false)
  })

  it('places a stock in its market and its trade currency', () => {
    expect(marketOf('RY.TO')).toBe('TSX')
    expect(marketOf('BRK.B')).toBe('US')
    expect(tradeCurrency('stock', 'AAPL')).toBe('USD')
    expect(tradeCurrency('stock', 'RY.TO')).toBe('CAD')
    expect(tradeCurrency('crypto', 'BTC')).toBe('CAD')
  })
})
```

- [ ] **Step 4: Run them and see them fail**

Run: `npm test`
Expected: `Test Files  2 failed (2)`, with `Error: Cannot find module './dates'` and `Error: Cannot find module './symbols'`.

- [ ] **Step 5: Write the helpers**

`web/lib/dates.ts`:

```ts
/** Calendar days as ISO strings (`YYYY-MM-DD`), compared as text and shifted in UTC. */

const MS_PER_DAY = 86_400_000

export const addDays = (day: string, days: number): string =>
  new Date(Date.parse(`${day}T00:00:00Z`) + days * MS_PER_DAY).toISOString().slice(0, 10)

export const daysBetween = (from: string, to: string): number =>
  Math.round((Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / MS_PER_DAY)

/** Today in Toronto, where both markets trade. */
export const todayInToronto = (now: Date = new Date()): string =>
  new Intl.DateTimeFormat('en-CA', { timeZone: 'America/Toronto' }).format(now)

/** "Oct 16" */
export const shortDay = (day: string): string =>
  new Date(`${day}T12:00:00Z`).toLocaleDateString('en-CA', { month: 'short', day: 'numeric', timeZone: 'UTC' })

/** "Oct 16, 2026" */
export const longDay = (day: string): string =>
  new Date(`${day}T12:00:00Z`).toLocaleDateString('en-CA', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    timeZone: 'UTC',
  })
```

`web/lib/format.ts`:

```ts
/** Number formats from the Ledger mockups: a real minus sign, and en-CA grouping. */

const MINUS = '−'

/** "+6.0%", "−16.1%", "0.0%" */
export const fmtPct = (value: number, digits = 1): string => {
  const rounded = Number(Math.abs(value).toFixed(digits))
  const sign = rounded === 0 ? '' : value > 0 ? '+' : MINUS
  return `${sign}${rounded.toFixed(digits)}%`
}

const grouped = (value: number, digits: number): string =>
  Math.abs(value).toLocaleString('en-CA', { minimumFractionDigits: digits, maximumFractionDigits: digits })

/** "C$34,237", "−C$405"; `signed` adds "+" to gains. */
export const fmtMoney = (value: number, { prefix = 'C$', digits = 0, signed = false } = {}): string => {
  const text = grouped(value, digits)
  const zero = Number(text.replace(/,/g, '')) === 0
  const sign = zero ? '' : value < 0 ? MINUS : signed ? '+' : ''
  return `${sign}${prefix}${text}`
}

/** A bare amount for table cells: "2,115", "−405", "+937" when signed. */
export const fmtAmount = (value: number, { digits = 0, signed = false } = {}): string =>
  fmtMoney(value, { prefix: '', digits, signed })

/** A price in its own currency: "US$163.40", "C$171.20". */
export const fmtPrice = (value: number, currency: 'CAD' | 'USD'): string =>
  fmtMoney(value, { prefix: currency === 'USD' ? 'US$' : 'C$', digits: value < 1 ? 4 : 2 })

/** Quantities keep up to 8 decimals for coins: "10", "0.5", "1.25". */
export const fmtQty = (value: number): string =>
  value.toLocaleString('en-CA', { maximumFractionDigits: 8 })
```

`web/lib/symbols.ts` imports types from `lib/portfolio/types.ts`, which Task 2 creates. Write that file now, exactly as Task 2 gives it, so this task type-checks. Task 2 then only adds its tests and the other modules.

`web/lib/symbols.ts`:

```ts
import type { AssetType, Currency, Market } from './portfolio/types'

/** The symbol formats the database's CHECK constraints enforce (spec §8). */
export const US_STOCK = /^[A-Z]{1,5}(\.[A-Z])?$/
export const TSX_STOCK = /^[A-Z]{1,5}(-[A-Z]{1,2})?\.TO$/
export const COIN = /^[A-Z0-9]{2,10}$/

/**
 * Upper-case and trim. A TSX class written with a dot (RCI.B.TO) becomes Yahoo's form (RCI-B.TO),
 * which is how the pipeline stores TSX symbols.
 */
export const normalizeSymbol = (raw: string): string => {
  const symbol = raw.trim().toUpperCase()
  const dotted = /^([A-Z]{1,5})\.([A-Z]{1,2})\.TO$/.exec(symbol)
  return dotted ? `${dotted[1]}-${dotted[2]}.TO` : symbol
}

export const isValidSymbol = (symbol: string, assetType: AssetType): boolean =>
  assetType === 'crypto' ? COIN.test(symbol) : US_STOCK.test(symbol) || TSX_STOCK.test(symbol)

export const marketOf = (symbol: string): Market => (symbol.endsWith('.TO') ? 'TSX' : 'US')

/** Wealthsimple trades US stocks in USD and everything else, coins included, in CAD (spec rev 2). */
export const tradeCurrency = (assetType: AssetType, symbol: string): Currency =>
  assetType === 'stock' && marketOf(symbol) === 'US' ? 'USD' : 'CAD'
```

`web/lib/portfolio/types.ts`:

```ts
/** The portfolio's inputs, as the dashboard reads them from Supabase (spec §7, §8). */

export type Account = 'tfsa' | 'rrsp' | 'fhsa' | 'non_registered' | 'crypto'
export type AssetType = 'stock' | 'crypto'
export type Currency = 'CAD' | 'USD'
export type Market = 'US' | 'TSX'

export const ACCOUNTS: readonly Account[] = ['tfsa', 'rrsp', 'fhsa', 'non_registered', 'crypto']
export const ACCOUNT_LABELS: Record<Account, string> = {
  tfsa: 'TFSA',
  rrsp: 'RRSP',
  fhsa: 'FHSA',
  non_registered: 'Non-registered',
  crypto: 'Crypto',
}
/** Accounts whose gains are taxed (spec §7.5); the others are sheltered. */
export const TAXABLE: ReadonlySet<Account> = new Set(['crypto', 'non_registered'])

/** A buy (a `lots` row) or a sell (a `sells` row). Days are ISO dates, `YYYY-MM-DD`. */
export interface Trade {
  side: 'buy' | 'sell'
  account: Account
  symbol: string
  assetType: AssetType
  qty: number
  price: number
  currency: Currency
  /** CAD per USD for a USD trade; null for CAD trades and for USD trades from before spec rev 2. */
  fxRateCad: number | null
  day: string
}

/** One stored daily close (`daily_closes`). */
export interface Close {
  day: string
  close: number
  currency: Currency
}

/** The key an asset's closes are stored under. */
export const assetKey = (assetType: AssetType, symbol: string): string => `${assetType}:${symbol}`

/** A held asset in one account, at average cost (adjusted cost base) in CAD. */
export interface Position {
  account: Account
  symbol: string
  assetType: AssetType
  qty: number
  costCad: number
  /** The day the position last went from nothing held to something held. */
  openedOn: string
}

/** A sell's result at average cost, in CAD. */
export interface Sale {
  account: Account
  symbol: string
  assetType: AssetType
  day: string
  qty: number
  proceedsCad: number
  costCad: number
  gainCad: number
  /** Days since the position was opened. */
  heldDays: number
}
```

`web/lib/theme.ts`:

```ts
/** Light or dark: the owner's choice on this device (localStorage), else the device setting. */

export type ThemeChoice = 'system' | 'light' | 'dark'
export const THEME_KEY = 'ledger-theme'

/** Runs in <head> before first paint, so a dark page never flashes light. */
export const THEME_SCRIPT = `(function(){var t=null;try{t=localStorage.getItem('${THEME_KEY}')}catch(e){}var d=t?t==='dark':matchMedia('(prefers-color-scheme: dark)').matches;document.documentElement.classList.toggle('dark',d)})()`

export function savedTheme(): ThemeChoice {
  try {
    const saved = localStorage.getItem(THEME_KEY)
    return saved === 'light' || saved === 'dark' ? saved : 'system'
  } catch {
    return 'system' // storage blocked
  }
}

export function applyTheme(choice: ThemeChoice): boolean {
  const dark = choice === 'dark' || (choice === 'system' && matchMedia('(prefers-color-scheme: dark)').matches)
  document.documentElement.classList.toggle('dark', dark)
  try {
    if (choice === 'system') localStorage.removeItem(THEME_KEY)
    else localStorage.setItem(THEME_KEY, choice)
  } catch {
    // storage blocked: the choice lasts until the page reloads
  }
  return dark
}
```

`web/lib/copy.ts`:

```ts
/** Text the spec fixes word for word (spec §9). */
export const DISCLAIMER = 'Not financial or tax advice. Forecasts are probabilistic and can be wrong.'

/** Credits for the data these pages show (deferred.md, "Source credits"). Plan 5c adds the rest. */
export const CREDITS = 'Prices from Yahoo Finance and Coinbase. USD/CAD from the Bank of Canada.'
```

- [ ] **Step 6: Run the tests**

Run: `npm test`
Expected: `Test Files  2 passed (2)`, `Tests  9 passed (9)`.

- [ ] **Step 7: Write the root layout and the Ledger CSS**

The three stylesheets are the approved mockups' CSS:
- `theme.css` is `theme_1.css`, with the font stacks pointed at `next/font`'s variables.
- `ledger.css` is `dashboard_1.css` without the mockup-only state switcher. Headings' `margin` lost its `!important`, so their inline margins apply.
- `pages.css` collects the pages' `<style>` blocks. Holdings cells are placed by class, and the watchlist has a `plain` row for before the model.

`web/app/styles/theme.css`:

```css
/* Ledger: the stock-advisor dashboard theme (superdesign step 2, theme_1.css).
 *
 * Ink on warm paper in light mode, graphite in dark mode (class "dark").
 * The interface itself is monochrome. Colour is kept for meaning:
 * gains and losses, the five holding actions, the four risk levels and source status.
 * Numbers use Geist Mono so prices, P/L and percentages line up in columns.
 * No blue or indigo anywhere.
 */
:root {
  --background: oklch(0.9850 0.0030 85);
  --foreground: oklch(0.2100 0.0060 60);
  --card: oklch(1.0000 0 0);
  --card-foreground: oklch(0.2100 0.0060 60);
  --popover: oklch(1.0000 0 0);
  --popover-foreground: oklch(0.2100 0.0060 60);
  --primary: oklch(0.2100 0.0060 60);
  --primary-foreground: oklch(0.9850 0.0030 85);
  --secondary: oklch(0.9550 0.0050 85);
  --secondary-foreground: oklch(0.2100 0.0060 60);
  --muted: oklch(0.9550 0.0050 85);
  --muted-foreground: oklch(0.5000 0.0110 70);
  --accent: oklch(0.9400 0.0070 85);
  --accent-foreground: oklch(0.2100 0.0060 60);
  --destructive: oklch(0.5500 0.1900 27);
  --destructive-foreground: oklch(0.9850 0.0030 85);
  --border: oklch(0.9050 0.0060 85);
  --input: oklch(0.8700 0.0070 85);
  --ring: oklch(0.5000 0.0110 70);

  /* Meaning. Each colour has a strong tone (text, dots, bars) and a soft tone (badge fill). */
  --gain: oklch(0.4950 0.1300 155);
  --gain-soft: oklch(0.9500 0.0400 155);
  --loss: oklch(0.5250 0.1850 27);
  --loss-soft: oklch(0.9500 0.0300 27);
  --attention: oklch(0.5150 0.1100 75);          /* Review, warnings, Paper */
  --attention-soft: oklch(0.9600 0.0500 85);
  --trim: oklch(0.5200 0.1500 48);
  --trim-soft: oklch(0.9500 0.0400 55);
  --hold: oklch(0.5000 0.0110 70);
  --hold-soft: oklch(0.9400 0.0060 85);
  --risk-low: oklch(0.5050 0.1000 165);

  --chart-1: oklch(0.2100 0.0060 60);            /* the portfolio, the price */
  --chart-2: oklch(0.6000 0.1400 50);            /* XIU.TO */
  --chart-3: oklch(0.5500 0.0200 250);           /* SPY */
  --chart-4: oklch(0.5300 0.1400 155);           /* forecast median */
  --chart-5: oklch(0.5300 0.1400 155 / 0.14);    /* forecast cone */

  --sidebar: oklch(0.9700 0.0040 85);
  --sidebar-foreground: oklch(0.2100 0.0060 60);
  --sidebar-primary: oklch(0.2100 0.0060 60);
  --sidebar-primary-foreground: oklch(0.9850 0.0030 85);
  --sidebar-accent: oklch(0.9300 0.0070 85);
  --sidebar-accent-foreground: oklch(0.2100 0.0060 60);
  --sidebar-border: oklch(0.9050 0.0060 85);
  --sidebar-ring: oklch(0.5000 0.0110 70);

  --font-sans: var(--font-geist), 'Geist', ui-sans-serif, system-ui, -apple-system, 'Segoe UI', sans-serif;
  --font-serif: ui-serif, Georgia, Cambria, 'Times New Roman', serif;
  --font-mono: var(--font-geist-mono), 'Geist Mono', ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  --radius: 0.5rem;
  --shadow-2xs: 0 1px 1px 0 hsl(30 10% 15% / 0.04);
  --shadow-xs: 0 1px 2px 0 hsl(30 10% 15% / 0.05);
  --shadow-sm: 0 1px 2px 0 hsl(30 10% 15% / 0.06), 0 1px 3px -1px hsl(30 10% 15% / 0.06);
  --shadow: 0 1px 3px 0 hsl(30 10% 15% / 0.07), 0 2px 4px -2px hsl(30 10% 15% / 0.06);
  --shadow-md: 0 2px 6px -1px hsl(30 10% 15% / 0.08), 0 4px 8px -4px hsl(30 10% 15% / 0.06);
  --shadow-lg: 0 6px 16px -4px hsl(30 10% 15% / 0.10), 0 4px 6px -4px hsl(30 10% 15% / 0.06);
  --shadow-xl: 0 12px 28px -8px hsl(30 10% 15% / 0.14);
  --shadow-2xl: 0 24px 48px -12px hsl(30 10% 15% / 0.20);
  --tracking-normal: 0em;
  --spacing: 0.25rem;

  --radius-sm: calc(var(--radius) - 4px);
  --radius-md: calc(var(--radius) - 2px);
  --radius-lg: var(--radius);
  --radius-xl: calc(var(--radius) + 4px);
}

.dark {
  --background: oklch(0.1650 0.0040 60);
  --foreground: oklch(0.9400 0.0040 85);
  --card: oklch(0.2000 0.0050 60);
  --card-foreground: oklch(0.9400 0.0040 85);
  --popover: oklch(0.2150 0.0050 60);
  --popover-foreground: oklch(0.9400 0.0040 85);
  --primary: oklch(0.9400 0.0040 85);
  --primary-foreground: oklch(0.1650 0.0040 60);
  --secondary: oklch(0.2500 0.0060 60);
  --secondary-foreground: oklch(0.9400 0.0040 85);
  --muted: oklch(0.2400 0.0060 60);
  --muted-foreground: oklch(0.6900 0.0100 70);
  --accent: oklch(0.2700 0.0070 60);
  --accent-foreground: oklch(0.9400 0.0040 85);
  --destructive: oklch(0.6900 0.1800 25);
  --destructive-foreground: oklch(0.1650 0.0040 60);
  --border: oklch(0.2900 0.0060 60);
  --input: oklch(0.3300 0.0070 60);
  --ring: oklch(0.6900 0.0100 70);

  --gain: oklch(0.7600 0.1500 155);
  --gain-soft: oklch(0.3000 0.0600 155);
  --loss: oklch(0.6900 0.1800 25);
  --loss-soft: oklch(0.3000 0.0700 25);
  --attention: oklch(0.8000 0.1300 80);
  --attention-soft: oklch(0.3200 0.0600 80);
  --trim: oklch(0.7400 0.1500 55);
  --trim-soft: oklch(0.3100 0.0600 55);
  --hold: oklch(0.7400 0.0100 70);
  --hold-soft: oklch(0.2700 0.0060 60);
  --risk-low: oklch(0.7300 0.1100 165);

  --chart-1: oklch(0.9400 0.0040 85);
  --chart-2: oklch(0.7400 0.1400 55);
  --chart-3: oklch(0.6800 0.0300 250);
  --chart-4: oklch(0.7600 0.1500 155);
  --chart-5: oklch(0.7600 0.1500 155 / 0.16);

  --sidebar: oklch(0.1850 0.0050 60);
  --sidebar-foreground: oklch(0.9400 0.0040 85);
  --sidebar-primary: oklch(0.9400 0.0040 85);
  --sidebar-primary-foreground: oklch(0.1650 0.0040 60);
  --sidebar-accent: oklch(0.2600 0.0070 60);
  --sidebar-accent-foreground: oklch(0.9400 0.0040 85);
  --sidebar-border: oklch(0.2900 0.0060 60);
  --sidebar-ring: oklch(0.6900 0.0100 70);

  /* Dark mode draws edges with borders, not shadows. */
  --shadow-2xs: 0 0 #0000;
  --shadow-xs: 0 0 #0000;
  --shadow-sm: 0 0 #0000;
  --shadow: 0 0 #0000;
  --shadow-md: 0 0 #0000;
  --shadow-lg: 0 8px 24px -8px hsl(0 0% 0% / 0.5);
  --shadow-xl: 0 12px 32px -8px hsl(0 0% 0% / 0.55);
  --shadow-2xl: 0 24px 48px -12px hsl(0 0% 0% / 0.6);
}

/* Aliases, declared for both modes so each one resolves against its own mode's colours
   (a var() in a custom property is resolved where it is declared, then inherited). */
:root,
.dark {
  --action-sell: var(--loss);
  --action-trim: var(--trim);
  --action-review: var(--attention);
  --action-add: var(--gain);
  --action-hold: var(--hold);
  --risk-medium: var(--attention);
  --risk-high: var(--trim);
  --risk-very-high: var(--loss);
  --status-ok: var(--gain);
  --status-partial: var(--attention);
  --status-stale: var(--trim);
  --status-failed: var(--loss);
  --status-skipped: var(--hold);
}
```

`web/app/styles/ledger.css`:

```css
/* Ledger components and motion (superdesign steps 3 and 4, dashboard_1.css). Colours and fonts come from
 * theme.css. Unlayered, these rules already beat Tailwind's layered preflight; the mockups' !important marks are kept so the port stays line for line. */

html { color-scheme: light; }
html.dark { color-scheme: dark; }
body {
  margin: 0 !important;
  background: var(--background) !important;
  color: var(--foreground) !important;
  font-family: var(--font-sans) !important;
  font-size: 14px !important;
  line-height: 1.5 !important;
  -webkit-font-smoothing: antialiased;
}
h1, h2, h3, h4 { margin: 0; /* not !important, unlike the mockup: headings' inline margins apply */ color: var(--foreground) !important; font-family: var(--font-sans) !important; letter-spacing: -0.01em; }
h1 { font-size: 22px !important; font-weight: 600 !important; line-height: 1.2 !important; }
h2 { font-size: 15px !important; font-weight: 600 !important; line-height: 1.3 !important; }
h3 { font-size: 13px !important; font-weight: 600 !important; }
a { color: inherit !important; text-decoration: none !important; }
button, input, select, textarea { font-family: inherit !important; color: inherit; }
:focus-visible { outline: 2px solid var(--ring) !important; outline-offset: 2px !important; border-radius: var(--radius-sm); }

.num { font-family: var(--font-mono) !important; font-variant-numeric: tabular-nums; letter-spacing: -0.01em; }
.label { font: 500 11px/1.2 var(--font-mono) !important; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted-foreground) !important; }
.muted { color: var(--muted-foreground) !important; }
.gain { color: var(--gain) !important; }
.loss { color: var(--loss) !important; }
.attention-text { color: var(--attention) !important; }

/* ---------- App frame ---------- */
.shell { min-height: 100dvh; display: grid; grid-template-columns: minmax(0, 1fr); }
.sidebar { display: none; }
.content { min-width: 0; display: flex; flex-direction: column; }
main.page { flex: 1; width: 100%; max-width: 1240px; margin: 0 auto; padding: 16px 16px 112px; display: grid; grid-template-columns: minmax(0, 1fr); gap: 16px; align-content: start; }
main.page > *, main.page section > *, main.page .grid > *, .card { min-width: 0; }
@media (min-width: 1024px) {
  .shell { grid-template-columns: 232px minmax(0, 1fr); }
  .sidebar {
    display: flex; flex-direction: column; gap: 4px; position: sticky; top: 0; height: 100dvh;
    padding: 18px 12px; background: var(--sidebar); border-right: 1px solid var(--sidebar-border);
  }
  main.page { padding: 24px 28px 40px; gap: 20px; }
}
.brand { display: flex; align-items: center; gap: 8px; padding: 2px 10px 16px; font: 600 13px/1 var(--font-mono); letter-spacing: 0.14em; }
.brand-mark { width: 22px; height: 22px; border-radius: 6px; background: var(--primary); color: var(--primary-foreground); display: grid; place-items: center; font-size: 12px; }
.nav-link {
  display: flex; align-items: center; gap: 10px; padding: 8px 10px; border-radius: var(--radius-md);
  color: var(--muted-foreground) !important; font-size: 14px; transition: background 150ms, color 150ms;
}
.nav-link:hover { background: var(--sidebar-accent); color: var(--foreground) !important; }
.nav-link[aria-current="page"] { background: var(--sidebar-accent); color: var(--foreground) !important; font-weight: 500; }
.nav-link svg { width: 17px; height: 17px; }
.sidebar-search { margin-top: 14px; position: relative; }
.sidebar-search input { width: 100%; padding-left: 32px !important; }
.sidebar-search svg { position: absolute; left: 10px; top: 50%; transform: translateY(-50%); width: 15px; height: 15px; color: var(--muted-foreground); }
.sidebar-foot { margin-top: auto; padding: 10px; font-size: 12px; color: var(--muted-foreground); display: grid; gap: 6px; }

.statusbar {
  position: sticky; top: 0; z-index: 30; display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  padding: 10px 16px; border-bottom: 1px solid var(--border);
  background: color-mix(in oklch, var(--background) 88%, transparent); backdrop-filter: blur(10px);
}
@media (min-width: 1024px) { .statusbar { padding: 10px 28px; } }
.statusbar .brand { padding: 0 8px 0 0; }
@media (min-width: 1024px) { .statusbar .brand { display: none; } }
.status-spacer { flex: 1; }
.pill {
  display: inline-flex; align-items: center; gap: 7px; padding: 5px 10px; font-size: 12.5px; font-weight: 500;
  border: 1px solid var(--border); border-radius: 999px; background: var(--card); white-space: nowrap;
}
button.pill { cursor: pointer; }
button.pill:hover, a.pill:hover { background: var(--accent); }
.icon-btn {
  display: inline-grid; place-items: center; width: 32px; height: 32px; border-radius: var(--radius-md);
  border: 1px solid var(--border); background: var(--card); cursor: pointer;
}
.icon-btn:hover { background: var(--accent); }
.icon-btn svg { width: 16px; height: 16px; }
.hide-sm { display: none !important; }
@media (min-width: 640px) { .hide-sm { display: inline-flex !important; } }
.only-sm { display: inline-flex; }
@media (min-width: 1024px) { .only-sm { display: none !important; } }

.popover {
  position: absolute; z-index: 60; min-width: 300px; padding: 6px; border-radius: var(--radius-lg);
  background: var(--popover); color: var(--popover-foreground); border: 1px solid var(--border); box-shadow: var(--shadow-lg);
  opacity: 0; transform: translateY(-4px); pointer-events: none; transition: opacity 150ms, transform 150ms;
}
.popover.open { opacity: 1; transform: none; pointer-events: auto; }
.popover-row { display: grid; grid-template-columns: auto 1fr auto; gap: 10px; align-items: center; padding: 8px 10px; border-radius: var(--radius-md); font-size: 13px; }
.popover-row:hover { background: var(--accent); }

.disclaimer { padding: 14px 16px 92px; text-align: center; font-size: 12px; color: var(--muted-foreground); border-top: 1px solid var(--border); }
@media (min-width: 1024px) { .disclaimer { padding: 14px 28px; } }

.bottom-tabs {
  position: fixed; left: 0; right: 0; bottom: 0; z-index: 40; display: grid; grid-template-columns: repeat(4, 1fr);
  border-top: 1px solid var(--border); background: color-mix(in oklch, var(--background) 92%, transparent);
  backdrop-filter: blur(12px); padding-bottom: env(safe-area-inset-bottom);
}
@media (min-width: 1024px) { .bottom-tabs { display: none; } }
.bottom-tab {
  display: grid; justify-items: center; gap: 3px; padding: 9px 4px 10px; font-size: 11px; font-weight: 500;
  color: var(--muted-foreground) !important; background: none; border: 0; cursor: pointer;
}
.bottom-tab svg { width: 20px; height: 20px; transition: transform 150ms; }
.bottom-tab[aria-current="page"] { color: var(--foreground) !important; }
.bottom-tab[aria-current="page"] svg { animation: tab-bump 150ms ease-out; }
@keyframes tab-bump { 50% { transform: scale(1.08); } }

/* ---------- Surfaces and controls ---------- */
.card { background: var(--card); color: var(--card-foreground); border: 1px solid var(--border); border-radius: var(--radius-lg); box-shadow: var(--shadow-xs); }
.card-pad { padding: 16px; }
@media (min-width: 1024px) { .card-pad { padding: 18px 20px; } }
.section-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; margin-bottom: 12px; }

.chip { display: inline-flex; align-items: center; gap: 6px; font: 600 11px/1 var(--font-mono) !important; letter-spacing: 0.06em; text-transform: uppercase; padding: 6px 9px; border-radius: 999px; white-space: nowrap; }
.chip.sell { color: var(--action-sell); background: var(--loss-soft); }
.chip.trim { color: var(--action-trim); background: var(--trim-soft); }
.chip.review { color: var(--action-review); background: var(--attention-soft); }
.chip.add { color: var(--action-add); background: var(--gain-soft); }
.chip.hold { color: var(--action-hold); background: var(--hold-soft); }
.chip.buy { color: var(--gain); background: var(--gain-soft); }
.chip.avoid { color: var(--loss); background: var(--loss-soft); }

.badge { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; font-weight: 500; padding: 3px 8px; border-radius: var(--radius-sm); border: 1px solid var(--border); background: var(--card); white-space: nowrap; }
.dot { width: 8px; height: 8px; border-radius: 999px; display: inline-block; flex: none; }
.dot.ok { background: var(--status-ok); } .dot.partial { background: var(--status-partial); } .dot.stale { background: var(--status-stale); }
.dot.failed { background: var(--status-failed); } .dot.skipped { background: var(--status-skipped); }
.dot.low { background: var(--risk-low); } .dot.medium { background: var(--risk-medium); } .dot.high { background: var(--risk-high); } .dot.very-high { background: var(--risk-very-high); }
.dot.paper { background: var(--attention); } .dot.validated { background: var(--gain); }

.btn {
  display: inline-flex; align-items: center; justify-content: center; gap: 7px; font: 500 13px/1 var(--font-sans) !important;
  padding: 9px 14px; border-radius: var(--radius-md); border: 1px solid transparent; cursor: pointer; white-space: nowrap;
  transition: background 150ms, transform 100ms, opacity 150ms;
}
.btn:active { transform: scale(0.98); }
.btn svg { width: 15px; height: 15px; }
.btn-primary { background: var(--primary) !important; color: var(--primary-foreground) !important; }
.btn-primary:hover { opacity: 0.9; }
.btn-secondary { background: var(--secondary) !important; color: var(--secondary-foreground) !important; border-color: var(--border) !important; }
.btn-secondary:hover { background: var(--accent) !important; }
.btn-ghost { background: transparent !important; color: var(--foreground) !important; }
.btn-ghost:hover { background: var(--accent) !important; }
.btn-sm { padding: 7px 10px; font-size: 12.5px !important; }

.input, .select {
  font: 400 13px/1.2 var(--font-sans) !important; padding: 9px 11px; border-radius: var(--radius-md);
  border: 1px solid var(--input) !important; background: var(--card) !important; color: var(--foreground) !important;
  width: 100%; transition: box-shadow 120ms, border-color 120ms;
}
.input:focus, .select:focus { outline: none !important; border-color: var(--ring) !important; box-shadow: 0 0 0 2px color-mix(in oklch, var(--ring) 35%, transparent); }
.input.num-input { font-family: var(--font-mono) !important; }
.field { display: grid; gap: 6px; }
.field > span:first-child { font-size: 12.5px; font-weight: 500; }
.field .hint { font-size: 12px; color: var(--muted-foreground); }
.field .error { font-size: 12px; color: var(--loss); display: none; }
.field.invalid .input, .field.invalid .select { border-color: var(--loss) !important; }
.field.invalid .error { display: block; animation: fade 150ms ease-out; }

.tabs { position: relative; display: inline-flex; padding: 3px; gap: 2px; border-radius: var(--radius-md); background: var(--muted); }
.tab { position: relative; z-index: 1; font: 500 13px/1 var(--font-sans) !important; padding: 7px 14px; border: 0; background: none; border-radius: var(--radius-sm); color: var(--muted-foreground); cursor: pointer; transition: color 150ms; }
.tab[aria-selected="true"] { color: var(--foreground); }
.tab-indicator { position: absolute; z-index: 0; top: 3px; bottom: 3px; left: 0; border-radius: var(--radius-sm); background: var(--card); box-shadow: var(--shadow-xs); transition: transform 200ms ease-out, width 200ms ease-out; }
html.dark .tab-indicator { background: var(--accent); }
[data-panel][hidden] { display: none !important; }
[data-panel] { animation: fade 150ms ease-out; }

.data-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.data-table th { text-align: left; font: 500 11px/1.2 var(--font-mono) !important; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted-foreground); padding: 0 10px 10px; border-bottom: 1px solid var(--border); white-space: nowrap; }
.data-table td { padding: 11px 10px; border-bottom: 1px solid var(--border); vertical-align: middle; white-space: nowrap; }
.data-table tbody tr { transition: background 150ms; }
.data-table tbody tr:hover { background: var(--accent); }
.data-table tr:last-child td { border-bottom: 0; }
.data-table .r { text-align: right; }
.table-scroll { overflow-x: auto; margin: 0 -16px; padding: 0 16px; }
@media (min-width: 1024px) { .table-scroll { margin: 0 -20px; padding: 0 20px; } }
.sym { font: 600 13px/1.2 var(--font-mono) !important; }
.sub { font-size: 12px; color: var(--muted-foreground); }

/* Forecast range bar: q10..q90 band, q50 dot, zero line */
.range { position: relative; height: 16px; width: 132px; flex: none; }
.range .track { position: absolute; top: 7px; left: 0; right: 0; height: 2px; border-radius: 2px; background: var(--border); }
.range .zero { position: absolute; top: 1px; width: 1px; height: 14px; background: var(--muted-foreground); opacity: 0.7; }
.range .band { position: absolute; top: 4px; height: 8px; border-radius: 4px; background: var(--chart-5); border: 1px solid var(--chart-4); transform-origin: var(--origin, 50%) center; animation: band-grow 300ms ease-out both; }
.range .mid { position: absolute; top: 2px; width: 12px; height: 12px; margin-left: -6px; border-radius: 999px; background: var(--chart-4); border: 2px solid var(--card); animation: pop 200ms ease-out 150ms both; }
.range.wide { width: 100%; height: 22px; }
.range.wide .track { top: 10px; } .range.wide .zero { top: 2px; height: 18px; } .range.wide .band { top: 6px; height: 10px; } .range.wide .mid { top: 4px; width: 14px; height: 14px; margin-left: -7px; }

.banner { display: flex; align-items: flex-start; gap: 10px; padding: 10px 14px; border-radius: var(--radius-lg); font-size: 13px; border: 1px solid; animation: banner-in 250ms ease-out both; }
.banner svg { width: 16px; height: 16px; flex: none; margin-top: 2px; }
.banner.warn { background: var(--attention-soft); border-color: color-mix(in oklch, var(--attention) 35%, transparent); }
.banner.danger { background: var(--loss-soft); border-color: color-mix(in oklch, var(--loss) 35%, transparent); }
.banner.info { background: var(--muted); border-color: var(--border); }
.banners { display: grid; gap: 8px; padding: 0 16px; }
.banners:not(:empty) { padding-top: 12px; }
@media (min-width: 1024px) { .banners { padding: 0 28px; } }

.empty { display: grid; justify-items: center; gap: 8px; padding: 36px 16px; text-align: center; color: var(--muted-foreground); animation: fade 200ms ease-out; }
.empty svg { width: 26px; height: 26px; }
.empty strong { color: var(--foreground); font-size: 14px; }

.skeleton { display: block; border-radius: var(--radius-sm); background: var(--muted); animation: skeleton 1500ms ease-in-out infinite; }

/* Action cards */
.action-card { position: relative; display: grid; gap: 6px; padding: 14px; border-radius: var(--radius-lg); background: var(--card); border: 1px solid var(--border); border-top: 3px solid var(--tone); box-shadow: var(--shadow-xs); transition: transform 150ms, box-shadow 150ms; cursor: pointer; }
.action-card:hover { transform: translateY(-2px); box-shadow: var(--shadow-md); }
.action-card:active { transform: scale(0.98); transition-duration: 100ms; }
.action-card.sell { --tone: var(--action-sell); } .action-card.trim { --tone: var(--action-trim); }
.action-card.review { --tone: var(--action-review); } .action-card.add { --tone: var(--action-add); } .action-card.hold { --tone: var(--action-hold); }
.action-card.attention { animation: attention 700ms ease-out 400ms 2; }
.action-grid { display: grid; gap: 10px; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); }
@media (max-width: 639px) {
  .action-grid { display: flex; overflow-x: auto; scroll-snap-type: x mandatory; margin: 0 -16px; padding: 2px 16px 6px; }
  .action-grid > * { flex: 0 0 76%; scroll-snap-align: start; }
}

/* Drawers and sheets */
.backdrop { position: fixed; inset: 0; z-index: 70; background: hsl(0 0% 0% / 0.5); backdrop-filter: blur(2px); opacity: 0; pointer-events: none; transition: opacity 200ms; }
.backdrop.open { opacity: 1; pointer-events: auto; }
.drawer {
  position: fixed; z-index: 80; background: var(--background); border: 1px solid var(--border); box-shadow: var(--shadow-2xl);
  display: flex; flex-direction: column; inset: auto 0 0 0; max-height: 92dvh; border-radius: 16px 16px 0 0;
  transform: translateY(105%); transition: transform 300ms ease-out; visibility: hidden;
}
.drawer.open { transform: none; visibility: visible; }
@media (min-width: 768px) {
  .drawer { inset: 0 0 0 auto; width: 440px; max-height: none; border-radius: 0; transform: translateX(105%); transition-duration: 250ms; }
}
.drawer-head { display: flex; align-items: center; justify-content: space-between; padding: 16px 18px; border-bottom: 1px solid var(--border); }
.drawer-body { padding: 18px; overflow-y: auto; display: grid; gap: 14px; align-content: start; }
.drawer-foot { margin-top: auto; padding: 14px 18px calc(14px + env(safe-area-inset-bottom)); border-top: 1px solid var(--border); display: flex; gap: 8px; justify-content: flex-end; }
.grab { width: 36px; height: 4px; border-radius: 4px; background: var(--border); margin: 8px auto 0; }
@media (min-width: 768px) { .grab { display: none; } }

.toast {
  position: fixed; z-index: 90; top: 14px; right: 14px; left: 14px; display: flex; gap: 10px; align-items: center;
  padding: 11px 14px; border-radius: var(--radius-lg); background: var(--primary); color: var(--primary-foreground);
  box-shadow: var(--shadow-xl); font-size: 13px; opacity: 0; transform: translateY(-8px); pointer-events: none; transition: opacity 250ms, transform 250ms;
}
@media (min-width: 640px) { .toast { left: auto; max-width: 380px; } }
.toast.show { opacity: 1; transform: none; }
.toast svg { width: 16px; height: 16px; }


/* Charts */
.chart { position: relative; width: 100%; }
.chart svg { display: block; width: 100%; height: auto; overflow: visible; }
.chart text { font-family: var(--font-mono); font-size: 10px; fill: var(--muted-foreground); paint-order: stroke; stroke: var(--card); stroke-width: 3px; stroke-linejoin: round; }
.chart .grid line { stroke: var(--border); stroke-width: 1; }
.chart .tip { position: absolute; pointer-events: none; padding: 6px 9px; border-radius: var(--radius-md); background: var(--popover); border: 1px solid var(--border); box-shadow: var(--shadow-md); font-size: 12px; opacity: 0; transition: opacity 120ms; white-space: nowrap; }
.chart .tip.show { opacity: 1; }
.legend { display: flex; flex-wrap: wrap; gap: 14px; font-size: 12px; color: var(--muted-foreground); }
.legend i { display: inline-block; width: 14px; height: 2px; border-radius: 2px; vertical-align: middle; margin-right: 6px; }

/* ---------- Motion (signed off in step 3) ---------- */
@keyframes fade { from { opacity: 0; } to { opacity: 1; } }
@keyframes fade-up { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: none; } }
@keyframes banner-in { from { opacity: 0; transform: translateY(-100%); } to { opacity: 1; transform: none; } }
@keyframes draw { to { stroke-dashoffset: 0; } }
@keyframes cone-in { from { opacity: 0; transform: scaleX(0); } to { opacity: 1; transform: scaleX(1); } }
@keyframes band-grow { from { transform: scaleX(0); } to { transform: scaleX(1); } }
@keyframes pop { from { transform: scale(0); } to { transform: scale(1); } }
@keyframes attention { 0% { box-shadow: 0 0 0 0 color-mix(in oklch, var(--tone) 50%, transparent), var(--shadow-xs); } 100% { box-shadow: 0 0 0 6px color-mix(in oklch, var(--tone) 0%, transparent), var(--shadow-xs); } }
@keyframes running { 0%, 100% { opacity: 0.4; } 50% { opacity: 1; } }
@keyframes shake { 0%, 100% { transform: none; } 25% { transform: translateX(-4px); } 75% { transform: translateX(4px); } }
@keyframes highlight { from { background: var(--attention-soft); } to { background: transparent; } }
@keyframes skeleton { 0%, 100% { background: var(--muted); } 50% { background: var(--accent); } }

.enter { animation: fade-up 200ms ease-out both; }
.stagger > * { animation: fade-up 240ms ease-out both; animation-delay: calc(min(var(--i, 0), 7) * 40ms); }
.chart .draw { stroke-dasharray: var(--len); stroke-dashoffset: var(--len); animation: draw 600ms ease-out forwards; }
.chart .cone { transform-box: view-box; animation: cone-in 400ms ease-out 500ms both; }
.chart .late { animation: fade 300ms ease-out 300ms both; }
.dot.running { animation: running 1600ms ease-in-out infinite; }
.shake { animation: shake 150ms ease-in-out 2; }
.row-added td { animation: highlight 400ms ease-out; }

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation-duration: 1ms !important; animation-iteration-count: 1 !important; transition-duration: 1ms !important; scroll-behavior: auto !important; }
  .enter, .stagger > *, [data-panel], .empty { animation: fade 150ms ease-out both !important; animation-delay: 0ms !important; }
  .dot.running, .action-card.attention, .skeleton, .shake { animation: none !important; }
  .chart .draw { stroke-dasharray: none !important; stroke-dashoffset: 0 !important; animation: none !important; }
  .chart .cone, .chart .late { animation: none !important; opacity: 1 !important; transform: none !important; }
}
```

`web/app/styles/pages.css`:

```css
/* Page styles from the superdesign mockups' <style> blocks, one section per page. */

/* ---------- login_1.html ---------- */
.login-wrap { min-height: 100dvh; display: grid; place-items: center; padding: 24px 16px; }
.login { width: 100%; max-width: 380px; display: grid; gap: 18px; }
.login .card { padding: 24px; display: grid; gap: 14px; }
.theme-corner { position: fixed; top: 14px; right: 14px; }
.login h1 { font-size: 19px !important; } /* the mockup set this inline, which React can't mark !important */

/* ---------- portfolio_1.html ---------- */
.value-big { font: 600 34px/1.05 var(--font-mono) !important; letter-spacing: -0.03em; }
.expand { display: grid; grid-template-rows: 0fr; transition: grid-template-rows 200ms ease-out, opacity 200ms; opacity: 0; }
.expand.open { grid-template-rows: 1fr; opacity: 1; }
.expand > div { overflow: hidden; }
.hold-toggle { width: 100%; display: flex; align-items: center; gap: 10px; padding: 12px 14px; margin-top: 10px; border: 1px solid var(--border); border-radius: var(--radius-lg); background: var(--card); cursor: pointer; text-align: left; }
.hold-toggle:hover { background: var(--accent); }
.hold-toggle svg { width: 16px; height: 16px; transition: transform 200ms; }
.hold-toggle[aria-expanded="true"] svg { transform: rotate(180deg); }
.hold-row { display: grid; grid-template-columns: 1fr auto; gap: 4px 12px; padding: 10px 14px; border-bottom: 1px solid var(--border); font-size: 13px; }
.hold-row:last-child { border-bottom: 0; }
.warning { display: grid; grid-template-columns: auto 1fr; gap: 3px 10px; padding: 11px 0; border-bottom: 1px solid var(--border); }
.warning:last-child { border-bottom: 0; padding-bottom: 0; }
.warning svg { width: 16px; height: 16px; color: var(--attention); margin-top: 2px; }
.warning strong { font-size: 13px; font-weight: 600; }
.warning p { grid-column: 2; margin: 0; font-size: 12.5px; color: var(--muted-foreground); }
.stack { display: flex; height: 10px; border-radius: 999px; overflow: hidden; background: var(--muted); }
.stack span { display: block; height: 100%; transform-origin: left; animation: band-grow 400ms ease-out both; }
.stack-legend { display: flex; flex-wrap: wrap; gap: 4px 12px; margin-top: 8px; font-size: 12px; color: var(--muted-foreground); }
.stack-legend b { color: var(--foreground); font-weight: 500; font-family: var(--font-mono); }
.warn-cell { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: var(--muted-foreground); }
.warn-cell svg { width: 14px; height: 14px; color: var(--attention); }
#holdings td.h-note { white-space: normal; min-width: 150px; max-width: 190px; }
/* Phones: each holding becomes a stacked row (symbol, then account, value and P/L, then the note).
   Cells are placed by class, not position, so model columns can be added later (Plan 4). */
@media (max-width: 639px) {
  #holdings thead { display: none; }
  #holdings, #holdings tbody { display: block; }
  #holdings tr { display: grid; grid-template-columns: auto 1fr auto; grid-template-areas: "sym sym sym" "acct val pl" "note note note"; gap: 6px 10px; padding: 12px 0; border-bottom: 1px solid var(--border); }
  #holdings tr:last-child { border-bottom: 0; }
  #holdings td { display: none; padding: 0; border: 0; white-space: normal; max-width: none; min-width: 0; }
  #holdings td.h-acct { display: block; grid-area: acct; }
  #holdings td.h-sym { display: block; grid-area: sym; }
  #holdings td.h-sym br { display: none; }
  #holdings td.h-sym .sub::before { content: " · "; }
  #holdings td.h-value { display: block; grid-area: val; text-align: left !important; }
  #holdings td.h-value::before { content: "C$"; }
  #holdings td.h-pl { display: block; grid-area: pl; }
  #holdings td.h-pl br { display: none; }
  #holdings td.h-pl .sub::before { content: " · "; }
  #holdings td.h-note:has(.warn-cell) { display: block; grid-area: note; }
  .table-scroll { overflow: visible; margin: 0; padding: 0; }
}
.before-note { display: flex; gap: 10px; align-items: flex-start; padding: 10px 12px; border-radius: var(--radius-md); background: var(--muted); font-size: 12.5px; color: var(--muted-foreground); margin-bottom: 12px; }
.before-note svg { width: 15px; height: 15px; flex: none; margin-top: 1px; }

/* ---------- watchlist_1.html ---------- */
.add-row { display: grid; grid-template-columns: minmax(0, 1fr) 170px auto; gap: 10px; align-items: start; }
@media (max-width: 639px) { .add-row { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); } .add-row .btn { grid-column: 1 / 3; } }
.watch-row { display: grid; grid-template-columns: 110px 70px 86px minmax(0, 1fr) 96px 36px; gap: 12px; align-items: center; padding: 12px 4px; border-bottom: 1px solid var(--border); transition: background 150ms; }
.watch-row:hover { background: var(--accent); }
.watch-row:last-child { border-bottom: 0; }
.watch-row.removing { animation: collapse 200ms ease-in forwards; overflow: hidden; }
@keyframes collapse { to { opacity: 0; max-height: 0; padding-top: 0; padding-bottom: 0; } }
.watch-row.row-added { animation: highlight 400ms ease-out; }
@media (max-width: 767px) {
  .watch-row { grid-template-columns: minmax(0, 1fr) auto 36px; grid-template-areas: "sym verdict x" "detail detail detail"; gap: 4px 10px; }
  .watch-row .w-sym { grid-area: sym; } .watch-row .w-verdict { grid-area: verdict; } .watch-row .w-x { grid-area: x; }
  .watch-row .w-detail { grid-area: detail; } .watch-row .w-type, .watch-row .w-price { display: none; }
}
.watch-head { display: grid; grid-template-columns: 110px 70px 86px minmax(0, 1fr) 96px 36px; gap: 12px; padding: 0 4px 10px; border-bottom: 1px solid var(--border); }
@media (max-width: 767px) { .watch-head { display: none; } }
/* Before the model there are no verdict columns: symbol, type, price, remove (Plan 5b). */
.watch-head.plain, .watch-row.plain { grid-template-columns: minmax(0, 1fr) 70px 110px 36px; }
@media (max-width: 767px) {
  .watch-row.plain { grid-template-columns: minmax(0, 1fr) auto 36px; grid-template-areas: "sym price x"; }
  .watch-row.plain .w-price { display: block; grid-area: price; }
}

/* ---------- settings_1.html ---------- */
.settings { max-width: 760px; display: grid; gap: 16px; }
.setting { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 6px 24px; align-items: center; padding: 14px 0; border-bottom: 1px solid var(--border); }
.setting .with-unit { width: 190px; }
.setting:last-of-type { border-bottom: 0; }
@media (max-width: 639px) { .setting { grid-template-columns: minmax(0, 1fr); } }
.setting strong { font-size: 13.5px; font-weight: 600; }
.setting p { margin: 2px 0 0; font-size: 12.5px; color: var(--muted-foreground); }
.with-unit { position: relative; }
.with-unit .input { padding-right: 70px !important; text-align: right; }
.with-unit span.unit { position: absolute; right: 11px; top: 50%; transform: translateY(-50%); font-size: 12px; color: var(--muted-foreground); pointer-events: none; }
```

`web/app/globals.css`:

```css
@import "tailwindcss";
@import "./styles/theme.css";
@import "./styles/ledger.css";
@import "./styles/pages.css";
```

`web/app/icon.svg`:

```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="8" fill="#2b2622"/><text x="16" y="22" text-anchor="middle" font-family="ui-monospace,monospace" font-size="17" font-weight="600" fill="#fbfaf6">A</text></svg>
```

`web/app/layout.tsx`:

```tsx
import type { Metadata, Viewport } from 'next'
import { Geist, Geist_Mono } from 'next/font/google'
import { THEME_SCRIPT } from '@/lib/theme'
import './globals.css'

const sans = Geist({ subsets: ['latin'], variable: '--font-geist' })
const mono = Geist_Mono({ subsets: ['latin'], variable: '--font-geist-mono' })

export const metadata: Metadata = {
  title: { default: 'Advisor', template: '%s · Advisor' },
  description: 'A personal stock and crypto advisor.',
  robots: { index: false, follow: false },
}

export const viewport: Viewport = { width: 'device-width', initialScale: 1, viewportFit: 'cover' }

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    // The theme script sets the "dark" class before React hydrates.
    <html lang="en-CA" className={`${sans.variable} ${mono.variable}`} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body>{children}</body>
    </html>
  )
}
```

- [ ] **Step 8: Lint, type-check and build**

Run: `npm run lint`, then `npm run typecheck`, then `npm run build`
Expected:
- lint prints nothing after its header;
- typecheck prints `✓ Types generated successfully` and no errors;
- the build ends with the routes `/_not-found` and `/icon.svg`.

- [ ] **Step 9: Configure and start the local Supabase stack**

This is the CLI's `supabase init` output with four kinds of edits:
- `project_id = "stock-advisor"`;
- Realtime, Studio, local SMTP, Storage, the edge runtime, analytics and seeding turned off;
- `[auth] enable_signup = false`, matching the hosted project's "Allow new users to sign up" off;
- `[auth.email] enable_signup` kept `true`, because `false` there turns email sign-in off entirely.

`supabase/config.toml`:

```toml
# For detailed configuration reference documentation, visit:
# https://supabase.com/docs/guides/local-development/cli/config
# A string used to distinguish different Supabase projects on the same host. Defaults to the
# working directory name when running `supabase init`.
project_id = "stock-advisor"

[api]
enabled = true
# Port to use for the API URL.
port = 54321
# Schemas to expose in your API. Tables, views and stored procedures in this schema will get API
# endpoints. `public` and `graphql_public` schemas are included by default.
schemas = ["public", "graphql_public"]
# Extra schemas to add to the search_path of every request.
extra_search_path = ["public", "extensions"]
# The maximum number of rows returns from a view, table, or stored procedure. Limits payload size
# for accidental or malicious requests.
max_rows = 1000
# Controls whether new tables, views, sequences and functions created in the `public` schema by
# `postgres` are reachable through the Data API roles (`anon`, `authenticated`, `service_role`)
# without explicit GRANTs, matching the cloud default. Set to `false` to require explicit GRANTs
# instead. Left unset, a fresh project falls back to `true`.
# auto_expose_new_tables = true

[api.tls]
# Enable HTTPS endpoints locally using a self-signed certificate.
enabled = false
# Paths to self-signed certificate pair.
# cert_path = "../certs/my-cert.pem"
# key_path = "../certs/my-key.pem"

[db]
# Port to use for the local database URL.
port = 54322
# Port used by db diff command to initialize the shadow database.
shadow_port = 54320
# Maximum amount of time to wait for health check when starting the local database.
health_timeout = "2m"
# The database major version to use. This has to be the same as your remote database's. Run `SHOW
# server_version;` on the remote database to check.
major_version = 17
# OrioleDB version to use as the Postgres storage engine. Leave empty to use the default engine.
orioledb_version = ""

[db.pooler]
enabled = false
# Port to use for the local connection pooler.
port = 54329
# Specifies when a server connection can be reused by other clients.
# Configure one of the supported pooler modes: `transaction`, `session`.
pool_mode = "transaction"
# How many server connections to allow per user/database pair.
default_pool_size = 20
# Maximum number of client connections allowed.
max_client_conn = 100

# [db.vault]
# secret_key = "env(SECRET_VALUE)"

[db.migrations]
# If disabled, migrations will be skipped during a db push or reset.
enabled = true
# Specifies an ordered list of schema files, directories, or glob patterns that describe your database.
# Supports paths relative to supabase directory: "./schemas/*.sql", "./database".
schema_paths = []

[db.seed]
# If enabled, seeds the database after migrations during a db reset.
enabled = false
# Specifies an ordered list of seed files to load during db reset.
# Supports glob patterns relative to supabase directory: "./seeds/*.sql"
sql_paths = ["./seed.sql"]

[db.network_restrictions]
# Enable management of network restrictions.
enabled = false
# List of IPv4 CIDR blocks allowed to connect to the database.
# Defaults to allow all IPv4 connections. Set empty array to block all IPs.
allowed_cidrs = ["0.0.0.0/0"]
# List of IPv6 CIDR blocks allowed to connect to the database.
# Defaults to allow all IPv6 connections. Set empty array to block all IPs.
allowed_cidrs_v6 = ["::/0"]

# Uncomment to reject non-secure connections to the database.
# [db.ssl_enforcement]
# enabled = true

[realtime]
enabled = false
# Bind realtime via either IPv4 or IPv6. (default: IPv4)
# ip_version = "IPv6"
# The maximum length in bytes of HTTP request headers. (default: 4096)
# max_header_length = 4096

[studio]
enabled = false
# Port to use for Supabase Studio.
port = 54323
# External URL of the API server that frontend connects to.
api_url = "http://127.0.0.1"
# OpenAI API Key to use for Supabase AI in the Supabase Studio.
openai_api_key = "env(OPENAI_API_KEY)"

# Email testing server. Emails sent with the local dev setup are not actually sent - rather, they
# are monitored, and you can view the emails that would have been sent from the web interface.
[local_smtp]
enabled = false
# Port to use for the email testing server web interface.
port = 54324
# Uncomment to expose additional ports for testing user applications that send emails.
# smtp_port = 54325
# pop3_port = 54326
# admin_email = "admin@email.com"
# sender_name = "Admin"

[storage]
enabled = false
# The maximum file size allowed (e.g. "5MB", "500KB").
file_size_limit = "50MiB"

# Uncomment to configure local storage buckets
# [storage.buckets.images]
# public = false
# file_size_limit = "50MiB"
# allowed_mime_types = ["image/png", "image/jpeg"]
# objects_path = "./images"

# Allow connections via S3 compatible clients
[storage.s3_protocol]
enabled = true

# Image transformation API is available to Supabase Pro plan.
# [storage.image_transformation]
# enabled = true

# Store analytical data in S3 for running ETL jobs over Iceberg Catalog
# This feature is only available on the hosted platform.
[storage.analytics]
enabled = false
max_namespaces = 5
max_tables = 10
max_catalogs = 2

# Analytics Buckets is available to Supabase Pro plan.
# [storage.analytics.buckets.my-warehouse]

# Store vector embeddings in S3 for large and durable datasets
[storage.vector]
enabled = true
max_buckets = 10
max_indexes = 5

# Vector Buckets is available to Supabase Pro plan.
# [storage.vector.buckets.documents-openai]

[auth]
enabled = true
# The base URL of your website. Used as an allow-list for redirects and for constructing URLs used
# in emails.
site_url = "http://127.0.0.1:3000"
# The public URL that Auth serves on. Defaults to the API external URL with `/auth/v1` appended.
# external_url = ""
# A list of *exact* URLs that auth providers are permitted to redirect to post authentication.
additional_redirect_urls = ["https://127.0.0.1:3000"]
# How long tokens are valid for, in seconds. Defaults to 3600 (1 hour), maximum 604,800 (1 week).
jwt_expiry = 3600
# JWT issuer URL. If not set, defaults to auth.external_url.
# jwt_issuer = ""
# Path to JWT signing key. DO NOT commit your signing keys file to git.
# signing_keys_path = "./signing_keys.json"
# If disabled, the refresh token will never expire.
enable_refresh_token_rotation = true
# Allows refresh tokens to be reused after expiry, up to the specified interval in seconds.
# Requires enable_refresh_token_rotation = true.
refresh_token_reuse_interval = 10
# Allow/disallow new user signups to your project.
enable_signup = false
# Allow/disallow anonymous sign-ins to your project.
enable_anonymous_sign_ins = false
# Allow/disallow testing manual linking of accounts
enable_manual_linking = false
# Passwords shorter than this value will be rejected as weak. Minimum 6, recommended 8 or more.
minimum_password_length = 6
# Passwords that do not meet the following requirements will be rejected as weak. Supported values
# are: `letters_digits`, `lower_upper_letters_digits`, `lower_upper_letters_digits_symbols`
password_requirements = ""

# Configure passkey sign-ins.
# [auth.passkey]
# enabled = false

# Configure WebAuthn relying party settings (required when passkey is enabled).
# [auth.webauthn]
# rp_display_name = "Supabase"
# rp_id = "localhost"
# rp_origins = ["http://127.0.0.1:3000"]

[auth.rate_limit]
# Number of emails that can be sent per hour. Requires auth.email.smtp to be enabled.
email_sent = 2
# Number of SMS messages that can be sent per hour. Requires auth.sms to be enabled.
sms_sent = 30
# Number of anonymous sign-ins that can be made per hour per IP address. Requires enable_anonymous_sign_ins = true.
anonymous_users = 30
# Number of sessions that can be refreshed in a 5 minute interval per IP address.
token_refresh = 150
# Number of sign up and sign-in requests that can be made in a 5 minute interval per IP address (excludes anonymous users).
sign_in_sign_ups = 30
# Number of OTP / Magic link verifications that can be made in a 5 minute interval per IP address.
token_verifications = 30
# Number of Web3 logins that can be made in a 5 minute interval per IP address.
web3 = 30

# Configure one of the supported captcha providers: `hcaptcha`, `turnstile`.
# [auth.captcha]
# enabled = true
# provider = "hcaptcha"
# secret = ""

[auth.email]
# Keep this true: false turns off email sign-in altogether. Sign-ups are off for the whole project
# through [auth] enable_signup above (spec §9: one owner, no sign-ups).
enable_signup = true
# If enabled, a user will be required to confirm any email change on both the old, and new email
# addresses. If disabled, only the new email is required to confirm.
double_confirm_changes = true
# If enabled, users need to confirm their email address before signing in.
enable_confirmations = false
# If enabled, users will need to reauthenticate or have logged in recently to change their password.
secure_password_change = false
# Controls the minimum amount of time that must pass before sending another signup confirmation or password reset email.
max_frequency = "1s"
# Number of characters used in the email OTP.
otp_length = 6
# Number of seconds before the email OTP expires (defaults to 1 hour).
otp_expiry = 3600

# Use a production-ready SMTP server
# [auth.email.smtp]
# enabled = true
# host = "smtp.sendgrid.net"
# port = 587
# user = "apikey"
# pass = "env(SENDGRID_API_KEY)"
# admin_email = "admin@email.com"
# sender_name = "Admin"

# Uncomment to customize email template
# [auth.email.template.invite]
# subject = "You have been invited"
# content_path = "./supabase/templates/invite.html"

# Uncomment to customize notification email template
# [auth.email.notification.password_changed]
# enabled = true
# subject = "Your password has been changed"
# content_path = "./supabase/templates/password_changed_notification.html"

[auth.sms]
# Allow/disallow new user signups via SMS to your project.
enable_signup = false
# If enabled, users need to confirm their phone number before signing in.
enable_confirmations = false
# Template for sending OTP to users
template = "Your code is {{ .Code }}"
# Controls the minimum amount of time that must pass before sending another sms otp.
max_frequency = "5s"

# Use pre-defined map of phone number to OTP for testing.
# [auth.sms.test_otp]
# 4152127777 = "123456"

# Configure logged in session timeouts.
# [auth.sessions]
# Force log out after the specified duration.
# timebox = "24h"
# Force log out if the user has been inactive longer than the specified duration.
# inactivity_timeout = "8h"

# This hook runs before a new user is created and allows developers to reject the request based on the incoming user object.
# [auth.hook.before_user_created]
# enabled = true
# uri = "pg-functions://postgres/auth/before-user-created-hook"

# This hook runs before a token is issued and allows you to add additional claims based on the authentication method used.
# [auth.hook.custom_access_token]
# enabled = true
# uri = "pg-functions://<database>/<schema>/<hook_name>"

# Configure one of the supported SMS providers: `twilio`, `twilio_verify`, `messagebird`, `textlocal`, `vonage`.
[auth.sms.twilio]
enabled = false
account_sid = ""
message_service_sid = ""
# DO NOT commit your Twilio auth token to git. Use environment variable substitution instead:
auth_token = "env(SUPABASE_AUTH_SMS_TWILIO_AUTH_TOKEN)"

# Multi-factor-authentication is available to Supabase Pro plan.
[auth.mfa]
# Control how many MFA factors can be enrolled at once per user.
max_enrolled_factors = 10

# Control MFA via App Authenticator (TOTP)
[auth.mfa.totp]
enroll_enabled = false
verify_enabled = false

# Configure MFA via Phone Messaging
[auth.mfa.phone]
enroll_enabled = false
verify_enabled = false
otp_length = 6
template = "Your code is {{ .Code }}"
max_frequency = "5s"

# Configure MFA via WebAuthn
# [auth.mfa.web_authn]
# enroll_enabled = true
# verify_enabled = true

# Use an external OAuth provider. The full list of providers are: `apple`, `azure`, `bitbucket`,
# `discord`, `facebook`, `github`, `gitlab`, `google`, `keycloak`, `linkedin_oidc`, `notion`, `twitch`,
# `twitter`, `x`, `slack`, `spotify`, `workos`, `zoom`.
[auth.external.apple]
enabled = false
client_id = ""
# DO NOT commit your OAuth provider secret to git. Use environment variable substitution instead:
secret = "env(SUPABASE_AUTH_EXTERNAL_APPLE_SECRET)"
# Overrides the default auth callback URL derived from auth.external_url.
redirect_uri = ""
# Overrides the default auth provider URL. Used to support self-hosted gitlab, single-tenant Azure,
# or any other third-party OIDC providers.
url = ""
# If enabled, the nonce check will be skipped. Required for local sign in with Google auth.
skip_nonce_check = false
# If enabled, it will allow the user to successfully authenticate when the provider does not return an email address.
email_optional = false

# Allow Solana wallet holders to sign in to your project via the Sign in with Solana (SIWS, EIP-4361) standard.
# You can configure "web3" rate limit in the [auth.rate_limit] section and set up [auth.captcha] if self-hosting.
[auth.web3.solana]
enabled = false

# Use Firebase Auth as a third-party provider alongside Supabase Auth.
[auth.third_party.firebase]
enabled = false
# project_id = "my-firebase-project"

# Use Auth0 as a third-party provider alongside Supabase Auth.
[auth.third_party.auth0]
enabled = false
# tenant = "my-auth0-tenant"
# tenant_region = "us"

# Use AWS Cognito (Amplify) as a third-party provider alongside Supabase Auth.
[auth.third_party.aws_cognito]
enabled = false
# user_pool_id = "my-user-pool-id"
# user_pool_region = "us-east-1"

# Use Clerk as a third-party provider alongside Supabase Auth.
[auth.third_party.clerk]
enabled = false
# Obtain from https://clerk.com/setup/supabase
# domain = "example.clerk.accounts.dev"

# OAuth server configuration
[auth.oauth_server]
# Enable OAuth server functionality
enabled = false
# Path for OAuth consent flow UI
authorization_url_path = "/oauth/consent"
# Allow dynamic client registration
allow_dynamic_registration = false

[edge_runtime]
enabled = false
# Supported request policies: `oneshot`, `per_worker`.
# `per_worker` (default) — enables hot reload during local development.
# `oneshot` — fallback mode if hot reload causes issues (e.g. in large repos or with symlinks).
policy = "per_worker"
# Port to attach the Chrome inspector for debugging edge functions.
inspector_port = 8083
# The Deno major version to use.
deno_version = 2

# [edge_runtime.secrets]
# secret_key = "env(SECRET_VALUE)"

[analytics]
enabled = false
port = 54327
# Configure one of the supported backends: `postgres`, `bigquery`.
backend = "postgres"

# Experimental features may be deprecated any time
[experimental]
# Configures S3 bucket URL, eg. <bucket_name>.s3-<region>.amazonaws.com
s3_host = "env(S3_HOST)"
# Configures S3 bucket region, eg. us-east-1
s3_region = "env(S3_REGION)"
# Configures AWS_ACCESS_KEY_ID for S3 bucket
s3_access_key = "env(S3_ACCESS_KEY)"
# Configures AWS_SECRET_ACCESS_KEY for S3 bucket
s3_secret_key = "env(S3_SECRET_KEY)"

# pg-delta is the schema diff engine for db diff / db pull / db remote commit.
# Set enabled = false to fall back to the legacy migra engine.
[experimental.pgdelta]
enabled = true
# Directory under `supabase/` where declarative files are written.
# declarative_schema_path = "./schemas"
# JSON string passed through to pg-delta SQL formatting. When omitted, SQL is
# formatted with uppercase keywords, indent 2, max width 180, trailing commas,
# and column/key alignment. Set to "null" to emit raw, unformatted SQL.
# format_options = "{\"keywordCase\":\"upper\",\"indent\":2,\"maxWidth\":180,\"commaStyle\":\"trailing\"}"
```

`supabase/.gitignore`:

```gitignore
# Supabase
.branches
.temp

# dotenvx
.env.keys
.env.local
.env.*.local
```

Run: `npm run db:start` (Docker Desktop must be running; the first start pulls images for a few minutes)
Expected:
- `Applying migration 0001_schema.sql...` through `Applying migration 0006_price_history.sql...`;
- then a JSON status line with `"API_URL":"http://127.0.0.1:54321"`, `"DB_URL":"postgresql://postgres:postgres@127.0.0.1:54322/postgres"` and a `PUBLISHABLE_KEY`.

- [ ] **Step 10: Commit**

```bash
git add web/package.json web/package-lock.json web/tsconfig.json web/next.config.ts web/postcss.config.mjs \
  web/eslint.config.mjs web/vitest.config.mts web/.gitignore web/.env.example web/AGENTS.md web/CLAUDE.md \
  web/app web/lib supabase/config.toml supabase/.gitignore
git commit -m "feat: scaffold the dashboard with the Ledger theme and a local Supabase stack"
```

End the message with your `Co-Authored-By:` trailer.

---

### Task 2: Work out holdings at average cost and value them in CAD

**Files:**
- Create: `web/lib/portfolio/lookup.ts`, `web/lib/portfolio/ledger.ts`, `web/lib/portfolio/valuation.ts`
- Already there: `web/lib/portfolio/types.ts` (Task 1, Step 5)
- Test: `web/lib/portfolio/lookup.test.ts`, `web/lib/portfolio/ledger.test.ts`, `web/lib/portfolio/valuation.test.ts`

**Interfaces:**
- Consumes:
  - `lib/portfolio/types.ts`: `Trade`, `Close`, `Position`, `Sale`, `Account`, `ACCOUNT_LABELS`, `TAXABLE`, `assetKey(assetType, symbol)`;
  - `lib/dates.ts`: `daysBetween`;
  - `lib/symbols.ts`: `marketOf`.
- Produces:
  - `lib/portfolio/lookup.ts`: `onOrBefore(sorted, day)`; `class FxRates { rates; on(day); latest(); toCad(close, day?) }`; `class PriceBook { on(key, day); latest(key); days(key) }`.
  - `lib/portfolio/ledger.ts`: `QTY_EPSILON`, `tradeCad(trade, fx)`, `inOrder(trades)`, `positionKey(p)`, `buildLedger(trades, fx): { positions, sales, problems }`.
  - `lib/portfolio/valuation.ts`: `Holding`, `valueHoldings(positions, prices, fx)`, `totals(holdings)`, `Slice`, `breakdown(holdings, 'market' | 'account')`, `taxableEstimate(holding)`.

**The rules:**
- **Average cost** applies per account and asset. A sell takes cost out at the average. A day's buys count before its sells, and selling more than is held sells what is held, with a problem noted.
- **USD trades** are costed at their own rate. A USD trade with no rate (from before rev 2) uses the Bank of Canada rate of its day.
- **Valuation:**
  - The latest close, with USD closes converted at the latest rate.
  - An asset with no close yet is valued at cost.
  - Coins are valued from Coinbase's USD closes, as `daily_closes` stores them.

- [ ] **Step 1: Write the failing tests**

`web/lib/portfolio/lookup.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { FxRates, PriceBook, onOrBefore } from './lookup'

describe('onOrBefore', () => {
  const days = [{ day: '2026-10-01' }, { day: '2026-10-02' }, { day: '2026-10-05' }]

  it('finds the day itself, else the last day before it', () => {
    expect(onOrBefore(days, '2026-10-02')?.day).toBe('2026-10-02')
    expect(onOrBefore(days, '2026-10-04')?.day).toBe('2026-10-02')
    expect(onOrBefore(days, '2026-12-31')?.day).toBe('2026-10-05')
  })

  it('is null before the first day', () => {
    expect(onOrBefore(days, '2026-09-30')).toBeNull()
    expect(onOrBefore([], '2026-10-01')).toBeNull()
  })
})

describe('FxRates', () => {
  const fx = new FxRates([
    { day: '2026-10-02', usdCad: 1.37 },
    { day: '2026-10-01', usdCad: 1.36 },
  ])

  it('sorts its rates and carries the last one forward', () => {
    expect(fx.on('2026-10-04')).toBe(1.37)
    expect(fx.latest()).toEqual({ day: '2026-10-02', usdCad: 1.37 })
  })

  it('converts USD closes and leaves CAD closes alone', () => {
    expect(fx.toCad({ day: '2026-10-01', close: 100, currency: 'USD' })).toBeCloseTo(136)
    expect(fx.toCad({ day: '2026-10-01', close: 100, currency: 'CAD' })).toBe(100)
    expect(fx.toCad({ day: '2026-09-01', close: 100, currency: 'USD' })).toBeNull()
  })
})

describe('PriceBook', () => {
  const book = new PriceBook(
    new Map([
      [
        'stock:SPY',
        [
          { day: '2026-10-02', close: 510, currency: 'USD' as const },
          { day: '2026-10-01', close: 500, currency: 'USD' as const },
        ],
      ],
    ]),
  )

  it('carries a close forward over days without one', () => {
    expect(book.on('stock:SPY', '2026-10-03')?.close).toBe(510)
    expect(book.latest('stock:SPY')?.day).toBe('2026-10-02')
    expect(book.days('stock:SPY')).toEqual(['2026-10-01', '2026-10-02'])
  })

  it('knows nothing about an asset without closes', () => {
    expect(book.on('stock:XIU.TO', '2026-10-03')).toBeNull()
    expect(book.latest('crypto:BTC')).toBeNull()
  })
})
```

`web/lib/portfolio/ledger.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { buildLedger, tradeCad } from './ledger'
import { FxRates } from './lookup'
import type { Trade } from './types'

const FX = new FxRates([
  { day: '2026-09-01', usdCad: 1.35 },
  { day: '2026-10-01', usdCad: 1.4 },
])

const buy = (over: Partial<Trade>): Trade => ({
  side: 'buy',
  account: 'tfsa',
  symbol: 'RY.TO',
  assetType: 'stock',
  qty: 10,
  price: 100,
  currency: 'CAD',
  fxRateCad: null,
  day: '2026-09-02',
  ...over,
})
const sell = (over: Partial<Trade>): Trade => buy({ side: 'sell', ...over })

describe('tradeCad', () => {
  it('converts a USD trade at its own rate', () => {
    expect(tradeCad(buy({ currency: 'USD', fxRateCad: 1.38, price: 50 }), FX)).toBeCloseTo(690)
  })

  it('uses the Bank of Canada rate of the day when a USD trade has none', () => {
    expect(tradeCad(buy({ currency: 'USD', price: 50, day: '2026-10-05' }), FX)).toBeCloseTo(700)
  })

  it('is null for a USD trade older than every known rate', () => {
    expect(tradeCad(buy({ currency: 'USD', price: 50, day: '2026-08-01' }), FX)).toBeNull()
  })
})

describe('buildLedger', () => {
  it('averages the cost of buys and keeps the first buy day', () => {
    const { positions } = buildLedger(
      [buy({ qty: 10, price: 100 }), buy({ qty: 10, price: 120, day: '2026-09-20' })],
      FX,
    )
    expect(positions).toEqual([
      { account: 'tfsa', symbol: 'RY.TO', assetType: 'stock', qty: 20, costCad: 2200, openedOn: '2026-09-02' },
    ])
  })

  it('realizes a sell at average cost and keeps the rest at the same average', () => {
    const { positions, sales } = buildLedger(
      [buy({ qty: 10, price: 100 }), buy({ qty: 10, price: 120 }), sell({ qty: 5, price: 130, day: '2026-09-12' })],
      FX,
    )
    expect(sales).toEqual([
      {
        account: 'tfsa', symbol: 'RY.TO', assetType: 'stock', day: '2026-09-12',
        qty: 5, proceedsCad: 650, costCad: 550, gainCad: 100, heldDays: 10,
      },
    ])
    expect(positions[0].qty).toBe(15)
    expect(positions[0].costCad).toBeCloseTo(1650)
  })

  it('keeps each account apart', () => {
    const { positions } = buildLedger([buy({}), buy({ account: 'rrsp', price: 90 })], FX)
    expect(positions.map((p) => [p.account, p.costCad])).toEqual([
      ['tfsa', 1000],
      ['rrsp', 900],
    ])
  })

  it('closes a position sold in full, and a later buy opens a new one', () => {
    const { positions, sales } = buildLedger(
      [buy({}), sell({ day: '2026-09-10', price: 90 }), buy({ day: '2026-09-25', price: 80 })],
      FX,
    )
    expect(sales[0].gainCad).toBe(-100)
    expect(positions).toHaveLength(1)
    expect(positions[0]).toMatchObject({ qty: 10, costCad: 800, openedOn: '2026-09-25' })
  })

  it("counts a day's buys before its sells", () => {
    const { sales, problems } = buildLedger([sell({ day: '2026-09-02' }), buy({ day: '2026-09-02' })], FX)
    expect(problems).toEqual([])
    expect(sales).toHaveLength(1)
  })

  it('applies a sell of more than is held to what is held, and says so', () => {
    const { positions, sales, problems } = buildLedger([buy({ qty: 10 }), sell({ qty: 12, price: 110 })], FX)
    expect(positions).toEqual([])
    expect(sales[0]).toMatchObject({ qty: 10, proceedsCad: 1100, gainCad: 100 })
    expect(problems).toEqual(['RY.TO on 2026-09-02: sold 12 but held 10; counted as 10.'])
  })

  it('leaves out a sell with nothing held, and a USD trade with no known rate', () => {
    const { positions, problems } = buildLedger(
      [sell({}), buy({ symbol: 'AAPL', currency: 'USD', day: '2026-08-01' })],
      FX,
    )
    expect(positions).toEqual([])
    expect(problems).toEqual([
      'AAPL on 2026-08-01: no USD/CAD rate for that day, so it\'s left out.',
      "RY.TO on 2026-09-02: a sell with nothing held, so it's left out.",
    ])
  })

  it('closes a coin position whose leftover is a rounding error', () => {
    const coin = { symbol: 'BTC', assetType: 'crypto' as const, account: 'crypto' as const }
    const { positions } = buildLedger(
      [buy({ ...coin, qty: 0.1 }), buy({ ...coin, qty: 0.2 }), sell({ ...coin, qty: 0.30000000000000004 })],
      FX,
    )
    expect(positions).toEqual([])
  })
})
```

`web/lib/portfolio/valuation.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { FxRates, PriceBook } from './lookup'
import type { Close, Position } from './types'
import { breakdown, taxableEstimate, totals, valueHoldings } from './valuation'

const FX = new FxRates([
  { day: '2026-10-15', usdCad: 1.35 },
  { day: '2026-10-16', usdCad: 1.4 },
])
const usd = (day: string, close: number): Close => ({ day, close, currency: 'USD' })
const cad = (day: string, close: number): Close => ({ day, close, currency: 'CAD' })
const PRICES = new PriceBook(
  new Map([
    ['stock:AAPL', [usd('2026-10-15', 200), usd('2026-10-16', 210)]],
    ['stock:RY.TO', [cad('2026-10-16', 180)]],
    ['crypto:BTC', [usd('2026-10-17', 100000)]],
  ]),
)
const position = (over: Partial<Position>): Position => ({
  account: 'tfsa',
  symbol: 'AAPL',
  assetType: 'stock',
  qty: 10,
  costCad: 2500,
  openedOn: '2026-09-01',
  ...over,
})

describe('valueHoldings', () => {
  const [aapl, ry, btc, newco] = valueHoldings(
    [
      position({}),
      position({ symbol: 'RY.TO', costCad: 1900 }),
      position({ account: 'crypto', symbol: 'BTC', assetType: 'crypto', qty: 0.05, costCad: 6000 }),
      position({ symbol: 'NEWCO', qty: 5, costCad: 500 }),
    ],
    PRICES,
    FX,
  )

  it('converts a US close at the latest Bank of Canada rate', () => {
    expect(aapl).toMatchObject({ market: 'US', priceCad: 294, valueCad: 2940, gainCad: 440, priceDay: '2026-10-16' })
    expect(aapl.gainPct).toBeCloseTo(17.6)
  })

  it('takes a TSX close as is, and puts coins in no market', () => {
    expect(ry).toMatchObject({ market: 'TSX', valueCad: 1800, gainCad: -100 })
    expect(btc).toMatchObject({ market: null, valueCad: 7000, gainCad: 1000 })
  })

  it('values an asset with no close yet at cost', () => {
    expect(newco).toMatchObject({ priceCad: null, priceDay: null, valueCad: 500, gainCad: 0, gainPct: 0 })
  })

  it('adds up, naming what is valued at cost', () => {
    expect(totals([aapl, ry, btc, newco])).toEqual({
      valueCad: 12240,
      costCad: 10900,
      gainCad: 1340,
      unpriced: ['NEWCO'],
    })
  })

  it('splits value by market and by account', () => {
    const shares = (slices: { label: string; share: number }[]) =>
      slices.map((s) => [s.label, Math.round(s.share * 10) / 10])
    // 2,940 + 1,800 + 7,000 = 11,740
    expect(shares(breakdown([aapl, ry, btc], 'market'))).toEqual([
      ['Crypto', 59.6],
      ['US', 25],
      ['TSX', 15.3],
    ])
    expect(shares(breakdown([aapl, ry, btc], 'account'))).toEqual([
      ['Crypto', 59.6],
      ['TFSA', 40.4],
    ])
    expect(breakdown([], 'market')).toEqual([])
  })

  it('estimates tax on gains in taxable accounts only', () => {
    expect(taxableEstimate(btc)).toBe(500)
    expect(taxableEstimate(aapl)).toBeNull()
  })
})
```

- [ ] **Step 2: Run them and see them fail**

Run: `npm test -- lib/portfolio`
Expected: `Test Files  3 failed (3)`: `Error: Cannot find module './ledger'` for the ledger tests, and `Error: Cannot find module './lookup'` for the other two.

- [ ] **Step 3: Write the modules**

`web/lib/portfolio/lookup.ts`:

```ts
import type { Close } from './types'

/**
 * The last entry on or before `day` in a list sorted by day, or null.
 * Prices and the Bank of Canada rate carry forward over weekends and holidays.
 */
export function onOrBefore<T extends { day: string }>(sorted: readonly T[], day: string): T | null {
  let lo = 0
  let hi = sorted.length - 1
  let found: T | null = null
  while (lo <= hi) {
    const mid = (lo + hi) >> 1
    if (sorted[mid].day <= day) {
      found = sorted[mid]
      lo = mid + 1
    } else {
      hi = mid - 1
    }
  }
  return found
}

export interface FxRate {
  day: string
  usdCad: number
}

/** USD/CAD by day (`fx_rates`), sorted. */
export class FxRates {
  readonly rates: readonly FxRate[]

  constructor(rates: readonly FxRate[]) {
    this.rates = [...rates].sort((a, b) => (a.day < b.day ? -1 : a.day > b.day ? 1 : 0))
  }

  /** The rate in effect on `day`: that day's, else the last one before it. */
  on(day: string): number | null {
    return onOrBefore(this.rates, day)?.usdCad ?? null
  }

  latest(): FxRate | null {
    return this.rates.at(-1) ?? null
  }

  /** A close in CAD, or null when it's in USD and no rate is known yet. */
  toCad(close: Close, day: string = close.day): number | null {
    if (close.currency === 'CAD') return close.close
    const rate = this.on(day)
    return rate === null ? null : close.close * rate
  }
}

/** Each asset's closes, sorted by day, keyed by `assetKey`. */
export class PriceBook {
  private readonly byKey: Map<string, Close[]>

  constructor(closes: ReadonlyMap<string, readonly Close[]>) {
    this.byKey = new Map(
      [...closes].map(([key, list]) => [key, [...list].sort((a, b) => (a.day < b.day ? -1 : a.day > b.day ? 1 : 0))]),
    )
  }

  on(key: string, day: string): Close | null {
    return onOrBefore(this.byKey.get(key) ?? [], day)
  }

  latest(key: string): Close | null {
    return this.byKey.get(key)?.at(-1) ?? null
  }

  days(key: string): string[] {
    return (this.byKey.get(key) ?? []).map((c) => c.day)
  }
}
```

`web/lib/portfolio/ledger.ts`:

```ts
import { daysBetween } from '../dates'
import type { FxRates } from './lookup'
import type { Position, Sale, Trade } from './types'

/** Below this, a quantity is a rounding leftover and the position is closed. */
export const QTY_EPSILON = 1e-9

/**
 * A trade's amount in CAD. A USD trade uses its own rate; trades recorded before spec rev 2 have
 * none, so they use the Bank of Canada rate of that day. Null when no rate is known.
 */
export function tradeCad(trade: Trade, fx: FxRates): number | null {
  const amount = trade.qty * trade.price
  if (trade.currency === 'CAD') return amount
  const rate = trade.fxRateCad ?? fx.on(trade.day)
  return rate === null ? null : amount * rate
}

/** Trades in the order they count: by day, and a day's buys before its sells. */
export function inOrder(trades: readonly Trade[]): Trade[] {
  return [...trades].sort((a, b) => {
    if (a.day !== b.day) return a.day < b.day ? -1 : 1
    if (a.side !== b.side) return a.side === 'buy' ? -1 : 1
    return 0
  })
}

export const positionKey = (p: Pick<Trade, 'account' | 'assetType' | 'symbol'>): string =>
  `${p.account}:${p.assetType}:${p.symbol}`

export interface Ledger {
  /** Open positions, by account and asset. */
  positions: Position[]
  /** Every sell, at average cost. */
  sales: Sale[]
  /** Trades that couldn't be applied as entered, in plain words. */
  problems: string[]
}

/**
 * Average cost (adjusted cost base) per account and asset, as Canadian tax rules require
 * (spec §7.1). A sell reduces the quantity at average cost; its gain is proceeds minus average
 * cost × quantity, in CAD. A sell of more than is held is applied to what is held.
 */
export function buildLedger(trades: readonly Trade[], fx: FxRates): Ledger {
  const open = new Map<string, Position>()
  const sales: Sale[] = []
  const problems: string[] = []

  for (const trade of inOrder(trades)) {
    const key = positionKey(trade)
    const cad = tradeCad(trade, fx)
    if (cad === null) {
      problems.push(`${trade.symbol} on ${trade.day}: no USD/CAD rate for that day, so it's left out.`)
      continue
    }
    const held = open.get(key)
    if (trade.side === 'buy') {
      if (held) {
        held.qty += trade.qty
        held.costCad += cad
      } else {
        open.set(key, {
          account: trade.account,
          symbol: trade.symbol,
          assetType: trade.assetType,
          qty: trade.qty,
          costCad: cad,
          openedOn: trade.day,
        })
      }
      continue
    }
    if (!held) {
      problems.push(`${trade.symbol} on ${trade.day}: a sell with nothing held, so it's left out.`)
      continue
    }
    let qty = trade.qty
    let proceeds = cad
    if (qty > held.qty + QTY_EPSILON) {
      problems.push(
        `${trade.symbol} on ${trade.day}: sold ${trade.qty} but held ${held.qty}; counted as ${held.qty}.`,
      )
      proceeds = (cad * held.qty) / qty
      qty = held.qty
    }
    const cost = (held.costCad * qty) / held.qty
    sales.push({
      account: trade.account,
      symbol: trade.symbol,
      assetType: trade.assetType,
      day: trade.day,
      qty,
      proceedsCad: proceeds,
      costCad: cost,
      gainCad: proceeds - cost,
      heldDays: daysBetween(held.openedOn, trade.day),
    })
    held.qty -= qty
    held.costCad -= cost
    if (held.qty <= QTY_EPSILON) open.delete(key)
  }

  return { positions: [...open.values()], sales, problems }
}
```

`web/lib/portfolio/valuation.ts`:

```ts
import { marketOf } from '../symbols'
import type { FxRates, PriceBook } from './lookup'
import { ACCOUNT_LABELS, TAXABLE, assetKey } from './types'
import type { Account, Market, Position } from './types'

export interface Holding extends Position {
  market: Market | null
  /** The latest close, in CAD at the latest Bank of Canada rate; null before the first close. */
  priceCad: number | null
  priceDay: string | null
  /** At the latest close; at cost when there's no close yet. */
  valueCad: number
  gainCad: number
  gainPct: number
}

/**
 * Values each position at its latest close. USD closes (US stocks, and coins, which Coinbase
 * prices in USD) convert at the latest Bank of Canada rate (spec §7.4).
 */
export function valueHoldings(positions: readonly Position[], prices: PriceBook, fx: FxRates): Holding[] {
  const rate = fx.latest()?.usdCad ?? null
  return positions.map((position) => {
    const close = prices.latest(assetKey(position.assetType, position.symbol))
    const priceCad =
      close === null ? null : close.currency === 'CAD' ? close.close : rate === null ? null : close.close * rate
    const valueCad = priceCad === null ? position.costCad : position.qty * priceCad
    const gainCad = valueCad - position.costCad
    return {
      ...position,
      market: position.assetType === 'stock' ? marketOf(position.symbol) : null,
      priceCad,
      priceDay: priceCad === null ? null : (close?.day ?? null),
      valueCad,
      gainCad,
      gainPct: position.costCad > 0 ? (gainCad / position.costCad) * 100 : 0,
    }
  })
}

export interface Totals {
  valueCad: number
  costCad: number
  gainCad: number
  /** Symbols valued at cost because they have no close yet. */
  unpriced: string[]
}

export function totals(holdings: readonly Holding[]): Totals {
  const valueCad = holdings.reduce((sum, h) => sum + h.valueCad, 0)
  const costCad = holdings.reduce((sum, h) => sum + h.costCad, 0)
  const unpriced = [...new Set(holdings.filter((h) => h.priceCad === null).map((h) => h.symbol))].sort()
  return { valueCad, costCad, gainCad: valueCad - costCad, unpriced }
}

export interface Slice {
  label: string
  share: number
}

/** Shares of portfolio value by market (US, TSX, Crypto) or by account, largest first. */
export function breakdown(holdings: readonly Holding[], by: 'market' | 'account'): Slice[] {
  const total = holdings.reduce((sum, h) => sum + h.valueCad, 0)
  if (total <= 0) return []
  const sums = new Map<string, number>()
  for (const h of holdings) {
    const label = by === 'market' ? (h.market ?? 'Crypto') : ACCOUNT_LABELS[h.account as Account]
    sums.set(label, (sums.get(label) ?? 0) + h.valueCad)
  }
  return [...sums]
    .map(([label, value]) => ({ label, share: (value / total) * 100 }))
    .sort((a, b) => b.share - a.share)
}

/** The estimated taxable amount of an unrealized gain or loss: 50% inclusion (spec §7.5). */
export const taxableEstimate = (h: Holding): number | null => (TAXABLE.has(h.account) ? h.gainCad * 0.5 : null)
```

- [ ] **Step 4: Run the tests**

Run: `npm test`
Expected: `Test Files  5 passed (5)`, `Tests  32 passed (32)`. Then `npm run lint` and `npm run typecheck` are clean.

- [ ] **Step 5: Commit**

```bash
git add web/lib/portfolio
git commit -m "feat: work out holdings at average cost and value them in CAD"
```

End the message with your `Co-Authored-By:` trailer.

---

### Task 3: Compute returns against XIU.TO and SPY, the tax warnings, and the page's view

**Files:**
- Create: `web/lib/portfolio/returns.ts`, `web/lib/portfolio/warnings.ts`, `web/lib/portfolio/view.ts`
- Test: `web/lib/portfolio/returns.test.ts`, `web/lib/portfolio/warnings.test.ts`, `web/lib/portfolio/view.test.ts`

**Interfaces:**
- Consumes:
  - Task 2's `lookup`, `ledger` and `valuation`;
  - `lib/format.ts` `fmtMoney`;
  - `lib/dates.ts` `addDays`, `longDay`, `shortDay`;
  - `lib/symbols.ts` `tradeCurrency`.
- Produces:
  - `lib/portfolio/returns.ts`: `BENCHMARKS`, `Growth`, `growth(trades, prices, fx): Growth | null`, `Period` (`'1m' | '3m' | '12m' | 'all'`), `PERIODS`, `PeriodReturns`, `periodReturns(growth, period)`.
  - `lib/portfolio/warnings.ts`: `Warning`, `TfsaGuideline`, `ROUND_TRIP_WARN_AT` (0.75), `MIN_SALES_FOR_SHARE` (4), `tfsaWarnings(sales, guideline, today)`, `superficialLossWarnings(sales, trades, today)`.
  - `lib/portfolio/view.ts`: `Note`, `HoldingRow`, `SellOption`, `PortfolioView`, `PortfolioInputs`, `portfolioView(inputs, today)`.

**The rules:**
- **Returns** are time-weighted. Each day's return is (close value + sell proceeds) / (yesterday's value + buy cost) − 1. That is:
  - buys count from the start of their day, and sells at the close;
  - the trading days are the benchmarks' days;
  - a trade on a non-trading day counts on the next trading day;
  - SPY converts to CAD at each day's rate.
- **Periods:** 1M, 3M and 12M are the last 21, 63 and 252 trading days, and each line starts at 0. "All" measures the portfolio from cost.
- **TFSA (spec §7.5):**
  - Each TFSA sell in the last 12 months is a round trip, and the warning appears at 75% of the guideline.
  - A second warning appears when more than the guideline's share of holds lasted under 30 days, once there are at least four.
- **Superficial loss:** a loss in a taxable account within the last 30 days triggers a warning. If the asset was bought within 30 days either side of the sale and is still held, the loss is likely denied.

- [ ] **Step 1: Write the failing tests**

`web/lib/portfolio/returns.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { FxRates, PriceBook } from './lookup'
import { growth, periodReturns } from './returns'
import type { Close, Trade } from './types'

const FX = new FxRates([
  { day: '2026-10-01', usdCad: 1.4 },
  { day: '2026-10-05', usdCad: 1.5 },
])
const series = (currency: 'USD' | 'CAD', points: [string, number][]): Close[] =>
  points.map(([day, close]) => ({ day, close, currency }))
const DAYS = ['2026-10-01', '2026-10-02', '2026-10-05', '2026-10-06']
const flat = (value: number) => DAYS.map((day): [string, number] => [day, value])

const book = (extra: [string, Close[]][] = []) =>
  new PriceBook(
    new Map([
      ['stock:XIU.TO', series('CAD', [['2026-10-01', 40], ['2026-10-02', 41], ['2026-10-05', 42], ['2026-10-06', 44]])],
      ['stock:SPY', series('USD', flat(500))],
      ...extra,
    ]),
  )
const trade = (over: Partial<Trade>): Trade => ({
  side: 'buy',
  account: 'tfsa',
  symbol: 'RY.TO',
  assetType: 'stock',
  qty: 10,
  price: 100,
  currency: 'CAD',
  fxRateCad: null,
  day: '2026-10-01',
  ...over,
})

describe('growth', () => {
  it('is null without trades or without any closes', () => {
    expect(growth([], book(), FX)).toBeNull()
    expect(growth([trade({})], new PriceBook(new Map()), FX)).toBeNull()
  })

  it("measures from the buy price, on the benchmarks' trading days", () => {
    const prices = book([['stock:RY.TO', series('CAD', [['2026-10-01', 101], ['2026-10-02', 103], ['2026-10-06', 110]])]])
    const g = growth([trade({})], prices, FX)!
    expect(g.days).toEqual(DAYS)
    // 1000 paid; closes 1010, 1030, 1030 (carried over Oct 5), 1100.
    expect(g.portfolio.map((v) => +v.toFixed(4))).toEqual([1.01, 1.03, 1.03, 1.1])
    expect(g.xiu).toEqual([1, 41 / 40, 42 / 40, 44 / 40])
  })

  it('converts SPY to CAD at each day\'s rate', () => {
    const g = growth([trade({})], book([['stock:RY.TO', series('CAD', flat(100))]]), FX)!
    // SPY is flat in USD, but USD/CAD went from 1.40 to 1.50 on Oct 5.
    expect(g.spy!.map((v) => +v.toFixed(4))).toEqual([1, 1, 1.0714, 1.0714])
  })

  it("doesn't count money put in or taken out as a return", () => {
    const prices = book([['stock:RY.TO', series('CAD', [['2026-10-01', 100], ['2026-10-02', 110], ['2026-10-05', 110], ['2026-10-06', 121]])]])
    const g = growth(
      [
        trade({}),
        trade({ day: '2026-10-02', qty: 10, price: 110 }), // doubles the position at the close price
        trade({ side: 'sell', day: '2026-10-05', qty: 15, price: 110 }),
      ],
      prices,
      FX,
    )!
    // Oct 2: the 1,100 put in counts from the start of the day, so 2,200 / (1,000 + 1,100).
    // Oct 5: a sell at the close changes nothing. Oct 6: the 5 shares left gain 10%.
    expect(g.portfolio.map((v) => +v.toFixed(4))).toEqual([1, 1.0476, 1.0476, 1.1524])
  })

  it("doesn't let a big buy into a small position inflate the day's return", () => {
    const prices = book([['stock:RY.TO', series('CAD', [['2026-10-01', 100], ['2026-10-02', 101]])]])
    const g = growth([trade({ qty: 1 }), trade({ day: '2026-10-02', qty: 1000, price: 100 })], prices, FX)!
    // 100 held, then 100,000 more bought: the day's 1% move is ~1%, not 1,000%.
    expect(g.portfolio[1]).toBeCloseTo(1.01, 4)
  })

  it('counts a weekend coin buy on the next trading day and values it at cost until it has a close', () => {
    const prices = book([['crypto:BTC', series('USD', [['2026-10-05', 70000], ['2026-10-06', 77000]])]])
    const g = growth(
      [trade({ account: 'crypto', symbol: 'BTC', assetType: 'crypto', qty: 0.01, price: 98000, day: '2026-10-03' })],
      prices,
      FX,
    )!
    expect(g.days).toEqual(['2026-10-05', '2026-10-06'])
    // 980 paid; 0.01 × 70,000 × 1.5 = 1050, then 1155.
    expect(g.portfolio.map((v) => +v.toFixed(4))).toEqual([1.0714, 1.1786])
  })

  it('keeps the value at cost for an asset that never had a close', () => {
    const g = growth([trade({ symbol: 'NEWCO' })], book(), FX)!
    expect(g.portfolio).toEqual([1, 1, 1, 1])
  })

  it("leaves out a benchmark without a close on the first day", () => {
    const prices = new PriceBook(new Map([['stock:RY.TO', series('CAD', flat(100))]]))
    const g = growth([trade({})], prices, FX)!
    expect(g.xiu).toBeNull()
    expect(g.spy).toBeNull()
    expect(g.days).toEqual(DAYS)
  })
})

describe('periodReturns', () => {
  const g = {
    days: Array.from({ length: 30 }, (_, i) => `d${String(i).padStart(2, '0')}`),
    portfolio: Array.from({ length: 30 }, (_, i) => 1.1 + i * 0.01),
    xiu: Array.from({ length: 30 }, (_, i) => 1 + i * 0.02),
    spy: null,
  }

  it('measures "all" from cost for the portfolio and from the first close for benchmarks', () => {
    const all = periodReturns(g, 'all')
    expect(all.days).toHaveLength(30)
    expect(all.portfolio[0]).toBeCloseTo(10)
    expect(all.xiu![0]).toBe(0)
    expect(all.xiu!.at(-1)).toBeCloseTo(58)
    expect(all.spy).toBeNull()
  })

  it('starts every line at 0 over the last 21 trading days', () => {
    const month = periodReturns(g, '1m')
    expect(month.days).toHaveLength(22)
    expect(month.days[0]).toBe('d08')
    expect(month.portfolio[0]).toBe(0)
    expect(month.portfolio.at(-1)).toBeCloseTo(((1.39 / 1.18) - 1) * 100)
  })

  it('uses the whole history when it is shorter than the period', () => {
    expect(periodReturns(g, '12m').days).toHaveLength(30)
  })
})
```

`web/lib/portfolio/warnings.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import type { Sale, Trade } from './types'
import { superficialLossWarnings, tfsaWarnings } from './warnings'

const TODAY = '2026-10-16'
const sale = (over: Partial<Sale>): Sale => ({
  account: 'tfsa',
  symbol: 'RY.TO',
  assetType: 'stock',
  day: '2026-09-01',
  qty: 1,
  proceedsCad: 100,
  costCad: 90,
  gainCad: 10,
  heldDays: 60,
  ...over,
})
const GUIDE = { roundTrips: 24, shortHoldShare: 0.5 }

describe('tfsaWarnings', () => {
  it('stays quiet below 75% of the round-trip guideline', () => {
    expect(tfsaWarnings(Array.from({ length: 17 }, () => sale({})), GUIDE, TODAY)).toEqual([])
  })

  it('warns at 18 of 24 round trips in the last 12 months', () => {
    const sales = [...Array.from({ length: 18 }, () => sale({})), sale({ day: '2025-10-16' })]
    expect(tfsaWarnings(sales, GUIDE, TODAY)).toEqual([
      {
        title: 'TFSA: 18 round trips in 12 months',
        detail: 'Your guideline is 24. Frequent TFSA trading can make gains taxable as business income.',
      },
    ])
  })

  it('warns when most of at least four holds lasted under 30 days', () => {
    const sales = [sale({ heldDays: 3 }), sale({ heldDays: 12 }), sale({ heldDays: 29 }), sale({ heldDays: 30 })]
    expect(tfsaWarnings(sales, GUIDE, TODAY).map((w) => w.title)).toEqual(['TFSA: 3 of 4 holds under 30 days'])
    expect(tfsaWarnings(sales.slice(0, 3), GUIDE, TODAY)).toEqual([])
  })

  it('ignores sells in other accounts', () => {
    expect(tfsaWarnings(Array.from({ length: 30 }, () => sale({ account: 'rrsp' })), GUIDE, TODAY)).toEqual([])
  })
})

describe('superficialLossWarnings', () => {
  const coin = { account: 'crypto' as const, symbol: 'ETH', assetType: 'crypto' as const }
  const loss = sale({ ...coin, day: '2026-10-03', gainCad: -540 })
  const trade = (over: Partial<Trade>): Trade => ({
    side: 'buy', ...coin, qty: 1, price: 4000, currency: 'CAD', fxRateCad: null, day: '2026-06-01', ...over,
  })

  it('names the window after a loss in a taxable account', () => {
    const trades = [trade({}), trade({ side: 'sell', day: '2026-10-03' })]
    expect(superficialLossWarnings([loss], trades, TODAY)).toEqual([
      {
        symbol: 'ETH',
        title: 'ETH: superficial-loss window',
        detail: 'You sold ETH at a loss on Oct 3, 2026. Buying it back before Nov 2, 2026 denies that loss.',
        note: 'Loss window to Nov 2',
      },
    ])
  })

  it('says the loss is likely denied after a buy in the window that is still held', () => {
    const trades = [trade({}), trade({ side: 'sell', day: '2026-10-03' }), trade({ day: '2026-10-10' })]
    expect(superficialLossWarnings([loss], trades, TODAY)[0]).toMatchObject({
      title: 'ETH: the loss is likely superficial',
      note: 'Loss likely denied',
    })
  })

  it('treats a buy days before the sale as the position itself when nothing is left', () => {
    const trades = [trade({ day: '2026-09-25' }), trade({ side: 'sell', day: '2026-10-03' })]
    const sold = sale({ ...coin, day: '2026-10-03', gainCad: -100 })
    expect(superficialLossWarnings([sold], trades, TODAY)[0].title).toBe('ETH: superficial-loss window')
  })

  it('skips gains, sheltered accounts and sales older than 30 days', () => {
    expect(
      superficialLossWarnings(
        [sale({ ...coin, day: '2026-10-03', gainCad: 5 }), sale({ day: '2026-10-03', gainCad: -50 }), sale({ ...coin, day: '2026-09-15', gainCad: -50 })],
        [],
        TODAY,
      ),
    ).toEqual([])
  })
})
```

`web/lib/portfolio/view.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { FxRates, PriceBook } from './lookup'
import type { Close, Trade } from './types'
import { portfolioView } from './view'

const TODAY = '2026-10-16'
const FX = new FxRates([{ day: '2026-09-01', usdCad: 1.4 }])
const closes = (currency: 'USD' | 'CAD', values: [string, number][]): Close[] =>
  values.map(([day, close]) => ({ day, close, currency }))
const PRICES = new PriceBook(
  new Map([
    ['stock:XIU.TO', closes('CAD', [['2026-09-01', 40], ['2026-10-16', 42]])],
    ['stock:SPY', closes('USD', [['2026-09-01', 500], ['2026-10-16', 520]])],
    ['stock:AAPL', closes('USD', [['2026-09-01', 200], ['2026-10-16', 220]])],
    ['crypto:ETH', closes('USD', [['2026-09-01', 3000], ['2026-10-16', 2800]])],
  ]),
)
const trade = (over: Partial<Trade>): Trade => ({
  side: 'buy',
  account: 'tfsa',
  symbol: 'AAPL',
  assetType: 'stock',
  qty: 10,
  price: 200,
  currency: 'USD',
  fxRateCad: 1.4,
  day: '2026-09-01',
  ...over,
})
const coin = { account: 'crypto' as const, symbol: 'ETH', assetType: 'crypto' as const, currency: 'CAD' as const, fxRateCad: null }
const TRADES = [
  trade({}),
  trade({ ...coin, qty: 2, price: 4200 }),
  trade({ ...coin, side: 'sell', qty: 1, price: 3900, day: '2026-10-03' }),
  trade({ symbol: 'NEWCO', qty: 5, price: 10 }),
]
const view = portfolioView(
  {
    trades: TRADES,
    prices: PRICES,
    fx: FX,
    names: new Map([['AAPL', 'Apple Inc.']]),
    guideline: { roundTrips: 24, shortHoldShare: 0.5 },
  },
  TODAY,
)

describe('portfolioView', () => {
  it('values and orders the holdings, largest first', () => {
    // ETH 1 × 2,800 × 1.4; AAPL 10 × 220 × 1.4; NEWCO has no close, so its cost, 5 × 10 × 1.4.
    expect(view.holdings.map((h) => [h.symbol, h.name, h.market, Math.round(h.valueCad)])).toEqual([
      ['ETH', null, null, 3920],
      ['AAPL', 'Apple Inc.', 'US', 3080],
      ['NEWCO', null, 'US', 70],
    ])
    expect(Math.round(view.totals.valueCad)).toBe(7070)
    expect(view.accounts).toEqual(['Crypto', 'TFSA'])
  })

  it('notes a holding valued at cost, a loss window and the taxable estimate', () => {
    const notes = Object.fromEntries(view.holdings.map((h) => [h.symbol, h.notes]))
    expect(notes.NEWCO).toEqual([{ text: 'No close yet; at cost', warn: true }])
    // ETH: 1 left at 4,200 cost, worth 2,800 × 1.4 = 3,920; the Oct 3 sell lost 300.
    expect(notes.ETH).toEqual([
      { text: 'Loss window to Nov 2', warn: true },
      { text: 'Taxable: est. −C$140', warn: false },
    ])
    expect(notes.AAPL).toEqual([])
  })

  it('lists the warnings that need no model', () => {
    expect(view.warnings.map((w) => w.title)).toEqual(['ETH: superficial-loss window'])
  })

  it('draws every period once there are two trading days', () => {
    expect(view.periods?.all.days).toEqual(['2026-09-01', '2026-10-16'])
    expect(view.firstBuy).toBe('2026-09-01')
    expect(view.fx).toEqual({ day: '2026-09-01', usdCad: 1.4 })
  })

  it('offers each open position for a sell, in its trade currency', () => {
    expect(view.sellable.map((s) => [s.key, s.qty, s.currency])).toEqual([
      ['tfsa:stock:AAPL', 10, 'USD'],
      ['crypto:crypto:ETH', 1, 'CAD'],
      ['tfsa:stock:NEWCO', 5, 'USD'],
    ])
  })

  it('is empty without trades', () => {
    const empty = portfolioView(
      { trades: [], prices: PRICES, fx: FX, names: new Map(), guideline: { roundTrips: 24, shortHoldShare: 0.5 } },
      TODAY,
    )
    expect(empty.holdings).toEqual([])
    expect(empty.periods).toBeNull()
    expect(empty.firstBuy).toBeNull()
    expect(empty.totals.valueCad).toBe(0)
  })
})
```

- [ ] **Step 2: Run them and see them fail**

Run: `npm test -- lib/portfolio/returns.test.ts lib/portfolio/warnings.test.ts lib/portfolio/view.test.ts`
Expected: `Test Files  3 failed (3)`, with `Error: Cannot find module './returns'`, `'./warnings'` and `'./view'`.

- [ ] **Step 3: Write the modules**

`web/lib/portfolio/returns.ts`:

```ts
import { QTY_EPSILON, inOrder, tradeCad } from './ledger'
import type { FxRates, PriceBook } from './lookup'
import { assetKey } from './types'
import type { Trade } from './types'

export const BENCHMARKS = { xiu: assetKey('stock', 'XIU.TO'), spy: assetKey('stock', 'SPY') } as const

/**
 * Growth of 1 C$ over the trading days since the first buy: the portfolio's, and XIU.TO's and
 * SPY's in CAD. A benchmark is null when it has no close on the first day.
 */
export interface Growth {
  days: string[]
  portfolio: number[]
  xiu: number[] | null
  spy: number[] | null
}

/** The days to measure on: the benchmarks' trading days, else the held assets', from the first buy on. */
function tradingDays(trades: readonly Trade[], prices: PriceBook, start: string): string[] {
  const pick = (keys: string[]) =>
    [...new Set(keys.flatMap((key) => prices.days(key)))].filter((day) => day >= start).sort()
  const benchmarkDays = pick([BENCHMARKS.xiu, BENCHMARKS.spy])
  if (benchmarkDays.length > 0) return benchmarkDays
  return pick([...new Set(trades.map((t) => assetKey(t.assetType, t.symbol)))])
}

/**
 * Time-weighted growth, so buys and sells don't count as gains or losses. Each day's return is
 * (value at the close + sell proceeds) / (yesterday's value + buy cost) − 1: buys put money in
 * before the close, sells take it out after. Trades on days without a close (a coin bought on a
 * Saturday) count on the next trading day. An asset without a close yet is valued at cost.
 */
export function growth(trades: readonly Trade[], prices: PriceBook, fx: FxRates): Growth | null {
  const ordered = inOrder(trades)
  if (ordered.length === 0) return null
  const days = tradingDays(ordered, prices, ordered[0].day)
  if (days.length === 0) return null

  const held = new Map<string, { qty: number; costCad: number }>()
  const portfolio: number[] = []
  let next = 0
  let lastValue = 0
  let index = 1
  for (const day of days) {
    let bought = 0
    let sold = 0
    for (; next < ordered.length && ordered[next].day <= day; next += 1) {
      const trade = ordered[next]
      const cad = tradeCad(trade, fx)
      if (cad === null) continue
      const key = assetKey(trade.assetType, trade.symbol)
      const asset = held.get(key) ?? { qty: 0, costCad: 0 }
      if (trade.side === 'buy') {
        asset.qty += trade.qty
        asset.costCad += cad
        bought += cad
      } else if (asset.qty > QTY_EPSILON) {
        const qty = Math.min(trade.qty, asset.qty)
        asset.costCad -= (asset.costCad * qty) / asset.qty
        asset.qty -= qty
        sold += (cad * qty) / trade.qty
      }
      held.set(key, asset)
    }
    let value = 0
    for (const [key, asset] of held) {
      if (asset.qty <= QTY_EPSILON) continue
      const close = prices.on(key, day)
      const cad = close === null ? null : fx.toCad(close, day)
      value += cad === null ? asset.costCad : asset.qty * cad
    }
    const invested = lastValue + bought
    index *= invested > 0 ? (value + sold) / invested : 1
    portfolio.push(index)
    lastValue = value
  }

  const benchmark = (key: string): number[] | null => {
    const inCad = days.map((day) => {
      const close = prices.on(key, day)
      return close === null ? null : fx.toCad(close, day)
    })
    const first = inCad[0]
    if (first === null || first === undefined) return null
    let last = first
    return inCad.map((v) => {
      last = v ?? last
      return last / first
    })
  }
  return { days, portfolio, xiu: benchmark(BENCHMARKS.xiu), spy: benchmark(BENCHMARKS.spy) }
}

export type Period = '1m' | '3m' | '12m' | 'all'
export const PERIODS: readonly Period[] = ['1m', '3m', '12m', 'all']
const TRADING_DAYS: Record<Exclude<Period, 'all'>, number> = { '1m': 21, '3m': 63, '12m': 252 }

/** A period's returns in percent, each line starting at 0 (the portfolio's "all" starts at cost). */
export interface PeriodReturns {
  days: string[]
  portfolio: number[]
  xiu: number[] | null
  spy: number[] | null
}

export function periodReturns(g: Growth, period: Period): PeriodReturns {
  const start = period === 'all' ? 0 : Math.max(0, g.days.length - 1 - TRADING_DAYS[period])
  const pct = (values: number[], base: number) => values.slice(start).map((v) => (v / base - 1) * 100)
  return {
    days: g.days.slice(start),
    // Over the whole history the portfolio is measured from what was paid, so the first day's
    // move from the buy price to the close counts; benchmarks start at their first close.
    portfolio: pct(g.portfolio, period === 'all' ? 1 : g.portfolio[start]),
    xiu: g.xiu && pct(g.xiu, g.xiu[start]),
    spy: g.spy && pct(g.spy, g.spy[start]),
  }
}
```

`web/lib/portfolio/warnings.ts`:

```ts
import { addDays, longDay, shortDay } from '../dates'
import { QTY_EPSILON, inOrder } from './ledger'
import { TAXABLE } from './types'
import type { Sale, Trade } from './types'

export interface Warning {
  title: string
  detail: string
  /** The holding the warning is about, for the holdings table's notes. */
  symbol?: string
  note?: string
}

export interface TfsaGuideline {
  roundTrips: number
  /** Share of holds under 30 days, 0..1. */
  shortHoldShare: number
}

/** Warn this far ahead of the round-trip guideline. */
export const ROUND_TRIP_WARN_AT = 0.75
/** Too few sells to call holds "mostly short". */
export const MIN_SALES_FOR_SHARE = 4
const SHORT_HOLD_DAYS = 30

/**
 * TFSA trading frequency (spec §7.5): each TFSA sell in the last 12 months closes a round trip.
 * Warns as round trips reach 75% of the owner's guideline, and when more than the guideline's
 * share of those holds lasted under 30 days (once there are at least four).
 */
export function tfsaWarnings(sales: readonly Sale[], guideline: TfsaGuideline, today: string): Warning[] {
  const since = addDays(today, -365)
  const recent = sales.filter((s) => s.account === 'tfsa' && s.day > since && s.day <= today)
  const warnings: Warning[] = []
  if (recent.length > 0 && recent.length >= Math.ceil(guideline.roundTrips * ROUND_TRIP_WARN_AT)) {
    warnings.push({
      title: `TFSA: ${recent.length} round trips in 12 months`,
      detail: `Your guideline is ${guideline.roundTrips}. Frequent TFSA trading can make gains taxable as business income.`,
    })
  }
  const short = recent.filter((s) => s.heldDays < SHORT_HOLD_DAYS).length
  if (recent.length >= MIN_SALES_FOR_SHARE && short / recent.length > guideline.shortHoldShare) {
    warnings.push({
      title: `TFSA: ${short} of ${recent.length} holds under 30 days`,
      detail: `Your guideline is ${Math.round(guideline.shortHoldShare * 100)}% of holds. Frequent TFSA trading can make gains taxable as business income.`,
    })
  }
  return warnings
}

/** How much of an asset is held, across accounts, after the trades of `day`. */
function heldAfter(trades: readonly Trade[], symbol: string, assetType: Trade['assetType'], day: string): number {
  let qty = 0
  for (const t of inOrder(trades)) {
    if (t.day > day) break
    if (t.symbol !== symbol || t.assetType !== assetType) continue
    qty = t.side === 'buy' ? qty + t.qty : Math.max(0, qty - t.qty)
  }
  return qty
}

/**
 * Superficial losses (spec §7.5): a loss realized in a taxable account is denied when the same
 * asset is bought within 30 days before or after the sale and still held 30 days after it.
 * Covers sales from the last 30 days; until the window ends, "still held" means held today.
 */
export function superficialLossWarnings(sales: readonly Sale[], trades: readonly Trade[], today: string): Warning[] {
  return sales
    .filter((s) => TAXABLE.has(s.account) && s.gainCad < 0 && s.day > addDays(today, -31) && s.day <= today)
    .map((sale) => {
      const end = addDays(sale.day, 30)
      const bought = trades.find(
        (t) =>
          t.side === 'buy' &&
          t.symbol === sale.symbol &&
          t.assetType === sale.assetType &&
          t.day >= addDays(sale.day, -30) &&
          t.day <= end,
      )
      const stillHeld = heldAfter(trades, sale.symbol, sale.assetType, end < today ? end : today) > QTY_EPSILON
      if (bought && stillHeld) {
        return {
          symbol: sale.symbol,
          title: `${sale.symbol}: the loss is likely superficial`,
          detail: `You sold at a loss on ${longDay(sale.day)}, bought on ${longDay(bought.day)}, within 30 days, and still hold it. The loss is likely denied and added to the cost of what you hold.`,
          note: 'Loss likely denied',
        }
      }
      return {
        symbol: sale.symbol,
        title: `${sale.symbol}: superficial-loss window`,
        detail: `You sold ${sale.symbol} at a loss on ${longDay(sale.day)}. Buying it back before ${longDay(end)} denies that loss.`,
        note: `Loss window to ${shortDay(end)}`,
      }
    })
}
```

`web/lib/portfolio/view.ts`:

```ts
import { fmtMoney } from '../format'
import { tradeCurrency } from '../symbols'
import { buildLedger, positionKey } from './ledger'
import type { FxRate, FxRates, PriceBook } from './lookup'
import { PERIODS, growth, periodReturns, type Period, type PeriodReturns } from './returns'
import { ACCOUNT_LABELS } from './types'
import type { Account, AssetType, Currency, Market, Trade } from './types'
import { breakdown, taxableEstimate, totals, valueHoldings, type Slice, type Totals } from './valuation'
import { superficialLossWarnings, tfsaWarnings, type TfsaGuideline, type Warning } from './warnings'

export interface Note {
  text: string
  /** Shown with a warning icon. */
  warn: boolean
}

export interface HoldingRow {
  key: string
  account: Account
  symbol: string
  name: string | null
  market: Market | null
  valueCad: number
  gainCad: number
  gainPct: number
  notes: Note[]
}

/** What the sell form offers: each open position at average cost. */
export interface SellOption {
  key: string
  account: Account
  symbol: string
  assetType: AssetType
  qty: number
  costCad: number
  currency: Currency
}

export interface PortfolioView {
  totals: Totals
  /** Accounts with an open position, as labels. */
  accounts: string[]
  fx: FxRate | null
  firstBuy: string | null
  /** Null until there are two trading days to draw. */
  periods: Record<Period, PeriodReturns> | null
  holdings: HoldingRow[]
  warnings: Warning[]
  byMarket: Slice[]
  byAccount: Slice[]
  sellable: SellOption[]
}

export interface PortfolioInputs {
  trades: Trade[]
  prices: PriceBook
  fx: FxRates
  names: Map<string, string>
  guideline: TfsaGuideline
}

/** Everything the portfolio page shows before the model exists (spec §7.4, §7.5, §9). */
export function portfolioView({ trades, prices, fx, names, guideline }: PortfolioInputs, today: string): PortfolioView {
  const ledger = buildLedger(trades, fx)
  const valued = valueHoldings(ledger.positions, prices, fx).sort((a, b) => b.valueCad - a.valueCad)
  const lossWarnings = superficialLossWarnings(ledger.sales, trades, today)
  const warnings: Warning[] = [
    ...ledger.problems.map((problem) => ({ title: 'A trade was left out', detail: problem })),
    ...tfsaWarnings(ledger.sales, guideline, today),
    ...lossWarnings,
  ]

  const holdings = valued.map((h): HoldingRow => {
    const notes: Note[] = []
    if (h.priceCad === null) notes.push({ text: 'No close yet; at cost', warn: true })
    for (const w of lossWarnings) if (w.symbol === h.symbol && w.note) notes.push({ text: w.note, warn: true })
    const taxable = taxableEstimate(h)
    if (taxable !== null) notes.push({ text: `Taxable: est. ${fmtMoney(taxable, { signed: true })}`, warn: false })
    return {
      key: positionKey(h),
      account: h.account,
      symbol: h.symbol,
      name: names.get(h.symbol) ?? null,
      market: h.market,
      valueCad: h.valueCad,
      gainCad: h.gainCad,
      gainPct: h.gainPct,
      notes,
    }
  })

  const g = growth(trades, prices, fx)
  const periods =
    g && g.days.length >= 2
      ? (Object.fromEntries(PERIODS.map((p) => [p, periodReturns(g, p)])) as Record<Period, PeriodReturns>)
      : null

  const accounts = [...new Set(valued.map((h) => h.account))].map((a) => ACCOUNT_LABELS[a])
  const firstBuy = trades.filter((t) => t.side === 'buy').reduce<string | null>((min, t) => (min === null || t.day < min ? t.day : min), null)

  return {
    totals: totals(valued),
    accounts,
    fx: fx.latest(),
    firstBuy,
    periods,
    holdings,
    warnings,
    byMarket: breakdown(valued, 'market'),
    byAccount: breakdown(valued, 'account'),
    sellable: [...ledger.positions]
      .sort((a, b) => a.symbol.localeCompare(b.symbol) || a.account.localeCompare(b.account))
      .map((p) => ({
        key: positionKey(p),
        account: p.account,
        symbol: p.symbol,
        assetType: p.assetType,
        qty: p.qty,
        costCad: p.costCad,
        currency: tradeCurrency(p.assetType, p.symbol),
      })),
  }
}
```

- [ ] **Step 4: Run the tests**

Run: `npm test`
Expected: `Test Files  8 passed (8)`, `Tests  57 passed (57)`. Then `npm run lint` and `npm run typecheck` are clean.

- [ ] **Step 5: Commit**

```bash
git add web/lib/portfolio
git commit -m "feat: compute portfolio returns against XIU.TO and SPY, and the tax warnings"
```

End the message with your `Co-Authored-By:` trailer.

---

### Task 4: Sign-in, the owner gate and the app shell

**Files:**
- Create: `web/lib/supabase/server.ts`, `web/lib/auth.ts`, `web/lib/runs.ts`, `web/lib/data/fetch.ts`, `web/lib/data/runs.ts`, `web/proxy.ts`
- Create: `web/app/login/actions.ts`, `web/app/login/LoginForm.tsx`, `web/app/login/page.tsx`
- Create: `web/app/(app)/actions.ts`, `web/app/(app)/layout.tsx`, `web/app/(app)/page.tsx` (a placeholder until Task 5)
- Create: `web/components/ThemeToggle.tsx`, `web/components/Toast.tsx`, `web/components/Drawer.tsx`, `web/components/shell/nav.ts`, `web/components/shell/Navigation.tsx`, `web/components/shell/RunsPill.tsx`, `web/components/shell/Shell.tsx`
- Test: `web/lib/runs.test.ts`, `web/playwright.config.ts`, `web/e2e/stack.ts`, `web/e2e/db.ts`, `web/e2e/auth.setup.ts`, `web/e2e/auth.spec.ts`, `web/e2e/shell.spec.ts`

**Interfaces:**
- Consumes:
  - `lib/dates.ts` `shortDay`, `todayInToronto`, `addDays`;
  - `lib/copy.ts`;
  - `lib/theme.ts` `applyTheme`.
- Produces:
  - `lib/supabase/server.ts`: `supabaseEnv()`, `createClient()`, `type Supabase`.
  - `lib/auth.ts`: `session()`, cached per request and returning `{ supabase, owner }`; `ownerClient()`, which returns the owner's client or null.
  - `lib/runs.ts`: `Run`, `RunKind`, `RunStatus`, `KIND_LABEL`, `STATUS_DOT`, `runTime`, `runLabel`, `runWhen`, `runSources`, `staleNotice(runs, lastPublished)`.
  - `lib/data/fetch.ts`: `fetchAll(page)` (PostgREST returns at most 1,000 rows per request) and `must(answer)`.
  - `lib/data/runs.ts`: `recentRuns(supabase, limit?)` and `lastPublishedRun(supabase)`.
  - `components/Drawer.tsx` (`Drawer`), `components/Toast.tsx` (`ToastProvider`, `useToast`) and `components/ThemeToggle.tsx` (`ThemeToggle`, `useDarkMode`).
  - `e2e/db.ts`: `sql`, `resetData`, `today`, `daysAgo`, `weekdays`, `seedSymbols`, `seedCloses`, `seedFx`, `seedLot`, `seedSell` and `seedRun`, which later tasks' specs use. `e2e/stack.ts`: `localStack()`, `OWNER`, `VISITOR`, `OWNER_STATE`.

**How it fits:**
- **`proxy.ts`** runs before every page and server action. It refreshes the session cookie and sends visitors who aren't signed in to `/login`.
- **The `(app)` layout:**
  - calls `session()`, which checks `public.is_owner()` once per request;
  - shows anyone who isn't the owner a notice;
  - otherwise wraps the page in the shell.
- **Pages call `ownerClient()`** and render nothing for someone who isn't the owner. Next renders a page alongside its layout, and the page's queries would otherwise fail under row-level security.
- **Sign-out** is local to this browser (`scope: 'local'`).
- **The stale banner** appears when the newest finished run failed.
- **The Paper badges** stay static until picks are graded (Plan 4).

The unit test goes red and green first. `next build`, which the browser tests run, type-checks every `.ts` file, unit tests included. So a unit test that imports a module that doesn't exist yet would stop the browser tests from building. The same order applies in Tasks 5 to 7.

- [ ] **Step 1: Write the failing unit test**

`web/lib/runs.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import type { Run } from './runs'
import { runLabel, runSources, runWhen, staleNotice } from './runs'

const run = (over: Partial<Run>): Run => ({
  id: 2,
  kind: 'pre_close',
  et_date: '2026-10-16',
  started_at: '2026-10-16T19:15:00Z',
  finished_at: '2026-10-16T19:31:00Z',
  status: 'success',
  published: true,
  sources_ok: 30,
  sources_total: 33,
  summary: {},
  ...over,
})

describe('run labels', () => {
  it("uses Toronto's clock and the run's kind", () => {
    expect(runLabel(run({}))).toBe('Pre-close 15:31')
    expect(runWhen(run({}))).toBe('Oct 16 · pre-close 15:31')
    expect(runWhen(run({ kind: 'early_close', finished_at: null, started_at: '2026-10-16T16:15:00Z' }))).toBe(
      'Oct 16 · early close 12:15',
    )
  })

  it('counts sources once the run has', () => {
    expect(runSources(run({}))).toBe('30/33')
    expect(runSources(run({ sources_ok: null }))).toBeNull()
  })
})

describe('staleNotice', () => {
  const published = run({ id: 1, kind: 'pre_open', finished_at: '2026-10-16T12:24:00Z' })

  it('is quiet when the newest finished run worked', () => {
    expect(staleNotice([run({})], published)).toBeNull()
    expect(staleNotice([run({ status: 'running' }), run({ status: 'degraded' })], published)).toBeNull()
    expect(staleNotice([], null)).toBeNull()
  })

  it("names a failed run's reasons and the results still shown", () => {
    const failed = run({ status: 'failed', published: false, summary: { failed_reason: ['TSX: universe too small (2 < 300)'] } })
    expect(staleNotice([failed, published], published)).toEqual({
      title: 'The Oct 16 · pre-close 15:31 run failed:',
      detail: 'TSX: universe too small (2 < 300). Showing the Oct 16 · pre-open 08:24 results until the next run.',
    })
  })

  it('looks past a run still in progress, and says when nothing has published', () => {
    const failed = run({ status: 'failed', published: false })
    expect(staleNotice([run({ status: 'running' }), failed], null)).toEqual({
      title: 'The Oct 16 · pre-close 15:31 run failed:',
      detail: 'See the run summary. No run has published yet.',
    })
  })
})
```

- [ ] **Step 2: Run it and see it fail**

Run: `npm test -- lib/runs.test.ts`
Expected: `Error: Cannot find module './runs'`.

- [ ] **Step 3: Write the run labels**

`web/lib/runs.ts`:

```ts
/** How the status bar and its banners describe pipeline runs (spec §9, top bar). */

import { shortDay } from './dates'

export type RunKind = 'pre_open' | 'pre_close' | 'early_close'
export type RunStatus = 'running' | 'success' | 'degraded' | 'failed'

/** The columns of a `runs` row the dashboard reads. */
export interface Run {
  id: number
  kind: RunKind
  et_date: string
  started_at: string
  finished_at: string | null
  status: RunStatus
  published: boolean
  sources_ok: number | null
  sources_total: number | null
  summary: { failed_reason?: string[] } & Record<string, unknown>
}

export const KIND_LABEL: Record<RunKind, string> = {
  pre_open: 'Pre-open',
  pre_close: 'Pre-close',
  early_close: 'Early close',
}

/** The dot classes of ledger.css for each status. */
export const STATUS_DOT: Record<RunStatus, string> = {
  success: 'ok',
  degraded: 'partial',
  failed: 'failed',
  running: 'ok running',
}

const clock = new Intl.DateTimeFormat('en-CA', {
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
  timeZone: 'America/Toronto',
})

/** When the run finished (or started, while it runs), on Toronto's clock: "15:31". */
export const runTime = (run: Run): string => clock.format(new Date(run.finished_at ?? run.started_at))

/** "Pre-close 15:31" */
export const runLabel = (run: Run): string => `${KIND_LABEL[run.kind]} ${runTime(run)}`

/** "Oct 16 · pre-close 15:31" */
export const runWhen = (run: Run): string =>
  `${shortDay(run.et_date)} · ${KIND_LABEL[run.kind].toLowerCase()} ${runTime(run)}`

/** "30/33", or null for a run that hasn't counted its sources yet. */
export const runSources = (run: Run): string | null =>
  run.sources_ok === null || run.sources_total === null ? null : `${run.sources_ok}/${run.sources_total}`

export interface Notice {
  title: string
  detail: string
}

/**
 * The stale banner: shown when the newest finished run failed, so the dashboard is showing an
 * older run's results (spec §9). `runs` is newest first.
 */
export function staleNotice(runs: readonly Run[], lastPublished: Run | null): Notice | null {
  const latest = runs.find((r) => r.status !== 'running')
  if (!latest || latest.status !== 'failed') return null
  const reasons = latest.summary.failed_reason ?? []
  const why = reasons.length > 0 ? `${reasons.join('; ')}.` : 'See the run summary.'
  const showing = lastPublished
    ? `Showing the ${runWhen(lastPublished)} results until the next run.`
    : 'No run has published yet.'
  return { title: `The ${runWhen(latest)} run failed:`, detail: `${why} ${showing}` }
}
```

- [ ] **Step 4: Run it**

Run: `npm test -- lib/runs.test.ts`
Expected: `Tests  5 passed (5)`.

- [ ] **Step 5: Write the browser tests and their helpers**

The web server is ready when `/icon.svg` answers. The icon exists from Task 1, and the proxy lets it through.

`web/playwright.config.ts`:

```ts
import { defineConfig, devices } from '@playwright/test'
import { OWNER_STATE, localStack } from './e2e/stack'

const stack = localStack()
const PORT = 3100

/**
 * Browser tests against the local Supabase stack and a production build of the dashboard. The
 * tests share one database, so they run one at a time. On Windows they use the installed Edge;
 * elsewhere (CI) Playwright's Chromium (`npx playwright install chromium`).
 */
export default defineConfig({
  testDir: 'e2e',
  fullyParallel: false,
  workers: 1,
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  reporter: process.env.CI ? 'github' : 'list',
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    channel: process.platform === 'win32' ? 'msedge' : undefined,
    locale: 'en-CA',
    timezoneId: 'America/Toronto',
    trace: 'retain-on-failure',
  },
  projects: [
    { name: 'setup', testMatch: /auth\.setup\.ts/ },
    {
      name: 'desktop',
      dependencies: ['setup'],
      use: { ...devices['Desktop Chrome'], channel: process.platform === 'win32' ? 'msedge' : undefined, storageState: OWNER_STATE },
    },
  ],
  webServer: {
    command: `npm run build && npx next start -p ${PORT}`,
    // The icon is served before any page exists, and the proxy lets it through.
    url: `http://127.0.0.1:${PORT}/icon.svg`,
    reuseExistingServer: !process.env.CI,
    timeout: 240_000,
    env: { SUPABASE_URL: stack.API_URL, SUPABASE_PUBLISHABLE_KEY: stack.PUBLISHABLE_KEY },
  },
})
```

`web/e2e/stack.ts`:

```ts
import { execSync } from 'node:child_process'
import { mkdirSync } from 'node:fs'
import { join } from 'node:path'

/** The local Supabase stack (`npm run db:start`, see web/README.md). */
export interface Stack {
  API_URL: string
  DB_URL: string
  PUBLISHABLE_KEY: string
  SECRET_KEY: string
}

/**
 * The stack's URLs and keys, from `supabase status`. Playwright loads its config in the main
 * process and in each worker; the main process asks once and the workers inherit the answer.
 */
export function localStack(): Stack {
  if (!process.env.E2E_STACK) {
    let out: string
    try {
      out = execSync('npx supabase status -o json --workdir ..', {
        cwd: join(__dirname, '..'),
        encoding: 'utf8',
        stdio: ['ignore', 'pipe', 'ignore'],
      })
    } catch {
      throw new Error('The local Supabase stack is not running. Start it with `npm run db:start` (see web/README.md).')
    }
    process.env.E2E_STACK = out.slice(out.indexOf('{'), out.lastIndexOf('}') + 1)
  }
  return JSON.parse(process.env.E2E_STACK) as Stack
}

/** Test accounts on the local stack only. */
export const OWNER = { email: 'owner@example.com', password: 'local-owner-password' }
export const VISITOR = { email: 'visitor@example.com', password: 'local-visitor-password' }

const AUTH_DIR = join(__dirname, '.auth')
mkdirSync(AUTH_DIR, { recursive: true })
export const OWNER_STATE = join(AUTH_DIR, 'owner.json')
```

`web/e2e/db.ts`:

```ts
import postgres, { type JSONValue } from 'postgres'
import { addDays, todayInToronto } from '../lib/dates'
import { localStack } from './stack'

const DB_URL = localStack().DB_URL
// These helpers truncate tables: refuse anything but a database on this machine.
if (!/@(127\.0\.0\.1|localhost):/.test(DB_URL)) throw new Error(`Refusing to seed a database that isn't local: ${DB_URL}`)

/** Direct SQL on the local stack's database, as its superuser, for seeding and checking. */
export const sql = postgres(DB_URL, { onnotice: () => {} })

/** Everything the owner or a run writes, emptied between tests. Users and app_config stay. */
export async function resetData() {
  await sql`truncate lots, sells, watchlist, runs, daily_closes, fx_rates, symbols restart identity cascade`
  await sql`update settings set usd_fx_fee_pct = 1.5, crypto_fee_pct = 2.0, tfsa_round_trips_warn = 24,
            tfsa_short_hold_share_warn = 0.5, updated_at = now() where id = 1`
}

export const today = () => todayInToronto()
export const daysAgo = (n: number) => addDays(today(), -n)

/** Weekdays from `from` to yesterday. */
export function weekdays(from: string): string[] {
  const days: string[] = []
  for (let day = from; day < today(); day = addDays(day, 1)) {
    const weekday = new Date(`${day}T12:00:00Z`).getUTCDay()
    if (weekday !== 0 && weekday !== 6) days.push(day)
  }
  return days
}

export async function seedSymbols(rows: { symbol: string; market: 'US' | 'TSX'; name: string }[]) {
  for (const r of rows) {
    await sql`insert into symbols (symbol, asset_type, market, name, exchange)
              values (${r.symbol}, 'stock', ${r.market}, ${r.name}, ${r.market === 'TSX' ? 'TSX' : 'NYSE'})`
  }
}

/** A close for every day, rising by `step` a day from `start`. */
export async function seedCloses(
  symbol: string,
  assetType: 'stock' | 'crypto',
  currency: 'USD' | 'CAD',
  days: string[],
  start: number,
  step: number,
) {
  const rows = days.map((day, i) => ({ symbol, asset_type: assetType, day, close: start + step * i, currency }))
  if (rows.length) await sql`insert into daily_closes ${sql(rows)}`
}

export async function seedFx(days: string[], usdCad = 1.37) {
  const rows = days.map((day) => ({ day, usd_cad: usdCad }))
  if (rows.length) await sql`insert into fx_rates ${sql(rows)}`
}

export async function seedLot(lot: {
  account: string
  symbol: string
  asset_type: 'stock' | 'crypto'
  qty: number
  price: number
  currency: 'USD' | 'CAD'
  fx_rate_cad?: number | null
  bought_at: string
}) {
  await sql`insert into lots ${sql({ fx_rate_cad: null, ...lot })}`
}

export async function seedSell(sell: {
  account: string
  symbol: string
  asset_type: 'stock' | 'crypto'
  qty: number
  price: number
  currency: 'USD' | 'CAD'
  sold_at: string
}) {
  await sql`insert into sells ${sql({ fx_rate_cad: null, ...sell })}`
}

export async function seedRun(run: {
  kind: 'pre_open' | 'pre_close' | 'early_close'
  status: 'success' | 'degraded' | 'failed' | 'running'
  published: boolean
  finished: string
  summary?: JSONValue
}) {
  const finished = new Date(run.finished)
  await sql`insert into runs (kind, et_date, started_at, finished_at, status, published, sources_ok, sources_total, summary)
            values (${run.kind}, ${todayInToronto(finished)}, ${new Date(finished.getTime() - 15 * 60_000)}, ${finished},
                    ${run.status}, ${run.published}, 30, 33, ${sql.json(run.summary ?? {})})`
}
```

`web/e2e/auth.setup.ts`:

```ts
import { expect, test as setup } from '@playwright/test'
import { createClient } from '@supabase/supabase-js'
import { sql } from './db'
import { OWNER, OWNER_STATE, VISITOR, localStack } from './stack'

/** Creates the owner and a second user on the local stack, names the owner, and signs in once. */
setup('owner and visitor exist, and the owner is signed in', async ({ page }) => {
  const stack = localStack()
  const admin = createClient(stack.API_URL, stack.SECRET_KEY, { auth: { persistSession: false } })
  const { data: list, error } = await admin.auth.admin.listUsers()
  if (error) throw error
  const ids: Record<string, string> = {}
  for (const account of [OWNER, VISITOR]) {
    const existing = list.users.find((u) => u.email === account.email)
    if (existing) {
      await admin.auth.admin.updateUserById(existing.id, { password: account.password })
      ids[account.email] = existing.id
    } else {
      const { data, error: createError } = await admin.auth.admin.createUser({ ...account, email_confirm: true })
      if (createError) throw createError
      ids[account.email] = data.user.id
    }
  }
  await sql`insert into app_config (id, owner_id) values (1, ${ids[OWNER.email]})
            on conflict (id) do update set owner_id = excluded.owner_id`

  await page.goto('/login')
  await page.getByLabel('Email').fill(OWNER.email)
  await page.getByLabel('Password').fill(OWNER.password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { name: 'My Portfolio' })).toBeVisible()
  await page.context().storageState({ path: OWNER_STATE })
})
```

`web/e2e/auth.spec.ts`:

```ts
import { expect, test } from '@playwright/test'
import { resetData } from './db'
import { OWNER, VISITOR, localStack } from './stack'

test.use({ storageState: { cookies: [], origins: [] } })
test.beforeEach(resetData)

test('a signed-out visitor is sent to the sign-in page', async ({ page }) => {
  await page.goto('/watchlist')
  await expect(page).toHaveURL(/\/login$/)
  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()
  await expect(page.getByText('Not financial or tax advice. Forecasts are probabilistic and can be wrong.')).toBeVisible()
})

test('a wrong password is refused, and the email stays filled in', async ({ page }) => {
  await page.goto('/login')
  await page.getByLabel('Email').fill(OWNER.email)
  await page.getByLabel('Password').fill('not-the-password')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByText("That email and password don't match.")).toBeVisible()
  await expect(page.getByLabel('Email')).toHaveValue(OWNER.email)
})

test('empty fields are named', async ({ page }) => {
  await page.goto('/login')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByText('Enter your email.')).toBeVisible()
  await expect(page.getByText('Enter your password.')).toBeVisible()
})

test('the owner signs in and out', async ({ page }) => {
  await page.goto('/login')
  await page.getByLabel('Email').fill(OWNER.email)
  await page.getByLabel('Password').fill(OWNER.password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { name: 'My Portfolio' })).toBeVisible()

  await page.goto('/login')
  await expect(page).toHaveURL(/\/$/) // a signed-in owner doesn't see the sign-in page

  await page.getByRole('complementary', { name: 'Main' }).getByRole('button', { name: 'Sign out' }).click()
  await expect(page).toHaveURL(/\/login$/)
  await page.goto('/')
  await expect(page).toHaveURL(/\/login$/)
})

test('nobody can sign up', async ({ request }) => {
  const stack = localStack()
  const response = await request.post(`${stack.API_URL}/auth/v1/signup`, {
    headers: { apikey: stack.PUBLISHABLE_KEY },
    data: { email: 'stranger@example.com', password: 'stranger-password-1' },
  })
  expect(response.status()).toBe(422)
  expect((await response.json()).error_code).toBe('signup_disabled')
})

test('someone who is not the owner sees no data', async ({ page }) => {
  await page.goto('/login')
  await page.getByLabel('Email').fill(VISITOR.email)
  await page.getByLabel('Password').fill(VISITOR.password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByText("This account isn't the owner")).toBeVisible()
  await expect(page.getByRole('heading', { name: 'My Portfolio' })).toHaveCount(0)
})
```

`web/e2e/shell.spec.ts`:

```ts
import { expect, test } from '@playwright/test'
import { resetData, seedRun } from './db'

test.beforeEach(resetData)

test('the status bar shows the latest run and opens the last four', async ({ page }) => {
  await seedRun({ kind: 'pre_open', status: 'success', published: true, finished: '2026-10-16T12:24:00Z' })
  await seedRun({
    kind: 'pre_close',
    status: 'degraded',
    published: true,
    finished: '2026-10-16T19:31:00Z',
  })
  await page.goto('/')
  const pill = page.getByRole('button', { name: /Pre-close 15:31/ })
  await expect(pill).toContainText('degraded')
  await expect(page.getByText('30/33', { exact: true }).first()).toBeVisible()
  await pill.click()
  const runs = page.getByRole('menu')
  await expect(runs.getByRole('menuitem')).toHaveCount(2)
  await expect(runs).toContainText('Oct 16 · pre-open 08:24')
  await page.keyboard.press('Escape')
  await expect(runs).not.toHaveClass(/open/)
  await expect(page.getByText('US Paper')).toBeVisible()
  await expect(page.getByRole('contentinfo')).toContainText(
    'Not financial or tax advice. Forecasts are probabilistic and can be wrong.',
  )
  await expect(page.getByRole('contentinfo')).toContainText('USD/CAD from the Bank of Canada.')
})

test('a failed run raises the stale banner', async ({ page }) => {
  await seedRun({ kind: 'pre_open', status: 'success', published: true, finished: '2026-10-16T12:24:00Z' })
  await seedRun({
    kind: 'pre_close',
    status: 'failed',
    published: false,
    finished: '2026-10-16T19:31:00Z',
    summary: { failed_reason: ['TSX: universe too small (2 < 300)'] },
  })
  await page.goto('/')
  await expect(page.locator('.banner.danger')).toHaveText(
    'The Oct 16 · pre-close 15:31 run failed: TSX: universe too small (2 < 300). Showing the Oct 16 · pre-open 08:24 results until the next run.',
  )
})

test('before any run, the status bar says so', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByText('No runs yet')).toBeVisible()
  await expect(page.locator('.banner.danger')).toHaveCount(0)
})

test('dark mode is remembered', async ({ page }) => {
  await page.goto('/')
  const dark = () => page.evaluate(() => document.documentElement.classList.contains('dark'))
  const before = await dark()
  await page.getByRole('banner').getByRole('button', { name: 'Switch between light and dark' }).click()
  await expect.poll(dark).toBe(!before)
  await page.reload()
  await expect.poll(dark).toBe(!before)
})
```

- [ ] **Step 6: Run them and see them fail**

Run: `npm run e2e` (the stack from Task 1 must be running)
Expected: the build succeeds. Then `1 failed` (the setup test: `/login` is a 404, so there is no Email field) and `10 did not run`.

- [ ] **Step 7: Write the server side**

`web/lib/supabase/server.ts`:

```ts
import 'server-only'
import { createServerClient } from '@supabase/ssr'
import { cookies } from 'next/headers'

/**
 * Supabase settings. The dashboard only talks to Supabase from the server, so neither value is
 * shipped to the browser. The publishable key carries no rights of its own: row-level security
 * gives the signed-in owner, and nobody else, access to the data (spec §8).
 */
export function supabaseEnv(): { url: string; key: string } {
  const url = process.env.SUPABASE_URL
  const key = process.env.SUPABASE_PUBLISHABLE_KEY
  if (!url || !key) throw new Error('Set SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY (see web/README.md).')
  return { url, key }
}

/** A client for one server render or server action, signed in as the visitor's session. */
export async function createClient() {
  const cookieStore = await cookies()
  const { url, key } = supabaseEnv()
  return createServerClient(url, key, {
    cookies: {
      getAll: () => cookieStore.getAll(),
      setAll: (cookiesToSet) => {
        try {
          for (const { name, value, options } of cookiesToSet) cookieStore.set(name, value, options)
        } catch {
          // A server component can't set cookies; the proxy keeps the session fresh instead.
        }
      },
    },
  })
}

export type Supabase = Awaited<ReturnType<typeof createClient>>
```

`web/lib/auth.ts`:

```ts
import 'server-only'
import { redirect } from 'next/navigation'
import { cache } from 'react'
import { createClient, type Supabase } from './supabase/server'

/**
 * The visitor's session, once per request: signed out goes to /login. `owner` is whether the
 * visitor is the owner named in `app_config`, the only one row-level security shows data to.
 */
export const session = cache(async (): Promise<{ supabase: Supabase; owner: boolean }> => {
  const supabase = await createClient()
  const { data } = await supabase.auth.getClaims()
  if (!data?.claims) redirect('/login')
  const { data: owner, error } = await supabase.rpc('is_owner')
  if (error) throw new Error(error.message)
  return { supabase, owner: owner === true }
})

/**
 * For pages: the owner's client, or null. Next renders a page alongside its layout, so a page
 * must not load data when the layout is showing someone else the not-the-owner notice.
 */
export async function ownerClient(): Promise<Supabase | null> {
  const { supabase, owner } = await session()
  return owner ? supabase : null
}
```

`web/lib/data/fetch.ts`:

```ts
import 'server-only'

/** PostgREST answers at most 1,000 rows per request (Supabase's default `max_rows`). */
const PAGE = 1000

type Answer<T> = { data: T | null; error: { message: string } | null }

/** Every row of a query, a page at a time. The query must have a stable order. */
export async function fetchAll<T>(page: (from: number, to: number) => PromiseLike<Answer<T[]>>): Promise<T[]> {
  const rows: T[] = []
  for (let from = 0; ; from += PAGE) {
    const { data, error } = await page(from, from + PAGE - 1)
    if (error) throw new Error(error.message)
    rows.push(...(data ?? []))
    if (!data || data.length < PAGE) return rows
  }
}

/** The data of an answer, or the error thrown. */
export const must = <T>({ data, error }: Answer<T>): T => {
  if (error) throw new Error(error.message)
  return data as T
}
```

`web/lib/data/runs.ts`:

```ts
import 'server-only'
import type { Run } from '../runs'
import type { Supabase } from '../supabase/server'
import { must } from './fetch'

const COLUMNS = 'id, kind, et_date, started_at, finished_at, status, published, sources_ok, sources_total, summary'

/** The newest runs, newest first, for the status bar. */
export async function recentRuns(supabase: Supabase, limit = 4): Promise<Run[]> {
  return must(await supabase.from('runs').select(COLUMNS).order('id', { ascending: false }).limit(limit)) as Run[]
}

/** The newest run that published, for the stale banner. */
export async function lastPublishedRun(supabase: Supabase): Promise<Run | null> {
  const rows = must(
    await supabase.from('runs').select(COLUMNS).eq('published', true).order('id', { ascending: false }).limit(1),
  ) as Run[]
  return rows[0] ?? null
}
```

`web/proxy.ts`:

```ts
import { createServerClient } from '@supabase/ssr'
import { NextResponse, type NextRequest } from 'next/server'

/**
 * Runs before every page and server action: refreshes the Supabase session cookie, sends signed-out
 * visitors to /login, and signed-in ones away from it. Pages still check for the owner; this is
 * only the first gate (row-level security is the last).
 */
export async function proxy(request: NextRequest) {
  const url = process.env.SUPABASE_URL
  const key = process.env.SUPABASE_PUBLISHABLE_KEY
  if (!url || !key) throw new Error('Set SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY (see web/README.md).')

  let response = NextResponse.next({ request })
  const supabase = createServerClient(url, key, {
    cookies: {
      getAll: () => request.cookies.getAll(),
      setAll: (cookiesToSet, headers) => {
        for (const { name, value } of cookiesToSet) request.cookies.set(name, value)
        response = NextResponse.next({ request })
        for (const { name, value, options } of cookiesToSet) response.cookies.set(name, value, options)
        for (const [name, value] of Object.entries(headers ?? {})) response.headers.set(name, value)
      },
    },
  })
  const { data } = await supabase.auth.getClaims()
  const signedIn = Boolean(data?.claims)
  const onLogin = request.nextUrl.pathname === '/login'

  if (signedIn === onLogin) {
    const to = request.nextUrl.clone()
    to.pathname = signedIn ? '/' : '/login'
    to.search = ''
    const redirect = NextResponse.redirect(to)
    for (const cookie of response.cookies.getAll()) redirect.cookies.set(cookie)
    return redirect
  }
  return response
}

export const config = {
  // Everything but Next's static files and the icon.
  matcher: ['/((?!_next/static|_next/image|icon.svg|favicon.ico).*)'],
}
```

- [ ] **Step 8: Write sign-in**

`web/app/login/actions.ts`:

```ts
'use server'

import { redirect } from 'next/navigation'
import { z } from 'zod'
import { createClient } from '@/lib/supabase/server'

export interface SignInState {
  email: string
  error?: string
  missing?: ('email' | 'password')[]
}

const credentials = z.object({ email: z.string().trim().min(1), password: z.string().min(1) })

/** Email and password sign-in (spec §9). Sign-ups are off in Supabase, so only the owner exists. */
export async function signIn(_: SignInState, form: FormData): Promise<SignInState> {
  const email = String(form.get('email') ?? '')
  const parsed = credentials.safeParse({ email, password: form.get('password') ?? '' })
  if (!parsed.success) {
    const missing = parsed.error.issues.map((issue) => issue.path[0] as 'email' | 'password')
    return { email, missing }
  }
  const supabase = await createClient()
  const { error } = await supabase.auth.signInWithPassword(parsed.data)
  if (error) return { email, error: "That email and password don't match." }
  redirect('/')
}
```

`web/app/login/LoginForm.tsx`:

```tsx
'use client'

import { TriangleAlert } from 'lucide-react'
import { useActionState } from 'react'
import { signIn, type SignInState } from './actions'

export function LoginForm() {
  const [state, action, pending] = useActionState<SignInState, FormData>(signIn, { email: '' })
  const missing = new Set(state.missing ?? [])
  return (
    <form className="card" action={action} noValidate>
      <div>
        <h1>Sign in</h1>
        <p className="sub" style={{ margin: '4px 0 0' }}>
          Your portfolio, picks and track record.
        </p>
      </div>
      {state.error && (
        <div className="banner danger" role="alert">
          <TriangleAlert />
          <div>{state.error}</div>
        </div>
      )}
      <label className={`field ${missing.has('email') ? 'invalid' : ''}`}>
        <span>Email</span>
        <input
          className="input"
          type="email"
          name="email"
          autoComplete="username"
          placeholder="you@example.com"
          defaultValue={state.email}
          required
        />
        <span className="error">Enter your email.</span>
      </label>
      <label className={`field ${missing.has('password') ? 'invalid' : ''}`}>
        <span>Password</span>
        <input className="input" type="password" name="password" autoComplete="current-password" required />
        <span className="error">Enter your password.</span>
      </label>
      <button type="submit" className="btn btn-primary" style={{ width: '100%', padding: '11px 14px' }} disabled={pending}>
        {pending ? 'Signing in…' : 'Sign in'}
      </button>
      <p className="sub" style={{ margin: 0, textAlign: 'center' }}>
        One owner, no sign-ups.
      </p>
    </form>
  )
}
```

`web/app/login/page.tsx`:

```tsx
import type { Metadata } from 'next'
import { ThemeToggle } from '@/components/ThemeToggle'
import { DISCLAIMER } from '@/lib/copy'
import { LoginForm } from './LoginForm'

export const metadata: Metadata = { title: 'Sign in' }

export default function LoginPage() {
  return (
    <>
      <ThemeToggle className="theme-corner" />
      <main className="login-wrap">
        <div className="login enter">
          <div className="brand" style={{ justifyContent: 'center', padding: 0 }}>
            <span className="brand-mark" aria-hidden="true">
              A
            </span>
            ADVISOR
          </div>
          <LoginForm />
          <p className="sub" style={{ margin: 0, textAlign: 'center', fontSize: 12 }}>
            {DISCLAIMER}
          </p>
        </div>
      </main>
    </>
  )
}
```

- [ ] **Step 9: Write the shell's components**

`web/components/ThemeToggle.tsx`:

```tsx
'use client'

import { Moon, Sun } from 'lucide-react'
import { useSyncExternalStore } from 'react'
import { applyTheme } from '@/lib/theme'

const subscribe = (onChange: () => void) => {
  const observer = new MutationObserver(onChange)
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] })
  return () => observer.disconnect()
}
const isDark = () => document.documentElement.classList.contains('dark')

/** Follows the page's "dark" class, which the head script set before React ran. */
export function useDarkMode(): boolean {
  return useSyncExternalStore(subscribe, isDark, () => false)
}

export function ThemeToggle({ className = '' }: { className?: string }) {
  const dark = useDarkMode()
  return (
    <button
      type="button"
      className={`icon-btn ${className}`}
      aria-label="Switch between light and dark"
      onClick={() => applyTheme(dark ? 'light' : 'dark')}
    >
      {dark ? <Sun /> : <Moon />}
    </button>
  )
}
```

`web/components/Toast.tsx`:

```tsx
'use client'

import { CircleCheck } from 'lucide-react'
import { createContext, useCallback, useContext, useRef, useState } from 'react'

const ToastContext = createContext<(message: string) => void>(() => {})

/** One toast at a time, top right, for 4 seconds (ledger.css `.toast`). */
export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [message, setMessage] = useState('')
  const [shown, setShown] = useState(false)
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined)
  const show = useCallback((text: string) => {
    setMessage(text)
    setShown(true)
    clearTimeout(timer.current)
    timer.current = setTimeout(() => setShown(false), 4000)
  }, [])
  return (
    <ToastContext.Provider value={show}>
      {children}
      <div className={`toast ${shown ? 'show' : ''}`} role="status">
        <CircleCheck />
        <span>{message}</span>
      </div>
    </ToastContext.Provider>
  )
}

export const useToast = () => useContext(ToastContext)
```

`web/components/Drawer.tsx`:

```tsx
'use client'

import { X } from 'lucide-react'
import { useEffect, useRef, useSyncExternalStore } from 'react'
import { createPortal } from 'react-dom'

const noop = () => () => {}

/**
 * A sheet from the bottom on phones and a panel from the right on wider screens (ledger.css).
 * Escape and the backdrop close it; focus moves to its first field and back to the opener.
 * It renders into <body>, as in the mockups: inside the page, an animated ancestor's stacking
 * context would put it under the sticky status bar.
 */
export function Drawer({
  id,
  title,
  open,
  onClose,
  children,
}: {
  id: string
  title: string
  open: boolean
  onClose: () => void
  children: React.ReactNode
}) {
  const panel = useRef<HTMLDivElement>(null)
  const opener = useRef<Element | null>(null)
  const mounted = useSyncExternalStore(noop, () => true, () => false)

  useEffect(() => {
    if (!open) return
    opener.current = document.activeElement
    const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches
    const timer = setTimeout(() => {
      const first = panel.current?.querySelector<HTMLElement>('input, select, textarea, button:not([data-close])')
      ;(first ?? panel.current)?.focus()
    }, reduce ? 0 : 260)
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => {
      clearTimeout(timer)
      document.removeEventListener('keydown', onKey)
      if (opener.current instanceof HTMLElement) opener.current.focus()
    }
  }, [open, onClose])

  if (!mounted) return null
  return createPortal(
    <>
      <div className={`backdrop ${open ? 'open' : ''}`} onClick={onClose} aria-hidden="true" />
      <div
        ref={panel}
        id={id}
        className={`drawer ${open ? 'open' : ''}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby={`${id}-title`}
        aria-hidden={!open}
        tabIndex={-1}
      >
        <div className="grab" />
        <div className="drawer-head">
          <h2 id={`${id}-title`}>{title}</h2>
          <button type="button" className="icon-btn" data-close aria-label="Close" onClick={onClose}>
            <X />
          </button>
        </div>
        {/* Kept mounted so it doesn't empty while sliding out; a closed drawer is hidden and unfocusable. */}
        {children}
      </div>
    </>,
    document.body,
  )
}
```

`web/components/shell/nav.ts`:

```ts
import { Eye, Settings, Wallet, type LucideIcon } from 'lucide-react'

export interface NavItem {
  href: string
  label: string
  icon: LucideIcon
  /** Primary pages are phone tabs; the rest sit in the More sheet. */
  primary: boolean
}

/** The pages Plan 5b builds. Picks, Track record and Sources join in Plan 5c. */
export const NAV: readonly NavItem[] = [
  { href: '/', label: 'Portfolio', icon: Wallet, primary: true },
  { href: '/watchlist', label: 'Watchlist', icon: Eye, primary: true },
  { href: '/settings', label: 'Settings', icon: Settings, primary: false },
]

export const isCurrent = (href: string, pathname: string): boolean =>
  href === '/' ? pathname === '/' : pathname === href || pathname.startsWith(`${href}/`)
```

`web/components/shell/Navigation.tsx`:

```tsx
'use client'

import { Ellipsis } from 'lucide-react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useCallback, useState } from 'react'
import { Drawer } from '../Drawer'
import { NAV, isCurrent } from './nav'

export function SidebarLinks() {
  const pathname = usePathname()
  return (
    <nav style={{ display: 'grid', gap: 2 }}>
      {NAV.map(({ href, label, icon: Icon }) => (
        <Link key={href} className="nav-link" href={href} aria-current={isCurrent(href, pathname) ? 'page' : undefined}>
          <Icon />
          {label}
        </Link>
      ))}
    </nav>
  )
}

/** Phone tabs: the primary pages, then More for the rest. */
export function BottomTabs() {
  const pathname = usePathname()
  const [more, setMore] = useState(false)
  const close = useCallback(() => setMore(false), [])
  const primary = NAV.filter((n) => n.primary)
  const secondary = NAV.filter((n) => !n.primary)
  return (
    <>
      <nav
        className="bottom-tabs"
        aria-label="Main"
        style={{ gridTemplateColumns: `repeat(${primary.length + (secondary.length ? 1 : 0)}, 1fr)` }}
      >
        {primary.map(({ href, label, icon: Icon }) => (
          <Link key={href} className="bottom-tab" href={href} aria-current={isCurrent(href, pathname) ? 'page' : undefined}>
            <Icon />
            {label}
          </Link>
        ))}
        {secondary.length > 0 && (
          <button
            type="button"
            className="bottom-tab"
            aria-current={secondary.some((n) => isCurrent(n.href, pathname)) ? 'page' : undefined}
            onClick={() => setMore(true)}
          >
            <Ellipsis />
            More
          </button>
        )}
      </nav>
      <Drawer id="more-sheet" title="More" open={more} onClose={close}>
        <div className="drawer-body">
          {secondary.map(({ href, label, icon: Icon }) => (
            <Link key={href} className="nav-link" href={href} onClick={close}>
              <Icon />
              {label}
            </Link>
          ))}
        </div>
      </Drawer>
    </>
  )
}
```

`web/components/shell/RunsPill.tsx`:

```tsx
'use client'

import { ChevronDown } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

export interface RunView {
  id: number
  dot: string
  label: string
  when: string
  status: string
  note: string | null
  sources: string | null
}

/** The latest run in the status bar; it opens the last four runs (spec §9, top bar). */
export function RunsPill({ runs }: { runs: RunView[] }) {
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onClick = (event: MouseEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false)
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('click', onClick)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('click', onClick)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const latest = runs[0]
  if (!latest) {
    return (
      <span className="pill">
        <span className="dot skipped" />
        No runs yet
      </span>
    )
  }
  return (
    <div ref={root} style={{ position: 'relative' }}>
      <button
        type="button"
        className="pill"
        aria-haspopup="true"
        aria-expanded={open}
        aria-controls="runs-pop"
        onClick={() => setOpen((o) => !o)}
      >
        <span className={`dot ${latest.dot}`} />
        {latest.label}
        <span className="muted hide-sm">{latest.status}</span>
        <ChevronDown style={{ width: 14, height: 14 }} />
      </button>
      <div className={`popover ${open ? 'open' : ''}`} id="runs-pop" role="menu" style={{ left: 0, top: 'calc(100% + 6px)' }}>
        <div className="label" style={{ padding: '8px 10px 4px' }}>
          Last runs
        </div>
        {runs.map((r) => (
          <div key={r.id} className="popover-row" role="menuitem">
            <span className={`dot ${r.dot}`} />
            <span>
              <span style={{ fontWeight: 500 }}>{r.when}</span>
              <br />
              <span className="sub">
                {r.status}
                {r.note ? ` · ${r.note}` : ''}
              </span>
            </span>
            <span className="num sub">{r.sources ?? '—'}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
```

`web/components/shell/Shell.tsx`:

```tsx
import { LogOut, TriangleAlert } from 'lucide-react'
import Link from 'next/link'
import { signOut } from '@/app/(app)/actions'
import { CREDITS, DISCLAIMER } from '@/lib/copy'
import type { Run } from '@/lib/runs'
import { STATUS_DOT, runLabel, runSources, runWhen, staleNotice } from '@/lib/runs'
import { ThemeToggle } from '../ThemeToggle'
import { ToastProvider } from '../Toast'
import { BottomTabs, SidebarLinks } from './Navigation'
import { RunsPill, type RunView } from './RunsPill'

const brand = (
  <span className="brand-mark" aria-hidden="true">
    A
  </span>
)

/**
 * The app frame from the mockups: a sidebar on desktop, a status bar with the latest runs, the
 * stale banner, the disclaimer, and tabs at the bottom on phones.
 */
export function Shell({
  runs,
  lastPublished,
  children,
}: {
  runs: Run[]
  lastPublished: Run | null
  children: React.ReactNode
}) {
  const views: RunView[] = runs.map((r) => ({
    id: r.id,
    dot: STATUS_DOT[r.status],
    label: runLabel(r),
    when: runWhen(r),
    status: r.status,
    note: r.status === 'failed' ? (r.summary.failed_reason ?? []).join('; ') || null : null,
    sources: runSources(r),
  }))
  const latest = runs[0]
  const sources = latest ? runSources(latest) : null
  const stale = staleNotice(runs, lastPublished)
  return (
    <ToastProvider>
      <div className="shell">
        <aside className="sidebar" aria-label="Main">
          <Link className="brand" href="/">
            {brand}ADVISOR
          </Link>
          <SidebarLinks />
          <div className="sidebar-foot">
            <form action={signOut}>
              <button type="submit" className="btn btn-ghost btn-sm" style={{ paddingLeft: 0 }}>
                <LogOut />
                Sign out
              </button>
            </form>
          </div>
        </aside>
        <div className="content">
          <header className="statusbar">
            <Link className="brand" href="/" aria-label="Advisor">
              {brand}
            </Link>
            <RunsPill runs={views} />
            {sources && (
              <span className="pill hide-sm">
                <span className="num">{sources}</span>&nbsp;sources
              </span>
            )}
            {/* Every market is in its paper period until picks are graded live (spec §6.6, Plan 4). */}
            <span className="pill hide-sm" title="No picks graded live yet">
              <span className="dot paper" />
              US Paper
            </span>
            <span className="pill hide-sm" title="No picks graded live yet">
              <span className="dot paper" />
              TSX Paper
            </span>
            <span className="status-spacer" />
            <ThemeToggle />
          </header>
          <div className="banners" aria-live="polite">
            {stale && (
              <div className="banner danger">
                <TriangleAlert />
                <div>
                  <strong>{stale.title}</strong> {stale.detail}
                </div>
              </div>
            )}
          </div>
          {children}
          <footer className="disclaimer">
            {DISCLAIMER}
            <br />
            {CREDITS}
          </footer>
        </div>
        <BottomTabs />
      </div>
    </ToastProvider>
  )
}
```

- [ ] **Step 10: Write the signed-in layout, sign-out and a placeholder home page**

`web/app/(app)/actions.ts`:

```ts
'use server'

import { redirect } from 'next/navigation'
import { createClient } from '@/lib/supabase/server'

/** Signs out this browser only; the owner's other devices stay signed in. */
export async function signOut() {
  const supabase = await createClient()
  await supabase.auth.signOut({ scope: 'local' })
  redirect('/login')
}
```

`web/app/(app)/layout.tsx`:

```tsx
import { LogOut } from 'lucide-react'
import { Shell } from '@/components/shell/Shell'
import { session } from '@/lib/auth'
import { lastPublishedRun, recentRuns } from '@/lib/data/runs'
import { signOut } from './actions'

/**
 * Every signed-in page. Only the owner named in `app_config` sees data (row-level security, spec
 * §8); anyone else who signs in gets this notice instead of empty pages.
 */
export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const { supabase, owner } = await session()
  if (!owner) {
    return (
      <main className="login-wrap">
        <div className="login">
          <div className="card empty" style={{ padding: 24 }}>
            <strong>This account isn&apos;t the owner</strong>
            <span>
              The dashboard shows data only to the owner set in <code>app_config</code>. Sign out and sign in as the
              owner.
            </span>
            <form action={signOut}>
              <button type="submit" className="btn btn-secondary">
                <LogOut />
                Sign out
              </button>
            </form>
          </div>
        </div>
      </main>
    )
  }

  const [runs, lastPublished] = await Promise.all([recentRuns(supabase), lastPublishedRun(supabase)])
  return (
    <Shell runs={runs} lastPublished={lastPublished}>
      {children}
    </Shell>
  )
}
```

`web/app/(app)/page.tsx` (Task 5 replaces it with My Portfolio):

```tsx
import type { Metadata } from 'next'
import { ownerClient } from '@/lib/auth'

export const metadata: Metadata = { title: 'My Portfolio' }

/** My Portfolio, the home page (spec §9). Values, returns and warnings come next. */
export default async function PortfolioPage() {
  const supabase = await ownerClient()
  if (!supabase) return null // the layout is showing the not-the-owner notice
  return (
    <main className="page">
      <h1>My Portfolio</h1>
    </main>
  )
}
```

- [ ] **Step 11: Run the tests**

Run: `npm test`
Expected: `Test Files  9 passed (9)`, `Tests  62 passed (62)`.

Run: `npm run e2e`
Expected: `11 passed`, with no `[WebServer] ⨯ Error` line.

Then `npm run lint` and `npm run typecheck` are clean.

- [ ] **Step 12: Commit**

```bash
git add web/lib web/proxy.ts web/app web/components web/playwright.config.ts web/e2e
git commit -m "feat: sign in, the owner gate and the app shell"
```

End the message with your `Co-Authored-By:` trailer.

---

### Task 5: Show My Portfolio: value, returns chart, warnings and holdings

**Files:**
- Create: `web/lib/chart.ts`, `web/lib/data/settings.ts`, `web/lib/data/symbols.ts`, `web/lib/data/portfolio.ts`
- Create: `web/components/Tabs.tsx`, `web/components/TweenNumber.tsx`, `web/components/LineChart.tsx`, `web/components/portfolio/ValueCard.tsx`, `web/components/portfolio/Cards.tsx`
- Modify: `web/app/(app)/page.tsx` (replace the placeholder)
- Test: `web/lib/chart.test.ts`, `web/e2e/portfolio.spec.ts`

**Interfaces:**
- Consumes:
  - Task 3's `portfolioView`, `PeriodReturns` and `Period`;
  - Task 2's `FxRates`, `PriceBook`, `Totals` and `Slice`;
  - `lib/data/fetch.ts`;
  - `lib/auth.ts` `ownerClient`.
- Produces:
  - `lib/chart.ts`: `PAD`, `MIN_WIDTH`, `MORPH_POINTS`, `Geometry`, `geometry(width, height, lines)`, `linePath(values, g)`, `resample(values, k)`, `indexAt(px, n, g)`, `ease(k)`.
  - `lib/data/settings.ts`: `Settings` and `loadSettings`. `lib/data/symbols.ts`: `loadNames` and `isListedStock`.
  - `lib/data/portfolio.ts`: `loadTrades`, `loadFx`, `AssetRef`, `loadCloses(supabase, assets, since)`, `BENCHMARK_ASSETS`, `PortfolioData` and `loadPortfolio`.
  - `components/Tabs.tsx`: `Tabs`, with a sliding indicator. `components/LineChart.tsx`: `LineChart`, `Benchmark`. `components/TweenNumber.tsx`: `TweenNumber`.

**What the page shows before the model:**
- **Page head and value card:**
  - The head names the accounts held and the latest Bank of Canada rate.
  - The value card shows total value, unrealized P/L and cost.
  - Its 1M, 3M, 12M and All tabs switch the returns line (portfolio, XIU.TO, SPY in CAD) and the chart, which morphs between periods in 250 ms.
- **Actions** is an empty state, because the model doesn't exist yet.
- **Warnings** lists trades the ledger left out, then the TFSA and superficial-loss warnings.
- **Breakdown** splits value by market and by account.
- **The holdings table** shows account, symbol and name, market, value, P/L and notes. The notes cover holdings at cost, loss windows and taxable estimates. On phones each holding stacks into a row.

- [ ] **Step 1: Write the failing unit test**

`web/lib/chart.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { PAD, ease, geometry, indexAt, linePath, resample } from './chart'

describe('geometry', () => {
  const g = geometry(400, 240, [[0, 10], [5, 20]])

  it('pads the value range by 10% and spans the plot', () => {
    expect([g.lo, g.hi]).toEqual([-2, 22])
    expect(g.plotW).toBe(400 - PAD.l - PAD.r)
    expect(g.y(22)).toBe(PAD.t)
    expect(g.y(-2)).toBe(240 - PAD.b)
    expect(g.x(0, 5)).toBe(PAD.l)
    expect(g.x(4, 5)).toBe(PAD.l + g.plotW)
  })

  it('puts grid lines 15%, 50% and 85% of the way down', () => {
    expect(g.ticks.map((t) => +t.toFixed(1))).toEqual([18.4, 10, 1.6])
  })

  it('never draws narrower than 300 px, and survives a flat line', () => {
    const flat = geometry(120, 200, [[5, 5, 5]])
    expect(flat.width).toBe(300)
    expect([flat.lo, flat.hi]).toEqual([4, 6])
  })

  it('draws a path through every point', () => {
    // Plot height 100 − 18 − 26 = 56 over the range −2..22: y(0) = 18 + 56 × 22/24.
    expect(linePath([0, 20], geometry(300, 100, [[0, 20]]))).toBe('M4.0,69.3L238.0,22.7')
  })

  it('finds the point under the pointer', () => {
    expect(indexAt(PAD.l, 5, g)).toBe(0)
    expect(indexAt(PAD.l + g.plotW, 5, g)).toBe(4)
    expect(indexAt(PAD.l + g.plotW + 60, 5, g)).toBeNull()
  })
})

describe('resample', () => {
  it('stretches a line to k points by linear interpolation', () => {
    expect(resample([0, 10], 5)).toEqual([0, 2.5, 5, 7.5, 10])
    expect(resample([3], 3)).toEqual([3, 3, 3])
    expect(resample([1, 2, 3], 3)).toEqual([1, 2, 3])
  })
})

describe('ease', () => {
  it('starts slow, ends slow, and is symmetric', () => {
    expect(ease(0)).toBe(0)
    expect(ease(0.5)).toBe(0.5)
    expect(ease(1)).toBe(1)
    expect(ease(0.25)).toBeCloseTo(1 - ease(0.75))
  })
})
```

- [ ] **Step 2: Run it and see it fail**

Run: `npm test -- lib/chart.test.ts`
Expected: `Error: Cannot find module './chart'`.

- [ ] **Step 3: Write the chart geometry**

`web/lib/chart.ts`:

```ts
/**
 * Geometry for the Ledger line chart (ported from the mockups' `lineChart`). The SVG is drawn at
 * the container's real width, 1 unit = 1 px, so its 10 px labels stay 10 px on a phone.
 */

export const PAD = { l: 4, r: 62, t: 18, b: 26 } as const
export const MIN_WIDTH = 300
/** Points both windows are resampled to while one morphs into the other. */
export const MORPH_POINTS = 160

export interface Geometry {
  width: number
  height: number
  plotW: number
  plotH: number
  lo: number
  hi: number
  /** Three grid lines: 15%, 50% and 85% of the way down. */
  ticks: number[]
  x: (i: number, n: number) => number
  y: (v: number) => number
}

export function geometry(width: number, height: number, lines: readonly (readonly number[])[]): Geometry {
  const w = Math.max(MIN_WIDTH, Math.round(width))
  const plotW = w - PAD.l - PAD.r
  const plotH = height - PAD.t - PAD.b
  const values = lines.flat()
  let lo = Math.min(...values)
  let hi = Math.max(...values)
  const pad = (hi - lo) * 0.1 || 1
  lo -= pad
  hi += pad
  return {
    width: w,
    height,
    plotW,
    plotH,
    lo,
    hi,
    ticks: [0.15, 0.5, 0.85].map((f) => lo + (hi - lo) * (1 - f)),
    x: (i, n) => PAD.l + (n > 1 ? i / (n - 1) : 0) * plotW,
    y: (v) => PAD.t + (1 - (v - lo) / (hi - lo)) * plotH,
  }
}

export const linePath = (values: readonly number[], g: Geometry): string =>
  values.map((v, i) => `${i ? 'L' : 'M'}${g.x(i, values.length).toFixed(1)},${g.y(v).toFixed(1)}`).join('')

/** Linear resampling to k points, so two windows of different lengths can morph point by point. */
export function resample(values: readonly number[], k: number): number[] {
  if (values.length === k) return [...values]
  if (values.length === 1) return Array.from({ length: k }, () => values[0])
  return Array.from({ length: k }, (_, i) => {
    const x = (i / (k - 1)) * (values.length - 1)
    const lo = Math.floor(x)
    const hi = Math.min(values.length - 1, lo + 1)
    return values[lo] + (values[hi] - values[lo]) * (x - lo)
  })
}

/** The data index under a pointer at `px` (in SVG units), or null outside the line. */
export function indexAt(px: number, n: number, g: Geometry): number | null {
  const i = Math.round(((px - PAD.l) / g.plotW) * (n - 1))
  return i < 0 || i >= n ? null : i
}

/** Ease in and out, as the mockups' tween. */
export const ease = (k: number): number => (k < 0.5 ? 2 * k * k : 1 - (-2 * k + 2) ** 2 / 2)
```

- [ ] **Step 4: Run it**

Run: `npm test -- lib/chart.test.ts`
Expected: `Tests  7 passed (7)`.

- [ ] **Step 5: Write the failing browser tests**

`web/e2e/portfolio.spec.ts`:

```ts
import { expect, test, type Page } from '@playwright/test'
import { daysAgo, resetData, seedCloses, seedFx, seedLot, seedSell, seedSymbols, weekdays } from './db'

test.beforeEach(resetData)

const holdings = (page: Page) => page.locator('#holdings tbody tr')

test('an empty portfolio invites the first buy', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'My Portfolio' })).toBeVisible()
  await expect(page.getByText('No holdings yet. Add your first buy to start.')).toBeVisible()
  await expect(page.getByText('No actions yet')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Sell' })).toHaveCount(0)
})

/** RY.TO and AAPL in the TFSA, ETH in the crypto account (part sold at a loss 5 days ago). */
async function seedPortfolio() {
  const days = weekdays(daysAgo(60))
  const allDays = Array.from({ length: 61 }, (_, i) => daysAgo(60 - i)).filter((d) => d < daysAgo(0))
  await seedSymbols([
    { symbol: 'RY.TO', market: 'TSX', name: 'Royal Bank of Canada' },
    { symbol: 'AAPL', market: 'US', name: 'Apple Inc.' },
  ])
  await seedFx(days, 1.4)
  await seedCloses('XIU.TO', 'stock', 'CAD', days, 40, 0.05)
  await seedCloses('SPY', 'stock', 'USD', days, 500, 0.5)
  await seedCloses('RY.TO', 'stock', 'CAD', days, 170, 0.25)
  await seedCloses('AAPL', 'stock', 'USD', days, 200, 0.5)
  await seedCloses('ETH', 'crypto', 'USD', allDays, 3000, -5)
  await seedLot({ account: 'tfsa', symbol: 'RY.TO', asset_type: 'stock', qty: 10, price: 170, currency: 'CAD', bought_at: days[0] })
  await seedLot({ account: 'tfsa', symbol: 'AAPL', asset_type: 'stock', qty: 5, price: 200, currency: 'USD', fx_rate_cad: 1.4, bought_at: days[0] })
  await seedLot({ account: 'crypto', symbol: 'ETH', asset_type: 'crypto', qty: 2, price: 4200, currency: 'CAD', bought_at: days[0] })
  await seedSell({ account: 'crypto', symbol: 'ETH', asset_type: 'crypto', qty: 1, price: 3900, currency: 'CAD', sold_at: daysAgo(5) })
}

test('holdings are valued in CAD, charted against both benchmarks, and warned about', async ({ page }) => {
  await seedPortfolio()
  await page.goto('/')

  await expect(page.getByText('Crypto and TFSA accounts · values in CAD at the latest Bank of Canada rate (1.4000)')).toBeVisible()
  await expect(holdings(page)).toHaveCount(3)
  const ry = holdings(page).filter({ hasText: 'RY.TO' })
  await expect(ry).toContainText('Royal Bank of Canada')
  await expect(ry).toContainText('TSX')
  const eth = holdings(page).filter({ hasText: 'ETH' })
  await expect(eth).toContainText(/Loss window to/)
  await expect(eth).toContainText(/Taxable: est\./)

  await expect(page.getByRole('img', { name: 'Portfolio return against XIU.TO and SPY in CAD' })).toBeVisible()
  await expect(page.getByText(/since the first buy, /)).toBeVisible()
  await page.getByRole('tab', { name: '1M' }).click()
  await expect(page.getByText('over the last month')).toBeVisible()
  await expect(page.getByRole('tab', { name: '1M' })).toHaveAttribute('aria-selected', 'true')

  await expect(page.getByText('ETH: superficial-loss window')).toBeVisible()
  const breakdown = page.getByRole('heading', { name: 'Breakdown' }).locator('..')
  await expect(breakdown).toContainText('By market')
  await expect(breakdown).toContainText('TFSA')
})
```

- [ ] **Step 6: Run them and see them fail**

Run: `npm run e2e -- e2e/portfolio.spec.ts`
Expected: `2 failed` and `1 passed` (the setup). The placeholder page has no "No holdings yet" text and no holdings table.

- [ ] **Step 7: Write the data loaders**

`web/lib/data/settings.ts`:

```ts
import 'server-only'
import type { Supabase } from '../supabase/server'
import { must } from './fetch'

/** The one `settings` row (spec §8). */
export interface Settings {
  usd_fx_fee_pct: number
  crypto_fee_pct: number
  tfsa_round_trips_warn: number
  tfsa_short_hold_share_warn: number
  updated_at: string
}

export async function loadSettings(supabase: Supabase): Promise<Settings> {
  const row = must(
    await supabase
      .from('settings')
      .select('usd_fx_fee_pct, crypto_fee_pct, tfsa_round_trips_warn, tfsa_short_hold_share_warn, updated_at')
      .eq('id', 1)
      .single(),
  ) as Record<string, string | number>
  return {
    usd_fx_fee_pct: Number(row.usd_fx_fee_pct),
    crypto_fee_pct: Number(row.crypto_fee_pct),
    tfsa_round_trips_warn: Number(row.tfsa_round_trips_warn),
    tfsa_short_hold_share_warn: Number(row.tfsa_short_hold_share_warn),
    updated_at: String(row.updated_at),
  }
}
```

`web/lib/data/symbols.ts`:

```ts
import 'server-only'
import type { Supabase } from '../supabase/server'
import { must } from './fetch'

/** Company names of listed stocks; coins have none stored. */
export async function loadNames(supabase: Supabase, symbols: readonly string[]): Promise<Map<string, string>> {
  if (symbols.length === 0) return new Map()
  const rows = must(
    await supabase.from('symbols').select('symbol, name').eq('asset_type', 'stock').in('symbol', [...new Set(symbols)]),
  ) as { symbol: string; name: string }[]
  return new Map(rows.map((r) => [r.symbol, r.name]))
}

/** Whether a stock is in the US or TSX lists the pipeline keeps (ETFs aren't). */
export async function isListedStock(supabase: Supabase, symbol: string): Promise<boolean> {
  const rows = must(
    await supabase.from('symbols').select('symbol').eq('asset_type', 'stock').eq('symbol', symbol).limit(1),
  ) as unknown[]
  return rows.length > 0
}
```

`web/lib/data/portfolio.ts`:

```ts
import 'server-only'
import { addDays } from '../dates'
import { FxRates, PriceBook } from '../portfolio/lookup'
import { assetKey } from '../portfolio/types'
import type { Account, AssetType, Close, Currency, Trade } from '../portfolio/types'
import type { Supabase } from '../supabase/server'
import { fetchAll } from './fetch'
import { loadSettings, type Settings } from './settings'
import { loadNames } from './symbols'

interface TradeRow {
  account: Account
  symbol: string
  asset_type: AssetType
  qty: string | number
  price: string | number
  currency: Currency
  fx_rate_cad: string | number | null
}

const toTrade = (side: Trade['side'], day: string, row: TradeRow): Trade => ({
  side,
  account: row.account,
  symbol: row.symbol,
  assetType: row.asset_type,
  qty: Number(row.qty),
  price: Number(row.price),
  currency: row.currency,
  fxRateCad: row.fx_rate_cad === null ? null : Number(row.fx_rate_cad),
  day,
})

const TRADE_COLUMNS = 'id, account, symbol, asset_type, qty, price, currency, fx_rate_cad'

/** Every buy (`lots`) and sell (`sells`). Postgres numerics arrive as strings. */
export async function loadTrades(supabase: Supabase): Promise<Trade[]> {
  const [lots, sells] = await Promise.all([
    fetchAll((from, to) => supabase.from('lots').select(`${TRADE_COLUMNS}, bought_at`).order('id').range(from, to)),
    fetchAll((from, to) => supabase.from('sells').select(`${TRADE_COLUMNS}, sold_at`).order('id').range(from, to)),
  ])
  return [
    ...(lots as (TradeRow & { bought_at: string })[]).map((r) => toTrade('buy', r.bought_at, r)),
    ...(sells as (TradeRow & { sold_at: string })[]).map((r) => toTrade('sell', r.sold_at, r)),
  ]
}

export async function loadFx(supabase: Supabase): Promise<FxRates> {
  const rows = (await fetchAll((from, to) =>
    supabase.from('fx_rates').select('day, usd_cad').order('day').range(from, to),
  )) as { day: string; usd_cad: string | number }[]
  return new FxRates(rows.map((r) => ({ day: r.day, usdCad: Number(r.usd_cad) })))
}

export interface AssetRef {
  symbol: string
  assetType: AssetType
}

/** Closes for these assets from `since` on, one request per asset type and page. */
export async function loadCloses(supabase: Supabase, assets: readonly AssetRef[], since: string): Promise<PriceBook> {
  const byKey = new Map<string, Close[]>()
  for (const assetType of ['stock', 'crypto'] as const) {
    const symbols = [...new Set(assets.filter((a) => a.assetType === assetType).map((a) => a.symbol))]
    if (symbols.length === 0) continue
    const rows = (await fetchAll((from, to) =>
      supabase
        .from('daily_closes')
        .select('symbol, day, close, currency')
        .eq('asset_type', assetType)
        .in('symbol', symbols)
        .gte('day', since)
        .order('symbol')
        .order('day')
        .range(from, to),
    )) as { symbol: string; day: string; close: string | number; currency: Currency }[]
    for (const row of rows) {
      const key = assetKey(assetType, row.symbol)
      const list = byKey.get(key) ?? []
      list.push({ day: row.day, close: Number(row.close), currency: row.currency })
      byKey.set(key, list)
    }
  }
  return new PriceBook(byKey)
}

export const BENCHMARK_ASSETS: AssetRef[] = [
  { symbol: 'XIU.TO', assetType: 'stock' },
  { symbol: 'SPY', assetType: 'stock' },
]

export interface PortfolioData {
  trades: Trade[]
  prices: PriceBook
  fx: FxRates
  names: Map<string, string>
  settings: Settings
}

/** Everything the portfolio page values and charts. */
export async function loadPortfolio(supabase: Supabase): Promise<PortfolioData> {
  const [trades, fx, settings] = await Promise.all([loadTrades(supabase), loadFx(supabase), loadSettings(supabase)])
  const traded = trades.map((t) => ({ symbol: t.symbol, assetType: t.assetType }))
  const firstDay = trades.reduce<string | null>((min, t) => (min === null || t.day < min ? t.day : min), null)
  // A week before the first buy, so a buy on a holiday still finds the close before it.
  const since = firstDay === null ? '9999-12-31' : addDays(firstDay, -7)
  const [prices, names] = await Promise.all([
    loadCloses(supabase, firstDay === null ? [] : [...traded, ...BENCHMARK_ASSETS], since),
    loadNames(supabase, traded.filter((a) => a.assetType === 'stock').map((a) => a.symbol)),
  ])
  return { trades, prices, fx, names, settings }
}
```

- [ ] **Step 8: Write the components**

`web/components/Tabs.tsx`:

```tsx
'use client'

import { useCallback, useLayoutEffect, useRef, useState } from 'react'

export interface TabItem<T extends string> {
  value: T
  label: string
}

/**
 * The Ledger segmented control: a card-coloured indicator slides under the selected tab (200 ms).
 * The first placement doesn't animate.
 */
export function Tabs<T extends string>({
  items,
  value,
  onChange,
  label,
  className = '',
}: {
  items: readonly TabItem<T>[]
  value: T
  onChange: (value: T) => void
  label: string
  className?: string
}) {
  const buttons = useRef(new Map<T, HTMLButtonElement>())
  const [indicator, setIndicator] = useState<{ width: number; x: number; animate: boolean } | null>(null)
  const placed = useRef(false)

  const place = useCallback(
    (animate: boolean) => {
      const button = buttons.current.get(value)
      if (!button) return
      setIndicator({ width: button.offsetWidth, x: button.offsetLeft - 3, animate })
    },
    [value],
  )

  useLayoutEffect(() => {
    place(placed.current)
    placed.current = true
  }, [place])

  useLayoutEffect(() => {
    const again = () => place(false)
    window.addEventListener('resize', again)
    document.fonts?.ready.then(again)
    return () => window.removeEventListener('resize', again)
  }, [place])

  return (
    <div className={`tabs ${className}`} role="tablist" aria-label={label}>
      {indicator && (
        <span
          className="tab-indicator"
          style={{
            left: 3,
            width: indicator.width,
            transform: `translateX(${indicator.x}px)`,
            transition: indicator.animate ? undefined : 'none',
          }}
        />
      )}
      {items.map((item) => (
        <button
          key={item.value}
          ref={(el) => {
            if (el) buttons.current.set(item.value, el)
            else buttons.current.delete(item.value)
          }}
          type="button"
          role="tab"
          className="tab"
          aria-selected={item.value === value}
          onClick={() => onChange(item.value)}
        >
          {item.label}
        </button>
      ))}
    </div>
  )
}
```

`web/components/TweenNumber.tsx`:

```tsx
'use client'

import { useEffect, useRef, useState } from 'react'
import { ease } from '@/lib/chart'

/** A number that counts to its new value over 250 ms (the mockups' `tweenNumber`). */
export function TweenNumber({
  value,
  format,
  className,
}: {
  value: number
  format: (value: number) => string
  className?: string
}) {
  const [shown, setShown] = useState(value)
  const from = useRef(value)

  useEffect(() => {
    const start = performance.now()
    const begin = from.current
    from.current = value
    if (begin === value) return
    const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches
    let frame = requestAnimationFrame(function step(now) {
      const k = reduce ? 1 : Math.min(1, (now - start) / 250)
      setShown(begin + (value - begin) * ease(k))
      if (k < 1) frame = requestAnimationFrame(step)
    })
    return () => cancelAnimationFrame(frame)
  }, [value])

  return <span className={className}>{format(shown)}</span>
}
```

`web/components/LineChart.tsx`:

```tsx
'use client'

import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { MORPH_POINTS, PAD, ease, geometry, indexAt, linePath, resample } from '@/lib/chart'

export interface Benchmark {
  values: number[]
  color: string
}

interface Drawn {
  series: number[]
  benchmarks: Benchmark[]
  dates: string[]
}

/**
 * The Ledger line chart (the mockups' `lineChart`, without the forecast cone, which comes with the
 * ticker page). The main line draws in over 600 ms, benchmark lines fade in, and a new window of
 * data morphs from the old one over 250 ms. Hovering shows the day and value under the pointer.
 */
export function LineChart({
  series,
  dates,
  benchmarks = [],
  height = 240,
  format = (v) => v.toFixed(2),
  label,
}: {
  series: number[]
  dates: string[]
  benchmarks?: Benchmark[]
  height?: number
  format?: (value: number) => string
  label: string
}) {
  const box = useRef<HTMLDivElement>(null)
  const mainLine = useRef<SVGPathElement>(null)
  const lastWidth = useRef<number | null>(null)
  const shown = useRef<Drawn>({ series, benchmarks, dates })
  const [width, setWidth] = useState<number | null>(null)
  const [intro, setIntro] = useState(true)
  const [drawn, setDrawn] = useState<Drawn>(shown.current)
  const [hover, setHover] = useState<number | null>(null)

  // Measure before the first paint, so the line draws in once, at the real width. A later
  // resize redraws without the intro.
  useLayoutEffect(() => {
    const el = box.current
    if (!el) return
    const measure = () => {
      const w = el.clientWidth
      if (lastWidth.current !== null && Math.round(lastWidth.current) !== Math.round(w)) setIntro(false)
      lastWidth.current = w
      setWidth(w)
    }
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  // The draw-in animation needs the main line's length.
  useLayoutEffect(() => {
    if (intro && mainLine.current) {
      mainLine.current.style.setProperty('--len', String(Math.ceil(mainLine.current.getTotalLength())))
    }
  }, [intro, width])

  useEffect(() => {
    shown.current = drawn
  }, [drawn])

  // A new window of data morphs from the one on screen.
  useEffect(() => {
    const from = shown.current
    if (from.series === series && from.benchmarks === benchmarks && from.dates === dates) return
    const target: Drawn = { series, benchmarks, dates }
    let frame = 0
    if (matchMedia('(prefers-reduced-motion: reduce)').matches) {
      frame = requestAnimationFrame(() => {
        setIntro(false)
        setDrawn(target)
      })
      return () => cancelAnimationFrame(frame)
    }
    const fromS = resample(from.series, MORPH_POINTS)
    const toS = resample(series, MORPH_POINTS)
    const fromB = benchmarks.map((b, j) => resample(from.benchmarks[j]?.values ?? b.values, MORPH_POINTS))
    const toB = benchmarks.map((b) => resample(b.values, MORPH_POINTS))
    const morphDates = resample(dates.map((_, i) => i), MORPH_POINTS).map((x) => dates[Math.round(x)])
    const start = performance.now()
    frame = requestAnimationFrame(function step(now) {
      const k = Math.min(1, (now - start) / 250)
      const e = ease(k)
      setIntro(false)
      if (k < 1) {
        setDrawn({
          series: fromS.map((v, i) => v + (toS[i] - v) * e),
          benchmarks: benchmarks.map((b, j) => ({ ...b, values: fromB[j].map((v, i) => v + (toB[j][i] - v) * e) })),
          dates: morphDates,
        })
        frame = requestAnimationFrame(step)
      } else {
        setDrawn(target)
      }
    })
    return () => cancelAnimationFrame(frame)
  }, [series, benchmarks, dates])

  const n = drawn.series.length
  const g =
    width === null || n < 2 ? null : geometry(width, height, [drawn.series, ...drawn.benchmarks.map((b) => b.values)])

  const onMove = (event: React.PointerEvent<SVGSVGElement>) => {
    if (!g) return
    const rect = event.currentTarget.getBoundingClientRect()
    setHover(indexAt(((event.clientX - rect.left) / rect.width) * g.width, n, g))
  }

  const hx = g && hover !== null ? g.x(hover, n) : 0
  const hy = g && hover !== null ? g.y(drawn.series[hover]) : 0
  // The SVG is scaled down only when the box is narrower than the 300 px minimum.
  const scale = g && width ? width / g.width : 1
  return (
    <div ref={box} className="chart">
      {g && (
        <svg
          role="img"
          aria-label={label}
          viewBox={`0 0 ${g.width} ${height}`}
          onPointerMove={onMove}
          onPointerLeave={() => setHover(null)}
        >
          <g className="grid">
            {g.ticks.map((v) => (
              <g key={v}>
                <line x1={PAD.l} x2={PAD.l + g.plotW} y1={g.y(v)} y2={g.y(v)} />
                <text x={g.width - 4} y={g.y(v) + 3} textAnchor="end">
                  {format(v)}
                </text>
              </g>
            ))}
          </g>
          {drawn.benchmarks.map((b, j) => (
            <path
              key={j}
              d={linePath(b.values, g)}
              fill="none"
              stroke={b.color}
              strokeWidth={1.6}
              strokeLinejoin="round"
              className={intro ? 'late' : undefined}
            />
          ))}
          <path
            ref={mainLine}
            d={linePath(drawn.series, g)}
            fill="none"
            stroke="var(--chart-1)"
            strokeWidth={2}
            strokeLinejoin="round"
            strokeLinecap="round"
            className={intro ? 'draw main-line' : 'main-line'}
          />
          <circle
            cx={g.x(n - 1, n)}
            cy={g.y(drawn.series[n - 1])}
            r={4}
            fill="var(--chart-1)"
            stroke="var(--card)"
            strokeWidth={2}
          />
          <text x={PAD.l} y={height - 6}>
            {drawn.dates[0]}
          </text>
          <text x={g.x(n - 1, n)} y={height - 6} textAnchor="end">
            {drawn.dates[n - 1]}
          </text>
          <line
            x1={hx}
            x2={hx}
            y1={PAD.t}
            y2={PAD.t + g.plotH}
            stroke="var(--muted-foreground)"
            strokeDasharray="3 3"
            opacity={hover === null ? 0 : 0.6}
          />
          <circle cx={hx} cy={hy} r={4} fill="var(--chart-1)" opacity={hover === null ? 0 : 1} />
        </svg>
      )}
      {g && width !== null && hover !== null && (
        <div
          className="tip show"
          style={{
            left: Math.min(width - 150, Math.max(0, hx * scale - 60)),
            top: Math.max(0, hy * scale - 44),
          }}
        >
          <span className="muted">{drawn.dates[hover]}</span>{' '}
          <span className="num" style={{ fontWeight: 600 }}>
            {format(drawn.series[hover])}
          </span>
        </div>
      )}
    </div>
  )
}
```

`web/components/portfolio/ValueCard.tsx`:

```tsx
'use client'

import { useMemo, useState } from 'react'
import { LineChart, type Benchmark } from '@/components/LineChart'
import { Tabs } from '@/components/Tabs'
import { TweenNumber } from '@/components/TweenNumber'
import { longDay, shortDay } from '@/lib/dates'
import { fmtMoney, fmtPct } from '@/lib/format'
import type { Period, PeriodReturns } from '@/lib/portfolio/returns'
import type { Totals } from '@/lib/portfolio/valuation'

const PERIOD_TABS = [
  { value: '1m', label: '1M' },
  { value: '3m', label: '3M' },
  { value: '12m', label: '12M' },
  { value: 'all', label: 'All' },
] as const

const last = (values: number[] | null) => (values ? values[values.length - 1] : null)

/** Value and returns (spec §7.4): total value in CAD, and the return against XIU.TO and SPY in CAD. */
export function ValueCard({
  totals,
  periods,
  firstBuy,
}: {
  totals: Totals
  periods: Record<Period, PeriodReturns> | null
  firstBuy: string | null
}) {
  const [period, setPeriod] = useState<Period>('all')
  const r = periods?.[period] ?? null
  const dates = useMemo(() => r?.days.map(shortDay) ?? [], [r])
  const benchmarks = useMemo(() => {
    const lines: Benchmark[] = []
    if (r?.xiu) lines.push({ values: r.xiu, color: 'var(--chart-2)' })
    if (r?.spy) lines.push({ values: r.spy, color: 'var(--chart-3)' })
    return lines
  }, [r])
  const label = {
    '1m': 'over the last month',
    '3m': 'over 3 months',
    '12m': 'over 12 months',
    all: firstBuy ? `since the first buy, ${longDay(firstBuy)}` : 'since the first buy',
  }[period]
  const portfolio = last(r?.portfolio ?? null)
  const xiu = last(r?.xiu ?? null)
  const spy = last(r?.spy ?? null)

  return (
    <section className="card card-pad enter" aria-labelledby="value-h">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <span className="label" id="value-h">
            Portfolio value
          </span>
          <div className="value-big" style={{ marginTop: 8 }}>
            {fmtMoney(totals.valueCad)}
          </div>
          <div className="num" style={{ marginTop: 6, fontSize: 13 }}>
            <span className={totals.gainCad < 0 ? 'loss' : 'gain'}>
              {fmtMoney(totals.gainCad, { signed: true })} unrealized
            </span>{' '}
            <span className="muted">· cost {fmtMoney(totals.costCad)}</span>
          </div>
        </div>
        {r && portfolio !== null && (
          <div className="grid gap-3 justify-items-end">
            <Tabs items={PERIOD_TABS} value={period} onChange={setPeriod} label="Period" />
            <div className="num" style={{ fontSize: 13, textAlign: 'right' }}>
              <span className="muted">{label}</span>
              <br />
              Portfolio{' '}
              <b>
                <TweenNumber value={portfolio} format={fmtPct} className={portfolio < 0 ? 'loss' : 'gain'} />
              </b>
              {xiu !== null && (
                <>
                  {' '}
                  <span className="muted">· XIU.TO</span> <TweenNumber value={xiu} format={fmtPct} />
                </>
              )}
              {spy !== null && (
                <>
                  {' '}
                  <span className="muted">· SPY in CAD</span> <TweenNumber value={spy} format={fmtPct} />
                </>
              )}
            </div>
          </div>
        )}
      </div>
      {r ? (
        <>
          <div style={{ marginTop: 14 }}>
            <LineChart
              series={r.portfolio}
              dates={dates}
              benchmarks={benchmarks}
              height={230}
              format={(v) => fmtPct(v)}
              label="Portfolio return against XIU.TO and SPY in CAD"
            />
          </div>
          <div className="legend" style={{ marginTop: 6 }}>
            <span>
              <i style={{ background: 'var(--chart-1)' }} />
              Portfolio
            </span>
            {r.xiu && (
              <span>
                <i style={{ background: 'var(--chart-2)' }} />
                XIU.TO
              </span>
            )}
            {r.spy && (
              <span>
                <i style={{ background: 'var(--chart-3)' }} />
                SPY in CAD
              </span>
            )}
          </div>
        </>
      ) : (
        <p className="sub" style={{ margin: '14px 0 0' }}>
          {firstBuy
            ? 'The chart starts once your holdings have closes on two trading days. The pipeline stores them each run.'
            : 'No holdings yet. Add your first buy to start.'}
        </p>
      )}
    </section>
  )
}
```

`web/components/portfolio/Cards.tsx`:

```tsx
import { Info, Sparkles, TriangleAlert } from 'lucide-react'
import { fmtAmount, fmtPct } from '@/lib/format'
import { ACCOUNT_LABELS } from '@/lib/portfolio/types'
import type { Slice } from '@/lib/portfolio/valuation'
import type { HoldingRow } from '@/lib/portfolio/view'
import type { Warning } from '@/lib/portfolio/warnings'

/** Sell, Trim, Review, Add and Hold come from the model (Plan 4); until then, this says so. */
export function ActionsCard() {
  return (
    <div className="card card-pad enter" aria-labelledby="actions-h">
      <div className="section-head">
        <h2 id="actions-h">Actions</h2>
        <span className="sub">Sell → Trim → Review → Add → Hold</span>
      </div>
      <div className="empty">
        <Sparkles />
        <strong>No actions yet</strong>
        <span style={{ maxWidth: 440 }}>
          Sell, Trim, Review, Add and Hold come from the model, which isn&apos;t trained yet. Until then, this page shows
          values and P/L, and the warnings that don&apos;t need the model.
        </span>
      </div>
    </div>
  )
}

export function WarningsCard({ warnings }: { warnings: Warning[] }) {
  return (
    <div className="card card-pad enter" aria-labelledby="warn-h">
      <div className="section-head" style={{ marginBottom: 2 }}>
        <h2 id="warn-h">Warnings</h2>
        <span className="sub">not tax advice</span>
      </div>
      {warnings.length === 0 ? (
        <p className="sub" style={{ margin: '8px 0 0' }}>
          None. TFSA trading frequency and superficial losses are checked here.
        </p>
      ) : (
        warnings.map((w) => (
          <div className="warning" key={`${w.title}:${w.detail}`}>
            <TriangleAlert />
            <strong>{w.title}</strong>
            <p>{w.detail}</p>
          </div>
        ))
      )}
    </div>
  )
}

const MARKET_COLOURS: Record<string, string> = { US: 'var(--chart-1)', TSX: 'var(--chart-2)', Crypto: 'var(--chart-3)' }
const ACCOUNT_COLOURS: Record<string, string> = {
  [ACCOUNT_LABELS.tfsa]: 'var(--chart-1)',
  [ACCOUNT_LABELS.rrsp]: 'var(--chart-2)',
  [ACCOUNT_LABELS.fhsa]: 'var(--chart-4)',
  [ACCOUNT_LABELS.non_registered]: 'var(--hold)',
  [ACCOUNT_LABELS.crypto]: 'var(--chart-3)',
}

function Stack({ title, slices, colours }: { title: string; slices: Slice[]; colours: Record<string, string> }) {
  return (
    <div>
      <span className="label">{title}</span>
      <div className="stack" style={{ marginTop: 8 }} role="img" aria-label={slices.map((s) => `${s.label} ${s.share.toFixed(1)}%`).join(', ')}>
        {slices.map((s) => (
          <span key={s.label} style={{ width: `${s.share}%`, background: colours[s.label] }} />
        ))}
      </div>
      <div className="stack-legend">
        {slices.map((s) => (
          <span key={s.label}>
            {s.label} <b>{s.share.toFixed(1)}%</b>
          </span>
        ))}
      </div>
    </div>
  )
}

/** By market and by account (spec §7.4). By risk level comes with the model. */
export function BreakdownCard({ byMarket, byAccount }: { byMarket: Slice[]; byAccount: Slice[] }) {
  return (
    <div className="card card-pad enter" aria-labelledby="mix-h">
      <h2 id="mix-h" style={{ marginBottom: 12 }}>
        Breakdown
      </h2>
      {byMarket.length === 0 ? (
        <p className="sub" style={{ margin: 0 }}>
          Appears with your first holding.
        </p>
      ) : (
        <div className="grid gap-4">
          <Stack title="By market" slices={byMarket} colours={MARKET_COLOURS} />
          <Stack title="By account" slices={byAccount} colours={ACCOUNT_COLOURS} />
        </div>
      )}
    </div>
  )
}

export function HoldingsCard({ holdings, accounts }: { holdings: HoldingRow[]; accounts: number }) {
  return (
    <section className="card card-pad enter" aria-labelledby="hold-h">
      <div className="section-head">
        <h2 id="hold-h">Holdings</h2>
        <span className="sub">
          {holdings.length} {holdings.length === 1 ? 'position' : 'positions'} · {accounts}{' '}
          {accounts === 1 ? 'account' : 'accounts'}
        </span>
      </div>
      <div className="before-note">
        <Info />
        <span>Actions, likely ranges, trailing stops, exit dates and risk levels appear once the model runs.</span>
      </div>
      {holdings.length === 0 ? (
        <p className="sub" style={{ margin: 0 }}>
          No holdings yet.
        </p>
      ) : (
        <div className="table-scroll">
          <table className="data-table" id="holdings">
            <thead>
              <tr>
                <th>Account</th>
                <th>Symbol</th>
                <th>Market</th>
                <th className="r">Value C$</th>
                <th className="r">P/L C$</th>
                <th>Notes</th>
              </tr>
            </thead>
            <tbody>
              {holdings.map((h) => {
                const tone = h.gainCad < 0 ? 'loss' : 'gain'
                return (
                  <tr key={h.key}>
                    <td className="sub h-acct">{ACCOUNT_LABELS[h.account]}</td>
                    <td className="h-sym">
                      <span className="sym">{h.symbol}</span>
                      {h.name && (
                        <>
                          <br />
                          <span className="sub">{h.name}</span>
                        </>
                      )}
                    </td>
                    <td className={h.market ? 'h-mkt' : 'sub h-mkt'}>{h.market ?? '—'}</td>
                    <td className="r num h-value">{fmtAmount(h.valueCad)}</td>
                    <td className={`r num h-pl ${tone}`}>
                      {fmtAmount(h.gainCad, { signed: true })}
                      <br />
                      <span className={`sub ${tone}`}>{fmtPct(h.gainPct)}</span>
                    </td>
                    <td className="h-note">
                      {h.notes.length === 0 ? (
                        <span className="sub">—</span>
                      ) : (
                        h.notes.map((n) =>
                          n.warn ? (
                            <span key={n.text} className="warn-cell">
                              <TriangleAlert />
                              {n.text}
                            </span>
                          ) : (
                            <span key={n.text} className="sub" style={{ display: 'block' }}>
                              {n.text}
                            </span>
                          ),
                        )
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
```

- [ ] **Step 9: Replace the placeholder home page**

`web/app/(app)/page.tsx` (Task 6 adds the Buy and Sell buttons):

```tsx
import type { Metadata } from 'next'
import { ActionsCard, BreakdownCard, HoldingsCard, WarningsCard } from '@/components/portfolio/Cards'
import { ValueCard } from '@/components/portfolio/ValueCard'
import { ownerClient } from '@/lib/auth'
import { loadPortfolio } from '@/lib/data/portfolio'
import { todayInToronto } from '@/lib/dates'
import { portfolioView } from '@/lib/portfolio/view'

export const metadata: Metadata = { title: 'My Portfolio' }

/** My Portfolio, the home page (spec §9), as it stands before the model: values, returns, warnings. */
export default async function PortfolioPage() {
  const supabase = await ownerClient()
  if (!supabase) return null // the layout is showing the not-the-owner notice
  const data = await loadPortfolio(supabase)
  const today = todayInToronto()
  const view = portfolioView(
    {
      trades: data.trades,
      prices: data.prices,
      fx: data.fx,
      names: data.names,
      guideline: {
        roundTrips: data.settings.tfsa_round_trips_warn,
        shortHoldShare: data.settings.tfsa_short_hold_share_warn,
      },
    },
    today,
  )
  const accounts = view.accounts.length === 0 ? 'No accounts yet' : `${view.accounts.join(' and ')} accounts`
  const rate = view.fx ? ` (${view.fx.usdCad.toFixed(4)})` : ''

  return (
    <main className="page">
      <div className="section-head enter" style={{ marginBottom: 0 }}>
        <div>
          <h1>My Portfolio</h1>
          <p className="sub">
            {accounts} · values in CAD at the latest Bank of Canada rate{rate}
          </p>
        </div>
      </div>
      <ValueCard totals={view.totals} periods={view.periods} firstBuy={view.firstBuy} />
      <section className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_330px]" style={{ alignItems: 'start' }}>
        <ActionsCard />
        <aside className="grid gap-4">
          <WarningsCard warnings={view.warnings} />
          <BreakdownCard byMarket={view.byMarket} byAccount={view.byAccount} />
        </aside>
      </section>
      <HoldingsCard holdings={view.holdings} accounts={view.accounts.length} />
    </main>
  )
}
```

- [ ] **Step 10: Run the tests**

Run: `npm test`
Expected: `Test Files  10 passed (10)`, `Tests  69 passed (69)`.

Run: `npm run e2e`
Expected: `13 passed`. Then `npm run lint` and `npm run typecheck` are clean.

- [ ] **Step 11: Commit**

```bash
git add web/lib web/components web/app web/e2e
git commit -m "feat: show My Portfolio: value, returns chart, warnings and holdings"
```

End the message with your `Co-Authored-By:` trailer.

---

### Task 6: Add buys and sells from the portfolio page

**Files:**
- Create: `web/lib/trade-form.ts`, `web/app/(app)/trades.ts`, `web/components/portfolio/TradeForms.tsx`
- Modify: `web/app/(app)/page.tsx` (adds the Buy and Sell buttons)
- Test: `web/lib/trade-form.test.ts`, `web/e2e/trades.spec.ts`

**Interfaces:**
- Consumes:
  - Task 3's `SellOption`;
  - Task 2's `buildLedger`, `positionKey`, `QTY_EPSILON` and `FxRates`;
  - Task 5's `loadTrades`, `loadFx` and `isListedStock`;
  - Task 4's `Drawer` and `useToast`;
  - `lib/symbols.ts`.
- Produces:
  - `lib/trade-form.ts`: `FieldErrors`, `FormState` (`ok`, `message`, `errors`, `confirm`, `at`), `parseAmount`, `RATE_RANGE`, `BuyInput`, `parseBuy(form, today)`, `Held`, `SellInput`, `parseSell(form, held, today)`, `formFields(formData)`. Task 7's forms use `FormState`, `FieldErrors`, `parseAmount` and `formFields`.
  - `app/(app)/trades.ts`: the server actions `addBuy` and `addSell`.
  - `components/portfolio/TradeForms.tsx`: `TradeButtons`.

**The rules:**
- **The trade's account and currency** come from the symbol:
  - the crypto account means a coin;
  - a US stock trades in USD, everything else in CAD (spec rev 2).
- **A USD trade's rate** defaults to the Bank of Canada rate on or before its day; the owner can type Wealthsimple's rate instead. A blank rate is filled in by the server.
- **A stock missing from the lists** (`symbols`) asks "save it anyway?". A held stock Yahoo can't price leaves every run degraded, and ETFs aren't listed.
- **A sell** must come from an open position, be no more than is held, and be dated no earlier than the position's opening.
- **The sell form previews the gain** at average cost, with the account's tax note.
- **Every field is controlled,** so an error keeps what was typed.

- [ ] **Step 1: Write the failing unit test**

`web/lib/trade-form.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { parseBuy, parseSell, type Held } from './trade-form'

const TODAY = '2026-10-16'
const buy = (over: Record<string, string> = {}) => ({
  account: 'tfsa',
  symbol: 'aapl',
  qty: '10',
  price: '182.50',
  day: '2026-10-15',
  fxRate: '1.3712',
  notes: '',
  ...over,
})

describe('parseBuy', () => {
  it('reads a US buy in USD with its rate', () => {
    expect(parseBuy(buy(), TODAY)).toEqual({
      input: {
        account: 'tfsa', symbol: 'AAPL', assetType: 'stock', currency: 'USD',
        qty: 10, price: 182.5, day: '2026-10-15', fxRateCad: 1.3712, notes: null,
      },
    })
  })

  it('leaves the rate to the Bank of Canada when it is blank', () => {
    expect(parseBuy(buy({ fxRate: '' }), TODAY)).toMatchObject({ input: { fxRateCad: null } })
  })

  it('reads TSX stocks and coins in CAD, with no rate', () => {
    expect(parseBuy(buy({ symbol: 'rci.b.to', price: '1,234.5' }), TODAY)).toMatchObject({
      input: { symbol: 'RCI-B.TO', currency: 'CAD', price: 1234.5, fxRateCad: null },
    })
    expect(parseBuy(buy({ account: 'crypto', symbol: 'btc', qty: '0.015' }), TODAY)).toMatchObject({
      input: { assetType: 'crypto', currency: 'CAD', qty: 0.015 },
    })
  })

  it('names every field that is wrong', () => {
    expect(
      parseBuy(
        buy({ account: 'margin', symbol: 'not a symbol', qty: '0', price: 'abc', day: '2026-10-17', fxRate: '137', notes: 'x'.repeat(501) }),
        TODAY,
      ),
    ).toEqual({
      errors: {
        account: 'Pick an account.',
        symbol: 'Enter a symbol like AAPL or RY.TO.',
        qty: 'Enter a quantity above 0.',
        price: 'Enter a price above 0.',
        day: "The date can't be after today.",
        fxRate: 'Enter the USD/CAD rate, for example 1.37.',
        notes: 'Keep notes under 500 characters.',
      },
    })
  })

  it('asks for a coin symbol in the crypto account', () => {
    expect(parseBuy(buy({ account: 'crypto', symbol: 'RY.TO' }), TODAY)).toEqual({
      errors: { symbol: 'Enter a coin symbol, like BTC.' },
    })
  })
})

describe('parseSell', () => {
  const HELD: Held[] = [
    { key: 'tfsa:stock:SHOP.TO', account: 'tfsa', symbol: 'SHOP.TO', assetType: 'stock', qty: 15, openedOn: '2026-05-01' },
    { key: 'tfsa:stock:NVDA', account: 'tfsa', symbol: 'NVDA', assetType: 'stock', qty: 8, openedOn: '2026-01-10' },
  ]
  const sell = (over: Record<string, string> = {}) => ({
    holding: 'tfsa:stock:SHOP.TO', qty: '15', price: '141', day: '2026-10-16', fxRate: '', ...over,
  })

  it('sells from a held position in its currency', () => {
    expect(parseSell(sell(), HELD, TODAY)).toEqual({
      input: {
        account: 'tfsa', symbol: 'SHOP.TO', assetType: 'stock', currency: 'CAD',
        qty: 15, price: 141, day: '2026-10-16', fxRateCad: null,
      },
    })
    expect(parseSell(sell({ holding: 'tfsa:stock:NVDA', qty: '4', fxRate: '1.38' }), HELD, TODAY)).toMatchObject({
      input: { symbol: 'NVDA', currency: 'USD', fxRateCad: 1.38 },
    })
  })

  it('refuses more than is held, a day before the buy, and an unknown holding', () => {
    expect(parseSell(sell({ qty: '16' }), HELD, TODAY)).toEqual({ errors: { qty: 'You hold 15 in your TFSA.' } })
    expect(parseSell(sell({ day: '2026-04-30' }), HELD, TODAY)).toEqual({
      errors: { day: "That's before you bought it, on May 1, 2026." },
    })
    expect(parseSell(sell({ holding: 'tfsa:stock:AAPL' }), HELD, TODAY)).toEqual({ errors: { holding: 'Pick a holding.' } })
  })
})
```

- [ ] **Step 2: Run it and see it fail**

Run: `npm test -- lib/trade-form.test.ts`
Expected: `Error: Cannot find module './trade-form'`.

- [ ] **Step 3: Write the form checks**

`web/lib/trade-form.ts`:

```ts
/** Checks for the buy and sell forms (spec §7.1). The server actions run them; the database's
 * CHECK constraints are the last line. */

import { QTY_EPSILON } from './portfolio/ledger'
import { ACCOUNTS, ACCOUNT_LABELS } from './portfolio/types'
import type { Account, AssetType, Currency } from './portfolio/types'
import { fmtQty } from './format'
import { longDay } from './dates'
import { isValidSymbol, normalizeSymbol, tradeCurrency } from './symbols'

export type FieldErrors = Partial<Record<string, string>>

/** What a trade form's server action answers. `at` tells two identical answers apart. */
export interface FormState {
  ok?: boolean
  message?: string
  errors?: FieldErrors
  /** A stock that isn't in the lists: the owner must confirm it. */
  confirm?: string
  at?: number
}

/** A typed amount: "1,234.50" or "$12" read as numbers; anything else is null. */
export const parseAmount = (raw: string | undefined): number | null => {
  const text = (raw ?? '').replace(/[,\s$]/g, '')
  if (text === '' || !/^\d*\.?\d+$/.test(text)) return null
  return Number(text)
}
const number = parseAmount

const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/
const validDay = (day: string) => ISO_DAY.test(day) && !Number.isNaN(Date.parse(`${day}T00:00:00Z`))

/** USD/CAD outside this range is a typo, not a rate. */
export const RATE_RANGE = [0.5, 3] as const

interface Common {
  qty: number
  price: number
  day: string
  /** For a USD trade: the rate entered, or null to use the Bank of Canada's. */
  fxRateCad: number | null
}

function common(form: Record<string, string>, today: string, currency: Currency, errors: FieldErrors): Common | null {
  const qty = number(form.qty)
  const price = number(form.price)
  const day = (form.day ?? '').trim()
  if (qty === null || qty <= 0) errors.qty = 'Enter a quantity above 0.'
  if (price === null || price <= 0) errors.price = 'Enter a price above 0.'
  if (!validDay(day)) errors.day = 'Enter a date.'
  else if (day > today) errors.day = "The date can't be after today."
  let fxRateCad: number | null = null
  if (currency === 'USD' && (form.fxRate ?? '').trim() !== '') {
    fxRateCad = number(form.fxRate)
    if (fxRateCad === null || fxRateCad < RATE_RANGE[0] || fxRateCad > RATE_RANGE[1]) {
      errors.fxRate = 'Enter the USD/CAD rate, for example 1.37.'
    }
  }
  if (qty === null || price === null || errors.qty || errors.price || errors.day || errors.fxRate) return null
  return { qty, price, day, fxRateCad }
}

export interface BuyInput extends Common {
  account: Account
  symbol: string
  assetType: AssetType
  currency: Currency
  notes: string | null
}

export function parseBuy(form: Record<string, string>, today: string): { input: BuyInput } | { errors: FieldErrors } {
  const errors: FieldErrors = {}
  const account = form.account as Account
  if (!ACCOUNTS.includes(account)) errors.account = 'Pick an account.'
  const assetType: AssetType = account === 'crypto' ? 'crypto' : 'stock'
  const symbol = normalizeSymbol(form.symbol ?? '')
  if (!isValidSymbol(symbol, assetType)) {
    errors.symbol = assetType === 'crypto' ? 'Enter a coin symbol, like BTC.' : 'Enter a symbol like AAPL or RY.TO.'
  }
  const currency = tradeCurrency(assetType, symbol)
  const notes = (form.notes ?? '').trim()
  if (notes.length > 500) errors.notes = 'Keep notes under 500 characters.'
  const rest = common(form, today, currency, errors)
  if (!rest || Object.keys(errors).length > 0) return { errors }
  return { input: { ...rest, account, symbol, assetType, currency, notes: notes || null } }
}

/** An open position the sell form can sell from. */
export interface Held {
  key: string
  account: Account
  symbol: string
  assetType: AssetType
  qty: number
  openedOn: string
}

export interface SellInput extends Common {
  account: Account
  symbol: string
  assetType: AssetType
  currency: Currency
}

export function parseSell(
  form: Record<string, string>,
  held: readonly Held[],
  today: string,
): { input: SellInput } | { errors: FieldErrors } {
  const errors: FieldErrors = {}
  const position = held.find((h) => h.key === form.holding)
  if (!position) {
    errors.holding = 'Pick a holding.'
    return { errors }
  }
  const currency = tradeCurrency(position.assetType, position.symbol)
  const rest = common(form, today, currency, errors)
  if (rest && rest.qty > position.qty + QTY_EPSILON) {
    errors.qty = `You hold ${fmtQty(position.qty)} in your ${ACCOUNT_LABELS[position.account]}.`
  }
  if (rest && rest.day < position.openedOn) errors.day = `That's before you bought it, on ${longDay(position.openedOn)}.`
  if (!rest || Object.keys(errors).length > 0) return { errors }
  return {
    input: { ...rest, account: position.account, symbol: position.symbol, assetType: position.assetType, currency },
  }
}

/** FormData as plain strings; files and repeated fields aren't used by these forms. */
export const formFields = (form: FormData): Record<string, string> =>
  Object.fromEntries([...form.entries()].map(([k, v]) => [k, typeof v === 'string' ? v : '']))
```

- [ ] **Step 4: Run it**

Run: `npm test -- lib/trade-form.test.ts`
Expected: `Tests  7 passed (7)`.

- [ ] **Step 5: Write the failing browser tests**

`web/e2e/trades.spec.ts`:

```ts
import { expect, test, type Page } from '@playwright/test'
import { daysAgo, resetData, seedFx, seedLot, seedSymbols, sql } from './db'

test.beforeEach(resetData)

const holdings = (page: Page) => page.locator('#holdings tbody tr')

async function openBuy(page: Page) {
  await page.goto('/')
  await page.getByRole('button', { name: 'Buy' }).click()
  return page.getByRole('dialog', { name: 'Add a buy' })
}

test('a buy is saved and shows up as a holding', async ({ page }) => {
  await seedSymbols([{ symbol: 'RY.TO', market: 'TSX', name: 'Royal Bank of Canada' }])
  const drawer = await openBuy(page)
  await drawer.getByLabel('Symbol').fill('ry.to')
  await expect(drawer.getByLabel('Price (CAD)')).toBeVisible()
  await expect(drawer.getByLabel('USD/CAD rate')).toHaveCount(0)
  await drawer.getByLabel('Quantity').fill('10')
  await drawer.getByLabel('Price (CAD)').fill('184.50')
  await drawer.getByRole('button', { name: 'Save buy' }).click()

  await expect(page.getByRole('status')).toHaveText('Buy saved: 10 RY.TO in TFSA')
  await expect(drawer).toBeHidden()
  await expect(holdings(page).filter({ hasText: 'RY.TO' })).toContainText('No close yet; at cost')
  const [lot] = await sql`select symbol, qty::float as qty, price::float as price, currency, fx_rate_cad from lots`
  expect(lot).toEqual({ symbol: 'RY.TO', qty: 10, price: 184.5, currency: 'CAD', fx_rate_cad: null })
})

test('a US buy uses the Bank of Canada rate unless another is entered', async ({ page }) => {
  await seedSymbols([{ symbol: 'AAPL', market: 'US', name: 'Apple Inc.' }])
  await seedFx([daysAgo(3)], 1.3712)
  const drawer = await openBuy(page)
  await drawer.getByLabel('Symbol').fill('AAPL')
  await expect(drawer.getByLabel('USD/CAD rate')).toHaveValue('1.3712')
  await drawer.getByLabel('Quantity').fill('2')
  await drawer.getByLabel('Price (USD)').fill('180')
  await drawer.getByLabel('USD/CAD rate').fill('1.3918')
  await drawer.getByRole('button', { name: 'Save buy' }).click()
  await expect(page.getByRole('status')).toHaveText('Buy saved: 2 AAPL in TFSA')
  const [lot] = await sql`select currency, fx_rate_cad::float as rate from lots`
  expect(lot).toEqual({ currency: 'USD', rate: 1.3918 })
})

test('mistakes are named and what was typed stays', async ({ page }) => {
  const drawer = await openBuy(page)
  await drawer.getByLabel('Symbol').fill('RY.TO')
  await drawer.getByLabel('Quantity').fill('0')
  await drawer.getByLabel('Price (CAD)').fill('184')
  await drawer.getByRole('button', { name: 'Save buy' }).click()
  await expect(drawer.getByText('Enter a quantity above 0.')).toBeVisible()
  await expect(drawer.getByLabel('Price (CAD)')).toHaveValue('184')
  await expect(drawer.getByLabel('Symbol')).toHaveValue('RY.TO')
  expect(await sql`select 1 from lots`).toHaveLength(0)
})

test('a stock missing from the lists needs a second look', async ({ page }) => {
  const drawer = await openBuy(page)
  await drawer.getByLabel('Symbol').fill('XEQT.TO')
  await drawer.getByLabel('Quantity').fill('20')
  await drawer.getByLabel('Price (CAD)').fill('35')
  await drawer.getByRole('button', { name: 'Save buy' }).click()
  await expect(drawer.getByText(/XEQT\.TO isn't in the US or TSX stock lists/)).toBeVisible()
  expect(await sql`select 1 from lots`).toHaveLength(0)

  await drawer.getByLabel('Save it anyway').check()
  await drawer.getByRole('button', { name: 'Save buy' }).click()
  await expect(page.getByRole('status')).toHaveText('Buy saved: 20 XEQT.TO in TFSA')
})

test('a sell shows its gain at average cost and reduces the holding', async ({ page }) => {
  await seedSymbols([{ symbol: 'RY.TO', market: 'TSX', name: 'Royal Bank of Canada' }])
  await seedLot({ account: 'tfsa', symbol: 'RY.TO', asset_type: 'stock', qty: 10, price: 170, currency: 'CAD', bought_at: daysAgo(30) })
  await page.goto('/')
  await page.getByRole('button', { name: 'Sell' }).click()
  const drawer = page.getByRole('dialog', { name: 'Add a sell' })
  await expect(drawer.getByLabel('Holding')).toHaveValue('tfsa:stock:RY.TO')
  await expect(drawer.getByLabel('Quantity')).toHaveValue('10')
  await drawer.getByLabel('Quantity').fill('4')
  await drawer.getByLabel('Price (CAD)').fill('180')
  // 4 × (180 − 170) = +C$40, sheltered in the TFSA.
  await expect(drawer.getByText('+C$40 realized')).toBeVisible()
  await expect(drawer.getByText(/In a TFSA, gains and losses aren't taxed/)).toBeVisible()

  await drawer.getByLabel('Quantity').fill('11')
  await drawer.getByRole('button', { name: 'Save sell' }).click()
  await expect(drawer.getByText('You hold 10 in your TFSA.')).toBeVisible()

  await drawer.getByLabel('Quantity').fill('4')
  await drawer.getByRole('button', { name: 'Save sell' }).click()
  await expect(page.getByRole('status')).toHaveText('Sell saved: 4 RY.TO from TFSA')
  await expect(holdings(page).filter({ hasText: 'RY.TO' })).toBeVisible()
  const [held] = await sql`select (select sum(qty) from lots) - (select sum(qty) from sells) as qty`
  expect(Number(held.qty)).toBe(6)
})
```

- [ ] **Step 6: Run them and see them fail**

Run: `npm run e2e -- e2e/trades.spec.ts`
Expected: `5 failed` and `1 passed` (the setup). There's no Buy or Sell button yet.

- [ ] **Step 7: Write the server actions**

`web/app/(app)/trades.ts`:

```ts
'use server'

import { revalidatePath } from 'next/cache'
import { todayInToronto } from '@/lib/dates'
import { loadFx, loadTrades } from '@/lib/data/portfolio'
import { isListedStock } from '@/lib/data/symbols'
import { fmtQty } from '@/lib/format'
import { buildLedger, positionKey } from '@/lib/portfolio/ledger'
import { ACCOUNT_LABELS } from '@/lib/portfolio/types'
import { createClient } from '@/lib/supabase/server'
import { formFields, parseBuy, parseSell, type FormState } from '@/lib/trade-form'

const failed = (message: string): FormState => ({ message, at: Date.now() })

/** Add a buy (a `lots` row). Row-level security lets only the owner insert. */
export async function addBuy(_: FormState, form: FormData): Promise<FormState> {
  const fields = formFields(form)
  const parsed = parseBuy(fields, todayInToronto())
  if ('errors' in parsed) return { errors: parsed.errors, at: Date.now() }
  const buy = parsed.input
  const supabase = await createClient()

  // A held stock Yahoo can't price leaves every run degraded, so a typo is worth a second look.
  // ETFs aren't in the lists, so the owner can still confirm one.
  if (buy.assetType === 'stock' && fields.confirmUnlisted !== 'on' && !(await isListedStock(supabase, buy.symbol))) {
    return {
      confirm: `${buy.symbol} isn't in the US or TSX stock lists (ETFs aren't listed). Check the symbol, or save it anyway.`,
      at: Date.now(),
    }
  }

  let rate = buy.fxRateCad
  if (buy.currency === 'USD' && rate === null) {
    rate = (await loadFx(supabase)).on(buy.day)
    if (rate === null) {
      return { errors: { fxRate: 'No Bank of Canada rate on or before that day yet; enter the rate.' }, at: Date.now() }
    }
  }

  const { error } = await supabase.from('lots').insert({
    account: buy.account,
    symbol: buy.symbol,
    asset_type: buy.assetType,
    qty: buy.qty,
    price: buy.price,
    currency: buy.currency,
    fx_rate_cad: buy.currency === 'USD' ? rate : null,
    bought_at: buy.day,
    notes: buy.notes,
  })
  if (error) return failed(`The buy wasn't saved: ${error.message}`)
  revalidatePath('/')
  return { ok: true, message: `Buy saved: ${fmtQty(buy.qty)} ${buy.symbol} in ${ACCOUNT_LABELS[buy.account]}`, at: Date.now() }
}

/** Add a sell (a `sells` row), checked against what the ledger says is held. */
export async function addSell(_: FormState, form: FormData): Promise<FormState> {
  const supabase = await createClient()
  const [trades, fx] = await Promise.all([loadTrades(supabase), loadFx(supabase)])
  const held = buildLedger(trades, fx).positions.map((p) => ({ ...p, key: positionKey(p) }))
  const parsed = parseSell(formFields(form), held, todayInToronto())
  if ('errors' in parsed) return { errors: parsed.errors, at: Date.now() }
  const sell = parsed.input

  let rate = sell.fxRateCad
  if (sell.currency === 'USD' && rate === null) {
    rate = fx.on(sell.day)
    if (rate === null) {
      return { errors: { fxRate: 'No Bank of Canada rate on or before that day yet; enter the rate.' }, at: Date.now() }
    }
  }

  const { error } = await supabase.from('sells').insert({
    account: sell.account,
    symbol: sell.symbol,
    asset_type: sell.assetType,
    qty: sell.qty,
    price: sell.price,
    currency: sell.currency,
    fx_rate_cad: sell.currency === 'USD' ? rate : null,
    sold_at: sell.day,
  })
  if (error) return failed(`The sell wasn't saved: ${error.message}`)
  revalidatePath('/')
  return { ok: true, message: `Sell saved: ${fmtQty(sell.qty)} ${sell.symbol} from ${ACCOUNT_LABELS[sell.account]}`, at: Date.now() }
}
```

- [ ] **Step 8: Write the drawers and put the buttons on the page**

`web/components/portfolio/TradeForms.tsx`:

```tsx
'use client'

import { Minus, Plus, TriangleAlert } from 'lucide-react'
import { useActionState, useCallback, useEffect, useMemo, useState } from 'react'
import { addBuy, addSell } from '@/app/(app)/trades'
import { Drawer } from '@/components/Drawer'
import { useToast } from '@/components/Toast'
import { shortDay } from '@/lib/dates'
import { fmtMoney, fmtQty } from '@/lib/format'
import { FxRates, type FxRate } from '@/lib/portfolio/lookup'
import { ACCOUNTS, ACCOUNT_LABELS, TAXABLE } from '@/lib/portfolio/types'
import type { Account } from '@/lib/portfolio/types'
import type { SellOption } from '@/lib/portfolio/view'
import { normalizeSymbol, tradeCurrency } from '@/lib/symbols'
import { parseAmount, type FormState } from '@/lib/trade-form'

/**
 * A field's error from the last answer, until the owner edits the field. Every field is
 * controlled: React resets uncontrolled fields after each action, which would wipe what the
 * owner typed whenever the server answers with an error.
 */
function useFieldErrors(state: FormState) {
  const [edited, setEdited] = useState<Record<string, number>>({})
  const editedSince = (name: string) => (edited[name] ?? 0) > (state.at ?? 0)
  const error = (name: string) => {
    const message = state.errors?.[name]
    return message && !editedSince(name) ? message : undefined
  }
  const touch = (name: string) => setEdited((e) => ({ ...e, [name]: Date.now() }))
  return { error, touch, editedSince }
}

function Foot({ pending, label, icon, onCancel }: { pending: boolean; label: string; icon?: React.ReactNode; onCancel: () => void }) {
  return (
    <div className="drawer-foot">
      <button type="button" className="btn btn-secondary" onClick={onCancel}>
        Cancel
      </button>
      <button type="submit" className="btn btn-primary" disabled={pending}>
        {icon}
        {pending ? 'Saving…' : label}
      </button>
    </div>
  )
}

/** On success: toast, then close. */
function useDone(state: FormState, onDone: (message: string) => void) {
  useEffect(() => {
    if (state.ok && state.message) onDone(state.message)
  }, [state, onDone])
}

function Field({
  label,
  error,
  hint,
  children,
}: {
  label: React.ReactNode
  error?: string
  hint?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <label className={`field ${error ? 'invalid' : ''}`}>
      <span>{label}</span>
      {children}
      {hint && <span className="hint">{hint}</span>}
      <span className="error">{error}</span>
    </label>
  )
}

/** The Bank of Canada rate for a day, as the rate field's default. */
const useBocRate = (rates: FxRate[], day: string) => {
  const fx = useMemo(() => new FxRates(rates), [rates])
  const rate = fx.on(day)
  const from = fx.rates.findLast((r) => r.day <= day)?.day ?? null
  return { rate: rate === null ? '' : rate.toFixed(4), from }
}

function FormMessage({ state }: { state: FormState }) {
  if (!state.message || state.ok) return null
  return (
    <div className="banner danger" role="alert">
      <TriangleAlert />
      <div>{state.message}</div>
    </div>
  )
}

interface FormProps {
  rates: FxRate[]
  today: string
  onDone: (message: string) => void
  onCancel: () => void
}

function BuyForm({ rates, today, onDone, onCancel }: FormProps) {
  const [state, action, pending] = useActionState<FormState, FormData>(addBuy, {})
  const { error, touch, editedSince } = useFieldErrors(state)
  useDone(state, onDone)
  const [account, setAccount] = useState<Account>('tfsa')
  const [symbol, setSymbol] = useState('')
  const [qty, setQty] = useState('')
  const [price, setPrice] = useState('')
  const [day, setDay] = useState(today)
  const [rate, setRate] = useState<string | null>(null)
  const [notes, setNotes] = useState('')
  const [confirmed, setConfirmed] = useState(false)
  const currency = tradeCurrency(account === 'crypto' ? 'crypto' : 'stock', normalizeSymbol(symbol))
  const boc = useBocRate(rates, day)
  // The unlisted-symbol question stands until the symbol changes.
  const askConfirm = state.confirm && !editedSince('symbol') ? state.confirm : null

  return (
    <form action={action} style={{ display: 'contents' }} noValidate>
      <div className="drawer-body">
        <FormMessage state={state} />
        <Field label="Account" error={error('account')}>
          <select
            className="select"
            name="account"
            value={account}
            onChange={(e) => {
              setAccount(e.target.value as Account)
              touch('account')
            }}
          >
            {ACCOUNTS.map((a) => (
              <option key={a} value={a}>
                {ACCOUNT_LABELS[a]}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Symbol" error={error('symbol')} hint="US: AAPL · TSX: RY.TO · crypto: BTC">
          <input
            className="input num-input"
            name="symbol"
            placeholder="AAPL, RY.TO or BTC"
            autoCapitalize="characters"
            value={symbol}
            onChange={(e) => {
              setSymbol(e.target.value)
              setConfirmed(false)
              touch('symbol')
            }}
          />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Quantity" error={error('qty')}>
            <input
              className="input num-input"
              name="qty"
              inputMode="decimal"
              placeholder="10"
              value={qty}
              onChange={(e) => {
                setQty(e.target.value)
                touch('qty')
              }}
            />
          </Field>
          <Field label={`Price (${currency})`} error={error('price')}>
            <input
              className="input num-input"
              name="price"
              inputMode="decimal"
              placeholder="184.00"
              value={price}
              onChange={(e) => {
                setPrice(e.target.value)
                touch('price')
              }}
            />
          </Field>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Date" error={error('day')}>
            <input
              className="input num-input"
              type="date"
              name="day"
              max={today}
              value={day}
              onChange={(e) => {
                setDay(e.target.value)
                touch('day')
              }}
            />
          </Field>
          {currency === 'USD' && (
            <Field
              label="USD/CAD rate"
              error={error('fxRate')}
              hint={boc.from ? `Bank of Canada, ${shortDay(boc.from)}. Enter Wealthsimple's rate to include its fee.` : 'Enter the rate you paid.'}
            >
              <input
                className="input num-input"
                name="fxRate"
                inputMode="decimal"
                value={rate ?? boc.rate}
                onChange={(e) => {
                  setRate(e.target.value)
                  touch('fxRate')
                }}
              />
            </Field>
          )}
        </div>
        <Field
          label={
            <>
              Notes <span className="muted">(optional)</span>
            </>
          }
          error={error('notes')}
        >
          <input
            className="input"
            name="notes"
            placeholder="Why you bought"
            value={notes}
            onChange={(e) => {
              setNotes(e.target.value)
              touch('notes')
            }}
          />
        </Field>
        {askConfirm && (
          <div className="banner warn">
            <TriangleAlert />
            <div style={{ display: 'grid', gap: 8 }}>
              <span>{askConfirm}</span>
              <label style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <input
                  type="checkbox"
                  name="confirmUnlisted"
                  checked={confirmed}
                  onChange={(e) => setConfirmed(e.target.checked)}
                />
                Save it anyway
              </label>
            </div>
          </div>
        )}
      </div>
      <Foot pending={pending} label="Save buy" icon={<Plus />} onCancel={onCancel} />
    </form>
  )
}

function SellForm({ options, rates, today, onDone, onCancel }: FormProps & { options: SellOption[] }) {
  const [state, action, pending] = useActionState<FormState, FormData>(addSell, {})
  const { error, touch } = useFieldErrors(state)
  useDone(state, onDone)
  const [key, setKey] = useState(options[0]?.key ?? '')
  const option = options.find((o) => o.key === key) ?? null
  const [qty, setQty] = useState(option ? String(option.qty) : '')
  const [price, setPrice] = useState('')
  const [day, setDay] = useState(today)
  const [rate, setRate] = useState<string | null>(null)
  const boc = useBocRate(rates, day)
  const usd = option?.currency === 'USD'

  const q = parseAmount(qty)
  const p = parseAmount(price)
  const r = usd ? parseAmount(rate ?? boc.rate) : 1
  const gain =
    option && q !== null && p !== null && r !== null && q > 0 && q <= option.qty + 1e-9
      ? q * p * r - (option.costCad * q) / option.qty
      : null

  return (
    <form action={action} style={{ display: 'contents' }} noValidate>
      <div className="drawer-body">
        <FormMessage state={state} />
        <Field label="Holding" error={error('holding')}>
          <select
            className="select"
            name="holding"
            value={key}
            onChange={(e) => {
              const next = options.find((o) => o.key === e.target.value)
              setKey(e.target.value)
              setQty(next ? String(next.qty) : '')
              setRate(null)
              touch('holding')
            }}
          >
            {options.map((o) => (
              <option key={o.key} value={o.key}>
                {`${o.symbol} · ${ACCOUNT_LABELS[o.account]} · ${fmtQty(o.qty)}${o.assetType === 'stock' ? ' shares' : ''}`}
              </option>
            ))}
          </select>
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Quantity" error={error('qty')}>
            <input
              className="input num-input"
              name="qty"
              inputMode="decimal"
              value={qty}
              onChange={(e) => {
                setQty(e.target.value)
                touch('qty')
              }}
            />
          </Field>
          <Field label={`Price (${option?.currency ?? 'CAD'})`} error={error('price')}>
            <input
              className="input num-input"
              name="price"
              inputMode="decimal"
              placeholder="141.00"
              value={price}
              onChange={(e) => {
                setPrice(e.target.value)
                touch('price')
              }}
            />
          </Field>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Date" error={error('day')}>
            <input
              className="input num-input"
              type="date"
              name="day"
              max={today}
              value={day}
              onChange={(e) => {
                setDay(e.target.value)
                touch('day')
              }}
            />
          </Field>
          {usd && (
            <Field
              label="USD/CAD rate"
              error={error('fxRate')}
              hint={boc.from ? `Bank of Canada, ${shortDay(boc.from)}` : 'Enter the rate you got.'}
            >
              <input
                className="input num-input"
                name="fxRate"
                inputMode="decimal"
                value={rate ?? boc.rate}
                onChange={(e) => {
                  setRate(e.target.value)
                  touch('fxRate')
                }}
              />
            </Field>
          )}
        </div>
        {option && gain !== null && (
          <div className="card card-pad" style={{ background: 'var(--muted)' }}>
            <span className="label">At average cost</span>
            <div className={`num ${gain < 0 ? 'loss' : 'gain'}`} style={{ fontSize: 18, fontWeight: 600, marginTop: 6 }}>
              {fmtMoney(gain, { signed: true })} realized
            </div>
            <p className="sub" style={{ margin: '4px 0 0' }}>
              {!TAXABLE.has(option.account)
                ? `In a ${ACCOUNT_LABELS[option.account]}, gains and losses aren't taxed.`
                : gain >= 0
                  ? `Taxable: est. ${fmtMoney(gain * 0.5, { signed: true })} at 50% inclusion.`
                  : `Buying ${option.symbol} within 30 days before or after this sale denies the loss.`}{' '}
              Not tax advice.
            </p>
          </div>
        )}
      </div>
      <Foot pending={pending} label="Save sell" onCancel={onCancel} />
    </form>
  )
}

/** The Buy and Sell buttons in the page head, and their drawers. */
export function TradeButtons({ sellable, rates, today }: { sellable: SellOption[]; rates: FxRate[]; today: string }) {
  const toast = useToast()
  const [open, setOpen] = useState<'buy' | 'sell' | null>(null)
  // Each opening starts a fresh form.
  const [round, setRound] = useState(0)
  const show = (which: 'buy' | 'sell') => {
    setRound((n) => n + 1)
    setOpen(which)
  }
  const close = useCallback(() => setOpen(null), [])
  const done = useCallback(
    (message: string) => {
      setOpen(null)
      toast(message)
    },
    [toast],
  )
  return (
    <>
      <div className="flex flex-wrap gap-2">
        {sellable.length > 0 && (
          <button type="button" className="btn btn-secondary" onClick={() => show('sell')}>
            <Minus />
            Sell
          </button>
        )}
        <button type="button" className="btn btn-primary" onClick={() => show('buy')}>
          <Plus />
          Buy
        </button>
      </div>
      <Drawer id="buy-drawer" title="Add a buy" open={open === 'buy'} onClose={close}>
        <BuyForm key={`buy-${round}`} rates={rates} today={today} onDone={done} onCancel={close} />
      </Drawer>
      <Drawer id="sell-drawer" title="Add a sell" open={open === 'sell'} onClose={close}>
        <SellForm key={`sell-${round}`} options={sellable} rates={rates} today={today} onDone={done} onCancel={close} />
      </Drawer>
    </>
  )
}
```

Replace `web/app/(app)/page.tsx` with:

```tsx
import type { Metadata } from 'next'
import { ActionsCard, BreakdownCard, HoldingsCard, WarningsCard } from '@/components/portfolio/Cards'
import { TradeButtons } from '@/components/portfolio/TradeForms'
import { ValueCard } from '@/components/portfolio/ValueCard'
import { ownerClient } from '@/lib/auth'
import { loadPortfolio } from '@/lib/data/portfolio'
import { todayInToronto } from '@/lib/dates'
import { portfolioView } from '@/lib/portfolio/view'

export const metadata: Metadata = { title: 'My Portfolio' }

/** My Portfolio, the home page (spec §9), as it stands before the model: values, returns, warnings. */
export default async function PortfolioPage() {
  const supabase = await ownerClient()
  if (!supabase) return null // the layout is showing the not-the-owner notice
  const data = await loadPortfolio(supabase)
  const today = todayInToronto()
  const view = portfolioView(
    {
      trades: data.trades,
      prices: data.prices,
      fx: data.fx,
      names: data.names,
      guideline: {
        roundTrips: data.settings.tfsa_round_trips_warn,
        shortHoldShare: data.settings.tfsa_short_hold_share_warn,
      },
    },
    today,
  )
  const accounts = view.accounts.length === 0 ? 'No accounts yet' : `${view.accounts.join(' and ')} accounts`
  const rate = view.fx ? ` (${view.fx.usdCad.toFixed(4)})` : ''

  return (
    <main className="page">
      <div className="section-head enter" style={{ marginBottom: 0 }}>
        <div>
          <h1>My Portfolio</h1>
          <p className="sub">
            {accounts} · values in CAD at the latest Bank of Canada rate{rate}
          </p>
        </div>
        <TradeButtons sellable={view.sellable} rates={[...data.fx.rates]} today={today} />
      </div>
      <ValueCard totals={view.totals} periods={view.periods} firstBuy={view.firstBuy} />
      <section className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_330px]" style={{ alignItems: 'start' }}>
        <ActionsCard />
        <aside className="grid gap-4">
          <WarningsCard warnings={view.warnings} />
          <BreakdownCard byMarket={view.byMarket} byAccount={view.byAccount} />
        </aside>
      </section>
      <HoldingsCard holdings={view.holdings} accounts={view.accounts.length} />
    </main>
  )
}
```

- [ ] **Step 9: Run the tests**

Run: `npm test`
Expected: `Test Files  11 passed (11)`, `Tests  76 passed (76)`.

Run: `npm run e2e`
Expected: `18 passed`. Then `npm run lint` and `npm run typecheck` are clean.

- [ ] **Step 10: Commit**

```bash
git add web/lib web/app web/components web/e2e
git commit -m "feat: add buys and sells from the portfolio page"
```

End the message with your `Co-Authored-By:` trailer.

---

### Task 7: Add the Watchlist and Settings pages

**Files:**
- Create: `web/lib/watch-form.ts`, `web/lib/settings-form.ts`, `web/lib/data/watchlist.ts`
- Create: `web/app/(app)/watchlist/actions.ts`, `web/app/(app)/watchlist/page.tsx`, `web/components/watchlist/Watchlist.tsx`
- Create: `web/app/(app)/settings/actions.ts`, `web/app/(app)/settings/page.tsx`, `web/components/settings/SettingsForms.tsx`
- Test: `web/lib/forms.test.ts`, `web/e2e/watchlist-settings.spec.ts`, `web/e2e/navigation.spec.ts`

**Interfaces:**
- Consumes:
  - Task 6's `FormState`, `FieldErrors`, `parseAmount` and `formFields`;
  - Task 5's `loadCloses`, `loadFx`, `loadNames`, `isListedStock`, `loadSettings` and `Tabs`;
  - Task 4's `useToast` and `signOut`;
  - `lib/theme.ts`.
- Produces:
  - `lib/watch-form.ts`: `WatchType`, `WATCH_TYPES` and `parseWatch(symbol, type)`.
  - `lib/settings-form.ts`: `SettingsInput` and `parseSettings(form)`.
  - `lib/data/watchlist.ts`: `WatchItem` and `loadWatchlist`.

**The rules:**
- **Watchlist:**
  - It takes US stocks, TSX stocks (".TO" is added when missing) and coins.
  - A duplicate is refused, and an unlisted stock is accepted with a note.
  - A coin's price shows in CAD.
  - There are no verdict columns until Plan 4.
- **Settings:**
  - Values stay within the database's CHECK limits: fees 0–10%, round trips 1–1,000, short holds 1–100%. Short holds are stored as 0..1.
  - Saving sets `updated_at`, because the table has no trigger.
  - The theme choice is per device.

- [ ] **Step 1: Write the failing unit test**

`web/lib/forms.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { parseSettings } from './settings-form'
import { parseWatch } from './watch-form'

describe('parseWatch', () => {
  it('reads US stocks, TSX stocks (adding .TO) and coins', () => {
    expect(parseWatch(' nvda ', 'us')).toEqual({ symbol: 'NVDA', assetType: 'stock' })
    expect(parseWatch('shop', 'tsx')).toEqual({ symbol: 'SHOP.TO', assetType: 'stock' })
    expect(parseWatch('rci.b', 'tsx')).toEqual({ symbol: 'RCI-B.TO', assetType: 'stock' })
    expect(parseWatch('dol.to', 'tsx')).toEqual({ symbol: 'DOL.TO', assetType: 'stock' })
    expect(parseWatch('eth', 'crypto')).toEqual({ symbol: 'ETH', assetType: 'crypto' })
  })

  it('explains what is wrong', () => {
    expect(parseWatch('', 'us')).toEqual({ error: 'Enter a symbol.' })
    expect(parseWatch('ry.to', 'us')).toEqual({ error: 'Symbols ending in .TO are TSX stocks; pick TSX stock.' })
    expect(parseWatch('TOOLONG', 'us')).toEqual({ error: 'Enter a US symbol, like NVDA or BRK.B.' })
    expect(parseWatch('E', 'crypto')).toEqual({ error: 'Enter a coin symbol, like ETH.' })
    expect(parseWatch('NVDA', 'bond')).toEqual({ error: 'Pick a type.' })
  })
})

describe('parseSettings', () => {
  const form = { usd_fx_fee_pct: '1.5', crypto_fee_pct: '2', tfsa_round_trips_warn: '24', tfsa_short_hold_share_warn: '50' }

  it('reads the four settings, the share as a fraction', () => {
    expect(parseSettings(form)).toEqual({
      input: { usd_fx_fee_pct: 1.5, crypto_fee_pct: 2, tfsa_round_trips_warn: 24, tfsa_short_hold_share_warn: 0.5 },
    })
    expect(parseSettings({ ...form, usd_fx_fee_pct: '0' })).toMatchObject({ input: { usd_fx_fee_pct: 0 } })
  })

  it("keeps each value within the database's limits", () => {
    expect(
      parseSettings({ usd_fx_fee_pct: '11', crypto_fee_pct: '', tfsa_round_trips_warn: '2.5', tfsa_short_hold_share_warn: '0' }),
    ).toEqual({
      errors: {
        usd_fx_fee_pct: 'Enter a fee from 0 to 10%.',
        crypto_fee_pct: 'Enter a spread from 0 to 10%.',
        tfsa_round_trips_warn: 'Enter a whole number from 1 to 1,000.',
        tfsa_short_hold_share_warn: 'Enter a share from 1 to 100%.',
      },
    })
  })
})
```

- [ ] **Step 2: Run it and see it fail**

Run: `npm test -- lib/forms.test.ts`
Expected: `Error: Cannot find module './settings-form'`.

- [ ] **Step 3: Write the form checks**

`web/lib/watch-form.ts`:

```ts
import type { AssetType } from './portfolio/types'
import { isValidSymbol, normalizeSymbol } from './symbols'

export type WatchType = 'us' | 'tsx' | 'crypto'
export const WATCH_TYPES: { value: WatchType; label: string }[] = [
  { value: 'us', label: 'US stock' },
  { value: 'tsx', label: 'TSX stock' },
  { value: 'crypto', label: 'Crypto' },
]

/**
 * A symbol for the watchlist (spec §9: US stocks, TSX stocks and crypto). A TSX stock typed
 * without its suffix gets ".TO"; a US stock can't have one.
 */
export function parseWatch(rawSymbol: string, type: string): { symbol: string; assetType: AssetType } | { error: string } {
  let symbol = normalizeSymbol(rawSymbol)
  if (!symbol) return { error: 'Enter a symbol.' }
  if (type === 'crypto') {
    return isValidSymbol(symbol, 'crypto') ? { symbol, assetType: 'crypto' } : { error: 'Enter a coin symbol, like ETH.' }
  }
  if (type === 'tsx') {
    if (!symbol.endsWith('.TO')) symbol = normalizeSymbol(`${symbol.replace('.', '-')}.TO`)
    return isValidSymbol(symbol, 'stock') ? { symbol, assetType: 'stock' } : { error: 'Enter a TSX symbol, like SHOP or RCI-B.' }
  }
  if (type === 'us') {
    if (symbol.endsWith('.TO')) return { error: 'Symbols ending in .TO are TSX stocks; pick TSX stock.' }
    return isValidSymbol(symbol, 'stock') ? { symbol, assetType: 'stock' } : { error: 'Enter a US symbol, like NVDA or BRK.B.' }
  }
  return { error: 'Pick a type.' }
}
```

`web/lib/settings-form.ts`:

```ts
import { parseAmount, type FieldErrors } from './trade-form'

export interface SettingsInput {
  usd_fx_fee_pct: number
  crypto_fee_pct: number
  tfsa_round_trips_warn: number
  /** 0..1; the form shows it as a percentage. */
  tfsa_short_hold_share_warn: number
}

/** The owner-editable settings (spec §3, §7.5), within the database's CHECK limits. */
export function parseSettings(form: Record<string, string>): { input: SettingsInput } | { errors: FieldErrors } {
  const errors: FieldErrors = {}
  const fee = (name: string, label: string) => {
    const value = parseAmount(form[name])
    if (value === null || value > 10) errors[name] = `Enter a ${label} from 0 to 10%.`
    return value ?? 0
  }
  const usd = fee('usd_fx_fee_pct', 'fee')
  const crypto = fee('crypto_fee_pct', 'spread')
  const trips = parseAmount(form.tfsa_round_trips_warn)
  if (trips === null || !Number.isInteger(trips) || trips < 1 || trips > 1000) {
    errors.tfsa_round_trips_warn = 'Enter a whole number from 1 to 1,000.'
  }
  const share = parseAmount(form.tfsa_short_hold_share_warn)
  if (share === null || share < 1 || share > 100) errors.tfsa_short_hold_share_warn = 'Enter a share from 1 to 100%.'
  if (Object.keys(errors).length > 0) return { errors }
  return {
    input: {
      usd_fx_fee_pct: usd,
      crypto_fee_pct: crypto,
      tfsa_round_trips_warn: trips as number,
      tfsa_short_hold_share_warn: (share as number) / 100,
    },
  }
}
```

- [ ] **Step 4: Run it**

Run: `npm test -- lib/forms.test.ts`
Expected: `Tests  4 passed (4)`.

- [ ] **Step 5: Write the failing browser tests**

`web/e2e/watchlist-settings.spec.ts`:

```ts
import { expect, test } from '@playwright/test'
import { daysAgo, resetData, seedCloses, seedFx, seedSymbols, sql } from './db'

test.beforeEach(resetData)

test.describe('watchlist', () => {
  test('adds a TSX stock without its suffix, refuses a duplicate, and removes it', async ({ page }) => {
    await seedSymbols([{ symbol: 'SHOP.TO', market: 'TSX', name: 'Shopify Inc.' }])
    await seedCloses('SHOP.TO', 'stock', 'CAD', [daysAgo(1)], 141.25, 0)
    await page.goto('/watchlist')
    await expect(page.getByRole('heading', { name: 'Watching 0' })).toBeVisible()

    await page.getByLabel('Symbol', { exact: true }).fill('shop')
    await page.getByLabel('Type').selectOption('TSX stock')
    await page.getByRole('button', { name: 'Add' }).click()
    await expect(page.getByRole('status')).toHaveText('SHOP.TO added to the watchlist')
    await expect(page.getByRole('heading', { name: 'Watching 1' })).toBeVisible()
    await expect(page.locator('.watch-row')).toContainText('Shopify Inc.')
    await expect(page.locator('.watch-row')).toContainText('C$141.25')
    await expect(page.getByLabel('Symbol', { exact: true })).toHaveValue('')

    await page.getByLabel('Symbol', { exact: true }).fill('SHOP.TO')
    await page.getByRole('button', { name: 'Add' }).click()
    await expect(page.getByText('SHOP.TO is already on the watchlist.')).toBeVisible()

    await page.getByRole('button', { name: 'Remove SHOP.TO' }).click()
    await expect(page.getByRole('status')).toHaveText('SHOP.TO removed from the watchlist')
    await expect(page.getByRole('heading', { name: 'Watching 0' })).toBeVisible()
    expect(await sql`select 1 from watchlist`).toHaveLength(0)
  })

  test('shows a coin in CAD and an unlisted stock with a note', async ({ page }) => {
    await seedFx([daysAgo(1)], 1.4)
    await seedCloses('SOL', 'crypto', 'USD', [daysAgo(1)], 200, 0)
    await page.goto('/watchlist')
    await page.getByLabel('Symbol', { exact: true }).fill('sol')
    await page.getByLabel('Type').selectOption('Crypto')
    await page.getByRole('button', { name: 'Add' }).click()
    await expect(page.locator('.watch-row').filter({ hasText: 'SOL' })).toContainText('C$280.00')

    await page.getByLabel('Symbol', { exact: true }).fill('VFV')
    await page.getByLabel('Type').selectOption('TSX stock')
    await page.getByRole('button', { name: 'Add' }).click()
    await expect(page.getByRole('status')).toHaveText("VFV.TO added. It isn't in the stock lists; the next run will try Yahoo.")
    await expect(page.locator('.watch-row').filter({ hasText: 'VFV.TO' })).toContainText('next run')
  })
})

test.describe('settings', () => {
  test('saves costs and guidelines, and names a value out of range', async ({ page }) => {
    await page.goto('/settings')
    const fee = page.getByLabel(/USD conversion fee/)
    await expect(fee).toHaveValue('1.5')
    await fee.fill('12')
    await page.getByRole('button', { name: 'Save' }).click()
    await expect(page.getByText('Enter a fee from 0 to 10%.')).toBeVisible()

    await fee.fill('1.25')
    await page.getByLabel(/Short holds/).fill('40')
    await page.getByRole('button', { name: 'Save' }).click()
    await expect(page.getByRole('status')).toHaveText('Settings saved: they apply from the next run')
    const [row] = await sql`select usd_fx_fee_pct::float as fee, tfsa_short_hold_share_warn::float as share from settings`
    expect(row).toEqual({ fee: 1.25, share: 0.4 })

    await page.reload()
    await expect(page.getByLabel(/USD conversion fee/)).toHaveValue('1.25')
    await expect(page.getByLabel(/Short holds/)).toHaveValue('40')
  })

  test('the theme choice sticks on this device', async ({ page }) => {
    await page.goto('/settings')
    await page.getByRole('tab', { name: 'Dark' }).click()
    await expect(page.locator('html')).toHaveClass(/\bdark\b/)
    await page.reload()
    await expect(page.getByRole('tab', { name: 'Dark' })).toHaveAttribute('aria-selected', 'true')
    await page.getByRole('tab', { name: 'Light' }).click()
    await expect(page.locator('html')).not.toHaveClass(/\bdark\b/)
  })
})
```

`web/e2e/navigation.spec.ts`:

```ts
import { expect, test } from '@playwright/test'
import { resetData } from './db'

test.beforeEach(resetData)

test('the sidebar reaches every page and marks the current one', async ({ page }) => {
  await page.goto('/')
  const sidebar = page.getByRole('complementary', { name: 'Main' })
  await expect(sidebar.getByRole('link', { name: 'Portfolio' })).toHaveAttribute('aria-current', 'page')
  await sidebar.getByRole('link', { name: 'Watchlist' }).click()
  await expect(page.getByRole('heading', { name: 'Watchlist' })).toBeVisible()
  await expect(sidebar.getByRole('link', { name: 'Watchlist' })).toHaveAttribute('aria-current', 'page')
  await sidebar.getByRole('link', { name: 'Settings' }).click()
  await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible()
})

test.describe('on a phone', () => {
  test.use({ viewport: { width: 390, height: 844 } })

  test('pages are tabs at the bottom, and Settings is under More', async ({ page }) => {
    await page.goto('/')
    const tabs = page.getByRole('navigation', { name: 'Main' }).last()
    await expect(tabs.getByRole('link', { name: 'Portfolio' })).toHaveAttribute('aria-current', 'page')
    await tabs.getByRole('link', { name: 'Watchlist' }).click()
    await expect(page.getByRole('heading', { name: 'Watchlist' })).toBeVisible()
    await tabs.getByRole('button', { name: 'More' }).click()
    await page.getByRole('dialog', { name: 'More' }).getByRole('link', { name: 'Settings' }).click()
    await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible()
    await expect(tabs.getByRole('button', { name: 'More' })).toHaveAttribute('aria-current', 'page')
  })

  test('no page is wider than the screen', async ({ page }) => {
    for (const [path, heading] of [['/', 'My Portfolio'], ['/watchlist', 'Watchlist'], ['/settings', 'Settings']]) {
      await page.goto(path)
      await expect(page.getByRole('heading', { name: heading, level: 1 })).toBeVisible()
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
      expect(overflow, path).toBeLessThanOrEqual(0)
    }
  })
})
```

- [ ] **Step 6: Run them and see them fail**

Run: `npm run e2e -- e2e/watchlist-settings.spec.ts e2e/navigation.spec.ts`
Expected: `7 failed` and `1 passed` (the setup). `/watchlist` and `/settings` are 404s.

- [ ] **Step 7: Write the watchlist loader**

`web/lib/data/watchlist.ts`:

```ts
import 'server-only'
import type { AssetType } from '../portfolio/types'
import type { Supabase } from '../supabase/server'
import { must } from './fetch'
import type { AssetRef } from './portfolio'

export interface WatchItem extends AssetRef {
  addedAt: string
}

/** The watchlist, newest first. */
export async function loadWatchlist(supabase: Supabase): Promise<WatchItem[]> {
  const rows = must(
    await supabase.from('watchlist').select('symbol, asset_type, added_at').order('added_at', { ascending: false }),
  ) as { symbol: string; asset_type: AssetType; added_at: string }[]
  return rows.map((r) => ({ symbol: r.symbol, assetType: r.asset_type, addedAt: r.added_at }))
}
```

- [ ] **Step 8: Write the Watchlist page**

`web/app/(app)/watchlist/actions.ts`:

```ts
'use server'

import { revalidatePath } from 'next/cache'
import { isListedStock } from '@/lib/data/symbols'
import type { AssetType } from '@/lib/portfolio/types'
import { createClient } from '@/lib/supabase/server'
import type { FormState } from '@/lib/trade-form'
import { parseWatch } from '@/lib/watch-form'

/** Watch a symbol. The next run prices it first and collects its data (spec §7.2). */
export async function addWatch(_: FormState, form: FormData): Promise<FormState> {
  const parsed = parseWatch(String(form.get('symbol') ?? ''), String(form.get('type') ?? ''))
  if ('error' in parsed) return { errors: { symbol: parsed.error }, at: Date.now() }
  const supabase = await createClient()
  const { error } = await supabase.from('watchlist').insert({ symbol: parsed.symbol, asset_type: parsed.assetType })
  if (error?.code === '23505') return { errors: { symbol: `${parsed.symbol} is already on the watchlist.` }, at: Date.now() }
  if (error) return { message: `It wasn't added: ${error.message}`, at: Date.now() }
  revalidatePath('/watchlist')
  const listed = parsed.assetType === 'crypto' || (await isListedStock(supabase, parsed.symbol))
  return {
    ok: true,
    message: listed
      ? `${parsed.symbol} added to the watchlist`
      : `${parsed.symbol} added. It isn't in the stock lists; the next run will try Yahoo.`,
    at: Date.now(),
  }
}

export async function removeWatch(symbol: string, assetType: AssetType): Promise<FormState> {
  const supabase = await createClient()
  const { error } = await supabase.from('watchlist').delete().eq('symbol', symbol).eq('asset_type', assetType)
  if (error) return { message: `It wasn't removed: ${error.message}`, at: Date.now() }
  revalidatePath('/watchlist')
  return { ok: true, message: `${symbol} removed from the watchlist`, at: Date.now() }
}
```

`web/components/watchlist/Watchlist.tsx`:

```tsx
'use client'

import { Plus, X } from 'lucide-react'
import { useActionState, useEffect, useState, useTransition } from 'react'
import { addWatch, removeWatch } from '@/app/(app)/watchlist/actions'
import { useToast } from '@/components/Toast'
import type { AssetType } from '@/lib/portfolio/types'
import type { FormState } from '@/lib/trade-form'
import { WATCH_TYPES, type WatchType } from '@/lib/watch-form'

export interface WatchRow {
  symbol: string
  assetType: AssetType
  name: string | null
  type: 'US' | 'TSX' | 'Crypto'
  price: string | null
}

export function AddWatch() {
  const toast = useToast()
  const [state, action, pending] = useActionState<FormState, FormData>(addWatch, {})
  const [symbol, setSymbol] = useState('')
  const [type, setType] = useState<WatchType>('us')
  const [editedAt, setEditedAt] = useState(0)
  const error = state.errors?.symbol && editedAt <= (state.at ?? 0) ? state.errors.symbol : undefined

  useEffect(() => {
    if (state.ok && state.message) toast(state.message)
  }, [state, toast])
  // A saved symbol clears the box for the next one.
  const [savedAt, setSavedAt] = useState(0)
  if (state.ok && state.at && state.at !== savedAt) {
    setSavedAt(state.at)
    setSymbol('')
  }

  return (
    <form action={action} className="add-row" noValidate>
      <label className={`field ${error ? 'invalid' : ''}`}>
        <span className="sr-only">Symbol</span>
        <input
          className="input num-input"
          name="symbol"
          placeholder="Symbol, e.g. NVDA, SHOP.TO or ETH"
          autoCapitalize="characters"
          value={symbol}
          onChange={(e) => {
            setSymbol(e.target.value)
            setEditedAt(Date.now())
          }}
        />
        <span className="error">{error}</span>
      </label>
      <label className="field">
        <span className="sr-only">Type</span>
        <select className="select" name="type" value={type} onChange={(e) => setType(e.target.value as WatchType)}>
          {WATCH_TYPES.map((t) => (
            <option key={t.value} value={t.value}>
              {t.label}
            </option>
          ))}
        </select>
      </label>
      <button type="submit" className="btn btn-primary" disabled={pending}>
        <Plus />
        {pending ? 'Adding…' : 'Add'}
      </button>
      {state.message && !state.ok && <span className="sub loss">{state.message}</span>}
    </form>
  )
}

export function WatchList({ rows }: { rows: WatchRow[] }) {
  const toast = useToast()
  const [removing, setRemoving] = useState<string | null>(null)
  const [, startTransition] = useTransition()

  const remove = (row: WatchRow) => {
    setRemoving(row.symbol)
    startTransition(async () => {
      const result = await removeWatch(row.symbol, row.assetType)
      setRemoving(null)
      if (result.message) toast(result.message)
    })
  }

  if (rows.length === 0) {
    return (
      <p className="sub" style={{ margin: 0 }}>
        Nothing yet. Add a US stock, a TSX stock or a coin above.
      </p>
    )
  }
  return (
    <>
      <div className="watch-head plain label">
        <span>Symbol</span>
        <span>Type</span>
        <span style={{ textAlign: 'right' }}>Price</span>
        <span />
      </div>
      <div>
        {rows.map((row) => (
          <div
            key={`${row.assetType}:${row.symbol}`}
            className={`watch-row plain ${removing === row.symbol ? 'removing' : ''}`}
          >
            <span className="w-sym">
              <span className="sym">{row.symbol}</span>
              {row.name && (
                <>
                  <br />
                  <span className="sub">{row.name}</span>
                </>
              )}
            </span>
            <span className="w-type sub">{row.type}</span>
            <span className="w-price num" style={{ textAlign: 'right' }}>
              {row.price ?? <span className="sub">next run</span>}
            </span>
            <button
              type="button"
              className="icon-btn w-x"
              aria-label={`Remove ${row.symbol}`}
              disabled={removing !== null}
              onClick={() => remove(row)}
            >
              <X />
            </button>
          </div>
        ))}
      </div>
    </>
  )
}
```

`web/app/(app)/watchlist/page.tsx`:

```tsx
import { Info } from 'lucide-react'
import type { Metadata } from 'next'
import { AddWatch, WatchList, type WatchRow } from '@/components/watchlist/Watchlist'
import { ownerClient } from '@/lib/auth'
import { loadCloses, loadFx } from '@/lib/data/portfolio'
import { loadNames } from '@/lib/data/symbols'
import { loadWatchlist } from '@/lib/data/watchlist'
import { addDays, todayInToronto } from '@/lib/dates'
import { fmtPrice } from '@/lib/format'
import { assetKey } from '@/lib/portfolio/types'
import { marketOf } from '@/lib/symbols'

export const metadata: Metadata = { title: 'Watchlist' }

/** Watchlist (spec §9): add or remove US stocks, TSX stocks and coins. Verdicts come with the model. */
export default async function WatchlistPage() {
  const supabase = await ownerClient()
  if (!supabase) return null // the layout is showing the not-the-owner notice
  const items = await loadWatchlist(supabase)
  const [names, prices, fx] = await Promise.all([
    loadNames(supabase, items.filter((i) => i.assetType === 'stock').map((i) => i.symbol)),
    // Watched symbols get a close every run, so two weeks back always reaches the latest one.
    loadCloses(supabase, items, addDays(todayInToronto(), -14)),
    loadFx(supabase),
  ])
  const rate = fx.latest()?.usdCad ?? null

  const rows: WatchRow[] = items.map((item) => {
    const close = prices.latest(assetKey(item.assetType, item.symbol))
    let price: string | null = null
    if (close && item.assetType === 'stock') price = fmtPrice(close.close, close.currency)
    // Coinbase closes are in USD; coins are shown in CAD like their holdings.
    else if (close && rate !== null) price = fmtPrice(close.currency === 'USD' ? close.close * rate : close.close, 'CAD')
    return {
      symbol: item.symbol,
      assetType: item.assetType,
      name: names.get(item.symbol) ?? null,
      type: item.assetType === 'crypto' ? 'Crypto' : marketOf(item.symbol),
      price,
    }
  })

  return (
    <main className="page">
      <div className="enter">
        <h1>Watchlist</h1>
        <p className="sub">Any US stock, TSX stock or coin. Watched symbols are priced first and get a verdict every run.</p>
      </div>
      <section className="card card-pad enter" aria-labelledby="add-h">
        <h2 id="add-h" style={{ marginBottom: 12 }}>
          Add a symbol
        </h2>
        <AddWatch />
      </section>
      <section className="card card-pad enter" aria-labelledby="list-h">
        <div className="section-head">
          <h2 id="list-h">Watching {rows.length}</h2>
        </div>
        <div className="banner info" style={{ marginBottom: 12 }}>
          <Info />
          <div>Verdicts appear once the model runs. Until then, watched symbols are still priced first and collected.</div>
        </div>
        <WatchList rows={rows} />
      </section>
    </main>
  )
}
```

- [ ] **Step 9: Write the Settings page**

`web/app/(app)/settings/actions.ts`:

```ts
'use server'

import { revalidatePath } from 'next/cache'
import { parseSettings } from '@/lib/settings-form'
import { createClient } from '@/lib/supabase/server'
import { formFields, type FormState } from '@/lib/trade-form'

/** The owner may update the one settings row, never add or remove it (spec §8). */
export async function saveSettings(_: FormState, form: FormData): Promise<FormState> {
  const parsed = parseSettings(formFields(form))
  if ('errors' in parsed) return { errors: parsed.errors, at: Date.now() }
  const supabase = await createClient()
  const { error, count } = await supabase
    .from('settings')
    .update({ ...parsed.input, updated_at: new Date().toISOString() }, { count: 'exact' })
    .eq('id', 1)
  if (error) return { message: `Settings weren't saved: ${error.message}`, at: Date.now() }
  if (count === 0) return { message: "Settings weren't saved: only the owner can change them.", at: Date.now() }
  revalidatePath('/settings')
  revalidatePath('/')
  return { ok: true, message: 'Settings saved: they apply from the next run', at: Date.now() }
}
```

`web/components/settings/SettingsForms.tsx`:

```tsx
'use client'

import { useActionState, useEffect, useState, useSyncExternalStore } from 'react'
import { saveSettings } from '@/app/(app)/settings/actions'
import { Tabs } from '@/components/Tabs'
import { useToast } from '@/components/Toast'
import { applyTheme, savedTheme, type ThemeChoice } from '@/lib/theme'
import type { FormState } from '@/lib/trade-form'

export interface SettingsValues {
  usd_fx_fee_pct: string
  crypto_fee_pct: string
  tfsa_round_trips_warn: string
  tfsa_short_hold_share_warn: string
}

const FIELDS: { name: keyof SettingsValues; title: string; help: string; unit: string; mode: 'decimal' | 'numeric'; section: 'costs' | 'tfsa' }[] = [
  {
    name: 'usd_fx_fee_pct',
    title: 'USD conversion fee',
    help: 'Charged on each US buy and each US sell. A US pick must beat twice this, plus the spread.',
    unit: '% each way',
    mode: 'decimal',
    section: 'costs',
  },
  {
    name: 'crypto_fee_pct',
    title: 'Crypto spread',
    help: "Wealthsimple's crypto spread, paid on the way in and out.",
    unit: '% each way',
    mode: 'decimal',
    section: 'costs',
  },
  {
    name: 'tfsa_round_trips_warn',
    title: 'Round trips a year',
    help: 'Warn as TFSA buy-and-sell round trips in the last 12 months approach this.',
    unit: 'a year',
    mode: 'numeric',
    section: 'tfsa',
  },
  {
    name: 'tfsa_short_hold_share_warn',
    title: 'Short holds',
    help: 'Warn when this share of holds over 12 months lasted under 30 days.',
    unit: '% of holds',
    mode: 'numeric',
    section: 'tfsa',
  },
]

export function CostsForm({ initial, changed }: { initial: SettingsValues; changed: string }) {
  const toast = useToast()
  const [state, action, pending] = useActionState<FormState, FormData>(saveSettings, {})
  const [values, setValues] = useState(initial)
  const [edited, setEdited] = useState<Record<string, number>>({})
  useEffect(() => {
    if (state.ok && state.message) toast(state.message)
  }, [state, toast])
  const error = (name: string) =>
    state.errors?.[name] && !((edited[name] ?? 0) > (state.at ?? 0)) ? state.errors[name] : undefined

  const field = (f: (typeof FIELDS)[number]) => (
    <label key={f.name} className={`setting field ${error(f.name) ? 'invalid' : ''}`}>
      <span>
        <strong>{f.title}</strong>
        <p>{f.help}</p>
      </span>
      <span className="with-unit">
        <input
          className="input num-input"
          name={f.name}
          inputMode={f.mode}
          value={values[f.name]}
          onChange={(e) => {
            setValues((v) => ({ ...v, [f.name]: e.target.value }))
            setEdited((m) => ({ ...m, [f.name]: Date.now() }))
          }}
        />
        <span className="unit">{f.unit}</span>
        <span className="error">{error(f.name)}</span>
      </span>
    </label>
  )

  return (
    <form className="card card-pad enter" action={action} noValidate>
      <h2 style={{ marginBottom: 4 }}>Costs</h2>
      {FIELDS.filter((f) => f.section === 'costs').map(field)}
      <h2 style={{ margin: '18px 0 4px' }}>TFSA trading guideline</h2>
      <p className="sub" style={{ margin: '0 0 4px' }}>
        The CRA can tax frequent TFSA trading as business income. There&apos;s no official cutoff; these only set when
        warnings appear. Not tax advice.
      </p>
      {FIELDS.filter((f) => f.section === 'tfsa').map(field)}
      {state.message && !state.ok && <p className="sub loss">{state.message}</p>}
      <div className="flex items-center justify-between gap-3 flex-wrap" style={{ marginTop: 14 }}>
        <span className="sub">Last changed {changed}</span>
        <button type="submit" className="btn btn-primary" disabled={pending}>
          {pending ? 'Saving…' : 'Save'}
        </button>
      </div>
    </form>
  )
}

const THEME_TABS = [
  { value: 'system', label: 'System' },
  { value: 'light', label: 'Light' },
  { value: 'dark', label: 'Dark' },
] as const

const noop = () => () => {}

/** Saved on this device only (localStorage), as in the mockups. */
export function ThemeTabs() {
  const stored = useSyncExternalStore(noop, savedTheme, () => 'system' as ThemeChoice)
  const [choice, setChoice] = useState<ThemeChoice | null>(null)
  return (
    <Tabs
      items={THEME_TABS}
      value={choice ?? stored}
      label="Theme"
      onChange={(value) => {
        setChoice(value)
        applyTheme(value)
      }}
    />
  )
}
```

`web/app/(app)/settings/page.tsx`:

```tsx
import { LogOut } from 'lucide-react'
import type { Metadata } from 'next'
import { CostsForm, ThemeTabs } from '@/components/settings/SettingsForms'
import { ownerClient } from '@/lib/auth'
import { loadSettings } from '@/lib/data/settings'
import { longDay } from '@/lib/dates'
import { signOut } from '../actions'

export const metadata: Metadata = { title: 'Settings' }

/** Settings (spec §9): the USD conversion fee, the crypto spread and the TFSA guideline. */
export default async function SettingsPage() {
  const supabase = await ownerClient()
  if (!supabase) return null // the layout is showing the not-the-owner notice
  const settings = await loadSettings(supabase)
  const changed = longDay(
    new Intl.DateTimeFormat('en-CA', { timeZone: 'America/Toronto' }).format(new Date(settings.updated_at)),
  )
  return (
    <main className="page">
      <div className="enter">
        <h1>Settings</h1>
        <p className="sub">Costs and guidelines the recommendations use. Changes apply from the next run.</p>
      </div>
      <div className="settings">
        <CostsForm
          changed={changed}
          initial={{
            usd_fx_fee_pct: String(settings.usd_fx_fee_pct),
            crypto_fee_pct: String(settings.crypto_fee_pct),
            tfsa_round_trips_warn: String(settings.tfsa_round_trips_warn),
            tfsa_short_hold_share_warn: String(Math.round(settings.tfsa_short_hold_share_warn * 100)),
          }}
        />
        <section className="card card-pad enter">
          <h2 style={{ marginBottom: 4 }}>Appearance</h2>
          <div className="setting" style={{ borderBottom: 0 }}>
            <span>
              <strong>Theme</strong>
              <p>Saved on this device only.</p>
            </span>
            <ThemeTabs />
          </div>
        </section>
        <section className="card card-pad enter">
          <h2 style={{ marginBottom: 4 }}>Account</h2>
          <div className="setting" style={{ borderBottom: 0 }}>
            <span>
              <strong>Signed in as the owner</strong>
              <p>This dashboard has one account. Sign-ups are turned off.</p>
            </span>
            <form action={signOut}>
              <button type="submit" className="btn btn-secondary">
                <LogOut />
                Sign out
              </button>
            </form>
          </div>
        </section>
      </div>
    </main>
  )
}
```

- [ ] **Step 10: Run the tests**

Run: `npm test`
Expected: `Test Files  12 passed (12)`, `Tests  80 passed (80)`.

Run: `npm run e2e`
Expected: `25 passed`. Then `npm run lint` and `npm run typecheck` are clean.

- [ ] **Step 11: Commit**

```bash
git add web/lib web/app web/components web/e2e
git commit -m "feat: add the watchlist and settings pages"
```

End the message with your `Co-Authored-By:` trailer.

---

### Task 8: CI, the deploy steps and the docs

**Files:**
- Modify: `.github/workflows/ci.yml`, `README.md`, `docs/superpowers/specs/2026-10-09-stock-advisor-design.md`, `docs/superpowers/deferred.md`
- Create: `web/README.md`

- [ ] **Step 1: Add the dashboard's CI job**

In `.github/workflows/ci.yml`, add this job after the `pipeline` job (it runs the browser tests against the stack, as locally):

```yaml
  web:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: web
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 24
          cache: npm
          cache-dependency-path: web/package-lock.json
      - run: npm ci
      - run: npm run lint
      - run: npm run typecheck
      - run: npm test
      # The browser tests run against the local Supabase stack, with every migration applied.
      - run: npm run db:start
      - run: npx playwright install --with-deps chromium
      - run: npm run e2e
```

- [ ] **Step 2: Write the dashboard's README**

`web/README.md`:

````markdown
# Dashboard (web/)

The owner's dashboard (spec §9): Next.js App Router on Vercel, reading Supabase as the signed-in
owner. Row-level security decides what it can see and write; the dashboard writes only the
watchlist, buys, sells and the settings row.

Plan 5b built the frame, sign-in, My Portfolio (values, returns against XIU.TO and SPY in CAD,
warnings, buys and sells), the watchlist and settings. Picks, Ticker detail, Track record, Source
health and file import come in Plan 5c; actions, ranges and verdicts once the model exists (Plan 4).

## Run it locally

Needs Node 24 and Docker Desktop.

```bash
cd web
npm install
npm run db:start      # the local Supabase stack: Postgres, Auth and the REST API, with every migration applied
npm run db:status     # its API URL and publishable key
cp .env.example .env.local   # then paste the publishable key
npm run e2e           # once: creates the local owner, owner@example.com / local-owner-password
npm run dev           # http://localhost:3000
```

The stack keeps its data between `db:stop` and `db:start`. After a new migration in
`supabase/migrations/`, run `npm run db:reset` to rebuild the local database (it wipes it). The
local stack is only for development and tests: the hosted database is migrated with
`python -m advisor.store.migrate` (see the root README).

## Tests

```bash
npm run lint
npm run typecheck
npm test              # unit tests (Vitest): lib/**/*.test.ts, the portfolio maths and form checks
npm run e2e           # browser tests (Playwright) against the local stack and a production build
```

The browser tests need the stack running (`npm run db:start`). They truncate the owner's tables
on the **local** stack between tests (`e2e/db.ts` refuses any other database) and create two
users there: the owner and a second account that must see no data. On Windows they use the
installed Microsoft Edge; elsewhere run `npx playwright install chromium` once.

## Deploy (Vercel, free tier)

1. Import the repository in Vercel and set **Root Directory** to `web`.
2. Add two environment variables from the Supabase project (Project Settings → API Keys and
   Data API): `SUPABASE_URL` (the project URL) and `SUPABASE_PUBLISHABLE_KEY` (the publishable
   key). Neither is sent to the browser; both are safe to expose anyway, because row-level
   security only lets the owner read or write.
3. In Supabase, keep sign-ups off (Authentication → Sign In / Providers → Email: "Allow new users
   to sign up" off) and the owner's id in `app_config`, as in the root README's deployment steps.
4. Deploy, then sign in with the owner's email and password.
````

- [ ] **Step 3: Update the root README**

1. In `## Layout`, replace the `pipeline/` and `supabase/migrations/` lines with:

```markdown
- `pipeline/` — Python 3.12 data pipeline (uv)
- `web/` — the owner's dashboard: Next.js on Vercel (see `web/README.md`)
- `supabase/migrations/` — Postgres schema, row-level security, and roles (append-only)
- `supabase/config.toml` — the local Supabase stack the dashboard's tests run against
```

2. In `## Local development`, add this paragraph before the one starting `Why a container:`:

```markdown
The dashboard runs on the host with Node 24; `web/README.md` has its local stack and tests.
```

3. In `## Deployment (free tiers)`, add step 7 after step 6:

```markdown
7. **Vercel**: import the repository with **Root Directory** `web`, and add `SUPABASE_URL` and
   `SUPABASE_PUBLISHABLE_KEY` from the Supabase project (Project Settings → API Keys and Data API).
   Sign in with the owner from step 3. `web/README.md` has the details.
```

- [ ] **Step 4: Update the spec**

In `docs/superpowers/specs/2026-10-09-stock-advisor-design.md`:

1. In §9, replace the **Charts** bullet with these two bullets:

```markdown
- **Charts:** the Ledger mockups' own SVG line chart, ported as a component and drawn at the container's width (owner decision 2026-10-16: no chart library). Price history comes from `daily_closes` and `fx_rates` (§8). The ticker page adds the forecast cone.
- **Data access:** pages and forms talk to Supabase only from the server (server components and server actions), as the signed-in owner, so `SUPABASE_URL` and `SUPABASE_PUBLISHABLE_KEY` never reach the browser. Row-level security is what limits reads and writes.
```

2. In §9, append this sentence to the **Visual design** bullet:

```markdown
The approved design is "Ledger": `.superdesign/design_iterations/` (`theme_1.css`, `dashboard_1.css`, `dashboard_1.js` and one HTML page per screen).
```

3. In §11, replace the **Dashboard** bullet with:

```markdown
- **Dashboard:**
  - Vitest unit tests for the portfolio maths (average cost, CAD values, time-weighted returns against the benchmarks, TFSA-frequency and superficial-loss warnings), chart geometry and form checks;
  - Playwright tests against the local Supabase stack (`supabase/config.toml`) for login, a signed-in account that isn't the owner, adding a buy, a sell and a watchlist item, settings, every page rendering with seed data, and the stale and paper banners.
```

4. In §12, replace the `web/` line of the layout block with these two lines (the second goes after `supabase/migrations/`):

```text
  web/                      Next.js dashboard: app/, components/, lib/ (unit-tested), e2e/ (Playwright)
  supabase/config.toml      the local Supabase stack the dashboard's tests run against
```

- [ ] **Step 5: Update deferred.md**

In `docs/superpowers/deferred.md`, under `## Plans 4 and 5: recommendations and dashboard`:

1. Add this sub-bullet as the last one under **Price history (Plan 5a)**, then add the five new bullets below it:

```markdown
  - Plan 5b values holdings and charts portfolio returns from them; the ticker chart (Plan 5c) reads them too.

- **Dashboard before the model (Plan 5b):** the portfolio shows values, P/L, returns, warnings and a breakdown by market and account.
  - Waiting for `holding_actions` and picks (Plan 4): action cards, likely ranges, trailing stops, exit dates, risk levels, the breakdown by risk and the max-size warning. The holdings table places its cells by class, so these columns can be added.
  - Waiting for data no plan collects yet: the sector warning (`symbols.sector` is never filled; a fundamentals plan should fill it) and the note on US dividend payers in a TFSA.
  - The status bar's Paper badges are static until picks are graded live (Plan 4). The missed-slot notice and the next run's time need the schedule in TypeScript (Plan 5c).
  - Plan 5c: Picks, Ticker detail, Track record, Source health, file import, and the watchlist's verdict columns.
- **Portfolio returns (Plan 5b):** time-weighted. A day's buys count from the start of that day and its sells at the close, so a buy at the close dilutes that day's return slightly; counting buys at the close instead would let a large buy into a small position show a huge return. Trades on days without a close count on the next trading day, and an asset without a close is valued at cost.
- **Coin values (Plan 5b):** from Coinbase's USD closes at the Bank of Canada rate, the same source as the chart, not CoinGecko's CAD quote in `features_live`.
- **Unlisted stocks (Plan 5b):** a held stock Yahoo can't price leaves every run degraded, so the buy form asks for confirmation when a stock isn't in the US or TSX lists (ETFs aren't). The watchlist accepts them with a note.
```

2. Replace the last sentence of **Source credits** (`Put a sources footer on the dashboard.`) with:

```markdown
The dashboard footer credits Yahoo Finance, Coinbase and the Bank of Canada (Plan 5b); add each source when a page first shows its data.
```

3. Delete the bullet `- **`settings.updated_at`** has no trigger. The Settings page must set it, or add a trigger.`: the Settings page sets it.

- [ ] **Step 6: Run everything**

Run from `web/`: `npm run lint`, `npm run typecheck`, `npm test`, then `npm run e2e`
Expected: lint and typecheck clean, `Tests  80 passed (80)`, `25 passed`.

- [ ] **Step 7: Commit**

```bash
git add .github/workflows/ci.yml web/README.md README.md docs/superpowers/specs/2026-10-09-stock-advisor-design.md docs/superpowers/deferred.md
git commit -m "docs: deploy and test the dashboard, and record Plan 5b's decisions"
```

End the message with your `Co-Authored-By:` trailer.

---

## After this plan

- **CI** has no remote to run on yet. The `web` job runs, for the first time, when the repo is pushed to GitHub. Its steps are the ones run locally in this plan, on Ubuntu with Playwright's Chromium instead of Edge.
- **Deployment (the owner):**
  - In Vercel, import the repo with Root Directory `web`.
  - Add `SUPABASE_URL` and `SUPABASE_PUBLISHABLE_KEY` from the hosted project.
  - Sign in as the owner.
  - No migration is needed; Plan 5a's `0006` already holds the price history.
- **Next: Plan 5c.** Picks, Ticker detail (price chart with cone, news, sources), Track record, Source health, file import, the missed-slot notice, and the next run's time.
