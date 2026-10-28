# Cursor task: Plan 6a, round 1 (metrics, storage, report)

**Work on branch `prediction-upgrade-design`.** Create your branch from it with `git switch -c plan-6a-cursor`. Claude builds Tasks 1, 2 and 4 at the same time, in a separate worktree, so **don't touch** these files:
- `pipeline/src/advisor/model/train.py`;
- `pipeline/src/advisor/model/variants.py`;
- `pipeline/src/advisor/benchmark/folds.py`;
- `pipeline/src/advisor/benchmark/accept.py`.

## What to build

Read `docs/superpowers/plans/2026-10-28-plan-6a-evaluation-harness.md`: the header, **Global Constraints**, **Review Focus**, and **only Tasks 3, 5 and 6**. Build those three tasks exactly as written, in that order, one commit each, with the commit messages the plan gives.

- **Task 3** (`pipeline/src/advisor/benchmark/metrics.py`):
  - Create `pipeline/src/advisor/benchmark/__init__.py` with the one-line docstring `"""The evaluation harness: nested walk-forward, metrics, acceptance and the benchmark report."""`.
  - Claude's Task 2 creates the same file with the same line. If it already exists when you merge, keep one.
- **Task 5** (migration `0010_benchmarks.sql`, two dataclasses in `models.py`, six functions in `repo.py`, and integration tests).
- **Task 6** (`pipeline/src/advisor/benchmark/report.py`):
  - Write the test from Step 1's bullet list.
  - Every assertion listed there must be in it.

## Rules

- **Test-first:**
  - write each task's tests;
  - run them and see them fail;
  - then implement, and run them again.
  
  Don't change a test's assertions to make it pass. If a test in the plan looks wrong, stop and say why in your report.
- **Commands** (from `pipeline/`; Docker Desktop must be running, and so must the `advisor-pg` container for integration tests):
  - `scripts/in-docker.sh uv run pytest -q`;
  - `scripts/in-docker.sh uv run ruff check .`.
- **Before each commit,** the full suite and ruff pass.
- **Committing:**
  - run `git commit` in its own command, never with `--no-verify`;
  - skip the plan's `Co-Authored-By` line: that's for Claude's commits;
  - don't push, and don't merge.
- **When done,** reply with:
  - the three commit hashes;
  - the test counts;
  - anything you decided that the plan didn't say.
