# Cursor task: Plan 6j, Tasks 2 and 3

**Branch:** `git switch -c plan-6j-cursor plan-6j-claude`. This starts from Claude's branch, which holds the plan. Read `docs/superpowers/plans/2026-11-07-plan-6j-sparse-picks.md`: the **Contracts**, and **only Tasks 2 and 3**.

**Don't touch** anything under `pipeline/` or `supabase/`.

**Leave the line-ending-only local changes alone.** Use `git add <path>` for your own files only.

## Rules

- **Test-first:** write the named tests, see them fail, implement, then see them pass. Never weaken an assertion. If one looks wrong, stop and say why.
- **Wording:** use the plan's exact track-record sentence.
- **From `web/`:** `npx vitest run`, `npx tsc --noEmit` and `npx eslint lib components` pass before every commit. If the `.bin` shims are missing, call the packages' entry points, as you did last time.
- **Committing:**
  - one commit per task, with the plan's message;
  - `git commit` in its own command, never with `--no-verify`;
  - don't add a `Co-Authored-By` line;
  - don't push, and don't merge.
- **When done,** reply with:
  - the two commit hashes;
  - the test counts;
  - anything you decided that the plan didn't say.
