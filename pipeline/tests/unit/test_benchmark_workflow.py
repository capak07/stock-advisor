import re
from pathlib import Path

WORKFLOW = Path(__file__).parents[3] / ".github" / "workflows" / "benchmark.yml"


def test_the_benchmark_runs_on_the_first_sunday_only_or_on_demand():
    text = WORKFLOW.read_text()
    (cron,) = re.findall(r'cron: "([^"]+)"', text)
    _, _, day_of_month, _, day_of_week = cron.split()
    # GitHub ORs a restricted day-of-month with a restricted day-of-week: restrict only the weekday
    assert day_of_month == "*" and day_of_week == "0"
    assert "date -u +%-d" in text and "workflow_dispatch" in text
    assert text.count("steps.due.outputs.run == 'true'") >= 5
    assert "ADMIN_DATABASE_URL" not in text


def test_the_workflows_have_time_for_the_extra_benchmark_rows():
    workflows = WORKFLOW.parent
    assert "timeout-minutes: 360" in WORKFLOW.read_text()
    assert "timeout-minutes: 180" in (workflows / "train.yml").read_text()
