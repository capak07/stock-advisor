from pathlib import Path

ROOT = Path(__file__).parents[3]
WORKFLOW = (ROOT / ".github" / "workflows" / "daytrade.yml").read_text(encoding="utf-8")
SQL = (ROOT / "supabase" / "manual" / "daytrade_dispatch_cron.sql").read_text(encoding="utf-8")


def test_dispatch_offers_morning_and_afternoon():
    assert "workflow_dispatch:" in WORKFLOW
    assert "type: choice" in WORKFLOW
    assert "- morning" in WORKFLOW
    assert "- afternoon" in WORKFLOW


def test_concurrency_queues_without_cancelling():
    assert "group: daytrade" in WORKFLOW
    assert "cancel-in-progress: false" in WORKFLOW


def test_no_schedule_trigger():
    # GitHub's crons arrive hours late; pg_cron dispatches instead
    assert "\n  schedule:" not in WORKFLOW
    assert "cron:" not in WORKFLOW


def test_timeout_and_command_line():
    assert "timeout-minutes: 330" in WORKFLOW
    assert "uv run python -m advisor.daytrade --job ${{ inputs.job }}" in WORKFLOW
    assert "DATABASE_URL: ${{ secrets.DATABASE_URL }}" in WORKFLOW
    assert "uv sync --locked --no-dev" in WORKFLOW


def test_sql_schedules_both_dst_times_for_both_jobs():
    assert "'daytrade-morning', '35 13,14 * * 1-5'" in SQL
    assert "public.dispatch_daytrade('morning')" in SQL
    assert "'daytrade-afternoon', '35 16,17 * * 1-5'" in SQL
    assert "public.dispatch_daytrade('afternoon')" in SQL


def test_sql_function_is_locked_down_and_validates_job():
    assert "dispatch_daytrade(job text)" in SQL
    assert "security definer set search_path = ''" in SQL
    assert "github_dispatch_token" in SQL
    assert "revoke all on function public.dispatch_daytrade(text) from public, anon, authenticated" in SQL
    assert "'morning', 'afternoon'" in SQL
    assert "raise exception" in SQL
    assert "jsonb_build_object('ref', 'main', 'inputs', jsonb_build_object('job', job))" in SQL
