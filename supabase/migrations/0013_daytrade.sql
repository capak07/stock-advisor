-- Day trade tab: every five minutes of the session the pipeline looks for opening-range breakouts and
-- stores the day's status and each signal it found; the owner reads them and sets two settings.
create table daytrade_days (
  day date primary key,
  status text not null check (status in ('waiting', 'scanning', 'done', 'failed', 'closed')),
  cycles int not null default 0,
  last_update timestamptz,
  scanned int,
  usable int,
  candidates int,
  error text,
  updated_at timestamptz not null default now()
);

create table daytrade_signals (
  id bigint generated always as identity primary key,
  day date not null references daytrade_days on delete cascade,
  symbol text not null,
  market text not null check (market in ('US', 'TSX')),
  name text,
  trigger_at timestamptz not null,
  entry numeric not null,
  or_high numeric not null,
  or_low numeric not null,
  stop numeric not null,
  target numeric not null,
  volume_x numeric not null,
  cost_pct numeric not null,
  cost_r numeric not null,
  replay jsonb not null,
  history jsonb not null,
  net_replay_r numeric,
  net_history_r numeric,
  eligible boolean not null,
  rank int check (rank between 1 and 3),
  headlines jsonb not null default '[]',
  status text not null default 'open' check (status in ('open', 'target', 'stop', 'flat')),
  last_price numeric,
  last_at timestamptz,
  exit_at timestamptz,
  exit_price numeric,
  gross_r numeric,
  net_r numeric,
  created_at timestamptz not null default now(),
  unique (day, symbol, market)
);
create index daytrade_signals_by_rank on daytrade_signals (day, rank);

alter table daytrade_days enable row level security;
alter table daytrade_signals enable row level security;
create policy owner_read on daytrade_days for select to authenticated using ((select public.is_owner()));
create policy owner_read on daytrade_signals for select to authenticated using ((select public.is_owner()));
create policy pipeline_write on daytrade_days for all to pipeline_rw using (true) with check (true);
create policy pipeline_write on daytrade_signals for all to pipeline_rw using (true) with check (true);
grant select, insert, update, delete on daytrade_days, daytrade_signals to pipeline_rw;

-- New settings columns inherit the table's owner_update and pipeline_read policies.
alter table settings
  add column daytrade_max_loss_cad numeric not null default 50
    check (daytrade_max_loss_cad > 0 and daytrade_max_loss_cad <= 100000),
  add column daytrade_spread_pct numeric not null default 0.10
    check (daytrade_spread_pct between 0 and 5);
