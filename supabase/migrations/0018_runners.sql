-- Runners: a display-only list of US stocks under $5 that start to run. A weekly backtest freezes the
-- rule (runner_rules) and reports it (runner_backtests); each evening the pipeline stores the day's
-- signals and tracks each one to its target, stop or hold-by day (runner_signals).
create table runner_rules (
  version int primary key check (version >= 1),
  settings jsonb not null,
  chosen_at timestamptz not null default now(),
  backtest_id bigint,
  live boolean not null default false
);

create unique index runner_rules_one_live on runner_rules (live) where live;

create table runner_backtests (
  id bigint generated always as identity primary key,
  ran_at timestamptz not null default now(),
  data_from date not null,
  data_to date not null,
  cutoff date not null,            -- signals before it chose the rule; from it on, they confirm it
  variants_tried int not null,
  rule_version int,                -- the frozen version this run reports; null before one exists
  frozen jsonb,                    -- {settings, older, newer}
  pick jsonb not null,             -- {name, settings, older, newer, note}
  split_suspect int not null default 0
);

create table runner_signals (
  id bigint generated always as identity primary key,
  signal_day date not null,
  symbol text not null,
  name text,
  rule_version int not null,       -- 0 = the starting values, before a backtest froze a rule
  change_pct numeric not null,
  volume_x numeric not null,
  dollar_volume numeric not null,
  close_pos numeric not null,
  signal_close numeric not null,
  signal_low numeric not null,
  spread_pct numeric not null,
  warnings jsonb not null default '[]',
  warnings_checked boolean not null default false,
  status text not null default 'waiting'
    check (status in ('waiting', 'open', 'skipped', 'target', 'stop', 'held')),
  skip_reason text,
  entry_day date,
  entry numeric,
  stop numeric not null,           -- from D's close until the entry fills, then from the open
  target numeric not null,
  hold_by date not null,
  cost_r numeric not null,
  last_day date,
  last_close numeric,
  exit_day date,
  exit_price numeric,
  gross_r numeric,
  net_r numeric,
  created_at timestamptz not null default now(),
  unique (signal_day, symbol)
);

alter table runner_rules enable row level security;
alter table runner_backtests enable row level security;
alter table runner_signals enable row level security;
create policy owner_read on runner_rules for select to authenticated using ((select public.is_owner()));
create policy owner_read on runner_backtests for select to authenticated using ((select public.is_owner()));
create policy owner_read on runner_signals for select to authenticated using ((select public.is_owner()));
create policy pipeline_write on runner_rules for all to pipeline_rw using (true) with check (true);
create policy pipeline_write on runner_backtests for all to pipeline_rw using (true) with check (true);
create policy pipeline_write on runner_signals for all to pipeline_rw using (true) with check (true);
grant select, insert, update, delete on runner_rules, runner_backtests, runner_signals to pipeline_rw;

-- The new settings column inherits the table's owner_update and pipeline_read policies.
alter table settings
  add column runners_max_loss_cad numeric not null default 50
    check (runners_max_loss_cad > 0 and runners_max_loss_cad <= 100000);
