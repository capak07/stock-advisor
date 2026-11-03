# Plan 6h: Probabilities Calibrated the Way the Live Model Is — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two changes to how the walk-forward judges P(beat):
- Refit the probability map every calendar month instead of once per outer fold.
- Never split tied probabilities across bins.

Together they make the benchmark and weekly training judge probabilities as fresh as the live model's.

**Architecture:** Everything is in `pipeline/src/advisor/model/train.py`.
- A new `_tie_bins` gives each row a bin in score order without splitting ties. `_bin_gaps` (the calibration error) and `Calibrator.fit` (its floor and ceiling) use it.
- A new `calibrate_p` replaces `walk_forward`'s per-fold calibration loop with a refit per (fold, calendar month).
- `benchmark/metrics.py`, `weekly.py` and the policy search read the walk-forward's `p` and `_bin_gaps`, so they follow without edits.

**Tech Stack:** Python 3.12, pandas, numpy, scipy's `isotonic_regression`, LightGBM, pytest (in Docker).

**Spec:** `docs/superpowers/specs/2026-10-28-prediction-upgrade-design.md`, §10.

## Global Constraints

- **Tests run in Docker,** from the repo root: `pipeline/scripts/in-docker.sh uv run pytest -q` and `pipeline/scripts/in-docker.sh uv run ruff check .`. Start Docker Desktop and `docker start advisor-pg` if they're down. Native pytest is blocked on this machine; `uv run --project pipeline python` works on the host for scripts that don't import psycopg.
- **Don't run two suites at once:** they share the test database.
- **Commits:** run `git commit` in its own command, never with `--no-verify`. Messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Don't push. No database writes.
- **Exact values (spec §10):**
  - **Refit cadence:** each calendar month of each outer fold after the first.
  - **Refit data:** every earlier prediction, from any fold, whose outcome ended before that month's first prediction day. "Ended" is today's rule: `_ended_before(days, calendar, horizon, start)`.
  - **No calibration:** the first outer fold (`fold == 0`) and any month with no ended outcome get `p` NaN.
  - **A value's bin:** (rows with a smaller value) × bins ÷ rows, rounded down.
  - **Clip bins:** still `min(20, max(1, rows // MIN_BIN))`, with `MIN_BIN` 500.
  - **Calibration error:** still 10 bins, count-weighted.
- **Unchanged:**
  - `calibrate_ranges` (per fold);
  - `fit_final`'s calibrator data (every prediction with `fold > 0`);
  - `Calibrator.to_json`/`from_json`, and so the stored model files;
  - the `score` column, and so every rank IC.

## Review Focus

1. **Row order must not change any calibration number.** Shuffling the rows of a frame with tied P must give the same calibration error. Tested in Task 1 (`test_calibration_error_does_not_depend_on_row_order`).
2. **A constant score must get its overall hit rate.** This happens with crypto's early folds, where too few rows make every booster constant. It must not get a floor or ceiling taken from whichever rows came first. Tested in Task 1 (`test_a_constant_score_gets_its_overall_hit_rate`).
3. **Distinct scores must still get ten equal bins,** or every existing calibration number moves for no reason. Tested in Task 1 (`test_distinct_probabilities_still_get_equal_count_bins`).
4. **A month with nothing ended yet must give NaN, not an error or a fit on nothing.** This is the first month of a fold at long horizons. Tested in Task 2 (`test_a_month_with_no_known_outcome_gets_no_probability`).
5. **No month may see an outcome that ended on or after its first day.** That would be look-ahead, and would make the benchmark flatter the model. Tested in Task 2 (`test_each_month_is_calibrated_only_on_outcomes_known_when_it_began`).

---

### Task 1: Tie-aware bins

**Files:**
- Modify: `pipeline/src/advisor/model/train.py` (`Calibrator.fit` and its docstring; `_bin_gaps`; new `_tie_bins`)
- Test: `pipeline/tests/unit/test_model_train.py`

**Interfaces:**
- Produces:
  - `_tie_bins(values: np.ndarray, bins: int) -> np.ndarray`: an int bin per row, from 0 to bins − 1. It is `np.searchsorted(np.sort(values), values, side="left") * bins // len(values)`.
  - `_bin_gaps(p, beat, bins) -> tuple[np.ndarray, np.ndarray]`: same signature as today. It returns per non-empty bin, in ascending bin order, the gap |mean p − hit rate| × 100 and the row count.
  - `Calibrator.fit`: same signature. `lo` and `hi` are the hit rates of the rows in the lowest and highest `_tie_bins` bins. The reversal rule is unchanged: if `lo > hi`, both become the overall rate.

- [ ] **Step 1: Write the failing tests.** Add them to `test_model_train.py`, and add `_bin_gaps` to its import from `advisor.model.train`:

```python
def test_tied_probabilities_are_never_split_across_bins():
    p = np.full(10_000, 0.5)
    beat = np.arange(10_000) < 5_000  # the early rows beat, the later ones didn't
    assert calibration_error(p, beat) == pytest.approx(0.0)
    gaps, counts = _bin_gaps(p, beat, 10)
    assert counts.tolist() == [10_000] and gaps.tolist() == pytest.approx([0.0])


def test_calibration_error_does_not_depend_on_row_order():
    rng = np.random.default_rng(4)
    p = rng.choice([0.3, 0.45, 0.5, 0.62], 20_000)
    beat = rng.random(20_000) < 0.45
    perm = rng.permutation(20_000)
    assert calibration_error(p[perm], beat[perm]) == pytest.approx(calibration_error(p, beat), abs=1e-9)


def test_distinct_probabilities_still_get_equal_count_bins():
    p = np.random.default_rng(5).uniform(0.2, 0.8, 10_000)
    _, counts = _bin_gaps(p, p > 0.5, 10)
    assert counts.tolist() == [1_000] * 10


def test_the_floor_takes_every_row_tied_at_the_lowest_score():
    # a constant booster's rows tie at one score: the floor is their whole hit rate, not the rate
    # of whichever 1,000 of them came first (crypto's early folds, 2026-11-03)
    rng = np.random.default_rng(6)
    tied_beat = np.concatenate([np.arange(1_000) % 2 == 0, np.arange(9_000) < 2_500])  # 50% first, 30% overall
    p_raw = np.concatenate([np.full(10_000, 0.2), rng.uniform(0.5, 0.9, 10_000)])
    beat = np.concatenate([tied_beat, rng.random(10_000) < 0.7])
    cal = Calibrator.fit(p_raw, beat)
    assert cal.lo == pytest.approx(0.30)
    assert cal(np.array([0.2]))[0] == pytest.approx(0.30, abs=0.01)


def test_a_constant_score_gets_its_overall_hit_rate():
    p_raw = np.full(20_000, 0.37)
    beat = np.arange(20_000) >= 12_000  # 40%, all in the later rows
    cal = Calibrator.fit(p_raw, beat)
    assert cal.lo == pytest.approx(0.40) and cal.hi == pytest.approx(0.40)
    assert cal(np.array([0.1, 0.37, 0.9])).tolist() == pytest.approx([0.40] * 3)
```

- [ ] **Step 2: Run them and watch them fail.**

Run: `pipeline/scripts/in-docker.sh uv run pytest -q tests/unit/test_model_train.py -k "tied or row_order or equal_count or floor_takes or constant_score"`

Expected: four fail (`tied`, `row_order`, `floor_takes`, `constant_score`). `equal_count` passes already, because it pins today's behaviour for distinct values.

- [ ] **Step 3: Implement `_tie_bins`, then use it in `_bin_gaps` and in `Calibrator.fit`'s floor and ceiling.**
  - `_bin_gaps` groups rows by `_tie_bins(p, bins)`, skips empty bins, and returns bins in ascending order.
  - `Calibrator.fit` keeps its bin count `min(20, max(1, len(p_raw) // min_bin))`.
  - Update the `Calibrator` docstring: the floor and ceiling are the lowest- and highest-scored bins, with tied scores kept together.

- [ ] **Step 4: Run the file, then the whole suite.**

Run: `pipeline/scripts/in-docker.sh uv run pytest -q tests/unit/test_model_train.py tests/unit/test_benchmark_metrics.py`, then `pipeline/scripts/in-docker.sh uv run pytest -q` and `pipeline/scripts/in-docker.sh uv run ruff check .`

Expected: all pass. If an existing test's expected number depended on splitting tied values by row order, update that number. Name each such test and the old and new values in your report. Change no other expectation.

- [ ] **Step 5: Commit**

```bash
git add pipeline/src/advisor/model/train.py pipeline/tests/unit/test_model_train.py
git commit -m "feat: tied probabilities share a bin in the calibration error and the calibrator's floor and ceiling"
```

---

### Task 2: Monthly refit in the walk-forward

**Files:**
- Modify: `pipeline/src/advisor/model/train.py`. Add `calibrate_p`, replace the per-fold `Calibrator` loop in `walk_forward` (the block that sets `pred["p"]`), and update the module docstring's "calibrates each period on earlier periods' predictions" to say each month.
- Test: `pipeline/tests/unit/test_model_train.py`. Replace `test_each_period_is_calibrated_only_on_outcomes_known_when_it_began` and add one test.

**Interfaces:**
- Consumes:
  - `Calibrator.fit` from Task 1;
  - `_ended_before(days, calendar, horizon, start) -> np.ndarray` (exists).
- Produces: `calibrate_p(pred: pd.DataFrame, calendar: pd.DatetimeIndex, horizon: int) -> pd.Series`.
  - Input: one horizon's predictions, with columns `day`, `fold`, `p_raw` and `y`.
  - Output: P aligned to `pred.index`.
  - Fits run in ascending fold order, then ascending calendar month (`day.dt.to_period("M")`) within each fold, skipping fold 0.
  - Each group's fit uses the rows of `pred` (any fold) where `_ended_before(pred["day"], calendar, horizon, <the group's earliest day>)` holds. The beat label is `y > 0`.
  - A group with no such rows gets NaN and no fit.
  - `walk_forward` sets `pred["p"] = calibrate_p(pred, data.calendar, h)`.

- [ ] **Step 1: Write the failing tests.** Add `calibrate_p` to the imports.

```python
def test_each_month_is_calibrated_only_on_outcomes_known_when_it_began(tmp_path, monkeypatch):
    write_market(tmp_path, Market.TSX, stocks=20, days=1100)
    data = load_market(tmp_path, Market.TSX)
    seen = []
    fit = Calibrator.fit

    def spy(cls, p_raw, beat, min_bin=500):
        seen.append(np.sort(p_raw))
        return fit(p_raw, beat, min_bin)

    monkeypatch.setattr(Calibrator, "fit", classmethod(spy))
    wf = walk_forward(data, TrainConfig(horizons=(63,), rounds=10, params=FAST.params))
    pred = wf.predictions
    position = data.calendar.searchsorted(pd.DatetimeIndex(pred["day"]))
    month = pred["day"].dt.to_period("M")
    groups = (
        pred[pred["p"].notna()].assign(month=month).groupby(["fold", "month"])["day"].min().sort_index()
    )
    assert len(groups) > 3 * pred["fold"].nunique() and len(seen) == len(groups)  # a refit per month
    own_fold_seen = False
    for ((k, _), first), p_raw in zip(groups.items(), seen, strict=True):
        known = position + 63 < data.calendar.searchsorted(first)
        np.testing.assert_array_equal(p_raw, np.sort(pred.loc[known, "p_raw"].to_numpy()))
        own_fold_seen |= bool((pred.loc[known, "fold"] == k).any())
    assert own_fold_seen  # later months learn from outcomes earlier in their own period
    assert pred.loc[pred["fold"] == 0, "p"].isna().all()


def test_a_month_with_no_known_outcome_gets_no_probability():
    calendar = pd.bdate_range("2021-01-04", periods=300)
    rng = np.random.default_rng(7)
    pred = pd.DataFrame({
        "day": np.repeat(calendar, 4),
        "fold": np.repeat((np.arange(300) >= 100).astype(int), 4),
        "p_raw": rng.uniform(0.3, 0.7, 1_200),
        "y": rng.normal(0, 0.05, 1_200),
    })
    p = calibrate_p(pred, calendar, 120)
    assert p.index.equals(pred.index)
    assert p[pred["fold"] == 0].isna().all()
    first_month = (pred["fold"] == 1) & (pred["day"].dt.to_period("M") == calendar[100].to_period("M"))
    assert p[first_month].isna().all()  # nothing from fold 0 had ended 120 sessions on
    assert p[pred["day"] >= calendar[200]].between(0, 1).all()
```

- [ ] **Step 2: Run them and watch them fail.**

Run: `pipeline/scripts/in-docker.sh uv run pytest -q tests/unit/test_model_train.py -k "each_month or no_known_outcome"`

Expected:
- `no_known_outcome` fails with an ImportError for `calibrate_p`, which errors the whole module. Comment out the import to see the second failure if you like.
- `each_month` fails because there are fewer fits than months.

- [ ] **Step 3: Implement `calibrate_p` and wire it into `walk_forward`.** Delete the old per-fold loop. Keep `pred["p"] = np.nan` semantics for uncalibrated rows.

- [ ] **Step 4: Run the file, then the whole suite.**

Run: `pipeline/scripts/in-docker.sh uv run pytest -q tests/unit/test_model_train.py`, then `pipeline/scripts/in-docker.sh uv run pytest -q` and `pipeline/scripts/in-docker.sh uv run ruff check .`

Expected: all pass. If an existing test's expected number moved because P is now refitted monthly, update it. Name each in your report, with the old and new values and why the move is expected. Change no other expectation.

- [ ] **Step 5: Commit**

```bash
git add pipeline/src/advisor/model/train.py pipeline/tests/unit/test_model_train.py
git commit -m "feat: the walk-forward refits each month's probability map on every outcome known when the month began"
```

---

### Task 3: Measure it on the investigation's data

This task changes no repo file. It checks the spec §10 numbers with the real code and records the result for the owner.

**Files:** none in the repo. Write outputs to `C:\Users\athar\AppData\Local\Temp\claude\c--Users-athar-OneDrive-Desktop-repos\ba0f2219-9595-413a-ba4f-37b959bf7d55\scratchpad\cal-diag\out-6h\`.

**Interfaces:**
- Consumes:
  - `scratchpad\cal-diag\run_wf.py`, with usage `run_wf.py {US|crypto} DATA_DIR OUT_DIR`;
  - the US quarter in `scratchpad\cal-diag\us_quarter\`;
  - all coins in `pipeline\.cache\benchmark-2026-11-01\training\`;
  - the old code's numbers in `scratchpad\cal-diag\out\metrics_{market}_{model}.json` and its timings: US baseline 223 s, ranker 226 s; crypto baseline 21 s, ranker 50 s.

- [ ] **Step 1: Run the walk-forwards with the branch's code.** Run from the worktree root so `--project pipeline` uses this branch:

Run: `uv run --project pipeline python <scratchpad>\cal-diag\run_wf.py US <scratchpad>\cal-diag\us_quarter <scratchpad>\cal-diag\out-6h`, then the same with `crypto` and the coins' data folder.

Expected: `done`, with US and crypto predictions written for both models.

- [ ] **Step 2: Compare old and new, per market, model and horizon.** Compare `calibration_pts`, `rank_ic` and `base_rate` from the two `metrics_*.json` folders, plus the run time.

Expected:
- `rank_ic` and `base_rate` are equal to 1e-9 at every horizon. The rows with P are the same set, and `score` is untouched. If a horizon differs, check whether a whole fold was uncalibrated before, and say so.
- Calibration at US 63/126 and crypto 7/14 is at or below the spec §10 table's "monthly refit" row, within 0.5 points. The tie-aware error can only remove row-order artefacts.
- Walk-forward time is within 20% of the old.
- If any of these fails, don't change code. Record it and say so in the final report.

- [ ] **Step 3: Record the table** (market × horizon × model: old and new calibration, rank IC equal yes/no, seconds) in the ledger and the final report. It goes to the owner with the merge decision.
