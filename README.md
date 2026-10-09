# Stock Advisor

Personal decision-support tool: twice each trading day it gathers data from free sources,
forecasts likely ranges for US stocks and watchlist crypto, and suggests buys, hold times, and
risk levels — and grades every suggestion against reality. **Not financial advice.**

Design: `docs/superpowers/specs/2026-10-09-stock-advisor-design.md`
Plans: `docs/superpowers/plans/`

## Layout

- `pipeline/` — Python 3.12 data pipeline (uv)
- `supabase/migrations/` — Postgres schema and row-level security
- `.github/workflows/` — `ci.yml` (tests on push), `run.yml` (scheduled pipeline runs)

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

1. **Supabase**: create a project. In the SQL editor, run `supabase/migrations/0001_schema.sql`
   and then `0002_rls.sql`.
2. **Auth**: under Authentication → Sign In / Providers → Email, turn off "Allow new users to sign
   up". Add your user under Authentication → Users, then run:
   `insert into app_config (id, owner_id) values (1, '<your user uuid>');`
3. **Connection string**: under Connect → **Session pooler**, copy the URI (GitHub runners need
   the IPv4 pooler) and put in your database password.
4. **Alpaca**: create a free account and generate API keys (paper-trading keys work for market
   data).
5. **GitHub** (private repo): Settings → Secrets and variables → Actions. Add `DATABASE_URL`,
   `ALPACA_KEY_ID`, `ALPACA_SECRET_KEY`.
6. Actions → `run` → Run workflow → `pre_open` to test end to end.

## Manual run

```bash
cd pipeline
DATABASE_URL=... ALPACA_KEY_ID=... ALPACA_SECRET_KEY=... \
  scripts/in-docker.sh uv run python -m advisor.run --force-kind pre_open
```
