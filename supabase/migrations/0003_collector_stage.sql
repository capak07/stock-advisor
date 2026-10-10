-- Plan 2a: partial collector results, daily health-check rows, and a least-privilege
-- pipeline role. After applying, the owner creates the login role once (see README):
--   create role advisor_pipeline login password '<long random>'; grant pipeline_rw to advisor_pipeline;

alter table source_health drop constraint source_health_status_check;
alter table source_health add constraint source_health_status_check
  check (status in ('ok', 'partial', 'stale', 'failed', 'skipped'));
alter table source_health alter column run_id drop not null;
alter table source_health
  add column context text not null default 'run' check (context in ('run', 'health'));
alter table source_health
  add constraint source_health_run_context check ((context = 'run') = (run_id is not null));

do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'pipeline_rw') then
    create role pipeline_rw nologin;
  end if;
end $$;

grant usage on schema public to pipeline_rw;
grant select, insert, update, delete on all tables in schema public to pipeline_rw;
grant usage, select on all sequences in schema public to pipeline_rw;
alter default privileges in schema public
  grant select, insert, update, delete on tables to pipeline_rw;
alter default privileges in schema public grant usage, select on sequences to pipeline_rw;
revoke insert, update, delete on lots, sells, watchlist, app_config from pipeline_rw;
do $$ begin
  if to_regclass('public.schema_migrations') is not null then
    revoke all on public.schema_migrations from pipeline_rw;
  end if;
end $$;

-- RLS still applies to pipeline_rw (it does not own the tables), so it needs explicit policies.
do $$
declare
  t text;
begin
  foreach t in array array[
    'runs', 'source_health', 'symbols', 'features_live', 'predictions', 'picks',
    'pick_outcomes', 'watchlist_verdicts', 'holding_actions', 'news_items', 'models'
  ] loop
    execute format(
      'create policy pipeline_write on public.%I for all to pipeline_rw using (true) with check (true)', t);
  end loop;
  foreach t in array array['watchlist', 'lots', 'sells', 'app_config'] loop
    execute format('create policy pipeline_read on public.%I for select to pipeline_rw using (true)', t);
  end loop;
end $$;
