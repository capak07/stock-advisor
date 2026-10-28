# Plan 6b: The Crypto Model — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Coins get the same outputs as stocks (q10/q50/q90 and calibrated P(beat benchmark), over 7, 14, 30, 90 and 180 days) from a model trained weekly on keyless Coinbase history. Held and watched coins then get real forecasts, Buy/Hold/Avoid verdicts and holding actions, in place of "no crypto model yet". The model and its policy are judged by the same benchmark as the stocks.

**Architecture:**
- **Crypto is not a `Market` enum member.** The pipeline loops over `Market` (US and TSX) in many places. Crypto runs as its own path, keyed by the string `CRYPTO = "crypto"` (`advisor/model/crypto.py`), which is also its key in `models.kind`, `accepted_configs` and `benchmark_results` (all already allow it).
- **It reuses `walk_forward`, `fit_final`, `run_variant`, the benchmark harness, `simulate_book` and the policy search unchanged,** apart from the market-specific costs and swing horizons.
- **Live,** the run forecasts held and watched coins from their Coinbase candles. Feature code is shared between training and live, so the two can't drift.

**Tech Stack:** Python 3.12, pandas, numpy, LightGBM, httpx; pytest, ruff. No new dependency.

**Spec:** `docs/superpowers/specs/2026-10-28-prediction-upgrade-design.md`:
- §2 the crypto model;
- builder-check decisions 5 (calendar days) and 6 (crypto's policy);
- §6 and §7.

Also the main spec §5.4: coins never appear in pick lists; altcoins are judged against BTC, and BTC against SPY.

## Global Constraints

- **`CRYPTO = "crypto"`.** Coins quote in USD. Values are shown in CAD at the Bank of Canada rate, as today.
- **Horizons:** `CRYPTO_HORIZONS = (7, 14, 30, 90, 180)` calendar days ★.
- **Rows:** one per coin every `CRYPTO_SAMPLE_EVERY = 7` days ★.
- **Warm-up:** `CRYPTO_WARMUP = 252` days of closes before a coin's first row.
- **The universe on each sample day:** the top `UNIVERSE = 100` ★ coins by trailing 30-day mean USD dollar volume, among coins that have at least 252 days of closes and a close that day, and aren't excluded. Stablecoins and wrapped or pegged coins are excluded:
  - the fixed list `EXCLUDED = {"USDT", "USDC", "DAI", "PAX", "USDP", "PYUSD", "GUSD", "BUSD", "TUSD", "FDUSD", "EURC", "WBTC", "CBBTC", "CBETH", "WETH", "STETH"}`;
  - plus any coin whose `vol_60` that day is under 0.005, a peg in effect.
- **Targets:**
  - an altcoin's forward return over h days minus BTC's over the same days;
  - BTC's minus SPY's, where SPY's close on each day is its last close on or before it (forward-filled onto the calendar).
- **Features:** the stock `PRICE_FEATURES`, computed on the daily coin frames (so their windows count days), plus `ex_btc_21` and `ex_btc_63` (the coin's `ret_21`/`ret_63` minus BTC's). No sector, fundamental or on-chain features.
- **Costs:**
  - `round_trip_cost(CRYPTO, dollar_volume, crypto_fee_pct)` is the spread from dollar volume plus `2 × crypto_fee_pct / 100`, the same formula as US with the crypto fee;
  - swing horizons for crypto are `{7, 14}`;
  - `crypto_fee_pct` is `repo.fee_settings(conn)[1]`.
- **Gates:**
  - **Promotion** is the stock rule (calibration ≤ 5 points; rank IC against the active model's; the 28-day age rule).
  - **Coins never become picks,** so the weekly job records `picks_enabled: false` with the reason `"coins are never picks (spec §5.4)"`.
  - **A watched coin's Buy verdict has no market gate** (builder-check decision 6).
- **Policy (decision 6):** crypto's policy row runs `simulate_book` on the universe with each coin as its own sector, so the sector cap never binds, approximating a "follow the verdicts" book. The same hard limits apply.
- **Fallback:** with no active crypto model, every coin keeps today's behaviour exactly: `NO_COIN_MODEL` and trailing stops from candles.
- **Tests and Git:** as in Plan 6e. Tests run in Docker; run `git commit` in its own command, never with `--no-verify`. Only Claude's commits get the co-author trailer. Don't push.

## Review Focus

1. **A coin listed only recently** (under 252 days) must get no training row and no live forecast, with `why_no_forecast` saying how many days it has. It must not get a forecast from half-empty windows. Pinned in Tasks 2 and 4.
2. **BTC's target on a day SPY didn't trade** (weekends and US holidays) must use SPY's previous close, never NaN-drop BTC's weekend rows or read a later SPY close. Pinned in Task 2.
3. **A delisted Coinbase product with gaps** must not stall the build or fabricate closes. A 404 or empty page means "no more history". Pinned in Task 1.
4. **The live run with no BTC candles** (Coinbase down) must leave every coin unforecast with that reason, not raise. Pinned in Task 4.
5. **Coins must never reach the pick lists or the picks gate,** whatever their P. Pinned in Task 4.

---

### Task 1 (Cursor): Full Coinbase history in the training build

**Files:**
- Create: `pipeline/src/advisor/training/crypto.py`
- Modify: `pipeline/src/advisor/training/build.py`
- Test: `pipeline/tests/unit/test_training_crypto.py`, `pipeline/tests/unit/test_training_build.py`

**Interfaces:**
- **`list_products(client) -> list[str]`:** `GET https://api.exchange.coinbase.com/products`. Keep base currencies of products with `quote_currency == "USD"`, whatever their `status`, sorted and de-duplicated.
- **`fetch_history(client, symbol, end: date, limiter) -> pd.DataFrame`:**
  - pages `/products/{symbol}-USD/candles?granularity=86400` backwards, 300 days a request, until a page is empty, a 404 comes back, or 2015-01-01 is reached;
  - returns `symbol, day, open, high, low, close, volume`, oldest first, finished days only (before `end`);
  - parse with `coinbase_candles.parse_candles`.
- **`build` writes `prices_crypto.parquet`** in Plan 3a's long layout. Its manifest records the count of coins, rows and failures. One coin's failure is counted, never fatal. **The whole crypto step failing doesn't fail the stock build:** the manifest records `crypto_error`, and crypto training is then skipped that week.
- **Rate limit:** reuse `RateLimiter(COINBASE_PER_MINUTE)`. Expect about 3,000 requests, roughly 5 minutes.

- [ ] **Step 1: Tests**, with an `httpx.MockTransport` like `test_coinbase_candles.py`:
  - products keep only USD bases, including delisted ones;
  - paging joins 2 pages and stops on an empty page;
  - a 404 gives an empty frame;
  - today's candle is dropped;
  - `build` writes the parquet and the manifest counts;
  - a crypto step that raises leaves the stock files and sets `crypto_error`.
- [ ] **Steps 2–4:** fail, then implement, then pass. The full suite and ruff pass.
- [ ] **Step 5:** Commit `feat: the training build downloads full Coinbase history for every USD product`.

---

### Task 2 (Claude): The crypto dataset

**Files:**
- Create: `pipeline/src/advisor/model/crypto.py`
- Test: `pipeline/tests/unit/test_model_crypto.py`

**Interfaces:**
- **The constants above,** plus `CRYPTO_FEATURES = PRICE_FEATURES + ["ex_btc_21", "ex_btc_63"]`.
- **`crypto_frames(prices: pd.DataFrame) -> tuple[Wide, dict[str, pd.DataFrame], pd.DataFrame]`:** the wide frames on the calendar of days with a BTC close; the features (`CRYPTO_FEATURES`, full calendar); and USD dollar volume. Training and live both call it.
- **`load_crypto(data_dir: Path) -> MarketData`:**
  - `market` is `CRYPTO`;
  - rows hold `day, symbol, sector (None), dollar_volume_20, y_7…y_180, *CRYPTO_FEATURES`;
  - `features` is `CRYPTO_FEATURES`;
  - the calendar is every day with a BTC close.
  
  `MarketData.market`'s annotation widens to `Market | str`.
- **SPY for BTC's target** comes from `prices_US.parquet` (its `SPY` rows), forward-filled onto the crypto calendar.

- [ ] **Step 1: Tests**, on a synthetic `prices_crypto.parquet` plus a `prices_US.parquet` with SPY on weekdays only:
  - **`test_rows_are_weekly_and_in_the_universe`:**
    - row days are 7 apart, starting after 252 days;
    - a coin with 200 days of history has no rows;
    - USDT and a flat coin are excluded;
    - with 105 eligible coins, only the top 100 by 30-day dollar volume appear.
  - **`test_altcoins_are_judged_against_btc_and_btc_against_spy`:** hand-computed `y_7` for an altcoin and for BTC on a Saturday, where SPY's Friday close is used.
  - **`test_features_are_known_on_their_day`:** changing every close after day t leaves all features of rows dated ≤ t identical. Changing closes after t + h changes no `y_h` dated ≤ t.
  - **`test_the_embargo_counts_calendar_days`:** `training_rows(rows, calendar, 30, start)` keeps only rows whose day + 30 days < `start`.
  - **`test_walk_forward_trains_on_crypto`:** `walk_forward(load_crypto(...), TrainConfig(horizons=CRYPTO_HORIZONS, rounds=20, …))` returns predictions for every horizon with targets.
- [ ] **Steps 2–4:** fail, then implement, then pass. The unit suite and ruff pass.
- [ ] **Step 5:** Commit `feat: the crypto dataset: weekly rows over the top coins, judged against BTC (BTC against SPY)`.

---

### Task 3 (Claude): Weekly training and the benchmark include crypto

**Files:**
- Modify: `model/backtest.py` (`round_trip_cost` and the swing horizons per market); `benchmark/simulate.py` (`daily_panel` for crypto); `model/weekly.py`; `benchmark/job.py`
- Test: their existing test files, plus new crypto cases

**Interfaces:**
- **`round_trip_cost(market, dollar_volume_20, fee_pct)`:** `market` may be `CRYPTO`, which charges the fee both ways. `swing_horizons(market) -> frozenset[int]` is `{5, 10, 20}` for stocks and `{7, 14}` for crypto. It's used wherever `SWING_HORIZONS` decides a style.
- **`daily_panel(data_dir, CRYPTO)`:** the coin closes and ATR on the BTC calendar, with the benchmark `"BTC"`.
- **`weekly.run(..., crypto: bool = True)`:**
  - crypto trains after TSX and US, as the kind `"crypto"`, with versions `crypto-YYYYmmddHHMM`;
  - its config is read via `config_for(conn, CRYPTO)`;
  - it's skipped, with a report reason, when the manifest has `crypto_error` or `prices_crypto.parquet` is missing;
  - the report key is `"crypto"`.
- **`benchmark.job`:** `MARKET_ORDER` gains crypto last. A crypto market loads with `load_crypto`, uses `crypto_fee_pct` and `TrainConfig(horizons=CRYPTO_HORIZONS)`, and uses each coin as its own sector in the policy row. Its accepted config is keyed `"crypto"`.

- [ ] **Step 1: Tests:**
  - the crypto cost and swing set;
  - the weekly job trains, stores and promotes a `crypto` model from synthetic data, with `picks_enabled` false and the coin reason;
  - the weekly job skips crypto with a reason on `crypto_error`;
  - a benchmark run on synthetic crypto writes `benchmark_results` rows for `crypto` and accepts the baseline.
- [ ] **Steps 2–4:** fail, then implement, then pass. The full suite and ruff pass.
- [ ] **Step 5:** Commit `feat: weekly training and the monthly benchmark include the crypto model`.

---

### Task 4 (Cursor): Live forecasts, verdicts and actions for coins

**Files:**
- Modify: `run.py` (load the active `crypto` model; forecast held and watched coins); `crypto_prices.py` or a new `model/crypto_live.py`; `recommend/verdicts.py` (`coin_verdict`); `portfolio/stage.py` (coin holdings get forecast rows)
- Test: the existing tests of each, plus new cases

**Interfaces:**
- **`forecast_coins(model: FinalModel, bars: Mapping[str, Sequence[DailyBar]], spy_close: float | None, as_of) -> tuple[dict[str, list[PredictionRow]], dict[str, str]]`:**
  - builds a long price frame from the run's Coinbase candles (BTC always included), then `crypto_frames` (Task 2), and predicts each coin's last finished day;
  - `PredictionRow.benchmark` is `"BTC"` for altcoins and `"SPY"` for BTC;
  - the second dict holds the plain reason for each coin left out: `"only N days of history (needs 252)"`, `"no daily candles"`, or `"no BTC candles this run"`.
- **The run always fetches BTC's candles** with the coins (`coinbase_candles` symbols ∪ {"BTC"}).
- **`coin_verdict(symbol, rows, cost, policy)`:**
  - with rows, it applies the stock verdict rule (`stock_verdict` logic) with `sane=True` and no market gate;
  - with no rows, it's today's `NO_COIN_MODEL` verdict.
  
  The cost is `round_trip_cost(CRYPTO, …, crypto_fee_pct)`, and the policy is `policy_of(crypto_model.metrics)`.
- **Coin holdings get `rows` and the crypto policy,** so `decide()` can sell, trim or add on the forecast. Their trailing stops use the policy's `trail_atr`.
- **Coins never enter `recommend_market` or the picks gate.**
- **With no active crypto model,** everything is exactly as today.
- **Write predictions** for coins to `predictions`, as stocks are (asset type `crypto`).

- [ ] **Step 1: Tests:**
  - `forecast_coins` on synthetic candles gives 5 horizons per coin;
  - a 200-day coin and a no-BTC run give the reasons above;
  - a watched coin with `p=0.7` and `q50 > cost` gets Buy, and one with all `p ≤ p_sell` gets Avoid;
  - a held coin under a sell-line forecast gets Sell;
  - no coin appears in picks;
  - with no crypto model, the existing coin tests pass unchanged.
- [ ] **Steps 2–4:** fail, then implement, then pass. The full suite, ruff and the web e2e that reads coin verdicts pass.
- [ ] **Step 5:** Commit `feat: held and watched coins get forecasts, verdicts and holding actions from the crypto model`.

---

### Task 5 (Cursor): Docs

- **The design doc's status line:** Plans 6a, 6e and 6b are built; §3 and §4 remain future design.
- **The main spec's revision history:** "Plan 6b (2026-10-29): the crypto model replaces 'no crypto model yet' (§5.4)".
- **README:** the weekly build now downloads Coinbase history (about 5 minutes).
- **Commit:** `docs: Plan 6b`.

## After merging (the owner)

Push. The next Saturday `train.yml` builds the crypto history and trains the first crypto model. Then run **benchmark** and paste the report. No migration is needed.
