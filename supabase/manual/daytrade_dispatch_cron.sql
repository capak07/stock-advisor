-- On-time triggers for .github/workflows/daytrade.yml (run by hand in the Supabase SQL editor; not a migration).
--
-- Why: GitHub's own schedules arrive hours late, so pg_cron calls the workflow_dispatch API at each
-- window. Same Vault token as run_dispatch_cron.sql; run that file's setup first.

create extension if not exists pg_cron;
create extension if not exists pg_net;

create or replace function public.dispatch_daytrade(job text) returns bigint
language plpgsql security definer set search_path = '' as $$
begin
  if job not in ('morning', 'afternoon') then
    raise exception 'dispatch_daytrade: job must be morning or afternoon, got %', job;
  end if;
  return net.http_post(
    url := 'https://api.github.com/repos/capak07/stock-advisor/actions/workflows/daytrade.yml/dispatches',
    headers := jsonb_build_object(
      'Authorization', 'Bearer ' || (select decrypted_secret from vault.decrypted_secrets where name = 'github_dispatch_token'),
      'Accept', 'application/vnd.github+json',
      'X-GitHub-Api-Version', '2022-11-28',
      'User-Agent', 'stock-advisor-scheduler'
    ),
    body := jsonb_build_object('ref', 'main', 'inputs', jsonb_build_object('job', job))
  );
end;
$$;
revoke all on function public.dispatch_daytrade(text) from public, anon, authenticated;

-- Both DST offsets for each window (pg_cron runs in UTC); the job's guard ignores the wrong one.
-- 13/14 = morning 09:35 ET, 16/17 = afternoon 12:35 ET.
select cron.schedule('daytrade-morning', '35 13,14 * * 1-5', $$select public.dispatch_daytrade('morning')$$);
select cron.schedule('daytrade-afternoon', '35 16,17 * * 1-5', $$select public.dispatch_daytrade('afternoon')$$);

-- Check: GitHub answers 204 to a good dispatch.
--   select status_code, content, created from net._http_response order by created desc limit 5;
--   select * from cron.job_run_details order by start_time desc limit 5;
-- Remove: select cron.unschedule('daytrade-morning'); select cron.unschedule('daytrade-afternoon');
