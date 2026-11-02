# Plan 6g: More Price Features and Seed Averaging — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two benchmark-judged model additions. `extras` adds three features built from bars the pipeline already has: sector momentum, sector distance from its 52-week high, and Amihud illiquidity. `bagged` averages three seeds of every booster. Weekly training follows them only once the benchmark accepts them.

**Architecture:**
- The shared feature step computes the new features for every config. Training rows and live frames carry them, but only an `extras` config trains on them, so today's configs don't move.
- `train.py` gains a `Bag` of boosters that predicts their mean, and `walk_forward`/`fit_final` take `extra_features` and `bag`.
- `ModelConfig` version 3 adds `extras` and `bagged`. The benchmark adds three rows.

**Tech Stack:** Python 3.12, pandas, LightGBM, pytest (in Docker); Next.js/TypeScript with vitest for the explanation labels.

**Spec:** `docs/superpowers/specs/2026-10-28-prediction-upgrade-design.md`, §9.

## Global Constraints

- **Tests in Docker,** from the repo root: `pipeline/scripts/in-docker.sh uv run pytest -q` and `pipeline/scripts/in-docker.sh uv run ruff check .`. Web: `cd web && npx vitest run`, `npx tsc --noEmit`, `npx eslint lib`.
- **Don't run two suites at once:** they share the test database.
- **Commits:** run `git commit` in its own command, never with `--no-verify`. Messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Don't push.
- **Exact values (spec §9):**
  - `sector_mom_12_1` and `sector_dist_52w_high` are the sector ETF's own `mom_12_1` and `dist_52w_high`, NaN for a stock whose sector is the benchmark.
  - `amihud_20` = 1e6 × the 20-session mean of `|close / previous close − 1| / dollar volume`. A day with dollar volume ≤ 0 or NaN is left out, and the mean needs 15 sessions.
  - Coins' only extra is `amihud_20`.
  - Bag seeds are 7, 8 and 9.
  - The rows are `extras`, `ranker+extras` and `ranker+extras+bagged`, after `ranker`.
  - Timeouts: `benchmark.yml` 360 minutes, `train.yml` 180 minutes.
- **The baseline must not move:** with `extras` and `bagged` off, every prediction, metric and stored file is what it is today.
- **Point in time:** every new feature on a day reads only that day and earlier bars.

## Review Focus

1. **Today's accepted configs are version 2 JSON, and today's models have no `bag` in their meta.** Both must load and behave as before: no extras, one booster per part. Tested in Tasks 2 and 3.
2. **A live frame must carry the extras columns,** or a live `extras` model fails on its first forecast. This covers stocks (`live_features`) and coins (`forecast_coins`). The test asserts that live values equal the training rows on the same day. Tested in Task 1.
3. **A stock without a sector, or a sector ETF Yahoo missed,** gets NaN sector features, not its benchmark's numbers, and not an error. Tested in Task 1.
4. **Zero or missing volume** (halted stocks, thin coins) must not make `amihud_20` infinite. An infinite value would wreck the booster's splits. Tested in Task 1.
5. **A bagged model's explanations and importance** come from all three seeds. If only seed 7 were used, the explanation could name a factor the averaged forecast barely uses. Tested in Task 2.

---

### Task 1: The extra features, for training and live runs

**Files:**
- Modify: `pipeline/src/advisor/model/features.py` (`amihud_20` in `price_features`; new `sector_trend`; `EXTRA_FEATURES`)
- Modify: `pipeline/src/advisor/model/dataset.py` (`FeatureFrames.extras`, `MarketData.extras`, extras in the rows)
- Modify: `pipeline/src/advisor/model/live.py` (`_day_row` keeps the extras)
- Modify: `pipeline/src/advisor/model/crypto.py`, `pipeline/src/advisor/model/crypto_live.py` (`CRYPTO_EXTRAS`)
- Test: `pipeline/tests/unit/test_model_features.py`, `test_model_dataset.py`, `test_model_live.py`, `test_model_crypto.py`, `test_model_crypto_live.py`

**Interfaces:**
- Produces:
  - `features.EXTRA_FEATURES = ["sector_mom_12_1", "sector_dist_52w_high", "amihud_20"]`.
  - `price_features(...)` also returns `"amihud_20"`. `PRICE_FEATURES` is unchanged.
  - `sector_trend(features: Mapping[str, pd.DataFrame], benchmark: str, etf_of: Mapping[str, str]) -> dict[str, pd.DataFrame]`. It returns `sector_mom_12_1` and `sector_dist_52w_high`, picked per stock from the ETF columns as `relative_strength`'s `per_stock` does, with NaN where the stock's ETF is the benchmark.
  - `FeatureFrames.extras: list[str]` and `MarketData.extras: tuple[str, ...] = ()` (last field). For stocks they are `EXTRA_FEATURES`. `load_market` rows carry those columns after `names`.
  - `crypto.CRYPTO_EXTRAS = ["amihud_20"]`. `crypto_frames` returns them too, `load_crypto` rows carry them, and `MarketData.extras == ("amihud_20",)`.
  - `live_features` output has a column for every name in `frames.names + frames.extras`. `forecast_coins` builds its frame from `CRYPTO_FEATURES + CRYPTO_EXTRAS`.

- [ ] **Step 1: Write the failing tests.**
  - `test_amihud_is_the_mean_move_per_million_traded`: a 25-session series with returns alternating +2% and −2% and constant dollar volume of 4,000,000. On the last day, `amihud_20 == pytest.approx(1e6 * 0.02 / 4e6)`.
  - `test_amihud_leaves_out_days_with_no_volume_and_needs_fifteen`:
    - zero volume on 5 of the last 20 days gives a finite value, the mean of the other 15;
    - zero volume on 6 of them gives NaN;
    - no value anywhere is infinite.
  - `test_sector_trend_takes_the_sector_etfs_momentum_and_distance_from_high`: with the fixture of `test_relative_strength_...`, add `mom_12_1` and `dist_52w_high` frames where E is 0.3 and −0.05, and B is 0.1 and 0.0. Then:
    - `X` gets 0.3 and −0.05;
    - `Y` (no sector) gets NaN for both;
    - a stock whose ETF has no column gets NaN.
  - Update `test_price_features_on_a_steady_climb` to `set(f) == set(PRICE_FEATURES) | {"amihud_20"}`. Extend `test_features_on_a_day_ignore_everything_after_it` to loop over `amihud_20` too.
  - `test_training_rows_carry_the_extras_but_the_baseline_names_do_not_change`:
    - `load_market(tmp_path, Market.TSX)` has `extras == tuple(EXTRA_FEATURES)`;
    - the rows have those columns;
    - `data.features` equals `PRICE_FEATURES + RS_FEATURES`.
  - In `test_live_features_match_the_training_rows_on_the_same_day`, compare `list(data.features) + list(data.extras)` instead of `data.features`.
  - Crypto:
    - `load_crypto(...).extras == ("amihud_20",)`, and the rows have the column;
    - in `test_model_crypto_live`, a model whose `features` include `amihud_20` gets its forecast. Fake the model as the existing tests do, and assert the frame passed to `predict` has the column.

- [ ] **Step 2: Run them and watch them fail.**
  Run: `pipeline/scripts/in-docker.sh uv run pytest -q tests/unit/test_model_features.py tests/unit/test_model_dataset.py tests/unit/test_model_live.py tests/unit/test_model_crypto.py tests/unit/test_model_crypto_live.py`
  Expected: FAIL with ImportError on `EXTRA_FEATURES` or `sector_trend`, and KeyError on `amihud_20`.

- [ ] **Step 3: Implement the Interfaces above.**
  - `feature_frames` merges `sector_trend(features, benchmark, etf_of)` after `relative_strength`, and sets `extras = EXTRA_FEATURES`.
  - The `names` list it returns stays as today, so nothing that reads `names` changes.

- [ ] **Step 4: Run the same command.** Expected: all pass. Then run the existing model and run tests (`tests/unit/test_model_*.py`, `tests/integration/test_run.py`). Expected: all pass with no other change, which shows the baseline didn't move.

- [ ] **Step 5: Commit** `feat: sector momentum, sector distance from high and Amihud illiquidity, for every market's rows and live frames`.

### Task 2: Extra features and seed bags in training

**Files:**
- Modify: `pipeline/src/advisor/model/train.py`
- Test: create `pipeline/tests/unit/test_model_bagging.py`

**Interfaces:**
- Consumes: `MarketData.extras` from Task 1.
- Produces:
  - `BAG_SEEDS = (7, 8, 9)`.
  - `@dataclass(frozen=True) class Bag` with `boosters: tuple[lgb.Booster, ...]`, and:
    - `predict(self, x, **kwargs) -> np.ndarray`, the elementwise mean of every booster's `predict(x, **kwargs)`, so `pred_contrib=True` averages contributions;
    - `feature_importance(self, importance_type: str = "split") -> np.ndarray`, the mean;
    - `model_strings(self) -> list[str]`.
  - `_fit_horizon(..., seeds: Sequence[int] = ())`. With two or more seeds, each part (q10, q50, q90, and `rank` or `beat`) is a `Bag` of boosters trained with `params | {"seed": s}`. Otherwise it's a plain `lgb.Booster`, as today.
  - `walk_forward(..., extra_features: Sequence[str] = (), bag: bool = False)` and `fit_final(..., extra_features: Sequence[str] = (), bag: bool = False)`.
    - The feature list is `data.features + extra_features + betas`.
    - With `bag`, seeds are `BAG_SEEDS`.
    - Every extra must be in `data.extras`, else ValueError naming the missing ones.
  - Files:
    - `to_files` writes a `Bag` part as `h{h}_{part}` (seed 7), then `h{h}_{part}_s1` and `h{h}_{part}_s2`, and puts `"bag": 3` in meta only when bagged.
    - `from_files` reads `meta.get("bag", 1)` and rebuilds a `Bag` when it's above 1.
  - `weekly.py` importance already calls `.feature_importance("gain")`, which a `Bag` answers.

- [ ] **Step 1: Write the failing tests** in `test_model_bagging.py`. Use `write_market(tmp_path, Market.TSX, stocks=20, days=1100)` and a fast config, as in `test_model_ranker.py`.
  - `test_a_bag_predicts_the_mean_of_its_seeds`: fit `_fit_horizon(x, y, FAST, seeds=BAG_SEEDS)`. Then:
    - each part is a `Bag` of 3;
    - `bag.predict(x)` equals the mean of the three boosters' predictions;
    - the three seeds' predictions aren't all equal (the seeds matter).
  - `test_the_baseline_trains_one_booster_per_part`: `_fit_horizon(x, y, FAST)` parts are `lgb.Booster`. Step 4's existing model tests, unchanged, are what show the baseline's predictions didn't move.
  - `test_extra_features_join_the_feature_list_only_when_asked`:
    - `fit_final(data, wf, FAST).features` has no `amihud_20`;
    - `fit_final(..., extra_features=data.extras)` has all three at the end, before any `beta_`;
    - an extra not in `data.extras` raises ValueError naming it.
  - `test_a_bagged_model_round_trips_with_three_seeds_per_part`:
    - `to_files` has `h5_q50`, `h5_q50_s1` and `h5_q50_s2`;
    - meta has `bag == 3`;
    - `from_files(...).predict(x)` equals `m.predict(x)`.
  - `test_a_model_saved_before_bagging_loads_with_one_booster_per_part`: a baseline model's files (no `bag`) load, and predict as before.
  - `test_a_bagged_explanation_and_importance_average_the_seeds`:
    - `m.contributions(x, 5)` for a row equals the top-3 of the mean of the three boosters' `pred_contrib`;
    - `m.boosters[5]["q50"].feature_importance("gain")` equals the mean of the three.

- [ ] **Step 2: Run them and watch them fail.**
  Run: `pipeline/scripts/in-docker.sh uv run pytest -q tests/unit/test_model_bagging.py`
  Expected: FAIL with ImportError on `Bag` or `BAG_SEEDS`.

- [ ] **Step 3: Implement the Interfaces above in `train.py`.** `_predict`, `FinalModel.predict` and `contributions` call `.predict` on the part, so a `Bag` works unchanged there.

- [ ] **Step 4: Run the new tests with the existing model tests.**
  Run: `pipeline/scripts/in-docker.sh uv run pytest -q tests/unit/test_model_bagging.py tests/unit/test_model_train.py tests/unit/test_model_ranker.py tests/unit/test_model_ranges.py tests/unit/test_model_weekly.py`
  Expected: all pass.

- [ ] **Step 5: Commit** `feat: seed bags and extra features in training, saved and loaded with the model`.

### Task 3: The `extras` and `bagged` variants: config, benchmark rows, weekly training, time limits

**Files:**
- Modify: `pipeline/src/advisor/model/variants.py`
- Modify: `pipeline/src/advisor/benchmark/job.py` (`ABLATIONS`)
- Modify: `pipeline/src/advisor/benchmark/report.py` (`_ABLATION_ORDER`)
- Modify: `.github/workflows/benchmark.yml` (`timeout-minutes: 360`), `.github/workflows/train.yml` (`timeout-minutes: 180`)
- Test: `pipeline/tests/unit/test_model_variants.py`, `test_benchmark_report.py`, `pipeline/tests/integration/test_benchmark_job.py`, `test_model_weekly_job.py`, and the workflow test that reads `benchmark.yml` (`tests/unit/test_benchmark_workflow.py`)

**Interfaces:**
- Consumes: `walk_forward(..., extra_features=, bag=)` and `fit_final(..., extra_features=, bag=)` from Task 2, and `MarketData.extras` from Task 1.
- Produces:
  - `CONFIG_VERSION = 3`, with `ModelConfig.extras: bool = False` and `ModelConfig.bagged: bool = False` as the last fields.
  - `name` joins the on parts in the order factors, garch, ranker, extras, bagged, for example `"ranker+extras+bagged"`.
  - `_KEYS[3]` is version 2's keys plus `"extras"` and `"bagged"`. Versions 1 and 2 load with both False.
  - `run_variant` and `fit_variant` pass `extra_features=data.extras if config.extras else ()` and `bag=config.bagged`.
  - `ABLATIONS` gains, after `"ranker"`:
    - `"extras": ModelConfig(extras=True)`;
    - `"ranker+extras": ModelConfig(ranker=True, extras=True)`;
    - `"ranker+extras+bagged": ModelConfig(ranker=True, extras=True, bagged=True)`.

    `_ABLATION_ORDER` gains the same three names in the same place.

- [ ] **Step 1: Write the failing tests.**
  - **Variants:**
    - `ModelConfig(ranker=True, extras=True, bagged=True).name == "ranker+extras+bagged"`;
    - `BASELINE.to_json() == {"version": 3, "factors": False, "garch": False, "ranker": False, "extras": False, "bagged": False, "policy": None}`;
    - `test_a_version_2_config_loads_with_extras_and_bagging_off`;
    - the refusal cases become version 4, version 3 missing `bagged`, and an extra key;
    - `test_an_extras_config_trains_on_the_extra_features`: `run_variant(data, ModelConfig(extras=True), FAST)` predictions equal `walk_forward(data, FAST, extra_features=data.extras)`.
  - **Report:** the ablation table prints `extras`, `ranker+extras` and `ranker+extras+bagged` after `ranker`.
  - **Benchmark job:**
    - TSX's `variants["ranker+extras+bagged"]["status"] == "run"`, and the markdown has its row;
    - `test_a_kept_version_2_config_is_unchanged`: an active accepted version 2 `ranker` config that the run chooses again reports `changed` False.
  - **Weekly job:** an active accepted config with `extras` and `bagged` on trains a model whose files have `h5_q50_s2`, and whose `features` include `amihud_20`.
  - **Workflows:** `benchmark.yml` has `timeout-minutes: 360`, and `train.yml` has `timeout-minutes: 180`.

- [ ] **Step 2: Run them and watch them fail.**
  Run: `pipeline/scripts/in-docker.sh uv run pytest -q tests/unit/test_model_variants.py tests/unit/test_benchmark_report.py tests/unit/test_benchmark_workflow.py tests/integration/test_benchmark_job.py tests/integration/test_model_weekly_job.py`
  Expected: FAIL on the new fields, the version, the missing rows and the timeouts.

- [ ] **Step 3: Implement the Interfaces above,** and the two timeouts.

- [ ] **Step 4: Run the same command.** Expected: all pass.

- [ ] **Step 5: Run the full suite and ruff.** Expected: all pass, and ruff reports "All checks passed!".

- [ ] **Step 6: Commit** `feat: extras and bagged variants the benchmark judges and weekly training follows once accepted`.

### Task 4: Words for the new features in explanations

**Files:**
- Modify: `web/lib/advice.ts` (`FACTORS`)
- Test: `web/lib/advice.test.ts`

**Interfaces:**
- Produces three `FACTORS` entries:
  - `sector_mom_12_1`: `{ label: "Its sector's 12-month momentum, skipping the last month", format: 'signedPct' }`;
  - `sector_dist_52w_high`: `{ label: "Its sector's distance from the 52-week high", format: 'signedPct' }`;
  - `amihud_20`: `{ label: 'Price move per $1M traded, 20-day average', format: 'pct' }`.

- [ ] **Step 1: Write the failing test** `it('describes the sector and illiquidity features')`. It checks:
  - `describeFactor('sector_mom_12_1', 0.12, 'SPY') === "Its sector's 12-month momentum, skipping the last month +12.0%"`;
  - `describeFactor('amihud_20', 0.0042, 'SPY') === 'Price move per $1M traded, 20-day average 0.4%'`.
- [ ] **Step 2: Run** `cd web && npx vitest run lib/advice.test.ts`. Expected: FAIL. Without an entry, the label falls back to the raw feature name.
- [ ] **Step 3: Add the entries.**
- [ ] **Step 4: Run** `npx vitest run && npx tsc --noEmit && npx eslint lib`. Expected: all pass, with no output from tsc or eslint.
- [ ] **Step 5: Commit** `feat: explanation labels for the sector and illiquidity features`.

### Task 5: Check the variants on real data

No code change. This measures the rows through the code path the benchmark will use, and their cost.

- [ ] **Step 1:** Run `run_variant` at horizons 21 and 63 for four configs: `BASELINE`, `ModelConfig(ranker=True)`, `ModelConfig(ranker=True, extras=True)` and `ModelConfig(ranker=True, extras=True, bagged=True)`.
  - Use the fixed quarter of US stocks, plus TSX and crypto, with the diagnostics scripts in `pipeline/.cache/diag/` (`half_us.py`, adapted from `ranker_check.py`).
  - Docker can't hold the full US universe, so run this on the host.
- [ ] **Step 2:** For each config, record:
  - pooled and per-fold `rank_ic` (on `score`);
  - `calibration_pts`;
  - pinball loss;
  - seconds.
- [ ] **Step 3:** Expected results:
  - `ranker+extras` beats `ranker` on pooled rank IC in at least one market;
  - bagging costs about 3× the seconds of its row without bagging;
  - the projected US benchmark (today's rows plus the three new ones, scaled from the quarter to the full universe) stays under 330 minutes.

  If no addition helps anywhere, or the projection is over, record the numbers and stop before merging, so the owner can decide which rows to keep.

## Self-review notes

- **Spec coverage:** every §9 item maps to a task:
  - the three features: Task 1;
  - coins' extra: Task 1;
  - "computed for every config, trained on only by `extras`": Tasks 1 and 2;
  - seed averaging, explanations and importance: Task 2;
  - config version 3: Task 3;
  - the benchmark rows: Task 3;
  - stored models with `bag`: Task 2;
  - the timeouts: Task 3;
  - the rank-normalisation limit is a spec statement and needs no task.
- **Explanations on the web:** Task 4 makes sure a forecast explained by a new feature reads in words.
