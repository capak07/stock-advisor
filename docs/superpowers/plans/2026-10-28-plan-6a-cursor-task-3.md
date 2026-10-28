# Cursor task: Plan 6a, round 4 (the whole-branch review and fix pass)

**Do this after `2026-10-28-plan-6a-cursor-task-2.md` (Tasks 8 and 9), on the same branch, `plan-6a-cursor-2`.** Claude is out of usage, so you're the fresh reviewer for the whole of Plan 6a.

## Read first

- **The spec:** `docs/superpowers/specs/2026-10-28-prediction-upgrade-design.md` (§1, §6, §7, and "Decisions after the builder check").
- **The plan:** `docs/superpowers/plans/2026-10-28-plan-6a-evaluation-harness.md`, all of it, including **Review Focus**.
- **The diff under review:** `git diff prediction-upgrade-design...HEAD -- pipeline supabase .github README.md docs/superpowers/specs`.

## Claude's calls to weigh

Check each one. Say whether it stands.
1. **Task 4:** if the reference has no horizon with calibration ≤ 5, a candidate must have at least one horizon ≤ 5, rather than passing the calibration rule on nothing.
2. **Task 7:** with no active config, the job accepts the *chosen* row (`"first benchmark: today's model"` when it's the baseline), not always the baseline.
3. **Task 7:** an active config that `ModelConfig.from_json` can't parse is treated as no incumbent and replaced by the chosen row.
4. **Task 7:** `Scores.of` lives in `accept.py` and imports `summary` from `metrics.py`.

## Check deliberately

For each of these, say whether a test covers it. Where none does, add one and fix the code if it fails.

1. **The five Review Focus lines in the plan.** One example: GitHub cron ORs day-of-month with day-of-week, and the job must run only on the first Sunday or on manual dispatch.
2. **Leakage:**
   - `walk_forward(..., known_before=)` must drop test rows whose target ends at or after the cutoff;
   - inner folds must end at the outer start;
   - nothing fitted for a fold may change when that fold's test-period targets change.
3. **Fail-closed:** a NaN or missing metric never passes an acceptance rule, and never prints as `nan` or `None` in the report.
4. **The weekly fallback:**
   - no accepted config means the baseline;
   - an unparseable one means the baseline, with the reason recorded;
   - a parseable baseline config gives the same model as before Plan 6a (the same `walk_forward` and `fit_final` calls).
5. **The database:**
   - all three new tables have RLS;
   - the owner can only read them;
   - `pipeline_rw` can write them;
   - a killed run is marked failed by the next start.
6. **Secrets:** `benchmark.yml` uses only the `DATABASE_URL` and `SEC_USER_AGENT` secrets. No `ADMIN_DATABASE_URL`, and no hard-coded email.

## The fix pass

- **Real bugs** (wrong results, leakage, a crash, a check that can pass when it shouldn't):
  - fix them test-first: write the failing test, watch it fail, fix, then run the full suite;
  - one commit per fix, with a message like `fix: <what>`.
- **Style or polish** that doesn't change behaviour: don't change it. List it in your report.

## Rules

- **Commands** (from `pipeline/`; Docker Desktop and `advisor-pg` running):
  - `scripts/in-docker.sh uv run pytest -q`;
  - `scripts/in-docker.sh uv run ruff check .`.
  
  Both pass at the end.
- **Committing:**
  - run `git commit` in its own command, never with `--no-verify`;
  - don't push, and don't merge.
- **Reply with:**
  - each check above, and whether it holds;
  - each of Claude's calls, and whether it stands;
  - the fixes you made (with commit hashes and the test that proves each);
  - the polish you left alone;
  - the final test count.
