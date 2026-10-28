# Stock Advisor

Personal decision-support tool: twice each trading day it gathers data from free sources,
forecasts likely ranges for US and TSX stocks and watchlist crypto, and suggests buys, hold times, and
risk levels — and grades every suggestion against reality. **Not financial advice.**

Design: `docs/superpowers/specs/2026-10-09-stock-advisor-design.md`
Plans: `docs/superpowers/plans/`

## Layout

- `pipeline/` — Python 3.12 data pipeline (uv)
- `web/` — the owner's dashboard: Next.js on Vercel (see `web/README.md`)
- `supabase/migrations/` — Postgres schema, row-level security, and roles (append-only)
- `supabase/config.toml` — the local Supabase stack the dashboard's tests run against
- `.github/workflows/` — `ci.yml` (tests on push), `run.yml` (scheduled pipeline runs),
  `health.yml` (daily live check of every data source), `train.yml` (weekly training),
  `benchmark.yml` (monthly benchmark)

## Local development

```bash
# one-time
docker run -d --name advisor-pg -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=advisor_test \
  -p 54329:5432 postgres:16

# every session
docker start advisor-pg
cd pipeline
uv run ruff check .                    # lint runs on the host
scripts/in-docker.sh uv run pytest -q  # tests run in a Linux container
```

The dashboard runs on the host with Node 24; `web/README.md` has its local stack and tests.

Why a container: on this Windows machine, Application Control blocks the libpq DLLs bundled with psycopg, so anything that imports psycopg runs in Linux. `scripts/in-docker.sh` mounts the repo, keeps its own virtualenv in a Docker volume, and points tests at `advisor-pg`. CI runs on Ubuntu directly.

## Deployment (free tiers)

1. **Supabase**: create a project. Under Connect → **Session pooler**, copy the URI for the
   `postgres` user (GitHub runners need the IPv4 pooler). Percent-encode special characters in
   the password (for example `@` → `%40`). This is your **admin** URL: keep it local and never put
   it in GitHub.
2. **Schema**: from `pipeline/`, put `ADMIN_DATABASE_URL='<admin url>'` in a git-ignored
   `pipeline/.env.admin`, then run
   `set -a; . ./.env.admin; set +a; scripts/in-docker.sh uv run python -m advisor.store.migrate`.
   If you already pasted `0001`/`0002` into the SQL editor by hand, run it once with
   `--baseline 0002_rls.sql` added.
3. **Auth**: under Authentication → Sign In / Providers → Email, turn off "Allow new users to sign
   up". Add your user under Authentication → Users, then in the SQL editor run:
   `insert into app_config (id, owner_id) values (1, '<your user uuid>');`
4. **Pipeline login** (least privilege: no DDL, cannot edit your holdings). In the SQL editor:
   ```sql
   create role advisor_pipeline login password '<generate a long random password>';
   grant pipeline_rw to advisor_pipeline;
   ```
   Use a long password of letters and digits only (no URL encoding needed), and don't save that
   query as a snippet in the SQL editor.
   The pipeline's `DATABASE_URL` is the session-pooler URI with the user
   `advisor_pipeline.<project-ref>` and that password. If the pooler rejects the custom role,
   resolve that first: the `postgres` user has full DDL rights and should not run the pipeline.
5. **GitHub** (private repo): Settings → Secrets and variables → Actions. Add `DATABASE_URL`
   (the pipeline login from step 4) and `SEC_USER_AGENT`: a name plus your contact email, such
   as `stock-advisor you@example.com`. SEC requires a contact in every request; it is not an
   account or a key, and no data source needs one.
6. Actions → `health` → Run workflow, then `run` → Run workflow → `pre_open`.
7. **Vercel**: import the repository with **Root Directory** `web`, and add `SUPABASE_URL` and
   `SUPABASE_PUBLISHABLE_KEY` from the Supabase project (Project Settings → API Keys and Data API).
   Sign in with the owner from step 3. `web/README.md` has the details.

**Upgrading an existing deployment:** apply the new migrations (`python -m advisor.store.migrate`,
as in step 2: `0004` for Plan 2b, `0005` for Plan 2f, `0006` for Plan 5a, `0007` for Plan 5c) in the same window as you deploy the matching
code, between run slots. Code without the
migration, or the migration without the code, produces failed runs and emails; no data is
damaged. Until `0007` is applied, the dashboard's Ticker and Source health pages fail, and
Holdings links to Ticker pages; runs still publish, with a `sources_error` in their summary.
`0007` adds a table and a view, so run the grants in `web/README.md` (Deploy, step 3) again
after applying it. Before deploying Plan 2d's code, add the `SEC_USER_AGENT` secret (step 5); without it every run is degraded and the health job emails you daily.
`0010` for Plan 6a; apply it before the next `train.yml` or `benchmark.yml` run.

## Manual run

From `pipeline/`, with secrets in a git-ignored `pipeline/.env.local`
(`DATABASE_URL=...`, `SEC_USER_AGENT=...`):

```bash
set -a; . ./.env.local; set +a
scripts/in-docker.sh uv run python -m advisor.health                       # check every source
scripts/in-docker.sh uv run python -m advisor.run --force-kind pre_open    # one pipeline run
```

A local run scores no headline sentiment unless you add `--extra nlp` after `uv run`. That installs
CPU PyTorch and transformers (about 900 MB), and the first scored run downloads the FinBERT model
(about 440 MB) into the `advisor-hf` Docker volume. The next test run's `uv sync` removes the extra again.
