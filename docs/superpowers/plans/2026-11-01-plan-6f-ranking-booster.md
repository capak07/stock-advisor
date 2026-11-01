# Plan 6f: The Ranking Booster — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** A `ranker` model variant that learns each stock's rank among that day's stocks. Its score ranks stocks and, once calibrated, gives P(beat). The quantile boosters, and so the ranges, stay as they are. It goes live only if the benchmark accepts it.

**Architecture:**
- `train.py` gains a ranking booster per horizon, trained on the daily percentile rank of `y_h`. When the ranker is on, it replaces the beat classifier as the source of P.
- Every prediction frame gains a `score` column (q50, or the ranker's score), and rank IC is measured on it.
- `ModelConfig` version 2 adds `ranker`. The benchmark runs it as one more ablation row, and weekly training follows an accepted ranker config.

**Tech Stack:** Python 3.12, pandas, LightGBM, pytest (in Docker).

**Spec:** `docs/superpowers/specs/2026-10-28-prediction-upgrade-design.md`, §8 (and the §1 metrics line it amends).

## Global Constraints

- **Tests in Docker,** from the repo root: `pipeline/scripts/in-docker.sh uv run pytest -q` and `pipeline/scripts/in-docker.sh uv run ruff check .`.
- **Don't run two suites at once:** they share the test database.
- **Commits:** run `git commit` in its own command, never with `--no-verify`. Messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Don't push.
- **Exact values (spec §8):** rank target = daily percentile rank of `y_h` minus 0.5. Ranking booster: objective `quantile`, `alpha` 0.5, `learning_rate` 0.03, `num_leaves` 15, 400 rounds, the other parameters as `PARAMS`.
- **Point in time:** nothing fitted or predicted for a period may change when that period's own targets change.
- **The baseline must not move:** with `ranker` off, every prediction, metric and stored file is what it is today, plus a `score` column equal to the published q50.

## Review Focus

1. **Today's accepted configs are version 1 JSON.** They must still load. A benchmark that keeps the same config must report "unchanged", not write a new accepted row. Tested in Task 2.
2. **Today's active models have no `p_source` in their meta.** Live prediction must keep using their beat classifier. Tested in Task 1.
3. **A day with one stock, ties, or NaN targets** (early crypto, data gaps): the rank target keeps NaN as NaN, averages ties, and doesn't crash. Tested in Task 1.
4. **The baseline's rank IC is unchanged,** because `score` is the published q50, after range calibration as today. Tested in Task 1.
5. **Leakage:** the rank for a training day uses only that day's targets, and all rows of a day share one end date. So a period's own targets can't change its predictions. Tested in Task 1.

---

### Task 1: The ranking booster in training

**Files:**
- Modify: `pipeline/src/advisor/model/train.py`
- Modify: `pipeline/src/advisor/model/weekly.py` (feature importance reads the booster that gives P)
- Create: `pipeline/tests/unit/test_model_ranker.py`

**Interfaces:**
- Produces:
  - `RANK_PARAMS: dict = {**PARAMS, "learning_rate": 0.03, "num_leaves": 15}`, `RANK_ROUNDS = 400`.
  - `daily_rank(rows: pd.DataFrame, target: str) -> pd.Series`: per `day`, `rank(pct=True, method="average") - 0.5` of `rows[target]`. NaN stays NaN, and the result is indexed like `rows`.
  - `walk_forward(..., ranker: bool = False) -> WalkForward`. Predictions gain `score`, set after `calibrate_ranges`: `p_raw` with the ranker, otherwise `q50`. `_metrics` takes `rank_ic` on `score`.
  - `fit_final(..., ranker: bool = False) -> FinalModel`.
  - `FinalModel.p_source: str = "beat"` (`"rank"` with the ranker). `predict` takes `p_raw` from `boosters[h][p_source]`.
  - `to_files` writes `h{h}_{part}` for `(*QUANTILE_NAMES, p_source)`, plus `"p_source"` in meta. `from_files` reads `meta.get("p_source", "beat")`.
- With the ranker, `_fit_horizon` trains a `"rank"` booster on `daily_rank` with `RANK_PARAMS` and `RANK_ROUNDS`, and no `"beat"` booster. The quantile boosters are untouched.

- [ ] **Step 1: Write the failing tests** in `test_model_ranker.py`. Use the `write_market(tmp_path, Market.TSX, stocks=20, days=1100)` market and a fast config, as in `test_model_ranges.py`.
  - `test_the_rank_target_is_each_days_percentile_rank_centred_on_zero`:
    - day 1 has `y` = 0.1, 0.3, 0.2 and NaN, which gives −1/6, 0.5, 1/6 and NaN;
    - day 2 has one row, which gives 0.5;
    - a day with a tie of two equal values gives both the average rank.
  - `test_the_baseline_score_is_its_published_median`: `walk_forward(data, FAST)` has `score == q50` on every row, and `metrics[h]["rank_ic"] == rank_ic(pred[pred.p.notna()], "q50", "y")`.
  - `test_a_ranker_walk_forward_ranks_and_calibrates_by_its_ranking_booster`:
    - with `ranker=True`, `score == p_raw`;
    - `p` is set on folds > 0;
    - the `q10`, `q50` and `q90` columns equal the baseline run's (`assert_frame_equal`);
    - `metrics[h]["rank_ic"] == rank_ic(scored, "score", "y")`.
  - `test_a_rankers_period_never_sees_its_own_targets`: set `y_5` to 5.0 on every row of the last fold's days. The ranker run's `score` and `p` for that fold stay unchanged.
  - `test_a_ranker_final_model_gives_p_from_its_ranking_booster_and_round_trips`:
    - `fit_final(..., ranker=True).p_source == "rank"`;
    - the files have `h5_rank` and no `h5_beat`;
    - `from_files(to_files(m)).predict(x)` equals `m.predict(x)`.
  - `test_a_model_saved_before_the_ranker_still_gives_p_from_its_beat_booster`: re-pack a baseline model's meta without `p_source`. `from_files(...)` has `p_source == "beat"` and predicts the same.

- [ ] **Step 2: Run them and watch them fail.**
  Run: `pipeline/scripts/in-docker.sh uv run pytest -q tests/unit/test_model_ranker.py`
  Expected: FAIL with an ImportError on `daily_rank` or `RANK_PARAMS`.

- [ ] **Step 3: Implement the Interfaces above in `train.py`.** In `weekly.py`, take feature importance from `model.boosters[h][model.p_source]`.

- [ ] **Step 4: Run the new tests and the existing model tests.**
  Run: `pipeline/scripts/in-docker.sh uv run pytest -q tests/unit/test_model_ranker.py tests/unit/test_model_train.py tests/unit/test_model_ranges.py tests/unit/test_model_weekly.py`
  Expected: all pass.

- [ ] **Step 5: Commit** `feat: a ranking booster that learns each day's stock ranks and can give P(beat)`.

### Task 2: The `ranker` variant: config, benchmark row, weekly training

**Files:**
- Modify: `pipeline/src/advisor/model/variants.py`
- Modify: `pipeline/src/advisor/benchmark/job.py`
- Modify: `pipeline/src/advisor/benchmark/report.py` (`_ABLATION_ORDER`)
- Test: `pipeline/tests/unit/test_model_variants.py`, `pipeline/tests/integration/test_benchmark_job.py`, `pipeline/tests/unit/test_benchmark_report.py`, `pipeline/tests/integration/test_model_weekly_job.py`

**Interfaces:**
- Consumes: `walk_forward(..., ranker=)`, `fit_final(..., ranker=)` and `FinalModel.p_source` from Task 1.
- Produces:
  - `CONFIG_VERSION = 2`, and `ModelConfig.ranker: bool = False`.
  - `name` joins the on parts in the order factors, garch, ranker. For example, `"ranker"` and `"factors+ranker"`.
  - `to_json` writes `{"version": 2, "factors", "garch", "ranker", "policy"}`.
  - `from_json` accepts version 1 with exactly `{version, factors, garch, policy}` (as `ranker` False), and version 2 with those keys plus `ranker`. Any other version, or any other key set, raises ValueError.
  - `run_variant` and `fit_variant` pass `ranker=config.ranker`.
  - `ABLATIONS` gains `"ranker": ModelConfig(ranker=True)` after `"factors"`. `_ABLATION_ORDER` gains `"ranker"` after `"factors"`.
  - In `job.py`, the "unchanged" check compares meaning: both sides parsed with `ModelConfig.from_json`, and a stored config that won't parse is "changed".

- [ ] **Step 1: Write the failing tests.**
  - **Variants:**
    - `ModelConfig(ranker=True).name == "ranker"`, and `ModelConfig(factors=True, ranker=True).name == "factors+ranker"`;
    - `BASELINE.to_json() == {"version": 2, "factors": False, "garch": False, "ranker": False, "policy": None}`;
    - `test_a_version_1_config_loads_with_the_ranker_off`;
    - the refusal cases become version 3, version 2 missing `ranker`, and an extra key;
    - `test_a_ranker_config_runs_the_ranking_walk_forward`: `run_variant(data, ModelConfig(ranker=True), FAST)` predictions equal `walk_forward(data, FAST, ranker=True)`.
  - **Report:** an ablation table with a `ranker` row prints it after `factors`.
  - **Benchmark job:**
    - `tsx["variants"]["ranker"]["status"] == "run"`, and the markdown has `| ranker | run |`;
    - `test_a_kept_version_1_config_is_unchanged`: seed an active accepted config as version 1 baseline JSON, and a run that chooses the baseline reports `changed` False with no new accepted row.
  - **Weekly job:** with an active accepted config `{"version": 2, "factors": False, "garch": False, "ranker": True, "policy": None}`, the trained model's stored files include `h5_rank`.

- [ ] **Step 2: Run them and watch them fail.**
  Run: `pipeline/scripts/in-docker.sh uv run pytest -q tests/unit/test_model_variants.py tests/unit/test_benchmark_report.py tests/integration/test_benchmark_job.py tests/integration/test_model_weekly_job.py`
  Expected: FAIL on the `ranker` field, the version and the missing row.

- [ ] **Step 3: Implement the Interfaces above.**

- [ ] **Step 4: Run the same command.** Expected: all pass.

- [ ] **Step 5: Run the full suite and ruff.** Expected: all pass, and ruff reports "All checks passed!".

- [ ] **Step 6: Commit** `feat: a ranker variant the benchmark judges and weekly training follows once accepted`.

### Task 3: Check the wired variant on real data

No code change; this measures the variant through the code path the benchmark will use.

- [ ] **Step 1:** On a fixed quarter of US stocks, run `run_variant` for `BASELINE` and `ModelConfig(ranker=True)` at horizons 21 and 63. Use the diagnostics scripts in `pipeline/.cache/diag/` (`half_us.py`, adapted from `experiments.py`).
- [ ] **Step 2:** Compare the pooled and per-fold `rank_ic` (on `score`), `calibration_pts`, the highest `p`, and the share of `p >= 0.58`. Expected: ranker rank IC above the baseline's in most folds, and calibration within 5 points. If not, record the result and stop before merging.
