# Cursor task: Plan 6a, round 3 (weekly follows the accepted config; the workflow and docs)

**Start from Claude's branch `plan-6a-core`.** It holds your round 1, merged, plus Tasks 1, 2, 4 and 7. It's checked out in Claude's worktree, so branch from it without switching to it: `git switch -c plan-6a-cursor-2 plan-6a-core`.

## What to build

Read `docs/superpowers/plans/2026-10-28-plan-6a-evaluation-harness.md`: the header, **Global Constraints**, **Review Focus**, and **only Tasks 8 and 9**. Build them exactly as written, in that order, one commit each, with the commit messages the plan gives.

**What already exists that these tasks use:**
- **`advisor.model.variants`:**
  - `ModelConfig.from_json(d)` raises `ValueError` with a message naming the cause, e.g. `"factors arrives with Plan 6c"`;
  - `BASELINE` and `.name` (`"baseline"`);
  - `.to_json()`;
  - `run_variant(data, config, train_config)`;
  - `fit_variant(data, wf, config, train_config)`.
- **`advisor.store.repo`:** `active_config(conn, market: str)` returns an `AcceptedConfig` (with `.id`, `.config`) or `None`. `start_benchmark_run(conn, now, git_sha)` and `accept_config(conn, market, config, reason, run_id, now)` are there for the tests.
- **`advisor.model.weekly`:** its old `_clean` is now the public `json_safe`. Use `json_safe`.
- **The benchmark CLI** is `python -m advisor.benchmark.job --data DIR --out DIR`. It writes `benchmark-report.md` and `benchmark-report.json` into `--out`.

**For Task 8:**
- `config_for(conn, market)` takes the `Market` and passes `str(market)` to `repo.active_config`.
- The fallback reason embeds the `ValueError`'s message as `({error})`, so the third test finds "Plan 6c" in it.

**For Task 9:**
- Copy `train.yml`'s build step exactly: its `env` and the pinned `astral-sh/setup-uv` hash.
- The test path `Path(__file__).parents[3]` is the repo root from `pipeline/tests/unit/`.

## Rules

- **Test-first:**
  - write each task's tests;
  - run them and see them fail;
  - then implement, and run them again.
  
  Don't change a test's assertions to make it pass. If one looks wrong, stop and say why.
- **Commands** (from `pipeline/`; Docker Desktop and `advisor-pg` running):
  - `scripts/in-docker.sh uv run pytest -q`;
  - `scripts/in-docker.sh uv run ruff check .`.
  
  Both pass before each commit.
- **Committing:**
  - run `git commit` in its own command, never with `--no-verify`;
  - skip the plan's `Co-Authored-By` line;
  - don't push, and don't merge.
- **When done,** reply with:
  - the two commit hashes;
  - the test counts;
  - anything you decided that the plan didn't say.
