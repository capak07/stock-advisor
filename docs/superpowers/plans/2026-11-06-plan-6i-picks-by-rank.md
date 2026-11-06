# Plan 6i: Picks by Rank — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a market's picks come from the model's ranking instead of a probability floor: the top N stocks per horizon whose median forecast clears its costs. Use it only where the benchmark shows that rule makes money after costs.

**Architecture:**
- **The policy:** `Policy` gains `top_n`. With it set, a pick qualifies by being among the market's top N by P(beat) for that horizon that day, not by P ≥ `p_buy`.
  - Ranking by P within a horizon is the same as ranking by the model's score, because the calibrator is monotone.
- **The benchmark:** the backtest simulation and the policy search learn the rule. The search's first stage adds `top_n` to its grid.
- **The picks gate:** in rank mode it judges picks on their after-cost returns, not on P's accuracy.
- **Display:** picks record how they were chosen and their place in the ranking, and the app says "Ranked #k of N" instead of quoting P as a promise.

**Tech Stack:** Python 3.12, pandas, pytest in Docker; Postgres migration; Next.js/TypeScript with vitest.

**Spec:** `docs/superpowers/specs/2026-10-28-prediction-upgrade-design.md` §11. This plan adds it.

**Who builds what:**
- **Claude:** Tasks 1–3, the pipeline and the migration.
- **Cursor:** Tasks 4–5, the web side. The task file is `2026-11-06-plan-6i-cursor-task.md`.
- Cursor's tasks read only the contracts below, so they can start in parallel.

## Global Constraints

- **Tests:** Python in Docker, `pipeline/scripts/in-docker.sh uv run pytest -q` and `... uv run ruff check .`. Web: `cd web && npx vitest run`, `npx tsc --noEmit` and `npx eslint lib components`.
- **Commits:** one per task, with `git commit` in its own command and never `--no-verify`. Don't push.
- **Nothing changes until the evidence says so:**
  - `DEFAULT_POLICY` keeps `top_n = None`, so today's rules are untouched.
  - Rank mode reaches live picks only through an accepted policy, which needs the benchmark's `full+policy` row to pass.
  - Don't lower `p_buy` or the 30-pick rule, don't set `picks_enabled` by hand, and don't write configs to the production database.
- **Exact values:**
  - `top_n` grid: `(None, 3, 5, 10)`, in the search's first stage. With `top_n` set, `p_buy` is ignored, so the search tries each `top_n` once, at the first `p_buy`.
  - The ranking: per market, per horizon, per day, by P(beat) descending, ties by symbol ascending. Only eligible, forecast stocks are ranked, and ineligible ones never enter it.
  - Rank-mode qualification: in the top `top_n`, and `q50 > cost`. The horizon rule (`rule`, `horizons`), the 10-per-style and 3-per-sector limits, and the stops are unchanged.
  - Rank-mode picks gate: at least 30 backtest picks, and a mean net return after costs > 0. The two P-accuracy checks don't apply. The model's own calibration was already checked when it was accepted.
  - The stored picks contract (migration `0011_picks_by_rank.sql`):
    - `picks.chosen_by text not null default 'p' check (chosen_by in ('p', 'rank'))`;
    - `picks.score_rank int` (1 = best), and `picks.score_of int` (stocks ranked for that horizon); both null for `'p'`.
  - The policy JSON contract: `top_n` is a key of the stored policy (`metrics.config.policy.top_n`), a positive integer or null. A stored policy without the key loads with null.

## Review Focus

1. **A policy stored before this plan must load and behave as today.** Tested in Task 1 (`test_a_policy_without_top_n_loads_as_today`).
2. **In rank mode, an ineligible stock or one without a forecast must never take a top-N place.** Tested in Task 1 (`test_only_forecast_stocks_are_ranked`).
3. **Rank mode must never quote P as the pick's promise** in the app. Tested in Task 4.
4. **Invest must use the same rule as the picks** for the same model. Tested in Task 5, against the Python rule's example.
5. **Old picks rows (`chosen_by` 'p', null ranks)** must still render as today. Tested in Task 4.

---

### Task 1 (Claude): the policy's `top_n` and the rank rule

- **`advisor/policy.py`:** `Policy.top_n: int | None = None`. It's in `_KEYS`, round-trips through `to_json`/`from_json`, and must be a positive int or None. A stored policy without the key loads with None.
- **`recommend/picks.py`:**
  - `top_by_horizon(rows: Sequence[PredictionRow], n: int) -> dict[int, dict[str, tuple[int, int]]]` gives, per horizon, symbol → (rank, of) for the top `n`.
  - `choose(..., top: Mapping[int, Mapping[str, tuple[int, int]]] | None = None)`: with `policy.top_n` set, a row qualifies by being in `top` for its horizon, with `q50 > cost`, instead of `p_beat >= p_buy`.
  - `Choice` gains `score_rank`/`score_of`, which are None for P mode.
- **Tests:**
  - `test_a_policy_without_top_n_loads_as_today`
  - `test_top_n_round_trips_and_refuses_zero`
  - `test_only_forecast_stocks_are_ranked`
  - `test_rank_mode_takes_the_top_n_that_clear_costs`
  - `test_ties_rank_by_symbol`
- **Commit:** `feat: a policy can pick the market's top N by the model's ranking instead of a P floor`

### Task 2 (Claude): the backtest, the policy search and the picks gate

- **`model/backtest.py` and `benchmark/simulate.py`:** the simulated picks use the same rule, ranking each sampled day's rows per horizon.
- **`model/backtest.py`:** `gate(metrics, calibration_pts, rank_mode=False)` follows the rank-mode rule.
- **`benchmark/policy_search.py`:** `top_n` joins `GRID` and the first stage, as described in the Global Constraints.
- **`benchmark/report.py`:** shows `top_n` in the policy line.
- **`model/weekly.py`:** gates with `rank_mode=policy.top_n is not None`.
- **Tests:**
  - `test_rank_mode_simulates_the_top_n`
  - `test_the_search_tries_each_top_n_once`
  - `test_the_rank_gate_ignores_p_accuracy_but_needs_30_profitable_picks`
- **Commit:** `feat: the benchmark searches top-N rank rules and the picks gate judges them on returns`

### Task 3 (Claude): storing how a pick was chosen

- **The migration:** `supabase/migrations/0011_picks_by_rank.sql`, as in the Global Constraints. The owner reads it through the existing RLS.
- **The recommender stage:** it computes `top_by_horizon` over the market's predictions when the policy has `top_n`, passes it to `choose`, and writes `chosen_by`, `score_rank` and `score_of`.
- **Tests:** a schema test that the columns and the check exist; `test_a_rank_pick_is_stored_with_its_place`.
- **Commit:** `feat: picks record whether they were chosen by rank, and their place`

### Task 4 (Cursor): the pick card says "Ranked #k of N"

**Contract (Consumes):** picks rows carry `chosen_by` ('p' | 'rank'), `score_rank` and `score_of` (int, or null).

- **`web/lib/data/picks.ts`:** select the three columns and add them to the pick view as `chosenBy: 'p' | 'rank'`, `scoreRank: number | null` and `scoreOf: number | null`. A missing value maps to 'p', null, null.
- **`web/components/picks/PickCard.tsx`:**
  - With `chosenBy === 'rank'`, replace the P line with `Ranked #{scoreRank} of {scoreOf} by the model`, and add the small note `Chosen by rank: its probabilities run high, so it's shown by its place in the ranking.`
  - Don't show the percentage anywhere on that card.
  - With 'p', render exactly as today.
- **Tests,** in `PickCard.test.tsx`, test-first:
  - `it('shows a rank pick by its place, not a percentage')`: the rank text is present, and there's no `%` chance.
  - `it('renders a P pick as before')`: the existing P text is unchanged.
  - A data-mapping test in the picks loader's test file: a row without the new columns maps to 'p', null, null.
- **Commit:** `feat: a rank-chosen pick shows its place in the model's ranking, not a probability`

### Task 5 (Cursor): Invest follows the same rank rule

**Contract (Consumes):** the active model's `metrics.config.policy.top_n` (positive int or null, missing = null), read where `web/lib/data/invest.ts` already reads `stopRules` from the active `models` row.

- **`web/lib/invest/allocate.ts`:** `InvestInput.topN: number | null`.
  - With `topN` set, a stock's row qualifies when it is among the top `topN` by `pBeat` for that row's horizon among all input candidates (ties by symbol ascending), and `q50 > cost`. That replaces `pBeat >= P_MIN`.
  - With `topN` null, nothing changes.
  - The filler rule (`FILL_P_MIN`) is unchanged.
- **`web/lib/data/invest.ts`:** load `topN` next to `stopRules` and pass it through. `app/(app)/invest/page.tsx` passes it if needed.
- **Tests,** in `allocate.test.ts`, test-first:
  - `it('with topN, qualifies the top N by P per horizon that clear their costs')`: 4 TSX stocks at 21 days with pBeat 0.49, 0.48, 0.47, 0.46 and q50 all above cost, plus `topN = 2`. The first two qualify, even though all P < 0.58.
  - `it('with topN, a top stock that does not clear its costs is not taken')`
  - `it('ties rank by symbol')`
  - `it('without topN, behaves as today')`
- **Commit:** `feat: Invest qualifies stocks by the model's top-N ranking when the accepted policy says so`
