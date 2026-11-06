# Cursor task: Plan 6i, Tasks 4 and 5

**Branch from `main`:** `git switch -c plan-6i-cursor`. Read `docs/superpowers/plans/2026-11-06-plan-6i-picks-by-rank.md`: the header, **Global Constraints** (especially the two contracts), **Review Focus**, and **only Tasks 4 and 5**.

Claude builds Tasks 1–3 (pipeline and migration) in parallel. Your tasks only read the contracts, so build and test them with fixture data. Don't wait for the migration.

**Don't touch** anything under `pipeline/` or `supabase/`. Those are Claude's.

**Leave the line-ending-only local changes alone.** Use `git add <path>` for your own files only, never `git add -A` or `git add .`.

## Rules

- **Test-first:** write the tests the plan names, see them fail, implement, then see them pass. Never weaken an assertion. If one looks wrong, stop and say why.
- **Wording:** use the plan's exact strings: `Ranked #{k} of {N} by the model`, and the note sentence. A rank-chosen pick must show no percentage.
- **From `web/`:** `npx vitest run`, `npx tsc --noEmit` and `npx eslint lib components` pass before every commit.
- **Committing:**
  - one commit per task, with the plan's message;
  - `git commit` in its own command, never with `--no-verify`;
  - don't add a `Co-Authored-By` line;
  - don't push, and don't merge.
- **When done,** reply with:
  - the two commit hashes;
  - the test counts;
  - anything you decided that the plan didn't say.
