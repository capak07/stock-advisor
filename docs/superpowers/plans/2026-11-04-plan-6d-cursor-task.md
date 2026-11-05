# Cursor task: Plan 6d, Tasks 1 and 6

**Branch from `main`:** `git switch -c plan-6d-cursor`. Read `docs/superpowers/plans/2026-11-04-plan-6d-garch-volatility.md`: the header, **Global Constraints**, **Decisions**, **Review Focus**, and **only Tasks 1 and 6**.

**Leave these 11 files alone.** They show as modified in `main`'s working copy, but the changes are line endings only. Don't stage, commit or revert them:
- `.github/workflows/benchmark.yml`
- `pipeline/src/advisor/model/crypto_live.py`, `factors.py`
- `pipeline/src/advisor/policy.py`
- `pipeline/src/advisor/training/crypto.py`
- `pipeline/tests/unit/test_benchmark_workflow.py`, `test_model_crypto_live.py`, `test_model_factors.py`, `test_policy.py`, `test_training_crypto.py`
- `web/components/picks/PickCard.test.tsx`

Use `git add <path>` for your own files only, never `git add -A` or `git add .`.

**Order:**
1. **Task 1 first.** Commit it, then tell the owner "Task 1 done: <hash>". Claude builds Tasks 2–5 on top of it, in a separate worktree.
2. **Then Task 6,** one commit, with the plan's message. It only reads a report dict, so it doesn't need Tasks 2–5.

**Don't touch** `model/train.py`, `model/dataset.py`, `model/crypto.py`, `model/variants.py`, `model/weekly.py`, `model/market_run.py`, `model/live.py`, `model/crypto_live.py` or `benchmark/job.py`. Those are Claude's.

## Rules

- **Test-first:** write the plan's tests, see them fail, implement, then see them pass. Never weaken an assertion or change a fixed value (the 500, 2,520 and 250 limits, the starting values, the seeds, the tolerances). If one looks wrong, stop and say why.
- **The dependency:**
  - Add `"arch==8.0.0"` to `pipeline/pyproject.toml`'s `dependencies`.
  - Update `pipeline/uv.lock` by running plain `uv lock` from `pipeline/` on the host, not through `in-docker.sh`. The Docker script runs `uv sync --locked` first, which fails until the lock matches.
  - If 8.0.0 won't resolve, stop and report the error. Don't pick another version yourself. (7.2.0 can't import with pandas 3.0.6.)
- **From `pipeline/`:** `scripts/in-docker.sh uv run pytest -q` and `scripts/in-docker.sh uv run ruff check .` must pass before every commit. Start Docker Desktop and `docker start advisor-pg` if they're down. Don't run two suites at once.
- **Committing:**
  - run `git commit` in its own command, never with `--no-verify`;
  - don't add a `Co-Authored-By` line;
  - don't push, and don't merge.
- **When done,** reply with:
  - the two commit hashes;
  - the test counts and the ruff result;
  - the fitted alpha and beta from `test_a_fit_recovers_the_parameters_it_was_simulated_with`;
  - anything you decided that the plan didn't say.
