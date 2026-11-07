# Plan 6j: Sparse, Honestly Labelled Picks — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Let the benchmark find sparse rank rules: top 1 or 2, with q50 clearing costs by a margin. The research of 2026-11-06 found rules of that kind that pass every hard limit on TSX. Every pick then shows its model's backtest track record against the benchmark, so a pick that only rises with the market doesn't read as one that beats it.

**Spec:** `docs/superpowers/specs/2026-10-28-prediction-upgrade-design.md` §11 and its 2026-11-07 addendum.

**Who builds what:**
- **Claude:** Task 1, the pipeline (done on branch `plan-6j-claude`).
- **Cursor:** Tasks 2–3, the web side. The task file is `2026-11-07-plan-6j-cursor-task.md`.

## Contracts

- **The policy JSON:** `metrics.config.policy.min_edge` is a number from 0 up to 1, or absent (meaning 0). A pick qualifies only if `q50 > cost + min_edge`, in both P and rank mode.
- **The backtest track record:** the active model's `metrics.backtest.all` is `{picks: int, mean_net_pct: number | null, hit_rate_net: number | null, beat_rate: number | null, mean_p: number | null}`. That is the picks backtest over the model's outer folds, after costs. `beat_rate` is the share of picks that beat the market's benchmark.

## Task 1 (Claude): the pipeline

- **`Policy.min_edge`:** default 0, and stored only when set.
- **Where the margin applies:** `choose`, the picks backtest and the search's book.
- **The policy search grid:**
  - `top_n` ∈ (None, 1, 2, 3, 5, 10);
  - `min_edge` ∈ (0, 0.02), in stage 1.
- **The search's P-accuracy limit** no longer applies to rank rules, matching the live picks gate in rank mode.
- **Commit:** `feat: the benchmark tries sparse, margin-clearing rank rules`

## Task 2 (Cursor): Invest honours `min_edge`

- **`web/lib/invest/allocate.ts`:**
  - `InvestInput.minEdgeByMarket?: Partial<Record<Market, number>>`; a missing market means 0.
  - A qualifying row needs `q50 > cost + minEdge`, for the candidate's market, in P and rank mode alike.
  - The filler rule (`FILL_P_MIN`) is unchanged.
- **`web/lib/data/invest.ts`:** read each market's `min_edge` next to `top_n`, the same way `topNByMarket` is read.
- **Tests,** test-first, in `allocate.test.ts`:
  - `it('with minEdge, a qualifying stock must clear its costs by the margin')`: a TSX stock with q50 0.015 and cost about 0.002, with `minEdgeByMarket = { TSX: 0.02 }`, doesn't qualify. With q50 0.03, it does.
  - `it('without minEdge, behaves as today')`.
- **Commit:** `feat: Invest requires the accepted policy's margin over costs`

## Task 3 (Cursor): every pick shows its model's track record

- **`web/lib/data/picks.ts`:** for each pick's market, read the active stock model's `metrics.backtest.all` (`models.kind` `stock_us` / `stock_tsx`, `active = true`). Add `trackRecord: { picks: number; meanNetPct: number; beatRate: number } | null` to the pick view. It is null when the record is missing, `picks` is 0, or a number is null. Put the mapping in a pure, testable function in `web/lib/data/pick-row.ts`.
- **`web/components/picks/PickCard.tsx`:** when `trackRecord` is set, add one line under the pick's facts:

  `Backtest: {picks} past picks netted {meanNetPct, signed, 1 decimal}% each after costs and beat {benchmark} {beatRate as a whole %} of the time.`

  For example: `Backtest: 648 past picks netted +1.7% each after costs and beat XIU.TO 47% of the time.` Show it on every pick, P or rank.
- **Tests,** test-first:
  - `it('shows the model's backtest track record against the benchmark')`;
  - `it('shows no track record line when there is none')`;
  - mapping tests in the pick-row tests: zero picks, or a null number, gives null.
- **Commit:** `feat: each pick shows its model's backtest record against the benchmark`
