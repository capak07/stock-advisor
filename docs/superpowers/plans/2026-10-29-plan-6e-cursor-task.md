# Cursor task: Plan 6e, Tasks 1, 5, 6 and 7

**Branch from `main`:** `git switch -c plan-6e-cursor`. Read `docs/superpowers/plans/2026-10-29-plan-6e-policy-search.md`: the header, **Global Constraints**, **Review Focus**, and **only Tasks 1, 5, 6 and 7**.

**Order:**
1. **Task 1 first.** Commit it, then tell the owner "Task 1 done: <hash>". Claude builds Tasks 2–4 on top of it, in a separate worktree.
2. Then Tasks 5, 6 and 7, one commit each, with the plan's messages.

**Don't touch** `benchmark/simulate.py`, `benchmark/policy_search.py`, `benchmark/job.py` or `benchmark/accept.py`. Those are Claude's.

## Rules

- **Test-first:** write the tests, see them fail, implement, see them pass. Never weaken an assertion; if one looks wrong, stop and say why.
- **From `pipeline/`:** `scripts/in-docker.sh uv run pytest -q` and `scripts/in-docker.sh uv run ruff check .` pass before every commit.
- **Committing:**
  - run `git commit` in its own command, never with `--no-verify`;
  - don't add a `Co-Authored-By` line;
  - don't push, and don't merge.
- **When done,** reply with:
  - the four commit hashes;
  - the test counts;
  - anything you decided that the plan didn't say.
