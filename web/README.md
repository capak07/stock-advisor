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

## Fix a mistaken trade

The dashboard adds buys and sells but doesn't edit or delete them yet (Plan 5c adds a list of
trades with Delete). Until then, in the Supabase dashboard, open Table Editor → `lots` (buys) or
`sells`, find the row by symbol and date, and edit or delete it. The next page load recomputes
values, returns and warnings.

An old USD row from before spec rev 2 can't be edited until it has an `fx_rate_cad`. Fill one
in, or delete the row and add the trade again.

## Deploy (Vercel, free tier)

1. Import the repository in Vercel and set **Root Directory** to `web`.
2. Add two environment variables from the Supabase project (Project Settings → API Keys and
   Data API): `SUPABASE_URL` (the project URL) and `SUPABASE_PUBLISHABLE_KEY` (the publishable
   key). Neither is sent to the browser; both are safe to expose anyway, because row-level
   security only lets the owner read or write.
3. In Supabase, keep sign-ups off (Authentication → Sign In / Providers → Email: "Allow new users
   to sign up" off) and the owner's id in `app_config`, as in the root README's deployment steps.
4. Deploy, then sign in with the owner's email and password.
