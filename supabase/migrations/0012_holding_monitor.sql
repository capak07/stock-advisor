-- Holding monitor: the pipeline stores each holding's 8-Ks, quarterly financials, earnings dates and
-- insider trades so the web app can show them; the owner sets price alerts the pipeline marks as hit.
create table filings (
  accession text primary key,
  symbol text not null,
  form text not null,
  filed_at timestamptz not null,
  report_date date,
  items text[] not null default '{}',
  url text not null,
  -- when the pipeline first stored the row (kept on rewrite): the web's "what's new" cut-off, since a
  -- filing can be learned about runs after its filed_at (a daily source, a failed fetch)
  added_at timestamptz not null default now()
);
create index filings_by_symbol on filings (symbol, filed_at desc);

create table financial_quarters (
  symbol text not null,
  period_end date not null,
  period_start date not null,
  fiscal_year int,
  fiscal_period text,
  revenue numeric,
  gross_profit numeric,
  operating_income numeric,
  net_income numeric,
  eps_diluted numeric,
  form text not null,
  filed date not null,
  accession text not null,
  derived boolean not null default false,
  primary key (symbol, period_end)
);

create table earnings_reports (
  symbol text not null,
  report_date date not null,
  report_at timestamptz not null,
  eps_estimate numeric,
  eps_actual numeric,
  surprise_pct numeric,
  primary key (symbol, report_date)
);

create table insider_trades (
  accession text not null,
  line int not null,
  symbol text not null,
  filed_at timestamptz not null,
  trade_date date not null,
  owner text not null,
  role text not null,
  code text not null check (code in ('P', 'S')),
  shares numeric not null,
  price numeric,
  value numeric,
  planned boolean not null,
  added_at timestamptz not null default now(), -- when first stored, as for filings
  primary key (accession, line)
);
create index insider_trades_by_symbol on insider_trades (symbol, trade_date desc);

create table price_alerts (
  id bigint generated always as identity primary key,
  symbol text not null,
  asset_type text not null check (asset_type in ('stock', 'crypto')),
  direction text not null check (direction in ('above', 'below')),
  level numeric not null check (level > 0),
  note text check (char_length(note) <= 200),
  created_at timestamptz not null default now(),
  hit_at timestamptz,
  hit_price numeric,
  dismissed_at timestamptz
);

alter table filings enable row level security;
alter table financial_quarters enable row level security;
alter table earnings_reports enable row level security;
alter table insider_trades enable row level security;
alter table price_alerts enable row level security;

create policy owner_read on filings for select to authenticated using ((select public.is_owner()));
create policy owner_read on financial_quarters for select to authenticated using ((select public.is_owner()));
create policy owner_read on earnings_reports for select to authenticated using ((select public.is_owner()));
create policy owner_read on insider_trades for select to authenticated using ((select public.is_owner()));
create policy owner_read on price_alerts for select to authenticated using ((select public.is_owner()));

create policy pipeline_write on filings for all to pipeline_rw using (true) with check (true);
create policy pipeline_write on financial_quarters for all to pipeline_rw using (true) with check (true);
create policy pipeline_write on earnings_reports for all to pipeline_rw using (true) with check (true);
create policy pipeline_write on insider_trades for all to pipeline_rw using (true) with check (true);
grant select, insert, update, delete on filings, financial_quarters, earnings_reports, insider_trades
  to pipeline_rw;

-- The owner manages alerts; the pipeline only reads them and records the hit (column-level update).
create policy owner_insert on price_alerts for insert to authenticated with check ((select public.is_owner()));
create policy owner_update on price_alerts for update to authenticated
  using ((select public.is_owner())) with check ((select public.is_owner()));
create policy owner_delete on price_alerts for delete to authenticated using ((select public.is_owner()));
create policy pipeline_read on price_alerts for select to pipeline_rw using (true);
create policy pipeline_hit on price_alerts for update to pipeline_rw using (true) with check (true);
revoke insert, update, delete on price_alerts from pipeline_rw;
grant select on price_alerts to pipeline_rw;
grant update (hit_at, hit_price) on price_alerts to pipeline_rw;
