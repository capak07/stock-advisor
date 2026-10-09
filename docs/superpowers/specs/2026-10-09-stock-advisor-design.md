# Stock Advisor — Design Spec

- **Date:** 2026-10-09
- **Status:** Draft, awaiting owner review
- **Owner:** Atharva Kadam

## 1. Purpose

A personal decision-support app for **real investing**. Twice each trading day it collects data from 50+ free sources. It forecasts likely ranges for US stocks and watchlist crypto, then suggests what to buy, how long to hold it, and what the risk is. It also tells the owner what to do with their existing holdings. Every suggestion is graded against reality so the owner can judge, with evidence, whether to trust it.

**Honesty principle.** Stock prices can't be reliably predicted. The app gives probabilities and ranges, never certainties. It shows its live track record as prominently as its picks. It refuses to show picks when its own checks fail.

### Success criteria

1. In walk-forward backtests, picks beat SPY after estimated trading costs.
2. Calibration: stated probabilities are within 5 percentage points of observed hit rates, in both backtest and live results.
3. Results for each run are visible by about **9:00 AM ET** (pre-open) and about **3:45 PM ET** (pre-close).
4. The owner can see, at any time, the live track record compared with SPY, separately from backtest results.
5. Running cost is **$0/month**.

## 2. Requirements

### Stated by the owner

- R1. For real investing with the owner's own money.
- R2. Universe: **all US-listed stocks**, plus a **watchlist** that can hold any US stock or crypto.
- R3. Runs before market open and before market close on each trading day.
- R4. Uses at least 50 data sources.
- R5. Suggests buys with a **holding period** and a **risk level**.
- R6. Two horizons, labeled per pick: **Swing** (2 days to 4 weeks) and **Position** (1 to 6 months).
- R7. **Free data sources only.**
- R8. Output is a **web dashboard only**, with no push, email or chat notifications.
- R9. Hosting: GitHub Actions + Supabase + Vercel (option A).
- R10. A **My Portfolio** section for assets the owner has bought. These get **higher priority** for prediction, with a clear action for each (Sell / Trim / Add / Hold).

### Assumptions (confirmed during brainstorming)

- Run times are about 8:15 AM ET and 3:15 PM ET, scheduled 15 minutes early to absorb GitHub cron delays. Crypto uses the same schedule.
- Buys only: no shorting, options trading or day trading.
- Each pick shows a likely range, a probability of beating SPY, risk level, hold time, exit-by date, stop-loss and a suggested max position size.
- The app starts in a **paper period** (see §6.6).

### Non-goals

- Automated trade execution or broker integration, including broker sync.
- Shorting, options trading and intraday/day-trading signals.
- Notifications of any kind, apart from GitHub's built-in failure email for failed jobs.
- Paid data sources or paid LLMs.
- Multi-user support. This is a single owner app.
- Financial advice. The dashboard shows a standing disclaimer.

## 3. Architecture

```
GitHub Actions (private repo)
  run.yml    — cron, trading days: pre-open + pre-close
  train.yml  — weekly (Saturday): rebuild history, retrain, backtest, calibrate
  health.yml — daily: live ping of every source
  ci.yml     — every push: tests
        │
        ▼
Python pipeline (pipeline/)
  1. Universe  → 2. Holdings-first → 3. Screener → 4. Collectors
  → 5. Features → 6. Model → 7. Recommender + Portfolio advisor
  → 8. Grader → 9. Publish
        │ service key (GitHub secret)
        ▼
Supabase (free tier)
  Postgres: app data (runs, picks, holdings, outcomes, …)
  Storage:  Parquet history for training (prices, fundamentals)
        ▲ authenticated reads; owner writes only watchlist + lots
        │
Next.js dashboard on Vercel (web/), Supabase Auth login (single user)
```

### Design rules

1. **The pipeline writes and the dashboard reads.** The only things the dashboard writes are the watchlist and holdings lots.
2. **Each source is one module** that implements the `Collector` interface (§4.1). Sources never call each other.
3. **Point-in-time data everywhere.** Every record has an `as_of` timestamp, meaning when it became knowable. Features for a given date only use records with an `as_of` at or before that date.
4. **Atomic publish.** Results are written under a `run_id`. `runs.published` flips to true only when the whole run succeeds or is degraded. The dashboard only reads published runs.
5. **Holdings first.** Holdings are processed before anything else and get first claim on rate-limited sources.

### Scheduling

- GitHub cron uses UTC, so each run has two crons, one for EDT and one for EST:
  - Pre-open: `15 12 * * 1-5` and `15 13 * * 1-5`
  - Pre-close: `15 19 * * 1-5` and `15 20 * * 1-5`
  - Early-close days (1 PM close): `15 16 * * 1-5` and `15 17 * * 1-5`
- A guard step uses `pandas_market_calendars` (NYSE) to exit immediately unless it's a trading day and the current ET time is in the intended window. Early-close crons only proceed on early-close days, and on those days they replace the normal pre-close run.
- Target duration is 15 minutes or less per run. That's about 44 runs × 15 min ≈ 660 of the 2,000 free GitHub Actions minutes per month.
- The pre-open run uses the previous close plus pre-market snapshots where the free feed provides them. The pre-close run uses current, roughly 15-minute-delayed, intraday prices.

## 4. Data Pipeline

### 4.1 Collector interface

```python
class Collector(Protocol):
    name: str                      # e.g. "sec_form4"
    category: Category             # prices | fundamentals | options | macro | news | social | catalysts | onchain
    core: bool                     # if a core source fails, the run is marked degraded
    best_effort: bool              # unofficial / fragile; failures are expected
    cadence: Cadence               # per_run | daily | weekly
    asset_types: set[AssetType]    # {stock}, {crypto}, or both

    def fetch(self, symbols: list[str], as_of: datetime) -> CollectorResult: ...
```

`CollectorResult` holds the records, which are validated against a pydantic schema per category, along with status, latency and error.

The shared `base` module provides:

- a per-source token-bucket rate limiter
- a 20 s timeout
- 3 retries with exponential backoff
- an on-disk cache keyed by (source, symbol, cadence window), persisted with `actions/cache`
- a circuit breaker: a source that fails 3 consecutive runs is disabled and retried once a day by `health.yml`

A **registry** lists every collector. Adding a source means adding one module plus its registry entry.

### 4.2 Sources (53)

⚠ means best-effort.

| # | Category | Source | Cadence | Notes |
|---|---|---|---|---|
| 1 | prices | NASDAQ Trader symbol directory | daily | Universe (NASDAQ + other-listed). Core |
| 2 | prices | Alpaca market data (bars, snapshots) | per_run | Bulk screener prices. Free key. Core |
| 3 | prices | yfinance prices | per_run | Fallback and cross-check |
| 4 | prices | Stooq daily CSV | daily | History cross-check |
| 5 | prices | CoinGecko | per_run | Crypto prices and market cap. Core for crypto |
| 6 | prices | Coinbase Exchange public API | per_run | Crypto OHLCV |
| 7 | prices | Kraken public API | per_run | Crypto cross-check |
| 8 | fundamentals | SEC XBRL company facts | daily | Point-in-time financials via filing date. Core |
| 9 | fundamentals | SEC 8-K filings | per_run | Material-event catalysts |
| 10 | fundamentals | SEC Form 4 | daily | Insider buys and sells |
| 11 | fundamentals | SEC 13F | weekly | Institutional ownership changes |
| 12 | fundamentals | SEC 13D/13G | daily | Activist and large stakes |
| 13 | fundamentals | FINRA short interest | weekly | Twice-monthly files |
| 14 | fundamentals | FINRA Reg SHO daily short volume | daily | |
| 15 | fundamentals | Financial Modeling Prep (free) | daily | Ratios. 250 calls/day, holdings and shortlist only |
| 16 | fundamentals | yfinance analyst targets and ratings | daily | |
| 17 | fundamentals | Finnhub recommendation trends | daily | Free key. 60 calls/min |
| 18 | fundamentals | Finnhub earnings calendar and surprises | daily | Core (catalysts) |
| 19 | options | yfinance option chains | per_run | Implied volatility, per-ticker put/call. Shortlist only |
| 20 | options | CBOE daily put/call ratios | daily | Market-wide |
| 21 | macro | FRED (about 10 series) | daily | Yield curve, VIX, HY spread, CPI, unemployment, fed funds and others. Core |
| 22 | macro | Federal Reserve FOMC RSS | per_run | |
| 23 | macro | CNN Fear & Greed ⚠ | per_run | Unofficial endpoint |
| 24 | macro | alternative.me Crypto Fear & Greed | per_run | |
| 25 | news | Finnhub company news | per_run | Core (news) |
| 26 | news | Alpha Vantage NEWS_SENTIMENT ⚠ | per_run | 25 calls/day: holdings first, then top picks |
| 27 | news | Yahoo Finance per-ticker RSS | per_run | |
| 28 | news | Google News per-ticker RSS | per_run | |
| 29 | news | Seeking Alpha per-ticker RSS | per_run | |
| 30 | news | Nasdaq.com RSS | per_run | |
| 31 | news | CNBC RSS | per_run | |
| 32 | news | MarketWatch RSS | per_run | |
| 33 | news | WSJ Markets RSS | per_run | Headlines only |
| 34 | news | Investing.com RSS | per_run | |
| 35 | news | Benzinga RSS | per_run | |
| 36 | news | PR Newswire RSS | per_run | |
| 37 | news | GlobeNewswire RSS | per_run | |
| 38 | news | Business Wire RSS | per_run | |
| 39 | news | CoinDesk RSS | per_run | |
| 40 | news | Cointelegraph RSS | per_run | |
| 41 | news | Decrypt RSS | per_run | |
| 42 | social | Reddit API (r/wallstreetbets, r/stocks, r/investing, r/StockMarket, r/CryptoCurrency) | per_run | Free app key. Counted as 1 source |
| 43 | social | ApeWisdom mention counts | per_run | |
| 44 | social | StockTwits symbol streams ⚠ | per_run | |
| 45 | social | Google Trends (pytrends) ⚠ | daily | At most 50 symbols: holdings first |
| 46 | social | Wikipedia pageviews API | daily | Attention proxy |
| 47 | catalysts | openFDA | daily | Drug approvals and recalls |
| 48 | catalysts | ClinicalTrials.gov API | weekly | Trial status for biotech |
| 49 | catalysts | USAspending.gov | weekly | Federal contract awards |
| 50 | catalysts | House Clerk periodic transaction reports | weekly | Congressional trades |
| 51 | onchain | DefiLlama | daily | Chain and protocol TVL |
| 52 | onchain | blockchain.com stats | daily | BTC network metrics |
| 53 | onchain | Etherscan | daily | ETH metrics. Free key |

**Excluded because they aren't free:** X/Twitter, Bloomberg, Reuters, earnings-call transcripts, paid options flow.

**Required free accounts and keys:** Alpaca, Finnhub, FMP, Alpha Vantage, Reddit, Etherscan, Supabase, Vercel, GitHub. SEC requests send a `User-Agent` header with a contact email, as SEC requires.

**Terms of use:** best-effort sources are fetched at low volume, cached, and used only for personal, non-commercial purposes. If a source's terms forbid automated use, it's removed rather than worked around.

### 4.3 Run stages

1. **Universe.**
   - Load US common stocks from source 1, excluding ETFs, OTC, warrants, units and preferred shares. SPY and sector ETFs are loaded as benchmarks only and are never picked.
   - Add watchlist symbols and holdings.
   - Map sectors from yfinance metadata, cached weekly.
2. **Holdings first.** Run every collector for all held symbols before anything else (§7).
3. **Screener.**
   - Fetch bulk snapshots and recent bars for the whole universe, about 6,000 symbols, from Alpaca, with yfinance as fallback.
   - Hard filters: price ≥ $1, 20-day average dollar volume ≥ $1M, and at least 60 trading days of history.
   - Score the survivors with the **screener model** (§5.2), and keep the top about 300 by best predicted horizon score.
   - Holdings and the watchlist always pass the screener.
4. **Collectors.** Run all applicable collectors for the shortlist, with a concurrency of 8 and each source respecting its own rate limit.
5. **News processing.**
   - De-duplicate across feeds by canonical URL, then by headline similarity (MinHash, Jaccard ≥ 0.8) within 48 hours.
   - Map each item to tickers using cashtags, symbols and a company-name dictionary.
   - Score each unique item with **FinBERT** (`ProsusAI/finbert`, CPU, model files cached).
   - Per ticker, compute sentiment mean and trend, a volume z-score, and **coverage breadth**, the number of distinct outlets.
6. **Features.** One row per (symbol, as_of) (§5.1).
7. **Model.** Predictions for every horizon (§5).
8. **Recommender and portfolio advisor** (§6, §7).
9. **Grader.** Grade every pick and holding action whose horizon ended (§6.5).
10. **Publish.** Write a run summary, then set `published = true`.

## 5. Prediction

### 5.1 Features

| Group | Examples | Backtestable |
|---|---|---|
| Price/volume | Returns over 5d, 21d, 63d, 126d and 12-1m; RSI(14); ATR(14)%; realized vol 20d and 60d; distance to 52-week high and low; volume z-score; gap % | Yes |
| Relative strength | Excess return vs SPY and vs sector ETF over 21d and 63d; sector momentum rank | Yes |
| Fundamentals (point in time) | Revenue and EPS growth YoY, gross and operating margin and their trend, P/E, P/S, FCF yield, debt/equity, surprise from the last filing | Yes |
| Ownership and flow | Insider net buys over 90d, short interest % of float, days to cover, short volume ratio, 13F holder change | Yes |
| Macro regime | Yield-curve slope, VIX level and change, HY spread, fed funds trend | Yes |
| Options | Implied-vol rank, put/call ratio | No (live only) |
| News and social | Sentiment mean and trend, coverage breadth, mention z-score, Reddit, StockTwits, Trends, Wikipedia | No (live only) |
| Catalysts | Days to earnings, 8-K in the last 3 days, FDA or trial events, contract awards, congressional trades | Partly |

### 5.2 Base model (stocks)

- **Algorithm:** LightGBM, trained only on backtestable features.
- **Target:** forward excess return vs SPY at horizons h ∈ {5, 10, 20} (swing) and {21, 63, 126} (position) trading days.
- **Outputs per horizon:**
  - quantiles q10, q50, q90, from quantile regression with one model per quantile and horizon
  - a classifier for P(excess > 0), calibrated with **isotonic regression** on held-out walk-forward folds
- **Training data:** about 8 years of daily history for symbols that passed the liquidity filter. Stored as Parquet in Supabase Storage, and rebuilt and extended by `train.yml`.
- **Validation:** walk-forward, training on years [t−k, t), testing on year t, then rolling forward. There's an embargo gap equal to the horizon, so training labels never overlap the test data.
- **Screener model:** a variant trained on price/volume and relative-strength features only, so all ~6,000 symbols can be scored from bulk price data alone. It uses the same targets and validation and is retrained alongside the base model.
- **Retraining:** weekly. A new model is **promoted** only if its walk-forward metrics are at least as good as the active model's and its calibration error is ≤ 5 points. Otherwise the active model is kept.
- **Known bias:** free data under-represents delisted companies (survivorship bias), so backtests overstate performance. This is shown on the Track Record page.

### 5.3 Live overlay (news, social, options)

- Before stage-2 training, compute **overlay = clip(w · z_live, −0.25σ, +0.25σ)**, applied to q50. Here `z_live` is a hand-set weighted blend of the standardized live features, and σ is the cross-sectional standard deviation of q50 for that horizon.
- **Stage 2:** after at least 3 months of graded live picks, train a small model on the app's own logged live features to learn the overlay weights. It replaces the hand-set blend only if it improves live hit rate on a held-out period.
- All live features are **logged per run**, which is how stage 2 gets its training data.

### 5.4 Crypto model

- **Scope:** crypto is analyzed only for watchlist and held crypto. It never appears in the Swing/Position top lists, only as watchlist verdicts and holdings actions.
- A separate LightGBM model for crypto, trained on the top 100 coins by market cap. Training uses price/volume history from Coinbase candles (multi-year and free) plus on-chain and Fear & Greed features.
- Target: excess return vs **BTC** for altcoins, and vs SPY for BTC itself.
- Ranked only against other crypto.

## 6. Recommendations

### 6.1 Qualifying a buy

A (symbol, horizon) qualifies when all of these hold:

- P(beat benchmark) ≥ **0.58**
- q50 > estimated round-trip cost, which is 0.10% for large caps, 0.30% when ADV is under $10M, and 0.50% for crypto
- the latest data passes sanity checks

### 6.2 Hold time

For each qualifying symbol, pick the horizon h with the best **q50 / (q90 − q10)**. Display example: "Swing · hold ~10 trading days · exit by Oct 23", where the date is from the NYSE calendar.

### 6.3 Stop-loss

- **Swing:** entry reference minus 2 × ATR(14).
- **Position:** entry reference minus 3 × ATR(14), and never more than 15% below entry.

### 6.4 Risk level

The score is a weighted sum of percentile ranks across the universe:

| Component | Weight |
|---|---|
| Realized vol (60d) | 0.30 |
| Forecast range width (q90 − q10) | 0.20 |
| Signal disagreement (technical vs fundamental vs sentiment direction) | 0.15 |
| Illiquidity (inverse ADV) | 0.15 |
| Event risk (earnings or binary catalyst within the hold) | 0.10 |
| Small size (inverse market cap) | 0.10 |

| Level | Score percentile | Suggested max position |
|---|---|---|
| Low | < 30 | 5% of portfolio |
| Medium | 30–65 | 3% |
| High | 65–90 | 1.5% |
| Very High | ≥ 90 | 0.5% |

Floors: market cap under $300M is at least **High**, and all crypto is at least **High**.

### 6.5 Output limits and grading

- Each run gives at most **10 Swing + 10 Position** picks, with no more than **3 per sector** in each list, ranked by q50 / (q90 − q10).
- Every watchlist symbol gets a verdict. A **Buy** verdict carries the same fields as a pick: range, P(beat), hold time, exit-by, stop, risk and max size.
  - **Buy** if it qualifies
  - **Avoid** if P ≤ 0.42 at every horizon
  - **Hold** otherwise
- The pre-close run re-checks open picks. When P has fallen to 0.42 or below, or the stop has been hit, the pick is flagged **Exit early**.
- **Grading:** when a pick's exit-by date passes, or its stop is hit, record:
  - exit price (the first close on or after the exit-by date, or the stop price)
  - return
  - the benchmark's return over the same window
  - excess return
  - whether it beat the benchmark
  - whether the stop was hit
- Holding actions are graded the same way over their stated horizon.

### 6.6 Paper period

- A "**Not yet validated**" banner is shown until at least 100 Swing picks have been graded live.
- Position picks show "validated on backtest only" until at least 50 of them have been graded live.
- Backtest and live statistics are always shown in separate sections.
- If the backtest fails success criterion 1 or 2, picks are **disabled**. The dashboard shows the failing metrics, and only watchlist verdicts and holdings actions remain.

## 7. My Portfolio

### 7.1 Entering holdings

- **Lots:** symbol, asset type, quantity, price, date, optional `pick_id`, notes.
- **Sells:** symbol, quantity, price, date, matched against lots **FIFO**.
- **CSV import** for a generic broker export, with a column-mapping step.
- An **"I bought this"** button on a pick pre-fills a lot and links it to that pick.

### 7.2 Priority

- Holdings bypass the screener and get every applicable collector on every run.
- Rate-limited and best-effort sources serve holdings first: Alpha Vantage, Google Trends, FMP and option chains.
- Holdings are processed first, so their analysis survives a later failure in the run.

### 7.3 Actions

Each holding gets exactly one action, chosen in this order of precedence:

1. **Sell**:
   - the trailing stop is hit, **or**
   - P(beat benchmark) over the best horizon is ≤ 0.42, **or**
   - for a holding linked to a pick, the main signals behind that pick have reversed sign. These are the top three model factors stored with it.
2. **Trim**:
   - the position exceeds the max size for its current risk level, **or**
   - the unrealized gain is 25% or more **and** the 21-day momentum percentile has dropped below 40.
3. **Add**: the holding would qualify as a Buy pick today (§6.1) **and** the position is below its max size.
4. **Hold**: everything else. Shown with the expected remaining hold time and an exit-by date.

A **Review** badge is added on top of the action when earnings or a binary catalyst is within 5 trading days.

**Trailing stop:** the highest close since purchase minus 2.5 × ATR(14). It only moves up, and never sits below the original stop.

### 7.4 Portfolio-level checks

- Warning when any single sector is above 25% of portfolio value.
- Warning when any position is above its risk-based max.
- A breakdown of portfolio value by risk level.
- Portfolio return vs SPY since the first lot, and over 1, 3 and 12 months.

### 7.5 Tax awareness (US)

- Each lot shows the number of **days until long-term status**, which is reached once held more than 1 year.
- A Sell or Trim on a lot within 30 days of long-term status shows "consider waiting until \<date\>", unless the trigger was the trailing stop.
- This is informational only, not tax advice.

## 8. Data Model (Supabase Postgres)

| Table | Key columns |
|---|---|
| `runs` | id, kind (pre_open / pre_close / early_close), started_at, finished_at, status (success / degraded / failed), published, sources_ok, sources_total, model_version |
| `source_health` | run_id, source, status, latency_ms, records, error, consecutive_failures |
| `symbols` | symbol, asset_type, name, exchange, sector, industry, market_cap, active |
| `features_live` | run_id, symbol, features (jsonb), as_of. Holds the shortlist, holdings and watchlist |
| `predictions` | run_id, symbol, horizon_days, q10, q50, q90, p_beat, benchmark, model_version |
| `picks` | id, run_id, symbol, style (swing / position), horizon_days, exit_by, entry_ref_price, stop, risk_level, risk_score, max_position_pct, rank, top_factors (jsonb), catalysts (jsonb), status (open / exited_early / graded) |
| `pick_outcomes` | pick_id, exit_price, exit_reason, ret, bench_ret, excess, beat, hit_stop, graded_at |
| `watchlist` | symbol, asset_type, added_at |
| `watchlist_verdicts` | run_id, symbol, verdict, reasons (jsonb) |
| `lots` | id, symbol, asset_type, qty, price, bought_at, pick_id, notes |
| `sells` | id, symbol, qty, price, sold_at |
| `holding_actions` | run_id, symbol, action, review, reasons (jsonb), trailing_stop, q10, q50, q90, exit_by, days_to_long_term |
| `news_items` | id, symbol, published_at, outlet, url, title, sentiment, cluster_id. Pruned after 90 days |
| `models` | version, kind (stock / crypto), trained_at, metrics (jsonb), calibration_error, active |

- **Row-level security:** every table is readable only by the owner's authenticated user ID. The owner can write only to `watchlist`, `lots` and `sells`. The pipeline writes with the service-role key, which is stored only as a GitHub secret.
- **Storage:** training Parquet (prices, fundamentals) goes in a private Supabase Storage bucket, kept under about 600 MB.

## 9. Dashboard (web/)

- **Stack:** Next.js (App Router) and `@supabase/ssr` with Supabase Auth (email and password, single user, sign-ups disabled), deployed on Vercel.
- **Charts:** TradingView `lightweight-charts` (Apache-2.0) for price charts and forecast cones, and Recharts for track-record and calibration charts. The visual design follows the **superdesign workflow in the workspace CLAUDE.md**: layout, then theme, then animation, then HTML, with owner sign-off at each step before building the pages.
- **Disclaimer:** a footer on every page: "Not financial advice. Forecasts are probabilistic and can be wrong."

| Page | Contents |
|---|---|
| Top bar (all pages) | Last runs with status, Paper/Validated badge, sources OK (e.g. 49/53), stale banner if the latest run failed |
| **My Portfolio** (home) | Total value, P/L vs SPY. Action cards sorted Sell → Trim → Review → Add → Hold. Holdings table (symbol, P/L, action, range, trailing stop, exit-by, days to long-term, risk). Portfolio warnings. Add lot, add sell and import CSV |
| **Today's Picks** | Swing and Position tabs. A card per pick (range bar, P(beat), hold time and exit-by, stop, risk and max size, top factors, catalysts, "I bought this"). Watchlist verdicts. Exit-early flags on open picks |
| **Ticker Detail** | Price chart with forecast cone, top factors, news (de-duplicated, with sentiment), catalysts, which sources contributed, history of past picks and outcomes for the symbol |
| **Track Record** | Live vs backtest shown separately. Hit rate, average excess return and calibration chart by horizon and by risk level. Every past pick and its outcome. Survivorship-bias note |
| **Watchlist** | Add or remove stocks and crypto, with the latest verdict for each |
| **Source Health** | All 53 sources: last success, latency, records, errors, circuit-breaker state |

## 10. Error Handling

- **Per source:** timeout, 3 retries, cache fallback within the freshness window, and a circuit breaker (§4.1). A failure only affects that source's features, which become missing values. LightGBM handles missing values natively.
- **Run status:**
  - `failed` if the universe or prices can't be loaded, or the model can't be loaded.
  - `degraded` if any core source fails.
  - `success` otherwise.
  - A failed run is never published. The dashboard shows the last published run with a stale banner.
- **Validation:** pydantic schemas per category. Sanity rules:
  - price must be above 0
  - a daily move above 50% needs a recorded split or corporate action, otherwise the bar is dropped
  - records older than the source's freshness window are treated as missing
- **Price cross-check for holdings:** if Alpaca and yfinance differ by more than 2%, the holding's action is replaced with "Data conflict: check manually".
- **Model guard:** the last good model is kept if retraining fails promotion. If no active model passes calibration, picks are suppressed with "No picks today: model check failed", and holdings fall back to trailing-stop and size rules only.
- **Free-tier limits:**
  - Twice-daily writes prevent Supabase from pausing after 7 idle days.
  - News is pruned after 90 days.
  - Training data lives in Storage, not Postgres.
- **Alerts:** GitHub's built-in failure email for failed workflow runs. No other notifications.

## 11. Testing

- **Unit tests** (pytest):
  - each collector against recorded responses, with no live network in CI
  - feature functions against hand-computed values
  - recommender, risk, holdings-action, FIFO-lot and long-term-date rules, all table-driven
- **Look-ahead test:** inject "poisoned" records dated after `as_of` and assert that no feature changes.
- **Backtest report** (`train.yml`), produced as an artifact and stored in `models.metrics`:
  - walk-forward hit rate
  - excess return after costs compared with SPY
  - calibration curve and error
  - promotion gates per §5.2
- **Pipeline end-to-end:** a full run on recorded data against a Postgres service container. Checks that atomic publish works and that a failed run stays unpublished.
- **Dashboard:** Playwright tests for login; adding a lot, a sell and a watchlist item; every page rendering with seed data; and the stale banner and paper banner showing.
- **CI:** `ci.yml` runs all of the above on every push.
- **Live checks:** `health.yml` pings every source daily and updates `source_health`.

## 12. Repository Layout

```
stock-advisor/
  pipeline/                 Python 3.12, uv
    src/advisor/
      collectors/{base.py, registry.py, <one module per source>}
      universe.py  screener.py  news.py  features/  model/
      recommend/  portfolio/  grade.py  store/  run.py  train.py
    tests/{fixtures/, unit/, e2e/}
  web/                      Next.js dashboard
  supabase/migrations/      SQL schema + RLS policies
  .github/workflows/{run.yml, train.yml, health.yml, ci.yml}
  docs/superpowers/specs/
```

This is a standalone private GitHub repo. GitHub Actions and Vercel are both configured per repository.

## 13. Risks and Open Points

| Risk | Mitigation |
|---|---|
| The model doesn't beat SPY | Acceptance gates disable picks and show the metrics. Holdings tools still work |
| Unofficial sources break (yfinance, CNN, StockTwits, Trends) | Best-effort flag, circuit breaker, Alpaca as primary for prices |
| GitHub cron delay pushes pre-close results past 3:45 PM | Runs start 15 minutes early. Each run shows its completion time |
| Free API terms or limits change | One module per source, so a source can be swapped or removed without touching anything else |
| Survivorship bias inflates backtests | Disclosed on the Track Record page. Live record is shown separately and given more weight |
| Supabase or Actions free-tier limits | Budgets in §3 and §10. Usage is shown on Source Health |
