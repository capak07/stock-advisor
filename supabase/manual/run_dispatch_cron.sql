-- On-time triggers for .github/workflows/run.yml (run by hand in the Supabase SQL editor; not a migration).
--
-- Why: GitHub creates this repo's scheduled runs 3.5-7 hours late (seen every weekday 2026-10-28 to
-- 2026-11-09), so the schedule guard sees them outside every window and no run happens. Here pg_cron
-- calls GitHub's workflow_dispatch API with kind=auto at each slot. kind=auto keeps the guard: the
-- run only proceeds inside a slot window, and only once per kind per ET date (runs.published).
--
-- Before running this, the owner stores a GitHub fine-grained token (this repo only,
-- permission "Actions: Read and write") in Vault, in the SQL editor, never in the repo:
--   select vault.create_secret('<token>', 'github_dispatch_token');
-- To rotate it later: select vault.update_secret(id, '<new token>') from vault.secrets where name = 'github_dispatch_token';

create extension if not exists pg_cron;
create extension if not exists pg_net;

create or replace function public.dispatch_run_workflow() returns bigint
language sql security definer set search_path = '' as $$
  select net.http_post(
    url := 'https://api.github.com/repos/capak07/stock-advisor/actions/workflows/run.yml/dispatches',
    headers := jsonb_build_object(
      'Authorization', 'Bearer ' || (select decrypted_secret from vault.decrypted_secrets where name = 'github_dispatch_token'),
      'Accept', 'application/vnd.github+json',
      'X-GitHub-Api-Version', '2022-11-28',
      'User-Agent', 'stock-advisor-scheduler'
    ),
    body := '{"ref": "main", "inputs": {"kind": "auto"}}'::jsonb
  );
$$;
revoke all on function public.dispatch_run_workflow() from public, anon, authenticated;

-- Both DST offsets for each slot (pg_cron runs in UTC); the guard picks the one that is on time.
-- 12/13 = pre-open 08:15 ET, 16/17 = early-close 12:15 ET, 19/20 = pre-close 15:15 ET.
select cron.schedule('run-dispatch', '15 12,13,16,17,19,20 * * 1-5', 'select public.dispatch_run_workflow()');

-- Check: GitHub answers 204 to a good dispatch.
--   select status_code, content, created from net._http_response order by created desc limit 5;
--   select * from cron.job_run_details order by start_time desc limit 5;
-- Remove: select cron.unschedule('run-dispatch');
