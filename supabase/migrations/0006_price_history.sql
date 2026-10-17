-- Plan 5a (owner decision 2026-10-16): price history for the dashboard. The pipeline stores daily
-- closes for holdings, the watchlist, the shortlist and the two benchmarks, and the Bank of Canada's
-- USD/CAD rate, so the dashboard can chart returns and value US holdings in CAD.
-- Stock closes are Yahoo's split- and dividend-adjusted closes; crypto closes are Coinbase's, in USD.
create table daily_closes (
  symbol text not null,
  asset_type text not null check (asset_type in ('stock', 'crypto')),
  day date not null,
  close numeric not null check (close > 0),
  currency text not null check (currency in ('USD', 'CAD')),
  constraint daily_closes_symbol_format check (
    (asset_type = 'stock' and (symbol ~ '^[A-Z]{1,5}(\.[A-Z])?$'
                               or symbol ~ '^[A-Z]{1,5}(-[A-Z]{1,2})?\.TO$'))
    or (asset_type = 'crypto' and symbol ~ '^[A-Z0-9]{2,10}$')),
  primary key (symbol, asset_type, day)
);
create index daily_closes_by_day on daily_closes (day);

create table fx_rates (
  day date primary key,
  usd_cad numeric not null check (usd_cad > 0)
);

alter table daily_closes enable row level security;
alter table fx_rates enable row level security;
create policy owner_read on daily_closes for select to authenticated using ((select public.is_owner()));
create policy owner_read on fx_rates for select to authenticated using ((select public.is_owner()));
create policy pipeline_write on daily_closes for all to pipeline_rw using (true) with check (true);
create policy pipeline_write on fx_rates for all to pipeline_rw using (true) with check (true);
grant select, insert, update, delete on daily_closes, fx_rates to pipeline_rw;
