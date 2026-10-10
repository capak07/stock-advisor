-- Stock Advisor core schema (spec §8). Applied once to Supabase via the SQL editor, and to test DBs.

create table app_config (
  id int primary key default 1 check (id = 1),
  owner_id uuid not null
);

create table runs (
  id bigint generated always as identity primary key,
  kind text not null check (kind in ('pre_open', 'pre_close', 'early_close')),
  et_date date not null,
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  status text not null default 'running'
    check (status in ('running', 'success', 'degraded', 'failed')),
  published boolean not null default false,
  sources_ok int,
  sources_total int,
  model_version text,
  summary jsonb not null default '{}'::jsonb
);
create unique index runs_one_published_per_slot on runs (kind, et_date) where published;

create table source_health (
  id bigint generated always as identity primary key,
  run_id bigint not null references runs (id) on delete cascade,
  source text not null,
  status text not null check (status in ('ok', 'stale', 'failed', 'skipped')),
  latency_ms int not null,
  records int not null,
  error text,
  consecutive_failures int not null,
  attempted_at timestamptz not null default now()
);
create index source_health_by_source on source_health (source, attempted_at desc);

create table symbols (
  symbol text not null,
  asset_type text not null check (asset_type in ('stock', 'crypto')),
  name text not null,
  exchange text not null,
  sector text,
  industry text,
  market_cap numeric,
  active boolean not null default true,
  updated_at timestamptz not null default now(),
  primary key (symbol, asset_type)
);

create table features_live (
  run_id bigint not null references runs (id) on delete cascade,
  symbol text not null,
  asset_type text not null check (asset_type in ('stock', 'crypto')),
  features jsonb not null,
  as_of timestamptz not null,
  primary key (run_id, symbol, asset_type)
);

create table predictions (
  run_id bigint not null references runs (id) on delete cascade,
  symbol text not null,
  asset_type text not null check (asset_type in ('stock', 'crypto')),
  horizon_days int not null check (horizon_days > 0),
  q10 double precision not null,
  q50 double precision not null,
  q90 double precision not null,
  p_beat double precision not null check (p_beat between 0 and 1),
  benchmark text not null,
  model_version text not null,
  primary key (run_id, symbol, asset_type, horizon_days)
);

create table picks (
  id bigint generated always as identity primary key,
  run_id bigint not null references runs (id) on delete cascade,
  symbol text not null,
  asset_type text not null default 'stock' check (asset_type in ('stock', 'crypto')),
  style text not null check (style in ('swing', 'position')),
  horizon_days int not null check (horizon_days > 0),
  exit_by date not null,
  entry_ref_price numeric not null check (entry_ref_price > 0),
  stop numeric not null check (stop > 0),
  risk_level text not null check (risk_level in ('low', 'medium', 'high', 'very_high')),
  risk_score double precision not null,
  max_position_pct double precision not null,
  rank int not null,
  top_factors jsonb not null default '[]'::jsonb,
  catalysts jsonb not null default '[]'::jsonb,
  status text not null default 'open' check (status in ('open', 'exited_early', 'graded')),
  created_at timestamptz not null default now()
);

create table pick_outcomes (
  pick_id bigint primary key references picks (id) on delete cascade,
  exit_price numeric not null check (exit_price > 0),
  exit_reason text not null,
  ret double precision not null,
  bench_ret double precision not null,
  excess double precision not null,
  beat boolean not null,
  hit_stop boolean not null,
  graded_at timestamptz not null default now()
);

create table watchlist (
  symbol text not null,
  asset_type text not null check (asset_type in ('stock', 'crypto')),
  added_at timestamptz not null default now(),
  constraint watchlist_symbol_format check (
    (asset_type = 'stock' and symbol ~ '^[A-Z]{1,5}(\.[A-Z])?$')
    or (asset_type = 'crypto' and symbol ~ '^[A-Z0-9]{2,10}$')
  ),
  primary key (symbol, asset_type)
);

create table watchlist_verdicts (
  run_id bigint not null references runs (id) on delete cascade,
  symbol text not null,
  asset_type text not null check (asset_type in ('stock', 'crypto')),
  verdict text not null check (verdict in ('buy', 'hold', 'avoid')),
  reasons jsonb not null default '[]'::jsonb,
  details jsonb not null default '{}'::jsonb,
  primary key (run_id, symbol, asset_type)
);

create table lots (
  id bigint generated always as identity primary key,
  symbol text not null,
  asset_type text not null check (asset_type in ('stock', 'crypto')),
  qty numeric not null check (qty > 0),
  price numeric not null check (price > 0),
  bought_at date not null,
  pick_id bigint references picks (id) on delete set null,
  notes text,
  created_at timestamptz not null default now(),
  constraint lots_symbol_format check (
    (asset_type = 'stock' and symbol ~ '^[A-Z]{1,5}(\.[A-Z])?$')
    or (asset_type = 'crypto' and symbol ~ '^[A-Z0-9]{2,10}$')
  )
);

create table sells (
  id bigint generated always as identity primary key,
  symbol text not null,
  asset_type text not null check (asset_type in ('stock', 'crypto')),
  qty numeric not null check (qty > 0),
  price numeric not null check (price > 0),
  sold_at date not null,
  created_at timestamptz not null default now(),
  constraint sells_symbol_format check (
    (asset_type = 'stock' and symbol ~ '^[A-Z]{1,5}(\.[A-Z])?$')
    or (asset_type = 'crypto' and symbol ~ '^[A-Z0-9]{2,10}$')
  )
);

create table holding_actions (
  run_id bigint not null references runs (id) on delete cascade,
  symbol text not null,
  asset_type text not null check (asset_type in ('stock', 'crypto')),
  action text not null check (action in ('sell', 'trim', 'add', 'hold', 'data_conflict')),
  review boolean not null default false,
  reasons jsonb not null default '[]'::jsonb,
  trailing_stop numeric check (trailing_stop > 0),
  q10 double precision,
  q50 double precision,
  q90 double precision,
  exit_by date,
  days_to_long_term int,
  primary key (run_id, symbol, asset_type)
);

create table news_items (
  id bigint generated always as identity primary key,
  symbol text not null,
  published_at timestamptz not null,
  outlet text not null,
  url text not null,
  title text not null,
  sentiment double precision,
  cluster_id text
);
create index news_items_by_symbol on news_items (symbol, published_at desc);

create table models (
  version text primary key,
  kind text not null check (kind in ('stock', 'crypto')),
  trained_at timestamptz not null,
  metrics jsonb not null default '{}'::jsonb,
  calibration_error double precision,
  active boolean not null default false
);
create unique index models_one_active_per_kind on models (kind) where active;
