# Dashboard (web/)

The owner's dashboard (spec §9): Next.js App Router on Vercel, reading Supabase as the signed-in
owner. Row-level security decides what it can see and write; the dashboard writes only the
watchlist, buys, sells and the settings row.

Plan 5b built the frame, sign-in, My Portfolio (values, returns against XIU.TO and SPY in CAD,
warnings, buys and sells), the watchlist and settings. Plan 5c added the trade list with Delete,
file import, a Ticker page for any symbol (price, the owner's position, two days of news and the
sources that cover it) and Source health. Picks, Track record, verdicts, actions and the
forecast come with the model (Plans 3 and 4).

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

Delete it under Trades on My Portfolio (the latest ten show; "Show all" lists the rest), then add
it again with the right values. Deleting a buy that a later sell needs warns first, because the
sell would then exceed what was held.

## Import a broker file

My Portfolio → Import file takes a CSV of the broker's activity (in Wealthsimple: Activity →
Export). Match each column to its meaning (the usual names are recognised), say how the file
writes dates, then review every row: buys and sells are imported, dividends and transfers are left
out, and trades already recorded are skipped, so importing the same file twice adds nothing. A
file whose sells would exceed what was held is refused whole. Stocks missing from the US and TSX
lists (ETFs) are left out unless ticked in. USD trades take the Bank of Canada rate of their day.

## Deploy (Vercel, free tier)

1. Import the repository in Vercel and set **Root Directory** to `web`.
2. Add two environment variables from the Supabase project (Project Settings → API Keys and
   Data API): `SUPABASE_URL` (the project URL) and `SUPABASE_PUBLISHABLE_KEY` (the publishable
   key). Neither is sent to the browser; both are safe to expose anyway, because row-level
   security only lets the owner read or write.
3. The dashboard reads through Supabase's Data API as the `authenticated` role. In Project
   Settings → Data API, the `public` schema must be exposed. The migrations grant `authenticated`
   nothing; Supabase projects normally grant it table privileges by default. If a page fails with
   "permission denied for table …", run this in the SQL editor:

   ```sql
   grant usage on schema public to authenticated;
   grant select on all tables in schema public to authenticated;
   grant insert, update, delete on watchlist, lots, sells to authenticated;
   grant update on settings to authenticated;
   ```

   Row-level security still limits every row to the owner. `on all tables` covers only the tables
   that exist, so run it again after a migration adds one (Plan 5c added `sources` and the
   `source_last_ok` view).
4. In Supabase, keep sign-ups off (Authentication → Sign In / Providers → Email: "Allow new users
   to sign up" off) and the owner's id in `app_config`, as in the root README's deployment steps.
5. Deploy, then sign in with the owner's email and password.
