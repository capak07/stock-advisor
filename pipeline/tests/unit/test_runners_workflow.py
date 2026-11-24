from pathlib import Path

ROOT = Path(__file__).parents[3]
WORKFLOW = (ROOT / ".github" / "workflows" / "train.yml").read_text(encoding="utf-8")


def test_the_backtest_runs_after_the_build_and_cannot_fail_the_job():
    build = WORKFLOW.index("advisor.training.build")
    step = WORKFLOW.index('uv run python -m advisor.runners.weekly --data "$RUNNER_TEMP/training"')
    assert build < step < WORKFLOW.index("advisor.model.weekly")
    head = WORKFLOW[WORKFLOW.rindex("- name:", 0, step):step]
    assert "continue-on-error: true" in head and "timeout-minutes: 15" in head
