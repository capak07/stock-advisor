# Plan 6d: GARCH Volatility — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `garch` model part, so the benchmark's `garch` and `factors+garch` rows run and are judged. Weekly training then follows GARCH only if the benchmark accepts it.

**Architecture:**
- A new pure module, `model/garch.py`, fits GARCH(1,1) with Student-t errors per asset. It turns fixed parameters into a point-in-time volatility forecast per horizon.
- The walk-forward fits parameters per asset per fold, on returns before the fold starts, and gives each horizon's boosters one extra column, `garch_vol`.
- The final model stores its per-asset parameters, so the live run computes the same column from its price window.
- A range adjustment blends the model's range with `q50 ± s · garch_vol_h`, when earlier periods show it helps.
- With `garch` off, nothing moves.

**Tech Stack:** Python 3.12, pandas, numpy, `arch` (BSD, pinned), LightGBM, pytest in Docker.

**Spec:** `docs/superpowers/specs/2026-10-28-prediction-upgrade-design.md`. Read §4 (GARCH), §6 (fallbacks), §7 (determinism and leakage tests) and decision 4 (the leakage tests' wording).

**Who builds what:**
- **Cursor:** Tasks 1 and 6. The task file is `2026-11-04-plan-6d-cursor-task.md`.
- **Claude:** Tasks 2–5, which build on Task 1.

## Global Constraints

- **Tests in Docker,** from the repo root: `pipeline/scripts/in-docker.sh uv run pytest -q` and `pipeline/scripts/in-docker.sh uv run ruff check .`. Start Docker Desktop and `docker start advisor-pg` if they're down.
- **Don't run two suites at once:** they share the test database.
- **Commits:** run `git commit` in its own command, never with `--no-verify`. Use one commit per task, with the message the task gives. Don't push.
- **Don't change the pick gate:** don't lower `DEFAULT_POLICY.p_buy` or the 30-pick rule, don't set `picks_enabled` by hand, and don't write accepted configs to the production database.
- **The baseline must not move:** with `garch` off, every prediction, metric and stored file is what it is today. That covers baseline, ranker, extras and bagged.
- **Point in time:** a GARCH value on day t uses only returns dated t or earlier. A fold's parameters use only returns dated before the fold starts.
- **Never fail the run over GARCH:** an asset with fewer than 500 returns, a failed fit, or a non-stationary fit gets NaN. LightGBM handles NaN. The asset is never dropped, and it is counted.
- **Exact values (spec §4 ★, and this plan's fixed constants):**
  - **Model:** GARCH(1,1), constant mean, Student-t errors, fitted with `arch` on 100 × daily log returns, with `rescale=False`.
  - **Starting values,** fixed, in percent units (mu, omega, alpha, beta, nu): `(0.05, 0.05, 0.08, 0.90, 8.0)`.
  - **`GARCH_MIN_RETURNS = 500`.**
  - **`FIT_WINDOW = 2520`:** a fit uses at most the asset's last 2,520 finite returns before the cut-off, about 10 years.
  - **`FILTER_WINDOW = 250`:** a day's variance is filtered over the 250 returns ending that day, starting from the unconditional variance. Sessions for stocks, days for coins.
  - **The feature:** `garch_vol_h = sqrt(Σ_{k=1..h} E[σ²_{t+k}])`, in decimal return units, not annualised.
  - **Range blend:** q10′ = ½(q10 + q50 − s·g) and q90′ = ½(q90 + q50 + s·g), where g = `garch_vol_h`. `s` is searched on a fixed grid, 0.25 to 3.00 in steps of 0.05, for q10–q90 coverage closest to 80%.

## Decisions this plan makes where the spec leaves room

1. **Parameters per fold** are fitted on the asset's returns dated before the fold's start, at most the last 2,520. Returns just before the start are known before the test period. Only test-period outcomes are off limits, and the leakage test pins that.
2. **A fixed 250-return filter window, started at the unconditional variance.** The live run loads about 275 sessions (`LIVE_WINDOW`, 400 days), so a full-history filter couldn't be reproduced live. With a fixed window, training and live give the same value on the same day, to rounding.
3. **One column per horizon:** horizon h's boosters train on `garch_vol` = `garch_vol_h`, not on every horizon's value.
4. **A return missing inside the window** (a halt, or a gap in the bars) makes that day's value NaN.
5. **The range adjustment's "inner folds"** are the earlier periods' out-of-sample predictions whose outcomes ended before each period began. That's the same evidence today's range calibration uses (`calibrate_ranges`), and it avoids nested walk-forwards for one scale.
   - A period uses the blend only if, on that evidence, the blend's coverage error is smaller than the range's.
   - The final model uses it only if it was smaller over all calibrated periods.
   - Probability calibration doesn't depend on the range, so the spec's "calibration stays ≤ 5" is the acceptance rule's own check.
6. **Not in this plan (owner note):** the follow-up plan, named here so it isn't silently dropped, should take these two items:
   - **Replacing `vol_60` with `garch_vol_21` in the risk score** (`recommend/risk.py`). It needs its own evidence rule on realised drawdowns and its own report section.
   - **GARCH as an alternative stop distance** in the policy search. The policy search (`benchmark/policy_search.py`) has no stop-distance hook today; its grid is ATR multipliers only.

   Stops stay ATR-based in this plan.

## Review Focus

1. **Turning `garch` off must change nothing:** baseline, ranker, extras or bagged predictions, metrics or stored files. Tested in Task 2 (`test_walk_forward_without_garch_is_unchanged`) and Task 3 (`test_a_model_without_garch_has_no_garch_file`).
2. **A fold's GARCH parameters must not move when that fold's test-period targets change** (spec decision 4). Tested in Task 2 (`test_garch_parameters_ignore_the_folds_own_outcomes`).
3. **A live value must equal the training value on the same day.** A mismatch would make the live model see a different feature than it learned. Tested in Task 4 (`test_live_garch_matches_training_on_the_same_day`).
4. **A degenerate series must give NaN, not an exception:** constant prices, fewer than 500 returns, NaN gaps. Tested in Task 1.
5. **Stored configs and models from before this plan must load as before.** Version 3 configs with `garch: false` load, and models without a `garch` file predict as today. Tested in Task 3.

---

### Task 1 (Cursor): the `arch` dependency and the pure GARCH module

**Files:**
- Modify: `pipeline/pyproject.toml`, adding `"arch==7.2.0"` to `dependencies`, and `pipeline/uv.lock`. Run plain `uv lock` from `pipeline/` on the host, because `in-docker.sh` runs `uv sync --locked` first and fails until the lock matches.
- Create: `pipeline/src/advisor/model/garch.py`
- Test: `pipeline/tests/unit/test_model_garch.py`

**Interfaces (Produces):**
- Constants: `GARCH_MIN_RETURNS = 500`, `FIT_WINDOW = 2520`, `FILTER_WINDOW = 250`, `STARTING_VALUES = (0.05, 0.05, 0.08, 0.90, 8.0)`.
- `@dataclass(frozen=True) class GarchParams`:
  - fields `mu, omega, alpha, beta, nu: float`, in decimal return units (`mu` = fitted mu / 100, `omega` = fitted omega / 10,000);
  - `unconditional -> float` (property): `omega / (1 - alpha - beta)`;
  - `to_json() -> list[float]`, which is `[mu, omega, alpha, beta, nu]`;
  - `from_json(v) -> GarchParams` (classmethod).
- The module imports `from arch import arch_model` at module level, because the tests patch `advisor.model.garch.arch_model`.
- `fit_params(returns: pd.Series) -> GarchParams | None`:
  - Drop NaN and keep the last `FIT_WINDOW` values. With fewer than `GARCH_MIN_RETURNS`, or with every value equal, return None without calling `arch_model`.
  - Fit `arch_model(100 * r, mean="Constant", vol="GARCH", p=1, q=1, dist="t", rescale=False).fit(disp="off", show_warning=False, starting_values=np.array(STARTING_VALUES))`.
  - Read the fit's parameters by name from `result.params`: `mu`, `omega`, `alpha[1]`, `beta[1]`, `nu`.
  - Return None if any of these is true: an exception was raised; `result.convergence_flag != 0`; a parameter is non-finite; `omega <= 0`; `alpha < 0`; `beta < 0`; `alpha + beta >= 1`.
- `fit_all(returns: pd.DataFrame, before: pd.Timestamp, symbols: Iterable[str]) -> dict[str, GarchParams | None]`:
  - For each symbol in sorted order, fit on `returns.loc[returns.index < before, symbol]`.
  - A symbol not in `returns.columns` gets None.
- `garch_vol(returns: pd.Series, params: GarchParams | None, horizons: Sequence[int]) -> pd.DataFrame`:
  - Indexed like `returns`, with columns `garch_vol_{h}`.
  - With φ = α + β, σ̄² = `params.unconditional` and ε = r − μ: start at σ̄² for the first return of the window, run σ²₊₁ = ω + α ε² + β σ² through the 250 returns ending at day t, then take Σₖ₌₁..ₕ E[σ²ₜ₊ₖ] = h σ̄² + (σ²ₜ₊₁ − σ̄²)(1 − φʰ)/(1 − φ), and its square root.
  - NaN when `params` is None, or when any of the 250 returns is NaN, or there are fewer than 250 returns.
  - Vectorise it, for example with a convolution of ε² with the kernel βʲ (j = 0..249). It must equal the explicit loop.

- [ ] **Step 1: Write the failing tests** in `test_model_garch.py`. Use a helper `simulate(n, omega=0.02, alpha=0.08, beta=0.90, nu=6.0, mu=0.03, seed=1)`. It returns a `pd.Series` of decimal log returns on `pd.bdate_range("2010-01-04", periods=n)`. Build it in percent units with `rng = numpy.random.default_rng(seed)`:
  - σ² starts at ω/(1−α−β);
  - for each day: `z = rng.standard_t(nu) * sqrt((nu - 2) / nu)`, then `r = mu + sqrt(σ²) * z`, then `σ² = ω + α (r − mu)² + β σ²`;
  - return the r values divided by 100.

  If the recovery test misses its tolerance with seed 1, stop and report it. Don't change the seed or loosen the tolerance. Import the module as `from advisor.model import garch`, along with its names.

```python
def test_a_fit_recovers_the_parameters_it_was_simulated_with():
    p = fit_params(simulate(3000))
    assert p is not None
    assert p.alpha == pytest.approx(0.08, abs=0.04) and p.beta == pytest.approx(0.90, abs=0.05)
    assert p.alpha + p.beta < 1 and p.omega > 0


def test_under_500_returns_gives_no_fit_and_never_calls_arch(monkeypatch):
    calls = []
    real = garch.arch_model
    monkeypatch.setattr(garch, "arch_model", lambda y, *a, **k: calls.append(len(y)) or real(y, *a, **k))
    r = simulate(700)
    assert fit_params(r.iloc[:499]) is None and calls == []
    fit_params(r.iloc[:500])
    assert calls == [500]
    nan_tail = pd.concat([r.iloc[:499], pd.Series(np.nan, index=r.index[499:])])
    assert fit_params(nan_tail) is None and calls == [500]  # NaNs don't count


def test_a_degenerate_series_gives_none_not_an_error():
    flat = pd.Series(0.0, index=pd.bdate_range("2010-01-04", periods=800))
    assert fit_params(flat) is None


def test_a_non_stationary_fit_is_refused(monkeypatch):
    class Result:
        convergence_flag = 0
        params = pd.Series({"mu": 0.05, "omega": 0.05, "alpha[1]": 0.20, "beta[1]": 0.85, "nu": 6.0})

    class Model:
        def fit(self, *a, **k):
            return Result()

    monkeypatch.setattr(garch, "arch_model", lambda *a, **k: Model())
    assert fit_params(simulate(800)) is None  # alpha + beta = 1.05


def test_a_fit_is_deterministic():
    assert fit_params(simulate(1500)) == fit_params(simulate(1500))


def test_only_the_last_2520_returns_are_fitted():
    r = simulate(3000)
    changed = r.copy()
    changed.iloc[0] = 0.5  # older than the last 2,520
    assert fit_params(changed) == fit_params(r)


def test_fit_all_uses_only_returns_before_the_cut_off():
    r = pd.DataFrame({"A": simulate(1500, seed=2), "B": simulate(1500, seed=3)})
    cut = r.index[1200]
    later = r.copy()
    later.loc[later.index >= cut] = 0.3
    assert fit_all(later, cut, ["A", "B", "ZZZ"]) == fit_all(r, cut, ["A", "B", "ZZZ"])
    assert fit_all(r, cut, ["ZZZ"]) == {"ZZZ": None}


def test_garch_vol_equals_the_explicit_recursion():
    r = simulate(600)
    p = GarchParams(mu=0.0003, omega=2e-6, alpha=0.08, beta=0.90, nu=6.0)
    out = garch_vol(r, p, (1, 21))
    t = 400
    window = r.iloc[t - 249: t + 1].to_numpy()
    s2 = p.unconditional
    for x in window:
        s2 = p.omega + p.alpha * (x - p.mu) ** 2 + p.beta * s2
    phi = p.alpha + p.beta
    total = 21 * p.unconditional + (s2 - p.unconditional) * (1 - phi**21) / (1 - phi)
    assert out["garch_vol_1"].iloc[t] == pytest.approx(np.sqrt(s2), rel=1e-9)
    assert out["garch_vol_21"].iloc[t] == pytest.approx(np.sqrt(total), rel=1e-9)
    assert out["garch_vol_1"].iloc[:249].isna().all() and out["garch_vol_1"].iloc[249:].notna().all()


def test_garch_vol_on_a_day_ignores_later_returns():
    r = simulate(600)
    p = GarchParams(mu=0.0, omega=2e-6, alpha=0.08, beta=0.90, nu=6.0)
    later = r.copy()
    later.iloc[401:] = 0.4
    pd.testing.assert_frame_equal(garch_vol(later, p, (5,)).iloc[:401], garch_vol(r, p, (5,)).iloc[:401])


def test_a_missing_return_blanks_only_the_windows_that_hold_it():
    r = simulate(700)
    r.iloc[300] = np.nan
    out = garch_vol(r, GarchParams(0.0, 2e-6, 0.08, 0.90, 6.0), (5,))["garch_vol_5"]
    assert out.iloc[300:550].isna().all()
    assert pd.notna(out.iloc[299]) and out.iloc[550:].notna().all()


def test_no_parameters_give_nan():
    assert garch_vol(simulate(300), None, (5, 10)).isna().all().all()


def test_parameters_round_trip_through_json():
    p = GarchParams(0.0003, 2e-6, 0.08, 0.90, 6.0)
    assert GarchParams.from_json(p.to_json()) == p
```

- [ ] **Step 2: Run them and watch them fail.** Run `pipeline/scripts/in-docker.sh uv run pytest -q tests/unit/test_model_garch.py`. Expected: an ImportError for `advisor.model.garch`.
- [ ] **Step 3: Add the dependency and implement the module.** Give the module a docstring citing spec §4 and the fixed-window decision.
- [ ] **Step 4: Run the file, the full suite and ruff.** Expected: all pass.
- [ ] **Step 5: Commit:** `feat: a point-in-time GARCH(1,1) volatility forecast per asset, fitted with arch`

---

### Task 2 (Claude): returns in the data, and per-fold GARCH in the walk-forward

**Files:**
- `model/dataset.py`: `MarketData` gains `returns: pd.DataFrame | None = None`, the calendar × symbol daily log returns of the close. It also gains `garch_cache: dict = field(default_factory=dict, compare=False, repr=False)`, which maps a fold start to its fitted parameters, so the `garch` and `factors+garch` rows and the inner folds fit once. `load_market(..., with_garch=False)` fills `returns` when asked.
- `model/crypto.py`: `load_crypto(..., with_garch=False)` does the same on the coins' daily calendar.
- `model/train.py`:
  - `walk_forward(..., garch: bool = False)`. Per fold, it fits `fit_all(returns, fold.start, symbols in that fold's train ∪ test rows)`, cached.
  - Per horizon, it adds `garch_vol` (that horizon's `garch_vol_h` at each row's day and symbol) to the train and test frames, and to the feature list after the extras.
  - `WalkForward.garch_fallbacks: int`: the symbols with no parameters, summed over the folds.
- Tests: `tests/unit/test_model_train_garch.py`

**Interfaces:**
- Consumes: Task 1's `fit_all`, `garch_vol` and `GarchParams`.
- Produces:
  - `walk_forward(data, config, ..., garch=False)`;
  - `WalkForward.garch_fallbacks`;
  - `MarketData.returns`;
  - `load_market(..., with_garch)` and `load_crypto(..., with_garch)`.

**Tests:**
- `test_walk_forward_without_garch_is_unchanged`: predictions and metrics equal the default call's.
- `test_garch_adds_one_column_per_horizon`
- `test_garch_parameters_ignore_the_folds_own_outcomes`: change the fold's test targets, and the parameters and the training rows' `garch_vol` stay byte-identical.
- `test_a_symbol_without_enough_returns_is_counted_not_dropped`
- `test_needs_returns`: `garch=True` without `returns` raises a ValueError naming `with_garch=True`.
- **A timing measurement on the quarter of US stocks,** recorded in the commit body: fits per second, and walk-forward seconds with and without GARCH.

**Commit:** `feat: the walk-forward fits GARCH per asset per fold and trains each horizon on its forecast volatility`

---

### Task 3 (Claude): final model, variants, weekly training and the benchmark rows

**Files:**
- `model/train.py`:
  - `fit_final(..., garch=False)` fits `fit_all(returns, end_of_data + 1 day, symbols)` and stores it as `FinalModel.garch: dict[str, GarchParams | None] | None`.
  - `to_files`/`from_files` write and read a `garch` file (gzipped JSON, symbol → list or null) only when it's present.
  - `FinalModel.predict(x)` reads `garch_vol_{h}` columns from `x` for a garch model.
- `model/variants.py`:
  - `unbuilt()` returns None for GARCH;
  - `run_variant`/`fit_variant` pass `garch`;
  - the module docstring is updated.
- `model/weekly.py`: load with `with_garch=model_config.garch`.
- `benchmark/job.py`:
  - load with `with_garch=True`;
  - store `variants[name]["garch"] = {"fallbacks": wf.garch_fallbacks, "range": ...}` (the range part is from Task 5) for garch rows.

**Tests:**
- `test_a_garch_model_round_trips_through_its_files`
- `test_a_model_without_garch_has_no_garch_file`
- `test_a_version_3_config_with_garch_now_loads`
- `test_the_benchmark_runs_the_garch_rows`: `status` is `run`, not "arrives with Plan 6d".

**Commit:** `feat: garch models train, save, load and run in the benchmark and weekly training`

---

### Task 4 (Claude): the live paths

**Files:**
- `model/garch.py` gains `live_garch_vol(closes: pd.DataFrame, params: Mapping[str, GarchParams | None], horizons) -> pd.DataFrame`. It takes the live price window's closes on the market calendar and gives symbol × `garch_vol_{h}` on the window's last day.
- `model/market_run.py` and the crypto live path: when the active model has `garch`, attach those columns before `predict`.

**Tests:**
- `test_live_garch_matches_training_on_the_same_day`: same data, same parameters, and the live value equals `load_market`'s at the sample day to rel 1e-9.
- `test_a_symbol_the_model_has_no_parameters_for_gets_nan`

**Commit:** `feat: live stock and coin runs compute GARCH volatility with the model's own parameters`

---

### Task 5 (Claude): the range adjustment

**Files:**
- `model/train.py`, after `calibrate_ranges` in `walk_forward`, for garch runs:
  - Per horizon and period, fit `s` on the grid using the earlier periods' predictions whose outcomes had ended (decision 5).
  - Apply the blend only if it lowers |coverage − 0.80| on that evidence.
  - Record `info["garch_range"] = {"s": {period: s}, "used": {period: bool}, "adopted": bool}`.
- `fit_final` stores the per-horizon `s` it adopted, and `FinalModel.predict` applies it.
- Tests: the blend formula; no adoption when it doesn't help; it never runs with `garch` off.

**Commit:** `feat: a GARCH range blend per horizon, used only where earlier periods show it tightens coverage toward 80%`

---

### Task 6 (Cursor): the GARCH lines in the benchmark report

**Files:**
- Modify: `pipeline/src/advisor/benchmark/report.py`, where each variant's diagnostics are rendered, next to the "Factor diagnostic" line.
- Test: `pipeline/tests/unit/test_benchmark_report.py`

**Interface (Consumes), the report dict contract Task 3 writes:** a garch variant's entry `report["markets"][m]["variants"][name]` may carry:

```python
"garch": {"fallbacks": 12, "range": {"5": {"s": 0.85, "adopted": True}, "21": {"s": None, "adopted": False}}}
```

**What to render:** under that variant's outer-fold table, one line:

`GARCH: 12 assets without a fit (under 500 returns, or no stable fit); range blend 5d s=0.85 (used), 21d not used.`

- Horizons appear in ascending numeric order.
- With `"range"` missing or empty, the line ends after the fallbacks: `GARCH: 12 assets without a fit (under 500 returns, or no stable fit).`
- Variants without a `"garch"` key render exactly as today.

- [ ] **Step 1: Write the failing tests.** Add them to `test_benchmark_report.py`, with `import copy`. Build the variant dict on a copy of the existing `REPORT` fixture, whose `TSX` market has a `baseline` variant that ran:

```python
def test_a_garch_variant_reports_its_fallbacks_and_range_blend():
    report = copy.deepcopy(REPORT)
    variant = report["markets"]["TSX"]["variants"]["baseline"]
    variant["garch"] = {"fallbacks": 12, "range": {"21": {"s": None, "adopted": False}, "5": {"s": 0.85, "adopted": True}}}
    md = render_markdown(report)
    assert "GARCH: 12 assets without a fit (under 500 returns, or no stable fit); range blend 5d s=0.85 (used), 21d not used." in md


def test_a_garch_variant_without_a_range_reports_only_its_fallbacks():
    report = copy.deepcopy(REPORT)
    variant = report["markets"]["TSX"]["variants"]["baseline"]
    variant["garch"] = {"fallbacks": 0}
    assert "GARCH: 0 assets without a fit (under 500 returns, or no stable fit)." in render_markdown(report)


def test_variants_without_garch_render_as_before():
    assert "GARCH:" not in render_markdown(REPORT)
```

- [ ] **Step 2: Watch them fail,** then implement, then run the file, the full suite and ruff.
- [ ] **Step 3: Commit:** `feat: the benchmark report names each GARCH row's fallbacks and range blend`
