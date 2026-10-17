# Stock Advisor — Design Spec

- **Date:** 2026-10-09
- **Revision:** 2 (2026-10-13). Awaiting owner review.
- **Owner:** Atharva Kadam

### Revision history

- **Rev 1 (2026-10-09):** original design. The owner approved it, and Plans 1 and 2a were built from it.
- **Rev 2 (2026-10-13):** owner decisions:
  1. **Keyless data:** no data source may need an API key or an account. Alpaca, FMP, Finnhub, Alpha Vantage, the Reddit API and Etherscan are removed. Yahoo becomes the only stock price source, and unconfirmed price jumps are flagged instead of dropped.
  2. **Canadian market:** all **TSX** stocks are scanned for picks alongside US stocks.
  3. **Accounts:** the owner holds stocks in a Wealthsimple **TFSA** and crypto in a Wealthsimple **Crypto account**, and US trades are converted from CAD each time. Canadian tax rules replace the US ones, and the portfolio is shown in CAD.

  Rev 2 also records the design refinements Plans 1 and 2a settled: the collector protocol, the least-privilege database role, tracked migrations and the health check.

## 1. Purpose

A personal decision-support app for **real investing**. Twice each trading day it collects data from 50+ free, keyless sources. It forecasts likely ranges for **US and Canadian (TSX) stocks** and the owner's crypto, then suggests what to buy, how long to hold it, and what the risk is. It also tells the owner what to do with their existing holdings. Every suggestion is graded against reality so the owner can judge, with evidence, whether to trust it.

**Honesty principle.** Stock prices can't be reliably predicted. The app gives probabilities and ranges, never certainties. It shows its live track record as prominently as its picks. It refuses to show picks when its own checks fail.

### Success criteria

1. In walk-forward backtests, picks beat **their market's benchmark** (SPY for US, XIU.TO for TSX) after estimated trading costs. Costs include currency conversion for US picks.
2. Calibration: stated probabilities are within 5 percentage points of observed hit rates, in both backtest and live results.
3. Results for each run are visible by about **9:00 AM ET** (pre-open) and about **3:45 PM ET** (pre-close).
4. The owner can see, at any time, the live track record compared with each benchmark, separately from backtest results.
5. Running cost is **$0/month**, and **no data source needs an API key or an account**.

## 2. Requirements

### Stated by the owner

- R1. For real investing with the owner's own money.
- R2. **Universe:**
  - all US-listed common stocks;
  - all **TSX-listed** common stocks and REIT units;
  - a **watchlist** that can hold any US stock, TSX stock or crypto.
- R3. Runs before market open and before market close on each trading day of either market.
- R4. Uses at least 50 data sources.
- R5. Suggests buys with a **holding period** and a **risk level**.
- R6. Two horizons, labeled per pick: **Swing** (2 days to 4 weeks) and **Position** (1 to 6 months).
- R7. **Free data sources only, with no API keys and no accounts.** SEC's required contact string in the User-Agent is not an account.
- R8. Output is a **web dashboard only**, with no push, email or chat notifications.
- R9. Hosting: GitHub Actions + Supabase + Vercel (option A). These hosting accounts are allowed; they aren't data sources.
- R10. A **My Portfolio** section for assets the owner has bought. These get **higher priority** for prediction, with a clear action for each (Sell / Trim / Add / Hold).
- R11. **Accounts:** stocks sit in a Wealthsimple **TFSA**; crypto sits in a Wealthsimple **Crypto account**. The portfolio is shown in **CAD**.
- R12. **US trades are converted from CAD** on each buy and each sell, at about 1.5% each way. This is a setting.

### Assumptions (confirmed during brainstorming)

- Run times are about 8:15 AM ET and 3:15 PM ET, scheduled 15 minutes early to absorb GitHub cron delays. Both exchanges trade 9:30–16:00 ET. Crypto uses the same schedule.
- Buys only: no shorting, options trading or day trading. TSX Venture is out of scope.
- Each pick shows:
  - a likely range;
  - a probability of beating its benchmark;
  - risk level and hold time, with an exit-by date;
  - stop-loss and a suggested max position size;
  - its market.
- Wealthsimple has no public API. Holdings are entered by hand or imported from a file the owner downloads.
- The app starts in a **paper period** (see §6.6).

### Non-goals

- Automated trade execution or broker integration, including connecting to Wealthsimple with the owner's credentials.
- Shorting, options trading and intraday/day-trading signals.
- Notifications of any kind, apart from GitHub's built-in failure email for failed jobs.
- Paid data sources, paid LLMs, and any data source that needs an API key or an account.
- Multi-user support. This is a single owner app.
- Financial or tax advice. The dashboard shows a standing disclaimer.

## 3. Architecture

```
GitHub Actions (private repo)
  run.yml    — cron, trading days of either market: pre-open + pre-close (+ early-close)
  train.yml  — weekly (Saturday): rebuild history, retrain, backtest, calibrate
  health.yml — daily: live canary check of every source
  ci.yml     — every push: tests
        │
        ▼
Python pipeline (pipeline/)
  1. Holdings first → 2. Universes (US + TSX) → 3. Screener → 4. Enrichment collectors
  → 5. Features → 6. Model → 7. Recommender + Portfolio advisor
  → 8. Grader → 9. Publish
        │ least-privilege login (member of pipeline_rw; GitHub secret DATABASE_URL)
        ▼
Supabase (free tier)
  Postgres: app data (runs, picks, holdings, outcomes, …)
  Storage:  Parquet history for training (prices, fundamentals)
        ▲ authenticated reads; owner writes only watchlist, lots, sells
        │
Next.js dashboard on Vercel (web/), Supabase Auth login (single user)
```

### Design rules

1. **The pipeline writes and the dashboard reads.** The dashboard writes only the watchlist, lots, sells and the settings row.
2. **Each source is one module** that implements the `Collector` protocol (§4.1). Sources never call each other.
3. **Point-in-time data everywhere.** Every record is tied to the run's `as_of`. Features for a given date only use records that were knowable at or before that date.
4. **Atomic publish.** Results are written under a `run_id`. `runs.published` flips to true only when the whole run succeeds or is degraded. The dashboard only reads published runs.
5. **Holdings first.** Holdings and the watchlist are priced and saved before the rest of the market. They come first in every collector's symbol list, so capped sources spend their quota on them.
6. **Least privilege.**
   - At runtime the pipeline connects as a login role that is a member of `pipeline_rw`. That role can read and write data but has no DDL rights, and it can only read holdings, the watchlist, settings and the owner config.
   - Migrations are append-only and run only through `python -m advisor.store.migrate` with an admin URL that is never stored in GitHub.

### Markets

| | US | TSX |
|---|---|---|
| Stock list | NASDAQ Trader directory | TMX company directory: TSX only, common shares and REIT units. It excludes ETFs, CDRs, preferreds, warrants, debentures and split shares |
| Symbol format | `AAPL`, `BRK.B` | Yahoo's format: `RY.TO`, `RCI-B.TO`, `REI-UN.TO` |
| Calendar | NYSE | TSX |
| Currency | USD | CAD |
| Benchmark | SPY | XIU.TO (iShares S&P/TSX 60) |
| Hard filters | price ≥ US$1, average daily dollar volume ≥ US$1M, ≥ 60 sessions | price ≥ C$1, average daily dollar volume ≥ C$1M, ≥ 60 sessions |
| Shortlist | top 300 | top 100 |
| Round-trip cost | **2 × USD conversion fee** (default 1.5% each way) plus spread | spread only: 0.10% for large caps, 0.30% when average daily volume is under C$10M |

Crypto's round-trip cost is 2 × the crypto spread (default 2.0% each way). Fees are owner-editable, in the one-row `settings` table.

### Scheduling

- GitHub cron uses UTC, so each run has two crons, one for EDT and one for EST:
  - Pre-open: `15 12 * * 1-5` and `15 13 * * 1-5`
  - Pre-close: `15 19 * * 1-5` and `15 20 * * 1-5`
  - Early-close days (1 PM close): `15 16 * * 1-5` and `15 17 * * 1-5`
- A guard step uses `pandas_market_calendars` (NYSE and TSX):
  - A slot runs when **at least one market is open** that day and that market has that slot. Pre-close applies to markets closing at 16:00; early-close applies to markets closing at 13:00.
  - On a day when one market closes early and the other doesn't, both the early-close and pre-close runs happen.
  - Each market's freshness floor comes from **its own** calendar.
- A trigger arriving 30–60 minutes late exits with an error, so GitHub emails the owner about the missed slot.
- Target duration is 15 minutes or less per run, and runs are bounded by a 30-minute deadline. The job is killed at 40 minutes.
- The pre-open run uses the previous close. The pre-close run uses Yahoo's current-day bar, which is incomplete and is treated that way.

## 4. Data Pipeline

### 4.1 Collector protocol

```python
class Collector(Protocol):
    name: str                        # e.g. "sec_form4"
    category: Category               # prices | fundamentals | options | macro | news | social | catalysts | onchain
    core: bool                       # a core source that isn't OK marks the run degraded
    best_effort: bool                # unofficial / fragile; failures are expected
    cadence: Cadence                 # per_run | daily | weekly
    asset_types: frozenset[AssetType]
    markets: frozenset[Market]       # stock markets covered (US, TSX); a source is sent only their symbols
    record_type: type[BaseModel]
    freshness: timedelta | None      # max age of cached data served as a fallback; None = never cache
    scope: Scope                     # universe | symbols (one or more records per symbol) | market (market-wide)
    canary: tuple[str, ...]          # symbols the daily health check fetches
    canary_requires_records: bool    # empty canary answer fails the health check only when True
    max_symbols: int | None          # cap per call; the rest wait for a later run

    def fetch(self, symbols: Sequence[str], as_of: datetime) -> list[BaseModel]: ...
```

**Contract:**
- `fetch` returns validated records or raises. It never touches the database.
- SYMBOLS-scope records carry the canonical requested `symbol`. Provider formats such as `BRK/B`, `BRKB` and `BRK-B` are mapped inside the collector.
- `PartialFetch(records, error)` reports per-request failures. An empty one counts as a failure.
- A missing credential raises `MissingCredential`. No data source needs one under R7, so this applies only to the SEC contact string.

The shared framework provides:
- a token-bucket rate limiter, with one shared limiter per provider;
- a 20 s timeout and 3 retries with exponential backoff that honour `Retry-After`;
- error text that never contains query strings;
- a run deadline that stops retries and long loops;
- a `collect_per_symbol` helper.

`run_collector` wraps every call:
- **Circuit breaker:** a source that fails 3 consecutive runs is skipped for the rest of that ET day.
- **Daily health check:** it also retries the source, and a passing check resets the breaker.
- **Cadence window:** DAILY and WEEKLY collectors are served from entries saved in the current ET day or ISO week, and only missing symbols are fetched.
- **Failure fallback:** cache entries within `freshness` are served when a source fails, and partial answers are backfilled the same way.
- **Empty answers:** an empty answer never replaces cached data.
- **One result per source:** `SourceTracker` merges a source's calls within a run into one result and one `source_health` row.

### 4.2 Sources (53)

None needs an API key or an account. ⚠ means best-effort (unofficial or fragile). "Core" means a failure degrades the run. Markets: US, TSX or C (crypto).

| # | Category | Source | Markets | Cadence | Notes |
|---|---|---|---|---|---|
| 1 | prices | NASDAQ Trader symbol directory | US | daily | US universe. Core |
| 2 | prices | TMX company directory ⚠ | TSX | daily | TSX universe, one JSON call. Core |
| 3 | prices | Yahoo prices (yfinance) ⚠ | US, TSX | per_run | **The only stock price source.** Core |
| 4 | prices | CoinGecko public API ⚠ | C | per_run | Crypto prices and market cap. Core for crypto |
| 5 | prices | Coinbase Exchange public API | C | daily | Crypto OHLCV (finished UTC days) |
| 6 | prices | Kraken public API | C | daily | Crypto cross-check |
| 7 | prices | Bank of Canada Valet | US, TSX | daily | Official USD/CAD rate, plus the Canadian policy rate and yields |
| 8 | fundamentals | SEC XBRL company facts | US | daily | Point-in-time financials via filing date. Core |
| 9 | fundamentals | SEC 8-K filings | US | per_run | Material-event catalysts |
| 10 | fundamentals | SEC Form 4 | US | daily | Insider buys and sells |
| 11 | fundamentals | SEC 13F data sets (+ OpenFIGI CUSIP mapping) | US | weekly | Institutional ownership change |
| 12 | fundamentals | SEC 13D/13G | US | daily | Activist and large stakes |
| 13 | fundamentals | FINRA short interest | US | weekly | Twice-monthly settlement files |
| 14 | fundamentals | FINRA Reg SHO daily short volume | US | daily | One file per day |
| 15 | fundamentals | Canadian short-position report | TSX | weekly | Twice-monthly. Kept only if a keyless file is confirmed (Plan 2h) |
| 16 | fundamentals | Yahoo analyst data ⚠ | US, TSX | daily | Targets, recommendation counts, rating changes |
| 17 | fundamentals | Yahoo earnings dates and surprises ⚠ | US, TSX | daily | Upcoming dates, EPS estimate, actual and surprise. Core (catalysts) |
| 18 | options | Yahoo option chains ⚠ | US | per_run | Implied volatility, per-ticker put/call. Shortlist only |
| 19 | options | CBOE daily put/call ratios | US | daily | Market-wide |
| 20 | macro | FRED public CSV | US, TSX | daily | About 10 series: yield curve, VIX, HY spread, CPI, unemployment, fed funds. Core |
| 21 | macro | Federal Reserve FOMC RSS | US, TSX | per_run | Plus the meeting calendar page |
| 22 | macro | CNN Fear & Greed ⚠ | US | per_run | Unofficial endpoint |
| 23 | macro | alternative.me Crypto Fear & Greed | C | daily | |
| 24–30 | news | Per-ticker RSS: Yahoo Finance, **Google News (core)**, Seeking Alpha; market RSS: Nasdaq.com, CNBC, MarketWatch, WSJ Markets | US, TSX | per_run | Google News queries by company name, so it also covers TSX |
| 31–35 | news | Investing.com, Benzinga, PR Newswire/CNW, GlobeNewswire, Business Wire | US, TSX | per_run | CNW and GlobeNewswire carry Canadian press releases |
| 36–38 | news | CoinDesk, Cointelegraph, Decrypt | C | per_run | |
| 39–42 | news | Financial Post, Globe and Mail, BNN Bloomberg, Newsfile ⚠ | TSX | per_run | Canadian outlets. Each RSS feed is confirmed in Plan 2f, and swapped for another keyless Canadian feed if one isn't available |
| 43 | social | Reddit public RSS (r/stocks, r/wallstreetbets, r/investing, r/CanadianInvestor, r/Baystreetbets, r/CryptoCurrency) ⚠ | US, TSX, C | per_run | Counted as 1 source |
| 44 | social | ApeWisdom mention counts | US, C | per_run | |
| 45 | social | StockTwits symbol streams ⚠ | US | per_run | |
| 46 | social | Google Trends (pytrends) ⚠ | US, TSX | daily | At most 50 symbols, holdings first |
| 47 | social | Wikipedia pageviews API | US, TSX | daily | Attention proxy |
| 48 | catalysts | openFDA | US | daily | Drug approvals and recalls |
| 49 | catalysts | ClinicalTrials.gov API | US, TSX | weekly | Trial status for biotech |
| 50 | catalysts | USAspending.gov | US | weekly | Federal contract awards |
| 51 | catalysts | House Clerk periodic transaction reports | US | weekly | Congressional trades |
| 52 | onchain | DefiLlama | C | daily | Chain and protocol TVL |
| 53 | onchain | blockchain.com stats | C | daily | BTC network metrics |

- **Removed in Rev 2** because they need a key or an account: Alpaca, FMP, Finnhub (recommendations, earnings, news), Alpha Vantage, the Reddit API and Etherscan.
- **Removed** because it now blocks scripts with a browser check: Stooq.
- **Dropped in Plan 2f.** The owner chose to read terms as a personal feed reader would (2026-10-16).
  - Terms forbid automated access: Seeking Alpha, Investing.com, Financial Post, CoinDesk, Cointelegraph, Reddit and StockTwits.
  - No working keyless feed: Benzinga, GlobeNewswire, Business Wire and CNW.
  - WSJ Markets comes from Dow Jones' current feed, and Protos replaces the dropped crypto feeds.
  - The social sources (43–47) moved to Plan 2i.
  - Google News stays, as the owner's accepted reading of its personal-feed-reader licence.
- **Excluded** because they aren't free: X/Twitter, Bloomberg, Reuters, earnings-call transcripts, paid options flow.
- **Hosting accounts** (not data sources): GitHub, Supabase, Vercel. SEC requests send a `User-Agent` containing an owner-chosen contact string, as SEC requires.
- **Terms of use:** best-effort sources are fetched at low volume, cached, and used only for personal, non-commercial purposes. If a source's terms forbid automated use, it's removed rather than worked around.
- **TSX data is thinner.** Canadian companies have no SEC or FINRA equivalent with a free API, so TSX stocks get roughly 20–25 signals against 35–40 for US stocks. Their confidence and risk reflect this (§5, §6.4).

### 4.3 Run stages

1. **Holdings first.** Price the held and watched stocks of both markets, and save their features before anything else can fail. SPY and XIU.TO are priced with them.
2. **Universes.**
   - Load the US universe (source 1) and the TSX universe (source 2), applying the market rules in §3.
   - SPY, XIU.TO and sector ETFs are loaded as benchmarks only and are never picked.
   - Map sectors from Yahoo metadata, cached weekly.
3. **Screener.**
   - Fetch daily bars for both universes (about 6,000 US symbols and 1,500 TSX symbols) from Yahoo in bulk.
   - Apply the jump rule (§10).
   - Apply each market's hard filters, then score the survivors with the **screener model** (§5.2).
   - Keep the top 300 US and the top 100 TSX.
   - Holdings and the watchlist always pass.
4. **Enrichment collectors.** Every applicable collector runs once, concurrently (8 workers), on:
   - the priority symbols first;
   - then held and watched crypto;
   - then the shortlist.

   It runs only for a run that can still publish.
5. **News processing.**
   - De-duplicate across feeds by canonical URL, then by headline similarity (Jaccard ≥ 0.8 over title words, computed exactly) within 48 hours. Each asset stores a story once, even when later runs see it again.
   - Map each item to tickers using cashtags, symbols and a company-name dictionary for both markets.
   - Score each unique item with **FinBERT** (`ProsusAI/finbert`, CPU, model files cached).
   - Per ticker, compute sentiment mean and trend, a volume z-score, and **coverage breadth**.
6. **Features.** One row per (symbol, as_of) (§5.1).
7. **Model.** Predictions for every horizon (§5).
8. **Recommender and portfolio advisor** (§6, §7).
9. **Grader.** Grade every pick and holding action whose horizon ended (§6.5).
10. **Publish.** Store the day's closes and USD/CAD for the dashboard (`daily_closes`, `fx_rates`, §8). Write a run summary (per-market counts included), then set `published = true`.

## 5. Prediction

### 5.1 Features

| Group | Examples | Backtestable | Markets |
|---|---|---|---|
| Price/volume | Returns over 5d, 21d, 63d, 126d and 12-1m; RSI(14); ATR(14)%; realized vol 20d and 60d; distance to 52-week high and low; volume z-score; gap %; flagged-jump indicator | Yes | US, TSX |
| Relative strength | Excess return vs the market's benchmark and sector ETF over 21d and 63d; sector momentum rank | Yes | US, TSX |
| Fundamentals (point in time) | Revenue and EPS growth YoY, gross and operating margin and their trend, P/E, P/S, FCF yield, debt/equity, surprise from the last filing (from SEC XBRL plus prices) | Yes | US |
| Ownership and flow | Insider net buys over 90d, short interest as a share of shares outstanding, days to cover, short volume ratio, 13F holder change | Yes | US (TSX short positions if source 15 is confirmed) |
| Earnings | Days to the next report, last EPS surprise | Partly | US, TSX |
| Macro regime | Yield-curve slope, VIX level and change, HY spread, fed funds trend; Canadian policy rate and yields; USD/CAD trend | Yes | US, TSX |
| Options | Implied-vol rank, put/call ratio | No (live only) | US |
| News and social | Sentiment mean and trend, coverage breadth, mention z-score, Reddit, StockTwits, Trends, Wikipedia | No (live only) | US, TSX |
| Catalysts | 8-K in the last 3 days, FDA or trial events, contract awards, congressional trades | Partly | US |

Features a market lacks are missing values. LightGBM handles them natively.

### 5.2 Base model (stocks)

- **Algorithm:** LightGBM, trained only on backtestable features, **separately for each market**.
- **Target:** forward excess return vs the market's benchmark (SPY, XIU.TO) at horizons h ∈ {5, 10, 20} (swing) and {21, 63, 126} (position) trading days of that market's calendar.
- **Outputs per horizon:**
  - quantiles q10, q50, q90, from quantile regression;
  - a classifier for P(excess > 0), calibrated with **isotonic regression** on held-out walk-forward folds.
- **Training data:** about 8 years of daily history per market for symbols that passed the liquidity filter. It's stored as Parquet in Supabase Storage.
- **Validation:** walk-forward with an embargo gap equal to the horizon.
- **Screener model:** a price/volume and relative-strength variant per market. It scores every symbol from bulk price data alone.
- **Retraining:** weekly. A new model is **promoted** only if its walk-forward metrics are at least as good as the active model's and its calibration error is ≤ 5 points.
- **Known bias:** free data under-represents delisted companies (survivorship bias), so backtests overstate performance. This is shown on the Track Record page.

### 5.3 Live overlay (news, social, options)

- Before stage-2 training, compute **overlay = clip(w · z_live, −0.25σ, +0.25σ)**, applied to q50.
- **Stage 2:** after at least 3 months of graded live picks, learn the overlay weights from the app's own logged live features. They replace the hand-set blend only if they improve the live hit rate on a held-out period.
- All live features are **logged per run**.

### 5.4 Crypto model

- **Scope:** held and watchlist crypto only. Crypto appears as watchlist verdicts and holdings actions, never in the pick lists.
- **Model:** a separate LightGBM model trained on the top 100 coins by market cap, using Coinbase candle history plus on-chain and Fear & Greed features.
- **Target:** excess return vs **BTC** for altcoins, and vs SPY for BTC itself.

## 6. Recommendations

### 6.1 Qualifying a buy

A (symbol, horizon) qualifies when all of these hold:
- P(beat its market's benchmark) ≥ **0.58**;
- q50 > the estimated round-trip cost for its market (§3 Markets). That is 2 × the USD conversion fee plus spread for US stocks, spread only for TSX stocks, and 2 × the crypto spread for crypto;
- the latest data passes sanity checks;
- the latest bar is not a flagged, unconfirmed jump.

### 6.2 Hold time

For each qualifying symbol, pick the horizon h with the best **q50 / (q90 − q10)**. Display example: "Swing · hold ~10 trading days · exit by Oct 23". The date comes from the symbol's market calendar.

### 6.3 Stop-loss

- **Swing:** entry reference minus 2 × ATR(14).
- **Position:** entry reference minus 3 × ATR(14), and never more than 15% below entry.

### 6.4 Risk level

The score is a weighted sum of percentile ranks within the symbol's market:

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

**Floors:**
- a market cap under US$300M or C$300M is at least **High**;
- all crypto is at least **High**;
- a stock missing more than half of its market's feature groups is at least **Medium**.

### 6.5 Output limits and grading

- **Pick lists:** each run gives **per market** at most **10 Swing + 10 Position** picks, with no more than **3 per sector** in each list, ranked by q50 / (q90 − q10).
- **Watchlist verdicts:** every watchlist symbol gets one. A **Buy** verdict carries the same fields as a pick.
  - **Buy** if it qualifies.
  - **Avoid** if P ≤ 0.42 at every horizon.
  - **Hold** otherwise.
- **Exit early:** the pre-close run re-checks open picks. A pick is flagged when P has fallen to 0.42 or below, or its stop has been hit.
- **Grading:** when a pick's exit-by date passes, or its stop is hit, record:
  - the exit price;
  - return;
  - the benchmark's return over the same window;
  - excess return;
  - whether it beat the benchmark;
  - whether the stop was hit.

  US returns are also shown net of the conversion fee. Holding actions are graded the same way over their stated horizon.

### 6.6 Paper period

- **Swing:** a "**Not yet validated**" banner is shown until at least 100 Swing picks have been graded live. Each market is counted separately.
- **Position:** picks show "validated on backtest only" until at least 50 of them have been graded live.
- **Separate records:** backtest and live statistics are always shown in separate sections.
- **Disabling picks:** if a market's backtest fails success criterion 1 or 2, that market's picks are **disabled** and its failing metrics are shown. Watchlist verdicts and holdings actions remain.

## 7. My Portfolio

### 7.1 Entering holdings

- **Buys:**
  - account (`tfsa`, `rrsp`, `fhsa`, `non_registered` or `crypto`);
  - symbol, asset type, market, quantity, price and currency;
  - date;
  - for a USD buy, the Bank of Canada USD/CAD rate on that date (filled in automatically and editable);
  - an optional `pick_id`;
  - notes.
- **Sells:**
  - account, symbol, quantity, price, currency, date;
  - the exchange rate for USD sells.
- **Cost basis:** **average cost** (adjusted cost base) per (account, symbol), as Canadian tax rules require. A sell reduces quantity at average cost, and realized gain is proceeds minus average cost × quantity, in CAD.
- **File import:** imports a broker's activity file, for example one downloaded from Wealthsimple, through a column-mapping step.
- **"I bought this":** a button on a pick pre-fills a buy and links it to the pick.

### 7.2 Priority

- Holdings and the watchlist bypass the screener and are priced first.
- They come first in every collector's symbol list, so capped sources (Google Trends, option chains, Yahoo analyst data) serve them first.
- Their features are saved before the rest of the run.

### 7.3 Actions

Each holding gets exactly one action, chosen in this order of precedence:

1. **Sell:**
   - the trailing stop is hit, **or**
   - P(beat benchmark) over the best horizon is ≤ 0.42, **or**
   - for a holding linked to a pick, the main signals behind that pick have reversed sign.
2. **Trim:**
   - the position exceeds the max size for its current risk level, **or**
   - the unrealized gain is 25% or more **and** the 21-day momentum percentile has dropped below 40.
3. **Add:** the holding would qualify as a Buy pick today (§6.1) **and** the position is below its max size.
4. **Hold:** everything else, shown with the expected remaining hold time and an exit-by date.

**Badges on top of the action:**
- **Review:** earnings or a binary catalyst is within 5 trading days, **or** the latest bar is a flagged, unconfirmed jump.

**Trailing stop:** the highest close since purchase minus 2.5 × ATR(14). It only moves up, and never sits below the original stop.

### 7.4 Portfolio-level checks

- Values are shown in **CAD**. USD positions are converted at the latest Bank of Canada rate.
- A warning when any single sector is above 25% of portfolio value.
- A warning when any position is above its risk-based max.
- A breakdown of portfolio value by risk level, market and account.
- Portfolio return in CAD vs XIU.TO and vs SPY (converted to CAD), since the first buy and over 1, 3 and 12 months.

### 7.5 Account and tax awareness (Canada)

Informational only, labeled "not tax advice". These rules add warnings and never change the action.

- **Sheltered accounts (TFSA, RRSP, FHSA):**
  - No tax warnings on Sell or Trim.
  - **TFSA trading frequency:**
    - The CRA can treat frequent TFSA trading as carrying on a business, which makes gains taxable.
    - The app tracks TFSA round trips and the share of holds under 30 days over the last 12 months.
    - It warns as these approach an owner-editable guideline: by default 24 round trips a year, or most holds under 30 days. There is no official cutoff.
    - Swing picks note that they add to the count.
  - **US dividends in a TFSA** lose 15% to US withholding tax. This is a one-time note on US dividend payers held in a TFSA.
- **Taxable accounts (Crypto, non-registered):**
  - Show unrealized gain or loss in CAD and an estimated taxable amount (gain × 50% inclusion).
  - **Superficial loss:**
    - When a Sell would realize a loss, warn that buying the same asset within 30 days before or after the sale denies the loss.
    - Flag an Add suggestion on an asset sold at a loss in the last 30 days.

## 8. Data Model (Supabase Postgres)

| Table | Key columns |
|---|---|
| `app_config` | owner_id |
| `settings` | One row: usd_fx_fee_pct (1.5), crypto_fee_pct (2.0), tfsa_round_trips_warn (24), tfsa_short_hold_share_warn (0.5), updated_at. Kept apart from `app_config` so the owner can edit fees without write access to owner_id |
| `schema_migrations` | name, applied_at (RLS on, no policies) |
| `runs` | id, kind (pre_open / pre_close / early_close), et_date, started_at, finished_at, status (running / success / degraded / failed), published, sources_ok, sources_total, model_version, summary (jsonb) |
| `source_health` | run_id (null for health checks), context (run / health), source, status (ok / partial / stale / failed / skipped), latency_ms, records, error, consecutive_failures, attempted_at |
| `symbols` | symbol, asset_type, **market** (US / TSX / null for crypto), name, exchange, sector, industry, market_cap, active |
| `features_live` | run_id, symbol, asset_type, features (jsonb), as_of. Holds the shortlists, holdings and watchlist |
| `predictions` | run_id, symbol, asset_type, horizon_days, q10, q50, q90, p_beat, benchmark, model_version |
| `picks` | id, run_id, symbol, asset_type, **market**, style (swing / position), horizon_days, exit_by, entry_ref_price, stop, risk_level, risk_score, max_position_pct, rank, top_factors (jsonb), catalysts (jsonb), status (open / exited_early / graded) |
| `pick_outcomes` | pick_id, exit_price, exit_reason, ret, ret_net_of_fx, bench_ret, excess, beat, hit_stop, graded_at |
| `watchlist` | symbol, asset_type, added_at |
| `watchlist_verdicts` | run_id, symbol, asset_type, verdict, reasons (jsonb), details (jsonb) |
| `lots` (buys) | id, **account**, symbol, asset_type, qty, price, **currency**, **fx_rate_cad**, bought_at, pick_id, notes |
| `sells` | id, **account**, symbol, asset_type, qty, price, **currency**, **fx_rate_cad**, sold_at |
| `holding_actions` | run_id, **account**, symbol, asset_type, action (sell / trim / add / hold), review, reasons (jsonb), trailing_stop, q10, q50, q90, exit_by, warnings (jsonb) |
| `news_items` | id, symbol, published_at, outlet, url, title, sentiment, cluster_id. Pruned after 90 days |
| `models` | version, kind (stock_us / stock_tsx / crypto), trained_at, metrics (jsonb), calibration_error, active |
| `daily_closes` | symbol, asset_type, day, close, currency. Yahoo's adjusted closes for holdings, the watchlist, the shortlist and SPY and XIU.TO, reaching a year back or to the first buy; Coinbase closes in USD for held and watched coins. Pruned after 2 years, except symbols ever bought and the benchmarks |
| `fx_rates` | day, usd_cad. The Bank of Canada's daily rate, reaching a year back or to the first buy |

- **Symbol formats** are enforced by CHECK constraints:
  - US stocks: `^[A-Z]{1,5}(\.[A-Z])?$`
  - TSX stocks: `^[A-Z]{1,5}(-[A-Z]{1,2})?\.TO$`
  - crypto: `^[A-Z0-9]{2,10}$`
- **Row-level security:**
  - Every table is readable only by the owner (`public.is_owner()`).
  - The owner can write only `watchlist`, `lots` and `sells`, and can update (never add or delete) the `settings` row.
  - `pipeline_rw` has explicit policies on every table: read-only on owner-written tables, `settings` and `app_config`, and no access to `schema_migrations`. Tests enforce both.
- **Storage:** training Parquet (prices, fundamentals) goes in a private Supabase Storage bucket, kept under about 600 MB.

## 9. Dashboard (web/)

- **Stack:** Next.js (App Router) and `@supabase/ssr` with Supabase Auth (email and password, single user, sign-ups disabled), deployed on Vercel.
- **Charts:** TradingView `lightweight-charts` (Apache-2.0) for price charts and forecast cones, and Recharts for track-record and calibration charts.
- **Visual design:** follows the **superdesign workflow in the workspace CLAUDE.md**: layout, then theme, then animation, then HTML, with owner sign-off at each step.
- **Disclaimer:** "Not financial or tax advice. Forecasts are probabilistic and can be wrong."

| Page | Contents |
|---|---|
| Top bar (all pages) | Last runs with status, Paper/Validated badge per market, sources OK (e.g. 49/53), stale banner if the latest run failed, missed-slot notice |
| **My Portfolio** (home) | **Value and returns:** total value in CAD, with return vs XIU.TO and SPY. **Actions:** cards sorted Sell → Trim → Review → Add → Hold. **Holdings table:** account, symbol, market, P/L in CAD, action, range, trailing stop, exit-by, risk, warnings. **Warnings:** portfolio-level checks, plus TFSA trading-frequency and superficial-loss warnings. **Data entry:** add a buy, add a sell, import a file |
| **Today's Picks** | **US and TSX tabs**, each with Swing and Position lists. A card per pick shows the range bar, P(beat), hold time and exit-by, stop, risk and max size, estimated cost (US shows the conversion fee), top factors, catalysts and an "I bought this" button. Also: watchlist verdicts and exit-early flags |
| **Ticker Detail** | Price chart with forecast cone, top factors, news, catalysts, which sources contributed (TSX shows its thinner coverage), and past picks and outcomes |
| **Track Record** | Per market, live vs backtest shown separately: hit rate, average excess return (gross and net of costs), calibration by horizon and risk level, every past pick, and the survivorship-bias note |
| **Watchlist** | Add or remove US stocks, TSX stocks and crypto, with the latest verdict for each |
| **Source Health** | All sources: last success, latency, records, errors, circuit-breaker state, latest daily check |
| **Settings** | USD conversion fee, crypto spread, TFSA guideline thresholds |

## 10. Error Handling

- **Per source:**
  - timeout, retries and the run deadline;
  - cadence-window cache, fallback within `freshness` and partial backfill;
  - circuit breaker.

  A failure only affects that source's features, which become missing values.
- **Run status:**
  - `failed` if a universe or prices can't be loaded (too few fresh priced symbols), or the model can't be loaded. A failed run is never published, and the dashboard shows the last published run with a stale banner.
  - `degraded` if any core source isn't OK.
  - `success` otherwise.
  - An unexpected error marks the run failed and fails the job, which sends GitHub's failure email.
  - Runs left `running` for more than 2 hours are swept as abandoned.
- **Validation:** pydantic schemas per record type. Sanity rules:
  - prices must be above 0;
  - **jump rule:** a daily move above 50%, against both the last accepted close and the previous close, is **flagged as unconfirmed** rather than dropped, because Yahoo is the only stock price source. Flagged bars feed the jump indicator feature, block a Buy on that symbol (§6.1), and add a Review badge to holdings;
  - a market's last bar more than one session behind its expected session counts as missing.
- **Model guard:** the last good model is kept if retraining fails promotion. If no active model passes calibration for a market, that market's picks are suppressed with "No picks today: model check failed", and holdings fall back to trailing-stop and size rules.
- **Free-tier limits:**
  - Twice-daily writes keep Supabase from pausing.
  - News is pruned after 90 days.
  - Training data lives in Storage.
- **Alerts:** GitHub's built-in failure email, for failed runs, missed slots and a failing core source in the daily check. Nothing else.

## 11. Testing

- **Unit tests** (pytest):
  - each collector against recorded real responses, with no live network in CI;
  - feature functions against hand-computed values;
  - recommender, risk, holdings-action, per-market cost, average-cost (ACB), TFSA-frequency and superficial-loss rules, all table-driven.
- **Look-ahead test:** inject records dated after `as_of` and assert that no feature changes.
- **Backtest report** (`train.yml`), per market: walk-forward hit rate, excess return after costs, calibration curve and error, and the promotion gates.
- **Pipeline end-to-end:** full runs on recorded data against a Postgres service container, covering atomic publish, holdings first, partial sources, the deadline, and both markets.
- **Database:**
  - RLS and pipeline-role invariants on every table;
  - symbol-format constraints for all three formats;
  - migration runner (no-op, rollback, baseline).
- **Dashboard:** Playwright tests for login; adding a buy, a sell and a watchlist item; every page rendering with seed data; and the stale and paper banners.
- **CI:** `ci.yml` runs all of the above on every push.
- **Live checks:** `health.yml` fetches every source's canary daily.

## 12. Repository Layout

```
stock-advisor/
  pipeline/                 Python 3.12, uv
    src/advisor/
      collectors/{base, cache, runner, tracker, registry, <one module per source>}.py
      schedule.py  screener.py  prices.py  enrich.py  symbols.py  health.py  run.py
      features/  model/  recommend/  portfolio/  grade.py  train.py
      store/{db, migrate, repo}.py
    scripts/in-docker.sh    run tests in Linux (dev machine blocks psycopg's DLLs)
    tests/{fixtures/, unit/, integration/}
  web/                      Next.js dashboard
  supabase/migrations/      append-only SQL: schema, RLS, roles
  .github/workflows/{run.yml, train.yml, health.yml, ci.yml}
  docs/superpowers/{specs, plans, deferred.md}
```

This is a standalone private GitHub repo. GitHub Actions and Vercel are both configured per repository.

## 13. Risks and Open Points

| Risk | Mitigation |
|---|---|
| The model doesn't beat a market's benchmark | Per-market acceptance gates disable that market's picks and show the metrics. Holdings tools still work |
| **Yahoo is the only stock price source**, and it's unofficial | Low-volume use and the circuit breaker. A Yahoo outage fails the run, and GitHub emails the owner. The owner chose this over a second unofficial source |
| TMX directory, CNN, StockTwits or Trends break | Best-effort flags and circuit breaker. A TMX outage serves the cached TSX universe (3-day freshness) and degrades the run |
| TSX stocks have thinner data | Missing-feature-aware model, a per-market model and gates, a Medium risk floor for sparse stocks, and coverage shown on Ticker Detail |
| **CRA treats frequent TFSA trading as a business** | Trading-frequency warning with editable guidelines; swing picks note their effect |
| USD conversion costs (about 3% round trip) erode US returns | Costs are built into qualification and grading. Settings handle a future USD account |
| GitHub cron delay pushes pre-close results past 3:45 PM | Runs start 15 minutes early. Late triggers alert, and each run shows its completion time |
| Free source terms or limits change | One module per source, so a source can be swapped or removed without touching anything else |
| Survivorship bias inflates backtests | Disclosed on the Track Record page. The live record is shown separately and given more weight |
| Supabase or Actions free-tier limits | Budgets in §3 and §10, and usage shown on Source Health |
