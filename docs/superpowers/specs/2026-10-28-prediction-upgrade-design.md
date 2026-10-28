# Prediction upgrade: factor-adjusted targets, GARCH volatility, tuned policy — design

**Status:** draft for the owner's approval, 2026-10-28. Nothing here is built yet.

**Extends:** `docs/superpowers/specs/2026-10-09-stock-advisor-design.md` (§5 Prediction, §6 Recommendations). Once this design is approved, the main spec gets a revision line and §5/§6 cross-references (Plan 6a, Task 1).

## Why

The models predict a stock's return in excess of its benchmark. That target rewards a stock for simply carrying a factor:
- small caps in a small-cap rally;
- momentum names in a momentum run.

A factor rally can end on the day a pick is made, so this isn't skill the owner can bank.

The policy that turns forecasts into picks and actions also uses hand-set numbers:
- the 0.58 and 0.42 probability lines;
- stops at 2, 3 and 2.5 ATR;
- best-ratio horizon choice.

These have never been tuned against held-out data, after costs. This week's backtest qualified **0 picks** in both markets.

The owner wants three additions, each accepted only if held-out evidence says it helps:
1. **A factor-adjusted target:** the model learns the stock-specific part of a return.
2. **A GARCH volatility forecast:** used as a feature, and to adjust forecast ranges and risk.
3. **A constrained, walk-forward-tuned recommendation policy.**

A crypto model is to be built too (owner decision 2026-10-28), so all three markets have one.

## What exists today (implemented)

- **Models:** LightGBM per market, US and TSX only. Six horizons (5, 10, 20, 21, 63, 126 trading days), each with q10/q50/q90 quantile boosters and a binary "beat the benchmark" booster. Isotonic calibration is fitted only on earlier out-of-sample predictions (`pipeline/src/advisor/model/train.py`).
- **The target:** `y_h` is the forward h-session return minus the benchmark's (SPY or XIU.TO), from `forward_excess` in `model/features.py`.
- **Features:**
  - price, volume and momentum: `ret_*`, `mom_12_1`, `vol_20`, `vol_60`, `atr_14_pct`, …;
  - relative strength: benchmark and sector;
  - US fundamentals from SEC filings as filed, including `log_mcap`, `earnings_yield`, `sales_yield`, `op_margin`;
  - **TSX has no fundamentals, and macro is not a feature.**
- **Walk-forward:**
  - 4 equal test periods after 2 years of training;
  - the embargo per horizon equals the horizon (`training_rows`);
  - one stock-day every 10 sessions;
  - no hyperparameter or policy tuning, and no nested folds.
- **The gates:**
  - **Promotion:** worst usable horizon calibration ≤ 5 points, rank IC not worse than the active model's by more than 0.005, or the active model older than 28 days.
  - **Picks:** at least 30 backtest picks, a positive mean after costs, calibration ≤ 5 points, and claimed P within 5 points of the hit rate (`model/backtest.py`).
- **The policy:** the constants in `recommend/picks.py`, `recommend/verdicts.py`, `portfolio/actions.py` and `portfolio/stops.py`.
- **Training data:** about 8 years, rebuilt weekly by `train.yml`, for stocks listed today only.
- **Crypto:** no model. A watched coin's verdict is "no crypto model yet". The only crypto data stored is about a year of Coinbase closes for held and watched coins.

## Goals

1. **An evaluation harness** that every addition is judged by:
   - nested walk-forward, with inner folds for tuning and untouched outer folds for reporting;
   - a fixed ablation set per market;
   - a written benchmark report;
   - an "accepted configuration" per market that weekly training uses.
2. **A crypto model** with the same outputs as the stock models (q10/q50/q90 and calibrated P(beat benchmark)), trained on keyless history.
3. **Point-in-time factors** for each market, and a **factor-adjusted training target**.
4. **A GARCH(1,1) volatility forecast** per asset: used as a feature, and to adjust forecast ranges and the risk score.
5. **A constrained policy search** over probability thresholds, stop multipliers and the horizon rule, scored on risk-adjusted return net of every cost, with hard limits.
6. **Fallbacks:** whenever training or validation fails, the last accepted model and the current deterministic rules stay in use.

## Non-goals

- Reinforcement learning, or any unconstrained or online policy learning.
- Paid or authenticated data sources.
- Intraday models.
- New dashboard pages. The benchmark report is a file plus a database row; showing it is the Track Record page's job later.
- Changing ATR-based stops into another stop type. Only their multipliers are tuned, and only if the evidence supports it.

## Anti-goals (a failure even if it works)

- **Any leakage.** For example, an exposure, factor portfolio, GARCH fit, calibrator or policy value that saw data from its own test period.
- **An addition accepted on in-sample or inner-fold results,** or reported on the same data it was tuned on.
- **A policy that "wins" by trading too little** to measure, or by ignoring costs or stops.
- **Outputs that change meaning silently.** P(beat SPY) must still mean exactly that.

## Hard requirements (from the owner, 2026-10-28)

- **Models:** US, TSX and crypto models stay separate.
- **Point in time:** only data known before the feature day is used. No look-ahead or leakage, and survivorship is reduced as far as keyless data allows (see Known limits).
- **Everything is fitted inside each training fold:** preprocessing, factor estimation, calibration, GARCH and policy values.
- **Embargo:** a gap equal to each horizon is kept.
- **Outputs stay the same:** q10, q50, q90 and calibrated P(beat benchmark) per usable horizon.
- **Policy scoring includes every cost:** trading costs, the USD/CAD conversion fee, spreads and stop exits.
- **The objective:** risk-adjusted net return, with hard limits on turnover, drawdown, poor calibration and too few trades.
- **Tuning happens on inner folds; reporting only on untouched outer folds.**
- **Ablations, per market:**
  1. baseline;
  2. baseline + factors;
  3. baseline + GARCH;
  4. baseline + factors + GARCH;
  5. the full model + the optimized policy.
- **Acceptance:** an addition is rejected unless it improves held-out results, and calibration must stay within 5 points.
- **On any failure,** the last accepted model and the current deterministic rules are used.
- **The implementation is deterministic and testable.**

## Design

### 1. The evaluation harness (Plan 6a)

- **Outer folds:**
  - the current 4 equal test periods after 2 years (`make_folds`) are the outer folds;
  - nothing tuned may see an outer fold's rows.
  - The weekly training's own walk-forward stays as it is.
- **Inner folds:**
  - inside each outer fold's training span, 3 inner walk-forward splits (★) carry the same horizon embargo;
  - they're used to choose among variants and tune the policy.
- **Variants:**
  - **A variant** is a model configuration: features on or off, target raw or factor-adjusted, GARCH on or off, plus a policy (the defaults, or tuned).
  - **The five ablations** run per market on identical rows, folds and seeds.
- **Metrics, per outer fold and pooled:**
  - **Model:**
    - rank IC of q50 against the realised benchmark-excess return;
    - pinball loss of q10, q50 and q90;
    - q10–q90 coverage;
    - calibration of P (the existing 10-bin weighted gap and the worst bin).
  - **Policy:**
    - net return per trade, and the net daily return of an equal-weight book of open picks;
    - its Sharpe ratio (annualised, net);
    - maximum drawdown;
    - turnover (trades per month);
    - the number of separate trades;
    - hit rate, and claimed P against the realised beat rate.
- **Accepting an addition (per market and per addition, decided on outer folds only):**
  - **A model addition** (factors, GARCH or both) is accepted when all of these hold:
    - pooled outer rank IC improves on the baseline's;
    - pooled pinball loss is no worse (★ tolerance 0.5%);
    - calibration is ≤ 5 points at every usable horizon;
    - and rank IC improves in at least 3 of the 4 outer folds (★), so one lucky period can't carry it.
  - **The full model + optimized policy** is accepted when all of these hold:
    - its outer-fold net Sharpe beats the accepted model's with the default policy;
    - it meets every hard limit;
    - and its calibration is ≤ 5 points.
  - **Why model additions are judged on ranking and calibration, not trading returns:** today's default policy makes 0 trades, so trading returns can't separate model variants yet.
- **Storage (migration 0010):**
  - **`benchmark_runs`:** id, `started_at`, `finished_at`, status, `git_sha`, and the report as `jsonb`.
  - **`benchmark_results`:** run id, market, variant, outer fold (or "pooled") and metrics as `jsonb`.
  - **`accepted_configs`:** market, config as `jsonb` (feature flags, target, GARCH, policy values), `accepted_at`, benchmark run id, active.
  - **RLS:** the owner reads; the pipeline writes. These follow the tests in `test_schema.py`.
- **The workflow `benchmark.yml`:**
  - monthly (first Sunday) and manual, so the weekly budget isn't spent on it (owner decision 2026-10-28);
  - it writes the report as markdown and JSON to the run's artifacts and the database, and promotes newly accepted configurations;
  - the weekly `train.yml` trains only the active accepted configuration per market.
- **Fallback:** with no accepted configuration, or a failed benchmark, the current baseline configuration and the default policy are used (today's behaviour).

### 2. The crypto model (Plan 6b)

- **History:**
  - Coinbase daily candles (keyless, paged 300 a request) for every Coinbase USD product that ever traded, as far back as Coinbase serves, refreshed weekly in `train.yml`.
  - Coins quote in USD; values are shown in CAD at the Bank of Canada rate as today.
- **The universe on each day:** the top 100 (★) coins by trailing 30-day dollar volume on that day, among products trading then. This uses volume, not market cap, because CoinGecko's free history stops at 365 days.
- **The target:** the forward return in excess of **BTC** for altcoins, and of **SPY** for BTC itself (spec §5.4, unchanged).
- **Features:**
  - the stock price, volume and momentum set, minus stock-only ones (sector, fundamentals);
  - plus BTC-relative strength.

  On-chain and Fear & Greed features stay future design: there's no point-in-time keyless history for them.
- **Training, outputs and gates** are the same as the stock models. Crypto's round-trip cost is 2 × `crypto_fee_pct` (spec §3).
- **Live:** held and watched coins get forecasts, verdicts and holding actions from it. Coins never appear in pick lists (spec §5.4).

### 3. Point-in-time factors and the factor-adjusted target (Plan 6c)

- **Factors, built from each market's own universe** (owner decision 2026-10-28: our own, not Kenneth French's):

  | Market | Factors | Characteristic (known before the day) |
  |---|---|---|
  | US | market, size, value, profitability, momentum | benchmark return; `log_mcap`; `earnings_yield` + `sales_yield` rank average; `op_margin`; `mom_12_1` |
  | TSX | market, momentum | benchmark return; `mom_12_1` (no TSX market cap or fundamentals) |
  | Crypto | market, size, momentum | BTC return (altcoins); trailing 30-day dollar volume as the size proxy; 4-week momentum ★ |

- **Rebuilding the factors:**
  - each factor except the market is rebuilt every 21 sessions (★);
  - it is the equal-weight return of the top third minus the bottom third of that day's universe, by the characteristic as known the session before.
  - **Daily factor returns** are stored per market, as Parquet in the training build and `factor_returns` in Postgres for live.
- **Exposures (betas):**
  - per stock, a ridge regression (★ λ small, fixed) of daily excess returns on daily factor returns over the trailing 252 sessions ending the session before the feature day;
  - fitted only on data inside the training span of the fold being built.
- **The factor-adjusted target:** `alpha_h = y_h − Σ β_k · F_k,h`, where `F_k,h` is factor k's realised return over the same h sessions.
  - It's used to train the q10/q50/q90 boosters and to rank.
  - The embargo is unchanged.
- **What the owner sees doesn't change meaning:**
  - **P(beat benchmark):** the binary booster still learns `y_h > 0` (beating the benchmark, what the owner earns), with the alpha forecast and the betas added as features (★), and is calibrated as now.
  - **The ranges** shown and used by the cost check are rebuilt in benchmark-excess terms: `q_y = q_alpha + Σ β_k · μ_k,h`, where `μ_k,h` is factor k's mean h-session return over the fold's training span.
  - Coverage of the rebuilt q10–q90 is measured on outer folds like any range.
- **Live:**
  - `train.yml` stores the daily factor returns and each stock's latest betas with the model files;
  - each run uses the betas from the latest weekly build, which only uses data before it.
- **The cross-check:** the benchmark report correlates our US factors with Kenneth French's published daily factors (keyless CSV) to catch construction bugs. That data never enters training.

### 4. GARCH volatility (Plan 6d)

- **The model:** GARCH(1,1) on daily log returns per asset (stocks and coins), with Student-t errors (★), using the `arch` package (BSD licence, pinned).
- **Point in time:**
  - the parameters are fitted once per asset per training fold, on that fold's training span only;
  - the conditional variance is then filtered forward day by day with those fixed parameters, so a day's value uses only returns up to that day;
  - an asset with under 500 (★) returns, or a fit that doesn't converge, gets NaN, which LightGBM handles. The run never fails over it.
- **The feature:** `garch_vol_h`, the forecast volatility over each horizon h (the sum of the h-step variance forecasts, as a square root).
- **Range adjustment:**
  - per horizon, a scale `s` is fitted on inner folds so the q10–q90 coverage of `q50 ± s · garch_vol_h`, blended with the model's own range, comes closest to 80% (★);
  - it's applied only if outer-fold coverage error shrinks and calibration stays ≤ 5 points.
- **Risk:** the risk score's realised-volatility component (`vol_60`, spec §6.4) can be replaced by `garch_vol_21`. This follows the same evidence rule, judged on how well the risk level ranks realised drawdowns.
- **Stops stay ATR-based.** The GARCH volatility is offered to the policy search only as an alternative stop distance, and adopted only if the outer folds say so.

### 5. The constrained policy search (Plan 6e)

- **What's searched** is a small fixed grid (★). The grid is deterministic, not an optimiser with random restarts.
  - P to buy: 0.54 to 0.66 in steps of 0.02.
  - P to sell or avoid: 0.38 to 0.46 in steps of 0.02.
  - Swing stop: 1.5 to 3.0 ATR in steps of 0.5.
  - Position stop: 2.0 to 4.0 ATR in steps of 0.5, with its 15% cap kept.
  - Trailing stop: 2.0 to 3.5 ATR in steps of 0.5.
  - The horizon rule:
    - the best expected return per unit of range (today's rule);
    - the highest P;
    - or a fixed horizon set chosen per market.
- **The simulation:**
  - it extends `simulate_picks` with stop exits, closing on the first close at or under the stop (the grading rule), and exits at the exit-by date;
  - costs: the spread from dollar volume, `2 × usd_fx_fee_pct` for US, `2 × crypto_fee_pct` for coins;
  - one position per stock at a time (the existing rule);
  - at most 10 per style and 3 per sector.
- **The objective,** on the inner folds pooled: net Sharpe of the equal-weight book, minus penalties (★) for turnover above a cap and for drawdown above a soft line.
- **Hard limits,** where a configuration is rejected on any inner fold (★):
  - fewer than 30 separate trades;
  - maximum drawdown over 25%;
  - more than 20 trades a month per market;
  - claimed P more than 5 points from the realised beat rate.
- **Reporting:** the chosen values are scored once on each outer fold and reported. They become the market's accepted policy only if the full-model-plus-policy ablation passes.
- **Live:** the recommender, verdicts and holding actions read the policy values from the active accepted configuration, falling back to today's constants.

### 6. Fallbacks (all plans)

| Situation | What happens |
|---|---|
| The benchmark run fails or times out | Accepted configurations are unchanged. The report records the failure. |
| An addition fails the acceptance rule | It's not used. The report says which rule failed. |
| Weekly training fails for a configuration | The last accepted model stays active (as today). |
| GARCH, factor or beta data is missing for an asset | NaN features, and that asset's target falls back to `y_h`. It's never dropped silently, and it's counted in the report. |
| There's no accepted policy | Today's constants are used. |

### 7. Determinism and testing

- **Determinism:**
  - fixed seeds, as now (`PARAMS["seed"]`);
  - rows sorted before fitting;
  - fixed grids;
  - GARCH with fixed starting values;
  - no wall-clock or random dependence.
- **Tests per plan:**
  - unit tests for every pure function;
  - integration tests against the local Postgres, for storage and the workflow entry points.
- **Leakage and point-in-time tests, required by each plan:**
  - perturbation tests: changing any value on or after a fold's start, or a feature day, must not change anything fitted or computed for an earlier day;
  - embargo tests per horizon;
  - a factor portfolio formed on day t must use no characteristic dated t or later;
  - betas, GARCH parameters, calibrators and policy values must be byte-identical when a fold's test rows are deleted.

## Plans, in dependency order

| Plan | Builds | Needs |
|---|---|---|
| **6a** | The evaluation harness, migration 0010, `benchmark.yml`, the baseline benchmark report | today's pipeline |
| **6b** | The crypto model (history, universe, features, training, live verdicts and actions) | 6a |
| **6c** | Factors and the factor-adjusted target (all three markets) | 6a, 6b for crypto |
| **6d** | GARCH volatility (feature, range and risk adjustment) | 6a |
| **6e** | The policy search and the live use of accepted policies | 6a, ideally after 6c and 6d |

The full ablation table becomes reportable once 6c, 6d and 6e land. Each plan's report states which ablation rows it could fill.

## Known limits (stated, not solved)

- **Survivorship can't be removed with keyless data.**
  - Stock universes are today's listings: Yahoo has no delisted tickers, and SEC's ticker map is current-only.
  - Crypto history covers only products Coinbase still serves.
  - The benchmark report states this on every page, as the Track Record already must (spec §5.2).
- **Crypto "size" is a trading-volume proxy:** CoinGecko's free history covers only 365 days.
- **The TSX factor adjustment is two-factor** (market and momentum), since there's no point-in-time TSX market cap or fundamentals.
- **Compute:** a full benchmark is estimated at 2–3 hours for US and less for TSX and crypto. It's kept monthly within the private repo's Actions allowance.

## Decisions after the builder check (2026-10-28, designer's calls, for the owner to check)

1. **What's compared, for the factor variant.**
   - Acceptance compares the **rebuilt** `q_y = q_alpha + Σβμ` against the realised benchmark-excess `y`. That's the same yardstick as the baseline, and it's what the owner earns.
   - Picks and verdicts are also ranked on the rebuilt forecast. It keeps each stock's average factor premium (`βμ`, the fold's mean), but not factor *timing*. That's the point: the model can't earn its rank by riding a factor's recent run.
   - Rank IC of `q_alpha` against the realised `alpha` is reported as a diagnostic only.
2. **Outer fold 0, and what goes live.**
   - Outer fold 0 (only 2 years of training) is scored on rank IC and pinball loss only. It has no earlier out-of-sample predictions to calibrate on, so it gets no calibration or policy score, as today.
   - The model rule ("rank IC improves in at least 3 of 4 folds") uses all 4 folds. The policy rules use folds 1–3.
   - Inner splits expand within each outer training span, and the first inner split needs at least 1 year.
   - Once an addition passes on the outer folds, its configuration and policy are re-tuned once on inner splits over the whole history. That re-tuned version is what's promoted to `accepted_configs`.
3. **Rows and exits in the policy simulation.**
   - Entries and re-checks are decided on the sampled days the models are trained and scored on (every 10th session).
   - Exits are walked day by day on the daily closes and ATR between sampled days:
     - the stop, on the first close at or under it;
     - the trailing stop, which only rises;
     - the exit-by date;
     - a P-driven sell when a held position's re-forecast on a sampled day is at or under the sell line. This is what tunes the 0.38–0.46 line.
   - The hard limits use this cadence:
     - at least 30 separate trades pooled over the scored outer folds;
     - at most 20 new trades per month.
   - Forecasting every session (about 10× the compute) is not done.
4. **Betas roll forward.**
   - For every row, in training and test alike, betas use the 252 sessions ending the session before that row's day. That's point in time, and it matches live, where betas are at most a week old.
   - **The leakage tests are, precisely:**
     - nothing computed for day t changes when data dated t or later is changed or deleted;
     - nothing fitted for a fold (boosters, calibrators, GARCH parameters, scale `s`, policy values) changes when that fold's test-period targets are changed or deleted.
5. **Crypto's calendar.**
   - Coins trade daily, so crypto horizons are calendar days: 7, 14, 30, 90 and 180 (★), one row every 7 days.
   - BTC's target against SPY uses SPY's last close on or before each end of the window.
   - The embargo and the GARCH series are counted in calendar days.
6. **Crypto's policy.**
   - Coins never enter pick lists, so crypto's policy search tunes only the buy/avoid lines of its verdicts, the sell line and the stop multipliers of its holding actions.
   - These are scored on a simulated "follow the verdicts" book with the same costs and hard limits.
   - Ablation 5 for crypto is that book.
   - A coin's Buy verdict has no market gate, as watched stocks' verdicts don't today.
7. **Choosing among ablation rows.**
   - Each candidate row (factors, GARCH, both) is judged against the **original baseline** under the acceptance rule.
   - Among the rows that pass, the one with the best pooled rank IC becomes the model. The combination is used only if the combined row itself passes.
   - The policy row is then tuned on top of that model.
   - A later plan's candidate must also beat the **currently accepted** configuration on the outer folds to replace it.

## Left to the builder

- Module layout and function names.
- Ridge λ, GARCH starting values and the exact penalty weights, as long as they're fixed constants recorded in the report.
- The report's layout.
- How inner folds are cached between variants.
