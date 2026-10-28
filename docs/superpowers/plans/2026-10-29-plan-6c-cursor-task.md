# Cursor task: Plan 6c, all tasks

**Branch from `main`:** `git switch -c plan-6c-cursor`. Read all of `docs/superpowers/plans/2026-10-29-plan-6c-factors.md`, and the spec it names.

**Do Tasks 1–5 in order, one commit each.** Task 1 (the TSX note) is independent: do it first.

## Rules

- **Test-first:** write the tests, see them fail, implement, see them pass. Never weaken an assertion; if one looks wrong, stop and say why.
- **The point-in-time (perturbation) tests are the heart of this plan.** For each one, also break the code on purpose once (for example, let the beta window include day t), see the test fail, and restore. Report each such check.
- **Before each commit,** these pass:
  - from `pipeline/`: `scripts/in-docker.sh uv run pytest -q` and `scripts/in-docker.sh uv run ruff check .`;
  - for Task 1, also `npm test` and `npx playwright test` in `web/`.
  
  Never run two suites at once.
- **Committing:**
  - run `git commit` in its own command, never with `--no-verify`;
  - don't add a `Co-Authored-By` line;
  - don't push, and don't merge.
- **When done,** reply with:
  - the commit hashes;
  - the test counts;
  - each break-and-restore check;
  - anything you decided that the plan didn't say.
