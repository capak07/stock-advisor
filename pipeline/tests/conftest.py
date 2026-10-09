import os
from pathlib import Path

import psycopg
import pytest
from psycopg.rows import dict_row

from advisor.store.db import apply_migrations
from dbguard import require_test_database

FIXTURES = Path(__file__).parent / "fixtures"

# Mimics the parts of Supabase that the migrations rely on: roles, auth.uid(), default grants.
SUPABASE_STUB = """
do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'anon') then create role anon nologin; end if;
  if not exists (select 1 from pg_roles where rolname = 'authenticated') then
    create role authenticated nologin;
  end if;
end $$;
create schema auth;
create function auth.uid() returns uuid language sql stable as $$
  select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid
$$;
grant usage on schema auth to anon, authenticated;
"""
SUPABASE_GRANTS = """
grant usage on schema public to anon, authenticated;
grant select, insert, update, delete on all tables in schema public to anon, authenticated;
grant usage on all sequences in schema public to anon, authenticated;
"""


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture
def db():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    require_test_database(url)
    with psycopg.connect(url, autocommit=True, row_factory=dict_row) as conn:
        conn.execute("drop schema if exists public cascade")
        conn.execute("drop schema if exists auth cascade")
        conn.execute("create schema public")
        conn.execute(SUPABASE_STUB)
        apply_migrations(conn)
        conn.execute(SUPABASE_GRANTS)
        yield conn
