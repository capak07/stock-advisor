# Plan 7a: rank picks by the raw score — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A rank policy's top N follows the model's raw score instead of the clipped P with alphabetical ties, in the backtest, the policy book and live; and the benchmark reports how the top 5% of each ranking does.

**Architecture:** `p_raw` (the booster output P is calibrated from) already sits in every walk-forward frame; `in_top_n` ranks by it. Live, `FinalModel.predict` keeps it as `score`, `PredictionRow` carries it, and `top_by_horizon` ranks by it. A new `top_slice` measure in `benchmark/metrics.py` is stored per variant and rendered by the report. Nothing is added to the database.

**Tech Stack:** Python 3.12, pandas, LightGBM, pytest. Tests run in Docker: `bash pipeline/scripts/in-docker.sh uv run pytest -q`.

**Spec:** `docs/superpowers/specs/2026-11-19-prediction-improvements-design.md` (Plan 7a).

## Global Constraints

- No acceptance or policy limit changes: `MIN_TRADES`, the drawdown and trades-per-month limits, `PINBALL_TOLERANCE`, `MAX_CALIBRATION_PTS`, `MIN_FOLDS_IMPROVED` and the policy grid stay as they are.
- Only the top-N qualification changes. Horizon choice and list order still follow `policy.rule`. Avoid, Sell and the displayed probability still use P.
- No migration, no web change, no new benchmark row.
- A row with a NaN P or a NaN/missing raw score never ranks.
- `git commit` runs as its own command (a hook blocks `-n` flags in the same command). Never `--no-verify`. No push.
- Commit trailer: `Co-Authored-By: Claude Fable 5.2 <noreply@anthropic.com>`.

## Review Focus

1. Many stocks tied at the same P on one day: the top N must be the N highest raw scores, not the first N symbols. (Task 1, Task 2)
2. A frame or row without a raw score (a hand-built frame, a `PredictionRow` built without `score`): it must not rank and must not crash a non-rank policy. (Task 1, Task 2)
3. A day with too few stocks for a 5% slice, and rows whose `y` is NaN at the end of history: `top_slice` skips them rather than dividing by zero. (Task 3)
4. All scores equal on a day: `top_slice` still returns finite numbers, ties broken by symbol. (Task 3)
5. A stored report written before this plan has no `top_slice`: it must still render. (Task 3)

---

### Task 1: the backtest and the policy book rank by `p_raw`

**Files:**
- Modify: `pipeline/src/advisor/model/backtest.py` (`in_top_n`, its docstring and `_qualified`'s)
- Test: `pipeline/tests/unit/test_rank_backtest.py`

**Interfaces:**
- Produces: `in_top_n(df: pd.DataFrame, n: int) -> pd.Series` — unchanged signature. A row ranks only when both `p` and `p_raw` are finite; order is `p_raw` descending, then `symbol` ascending, per (`day`, `horizon`) where those columns exist. A frame with no `p_raw` column raises `KeyError("p_raw")`.
- `benchmark/simulate._candidates` and `backtest._qualified` already call `in_top_n`; they need no edit.

- [ ] **Step 1: Write the failing tests.** In `test_rank_backtest.py`, give `_frame()` a `p_raw` column and add:

```python
def _frame():
    day = pd.Timestamp("2026-01-05")
    return pd.DataFrame({
        "day": [day] * 5 + [day + pd.Timedelta(days=14)] * 2,
        "symbol": ["A", "B", "C", "D", "E", "A", "B"],
        "horizon": [21, 21, 21, 21, 63, 21, 21],
        "p": [0.47, 0.49, 0.48, np.nan, 0.40, 0.30, 0.31],
        "p_raw": [0.01, 0.03, 0.02, 0.09, 0.00, -0.02, -0.01],
    })


def test_tied_p_is_ranked_by_the_raw_score_not_the_alphabet():
    frame = _frame().iloc[:3].assign(p=0.53, p_raw=[0.01, 0.02, 0.03])  # A, B, C all at the ceiling
    assert in_top_n(frame, 2).tolist() == [False, True, True]


def test_a_row_without_a_raw_score_never_ranks():
    frame = _frame().iloc[:3].assign(p_raw=[np.nan, 0.02, 0.03])
    assert in_top_n(frame, 3).tolist() == [False, True, True]


def test_a_frame_without_raw_scores_is_refused():
    with pytest.raises(KeyError):
        in_top_n(_frame().drop(columns="p_raw"), 2)
```

Keep `test_rank_mode_simulates_the_top_n` as it is (D has the highest `p_raw` but a NaN P, so it still never ranks). Give every other frame in this file and in `test_sparse_picks.py`, `test_benchmark_policy_search*.py` or any other test that reaches `in_top_n` with `top_n` set a `p_raw` column equal to its `p`.

- [ ] **Step 2: Run them and see them fail.** `bash pipeline/scripts/in-docker.sh uv run pytest tests/unit/test_rank_backtest.py -q` — the three new tests fail (wrong order, or no `KeyError`).
- [ ] **Step 3: Change `in_top_n`** to filter on `p` and `p_raw` both finite and sort by `["p_raw", "symbol"]`. Update the two docstrings to say "raw score".
- [ ] **Step 4: Run the whole unit suite.** `bash pipeline/scripts/in-docker.sh uv run pytest tests/unit -q` — all pass. Fix any test frame that lacked `p_raw` by adding the column, never by loosening `in_top_n`.
- [ ] **Step 5: Commit.** `feat: rank the backtest's top N by the raw score`

### Task 2: live forecasts carry the raw score and rank by it

**Files:**
- Modify: `pipeline/src/advisor/models.py` (`PredictionRow`), `pipeline/src/advisor/model/train.py` (`FinalModel.predict`), `pipeline/src/advisor/model/predict.py` (`predict_rows`), `pipeline/src/advisor/model/crypto_live.py` (the `PredictionRow(...)` call), `pipeline/src/advisor/recommend/picks.py` (`top_by_horizon`)
- Test: `pipeline/tests/unit/test_picks_rank.py`, `pipeline/tests/unit/test_model_live.py` (or the file that already tests `predict_rows`)

**Interfaces:**
- `PredictionRow` gains a last field `score: float | None = None` — the raw score, None when unknown. Existing positional constructors keep working.
- `FinalModel.predict` returns its current columns plus `score` (the value it used to pop as `p_raw`); `p_beat` is unchanged.
- `predict_rows` and the crypto path pass `score=float(r.score)`.
- `top_by_horizon(rows, n)` — same signature and return type. A row ranks only when `p_beat` is not NaN and `score` is a finite number; order is `(-score, symbol)`.
- `repo.write_predictions` is untouched: the score is not stored.

- [ ] **Step 1: Write the failing tests.** In `test_picks_rank.py` (use the file's existing row helper, adding a `score` argument):

```python
def test_tied_p_is_ranked_by_the_raw_score():
    rows = [_row("AAA", 21, p=0.53, score=0.01), _row("BBB", 21, p=0.53, score=0.03), _row("CCC", 21, p=0.53, score=0.02)]
    assert top_by_horizon(rows, 2) == {21: {"BBB": (1, 3), "CCC": (2, 3)}}


def test_a_row_without_a_score_never_takes_a_place():
    rows = [_row("AAA", 21, p=0.60, score=None), _row("BBB", 21, p=0.50, score=0.01)]
    assert top_by_horizon(rows, 2) == {21: {"BBB": (1, 1)}}
```

Change `test_ties_rank_by_symbol` so the tie is on `score`, not on P. Add to the `predict_rows` test: every returned row's `score` is a finite float, and for two rows of one horizon with different `p_beat`, the higher `p_beat` has the higher `score`.

- [ ] **Step 2: Run them and see them fail.** `bash pipeline/scripts/in-docker.sh uv run pytest tests/unit/test_picks_rank.py -q`
- [ ] **Step 3: Implement** the five edits above. In `predict`, compute `p_beat` from `p_raw` and rename the column to `score` instead of popping it.
- [ ] **Step 4: Run the whole unit suite**, then the integration tests that exercise a run (`tests/integration -q`); all pass. Any caller that breaks on the extra `score` column from `predict` selects the columns it needs.
- [ ] **Step 5: Commit.** `feat: live forecasts carry the raw score and rank by it`

### Task 3: the top-slice measure, stored and reported

**Files:**
- Modify: `pipeline/src/advisor/benchmark/metrics.py`, `pipeline/src/advisor/benchmark/job.py` (`_benchmark_market`), `pipeline/src/advisor/benchmark/report.py`
- Test: `pipeline/tests/unit/test_benchmark_metrics.py` (create if absent), `pipeline/tests/unit/test_benchmark_report.py`

**Interfaces:**
- `TOP_SHARE = 0.05`, `MIN_DAY_ROWS = 20` in `metrics.py`.
- `top_slice(predictions: pd.DataFrame, market: Market | str, usd_fx_fee_pct: float) -> dict[str, dict[int, dict[str, float]]]` — keys are each fold as a string and `"pooled"`, then horizon. Each leaf: `{"days": int, "top_excess": float, "top_net": float, "bottom_excess": float}`.
  - Rows used: finite `score` and finite `y`. Fold 0 is included.
  - Per (day, horizon) with at least `MIN_DAY_ROWS` such rows: `k = max(1, floor(rows * TOP_SHARE))`; the top is the `k` highest `score`, ties by `symbol` ascending; the bottom is the `k` lowest, ties by `symbol` descending.
  - `top_excess` = mean `y` of the top minus mean `y` of all that day's rows. `bottom_excess` likewise. `top_net` = mean of (`y` minus `round_trip_cost(market, dollar_volume_20, usd_fx_fee_pct)`) over the top.
  - A leaf averages those per-day numbers over its days; `days` counts them. A horizon with no qualifying day is left out.
- `job.py`: `variants[name]["top_slice"] = top_slice(pred, market, usd_fx_fee_pct)`, and each `BenchmarkResult` json gains `"top_slice": top.get(fold)`.
- `report.py`: `_top_slice_table(name: str, variant: Mapping) -> list[str]`, rendered after the outer-folds table when the variant has `top_slice`; one row per horizon from `"pooled"`:

```
### Top 5% by score: {name}

| Horizon | Days | Top vs all | Top after costs | Bottom vs all |
| --- | --- | --- | --- | --- |
| 5 | 180 | +0.42% | -2.75% | -0.31% |
```

  Percentages use the file's `_net` formatter (or `_pct` if `_net` does not sign its output); a missing value renders as `—`.

- [ ] **Step 1: Write the failing tests.**

```python
def _slice_frame(scores, ys, day="2026-01-05", horizon=21, fold=1):
    n = len(scores)
    return pd.DataFrame({
        "day": pd.Timestamp(day), "symbol": [f"S{i:03d}" for i in range(n)], "horizon": horizon, "fold": fold,
        "score": scores, "y": ys, "dollar_volume_20": 5e7,
    })


def test_the_top_slice_is_the_highest_scores_against_the_whole_day():
    frame = _slice_frame(list(range(40)), [0.0] * 38 + [0.10, 0.20])  # k = 2: the two best scores earned 15% on average
    leaf = top_slice(frame, Market.TSX, 0.0)["pooled"][21]
    assert leaf["days"] == 1
    assert leaf["top_excess"] == pytest.approx(0.15 - 0.30 / 40)
    assert leaf["top_net"] == pytest.approx(0.15 - 0.001)  # TSX spread at this volume, no fx fee
    assert leaf["bottom_excess"] == pytest.approx(0.0 - 0.30 / 40)


def test_a_thin_day_and_unknown_outcomes_are_skipped():
    thin = _slice_frame(list(range(19)), [0.01] * 19)
    unknown = _slice_frame(list(range(40)), [np.nan] * 40, day="2026-01-19")
    assert top_slice(pd.concat([thin, unknown]), Market.TSX, 0.0) == {}


def test_equal_scores_break_ties_by_symbol():
    frame = _slice_frame([1.0] * 40, [0.40, 0.20] + [0.0] * 38)  # S000 and S001 are the top
    assert top_slice(frame, Market.TSX, 0.0)["pooled"][21]["top_excess"] == pytest.approx(0.30 - 0.60 / 40)


def test_each_fold_gets_its_own_block():
    frames = pd.concat([_slice_frame(list(range(40)), [0.0] * 40, fold=0),
                        _slice_frame(list(range(40)), [0.0] * 40, day="2026-03-02", fold=1)])
    assert set(top_slice(frames, Market.TSX, 0.0)) == {"0", "1", "pooled"}
```

Before relying on `0.001`, read `round_trip_cost` in `model/backtest.py` and use the value it gives TSX at `5e7` dollar volume with a zero fee.

In `test_benchmark_report.py`: a variant with `top_slice` renders the table header and a row for each pooled horizon; the existing fixture without `top_slice` renders with no such heading.

- [ ] **Step 2: Run them and see them fail** (`top_slice` is not defined; no table).
- [ ] **Step 3: Implement** `top_slice`, the `job.py` wiring and `_top_slice_table`.
- [ ] **Step 4: Run the whole suite and the linter.** `bash pipeline/scripts/in-docker.sh uv run pytest -q` and `bash pipeline/scripts/in-docker.sh uv run ruff check .` — both clean.
- [ ] **Step 5: Commit.** `feat: report how the top 5% of each ranking does`

### Task 4: record the change

**Files:**
- Modify: `docs/superpowers/deferred.md` (one entry: the seed-averaging test left out of 7a and why; the benchmark must be run by the owner to see the top-slice table and the policy row's new result)

- [ ] **Step 1:** Add the entry. **Step 2:** Commit the spec, this plan and `deferred.md`: `docs: plan 7a, rank picks by the raw score`
