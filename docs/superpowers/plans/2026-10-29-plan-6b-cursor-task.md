# Cursor task: Plan 6b, Tasks 1, 4 and 5

**Branch from `main`:** `git switch -c plan-6b-cursor`. Read `docs/superpowers/plans/2026-10-29-plan-6b-crypto-model.md`: the header, **Global Constraints**, **Review Focus**, and **only Tasks 1, 4 and 5**.

**Order:**
1. **Task 1 now.** Commit it, then tell the owner "Task 1 done: <hash>".
2. **Task 4 waits** for Claude's Tasks 2 and 3, on branch `plan-6b-core`. The owner will say when. Then run `git merge plan-6b-core`, do Task 4, then Task 5.

**Don't touch** `model/crypto.py`, `model/weekly.py`, `model/backtest.py`, `benchmark/*` or `training/build.py`'s stock steps. Those are Claude's.

## Rules

- **Test-first:** write the tests, see them fail, implement, see them pass. Never weaken an assertion; if one looks wrong, stop and say why.
- **From `pipeline/`:** `scripts/in-docker.sh uv run pytest -q` and `scripts/in-docker.sh uv run ruff check .` pass before each commit.
- **Committing:**
  - run `git commit` in its own command, never with `--no-verify`;
  - don't add a `Co-Authored-By` line;
  - don't push, and don't merge into `main`.
- **When done,** reply with the commit hashes, the test counts, and anything the plan didn't say.
