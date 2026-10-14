-- Plan 2b (spec rev 2): TSX stocks beside US stocks, Wealthsimple accounts, per-market models,
-- and owner-editable settings.

-- Every stock belongs to one market; crypto belongs to none. Rows before rev 2 are US stocks.
alter table symbols add column market text check (market in ('US', 'TSX'));
update symbols set market = 'US' where asset_type = 'stock';
alter table symbols add constraint symbols_market_matches_asset_type
  check ((asset_type = 'stock') = (market is not null));

-- Symbol formats (spec §8): US, TSX in Yahoo's form (RY.TO, RCI-B.TO, REI-UN.TO), and crypto.
do $$
declare
  t text;
begin
  foreach t in array array['watchlist', 'lots', 'sells'] loop
    execute format('alter table public.%I drop constraint %I', t, t || '_symbol_format');
    execute format($f$
      alter table public.%I add constraint %I check (
        (asset_type = 'stock' and (symbol ~ '^[A-Z]{1,5}(\.[A-Z])?$'
                                   or symbol ~ '^[A-Z]{1,5}(-[A-Z]{1,2})?\.TO$'))
        or (asset_type = 'crypto' and symbol ~ '^[A-Z0-9]{2,10}$'))$f$,
      t, t || '_symbol_format');
  end loop;
end $$;

-- Buys and sells record their account, trade currency and USD/CAD rate (spec §7.1). Rows from
-- before rev 2 are US stocks (held in the TFSA, traded in USD) or crypto (crypto account, CAD).
do $$
declare
  t text;
begin
  foreach t in array array['lots', 'sells'] loop
    execute format($f$
      alter table public.%I
        add column account text
          check (account in ('tfsa', 'rrsp', 'fhsa', 'non_registered', 'crypto')),
        add column currency text check (currency in ('CAD', 'USD')),
        add column fx_rate_cad numeric check (fx_rate_cad > 0)$f$, t);
    execute format($f$
      update public.%I set
        account = case when asset_type = 'crypto' then 'crypto' else 'tfsa' end,
        currency = case when asset_type = 'crypto' then 'CAD' else 'USD' end$f$, t);
    execute format(
      'alter table public.%I alter column account set not null, alter column currency set not null',
      t);
    execute format(
      'alter table public.%I add constraint %I check ((asset_type = ''crypto'') = (account = ''crypto''))',
      t, t || '_crypto_account');
    -- not valid: rows from before rev 2 have no rate; every new USD trade needs one.
    execute format(
      'alter table public.%I add constraint %I check (currency = ''CAD'' or fx_rate_cad is not null) not valid',
      t, t || '_usd_needs_fx_rate');
  end loop;
end $$;

-- Holding actions are per account. 'data_conflict' needed a second price source, which rev 2
-- removed. Nothing writes this table before Plan 4, so the new not-null column is safe.
alter table holding_actions
  drop column days_to_long_term,
  add column account text not null
    check (account in ('tfsa', 'rrsp', 'fhsa', 'non_registered', 'crypto')),
  add column warnings jsonb not null default '[]'::jsonb,
  drop constraint holding_actions_action_check,
  add constraint holding_actions_action_check check (action in ('sell', 'trim', 'add', 'hold')),
  add constraint holding_actions_crypto_account check ((asset_type = 'crypto') = (account = 'crypto')),
  drop constraint holding_actions_pkey,
  add primary key (run_id, account, symbol, asset_type);

-- Picks, grading and models are per market (spec §6, §8). Nothing writes these before Plan 3.
alter table picks
  add column market text check (market in ('US', 'TSX')),
  add constraint picks_market_matches_asset_type check ((asset_type = 'stock') = (market is not null));
alter table pick_outcomes add column ret_net_of_fx double precision not null;
alter table models
  drop constraint models_kind_check,
  add constraint models_kind_check check (kind in ('stock_us', 'stock_tsx', 'crypto'));

-- Owner-editable settings (spec §3, §7.5): one row the owner may update but never add or remove.
-- Kept apart from app_config so the owner never gets write access to owner_id.
create table settings (
  id int primary key default 1 check (id = 1),
  usd_fx_fee_pct numeric not null default 1.5 check (usd_fx_fee_pct between 0 and 10),
  crypto_fee_pct numeric not null default 2.0 check (crypto_fee_pct between 0 and 10),
  tfsa_round_trips_warn int not null default 24 check (tfsa_round_trips_warn > 0),
  tfsa_short_hold_share_warn numeric not null default 0.5
    check (tfsa_short_hold_share_warn > 0 and tfsa_short_hold_share_warn <= 1),
  updated_at timestamptz not null default now()
);
insert into settings (id) values (1);

alter table settings enable row level security;
create policy owner_read on settings for select to authenticated using ((select public.is_owner()));
create policy owner_update on settings for update to authenticated
  using ((select public.is_owner())) with check ((select public.is_owner()));
create policy pipeline_read on settings for select to pipeline_rw using (true);
grant select on settings to pipeline_rw;
revoke insert, update, delete on settings from pipeline_rw;
