-- Plan 5c: what the dashboard's Source health page needs.
-- Each run and each daily health check writes the registry's collectors here, so the page shows
-- every source with its category, whether it's core (a core failure degrades the run), its cadence
-- and the assets and stock markets it covers. A source that leaves the registry leaves this table.
create table sources (
  name text primary key,
  category text not null
    check (category in ('prices', 'fundamentals', 'options', 'macro', 'news', 'social', 'catalysts', 'onchain')),
  core boolean not null,
  cadence text not null check (cadence in ('per_run', 'daily', 'weekly')),
  asset_types text[] not null check (asset_types <@ array['stock', 'crypto']::text[] and cardinality(asset_types) > 0),
  markets text[] not null check (markets <@ array['US', 'TSX']::text[]),  -- empty for coin-only sources
  updated_at timestamptz not null default now()
);

alter table sources enable row level security;
create policy owner_read on sources for select to authenticated using ((select public.is_owner()));
create policy pipeline_write on sources for all to pipeline_rw using (true) with check (true);
grant select, insert, update, delete on sources to pipeline_rw;

-- The Source health page reads a run's rows.
create index source_health_by_run on source_health (run_id);

-- Each source's last good answer (ok or partial), in a run or a daily check. The view reads with
-- the reader's rights, so source_health's policy applies: only the owner sees rows.
create view source_last_ok with (security_invoker = true) as
  select source, max(attempted_at) as attempted_at from source_health
  where status in ('ok', 'partial') group by source;

-- The database's size, to compare with the free tier's 500 MB; null for anyone but the owner.
create or replace function public.database_size() returns bigint
language sql stable security definer set search_path = public
as $$
  select case when public.is_owner() then pg_database_size(current_database()) end;
$$;
revoke execute on function public.database_size() from public, anon;
grant execute on function public.database_size() to authenticated;
