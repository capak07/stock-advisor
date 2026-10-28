# Plan 6a: The Evaluation Harness — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every later prediction upgrade (factors, GARCH, a tuned policy, crypto) is judged by one fixed, leakage-tested harness:
- nested walk-forward;
- metrics per outer fold and pooled;
- the acceptance rules;
- a stored benchmark report;
- an accepted configuration per market, which weekly training follows.

Plan 6a ships it with the baseline as the only runnable variant.

**Architecture:**
- **A configuration type** (`ModelConfig`) names a variant. Every variant runs through one seam, `run_variant`/`fit_variant` in `advisor/model/variants.py`. In 6a it runs today's `walk_forward`; Plans 6c and 6d extend it.
- **A new package, `advisor/benchmark/`,** holds the harness. Each module is pure except `job`:
  - `folds`: inner splits;
  - `metrics`: per-fold model and policy metrics;
  - `accept`: the acceptance rules and the choice between ablation rows;
  - `report`: the markdown;
  - `job`: the monthly CLI that writes to the database.
- **Migration 0010** stores benchmark runs, per-fold results and accepted configurations. `benchmark.yml` runs the job monthly and on demand. The weekly job trains whatever configuration is accepted, falling back to the baseline.

**Tech Stack:** Python 3.12, pandas, numpy, LightGBM, scipy (existing), psycopg, Postgres/Supabase RLS; pytest, ruff; GitHub Actions. **No new dependency** (`arch` arrives with Plan 6d).

**Spec:** `docs/superpowers/specs/2026-10-28-prediction-upgrade-design.md`:
- §1 the harness;
- §6 Fallbacks;
- §7 Determinism and testing;
- "Decisions after the builder check" 2, 4 and 7.

It extends `docs/superpowers/specs/2026-10-09-stock-advisor-design.md` §5.2 and §6.6.

**Owner decisions this plan relies on (2026-10-28):**
- the design is approved;
- the benchmark is a separate monthly or manual workflow;
- weekly training uses the accepted configuration;
- crypto gets its own model (Plan 6b), so storage already admits a `crypto` market key.

**Measured, so no prototype is needed:** the last weekly job's walk-forward took **557 s for US and 55 s for TSX**. A baseline-only benchmark is about 11 minutes plus the data build. Plans 6c–6e add roughly one walk-forward per variant, plus about 3× that for inner tuning. That fits the design's 2–3 hours and this plan's 330-minute job limit.

## Global Constraints

- **Tests run in Docker,** from `pipeline/`:
  - `scripts/in-docker.sh uv run pytest -q`;
  - `scripts/in-docker.sh uv run ruff check .`.
  
  Integration tests need the `advisor-pg` container.
- **Outer folds are `make_folds(days, TrainConfig())`:** 4 equal test periods after 2.0 years. They're never changed by this plan.
- **Inner folds:** 3 expanding splits (★) inside each outer training span. The first inner split needs at least 1.0 year of training. The embargo per horizon equals the horizon.
- **The calibration limit is 5 points:** import `MAX_CALIBRATION_PTS` from `advisor.model.backtest`; never restate it.
- **Model acceptance:**
  - pooled outer rank IC must improve on the reference (strictly);
  - pooled pinball loss may be no worse than **0.5%**;
  - calibration ≤ 5 points at every horizon usable in the reference;
  - rank IC must improve in at least **3 of 4** outer folds.
- **Fail closed:** a NaN or missing metric never passes a rule.
- **Outer fold 0 has no calibration or policy score** (no earlier predictions). Policy metrics use folds 1–3.
- **Determinism:**
  - library code never reads the clock (`now` is passed in);
  - seeds come from `PARAMS`;
  - fixed constants only.
- **Market keys in the database** are `'US'`, `'TSX'` and `'crypto'`.
- **The survivorship sentence is exact copy,** used at the top of every report: `Survivorship: the stock universes are today's listings — Yahoo has no delisted tickers and SEC's ticker map is current-only — so every result here is optimistic by an unknown amount.`
- **Secrets:** the workflow gets only `DATABASE_URL` and `SEC_USER_AGENT` from GitHub secrets. `ADMIN_DATABASE_URL` never goes to GitHub.
- **Git:**
  - run `git commit` in its own command (a hook mistakes any `-n` in the same command for `--no-verify`);
  - never pass `--no-verify`;
  - end every commit message with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`;
  - don't push: the owner pushes.

## Review Focus

1. **GitHub cron ORs day-of-month with day-of-week,** so `0 9 1-7 * 0` would run on days 1–7 *and* every Sunday. The job must run only on the month's first Sunday, or on demand. Pinned in Task 9.
2. **A job killed by the 6-hour Actions limit leaves its `benchmark_runs` row `running` forever.** The next start must mark it `failed`, with the reason. Pinned in Task 5.
3. **A stored configuration this code can't run** (e.g. `factors: true` written by a later plan, then a rollback) must not crash weekly training. It must fall back to the baseline and say so. Pinned in Task 8.
4. **A variant that scores a different set of rows than the baseline** must not be compared at all. The market errors and nothing is accepted. Pinned in Task 7.
5. **A horizon with no calibrated rows** (e.g. US 126 days in the last fold) or a NaN metric must fail acceptance closed, and show as "—" in the report, never "nan". Pinned in Tasks 4 and 6.

## What this plan does not build (and who does)

- **The equal-weight daily book's Sharpe and drawdown, and the policy acceptance rule:** they need daily stop exits, which Plan 6e's simulator builds. 6a reports per-trade policy metrics of the default policy only.
- **Re-tuning an accepted variant over the whole history** (builder-check decision 2): the baseline has nothing to tune. The first tunable variant (6c or 6d) adds it.
- **The Kenneth French cross-check:** Plan 6c. **Crypto:** Plan 6b.
- **`inner_walk_forward` has no caller in 6a.** Plans 6d (range scale) and 6e (policy) are its first callers. It ships now so its leakage test guards it from the start.

---

### Task 1: Configurations and the variant seam

**Files:**
- Create: `pipeline/src/advisor/model/variants.py`
- Modify: `pipeline/src/advisor/model/train.py` (`walk_forward` signature and test-row filter)
- Test: `pipeline/tests/unit/test_model_variants.py`

**Interfaces:**
- **Produces:**
  - **`ModelConfig`**, a frozen dataclass:
    - `factors: bool = False`;
    - `garch: bool = False`;
    - `policy: Mapping[str, float] | None = None`;
    - the property `name -> str`;
    - `to_json() -> dict`;
    - `ModelConfig.from_json(d: Mapping) -> ModelConfig`.
  - **`BASELINE = ModelConfig()`.**
  - **`unbuilt(config: ModelConfig) -> str | None`:** the plan that builds the config's first missing part (`"Plan 6c"` for factors, `"Plan 6d"` for GARCH, `"Plan 6e"` for a policy), or `None`.
  - **`run_variant(data: MarketData, config: ModelConfig, train_config: TrainConfig, folds: Sequence[Fold] | None = None, known_before: pd.Timestamp | None = None) -> WalkForward`.**
  - **`fit_variant(data: MarketData, wf: WalkForward, config: ModelConfig, train_config: TrainConfig) -> FinalModel`.**
  - **`walk_forward(data, config=TrainConfig(), folds=None, known_before=None)`:**
    - `folds=None` means `make_folds` as today;
    - `known_before`, when given, keeps only test rows whose target ended before it.
- **Name rules:**
  - `"baseline"`, `"factors"`, `"garch"`, `"factors+garch"`;
  - with a policy, `"+policy"` is appended, e.g. `"baseline+policy"`.
- **`to_json()` returns exactly** `{"version": 1, "factors": bool, "garch": bool, "policy": dict | None}`.

- [ ] **Step 1: Write the failing tests**

```python
FAST = TrainConfig(horizons=(5, 63), rounds=40, params={**PARAMS, "min_data_in_leaf": 50, "num_threads": 2})

def test_configs_name_themselves_and_round_trip():
    assert BASELINE.name == "baseline"
    assert ModelConfig(factors=True, garch=True).name == "factors+garch"
    assert ModelConfig(policy={"p_buy": 0.6}).name == "baseline+policy"
    assert BASELINE.to_json() == {"version": 1, "factors": False, "garch": False, "policy": None}
    assert ModelConfig.from_json(BASELINE.to_json()) == BASELINE

@pytest.mark.parametrize("stored, match", [
    ({"version": 1, "factors": True, "garch": False, "policy": None}, "Plan 6c"),
    ({"version": 1, "factors": False, "garch": False, "policy": {"p_buy": 0.6}}, "Plan 6e"),
    ({"version": 2, "factors": False, "garch": False, "policy": None}, "version"),
    ({"version": 1, "factors": False, "garch": False, "policy": None, "extra": 1}, "extra"),
    ([], "mapping"),
])
def test_a_stored_config_this_code_cannot_run_is_refused(stored, match):
    with pytest.raises(ValueError, match=match):
        ModelConfig.from_json(stored)

def test_unbuilt_variants_say_which_plan_builds_them(tmp_path):
    write_market(tmp_path, Market.TSX, stocks=20, days=1100)
    with pytest.raises(NotImplementedError, match="Plan 6d"):
        run_variant(load_market(tmp_path, Market.TSX), ModelConfig(garch=True), FAST)

def test_the_baseline_runs_todays_walk_forward_unchanged(tmp_path):
    write_market(tmp_path, Market.TSX, stocks=20, days=1100)
    data = load_market(tmp_path, Market.TSX)
    pd.testing.assert_frame_equal(run_variant(data, BASELINE, FAST).predictions, walk_forward(data, FAST).predictions)

def test_walk_forward_scores_only_targets_known_before_a_cutoff(tmp_path):
    write_market(tmp_path, Market.TSX, stocks=20, days=1100)
    data = load_market(tmp_path, Market.TSX)
    folds = make_folds(pd.DatetimeIndex(data.rows["day"].unique()), TrainConfig())
    cutoff = folds[2].start
    pred = walk_forward(data, FAST, folds=folds[:2], known_before=cutoff).predictions
    assert not pred.empty
    position = data.calendar.searchsorted(pd.DatetimeIndex(pred["day"]))
    assert (position + pred["horizon"].to_numpy() < data.calendar.searchsorted(cutoff)).all()
```

- [ ] **Step 2: Run them and watch them fail**

Run: `scripts/in-docker.sh uv run pytest -q tests/unit/test_model_variants.py`
Expected: FAIL. The collection error says `advisor.model.variants` is missing.

- [ ] **Step 3: Implement `variants.py` and the `walk_forward` parameters**

- **`walk_forward`:** apply `known_before` with the existing `_ended_before` helper, on the test-row mask only. Training rows and calibration are unchanged.
- **`from_json` refuses** (`ValueError`, message naming the cause):
  - a non-mapping;
  - any key set other than the four;
  - a version other than 1;
  - a config `unbuilt` names. The message includes that plan.
- **`run_variant` and `fit_variant`** raise `NotImplementedError(f"{config.name} arrives with {plan}")` for unbuilt configs. Otherwise they call `walk_forward` and `fit_final`.

- [ ] **Step 4: Run the tests and the existing train tests**

Run: `scripts/in-docker.sh uv run pytest -q tests/unit/test_model_variants.py tests/unit/test_model_train.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pipeline/src/advisor/model/variants.py pipeline/src/advisor/model/train.py pipeline/tests/unit/test_model_variants.py
```
```bash
git commit -m "feat: name model variants and run them through one seam"
```

---

### Task 2: Inner folds and the leakage tests

**Files:**
- Create: `pipeline/src/advisor/benchmark/__init__.py` (a docstring only)
- Create: `pipeline/src/advisor/benchmark/folds.py`
- Test: `pipeline/tests/unit/test_benchmark_folds.py`

**Interfaces:**
- **Consumes:** `run_variant`, `BASELINE`, `ModelConfig` (Task 1); `Fold`, `make_folds`, `TrainConfig`, `WalkForward` (train.py).
- **Produces:**
  - `INNER_SPLITS = 3` and `INNER_MIN_TRAIN_YEARS = 1.0`;
  - **`inner_folds(days: pd.DatetimeIndex, outer: Fold, splits: int = INNER_SPLITS, min_train_years: float = INNER_MIN_TRAIN_YEARS) -> list[Fold]`:**
    - equal test periods from `days.min() + min_train_years` to `outer.start`;
    - the last ends at `outer.start`;
    - `[]` when that span is empty.
  - **`inner_walk_forward(data: MarketData, config: ModelConfig, train_config: TrainConfig, outer: Fold) -> WalkForward`:**
    - `run_variant` with `folds=inner_folds(...)` and `known_before=outer.start`;
    - an empty `WalkForward` (no predictions) when there are no inner folds.

- [ ] **Step 1: Write the failing tests**

```python
DAYS = pd.bdate_range("2017-01-02", "2024-12-31")

def test_inner_folds_split_the_outer_training_span_after_a_year():
    outer = Fold(pd.Timestamp("2019-01-02"), pd.Timestamp("2020-06-01"))
    inner = inner_folds(DAYS, outer)
    assert len(inner) == 3
    assert inner[0].start == pd.Timestamp("2018-01-02") and inner[-1].end == outer.start
    assert all(a.end == b.start for a, b in zip(inner, inner[1:]))
    lengths = {(f.end - f.start).days for f in inner}
    assert max(lengths) - min(lengths) <= 1

def test_an_outer_fold_too_early_for_a_year_of_training_has_no_inner_folds():
    assert inner_folds(DAYS, Fold(pd.Timestamp("2017-10-02"), pd.Timestamp("2018-06-01"))) == []

def test_inner_predictions_never_see_the_outer_period(tmp_path):
    write_market(tmp_path, Market.TSX, stocks=20, days=1100)
    data = load_market(tmp_path, Market.TSX)
    outer = make_folds(pd.DatetimeIndex(data.rows["day"].unique()), TrainConfig())[2]
    before = inner_walk_forward(data, BASELINE, FAST, outer).predictions
    rows, rng = data.rows.copy(), np.random.default_rng(0)
    start = data.calendar.searchsorted(outer.start)
    position = data.calendar.searchsorted(pd.DatetimeIndex(rows["day"]))
    for h in FAST.horizons:  # every outcome not yet known when the outer period begins
        late = position + h >= start
        rows.loc[late, f"y_{h}"] = rng.normal(size=late.sum())
    later = rows["day"] >= outer.start
    rows.loc[later, data.features] = rng.normal(size=(later.sum(), len(data.features)))
    after = inner_walk_forward(replace(data, rows=rows), BASELINE, FAST, outer).predictions
    assert not before.empty and (before["day"] < outer.start).all()
    pd.testing.assert_frame_equal(before, after)

def test_an_outer_fold_is_predicted_without_its_own_outcomes(tmp_path):
    write_market(tmp_path, Market.TSX, stocks=20, days=1100)
    data = load_market(tmp_path, Market.TSX)
    wf, k = run_variant(data, BASELINE, FAST), 2
    fold = wf.folds[k]
    rows = data.rows.copy()
    inside = (rows["day"] >= fold.start) & (rows["day"] < fold.end)
    for h in FAST.horizons:
        rows.loc[inside, f"y_{h}"] = -rows.loc[inside, f"y_{h}"]
    again = run_variant(replace(data, rows=rows), BASELINE, FAST)
    cols = ["day", "symbol", "horizon", "fold", "q10", "q50", "q90", "p_raw", "p"]
    upto = lambda p: p.loc[p["fold"] <= k, cols].reset_index(drop=True)  # noqa: E731
    pd.testing.assert_frame_equal(upto(wf.predictions), upto(again.predictions))
```

(`FAST` is as in Task 1. `replace` is `dataclasses.replace`.)

- [ ] **Step 2: Run them and watch them fail**

Run: `scripts/in-docker.sh uv run pytest -q tests/unit/test_benchmark_folds.py`
Expected: FAIL with `ModuleNotFoundError: advisor.benchmark`.

- [ ] **Step 3: Implement `folds.py`.** Compute the first inner start as in `make_folds`: `days.min() + pd.DateOffset(months=round(min_train_years * 12))`. Use `pd.date_range(first, outer.start, periods=splits + 1)` for the edges.  `inner_walk_forward` passes the row days (`pd.DatetimeIndex(data.rows["day"].unique())`), the same days `walk_forward` gives `make_folds`.

- [ ] **Step 4: Run the tests**

Run: `scripts/in-docker.sh uv run pytest -q tests/unit/test_benchmark_folds.py`
Expected: PASS. **If a perturbation test fails only by floating-point noise,** the cause is LightGBM thread nondeterminism. Add `"deterministic": True, "force_row_wise": True` to the test's `FAST` params and ledger it as a ruling. Never loosen the assertion.

- [ ] **Step 5: Commit**

```bash
git add pipeline/src/advisor/benchmark pipeline/tests/unit/test_benchmark_folds.py
```
```bash
git commit -m "feat: inner walk-forward splits, with leakage tests for inner and outer folds"
```

---

### Task 3: Per-fold metrics

**Files:**
- Create: `pipeline/src/advisor/benchmark/metrics.py`
- Test: `pipeline/tests/unit/test_benchmark_metrics.py`

**Interfaces:**
- **Consumes:**
  - from `train.py`: the `WalkForward.predictions` columns (`day, symbol, sector, dollar_volume_20, [jump_5d], horizon, fold, y, q10, q50, q90, p_raw, p`), `rank_ic` and `calibration_error`;
  - from `backtest.py`: `simulate_picks` and `MAX_CALIBRATION_PTS`.
- **Produces:**
  - **`pinball_loss(y: np.ndarray, q: np.ndarray, alpha: float) -> float`:** the mean of `max(alpha·(y−q), (alpha−1)·(y−q))`.
  - **`model_metrics(predictions: pd.DataFrame) -> dict[str, dict[int, dict[str, float]]]`:**
    - keys are each fold present as a string (`"0"`…) plus `"pooled"`;
    - per horizon: `rank_ic`, `pinball_q10`, `pinball_q50`, `pinball_q90`, `pinball` (their mean), `coverage_10_90`, `calibration_pts`, `max_bin_gap_pts` and `rows`;
    - calibration uses rows with `p` only, and is NaN when there are none.
  - **`summary(metrics, horizons: Sequence[int]) -> dict[str, dict[str, float]]`:** per fold key, `{"rank_ic", "pinball"}`, each the mean over the horizons present, ignoring NaN (as `weekly._mean_or_nan`).
  - **`calibrated_horizons(metrics) -> tuple[int, ...]`:** horizons whose pooled `calibration_pts` is measured and ≤ `MAX_CALIBRATION_PTS`.
  - **`policy_metrics(predictions: pd.DataFrame, market: Market, usd_fx_fee_pct: float) -> dict[str, dict]`:**
    - the default policy (`simulate_picks`) is run once over all rows with `p`;
    - each pick gets the fold of its day;
    - keys are each fold with `p` present, plus `"pooled"`;
    - values are `trades`, `trades_per_month`, `mean_net_pct`, `hit_rate_net`, `beat_rate`, `mean_p` and `claimed_gap_pts` (|mean_p − beat_rate| × 100);
    - rates are `None` when there are no trades;
    - `trades_per_month` is trades ÷ the number of distinct calendar months among that fold's prediction days.

- [ ] **Step 1: Write the failing tests**

```python
def rows(fold, day, ys, q50s, p=np.nan, horizon=5):
    n = len(ys)
    q50 = np.asarray(q50s, float)
    return pd.DataFrame({
        "day": pd.Timestamp(day), "symbol": [f"S{i}" for i in range(n)], "sector": "Tech",
        "dollar_volume_20": 2e7, "horizon": horizon, "fold": fold, "y": ys,
        "q10": q50 - 0.1, "q50": q50, "q90": q50 + 0.1, "p_raw": 0.5, "p": p,
    })

def test_pinball_loss_weights_misses_by_the_quantile():
    assert pinball_loss(np.array([0.2, -0.1]), np.zeros(2), 0.1) == pytest.approx(0.055)
    assert pinball_loss(np.array([0.2, -0.1]), np.zeros(2), 0.9) == pytest.approx(0.095)

def test_each_outer_fold_and_the_pool_are_scored_and_fold_0_has_no_calibration():
    pred = pd.concat([
        rows(0, "2024-01-02", [.01, .02, .03], [.01, .02, .03]),
        rows(0, "2024-01-16", [.03, .01, .02], [.03, .01, .02]),
        rows(1, "2024-02-01", [.01, .02, .03], [.03, .02, .01], p=[.4, .5, .6]),
        rows(1, "2024-02-15", [.01, .02, .03], [.03, .02, .01], p=[.4, .5, .6]),
    ], ignore_index=True)
    m = model_metrics(pred)
    assert set(m) == {"0", "1", "pooled"}
    assert m["0"][5]["rank_ic"] == pytest.approx(1.0) and m["1"][5]["rank_ic"] == pytest.approx(-1.0)
    assert m["pooled"][5]["rank_ic"] == pytest.approx(0.0)
    assert math.isnan(m["0"][5]["calibration_pts"])
    fold1 = pred[pred["fold"] == 1]
    assert m["pooled"][5]["calibration_pts"] == pytest.approx(calibration_error(fold1["p"], fold1["y"] > 0))
    assert m["1"][5]["rows"] == 6 and m["pooled"][5]["coverage_10_90"] == 1.0
    assert summary(m, (5,))["1"] == {"rank_ic": pytest.approx(-1.0), "pinball": m["1"][5]["pinball"]}

def test_the_default_policy_is_scored_per_calibrated_fold():
    pred = pd.concat([
        rows(0, "2024-02-01", [.03], [.05]),  # no p: never picked
        rows(1, "2024-03-01", [.03], [.05], p=.7).assign(symbol="S1"),
        rows(1, "2024-04-01", [.04], [.05], p=.7).assign(symbol="S2"),
        rows(2, "2024-05-01", [-.02], [.05], p=.7).assign(symbol="S3"),
    ], ignore_index=True)
    m = policy_metrics(pred, Market.TSX, 1.5)
    assert set(m) == {"1", "2", "pooled"}
    assert m["1"]["trades"] == 2 and m["1"]["trades_per_month"] == pytest.approx(1.0)
    assert m["2"]["hit_rate_net"] == 0.0 and m["pooled"]["trades"] == 3
    assert m["pooled"]["claimed_gap_pts"] == pytest.approx(abs(0.7 - 2 / 3) * 100)
```

- [ ] **Step 2: Run them and watch them fail**

Run: `scripts/in-docker.sh uv run pytest -q tests/unit/test_benchmark_metrics.py`
Expected: FAIL (`ImportError`).

- [ ] **Step 3: Implement `metrics.py`.** Reuse `rank_ic`, `_bin_gaps`/`calibration_error` and `simulate_picks`; don't reimplement them. Sort rows by `(fold, horizon, day, symbol)` before computing, so the output is order-independent.

- [ ] **Step 4: Run the tests**

Run: `scripts/in-docker.sh uv run pytest -q tests/unit/test_benchmark_metrics.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pipeline/src/advisor/benchmark/metrics.py pipeline/tests/unit/test_benchmark_metrics.py
```
```bash
git commit -m "feat: score each outer fold and the pool: rank IC, pinball, coverage, calibration, default policy"
```

---

### Task 4: The acceptance rules

**Files:**
- Create: `pipeline/src/advisor/benchmark/accept.py`
- Test: `pipeline/tests/unit/test_benchmark_accept.py`

**Interfaces:**
- **Consumes:** `model_metrics`, `summary` and `calibrated_horizons` (Task 3); `MAX_CALIBRATION_PTS`.
- **Produces:**
  - **Constants:** `PINBALL_TOLERANCE = 0.005` and `MIN_FOLDS_IMPROVED = 3`.
  - **`Scores`**, a frozen dataclass:
    - `rank_ic: Mapping[str, float]` (fold keys plus `"pooled"`);
    - `pinball: float` (pooled);
    - `calibration: Mapping[int, float]` (pooled, per horizon);
    - `Scores.of(metrics, horizons) -> Scores`.
  - **`Decision`**, a frozen dataclass: `accepted: bool` and `reasons: tuple[str, ...]`.
  - **`accept_model(candidate: Scores, reference: Scores) -> Decision`:** evaluates every rule and lists every failure. On a pass, the single reason is `f"rank IC {c:.3f} vs {r:.3f}, better in {n} of {total} outer folds"`.
  - **`choose_model(baseline: Scores, candidates: Mapping[str, Scores], incumbent: tuple[str, Scores] | None) -> tuple[str, dict[str, Decision]]`:** returns the chosen name and each candidate's decision against the baseline.
- **Failure reasons (exact copy):**
  - `f"rank IC {c:.3f} is not above {r:.3f}"`
  - `f"pinball loss {pct:.1f}% worse (limit 0.5%)"`
  - `f"horizon {h}: probabilities off by {pts:.1f} points (limit 5)"` (`"couldn't be measured"` replaces the numbers when NaN or missing)
  - `f"rank IC better in {n} of {total} outer folds (needs 3)"`
- **The choice rule** (builder-check decision 7, with the incumbent rule this plan adds):
  - **Passing rows:** the candidates that pass against the baseline.
  - **Best:** the passing row with the highest pooled rank IC. A tie goes to the earlier one in the candidates' order.
  - **With an incumbent** (a non-baseline accepted config):
    - if the incumbent itself still passes against the baseline, the best replaces it only if the best also passes `accept_model(best, incumbent)`; otherwise the incumbent stays;
    - if the incumbent no longer passes, the best is chosen, or `"baseline"`.
  - **With nothing passing,** the choice is `"baseline"`.

- [ ] **Step 1: Write the failing tests**

```python
def scores(ic=0.05, folds=(0.05, 0.05, 0.05, 0.05), pinball=0.010, cal=None):
    return Scores({**{str(k): v for k, v in enumerate(folds)}, "pooled": ic}, pinball, cal or {5: 3.0, 63: 4.0})

BASE = scores(ic=0.04, folds=(0.04,) * 4)

def test_a_better_candidate_passes():
    d = accept_model(scores(), BASE)
    assert d.accepted and d.reasons == ("rank IC 0.050 vs 0.040, better in 4 of 4 outer folds",)

def test_one_lucky_period_cannot_carry_it():
    d = accept_model(scores(ic=0.045, folds=(0.05, 0.05, 0.03, 0.03)), BASE)
    assert not d.accepted and "rank IC better in 2 of 4 outer folds (needs 3)" in d.reasons

def test_equal_rank_ic_is_not_an_improvement():
    assert not accept_model(BASE, BASE).accepted

def test_pinball_may_worsen_by_half_a_percent_and_no_more():
    assert accept_model(scores(pinball=0.01004), BASE).accepted
    d = accept_model(scores(pinball=0.01006), BASE)
    assert not d.accepted and "pinball loss 0.6% worse (limit 0.5%)" in d.reasons

def test_calibration_is_judged_on_the_horizons_the_reference_could_use():
    d = accept_model(scores(cal={5: 3.0, 63: 5.4}), BASE)
    assert not d.accepted and "horizon 63: probabilities off by 5.4 points (limit 5)" in d.reasons
    unusable_63 = scores(ic=0.04, folds=(0.04,) * 4, cal={5: 3.0, 63: 6.0})
    assert accept_model(scores(cal={5: 3.0, 63: 7.0}), unusable_63).accepted

@pytest.mark.parametrize("candidate", [
    scores(ic=float("nan")), scores(pinball=float("nan")), scores(cal={5: 3.0}), scores(cal={5: 3.0, 63: float("nan")}),
])
def test_anything_unmeasured_fails_closed(candidate):
    assert not accept_model(candidate, BASE).accepted

def test_the_best_passing_row_is_chosen_and_a_combination_must_pass_on_its_own():
    name, decisions = choose_model(BASE, {
        "factors": scores(ic=0.05), "garch": scores(ic=0.06, folds=(0.06,) * 4),
        "factors+garch": scores(ic=0.07, folds=(0.07, 0.07, 0.01, 0.01)),
    }, None)
    assert name == "garch" and not decisions["factors+garch"].accepted
    assert choose_model(BASE, {"factors": scores(ic=0.03, folds=(0.03,) * 4)}, None)[0] == "baseline"

def test_a_challenger_must_also_beat_the_incumbent():
    incumbent = scores(ic=0.055, folds=(0.055,) * 4)
    challenger = scores(ic=0.06, folds=(0.06, 0.06, 0.05, 0.05))  # beats the baseline, not the incumbent
    assert choose_model(BASE, {"factors": incumbent, "garch": challenger}, ("factors", incumbent))[0] == "factors"
    fallen = scores(ic=0.03, folds=(0.03,) * 4)  # the incumbent no longer beats the baseline
    assert choose_model(BASE, {"factors": fallen, "garch": challenger}, ("factors", fallen))[0] == "garch"
```

- [ ] **Step 2: Run them and watch them fail**

Run: `scripts/in-docker.sh uv run pytest -q tests/unit/test_benchmark_accept.py`
Expected: FAIL (`ImportError`).

- [ ] **Step 3: Implement `accept.py`.** Write each comparison so a NaN fails, as `gate` does (`if not c > r`). Count fold improvements over the reference's non-`"pooled"` keys: `total` is their count, and a fold missing from the candidate counts as not improved.

- [ ] **Step 4: Run the tests**

Run: `scripts/in-docker.sh uv run pytest -q tests/unit/test_benchmark_accept.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pipeline/src/advisor/benchmark/accept.py pipeline/tests/unit/test_benchmark_accept.py
```
```bash
git commit -m "feat: the acceptance rules for model additions, and the choice between ablation rows"
```

---

### Task 5: Storage — migration 0010

**Files:**
- Create: `supabase/migrations/0010_benchmarks.sql`
- Modify: `pipeline/src/advisor/models.py` (two dataclasses)
- Modify: `pipeline/src/advisor/store/repo.py` (six functions)
- Test: `pipeline/tests/integration/test_schema.py` (append)
- Test: `pipeline/tests/integration/test_repo.py` (append)

**Interfaces:**
- **Produces, in `models.py`:**
  - `AcceptedConfig(id: int, market: str, config: dict, reason: str, accepted_at: datetime, benchmark_run_id: int)`;
  - `BenchmarkResult(market: str, variant: str, fold: str, metrics: dict)`.
- **Produces, in `repo.py`:**
  - `BENCHMARK_ABANDONED_AFTER = timedelta(hours=7)` (past Actions' 6-hour job limit);
  - **`start_benchmark_run(conn, now: datetime, git_sha: str | None) -> int`:**
    - first marks every `running` row started before `now - BENCHMARK_ABANDONED_AFTER` as `failed`;
    - sets `finished_at = now`;
    - merges `{"error": "abandoned: no finish was recorded (job killed or timed out)"}` into `report`.
  - `finish_benchmark_run(conn, run_id: int, now: datetime, status: str, report: Mapping) -> None`;
  - `write_benchmark_results(conn, run_id: int, rows: Sequence[BenchmarkResult]) -> None`;
  - `active_config(conn, market: str) -> AcceptedConfig | None`;
  - **`accept_config(conn, market: str, config: Mapping, reason: str, run_id: int, now: datetime) -> int`:** in one transaction, it retires the market's active row, inserts the new one active, and returns its id.
- **The schema:**

```sql
create table benchmark_runs (
  id bigint generated always as identity primary key,
  started_at timestamptz not null,
  finished_at timestamptz,
  status text not null default 'running' check (status in ('running', 'success', 'failed')),
  git_sha text check (git_sha ~ '^[0-9a-f]{7,40}$'),
  report jsonb not null default '{}'::jsonb
);
create table benchmark_results (
  run_id bigint not null references benchmark_runs (id) on delete cascade,
  market text not null check (market in ('US', 'TSX', 'crypto')),
  variant text not null check (variant ~ '^[a-z+]{1,40}$'),
  fold text not null check (fold ~ '^([0-9]|pooled)$'),
  metrics jsonb not null,
  primary key (run_id, market, variant, fold)
);
create table accepted_configs (
  id bigint generated always as identity primary key,
  market text not null check (market in ('US', 'TSX', 'crypto')),
  config jsonb not null,
  reason text not null,
  accepted_at timestamptz not null,
  benchmark_run_id bigint not null references benchmark_runs (id),
  active boolean not null default false
);
create unique index accepted_configs_one_active_per_market on accepted_configs (market) where active;
```

- **RLS and grants:** the same as `model_files` in `0008_model_files.sql`, for all three tables:
  - `owner_read` for `authenticated` via `public.is_owner()`;
  - `pipeline_write` for `pipeline_rw`;
  - grant select, insert, update and delete to `pipeline_rw`.
  
  Check how `0001`/`0002` grant identity-column tables (`runs`) and match it.
- **The file's header comment** names Plan 6a and says that weekly training reads `accepted_configs`, and only `benchmark.yml` writes it.

- [ ] **Step 1: Write the failing tests**

```python
# test_schema.py
RUN = "insert into benchmark_runs (started_at) values ('2026-11-01T09:00Z') returning id"

def test_the_owner_reads_benchmarks_and_only_the_pipeline_writes_them(owned_db):
    run_id = owned_db.execute(RUN).fetchone()["id"]
    owned_db.execute("insert into benchmark_results (run_id, market, variant, fold, metrics) values (%s, 'TSX', 'baseline', 'pooled', '{}')", (run_id,))
    owned_db.execute("insert into accepted_configs (market, config, reason, accepted_at, benchmark_run_id, active) values ('TSX', '{}', 'r', now(), %s, true)", (run_id,))
    for table in ("benchmark_runs", "benchmark_results", "accepted_configs"):
        with acting_as(owned_db, "authenticated", OWNER):
            assert len(owned_db.execute(f"select * from {table}").fetchall()) == 1
            assert owned_db.execute(f"delete from {table}").rowcount == 0
        with acting_as(owned_db, "authenticated", STRANGER):
            assert owned_db.execute(f"select * from {table}").fetchall() == []
    with acting_as(owned_db, "pipeline_rw"):
        assert owned_db.execute("update benchmark_runs set status = 'success'").rowcount == 1

def test_one_accepted_config_is_active_per_market(db):
    run_id = db.execute(RUN).fetchone()["id"]
    insert = "insert into accepted_configs (market, config, reason, accepted_at, benchmark_run_id, active) values (%s, '{}', 'r', now(), %s, true)"
    db.execute(insert, ("US", run_id))
    db.execute(insert, ("crypto", run_id))
    with pytest.raises(psycopg.errors.UniqueViolation):
        db.execute(insert, ("US", run_id))

@pytest.mark.parametrize("column, value", [("market", "us"), ("variant", "Baseline"), ("fold", "pool"), ("fold", "10")])
def test_malformed_benchmark_results_are_rejected(db, column, value):
    run_id = db.execute(RUN).fetchone()["id"]
    row = {"market": "TSX", "variant": "baseline", "fold": "0"} | {column: value}
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute("insert into benchmark_results (run_id, market, variant, fold, metrics) values (%s, %s, %s, %s, '{}')",
                   (run_id, row["market"], row["variant"], row["fold"]))

# test_repo.py
T0 = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)

def test_a_benchmark_run_is_started_and_finished(db):
    run_id = repo.start_benchmark_run(db, T0, "abc1234")
    repo.finish_benchmark_run(db, run_id, T0 + timedelta(hours=2), "success", {"markets": {}})
    row = db.execute("select * from benchmark_runs where id = %s", (run_id,)).fetchone()
    assert (row["status"], row["git_sha"], row["report"]) == ("success", "abc1234", {"markets": {}})

def test_a_killed_benchmark_is_marked_failed_by_the_next_start(db):
    killed = repo.start_benchmark_run(db, T0, None)
    repo.start_benchmark_run(db, T0 + timedelta(hours=8), None)
    row = db.execute("select * from benchmark_runs where id = %s", (killed,)).fetchone()
    assert row["status"] == "failed" and row["report"]["error"].startswith("abandoned")

def test_a_recent_running_benchmark_is_left_alone(db):
    running = repo.start_benchmark_run(db, T0, None)
    repo.start_benchmark_run(db, T0 + timedelta(hours=1), None)
    assert db.execute("select status from benchmark_runs where id = %s", (running,)).fetchone()["status"] == "running"

def test_accepting_a_config_retires_the_markets_previous_one(db):
    run_id = repo.start_benchmark_run(db, T0, None)
    assert repo.active_config(db, "TSX") is None
    first = repo.accept_config(db, "TSX", {"version": 1}, "first", run_id, T0)
    second = repo.accept_config(db, "TSX", {"version": 1, "x": 1}, "better", run_id, T0)
    active = repo.active_config(db, "TSX")
    assert active.id == second != first and active.reason == "better" and active.config == {"version": 1, "x": 1}
    repo.write_benchmark_results(db, run_id, [BenchmarkResult("TSX", "baseline", "pooled", {"a": 1})])
    assert db.execute("select metrics from benchmark_results").fetchone()["metrics"] == {"a": 1}
```

- [ ] **Step 2: Run them and watch them fail**

Run: `scripts/in-docker.sh uv run pytest -q tests/integration/test_schema.py tests/integration/test_repo.py`
Expected: the new tests FAIL (`relation "benchmark_runs" does not exist` / `AttributeError`).

- [ ] **Step 3: Write the migration, the dataclasses and the repo functions.** Use `Jsonb(...)` for JSON parameters, as `save_model` does.

- [ ] **Step 4: Run the whole integration suite**

Run: `scripts/in-docker.sh uv run pytest -q tests/integration`
Expected: PASS. This includes `test_every_public_table_has_row_level_security` and `test_every_table_except_migrations_has_a_pipeline_policy`, which now cover the three tables.

- [ ] **Step 5: Commit**

```bash
git add supabase/migrations/0010_benchmarks.sql pipeline/src/advisor/models.py pipeline/src/advisor/store/repo.py pipeline/tests/integration/test_schema.py pipeline/tests/integration/test_repo.py
```
```bash
git commit -m "feat: store benchmark runs, per-fold results and accepted configurations (migration 0010)"
```

---

### Task 6: The report

**Files:**
- Create: `pipeline/src/advisor/benchmark/report.py`
- Test: `pipeline/tests/unit/test_benchmark_report.py`

**Interfaces:**
- **Produces:**
  - `SURVIVORSHIP` (the exact sentence from Global Constraints);
  - `render_markdown(report: Mapping) -> str`;
  - `write_reports(report: Mapping, out: Path) -> None`, which writes `benchmark-report.json` (indented) and `benchmark-report.md` into `out` (created if missing).
- **The report shape** (Task 7 produces it; `None` stands for an unmeasured number):

```python
{
  "run_id": 3, "started_at": "2026-11-01T09:00:00+00:00", "git_sha": "abc1234", "status": "success",
  "constants": {"outer_folds": 4, "min_train_years": 2.0, "inner_splits": 3, "inner_min_train_years": 1.0,
                "pinball_tolerance": 0.005, "min_folds_improved": 3, "max_calibration_pts": 5.0,
                "seed": 7, "rounds": 200, "sample_every": 10},
  "markets": {
    "TSX": {
      "horizons": [5, 10, 20, 21, 63, 126],
      "variants": {
        "baseline": {"status": "run", "seconds": 55.0, "model": {...model_metrics...},
                     "summary": {...summary...}, "policy": {...policy_metrics...}},
        "factors": {"status": "not built", "plan": "Plan 6c"},
        # "garch" → Plan 6d, "factors+garch" → Plan 6c, "full+policy" → Plan 6e
      },
      "decisions": {"factors": {"accepted": False, "reasons": ["..."]}},  # only rows that ran
      "chosen": "baseline",
      "accepted": {"changed": True, "reason": "first benchmark: today's model", "config": {...}},
    },
    "US": {"error": "FileNotFoundError: ..."},
  },
}
```

- **The markdown layout:**
  - **The title:** `# Benchmark report — 2026-11-01 (abc1234)`, then the survivorship sentence as a blockquote.
  - **Per market, an `## TSX` section** containing:
    - **the choice:** `**Chosen:** baseline — first benchmark: today's model`, or `unchanged` when `accepted.changed` is false;
    - **an `### Ablations` table:** Variant | Status | Rank IC (pooled) | Pinball (pooled) | Worst calibration | Decision. An unbuilt row reads `| factors | arrives with Plan 6c | — | — | — | — |`. Ran rows read `run`; their decision is `reference` for the baseline, else `accepted`/`rejected: <first reason>`;
    - **per ran variant, an `### Outer folds: <variant>` table:** Fold | Rank IC | Pinball | Worst calibration | Coverage q10–q90. Fold 0's calibration reads `— (no earlier predictions)`;
    - **a `### Default policy (folds 1–3)` table:** Fold | Trades | Trades/month | Net per trade | Hit rate | Claimed P vs beat rate.
  - **A failed market reads** `## US` then `Failed: FileNotFoundError: ...`.
  - **A final `## How decisions are made` section,** one bullet per rule, from `constants`. It names the 0.5% pinball tolerance, "at least 3 of 4 outer folds", the 5-point calibration limit, "outer fold 0 has no calibration or policy score", and "a candidate must also beat the currently accepted configuration".
  - **Number formats:** rank IC `0.061`; pinball `0.01234`; calibration points `3.2`; coverage and rates as `81%`; net per trade `0.42%`; `None` or NaN as `—`.

- [ ] **Step 1: Write the failing tests.** Build a minimal report dict in the test: TSX with a ran baseline (two folds, one horizon, fold 0 calibration `None`), an unbuilt `factors` row, and a failed US. Assert:
  - `SURVIVORSHIP` appears once, near the top;
  - `"| factors | arrives with Plan 6c | — | — | — | — |"` appears;
  - `"Failed: FileNotFoundError: no prices"` appears under `## US`;
  - `"— (no earlier predictions)"` appears;
  - neither `"nan"` nor `"None"` appears anywhere;
  - `"0.5%"` and `"3 of 4"` appear under `## How decisions are made`;
  - `write_reports` round-trips: `json.loads(...)` of the JSON file equals the input, and the `.md` file equals `render_markdown(report)`.

- [ ] **Step 2: Run them and watch them fail**

Run: `scripts/in-docker.sh uv run pytest -q tests/unit/test_benchmark_report.py`
Expected: FAIL (`ImportError`).

- [ ] **Step 3: Implement `report.py`**

- [ ] **Step 4: Run the tests**

Run: `scripts/in-docker.sh uv run pytest -q tests/unit/test_benchmark_report.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pipeline/src/advisor/benchmark/report.py pipeline/tests/unit/test_benchmark_report.py
```
```bash
git commit -m "feat: render the benchmark report as markdown and JSON"
```

---

### Task 7: The benchmark job

**Files:**
- Create: `pipeline/src/advisor/benchmark/job.py`
- Modify: `pipeline/src/advisor/model/weekly.py` (rename `_clean` to the public `json_safe`; update its callers)
- Test: `pipeline/tests/integration/test_benchmark_job.py`

**Interfaces:**
- **Consumes:**
  - `ModelConfig`, `BASELINE`, `unbuilt`, `run_variant` (Task 1);
  - `model_metrics`, `summary`, `calibrated_horizons`, `policy_metrics` (Task 3);
  - `Scores`, `choose_model`, `PINBALL_TOLERANCE`, `MIN_FOLDS_IMPROVED` (Task 4);
  - `repo.*` and `BenchmarkResult` (Task 5);
  - `write_reports` (Task 6);
  - `load_market`, `repo.fee_settings`, `json_safe`.
- **Produces:**
  - **`ABLATIONS: dict[str, ModelConfig | None]`:**
    - `"baseline": BASELINE`, `"factors": ModelConfig(factors=True)`, `"garch": ModelConfig(garch=True)`, `"factors+garch": ModelConfig(factors=True, garch=True)`;
    - `"full+policy": None`: the chosen model plus a tuned policy, unbuilt until Plan 6e, reported as `{"status": "not built", "plan": "Plan 6e"}`.
  - `MARKET_ORDER = [Market.TSX, Market.US]` (smaller first, as `weekly.TRAIN_ORDER`);
  - `run(data_dir: Path, markets: Sequence[Market], conn, now: datetime, git_sha: str | None, train_config: TrainConfig = TrainConfig()) -> dict` (the report of Task 6);
  - `exit_code(report) -> int`: 1 if any market has `"error"`;
  - **`main(argv=None) -> int`:**
    - `--data DIR` (required);
    - `--out DIR` (required);
    - `--market` (repeatable);
    - the git sha comes from the `GITHUB_SHA` environment variable, else `None`;
    - it writes reports with `write_reports` and prints the markdown.
- **Per market, in order:**
  1. Load the data. Read the incumbent with `repo.active_config(conn, str(market))`.
  2. Run every built ablation through `run_variant` on the outer folds. An unbuilt one gets `{"status": "not built", "plan": unbuilt(config)}`.
  3. **Refuse to compare different rows.** Every ran variant's sorted `(day, symbol, horizon)` keys must equal the baseline's, else raise `ValueError(f"{name} scored different rows than the baseline")`.
  4. **Compute the metrics:** `model_metrics`, `summary`, and `policy_metrics` on rows with `p` in that variant's `calibrated_horizons`.
  5. **Write one `BenchmarkResult` per fold key and `"pooled"`,** with `metrics = json_safe({"model": model[k], "summary": summary[k], "policy": policy.get(k)})`.
  6. **Choose a model:** `choose_model(Scores.of(baseline), {other ran variants}, incumbent)`. The incumbent is `(name, Scores)` only if its config parses, isn't the baseline, and ran in this benchmark; else `None`.
  7. **Accept:**
     - with no active config, accept `BASELINE.to_json()` with reason `"first benchmark: today's model"`;
     - else, if the chosen name differs from the active config's name, accept `ABLATIONS[chosen].to_json()` with that decision's reason;
     - else nothing is written, and `accepted.changed` is false.
- **`run` itself:**
  - it calls `repo.start_benchmark_run`;
  - it runs each market in a `try` (one market's failure is recorded as `{"error": f"{type(e).__name__}: {e}"}`, and that market's accepted config is untouched);
  - it always calls `finish_benchmark_run`: `"success"` if no market failed, else `"failed"`;
  - an exception outside the market loop finishes the run as `"failed"` and is re-raised.

- [ ] **Step 1: Write the failing tests**

```python
NOW = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)
FAST = TrainConfig(horizons=(5, 63), rounds=40, params={**PARAMS, "min_data_in_leaf": 50, "num_threads": 2})

def test_a_first_benchmark_scores_the_baseline_and_accepts_it(db, tmp_path):
    write_market(tmp_path, Market.TSX, stocks=40)
    report = job.run(tmp_path, [Market.TSX], db, NOW, "abc1234", FAST)
    tsx = report["markets"]["TSX"]
    assert tsx["chosen"] == "baseline" and tsx["accepted"]["changed"] is True
    assert tsx["variants"]["factors"] == {"status": "not built", "plan": "Plan 6c"}
    assert tsx["variants"]["full+policy"] == {"status": "not built", "plan": "Plan 6e"}
    folds = {r["fold"] for r in db.execute("select fold from benchmark_results where variant = 'baseline'").fetchall()}
    assert folds == {"0", "1", "2", "3", "pooled"}
    run = db.execute("select * from benchmark_runs").fetchone()
    assert (run["status"], run["git_sha"]) == ("success", "abc1234")
    active = repo.active_config(db, "TSX")
    assert active.config == BASELINE.to_json() and active.reason == "first benchmark: today's model"
    assert active.benchmark_run_id == run["id"]

def test_a_second_benchmark_keeps_the_accepted_config(db, tmp_path):
    write_market(tmp_path, Market.TSX, stocks=40)
    job.run(tmp_path, [Market.TSX], db, NOW, None, FAST)
    first = repo.active_config(db, "TSX").id
    report = job.run(tmp_path, [Market.TSX], db, NOW + timedelta(days=28), None, FAST)
    assert report["markets"]["TSX"]["accepted"]["changed"] is False
    assert repo.active_config(db, "TSX").id == first
    assert db.execute("select count(*) as n from accepted_configs").fetchone()["n"] == 1

def test_a_failed_market_changes_nothing_and_fails_the_run(db, tmp_path):
    write_market(tmp_path, Market.TSX, stocks=40)  # no US files
    report = job.run(tmp_path, [Market.US, Market.TSX], db, NOW, None, FAST)
    assert report["markets"]["US"]["error"].startswith("FileNotFoundError")
    assert "chosen" in report["markets"]["TSX"] and job.exit_code(report) == 1
    assert db.execute("select status from benchmark_runs").fetchone()["status"] == "failed"
    assert repo.active_config(db, "US") is None

def test_a_variant_that_scores_different_rows_is_never_compared(db, tmp_path, monkeypatch):
    write_market(tmp_path, Market.TSX, stocks=40)
    real = job.run_variant
    def fewer_rows(data, config, *args, **kwargs):
        wf = real(data, BASELINE, *args, **kwargs)
        return wf if config == BASELINE else replace(wf, predictions=wf.predictions.iloc[1:])
    monkeypatch.setattr(job, "run_variant", fewer_rows)
    monkeypatch.setattr(job, "unbuilt", lambda config: None)  # pretend factors is built
    report = job.run(tmp_path, [Market.TSX], db, NOW, None, FAST)
    assert "scored different rows than the baseline" in report["markets"]["TSX"]["error"]
    assert repo.active_config(db, "TSX") is None
```

- [ ] **Step 2: Run them and watch them fail**

Run: `scripts/in-docker.sh uv run pytest -q tests/integration/test_benchmark_job.py`
Expected: FAIL (`ImportError: advisor.benchmark.job`).

- [ ] **Step 3: Implement `job.py` and the `json_safe` rename.** `job.py` imports `run_variant` and `unbuilt` by name (`from advisor.model.variants import ...`), so the test can patch them on `job`. Record per-variant `seconds` with `time.monotonic()`; the timing is reported but never decides anything.

- [ ] **Step 4: Run the job tests and the weekly tests**

Run: `scripts/in-docker.sh uv run pytest -q tests/integration/test_benchmark_job.py tests/integration/test_model_weekly_job.py tests/unit/test_model_weekly.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pipeline/src/advisor/benchmark/job.py pipeline/src/advisor/model/weekly.py pipeline/tests/integration/test_benchmark_job.py
```
```bash
git commit -m "feat: the benchmark job scores every built ablation and promotes accepted configurations"
```

---

### Task 8: Weekly training follows the accepted configuration

**Files:**
- Modify: `pipeline/src/advisor/model/weekly.py`
- Test: `pipeline/tests/integration/test_model_weekly_job.py` (append)

**Interfaces:**
- **Consumes:** `repo.active_config` and `repo.start_benchmark_run`/`accept_config` (Task 5, test setup); `ModelConfig`, `BASELINE`, `run_variant`, `fit_variant` (Task 1).
- **Produces:**
  - **`config_for(conn, market: Market) -> tuple[ModelConfig, str]`:**
    - with no row: `(BASELINE, "no accepted configuration yet: baseline")`;
    - with an unusable row: `(BASELINE, f"accepted configuration #{id} can't be used ({error}): baseline")`;
    - otherwise: `(config, f"accepted configuration #{id} ({config.name})")`.
  - **`_train_market`** uses `run_variant`/`fit_variant` with that config. It adds `"config": config.to_json()` to the stored model's metrics, and `"config"` (the name) and `"config_reason"` to the market's report entry.

- [ ] **Step 1: Write the failing tests**

```python
def _accept(db, market, config):
    run_id = repo.start_benchmark_run(db, NOW, None)
    return repo.accept_config(db, market, config, "test", run_id, NOW)

def test_weekly_training_uses_the_baseline_until_a_config_is_accepted(db, tmp_path):
    write_market(tmp_path, Market.TSX, stocks=40)
    report = weekly.run(tmp_path, [Market.TSX], db, NOW, FAST)
    assert report["TSX"]["config"] == "baseline"
    assert report["TSX"]["config_reason"] == "no accepted configuration yet: baseline"
    assert repo.active_model(db, "stock_tsx").metrics["config"] == BASELINE.to_json()

def test_weekly_training_follows_the_accepted_config(db, tmp_path):
    write_market(tmp_path, Market.TSX, stocks=40)
    config_id = _accept(db, "TSX", BASELINE.to_json())
    report = weekly.run(tmp_path, [Market.TSX], db, NOW, FAST)
    assert report["TSX"]["config_reason"] == f"accepted configuration #{config_id} (baseline)"

def test_a_config_this_code_cannot_run_falls_back_to_the_baseline(db, tmp_path):
    write_market(tmp_path, Market.TSX, stocks=40)
    config_id = _accept(db, "TSX", {"version": 1, "factors": True, "garch": False, "policy": None})
    report = weekly.run(tmp_path, [Market.TSX], db, NOW, FAST)
    assert report["TSX"]["config"] == "baseline" and report["TSX"]["promoted"] is True
    assert report["TSX"]["config_reason"].startswith(f"accepted configuration #{config_id} can't be used (")
    assert "Plan 6c" in report["TSX"]["config_reason"]
```

- [ ] **Step 2: Run them and watch them fail**

Run: `scripts/in-docker.sh uv run pytest -q tests/integration/test_model_weekly_job.py`
Expected: the three new tests FAIL (`KeyError: 'config'`).

- [ ] **Step 3: Implement `config_for` and wire it into `_train_market`.** Read the config once, at the start of each market.

- [ ] **Step 4: Run the full suite and ruff**

Run: `scripts/in-docker.sh uv run pytest -q && scripts/in-docker.sh uv run ruff check .`
Expected: everything passes, and ruff prints `All checks passed!`.

- [ ] **Step 5: Commit**

```bash
git add pipeline/src/advisor/model/weekly.py pipeline/tests/integration/test_model_weekly_job.py
```
```bash
git commit -m "feat: weekly training follows the accepted configuration, falling back to the baseline"
```

---

### Task 9: The workflow and the docs

**Files:**
- Create: `.github/workflows/benchmark.yml`
- Test: `pipeline/tests/unit/test_benchmark_workflow.py`
- Modify:
  - `README.md` (the workflows list; the upgrade note for `0010`);
  - `docs/superpowers/specs/2026-10-09-stock-advisor-design.md` (the revision line and §5.2/§6.6 cross-references);
  - `docs/superpowers/specs/2026-10-28-prediction-upgrade-design.md` (the status line).

**Interfaces:**
- **Consumes:** `python -m advisor.benchmark.job --data DIR --out DIR` (Task 7), and `train.yml`'s build step, copied verbatim.
- **The workflow,** following `train.yml`'s structure, pinned actions and `working-directory: pipeline`:
  - **Triggers:** `schedule: cron: "0 9 * * 0"` (every Sunday at 09:00 UTC, the day after `train.yml`) and `workflow_dispatch`.
  - **Basics:** `permissions: contents: read`; `concurrency: group: benchmark, cancel-in-progress: false`; `timeout-minutes: 330`.
  - **The first step, `id: due`,** writes `run=true` to `$GITHUB_OUTPUT` when the event is `workflow_dispatch`, or when `date -u +%-d` is ≤ 7. Every later step has `if: steps.due.outputs.run == 'true'`.
  - **Then:**
    - checkout;
    - setup-uv;
    - `uv sync --locked --no-dev`;
    - the build step from `train.yml`, with the same env;
    - `uv run python -m advisor.benchmark.job --data "$RUNNER_TEMP/training" --out "$RUNNER_TEMP/benchmark"`, with `DATABASE_URL`;
    - `actions/upload-artifact@v4`, which has `if: always() && steps.due.outputs.run == 'true'`, the name `benchmark-report`, the paths `benchmark/benchmark-report.md`, `benchmark/benchmark-report.json` and `training/manifest.json` under `runner.temp`, `retention-days: 90` and `if-no-files-found: ignore`.
  - **The header comment** says what it does, that it runs monthly on the first Sunday or on demand, and that weekly training only reads what it accepts.

- [ ] **Step 1: Write the failing test**

```python
WORKFLOW = Path(__file__).parents[3] / ".github" / "workflows" / "benchmark.yml"

def test_the_benchmark_runs_on_the_first_sunday_only_or_on_demand():
    text = WORKFLOW.read_text()
    (cron,) = re.findall(r'cron: "([^"]+)"', text)
    _, _, day_of_month, _, day_of_week = cron.split()
    # GitHub ORs a restricted day-of-month with a restricted day-of-week: restrict only the weekday
    assert day_of_month == "*" and day_of_week == "0"
    assert "date -u +%-d" in text and "workflow_dispatch" in text
    assert text.count("steps.due.outputs.run == 'true'") >= 5
    assert "ADMIN_DATABASE_URL" not in text
```

- [ ] **Step 2: Run it and watch it fail**

Run: `scripts/in-docker.sh uv run pytest -q tests/unit/test_benchmark_workflow.py`
Expected: FAIL (`FileNotFoundError`).

- [ ] **Step 3: Write `benchmark.yml` and the docs**

- **README:**
  - add `train.yml` (weekly training) and `benchmark.yml` (monthly benchmark) to the workflows line;
  - extend the upgrade note: "`0010` for Plan 6a; apply it before the next `train.yml` or `benchmark.yml` run".
- **The main spec's revision history:**
  - add `- **Prediction upgrade (2026-10-28):** owner-approved design in docs/superpowers/specs/2026-10-28-prediction-upgrade-design.md — an evaluation harness, a crypto model, factor-adjusted targets, GARCH volatility and a tuned policy, each accepted only on held-out evidence (§5.2, §6.6). Plan 6a builds the harness.`;
  - add one line under §5.2 and one under §6.6, each pointing to that design's §1.
- **The design doc's status line:** `**Status:** approved by the owner 2026-10-28. Plan 6a builds §1; §2–§5 are future design until their plans land.`

- [ ] **Step 4: Run the full suite and ruff**

Run: `scripts/in-docker.sh uv run pytest -q && scripts/in-docker.sh uv run ruff check .`
Expected: everything passes.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/benchmark.yml pipeline/tests/unit/test_benchmark_workflow.py README.md docs/superpowers/specs/2026-10-09-stock-advisor-design.md docs/superpowers/specs/2026-10-28-prediction-upgrade-design.md
```
```bash
git commit -m "feat: run the benchmark monthly and on demand; document Plan 6a"
```

---

## After merging (the owner's steps, in order)

1. **Apply migration 0010 to the hosted database** with `python -m advisor.store.migrate`, as in the README, before the next Saturday `train.yml`. Weekly training reads `accepted_configs` and fails without it.
2. Push `main`.
3. **Run the benchmark:** Actions → `benchmark` → Run workflow. It takes about 20–30 minutes for the build, plus about 11 minutes of benchmark.
4. **Paste the `benchmark-report.md` artifact.** This is the **baseline benchmark report**. Its numbers become the reference that Plans 6b–6e must beat.
