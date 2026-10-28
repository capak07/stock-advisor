# Plan 6c: The TSX Basis Note and the Factor-Adjusted Target — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:**
1. A TSX forecast says it rests on price and sector only, with no company filings, wherever its P(beat) is shown with a Buy or a pick.
2. A `factors` model variant trains the range boosters on the stock-specific (factor-adjusted) return, so a stock isn't rewarded for riding a size, value, profitability or momentum rally. It goes live only if the benchmark accepts it.

**Spec:** `docs/superpowers/specs/2026-10-28-prediction-upgrade-design.md`, §3 and builder-check decisions 1 and 4. The harness, `ModelConfig(factors=True)`, `run_variant` and the benchmark exist from Plans 6a, 6e and 6b.

## Global Constraints

- **Tests in Docker,** from `pipeline/`: `scripts/in-docker.sh uv run pytest -q`; `scripts/in-docker.sh uv run ruff check .`; and `npm test` / `npx playwright test` in `web/` for Task 1.
- **Don't run two suites at once.** They share the test database, and one dropping its schema breaks the other.
- **Run `git commit` in its own command, never with `--no-verify`.** No `Co-Authored-By` line. Don't push or merge.
- **Point in time.** Nothing computed for day t may change when data dated after t changes, and nothing fitted for a fold may change when that fold's test targets change. Every task that computes factors, betas or μ has a perturbation test for this.
- **Exact copy for the TSX note:** `Price and sector only: TSX stocks have no company filings in this model, so weigh this call accordingly.`

## Decisions this plan makes (the design left them to the builder)

- **The beat booster gets betas, not the alpha forecast.** It still learns `y_h > 0` and is calibrated as now. Its features gain the stock's betas, but not the alpha forecast: feeding it that forecast would need a second, nested out-of-sample layer to avoid leakage.
- **Factor portfolios are re-formed every second sample day** (every 20 sessions), not every 21. Each one is formed from the characteristic on that day and holds from the next session.
- **Ridge λ is fixed:** `RIDGE_SHARE = 0.1`, applied as `λ = RIDGE_SHARE × trace(XᵀX) / k`.
- **A beta needs at least 126 days** with both returns. Otherwise the betas are NaN, the stock's target falls back to `y_h`, and its range shift is 0.
- **Factor returns over h sessions are summed daily returns** (`F_k,h(t) = Σ_{s=t+1..t+h} f_k(s)`).

---

### Task 1: The TSX basis note

**Files:** `pipeline/src/advisor/recommend/verdicts.py`, `pipeline/src/advisor/recommend/stage.py` (the pick details), the web pick card, watchlist verdict and Ticker page components that show a stock's reasons and details, and their tests.

**Interfaces:**
- **`TSX_BASIS`** holds the exact copy above.
- **For a TSX stock (`market_of(symbol) is Market.TSX`)** that gets a Buy verdict or is a pick, `TSX_BASIS` is appended as the last reason, and the pick details gain `"basis": TSX_BASIS`. US stocks and coins are unchanged.
- **The web** shows `basis`, where present, as a muted line under the pick's P(beat) on Today's Picks and on the Ticker page's forecast. The watchlist verdict shows its reasons as today, so the note appears with them.

- [ ] **Tests:**
  - pipeline: a TSX Buy verdict's last reason is `TSX_BASIS`; a US Buy's isn't; a TSX pick's details carry `basis`;
  - web unit: the pick card renders `basis` when present and nothing when absent;
  - Playwright: a seeded TSX pick shows the note, and a US pick doesn't.
  
  Each fails first, then passes.
- [ ] **Commit:** `feat: a TSX forecast says it rests on price and sector only`.

---

### Task 2: Point-in-time factor returns

**Files:** Create `pipeline/src/advisor/model/factors.py`; test `pipeline/tests/unit/test_model_factors.py`.

**Interfaces:**
- **`FACTORS`**, with its characteristics (each known on its day; higher means the "long" third):

  | Market | Factors and characteristics |
  |---|---|
  | US | `mkt` (the benchmark's daily return); `size` (−`log_mcap`, so small is long); `value` (the mean of the cross-sectional percentile ranks of `earnings_yield` and `sales_yield`); `prof` (`op_margin`); `mom` (`mom_12_1`) |
  | TSX | `mkt`; `mom` |
  | `"crypto"` | `mkt` (BTC's daily return); `size` (−30-day mean dollar volume); `mom` (`ret_21` over 28 days: use `close / close.shift(28) − 1`) |

- **`factor_returns(close: pd.DataFrame, characteristics: Mapping[str, pd.DataFrame], universe: pd.DataFrame, benchmark: str, form_days: pd.DatetimeIndex) -> pd.DataFrame`:**
  - returns daily factor returns indexed by the calendar, one column per factor;
  - **formation:** on each formation day d, rank the universe members with a characteristic. The equal-weight daily return of the top third minus the bottom third holds from the session after d up to and including the next formation day;
  - `mkt` is the benchmark's daily return;
  - **missing values:** before the first formation, and on days with fewer than 30 ranked names, the value is NaN.
- **`form_days(sample_days) = sample_days[::2]`.**

- [ ] **Tests:**
  - hand-built 9-stock example: the top-minus-bottom return on the day after formation matches a hand value;
  - **point in time:** changing any close or characteristic dated after day t leaves every factor return dated ≤ t identical, and changing a characteristic dated on formation day d changes nothing before d + 1 session;
  - fewer than 30 names gives NaN;
  - TSX has exactly `mkt` and `mom`.
- [ ] **Commit:** `feat: point-in-time factor returns per market`.

---

### Task 3: Rolling betas and the factor-adjusted target

**Files:** `pipeline/src/advisor/model/factors.py`; `pipeline/src/advisor/model/dataset.py` and `model/crypto.py` (attach the frames); test file as above.

**Interfaces:**
- **`rolling_betas(excess: pd.DataFrame, factors: pd.DataFrame, days: pd.DatetimeIndex, window: int = 252, min_days: int = 126) -> dict[str, pd.DataFrame]`:**
  - for each row day t, the ridge β of each stock's daily excess return (stock − benchmark) on the factor returns over the `window` sessions ending the session **before** t;
  - one frame per factor, `days × symbols`;
  - NaN with fewer than `min_days` complete days.
- **`forward_factor_sums(factors, horizons) -> dict[int, pd.DataFrame]`:** `F_k,h(t)` as defined in the decisions above.
- **`MarketData` gains `factors: FactorFrames | None = None`.** It holds:
  - `names`;
  - `beta_columns` (`beta_<name>`, added to `rows`);
  - `forward` (per horizon, a column per factor named `f_<name>_<h>`, added to `rows`);
  - `daily` (the factor returns, for storage).
  
  `load_market` and `load_crypto` fill it only when asked: `with_factors=True`.
- **`alpha_target(rows, h, names) -> pd.Series`:** `y_h − Σ beta_k · f_k_h`, falling back to `y_h` where any beta is NaN.

- [ ] **Tests:**
  - ridge β recovers known betas (within 0.05) on synthetic returns built as `0.8·f1 − 0.5·f2 + noise`;
  - **point in time:** changing returns dated t or later leaves the β for row day t identical;
  - the fallback gives `alpha == y` when a beta is NaN, and the count of fallbacks is reported;
  - `load_market(..., with_factors=True)` adds the beta and forward columns without changing any existing column.
- [ ] **Commit:** `feat: rolling ridge betas and the factor-adjusted target`.

---

### Task 4: The `factors` variant: train on alpha, rebuild ranges in excess terms

**Files:** `pipeline/src/advisor/model/train.py`, `model/variants.py`, `model/weekly.py`, `model/live.py`/`model/market_run.py` (the live range shift), `benchmark/job.py` (load with factors when a factors variant runs); tests in `test_model_train.py`, `test_model_variants.py`, `tests/integration/test_benchmark_job.py`.

**Interfaces:**
- **`walk_forward(..., factor_names: Sequence[str] | None = None)`.** When given:
  - the three quantile boosters train on `alpha_target` instead of `y_h`;
  - the beat booster still trains on `y_h > 0`;
  - every booster's features gain the `beta_*` columns;
  - test predictions are shifted: `q_y = q_alpha + Σ beta_k · μ_k,h`, where `μ_k,h` is the mean of `f_k_h` over **that fold's training rows**, and the shift is 0 where a beta is NaN;
  - the predictions gain `q50_alpha` (before the shift) and `alpha` (realised), for a diagnostic rank IC.
- **`fit_final` does the same over all rows.** `FinalModel` gains `factor_names`, `mu` (per horizon and factor) and `betas` (symbol → latest beta per factor, from the last row day). `to_files`/`from_files` store them as `factors` JSON.
- **`unbuilt` no longer names Plan 6c.** `run_variant` and `fit_variant` pass `factor_names` when `config.factors`.
- **Live:** `FinalModel.predict` adds a stock's beta features from `betas`, and shifts its quantiles by `Σ beta·μ`. A symbol missing from `betas` gets NaN betas and no shift.
- **The benchmark** loads data `with_factors=True` once per market. The baseline's rows and keys are unchanged.
- **The report:** for the factors row, add the diagnostic `rank IC of q50_alpha vs alpha` and the fallback count. For US, also show the correlation of our `size`, `value`, `prof` and `mom` daily returns with Kenneth French's daily factors (`https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_5_Factors_2x3_daily_CSV.zip`, and the momentum file). Fetch it keyless, never use it in training, and show "cross-check unavailable" on any failure.

- [ ] **Tests:**
  - a factors walk-forward on synthetic data where one stock's whole excess return is `1.0 × mom` gives that stock `q50_alpha` near 0, and a `q50` that still includes `β·μ`;
  - **leakage:** μ, the boosters' predictions and the calibrators for fold k are identical when fold k's test-period targets and forward factor sums are changed;
  - the final model's files round-trip with `factors`;
  - live `predict` shifts a known symbol and leaves an unknown symbol unshifted;
  - a benchmark run on synthetic US data runs the `factors` row (status `run`) and keeps the baseline's keys equal.
- [ ] **Commit:** `feat: the factors variant trains on the stock-specific return and keeps P(beat) meaning the same`.

---

### Task 5: Docs

- **The design doc's status:** Plan 6c is built.
- **The main spec's revision line:** "Plan 6c (2026-10-29): factor-adjusted training target (accepted only by the benchmark); TSX forecasts say they are price and sector only".
- **Commit:** `docs: Plan 6c`.

## After merging (the owner)

Push, then run **benchmark**. The `factors` and `factors+garch` rows report; `factors+garch` still waits for Plan 6d. Factors goes live only if it beats the baseline under the 6a rules. Then the policy is re-tuned on top of it, and the next `train.yml` trains it.
