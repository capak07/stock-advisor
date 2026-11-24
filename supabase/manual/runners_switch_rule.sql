-- Switch the live runner rule to the latest backtest's pick (run by hand in the Supabase SQL editor; not a migration).
--
-- Why: the weekly backtest (advisor.runners.weekly, in train.yml) freezes rule version 1 once and after
-- that only reports; the live rule never changes on its own. When the owner decides the latest pick
-- should replace it, this stores that pick's settings as the next version and makes it the only live one.
-- The live record and the page's gate then restart for that version; signals already stored keep theirs.
-- Running it again makes another version, even when the pick has not changed.
--
-- Look first at the pick it will take:
--   select id, ran_at, pick->>'name' as pick, pick->'settings' as settings from runner_backtests order by id desc limit 1;

do $$
declare
  latest record;
begin
  select id, pick->'settings' as settings into latest from public.runner_backtests order by id desc limit 1;
  if not found then
    raise exception 'runners_switch_rule: no backtest has run yet';
  end if;
  update public.runner_rules set live = false where live;
  insert into public.runner_rules (version, settings, backtest_id, live)
    select coalesce(max(version), 0) + 1, latest.settings, latest.id, true from public.runner_rules;
end;
$$;

-- Check: select version, settings, backtest_id, chosen_at from runner_rules where live;
