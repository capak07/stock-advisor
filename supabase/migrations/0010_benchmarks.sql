-- Plan 6a: benchmark runs, per-fold results and accepted configurations. Weekly training
-- reads accepted_configs; only the benchmark.yml job writes it.
create table benchmark_runs (
  id bigint generated always as identity primary key,
  started_at timestamptz not null,
  finished_at timestamptz,
  status text not null default 'running' check (status in ('running', 'success', 'failed')),
  git_sha text check (git_sha ~ '^[0-9a-f]{7,40}$'),
  report jsonb not null default '{}'::jsonb
);
create table benchmark_results (
  run_id bigint not null references benchmark_runs (id) on delete cascade,
  market text not null check (market in ('US', 'TSX', 'crypto')),
  variant text not null check (variant ~ '^[a-z+]{1,40}$'),
  fold text not null check (fold ~ '^([0-9]|pooled)$'),
  metrics jsonb not null,
  primary key (run_id, market, variant, fold)
);
create table accepted_configs (
  id bigint generated always as identity primary key,
  market text not null check (market in ('US', 'TSX', 'crypto')),
  config jsonb not null,
  reason text not null,
  accepted_at timestamptz not null,
  benchmark_run_id bigint not null references benchmark_runs (id),
  active boolean not null default false
);
create unique index accepted_configs_one_active_per_market on accepted_configs (market) where active;

alter table benchmark_runs enable row level security;
create policy owner_read on benchmark_runs for select to authenticated using ((select public.is_owner()));
create policy pipeline_write on benchmark_runs for all to pipeline_rw using (true) with check (true);
grant select, insert, update, delete on benchmark_runs to pipeline_rw;

alter table benchmark_results enable row level security;
create policy owner_read on benchmark_results for select to authenticated using ((select public.is_owner()));
create policy pipeline_write on benchmark_results for all to pipeline_rw using (true) with check (true);
grant select, insert, update, delete on benchmark_results to pipeline_rw;

alter table accepted_configs enable row level security;
create policy owner_read on accepted_configs for select to authenticated using ((select public.is_owner()));
create policy pipeline_write on accepted_configs for all to pipeline_rw using (true) with check (true);
grant select, insert, update, delete on accepted_configs to pipeline_rw;
