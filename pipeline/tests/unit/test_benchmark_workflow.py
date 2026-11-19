import re
from pathlib import Path

WORKFLOW = Path(__file__).parents[3] / ".github" / "workflows" / "benchmark.yml"
TRAIN = WORKFLOW.parent / "train.yml"
HISTORY = WORKFLOW.parent / "history.yml"
CACHE_OPTION = '--history-cache "$RUNNER_TEMP/history-cache"'


def test_the_benchmark_runs_on_the_first_sunday_only_or_on_demand():
    text = WORKFLOW.read_text()
    (cron,) = re.findall(r'cron: "([^"]+)"', text)
    _, _, day_of_month, _, day_of_week = cron.split()
    # GitHub ORs a restricted day-of-month with a restricted day-of-week: restrict only the weekday
    assert day_of_month == "*" and day_of_week == "0"
    assert "date -u +%-d" in text and "workflow_dispatch" in text
    assert text.count("steps.due.outputs.run == 'true'") >= 6  # the history cache restore is gated too
    assert "ADMIN_DATABASE_URL" not in text


def test_the_workflows_have_time_for_the_extra_benchmark_rows():
    assert "timeout-minutes: 360" in WORKFLOW.read_text()
    assert "timeout-minutes: 180" in TRAIN.read_text()
    assert "timeout-minutes: 180" in HISTORY.read_text()


def test_the_history_workflow_downloads_weekly_and_saves_the_cache_even_on_failure():
    text = HISTORY.read_text()
    assert 'cron: "0 2 * * 6"' in text and "workflow_dispatch" in text
    assert "--history-only" in text and CACHE_OPTION in text
    assert "actions/cache/restore@v4" in text
    assert "key: history-${{ github.run_id }}" in text and "restore-keys: history-" in text
    assert re.search(r"uses: actions/cache/save@v4\n\s+if: always\(\)", text)
    assert text.count("path: ${{ runner.temp }}/history-cache") == 2  # restore and save: the same path
    assert "SEC_USER_AGENT: ${{ secrets.SEC_USER_AGENT }}" in text
    assert "cancel-in-progress: false" in text and "contents: read" in text


def test_benchmark_and_train_only_restore_the_history_cache():
    for workflow in (WORKFLOW, TRAIN):
        text = workflow.read_text()
        assert "actions/cache/restore@v4" in text, workflow.name
        assert "path: ${{ runner.temp }}/history-cache" in text, workflow.name
        assert "key: history-${{ github.run_id }}" in text and "restore-keys: history-" in text, workflow.name
        assert "--no-history-download" in text and CACHE_OPTION in text, workflow.name
        assert "actions/cache/save" not in text and "--history-only" not in text, workflow.name
    restore = re.search(r"uses: actions/cache/restore@v4\n\s+if: (.+)", WORKFLOW.read_text())
    assert restore and restore.group(1) == "steps.due.outputs.run == 'true'"  # a non-due Sunday touches no cache
