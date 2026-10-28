# Plan 6e: The Constrained Policy Search — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The recommendation policy is tuned on inner folds and judged on untouched outer folds, after every cost. It goes live only when it beats today's rules and meets the hard limits. The policy covers the buy and sell/avoid probability lines, the swing, position and trailing stop multipliers, and the horizon rule.

**Architecture:**
- **One `Policy` value** (`advisor/policy.py`) replaces today's scattered constants. `DEFAULT_POLICY` equals them exactly.
- **A day-by-day book simulator** (`benchmark/simulate.py`) enters on sampled days and exits on daily closes. The exits are the stop, the rising trailing stop, the exit-by date, and a P-driven sell on a later sampled day.
- **A staged grid search** (`benchmark/policy_search.py`) tunes on inner folds under hard limits.
- **The benchmark job** tunes per outer fold, scores on that fold, and fills ablation row 5 (`full+policy`). If the policy passes, it's re-tuned over the whole history and stored in the accepted config.
- **Live use:** weekly training carries the accepted config's policy into the model's stored metrics. The live run, verdicts, holding actions, trailing stops, exit-early and the weekly pick gate read it from there, falling back to `DEFAULT_POLICY`.

**Tech Stack:** Python 3.12, pandas, numpy; pytest, ruff. No new dependency.

**Spec:** `docs/superpowers/specs/2026-10-28-prediction-upgrade-design.md`:
- §5 the policy search;
- §6 Fallbacks;
- §7 Determinism and testing;
- builder-check decisions 3 and 7.

**Builds on Plan 6a:** `docs/superpowers/plans/2026-10-28-plan-6a-evaluation-harness.md`, merged:
- `ModelConfig`, `run_variant`, `inner_walk_forward`, `inner_folds`;
- `model_metrics`, `Scores`, `choose_model`;
- `benchmark.job`, migration 0010.

**Why now (owner decision 2026-10-29):** the first benchmark (`a8c8daf`) shows today's rules made **0 trades** in every outer fold in both markets. The pooled rank IC was 0.053 for US and 0.012 for TSX. 6e moves ahead of 6b, 6c and 6d. Those later plans re-tune the policy on top of whatever model they accept.

## Global Constraints

- **Tests in Docker,** from `pipeline/`: `scripts/in-docker.sh uv run pytest -q`; `scripts/in-docker.sh uv run ruff check .`.
- **`DEFAULT_POLICY` reproduces today's behaviour exactly:**
  - `p_buy=0.58`, `p_sell=0.42`;
  - `swing_atr=2.0`, `position_atr=3.0`, `trail_atr=2.5`;
  - `rule="ratio"`, `horizons=None` (all usable horizons).
  
  The 15% position cap (`POSITION_MAX_DROP = 0.15`), 10 per style and 3 per sector stay fixed constants.
- **The grid ★** (fixed and ordered; on ties, the first wins):
  - `p_buy` 0.54, 0.56, …, 0.66;
  - `p_sell` 0.38, 0.40, …, 0.46;
  - `swing_atr` 1.5, 2.0, 2.5, 3.0;
  - `position_atr` 2.0, 2.5, …, 4.0;
  - `trail_atr` 2.0, 2.5, 3.0, 3.5;
  - `rule` `"ratio"` or `"p"`;
  - `horizons` `None`, `(5, 10, 20)` or `(21, 63, 126)`.
- **The staged search ★** (a builder call; the full product is 16,800 simulations):
  1. **Entries:** `p_buy × rule × horizons` (42), with the default exits.
  2. **Stops:** `swing_atr × position_atr × trail_atr` (80), with stage 1's best.
  3. **The sell line:** `p_sell` (5), with stage 2's best.
  
  If no combination in a stage is feasible, the search stops and returns no policy.
- **The objective ★:** pooled net Sharpe minus `DD_PENALTY × max(0, max_drawdown − DD_SOFT)`, with `DD_PENALTY = 2.0` and `DD_SOFT = 0.15`.
- **Hard limits** (a combination is infeasible if any fails):
  - at least `MIN_TRADES = 30` trades, pooled over the folds scored;
  - every fold's drawdown ≤ `MAX_DRAWDOWN = 0.25`;
  - every fold's new trades per month ≤ `MAX_TRADES_PER_MONTH = 20`;
  - the pooled claimed-P gap (|mean P − realised beat rate| × 100) ≤ `MAX_CALIBRATION_PTS` (5).
- **Costs:** `round_trip_cost` (the spread from dollar volume, plus `2 × usd_fx_fee_pct` for US), charged once, on the exit day.
- **Sharpe:** `sqrt(252) × mean / std` of the daily book return, over every session in the period (an empty book earns 0 that day). NaN when the std is 0 or there are no trades.
- **Point in time:** a simulation given `end` closes every open position at the last close before `end`. A tuning simulation never reads a close dated on or after its `known_before`.
- **Fail closed:** a NaN never passes a limit or an acceptance rule.
- **Determinism:** no clock; inputs sorted; grid order fixed.
- **Git:**
  - run `git commit` in its own command;
  - never pass `--no-verify`;
  - Claude's commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; Cursor's don't;
  - no push.

## Review Focus

1. **A tuning trade whose hold crosses into the outer fold** must be closed at the last close before it, or tuning peeks at graded prices. Pinned in Task 3's leakage test.
2. **TSX's model barely ranks (IC 0.012):** the search may find nothing feasible. Then the result must be "no policy", with today's rules kept and the reason in the report, never a crash or a forced pick. Pinned in Tasks 3 and 4.
3. **A stock whose close is missing on some days** (halted, or a data gap) must not crash the exit walk or fake a stop. The last close carries forward. Pinned in Task 2.
4. **A stored policy with an unknown key or a value outside the grid's types** must be refused, and the live run must fall back to `DEFAULT_POLICY`. Pinned in Tasks 1 and 5.
5. **The live run and the weekly gate must use the same policy as the model they belong to.** It's the one stored in that model's metrics, never a newer accepted config the model wasn't trained under. Pinned in Task 5.

---

### Task 1 (Cursor): The `Policy` value, and configs that carry one

**Files:**
- Create: `pipeline/src/advisor/policy.py`
- Modify: `pipeline/src/advisor/model/variants.py`
- Test: `pipeline/tests/unit/test_policy.py`, `pipeline/tests/unit/test_model_variants.py`

**Interfaces:**
- **`Policy`**, a frozen dataclass:
  - `p_buy: float`, `p_sell: float`;
  - `swing_atr: float`, `position_atr: float`, `trail_atr: float`;
  - `rule: str` (`"ratio"` or `"p"`);
  - `horizons: tuple[int, ...] | None`.
- **`DEFAULT_POLICY`**, with the Global Constraints values.
- **`Policy.to_json() -> dict`:** the seven keys; `horizons` is a list or null.
- **`Policy.from_json(d) -> Policy`:** raises `ValueError` on a non-mapping, missing or extra keys, a non-number threshold, `rule` not in (`"ratio"`, `"p"`), `p_sell >= p_buy`, or any multiplier ≤ 0.
- **`policy_of(metrics: Mapping) -> Policy`:** `metrics["config"]["policy"]` parsed, or `DEFAULT_POLICY` when it's absent, null or invalid.
- **`ModelConfig.policy` becomes `Policy | None`.**
  - `unbuilt` no longer names Plan 6e for a policy.
  - `to_json`/`from_json` (de)serialise it through `Policy`. An invalid policy raises `ValueError`.
  - The name rule is unchanged (`"baseline+policy"`).

- [ ] **Step 1: Tests**
  - **In `test_policy.py`:**
    - `DEFAULT_POLICY.to_json() == {"p_buy": 0.58, "p_sell": 0.42, "swing_atr": 2.0, "position_atr": 3.0, "trail_atr": 2.5, "rule": "ratio", "horizons": None}`;
    - the round trip, including `horizons=(21, 63, 126)`;
    - a parametrised refusal for each invalid case above;
    - `policy_of({})`, `policy_of({"config": {"policy": None}})` and `policy_of({"config": {"policy": {"bad": 1}}})` all equal `DEFAULT_POLICY`;
    - `policy_of` of a valid stored policy returns it.
  - **In `test_model_variants.py`:**
    - replace the `"Plan 6e"` refusal case with a round trip of `ModelConfig(policy=Policy(...))`;
    - add a refusal of `{"version": 1, "factors": False, "garch": False, "policy": {"p_buy": 0.5}}` (missing keys).
- [ ] **Step 2: Run them; they fail** (`ModuleNotFoundError: advisor.policy`).
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the full suite and ruff.** They pass.
- [ ] **Step 5:** Commit `feat: one Policy value for the recommendation rules, carried by model configs`.

---

### Task 2 (Claude): The day-by-day book simulator

**Files:**
- Create: `pipeline/src/advisor/benchmark/simulate.py`
- Test: `pipeline/tests/unit/test_benchmark_simulate.py`

**Interfaces:**
- **Consumes:** `Policy` (Task 1); `round_trip_cost`, `SWING_HORIZONS`, `PICKS_PER_STYLE`, `PER_SECTOR` (backtest); `POSITION_MAX_DROP` (`recommend/picks.py`).
- **Produces:**
  - **`DailyPanel`**, a frozen dataclass:
    - `close: pd.DataFrame` (sessions × symbols, split-adjusted, including the benchmark);
    - `atr_pct: pd.DataFrame` (the same shape, `atr_14_pct`);
    - `benchmark: str`.
  - **`daily_panel(data_dir: Path, market: Market) -> DailyPanel`:** built with `feature_frames` exactly as `load_market` builds its features, so the closes and ATR match the training rows.
  - **`simulate_book(pred: pd.DataFrame, panel: DailyPanel, policy: Policy, market: Market, usd_fx_fee_pct: float, start: pd.Timestamp, end: pd.Timestamp) -> Book`:**
    - `Book.trades` is a DataFrame with the columns `symbol, entry_day, exit_day, horizon, style, p, entry, exit, reason, cost, net, beat`, where `reason` is one of `stop`, `trail`, `exit_by`, `sell` or `end`;
    - `Book.daily` is a Series of the daily book return on every session in `[start, end)`.
  - **`book_metrics(book: Book) -> dict`:** `trades`, `trades_per_month`, `mean_net_pct`, `hit_rate_net`, `beat_rate`, `mean_p`, `claimed_gap_pts`, `sharpe` and `max_drawdown`.
    - Rates are `None` with no trades.
    - `max_drawdown` is the largest fall of the cumulative book from its running peak, as a positive fraction; it's 0.0 with no trades.
    - `trades_per_month` is new trades ÷ the distinct calendar months in `[start, end)`.
- **The rules,** walked session by session over `[start, end)`; closes are forward-filled within the panel:
  1. **Exits first, each session, for every open position, in this order:**
     - **`stop`:** close ≤ the stop;
     - **`trail`:** close ≤ the trailing stop, which is `max(previous trail, highest close since entry − trail_atr × atr_pct_t × close_t)`, starting at the entry stop and only rising;
     - **`exit_by`:** the session `horizon` sessions after entry;
     - **`sell`** (sampled days only): the day's row for that symbol at the trade's horizon has `p ≤ p_sell`;
     - **`end`:** the last session before `end`.
     
     A position exits at that session's close.
  2. **Entries,** on sampled days only (days with a row in `pred` that has `p`), at that day's close:
     - **Eligible rows:** `p ≥ p_buy`, `q50 > cost`, `q90 > q10`, horizon in `policy.horizons` (when set), and `jump_5d` not 1.
     - **The symbol's best row:** the highest `q50 / (q90 − q10)` for `rule="ratio"`, or the highest `p` for `"p"`. A tie goes to the shorter horizon.
     - **The style:** swing if the horizon is in `SWING_HORIZONS`, else position.
     - **Ranking within a style:** the same key, then symbol. At most 3 per sector (an unlabelled stock counts alone) and 10 per style **among new entries that day**.
     - **No duplicates:** a symbol already open, or exited earlier the same session, isn't entered.
  3. **The entry stop:**
     - swing: `entry × (1 − swing_atr × atr)`;
     - position: `max(entry × (1 − position_atr × atr), entry × (1 − POSITION_MAX_DROP))`;
     - `atr` is the entry day's `atr_pct`. A NaN ATR means the row isn't entered.
  4. **Results:**
     - `net = exit / entry − 1 − cost`;
     - `beat = exit / entry > bench_exit / bench_entry`;
     - the daily book return on a session is the mean over open positions of `close_t / close_{t−1} − 1`. On a position's exit session, its return for that session has `cost` subtracted.

- [ ] **Step 1: Tests (hand-built panels, one sampled day unless stated)**

```python
def panel(paths, atr=0.02, bench=None, start="2024-01-01"):
    """`paths`: symbol -> list of closes; the benchmark is flat unless given."""
    days = pd.bdate_range(start, periods=len(next(iter(paths.values()))))
    close = pd.DataFrame(paths, index=days)
    close["SPY"] = bench if bench is not None else 100.0
    return DailyPanel(close, pd.DataFrame(atr, index=days, columns=close.columns), "SPY")

def row(day, symbol="A", horizon=5, p=0.7, q50=0.05, **kw):
    return {"day": pd.Timestamp(day), "symbol": symbol, "sector": "Tech", "dollar_volume_20": 2e7,
            "horizon": horizon, "fold": 1, "y": 0.0, "q10": q50 - 0.1, "q50": q50, "q90": q50 + 0.1,
            "p_raw": p, "p": p, **kw}

TSX_COST = 0.001  # 2e7 dollar volume: large-cap spread, no FX fee
```

  - **`test_a_trade_exits_at_its_exit_by_close`:** A rises 100 → 105 over 6 sessions with horizon 5. There's one trade, `reason == "exit_by"`, `exit_day` is the 6th session, and `net == approx(0.05 − TSX_COST)`.
  - **`test_a_close_at_or_under_the_stop_exits_there`:** path `[100, 99, 96, 95, 97, 98]`, ATR 0.02, swing stop 96.0. The trade exits on session 3 at 96 (`reason == "stop"`), and `net == approx(−0.04 − TSX_COST)`.
  - **`test_the_trailing_stop_only_rises_and_exits_there`:** path `[100, 110, 120, 105, 130, 130]` with horizon 63 and `trail_atr=2.5`. The trail after session 3 is 120 − 2.5 × 0.02 × 120 = 114, so the trade exits on session 4 at 105 with `reason == "trail"`.
  - **`test_a_later_forecast_at_the_sell_line_sells`:** horizon 63, a second sampled row for A five sessions later at horizon 63 with `p = 0.42`, and the default policy. The trade exits that day with `reason == "sell"`. With `p_sell=0.40` it isn't sold then.
  - **`test_positions_still_open_close_at_end`:**
    - the simulation is given an `end` 3 sessions after entry, and the trade closes at session 3 with `reason == "end"`;
    - **changing every close dated on or after `end` leaves `trades` and `daily` identical** (the point-in-time rule).
  - **`test_entries_follow_the_policy`:**
    - the `rule="p"` and `rule="ratio"` choices differ on a two-horizon row set built for it;
    - `horizons=(21, 63, 126)` skips a 5-day row;
    - `p_buy=0.66` skips `p=0.65`;
    - a NaN-ATR row is skipped;
    - a `jump_5d == 1` row is skipped.
  - **`test_one_position_per_stock_and_the_style_and_sector_caps`:**
    - 12 qualifying stocks in one sector on one day give 3 entries;
    - 12 in 12 sectors give 10;
    - A already open isn't entered again.
  - **`test_a_missing_close_carries_forward`:** a NaN in A's path mid-hold neither raises nor triggers a stop.
  - **`test_book_metrics`:**
    - a two-trade book: `trades == 2`; `beat_rate`, `mean_p`, `claimed_gap_pts`, `trades_per_month` and `max_drawdown` match hand values;
    - an empty book: `trades == 0`, rates `None`, `sharpe` NaN, `max_drawdown == 0.0`.
  - **`test_us_costs_include_the_fx_fee`:** with `Market.US` and a fee of 1.5, `cost == approx(0.001 + 0.03)`.
- [ ] **Step 2: Run them; they fail** (`ModuleNotFoundError`).
- [ ] **Step 3: Implement.** Loop over sessions with plain Python and dict state, sorted for determinism. Vectorise only if a benchmark run shows the need.
- [ ] **Step 4: Run them; they pass.** Then run the full unit suite and ruff.
- [ ] **Step 5:** Commit `feat: simulate a book of picks day by day, with stops, trailing stops, exit-by and P sells`.

---

### Task 3 (Claude): The staged search, with leakage tests

**Files:**
- Create: `pipeline/src/advisor/benchmark/policy_search.py`
- Test: `pipeline/tests/unit/test_benchmark_policy_search.py`

**Interfaces:**
- **Consumes:** `simulate_book` and `book_metrics` (Task 2); `inner_folds`, `inner_walk_forward` (6a); `Policy`, `DEFAULT_POLICY`.
- **Produces:**
  - The constants `GRID`, `MIN_TRADES`, `MAX_DRAWDOWN`, `MAX_TRADES_PER_MONTH`, `DD_SOFT`, `DD_PENALTY`;
  - **`score(pred, panel, policy, market, fee, periods: Sequence[Fold]) -> dict`:**
    - one `simulate_book` per period, with `start`/`end` from the period;
    - `per_period` holds `book_metrics` for each;
    - `pooled` holds the metrics of the concatenated trades and daily series;
    - `feasible` is a bool;
    - `failures` lists plain-words strings, e.g. `"only 12 trades (needs 30)"`, `"period 2 drew down 31% (limit 25%)"`, `"period 1 made 24 trades a month (limit 20)"`, `"picks claimed 64% but beat 55% (limit 5 points)"`;
    - `objective` is a float, NaN when infeasible.
  - **`tune(pred, panel, market, fee, periods) -> Tuned`:**
    - `Tuned` has `policy: Policy | None`, `objective: float`, `tried: int` and `reason: str`;
    - `policy` is `None` with a reason like `"no stage-1 combination met the limits: best failed on only 4 trades (needs 30)"`.
  - **`tune_for_outer(data, config, train_config, panel, market, fee, outer: Fold) -> Tuned`:**
    - runs `inner_walk_forward`, keeping rows with `p` in the variant's calibrated horizons;
    - the periods are the inner folds that have `p` (inner fold 0 has none);
    - `known_before = outer.start`, so the last period ends at `outer.start`.

- [ ] **Step 1: Tests**
  - **`test_the_search_is_staged_and_deterministic`:**
    - on a synthetic `pred` and panel where `p_buy=0.60` alone gives ≥ 30 profitable trades, `tune` returns `p_buy == 0.60`;
    - `tried == 42 + 80 + 5`;
    - a second call returns the identical `Tuned`.
  - **`test_nothing_feasible_returns_no_policy_and_says_why`:** with too few qualifying rows, `policy is None` and the reason contains "needs 30".
  - **`test_each_hard_limit_rejects`:** one case each for trades, drawdown, turnover and the claimed-P gap, each failure string asserted.
  - **`test_a_nan_never_passes_a_limit`:** a NaN Sharpe makes the combination infeasible.
  - **`test_tuning_never_reads_the_outer_period`:**
    - use `write_market(..., stocks=40)`, with `outer` = the 3rd outer fold;
    - `tune_for_outer` gives the same `Tuned`, byte for byte, after every close and feature on or after `outer.start` is replaced with noise, and after every target unknown before `outer.start` is randomised (as in 6a's inner leakage test);
    - **mutation check:** removing the `end` truncation must make this test fail. Record it in the ledger.
- [ ] **Step 2: Run them; they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them; they pass.** Full unit suite and ruff.
- [ ] **Step 5:** Commit `feat: the staged policy search under hard limits, tuned only on inner folds`.

---

### Task 4 (Claude): The benchmark fills ablation 5 and accepts policies

**Files:**
- Modify: `pipeline/src/advisor/benchmark/accept.py`, `pipeline/src/advisor/benchmark/job.py`
- Test: `pipeline/tests/unit/test_benchmark_accept.py`, `pipeline/tests/integration/test_benchmark_job.py`

**Interfaces:**
- **`accept_policy(candidate: Mapping, default: Mapping) -> Decision`:** both are `score(...)` results over outer folds 1–3. It accepts only when all of these hold:
  - the candidate is `feasible`;
  - the candidate's pooled Sharpe > the default's pooled Sharpe. A default with no trades counts as **0.0**, since it holds cash; ledger this as a ruling.
  
  The pass reason reads `f"net Sharpe {c:.2f} vs {d:.2f} for today's rules, {n} trades"`.
- **The job, per market,** after `choose_model`, for the chosen variant's outer predictions (folds 1–3, rows with `p` in its calibrated horizons):
  1. **The default:** `default = score(pred, panel, DEFAULT_POLICY, …, periods=outer folds 1–3)`.
  2. **Per outer fold k = 1..3:** `tune_for_outer` → `policy_k`. Score `policy_k` on fold k only. Pool the three scores into the candidate (concatenate the trades and daily series, then recompute `book_metrics` and the limits). If any `policy_k` is `None`, the row is rejected with that `Tuned.reason`.
  3. **`decision = accept_policy(candidate, default)`.**
  4. **If it's accepted,** re-tune over the whole history: `tune_for_outer` with `outer = Fold(last_day + 1 day, last_day + 2 days)`. Accept `ModelConfig(<chosen flags>, policy=<that policy>)`. If that final tune returns `None`, keep the model without a policy and record why.
  5. **Not accepted:** the accepted config is the chosen model without a policy.
  6. **Changed** means the new config's `to_json()` differs from the active row's `config`. The reason is the policy decision's reason when a policy is set.
- **Report entries:**
  - `variants["full+policy"]` becomes `{"status": "run", "policy": {"default": default, "candidate": candidate, "per_fold": [policy_k.to_json() | None], "final": final policy json | None}}`;
  - `decisions["full+policy"]` holds the decision.
  
  Write `BenchmarkResult` rows for variant `"full+policy"`, folds `"1"`–`"3"` and `"pooled"`, with metrics `{"default": …, "candidate": …}`.
- **The daily panel** is built once per market (`daily_panel`) and freed after the market.

- [ ] **Step 1: Tests**
  - **Unit, `accept_policy`:**
    - beating a cash default passes;
    - an infeasible candidate fails, with its failures as reasons;
    - a NaN Sharpe fails;
    - a candidate below a default that traded fails.
  - **Integration** (`write_market` TSX, `FAST`):
    - `test_the_policy_row_runs_and_reports_both_books`: `variants["full+policy"]["status"] == "run"`, `"default"` and `"candidate"` are present, and `benchmark_results` has `"full+policy"` rows for folds 1–3 and pooled;
    - `test_a_policy_that_fails_keeps_the_model_without_one`: monkeypatch `tune_for_outer` to return `Tuned(None, nan, 0, "no stage-1 combination met the limits: …")`. Then `active_config(db, "TSX").config["policy"] is None`, and the decision's reasons contain that text;
    - `test_an_accepted_policy_is_stored_with_the_model`: monkeypatch `accept_policy` to accept, and `tune_for_outer` to return a fixed `Policy`. Then the active config's `policy` equals that policy's JSON, and `accepted.changed is True`.
- [ ] **Step 2: Run them; they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: The full suite and ruff pass.**
- [ ] **Step 5:** Commit `feat: the benchmark tunes the policy per outer fold and accepts it only on held-out evidence`.

---

### Task 5 (Cursor): The live run follows the model's policy

**Files:**
- Modify:
  - `recommend/picks.py` (`choose`, `stop_price`);
  - `recommend/verdicts.py` (`stock_verdict`, `_first_failing_check`);
  - `recommend/stage.py` (`is_sane`, `recommend_market`, `watch_verdicts`);
  - `portfolio/actions.py` (`decide` via `Holding.policy`);
  - `portfolio/stops.py` (`trailing_stop`);
  - `portfolio/stage.py`;
  - `grade.py` (`exit_early`).
- Test: the existing tests of each module, plus the new cases below.

**Interfaces:**
- **Every function above takes a `policy: Policy = DEFAULT_POLICY` keyword** and uses it in place of the constant:
  - `p_buy` replaces `P_MIN`;
  - `p_sell` replaces `AVOID_P`;
  - `swing_atr` and `position_atr` replace `SWING_ATR` and `POSITION_ATR`;
  - `trail_atr` replaces `TRAIL_ATR`.
  
  `choose` also applies `policy.rule` and `policy.horizons` exactly as Task 2's entry rule does.
- **`Holding` gets `policy: Policy = DEFAULT_POLICY`.**
- **`exit_early(picks, rows, policies: Mapping[str, Policy])`:** keyed by market, defaulting to `DEFAULT_POLICY`.
- **Where the policy comes from:** each market's policy is `policy_of(MarketModel.metrics)`. It's the policy stored with the **active model**, never read from `accepted_configs` directly.
- **Coins** keep `DEFAULT_POLICY` until Plan 6b.
- **Keep the old constants** as the defaults' sources: `P_MIN`, `AVOID_P`, `SWING_ATR`, `POSITION_ATR`, `TRAIL_ATR` stay importable, and `DEFAULT_POLICY` is built from them. Nothing else changes when the policy is the default.

- [ ] **Step 1: Tests**
  - **For each module, one new case each:** a non-default policy changes the outcome. Examples:
    - `choose` with `p_buy=0.54` picks a `p=0.55` row the default skips;
    - `stop_price` with `swing_atr=1.5`;
    - `trailing_stop` with `trail_atr=3.0`;
    - `decide` sells at `p=0.45` with `p_sell=0.46`;
    - `exit_early` flags a pick at `p=0.45` under a TSX policy with `p_sell=0.46`;
    - `is_sane` accepts ATR 0.4 with `swing_atr=2.0` but not with `swing_atr=3.0`.
  - **An end-to-end stage test:** a `MarketModel` whose `metrics["config"]["policy"]` has `p_buy=0.54` makes a `p=0.55` stock a pick and a watched Buy.
  - **The fallback:** an invalid stored policy behaves exactly as the default.
- [ ] **Step 2: Run them; they fail.** Step 3: implement. Step 4: the full suite, ruff, and the existing e2e-relevant pipeline tests pass unchanged.
- [ ] **Step 5:** Commit `feat: picks, verdicts, holding actions, stops and exit-early follow the model's policy`.

---

### Task 6 (Cursor): The weekly gate uses the policy, and the report's row order

**Files:**
- Modify: `model/backtest.py` (`simulate_picks`, `pick_funnel`); `model/weekly.py`; `benchmark/report.py`
- Test: `tests/unit/test_model_backtest.py`, `tests/integration/test_model_weekly_job.py`, `tests/unit/test_benchmark_report.py`

**Interfaces:**
- **`simulate_picks(predictions, market, usd_fx_fee_pct, policy: Policy = DEFAULT_POLICY)` and `pick_funnel(...)`:** they use `policy.p_buy`, `policy.rule` and `policy.horizons`. The default reproduces today's output exactly; the existing tests pass unchanged.
- **`weekly._train_market`** passes `model_config.policy or DEFAULT_POLICY` to both, so the picks gate judges the policy the model will run with.
- **`render_markdown` lists ablation rows in the fixed order** `baseline, factors, garch, factors+garch, full+policy`, whatever order the dict arrives in. Postgres `jsonb` reorders keys, which is why the first report listed `garch` first.
- **The report gains a `### Policy (folds 1–3)` table** when `full+policy` ran:
  - one row each for "today's rules" and "tuned", with the columns Trades | Trades/month | Net per trade | Hit rate | Net Sharpe | Max drawdown | Claimed P vs beat rate;
  - then the per-fold tuned policy values, one line each;
  - and the final policy, or why there's none.

- [ ] **Step 1: Tests**
  - `simulate_picks` with `p_buy=0.54` returns a pick the default doesn't;
  - the weekly job with an accepted config holding a policy stores `metrics["config"]["policy"]` equal to it, and its funnel uses `p_buy`;
  - `render_markdown` of a report whose `variants` dict is in jsonb order prints `baseline` first;
  - the policy table renders, with `—` for an empty default book.
- [ ] **Steps 2–4:** fail, then implement, then pass. The full suite and ruff pass.
- [ ] **Step 5:** Commit `feat: the weekly pick gate judges the model's policy; the report lists rows in order and shows the policy books`.

---

### Task 7 (Cursor): The docs

- **The design doc's status line:** Plan 6e builds §5; §2–§4 remain future design.
- **The main spec's revision history:** one line, "Plan 6e (2026-10-29): the policy is tuned on inner folds and goes live only on held-out evidence (§6)".
- **README:** one sentence under the workflows. The monthly benchmark may change the live buy/sell lines and stops, and the report says why.
- **Commit:** `docs: Plan 6e`.

## After merging (the owner)

Push, then run **benchmark** manually and paste the report. No migration is needed. The **next Saturday `train.yml`** puts an accepted policy live. Until then the live run uses today's rules.
