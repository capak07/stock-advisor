-- Owner-only access (spec §8). The pipeline connects as the table owner, which bypasses RLS.
-- Policies call is_owner() as (select public.is_owner()) so Postgres evaluates it once per
-- statement instead of once per row.

create or replace function public.is_owner() returns boolean
language sql stable security definer set search_path = public
as $$
  select exists (select 1 from public.app_config where id = 1 and owner_id = auth.uid());
$$;

do $$
declare
  t text;
begin
  foreach t in array array[
    'app_config', 'runs', 'source_health', 'symbols', 'features_live', 'predictions', 'picks',
    'pick_outcomes', 'watchlist', 'watchlist_verdicts', 'lots', 'sells', 'holding_actions',
    'news_items', 'models'
  ] loop
    execute format('alter table public.%I enable row level security', t);
    execute format(
      'create policy owner_read on public.%I for select to authenticated using ((select public.is_owner()))', t);
  end loop;

  foreach t in array array['watchlist', 'lots', 'sells'] loop
    execute format(
      'create policy owner_insert on public.%I for insert to authenticated with check ((select public.is_owner()))', t);
    execute format(
      'create policy owner_update on public.%I for update to authenticated using ((select public.is_owner())) with check ((select public.is_owner()))', t);
    execute format(
      'create policy owner_delete on public.%I for delete to authenticated using ((select public.is_owner()))', t);
  end loop;
end $$;
