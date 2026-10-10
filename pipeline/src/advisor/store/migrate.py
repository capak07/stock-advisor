"""Apply pending SQL migrations in name order, recording each one in schema_migrations.

Owner-only (never the pipeline's connection string):
    ADMIN_DATABASE_URL=... scripts/in-docker.sh uv run python -m advisor.store.migrate
Add --baseline 0002_rls.sql once if 0001/0002 were pasted into Supabase by hand.
"""

import argparse
import os
import sys
from pathlib import Path

import psycopg

from advisor.store.db import MIGRATIONS_DIR, connect

BOOTSTRAP = """
create table if not exists public.schema_migrations (
  name text primary key,
  applied_at timestamptz not null default now()
);
alter table public.schema_migrations enable row level security;
"""


def applied_migrations(conn: psycopg.Connection) -> set[str]:
    conn.execute(BOOTSTRAP)
    return {row["name"] for row in conn.execute("select name from public.schema_migrations")}


def migrate(
    conn: psycopg.Connection, directory: Path = MIGRATIONS_DIR, *, baseline: str | None = None
) -> list[str]:
    """Apply every *.sql file not yet recorded, each in its own transaction; return those run.

    `baseline` records files up to and including that name as applied without running them,
    for a database that was migrated by hand before tracking existed.
    """
    done = applied_migrations(conn)
    paths = sorted(directory.glob("*.sql"))
    if baseline is not None and baseline not in {path.name for path in paths}:
        raise ValueError(f"unknown baseline migration {baseline!r}")
    executed: list[str] = []
    for path in paths:
        if path.name in done:
            continue
        with conn.transaction():
            if baseline is None or path.name > baseline:
                conn.execute(path.read_text(encoding="utf-8"))
                executed.append(path.name)
            conn.execute("insert into public.schema_migrations (name) values (%s)", (path.name,))
    return executed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="advisor.store.migrate")
    parser.add_argument("--baseline", help="record migrations up to this file as already applied")
    args = parser.parse_args(argv)
    url = os.environ.get("ADMIN_DATABASE_URL")
    if not url:
        print("ADMIN_DATABASE_URL is not set (use an admin connection, never DATABASE_URL)",
              file=sys.stderr)
        return 2
    with connect(url) as conn:
        executed = migrate(conn, baseline=args.baseline)
    print("applied: " + (", ".join(executed) if executed else "nothing (up to date)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
