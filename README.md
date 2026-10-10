# Stock Advisor

Personal decision-support tool: twice each trading day it gathers data from free sources,
forecasts likely ranges for US stocks and watchlist crypto, and suggests buys, hold times, and
risk levels — and grades every suggestion against reality. **Not financial advice.**

Design: `docs/superpowers/specs/2026-10-09-stock-advisor-design.md`
Plans: `docs/superpowers/plans/`

## Layout

- `pipeline/` — Python 3.12 data pipeline (uv)
- `supabase/migrations/` — Postgres schema, row-level security, and roles (append-only)
- `.github/workflows/` — `ci.yml` (tests on push), `run.yml` (scheduled pipeline runs),
  `health.yml` (daily live check of every data source)

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
5. **Alpaca**: create a free account and generate API keys (paper-trading keys work for market
   data).
6. **GitHub** (private repo): Settings → Secrets and variables → Actions. Add `DATABASE_URL`
   (the pipeline login from step 4), `ALPACA_KEY_ID`, `ALPACA_SECRET_KEY`.
7. Actions → `health` → Run workflow, then `run` → Run workflow → `pre_open`.

## Manual run

From `pipeline/`, with secrets in a git-ignored `pipeline/.env.local`
(`DATABASE_URL=...`, `ALPACA_KEY_ID=...`, `ALPACA_SECRET_KEY=...`):

```bash
set -a; . ./.env.local; set +a
scripts/in-docker.sh uv run python -m advisor.health                       # check every source
scripts/in-docker.sh uv run python -m advisor.run --force-kind pre_open    # one pipeline run
```
