# Plan 4c: Portfolio Advisor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every published run gives each holding one action (Sell / Trim / Add / Hold, with a Review badge), a trailing stop and an exit-by date. The run also flags open picks to exit early and grades picks and holding actions whose time is up. My Portfolio shows the actions in place of its placeholder.

**Architecture:**
- **A new package, `advisor.portfolio`, with one job per module:**
  - `ledger`: positions at average cost from `lots` and `sells`. It mirrors `web/lib/portfolio/ledger.ts`.
  - `stops`: the trailing stop.
  - `actions`: the §7.3 rules as one pure function.
  - `stage`: builds each holding's inputs from what stages 7 and 8 already computed, then writes `holding_actions`.
- **A new module, `advisor.grade`:** stage 9, exit-early and grading.
- **Stage 8 shares its per-market work.** `recommend_stage` now also returns each market's `StockInputs` and risk frame, so holdings are judged on exactly the numbers that picks and verdicts use.
- **Failures degrade the run.** Like stage 8, both new stages catch their own failures, record them in the summary and degrade the run. Prices always publish.
- **The web reads the actions.** It reads `holding_actions` of the latest published run and fills the Actions card and the holdings table's model columns, following the approved Ledger mockup.

**Tech Stack:** Python 3.12, pandas, numpy, LightGBM (`pred_contrib`), pandas-market-calendars, psycopg, pytest, ruff; Next.js 16, TypeScript, Vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-10-09-stock-advisor-design.md` (rev 2):
- §6.3 stops, §6.4 risk, §6.5 exit early and grading;
- §7.3 actions, §7.4 portfolio checks, §7.5 tax warnings;
- §8 (`holding_actions`, `picks`, `pick_outcomes`), §9 My Portfolio, §10 fallbacks.

Also read `docs/superpowers/deferred.md`: "Plan 4: what is left after 4a" and "Plan 4a known limits".

**Owner's decisions this plan relies on:**
- **4c comes before 4b** (2026-10-27): picks are off in both markets, so holding actions are worth more now.
- **Size is a warning, not a Trim** (2026-10-27). With four holdings of about C$2,800, every position is far over its risk-based max, so §7.3's size Trim would fire on every holding at every run.
  - A position over its max gets a warning that names its share and its max.
  - It still can't be an Add.
  - Trim comes only from the gain-and-momentum rule.
  - Task 9 records this in spec §7.3.
- **Earlier rules that still apply:**
  - Only usable horizons give P(beat), and a stock the model may not score gets no forecast (Plan 3c).
  - A model failure degrades the run (§10).

**Prototype findings** (live Yahoo and Coinbase data for the owner's four holdings, 2026-10-27):

| Holding | Data | What it means for 4c |
|---|---|---|
| VEEA (TFSA) | 400 sessions, US$62M/day, ATR 16.6%, up 110% over 21 days | Eligible: gets forecasts. Its trailing stop is about 41% under its high. |
| XRPN (TFSA) | 339 sessions, US$50M/day, ATR 15.0% | Eligible. |
| BONK, WIF (Crypto) | 350 Coinbase daily candles (USD), ATR 6.5–6.7% | No crypto model (§5.4): fallback rules. A trailing stop is computable in USD. |

So the holdings get actions from both paths, the model rules and the §10 fallback, on the first run.

## Global Constraints

- **Values from the spec, verbatim:**
  - **Sell** when P(beat) at the best horizon is **≤ 0.42** (`advisor.recommend.verdicts.AVOID_P`).
  - **Trim** at an unrealized gain of **≥ 25%** and a 21-day momentum percentile **< 40**.
  - **Add** when the holding qualifies as a Buy (`advisor.recommend.picks.choose`: P ≥ **0.58** and q50 > cost) and is below its max size.
  - **Trailing stop:** the highest close since purchase **− 2.5 × ATR(14)**. It only moves up, and never sits below the original stop.
  - **Review badge:** earnings or a phase 2/3 trial completion within **5** trading sessions, or a flagged unconfirmed jump on the latest bar.
  - **Superficial loss:** a sale or buy within **30** days of a sale at a loss.
  - **Exit early:** an open pick whose P at its horizon is **≤ 0.42**, or whose stop is hit.
- **One rule source.** Reuse `choose`, `best_horizon`, `AVOID_P`, `risk_levels`, `round_trip_cost` and `sessions_after`. Never restate their thresholds.
- **Taxable accounts** are `crypto` and `non_registered` (`web/lib/portfolio/types.ts` `TAXABLE`). Tax notes are warnings only and never change the action (§7.5).
- **Per account.** A stock held in two accounts gets two `holding_actions` rows with the same forecast.
- **Prices in the asset's own currency:**
  - US stocks are in USD, TSX stocks in CAD.
  - Coins are in USD (Coinbase candles). Their CAD value comes from CoinGecko's `price_cad`.
  - `trailing_stop`, `ref_price` and every grading price are native. Only position value and size are in CAD.
- **Failures degrade, never fail.** A failure in the holdings stage or in grading goes to `summary["actions"]` / `summary["graded"]` as `model_failure(exc)`, and `decide_status` counts it as degrading (like `verdicts_failure`).
- **Commits:** run `git commit` in its own shell command: a hook mistakes any `-n` in the same command for `--no-verify`. End every message with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Tests:**
  - Pipeline: `pipeline/scripts/in-docker.sh uv run pytest -q`, with the `advisor-pg` container running.
  - Lint: `pipeline/scripts/in-docker.sh uv run ruff check .`
  - Web (from `web/`): `npm test`, `npm run lint`, `npm run typecheck`, `npx playwright test`. Playwright needs the local Supabase stack.
- **Data hygiene:** no real account numbers or emails in code, tests or docs. Test contact: `stock-advisor test@example.com`.

## Review Focus

1. **A position bought after the latest bar** (bought today before a pre-open run). It has no close since purchase. Expected: the trailing stop uses the latest close and nothing crashes. Test in Task 3.
2. **A USD lot with no `fx_rate_cad` and no stored rate on or before its day.** Expected: that trade is left out of the ledger with a plain problem (as the web does), and the other positions are unaffected. Test in Task 2.
3. **A held stock whose market's model failed, or that isn't eligible.** Expected: a fallback row (stop and size rules only) whose reason says why there's no forecast. It is never left without a row. Test in Task 5.
4. **A coin with a CoinGecko quote but no Coinbase candles.** Expected: Hold with no trailing stop and a reason saying so, valued from the quote. Test in Task 5.
5. **A pick or action whose symbol has no close on or after its exit-by date yet.** Expected: it stays ungraded until a later run has the close. It is never graded on a stale price. Test in Task 7.

---

### Task 1: Migration 0009 — columns for grading, and holding-action outcomes

**Files:**
- Create: `supabase/migrations/0009_portfolio_advisor.sql`
- Test: `pipeline/tests/integration/test_schema.py`

**Interfaces:**
- Produces:
  - `picks.feature_day date`, `picks.bench_ref_price numeric (> 0)` (both nullable: older rows have none);
  - on `holding_actions`, all nullable:
    - `horizon_days int (> 0)`, `feature_day date`;
    - `ref_price numeric (> 0)`, `bench_ref_price numeric (> 0)`;
    - `risk_level text in ('low','medium','high','very_high')`, `max_position_pct double precision`;
  - the table `holding_action_outcomes`:
    - columns `(run_id, account, symbol, asset_type, exit_price numeric > 0, ret, ret_net_of_fx, bench_ret, excess double precision, beat bool, hit_stop bool, graded_at timestamptz default now())`, all not null;
    - primary key and foreign key `(run_id, account, symbol, asset_type)` → `holding_actions`, `on delete cascade`.

- [ ] **Step 1: Write the failing tests** in `test_schema.py`:
  - `test_holding_actions_carry_what_grading_needs`: insert a run and a `holding_actions` row with all six new columns. Reading them back returns the values, and `risk_level='extreme'` raises `psycopg.errors.CheckViolation`.
  - `test_a_holding_action_outcome_belongs_to_its_action`:
    - an outcome for a missing action raises `ForeignKeyViolation`;
    - deleting the run deletes the outcome;
    - `exit_price = 0` raises `CheckViolation`.
  - `test_picks_record_their_feature_day_and_benchmark_price`: an insert with `feature_day` and `bench_ref_price` reads back.
  - The existing RLS tests (`test_every_table_except_migrations_has_a_pipeline_policy` and the owner-read checks) must cover `holding_action_outcomes` without changes. Run them.
- [ ] **Step 2: Run** `pipeline/scripts/in-docker.sh uv run pytest -q tests/integration/test_schema.py`. Expected: the three new tests FAIL (unknown column or table).
- [ ] **Step 3: Write `0009_portfolio_advisor.sql`.**
  - Open with a header comment in the style of 0008.
  - Then the `alter table`s and the `create table`.
  - Then RLS for the new table, as in 0008: `enable row level security`, an `owner_read` policy using `(select public.is_owner())`, a `pipeline_write` policy, and `grant select, insert, update, delete ... to pipeline_rw`.
- [ ] **Step 4: Run** the schema tests. Expected: PASS.
- [ ] **Step 5: Commit** `feat: add grading columns and holding-action outcomes (migration 0009)`.

### Task 2: The pipeline's ledger

**Files:**
- Create: `pipeline/src/advisor/portfolio/__init__.py`, `pipeline/src/advisor/portfolio/ledger.py`
- Modify: `pipeline/src/advisor/store/repo.py` (add `load_trades`, `load_fx_rates`)
- Test: `pipeline/tests/unit/test_portfolio_ledger.py`, `pipeline/tests/integration/test_repo.py`

**Interfaces:**
- Produces in `ledger.py`:
  - `@dataclass(frozen=True) class Trade`: `side: str` ("buy"/"sell"), `account: str`, `symbol: str`, `asset_type: AssetType`, `qty: float`, `price: float`, `currency: str`, `fx_rate_cad: float | None`, `day: date`, `pick_id: int | None` (None for sells).
  - `@dataclass(frozen=True) class Position`: `account`, `symbol`, `asset_type`, `qty: float`, `cost_cad: float`, `opened_on: date`, `pick_id: int | None` (the latest `pick_id` among the buys since `opened_on`).
  - `@dataclass(frozen=True) class Loss`: `account`, `symbol`, `asset_type`, `day: date`. A sell that realized a loss.
  - `@dataclass(frozen=True) class Ledger`: `positions: list[Position]`, `losses: list[Loss]`, `problems: list[str]`.
  - `build_ledger(trades: Sequence[Trade], fx: Mapping[date, float]) -> Ledger`.
- Produces in `repo.py`:
  - `load_trades(conn) -> list[Trade]` (lots and sells);
  - `load_fx_rates(conn) -> dict[date, float]`;
  - `latest_fx_rate(conn) -> float | None`.

- [ ] **Step 1: Write the failing unit tests**, mirroring `web/lib/portfolio/ledger.test.ts` case for case:
  - `test_average_cost_per_account_and_asset`: two TFSA buys of AAPL (10 @ 200 USD at rate 1.4, then 10 @ 220 at 1.35) and one RRSP buy. TFSA AAPL is qty 20 with `cost_cad == 10*200*1.4 + 10*220*1.35`, and RRSP is separate.
  - `test_a_sell_reduces_quantity_at_average_cost_and_a_loss_is_recorded`: buy 10 @ 100 CAD, sell 4 @ 80. Left: qty 6, `cost_cad` 600. One `Loss` dated on the sell.
  - `test_a_days_buys_count_before_its_sells` and `test_a_sell_of_more_than_is_held_applies_to_what_is_held` (with a problem string).
  - `test_selling_out_and_buying_again_opens_a_new_position`: `opened_on` is the rebuy day, and `pick_id` is only the rebuy's.
  - `test_a_usd_trade_without_any_rate_is_left_out_with_a_problem` (Review Focus 2). A pre-rev-2 USD lot with `fx_rate_cad=None` and an empty `fx` gives no position and the problem `"AAPL on 2026-01-05: no USD/CAD rate for that day, so it's left out."`. A lot with `fx` holding an earlier day uses that day's rate.
- [ ] **Step 2: Run** the file. Expected: FAIL (module missing).
- [ ] **Step 3: Implement `build_ledger`**, in the web ledger's order and wording (read `web/lib/portfolio/ledger.ts` first).
- [ ] **Step 4: Write the failing `test_repo.py` test** `test_trades_and_rates_load_for_the_ledger`. It seeds a lot with `pick_id` null, a sell and two `fx_rates`, then checks `load_trades`, `load_fx_rates` and `latest_fx_rate`.
- [ ] **Step 5: Implement the three repo functions** and run both test files. Expected: PASS.
- [ ] **Step 6: Commit** `feat: build holdings at average cost in the pipeline`.

### Task 3: Trailing stops

**Files:**
- Create: `pipeline/src/advisor/portfolio/stops.py`
- Modify: `pipeline/src/advisor/store/repo.py` (add `previous_trailing_stops`)
- Test: `pipeline/tests/unit/test_portfolio_stops.py`, `pipeline/tests/integration/test_repo.py`

**Interfaces:**
- Produces:
  - `TRAIL_ATR = 2.5`;
  - `atr_pct(bars: Sequence[DailyBar], n: int = 14) -> float`: Wilder-free simple mean of true range over the last `n` bars, divided by the last close. It must match `features.atr_14_pct` for stocks. It's used for coins, which have no model features. NaN under `n + 1` bars.
  - `trailing_stop(closes: Sequence[float], last_close: float, atr_pct: float, previous: float | None, floor: float | None) -> float | None`:
    - computes `max(high − 2.5 × atr_pct × last_close, previous, floor)` over the values that exist, where `high` is `max(closes)`, or `last_close` when `closes` is empty;
    - returns None when the ATR is NaN and there's neither a `previous` nor a `floor`.
  - `repo.previous_trailing_stops(conn) -> dict[tuple[str, str, str], tuple[date, float]]`: per `(account, symbol, asset_type)`, the `feature_day` and `trailing_stop` of its newest `holding_actions` row that has both.

- [ ] **Step 1: Write the failing tests:**
  - `test_atr_pct_matches_the_model_feature`: for a 30-bar series, `atr_pct(bars)` equals `price_features(...)["atr_14_pct"]` on the last day (import from `advisor.model.features`; follow `tests/unit/test_model_features.py` for building bars).
  - `test_the_stop_is_the_highest_close_less_two_and_a_half_atr`: closes `[10, 12, 11]`, last 11, ATR 10% → `12 − 2.5 × 0.1 × 11 = 9.25`.
  - `test_the_stop_only_moves_up_and_never_below_the_original`: with previous 9.8 → 9.8; with floor 9.5 and no previous → 9.5.
  - `test_a_position_with_no_close_since_purchase_uses_the_last_close` (Review Focus 1): `closes=[]`, last 20, ATR 5% → `20 − 2.5`.
  - `test_no_atr_and_no_memory_gives_no_stop`: NaN ATR → None. NaN ATR with previous 7 → 7.
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement** `stops.py` and `repo.previous_trailing_stops`, plus an integration test `test_the_newest_trailing_stop_per_holding_is_remembered`: two runs for the same holding, and the newer run's stop wins.
- [ ] **Step 4: Run** both test files. Expected: PASS.
- [ ] **Step 5: Commit** `feat: trailing stops that only move up`.

### Task 4: The action rules

**Files:**
- Create: `pipeline/src/advisor/portfolio/actions.py`
- Test: `pipeline/tests/unit/test_portfolio_actions.py`

**Interfaces:**
- Consumes: `choose`, `best_horizon` (`advisor.recommend.picks`), `AVOID_P` (`advisor.recommend.verdicts`), `PredictionRow`.
- Produces:
  - `GAIN_TRIM = 0.25`, `MOMENTUM_TRIM = 40.0`, `TAXABLE = frozenset({"crypto", "non_registered"})`.
  - `@dataclass(frozen=True) class Holding`, everything one holding's action reads:
    - `account: str`, `symbol: str`, `asset_type: AssetType`, `benchmark: str | None`;
    - `price: float` (native latest close), `value_cad: float`, `cost_cad: float`, `portfolio_cad: float`, `trailing_stop: float | None`;
    - `rows: list[PredictionRow]` (finite, usable horizons; empty = no forecast), `why_no_forecast: str | None`, `cost: float`, `sane: bool`;
    - `risk_level: str`, `max_position_pct: float`, `momentum_pct: float | None` (ret_21 percentile, 0–100);
    - `signals_reversed: bool | None` (None: not linked to a pick, or not checkable);
    - `review: list[str]` (the Review badge's reasons), `sold_at_loss_on: date | None` (newest taxable loss within 30 days of this asset, any account).
  - `@dataclass(frozen=True) class Action`:
    - `action: str` (sell/trim/add/hold), `review: bool`, `reasons: list[str]`, `warnings: list[str]`;
    - `horizon: int | None`, `q10`, `q50`, `q90: float | None`.
  - `decide(h: Holding) -> Action`.
- **The rules, in this order** (spec §7.3 plus the owner's size decision; the first that fires wins):
  1. **Sell**, if any of these hold. Every one that holds goes in `reasons`.
     - `price <= trailing_stop`. Reason: `"closed at {price}, under its trailing stop {stop}"`, both with `fmt` = 2 decimals, or 4 significant figures under 1.
     - `best_horizon(rows).p_beat <= AVOID_P`. Reason: `"P(beat {benchmark}) {p:.2f} over {h} trading days"`.
     - `signals_reversed is True`. Reason: `"the signals behind its pick have reversed"`.
  2. **Trim**, if `rows` is non-empty and `momentum_pct` is known, with `(value_cad / cost_cad − 1) >= 0.25` and `momentum_pct < 40`. Reason: `"up {gain:.0%} and its 21-day momentum is at the {pct:.0f}th percentile"`.
  3. **Add**, if `choose(rows, cost, sane)` qualifies and `100 × value_cad / portfolio_cad < max_position_pct`. Reason: `"would be a Buy today: P(beat {benchmark}) {p:.2f} over {h} trading days, below its max size"`.
  4. **Hold** otherwise. The reason is `why_no_forecast` when `rows` is empty, else `"no rule fired"`.
  - **Horizon and range:** for Add, the chosen horizon. For Sell, Trim or Hold with rows, `best_horizon(rows)`. With no rows: None, so no exit-by and no grading.
- **Warnings** (never change the action):
  - **Over size:** when `100 × value_cad / portfolio_cad > max_position_pct`: `"{share:.0f}% of the portfolio; {Level} risk allows {max:g}%"`.
  - **A Sell at a loss in a taxable account** (`value_cad < cost_cad`): `"selling at a loss: buying it again within 30 days before or after the sale denies the loss (superficial loss)"`.
  - **An Add with `sold_at_loss_on` set** (Add in any account, loss in a taxable one): `"sold at a loss on {date}: adding now denies that loss (superficial loss)"`.
- **Review:** `review = bool(h.review)`, and `h.review` is appended to `reasons`.

- [ ] **Step 1: Write the failing tests**, one per rule and boundary. Build `Holding`s with a small factory.
  - `test_a_hit_trailing_stop_sells_whatever_the_forecast` (price equal to the stop sells).
  - `test_a_best_horizon_at_or_under_0_42_sells`: 0.42 sells, 0.43 doesn't.
  - `test_reversed_pick_signals_sell`.
  - `test_a_big_gain_with_fading_momentum_trims`: gain exactly 25% with momentum 39.9 trims. Gain 24.9% or momentum 40 → Hold.
  - `test_oversize_is_a_warning_never_a_trim` (owner decision): a holding at 36% with max 1.5% and nothing else firing gives Hold plus the size warning. If it qualifies as a Buy, it is still not an Add.
  - `test_a_qualifying_holding_below_its_max_adds`, using `choose`'s own boundary row (p 0.58, q50 just over cost).
  - `test_without_a_forecast_only_the_stop_can_act` (§10): no rows, gain 40%, momentum 10 → Hold with the `why_no_forecast` reason. With the stop hit → Sell.
  - `test_review_is_a_badge_on_top_of_the_action`: Sell with an earnings review → Sell, `review=True`, both reasons present.
  - `test_tax_warnings_only_in_taxable_accounts`:
    - a TFSA Sell at a loss has no warning; a crypto Sell at a loss has one;
    - an Add with `sold_at_loss_on` has one in any account;
    - none of these changes the action.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement `decide`.**
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat: holding actions by the spec's rules, size as a warning`.

### Task 5: The holdings stage

**Files:**
- Create: `pipeline/src/advisor/portfolio/stage.py`
- Modify:
  - `pipeline/src/advisor/recommend/stage.py`: `recommend_market` also returns its risk frame, and `recommend_stage` also returns `dict[Market, MarketAdvice]`.
  - `pipeline/src/advisor/store/repo.py`: add `write_holding_actions` and `load_picks(conn, ids)`.
  - `pipeline/src/advisor/run.py`: call `advise_stage` after `recommend_stage`, and add `summary["actions"]` and its degrade.
- Test: `pipeline/tests/unit/test_portfolio_stage.py`, `pipeline/tests/unit/test_recommend_stage.py` (unpacking), `pipeline/tests/integration/test_run.py`

**Interfaces:**
- Consumes: Tasks 2–4; `StockInputs`, `scheduled_events`, `risk_frame`/`risk_levels` (through `MarketAdvice`); `sessions_after`; `MarketModel.active.model.contributions(x, h, top=len(features))`.
- Produces:
  - In `recommend/stage.py`: `@dataclass(frozen=True) class MarketAdvice`, holding `inputs: StockInputs` and `risk: pd.DataFrame` (indexed by symbol, with `risk_level` and `max_position_pct`). Every population stock is in it, not just the qualifying ones.
  - `recommend_market(...)` returns `(picks, details, summary, risk)`.
  - `recommend_stage(...)` returns `(summary, verdicts_failure, advice: dict[Market, MarketAdvice])`.
  - In `portfolio/stage.py`, `advise_stage(conn, run_id, *, models, forecasts, advice, bars, flagged, quotes, candles, crypto_features, results, kind, now_utc) -> dict`. It returns `summary["actions"]`, `{"written": n, "by_action": {...}}`, or `model_failure(exc)`.
  - `repo.write_holding_actions(conn, run_id, rows: Sequence[HoldingActionRow])`.
  - `HoldingActionRow` in `advisor.models`: `account, symbol, asset_type, action, review, reasons, warnings, trailing_stop, q10, q50, q90, exit_by, horizon_days, feature_day, ref_price, bench_ref_price, risk_level, max_position_pct`.
- **How each input is built** (the decisions; read stage 8 first):
  - **Positions:** `build_ledger(repo.load_trades(conn), repo.load_fx_rates(conn))`. Ledger problems go in `summary["actions"]["problems"]`.
  - **Market and feature day:**
    - A stock's market comes from `market_of`, its feature day from `feature_day(market, bars, kind, now_utc)`. `same_day` from there sets the Review window as in `hold_events`.
    - A coin's feature day is its last candle's day.
  - **Price and value:**
    - A stock's `price` is `bars[s][-1].close`. Its `value_cad` is `price × qty × (latest_fx_rate if US else 1)`.
    - A coin's `price` is `candles[s][-1].close` (USD). Its `value_cad` is `quotes[s].price_cad × qty`, falling back to the candle × the rate.
    - A holding with neither keeps `value_cad = cost_cad` and gets the reason `"not priced this run"`.
  - **Portfolio value:** the sum of every position's `value_cad`.
  - **Trailing stop:**
    - The ATR is `forecast.features.at[s, "atr_14_pct"]` for a forecast stock, else `atr_pct(bars or candles)`.
    - The closes are the bar or candle closes with `day >= opened_on`.
    - `previous` comes from `previous_trailing_stops`, used only when its `feature_day >= opened_on`.
    - The `floor` is the linked pick's `stop` (`repo.load_picks`) when `pick_id` is set, else None.
  - **Forecast rows, cost, sanity:** `advice[market].inputs.rows/cost/sane`.
    - With no rows, `why_no_forecast` is chosen exactly as `watch_verdicts` does: "not priced this run", `NOT_ELIGIBLE`, "no forecast this run", or the market's `no_forecast` reason.
    - For a coin it is `"no crypto model yet"`.
  - **Risk:** `advice[market].risk` for population stocks. Everything else, coins included, gets `very_high` / 0.5 (spec §6.4: a stock with every component missing).
  - **Momentum:** the percentile rank (0–100, `rank(pct=True) × 100`) of `ret_21` among `advice[market].inputs.rows` keys, read from `forecast.features`. None outside the population.
  - **Signals reversed:** only for a linked pick whose horizon is in this run's rows.
    - Take the pick's `top_factors` with a non-zero contribution, and today's contributions of the same features at the same horizon.
    - It's reversed when more than half have flipped sign.
  - **Review reasons:**
    - Each `scheduled_events` event within `sessions_after(market, day, 5)`: `"earnings on {Mon D}"` or `"phase 2/3 trial completion on {Mon D}"`.
    - `"the latest bar is a flagged, unconfirmed jump"` when `bars[s][-1].day in flagged[s]`, or for a coin when `crypto_features[s]["unconfirmed_price"] is True`.
  - **Superficial loss:** `sold_at_loss_on` is the newest `Loss` of the same symbol and asset type, in a taxable account, within 30 days of today.
  - **Exit-by:** `sessions_after(market, day, horizon)` when there's a horizon. For a linked pick still open, the pick's `exit_by` when it's later.
  - **Grading fields:** `ref_price = price`, and `bench_ref_price = bars[MARKETS[market].benchmark][-1].close` for stocks (None for coins).
- **Writing:** all rows in one transaction, after stage 8's writes.

- [ ] **Step 1: Adjust stage 8 first.** Change `recommend_market` and `recommend_stage` to the new returns, and fix the unpacking in `test_recommend_stage.py` and `test_run.py`. Run `pytest -q tests/unit/test_recommend_stage.py tests/integration/test_run.py -k "pick or verdict or recommend"`. Expected: PASS, with nothing else changed.
- [ ] **Step 2: Write the failing unit tests** for `stage.py`'s input building, with pure helpers split out so they test without a database: `holding_inputs(...) -> list[Holding]` and `action_rows(...) -> list[HoldingActionRow]`.
  - `test_a_forecast_stock_reads_stage_8s_rows_risk_and_momentum`.
  - `test_a_stock_without_a_forecast_says_why` (Review Focus 3). The cases are ineligible, and a market missing from `forecasts` with the reason "the model failed this run".
  - `test_a_coin_is_valued_from_its_quote_and_stopped_on_its_candles`.
  - `test_a_coin_without_candles_holds_without_a_stop` (Review Focus 4).
  - `test_one_stock_in_two_accounts_gets_two_rows`.
  - `test_the_review_window_is_five_sessions_and_includes_today_at_pre_close`.
  - `test_reversed_signals_need_most_of_the_picks_factors_flipped`: 2 of 3 flipped → True, 1 of 3 → False.
- [ ] **Step 3: Run.** Expected: FAIL.
- [ ] **Step 4: Implement** `stage.py`, `HoldingActionRow`, `repo.write_holding_actions` and `repo.load_picks`.
- [ ] **Step 5: Wire it into `run.py`.**
  - Keep the crypto rows: today `crypto_feature_rows(...)` goes straight to `write_features_live`. Hold it in a variable first, and pass `crypto_features = {ref.symbol: f for ref, f in rows}`. Without held coins it's `{}`.
  - Call `advise_stage` right after `recommend_stage`, inside `if enriched:`, guarded the same way (an outer `try` that records `model_failure`).
  - Add `summary["actions"]`.
  - `models_ok` also requires `"failed" not in summary["actions"]`.
- [ ] **Step 6: Write the failing `test_run.py` tests:**
  - `test_holdings_get_actions_and_a_coin_gets_the_fallback`: seed a TSX lot and a coin lot with the existing `tsx_model_files` fixture.
    - One `holding_actions` row each.
    - The stock's row has `horizon_days`, `exit_by`, `ref_price` and `bench_ref_price`.
    - The coin's row is Hold with reason `"no crypto model yet"`.
  - `test_an_actions_failure_degrades_the_run_and_prices_still_publish`: monkeypatch `advisor.portfolio.stage.decide` to raise. The run is `degraded` and published, and `summary["actions"]["failed"]` is present.
- [ ] **Step 7: Run** the full pipeline suite. Expected: all PASS.
- [ ] **Step 8: Commit** `feat: write an action for every holding each run`.

### Task 6: Picks record their feature day and benchmark price; exit early

**Files:**
- Modify: `pipeline/src/advisor/models.py` (`PickRow` gains `feature_day: date`, `bench_ref_price: float`), `pipeline/src/advisor/recommend/stage.py`, `pipeline/src/advisor/store/repo.py` (`write_picks`, plus `open_picks(conn)` and `mark_exited_early(conn, ids, run_id)`)
- Create: `pipeline/src/advisor/grade.py` (`exit_early` only in this task)
- Test: `pipeline/tests/unit/test_grade.py`, `pipeline/tests/integration/test_run.py`

**Interfaces:**
- Produces:
  - `OpenPick` (dataclass): `id, symbol, market, horizon_days, exit_by, entry_ref_price, stop, feature_day, bench_ref_price, run_kind`.
  - `repo.open_picks(conn) -> list[OpenPick]`: status `open`.
  - `exit_early(picks: Sequence[OpenPick], rows: Mapping[str, list[PredictionRow]]) -> list[int]`: the ids whose row at the pick's own horizon has `p_beat <= AVOID_P`. A pick with no row at its horizon this run isn't flagged.
  - `repo.mark_exited_early(conn, ids)` sets `status = 'exited_early'`. Task 7 calls `exit_early` and grades the flagged picks in the same run, at that run's close, so no flag day needs storing.
- **When:** exit-early runs only when `kind in PARTIAL_KINDS` (pre-close and early-close, spec §6.5 "the pre-close run re-checks"). A hit stop is graded every run, in Task 7. This task builds and tests `exit_early`; Task 7 wires it in.

- [ ] **Step 1: Write the failing tests:**
  - `test_a_pick_records_its_feature_day_and_benchmark_close` (extend the existing stage-8 picks test in `test_run.py`: the written pick's `feature_day` is the market's feature day, and `bench_ref_price` is XIU.TO's last close).
  - `test_exit_early_flags_a_pick_whose_p_fell_to_0_42`: 0.42 flagged, 0.43 not, and a pick with no row at its horizon is not flagged.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.** Fill `feature_day=inputs.day` and `bench_ref_price=bars[benchmark][-1].close` in `recommend_market`.
- [ ] **Step 4: Run** the full suite. Expected: PASS.
- [ ] **Step 5: Commit** `feat: record a pick's feature day and benchmark price, and flag exits`.

### Task 7: Grading (stage 9)

**Files:**
- Modify: `pipeline/src/advisor/grade.py`, `pipeline/src/advisor/store/repo.py`, `pipeline/src/advisor/run.py`
- Test: `pipeline/tests/unit/test_grade.py`, `pipeline/tests/integration/test_run.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class Outcome`: `exit_day: date`, `exit_price: float`, `exit_reason: str` (`"stop"`, `"exit_by"` or `"exit_early"`), `ret`, `ret_net_of_fx`, `bench_ret`, `excess: float`, `beat: bool`, `hit_stop: bool`.
  - `grade(entry: float, stop: float | None, feature_day: date, exit_by: date, closes: Mapping[date, float], bench_ref: float, bench_closes: Mapping[date, float], fee_pct: float, us: bool, exit_now: date | None = None) -> Outcome | None`:
    - Walk the closes after `feature_day` up to `exit_by`. The first close ≤ `stop` exits there (`"stop"`, `hit_stop=True`).
    - Otherwise, once a close exists on a day ≥ `exit_by`, exit at the close on `exit_by`, or the last one before it (`"exit_by"`).
    - With `exit_now`, exit at that day's close (`"exit_early"`).
    - The benchmark exits on the same day.
    - `ret_net_of_fx = ret − 2 × fee_pct / 100` for US, and `ret` for TSX.
    - `excess = ret − bench_ret`, `beat = excess > 0`.
    - Returns None while the exit's close (or the benchmark's) is missing (Review Focus 5).
  - `grade_stage(conn, run_id, bars, rows: Mapping[str, list[PredictionRow]], kind, now_utc) -> dict` returns `summary["graded"]` (`{"picks": n, "exited_early": k, "actions": m}`, or `model_failure(exc)`). `rows` is every market's `advice[m].inputs.rows` merged. It does three things:
    1. On a `PARTIAL_KINDS` run, calls `exit_early(repo.open_picks(conn), rows)`, marks those picks, and grades them now with `exit_now` = their market's feature day. Status stays `exited_early`. Then it grades the other open picks into `pick_outcomes`, and their status becomes `graded`.
    2. grades `holding_actions` with `exit_by` set and no outcome into `holding_action_outcomes`. The stop is the row's `trailing_stop`, the entry `ref_price`, the benchmark `bench_ref_price`.
    3. reads closes from `bars`, falling back to `repo.stored_closes` for a symbol not in this run's bars.
  - Repo additions: `actions_to_grade(conn)`, `write_pick_outcomes(conn, rows)`, `write_action_outcomes(conn, rows)`, `set_pick_status(conn, ids, status)`.

- [ ] **Step 1: Write the failing unit tests** for `grade`:
  - `test_a_hit_stop_exits_at_the_first_close_under_it`.
  - `test_without_a_stop_hit_the_exit_is_the_close_on_exit_by`, including exit-by on a holiday, which uses the last close before it once a later close exists.
  - `test_us_returns_are_also_shown_net_of_the_conversion_fee`: fee 1.5 → `ret − 0.03`. TSX is unchanged.
  - `test_nothing_is_graded_until_the_exit_close_exists` (Review Focus 5).
  - `test_an_early_exit_grades_at_that_days_close`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement `grade`, `grade_stage` and the repo functions.** Wire `grade_stage` into `run.py` after `advise_stage` (stage 9) with the same guard, and add `summary["graded"]` and its degrade.
- [ ] **Step 4: Write the failing `test_run.py` tests:**
  - `test_a_holding_action_past_its_exit_by_is_graded`: seed a `holding_actions` row from an earlier run with `exit_by` in the bars' past. After a run there is one `holding_action_outcomes` row with the expected `ret` and `bench_ret`.
  - `test_an_open_pick_whose_stop_is_hit_is_graded_and_closed`.
- [ ] **Step 5: Run** the full suite and ruff. Expected: all PASS, ruff clean.
- [ ] **Step 6: Commit** `feat: grade picks and holding actions when their time is up`.

### Task 8: My Portfolio shows the actions

**Files:**
- Create: `web/lib/data/actions.ts`, `web/lib/portfolio/actions.ts`, `web/lib/portfolio/actions.test.ts`
- Modify:
  - `web/components/portfolio/Cards.tsx` (`ActionsCard`, `HoldingsCard`);
  - `web/app/(app)/page.tsx`;
  - `web/lib/portfolio/view.ts`: `HoldingRow` gains `action`. Also fix `SellOption.lastClose` for coins (below).
  - `web/e2e/db.ts` (`seedHoldingAction`), `web/e2e/portfolio.spec.ts`.
- Follow: `.superdesign/design_iterations/portfolio_1.html`, lines 112–160 (the Actions card) and 200–240 (the holdings table's model columns). The CSS (`.action-card`, `.chip.sell|trim|review|add|hold`, `.hold-toggle`, `.range`) is already in `web/app/styles/ledger.css`.

**Interfaces:**
- Produces:
  - `HoldingAction` (TS):
    - `account: Account`, `symbol: string`, `assetType: AssetType`, `action: 'sell' | 'trim' | 'add' | 'hold'`, `review: boolean`;
    - `reasons: string[]`, `warnings: string[]`;
    - `trailingStop: number | null`, `q10`, `q50`, `q90: number | null`, `horizonDays: number | null`, `exitBy: string | null`;
    - `riskLevel: 'low' | 'medium' | 'high' | 'very_high' | null`.
  - `loadHoldingActions(supabase): Promise<{ runId: number; actions: HoldingAction[] } | null>`: the rows of the newest published run that has any.
  - `actionGroups(actions: HoldingAction[]): { cards: HoldingAction[]; hold: HoldingAction[] }`:
    - `cards` are ordered Sell → Trim → Review → Add. Review means a Hold or Add with `review`. A Sell or Trim with `review` stays in its own group.
    - Within a group, cards sort by symbol.
    - `hold` is the Holds without review.
  - A coin's `SellOption.lastClose` is the latest close converted to CAD with the latest rate, `currency: 'CAD'`, or null with no rate.
    - Why: coin closes are stored in USD (Coinbase), but coins trade in CAD. Without this, a holdings-report import errors on any coin the report no longer lists.
  - Two §7.4 portfolio checks that need the model's risk levels or the stock sectors (in `lib/portfolio/valuation.ts`, beside `breakdown`):
    - `byRisk(holdings, actions): Slice[]`: value by risk level. A holding with no action row is "Not rated".
    - `sectorWarnings(holdings, sectors: Map<string, string>): Warning[]`: one warning per sector above **25%** of the portfolio's value: `"{Sector} is {share}% of the portfolio (guideline 25%)"`. Coins and unlabelled stocks count toward the total but belong to no sector.
    - `loadNames` gains a sibling, `loadSectors(supabase, symbols)`, which reads `symbols.sector`.

- [ ] **Step 1: Write the failing Vitest tests:**
  - `actions.test.ts`:
    - `actionGroups orders Sell, Trim, Review, Add, and folds plain Holds`;
    - `a Sell with a review badge stays a Sell card`.
  - `view.test.ts`: `a coin's last close is offered in CAD`. ETH's USD close 2800 at rate 1.4 gives `{ close: 3920, currency: 'CAD' }`. Update the existing sell-option close test to match.
  - `valuation.test.ts`:
    - `byRisk groups value by the action's risk level, unrated last`;
    - `a sector over 25% of the portfolio is warned about`: exactly 25% isn't, and coins never are.
- [ ] **Step 2: Run** `npm test`. Expected: FAIL.
- [ ] **Step 3: Implement** the data loader, `actionGroups`, the view change, and the two cards.
  - **The Actions card** follows the mockup:
    - Each card shows the chip, the account, the symbol and name, the first reason (`reasons[0]`) as the sentence, and P/L from the holding row.
    - A Review card's chip line reads `"{Account} · {Action}"`.
    - A Hold toggle lists the plain Holds with `hold ~{horizonDays} days · exit by {shortDay}`, or with the reason when there's no horizon.
    - With no actions, the current empty state stays, with its text changed to: "Actions appear after the next run that forecasts your holdings."
  - **The holdings table** adds Action (chip, plus a Review chip), Likely range (the `.range` bar from q10/q50/q90 and `{h}d`), Trailing stop (`fmtPrice` in the asset's currency: USD for US stocks and coins, CAD for TSX), Exit by, and Risk (badge with dot). `warnings` join the Notes column with the warning icon.
  - A holding with no action row (bought after the run) shows "—" in those columns.
  - The holdings card's "appear once the model runs" note shows only when there are no actions.
  - `BreakdownCard` adds "By risk" (spec §7.4), and `WarningsCard` receives the sector warnings with the others.
- [ ] **Step 4: Write the failing Playwright test** in `portfolio.spec.ts`: `the actions of the latest run fill the Actions card and the holdings table`.
  - Seed two lots, a published run, and a Sell and a Hold `holding_actions` row through a new `seedHoldingAction` helper.
  - Expect a Sell card with its reason, the Hold toggle naming the held symbol, and the holdings table's Action chips and trailing stop.
- [ ] **Step 5: Run** `npm test`, `npm run lint`, `npm run typecheck` and `npx playwright test`. Expected: all PASS.
- [ ] **Step 6: Commit** `feat: show each holding's action on My Portfolio`.

### Task 9: Documents

**Files:**
- Modify: `docs/superpowers/specs/2026-10-09-stock-advisor-design.md`, `docs/superpowers/deferred.md`

- [ ] **Step 1: Update the spec:**
  - **§7.3:** add the owner's decision of 2026-10-27, that size is a warning and not a Trim, with its reason. Also add how "the main signals behind that pick have reversed" is decided: more than half of the pick's top factors flipped sign at its horizon.
  - **§4.3 stages 8 and 9:** holding actions and grading are built, and their failures degrade the run (`summary.actions`, `summary.graded`).
  - **§8:** the new columns and `holding_action_outcomes`.
  - **§6.5:** grading uses closes, so a stop counts as hit on a close at or under it, and exit-early grades at the flagging run's close.
- [ ] **Step 2: Update `deferred.md`:**
  - Move Plan 4c out of "what is left after 4a".
  - Add a "Plan 4c known limits" section:
    - holdings outside a forecast population are Very High by default;
    - coins have no model, so they get stops only;
    - ungraded rows wait for closes;
    - grading by closes, not intraday lows;
    - §7.5's one-time note on US dividend payers in a TFSA isn't built: no source says which stocks pay dividends.
  - Remove the "A table for holding-action outcomes" open point.
- [ ] **Step 3: Commit** `docs: record Plan 4c in the spec and the deferred list`.

---

## Owner steps after merge

1. **Apply migration 0009 to the hosted database** with `ADMIN_DATABASE_URL`, the way 0008 was applied. Until then, the holdings stage fails and degrades every run.
2. **Push `main`.** The next pre-open or pre-close run writes the first actions.
