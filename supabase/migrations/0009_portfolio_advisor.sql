-- Plan 4c: what grading needs. Picks remember the day their features were cut and the
-- benchmark's price then; holding actions remember the same, plus the horizon, reference price
-- and risk, so a later run can grade them. Graded holding actions land in holding_action_outcomes.
-- All the new columns are nullable: rows written before this have none of them.
alter table picks
  add column feature_day date,
  add column bench_ref_price numeric check (bench_ref_price > 0);

alter table holding_actions
  add column horizon_days int check (horizon_days > 0),
  add column feature_day date,
  add column ref_price numeric check (ref_price > 0),
  add column bench_ref_price numeric check (bench_ref_price > 0),
  add column risk_level text check (risk_level in ('low', 'medium', 'high', 'very_high')),
  add column max_position_pct double precision;

create table holding_action_outcomes (
  run_id bigint not null,
  account text not null,
  symbol text not null,
  asset_type text not null,
  exit_price numeric not null check (exit_price > 0),
  ret double precision not null,
  ret_net_of_fx double precision not null,
  bench_ret double precision not null,
  excess double precision not null,
  beat boolean not null,
  hit_stop boolean not null,
  graded_at timestamptz not null default now(),
  primary key (run_id, account, symbol, asset_type),
  foreign key (run_id, account, symbol, asset_type)
    references holding_actions (run_id, account, symbol, asset_type) on delete cascade
);

alter table holding_action_outcomes enable row level security;
create policy owner_read on holding_action_outcomes for select to authenticated using ((select public.is_owner()));
create policy pipeline_write on holding_action_outcomes for all to pipeline_rw using (true) with check (true);
grant select, insert, update, delete on holding_action_outcomes to pipeline_rw;
