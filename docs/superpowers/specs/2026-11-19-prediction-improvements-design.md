# Prediction improvements: design

Date: 2026-11-19. Status: draft for the owner's approval.

## Why

The US model ranks stocks reasonably well (pooled rank IC 0.089 for `garch+ranker+forest`, against
0.053 for the baseline), but it produces no picks. A pick needs P(beat) of at least 0.58 and the
highest P the model gives is 0.533. The benchmark's default policy made 0 trades in every fold, and
the tuned-policy row (`full+policy`) was rejected in every market.

The owner asked for four things, all of them: pick by rank, add new data, average more models, and
fix the survivorship gap. Research and two code and data checks on 2026-11-19 shaped what each one
means here. This document orders them as four plans. Each plan ends with a benchmark run and stands
on its own.

## What the checks found

- **A top-N rule already exists and has never gone live.** `Policy.top_n` is wired through the
  backtest, the policy search, the live picks and the Invest page. It ranks by the calibrated P.
  The calibrator clips P at a ceiling (the beat rate of the top 5% of scores), and in the
  2026-11-06 US model at least 1% of forecasts sat tied at that top value. Ties are broken alphabetically by symbol
  (`model/backtest.py:61`, `recommend/picks.py:61`). "Top 5" is partly the first five tickers in
  the alphabet.
- **Live rows carry no raw score.** `PredictionRow` and the `predictions` table hold only
  `q10, q50, q90, p_beat`. Walk-forward frames do have `score`.
- **The benchmark has no top-of-ranking measure.** Rank IC covers the whole ranking; nothing
  reports how the top slice does.
- **Short interest, analyst events, options and 13F are collected on live runs but never stored as
  history and never trained on.**
- **Averaging three seeds tripled the US benchmark time for no gain** (`ranker+extras+bagged`
  against its twin). The forest was never tested with a bag.
- **Free history that exists** (verified by live fetches):
  - FINRA short interest, twice monthly, exchange-listed stocks included, from settlement
    2017-12-29: `https://cdn.finra.org/equity/otcmarket/biweekly/shrtYYYYMMDD.csv`. Published
    about 12 business days after settlement.
  - Yahoo `upgradeDowngradeHistory`: timestamped analyst rating and price-target events, dense
    from about 2019 for US names, capped near 1,000 rows a symbol, thin for TSX. Needs Yahoo's
    cookie and crumb.
  - DoltHub `post-no-preference/stocks`: daily raw prices from 2011 with split and dividend
    tables. It keeps dead tickers (TWTR, SIVB). Its licence was not checked.
  - Tiingo `supported_tickers.zip`: start and end dates per ticker, no key. Incomplete.
- **Free history that does not exist:** per-stock option data for the whole universe; estimate
  revisions (Yahoo and Nasdaq give snapshots only); TSX short positions without a browser.

## Goals

1. Picks follow the model's actual ranking, in the benchmark and live, the same way in both.
2. The benchmark shows how the top of the ranking performs, after costs.
3. Every US data group the app already collects live, and that has free point-in-time history,
   is tested as model input under the existing acceptance rule: short interest, analyst rating
   events, insider trades, 8-K events, 13F ownership changes, and earnings (the SEC-filed numbers
   and the result against the analysts' estimate). Added 2026-11-19 at the owner's request
   ("give the model all the data").
4. Dead stocks are in the US training and evaluation history, so results stop being flattered.
5. Seed averaging: considered and left out of the build; see Plan 7a.

## Non-goals

- TSX and crypto get no new features. TSX keeps its current model.
- Option-implied features and estimate revisions. See "Left out, and why".
- Any change to the web app beyond what the stored raw score needs. The Invest page already
  handles a rank policy.
- A new model type. LightGBM stays.

## Anti-goals

- Loosening an acceptance limit or a policy limit (30 trades, 25% drawdown, 20 trades a month,
  the pinball tolerance, the calibration limit) to get something accepted.
- A feature that reads data before it was public.
- A live feature computed differently from its training twin.
- Reporting "better" from a run whose universe differs from the run it is compared with.

A plan whose benchmark row is rejected is a finished plan with a result, not a failure to retry
until it passes.

## Constraints

- Free data only. No keys or tokens in the repo. The owner pushes; nothing is pushed or merged
  without asking.
- The benchmark job has 360 minutes and the weekly train job 180, both pinned by
  `tests/unit/test_benchmark_workflow.py`. US variants took about 141 minutes in the last run. A
  plan that adds rows measures its added time on real data before it is called done.
- Variant names match `^[a-z+]{1,40}$`.
- Acceptance stays as `benchmark/accept.py` has it.
- TDD and the repo's usual plan and review flow.

## Plan 7a: rank picks by the raw score

**What changes**

- The raw score is the booster output that P is calibrated from: `p_raw`, the rank booster's
  output for a ranker model and the beat classifier's for any other. P is a monotone map of it, so
  ranking by it agrees with ranking by P wherever P does not tie, for every model type.
- The live prediction carries it. `PredictionRow` gains `score` and `FinalModel.predict` keeps it.
  Nothing reads predictions back from the database to rank, so no column is added (revised
  2026-11-19, my call; the first draft added one).
- Rank mode decides who is in the top N by the raw score descending, then by symbol, in all three
  places: `in_top_n` (`model/backtest.py`), `top_by_horizon` (`recommend/picks.py`) and the policy
  book's candidates (`benchmark/simulate.py`). Only that qualification changes. Choosing each
  stock's horizon and ordering the list still follow `policy.rule`, as today. P stays as the
  displayed probability and as the rule for Avoid and Sell.
- A row with no P or no raw score never ranks.
- A new benchmark measure, the top-slice return, per variant, fold and horizon: each day, the mean
  excess return `y` of the top 5% of stocks by score, minus the mean of all stocks that day, then
  the average over days. Fold 0 is included, since it has scores. The report also shows the same
  number after `round_trip_cost`, and the bottom 5%. It is reported, not part of the acceptance
  rule (my call).
- The policy search grid stays as it is (my call).

**Seed averaging is not in this plan** (revised 2026-11-19). A bagged row triples its own run
time, and if it were chosen the policy row's inner runs would triple too: about 43 and 90 more
minutes on a US benchmark that already takes 141, which passes 80% of the 360-minute limit before
TSX, crypto and the data build are counted. The earlier three-seed test showed no gain. It can be
run later as a one-off if the owner wants the number.

**Done when** the US benchmark runs with these changes and the report shows the top-slice table.
The policy row may still be rejected; the report then says why with real rankings behind it.

**Known limit, not fixed here:** live ranking covers only the forecast stocks (holdings, watchlist
and the screener shortlist of 300), while the backtest ranks every eligible stock
(`deferred.md:138`).

## Plan 7b: short interest and analyst events (US)

**History, built by `training/build.py`**

- `short_interest.parquet` from the FINRA twice-monthly files, 2017-12-29 onward: symbol,
  settlement date, shares short, average daily volume, days to cover. A value counts as known 12
  business days after its settlement date (a fixed rule, because the true publication dates of
  old files cannot be recovered).
- `analyst_events.parquet` from Yahoo `upgradeDowngradeHistory`, one request per US symbol:
  timestamp, firm, action, from and to grade, price-target action.

**Features**

- Short interest: `short_pct_shares` (shares short over shares outstanding from the fundamentals
  file), `days_to_cover`, `short_chg` (change from the previous report, as a share of shares
  outstanding).
- Analyst events: `net_upgrades_30d`, `net_upgrades_90d` (upgrades minus downgrades),
  `net_target_raises_90d` (target raises minus cuts), `days_since_downgrade`.
- A symbol's analyst features are missing, not zero, before its first recorded event, and missing
  for any symbol whose history is at the 1,000-row cap before the row's date range begins.

**Model and benchmark**

- Two config fields, `short` and `analyst`, with a config version bump, following the earnings
  group's pattern file for file (`model/earnings.py`, `dataset.py`, `variants.py`,
  `benchmark/job.py` and their tests).
- Two US-only rows on the current US config: `garch+ranker+forest` plus `short`, and the same plus
  `analyst`.
- A feature row must beat its base row, `garch+ranker+forest`, under `accept_model`, as well as
  the baseline. This extends the twin rule that bagged rows already have (my call). Without it a
  feature row would pass whenever its base passes.
- The history is read through yfinance, as the existing analyst collector does.
- FINRA re-issues files after first publication, so the history holds revised values. This is a
  small look-ahead that cannot be removed with the data available; the plan records it as a known
  limit.
- Live: the run computes the same features from the same sources for every forecast US symbol. The
  analyst collector's cap of 200 symbols a run has to rise to cover the forecast set, or the
  feature is missing for the rest; the builder measures the added run time.

**Done when** the US benchmark runs with both rows and the report shows each one's decision.

**Terms:** Yahoo's API is unofficial. The app already depends on Yahoo for prices; this adds one
more Yahoo call per symbol per training build and per forecast symbol per run. The owner's
standing reading of data-source terms applies.

## Plan 7c: SEC events — insider trades, 8-K events, 13F ownership (US)

Revised 2026-11-19. Sources checked: SEC's quarterly data sets and bulk files, plus files the
project downloaded live in October. SEC refused this session's research requests (it wants an
email in the User-Agent); the pipeline sends the owner's `SEC_USER_AGENT`, so the build is not
affected, but the plan's first step re-checks the points marked unverified below.

**History, built by `training/build.py`**

- `insider_trades.parquet` from SEC's Insider Transactions Data Sets (Form 3/4/5), one zip a quarter
  from 2018 Q1 (about 35 zips, 350 MB). Kept: Form 4 and 4/A, open-market purchases (P) and sales
  (S) of common stock, with shares, price, the owner's role (officer, director, 10% owner), the
  filing's acceptance time (joined from the submissions file by accession; the filing date plus
  one session when that is missing), and the issuer's ticker as filed. The download links are read
  from SEC's listing page, not built.
- `material_events.parquet` from SEC's nightly `submissions.zip`: every 8-K and 8-K/A with its item
  codes and acceptance time, for every US symbol's CIK, 2018 onward. The `acceptanceDateTime`
  field is read as New York wall-clock time (a known SEC quirk, already handled in `sec.py`).
  Unverified: whether the zip holds each company's older filing pages; if not, those pages are
  fetched per company (about one extra request a company).
- `holders.parquet` from SEC's Form 13F data sets, 2018 onward: per CUSIP per quarter, shares held
  and the number of distinct holders, built with the same rules as the live `sec_13f` collector.
  CUSIPs map to tickers through OpenFIGI, as live. A quarter's figure counts as known 45 days after
  the quarter ends, or on the data set's publication date if later.
- A symbol whose CIK or CUSIP cannot be found gets missing features, not zeros.

**Features** (each reads only what was public strictly before the row's day)

- Insider (`insider`): `insider_net_buy_90d` (open-market buy minus sell dollars over 90 days, as a
  share of market value), `insider_buyers_90d` (distinct insiders who bought), `officer_buy_180d`
  (1 if an officer bought on the open market within 180 days).
- 8-K events (`events`): counts over 90 days of item 5.02 (officer or director change), 1.01
  (material agreement), 2.01 (acquisition or sale of assets), 4.02 (restatement) and 3.01
  (delisting notice), and `days_since_8k`.
- 13F (`holders`): `holder_count_chg` and `inst_shares_chg` (quarter on quarter, the second as a
  share of shares outstanding).

**Live:** the existing `sec_insiders`, `sec_events` and `sec_13f` collectors give the same records
for forecast symbols. Their lookbacks must cover the longest window above (180 days for insiders;
today 90), and the insider collector's 1,000-document cap per run must cover the forecast set.

**Done when** the US benchmark runs with the three rows and the report shows each decision.

## Plan 7d: earnings (US)

**What exists:** `model/earnings.py` already turns SEC-filed quarters into four features (revenue
growth, margin change, standardised EPS surprise against the same quarter a year before, days
since the report). They passed as `ranker+earnings` but have never been tried on the current US
model, `garch+ranker+forest`.

**What is new**

- `earnings_estimates.parquet` from Yahoo's earnings calendar through yfinance
  (`get_earnings_dates`, one request per US symbol, about 37 reports since 2018 each): report day,
  before-open or after-close, the analysts' consensus EPS and the reported EPS. A report counts as
  known from the first session after it.
- Features (`estimates`): `eps_surprise_last` (reported minus consensus, over the absolute
  consensus, clipped), `eps_beat_streak` (how many of the last four beat), and
  `days_to_next_report`, estimated as the same quarter's report a year earlier plus 364 days. The
  real announcement date of a future report is not known historically, so the actual date is never
  used.
- Yahoo shows the final consensus before each report. A row never reads a report on or after its
  own day.
- Nasdaq.com's earnings history is not used: its terms forbid automated capture and model training.

**Live:** `yfinance_earnings` already collects the same fields for forecast symbols.

**Done when** the US benchmark runs with an `earnings` row on the current model and an `estimates`
row, and the report shows each decision.

## Benchmark rows for 7b–7d

- One row per new group on the current US config `garch+ranker+forest`: plus `short`, `analyst`,
  `insider`, `events`, `holders`, `earnings` and `estimates`. Each must beat that base row as well
  as the baseline (7b's twin rule).
- One more row, added by the last of these plans, with every group that passed. It is judged the
  same way. This is how the model gets "all the data": every group that earns its place.
- Seven new rows at about 7–14 minutes each would push the US benchmark well past 80% of its limit.
  So rows that the last two benchmarks rejected in every market they ran in are retired, after the
  plan confirms that from the stored results (likely `factors`, `extras`, `ranker+extras`,
  `ranker+extras+bagged` and `factors+garch`; my call). Each plan still measures its added time,
  and the 80% stop rule below applies.
- Variant names must fit 40 characters. Fitting the combined row's name is the builder's call.

## Plan 7e: dead stocks in the US history

**Prototype first.** Before a plan is written, a throwaway script measures: how many dead US
common stocks 2018–2026 the sources give, how closely prices adjusted from DoltHub's split and
dividend tables match Yahoo's adjusted prices on 50 living symbols (the daily returns must agree
within 0.5 percentage points on 99% of days), and how much the training row count and the build
time grow. It also reads the DoltHub stocks repo's licence. If the licence does not allow
personal use, or the adjusted prices do not match, the plan stops and comes back to the owner.

**Design, subject to the prototype**

- Dead symbols come from DoltHub `stocks` (last seen before the build date), kept only when
  Tiingo's ticker list marks them as a stock on a US exchange and they have at least 60 sessions
  inside the 8-year window.
- A ticker reused by a later company is two different stocks. A dead stock is keyed by ticker and
  date range, and is dropped where its dates overlap a living symbol of the same ticker.
- Dead stocks have no sector and no fundamentals (the SEC ticker map is current-only). Their
  sector is "Unknown" and those features are missing.
- Today, a row whose forward window runs past a stock's last price has no target and is dropped,
  so the weeks before a delisting vanish. For a dead stock the window instead ends at its last
  traded price, and the benchmark's return is measured over the same shortened window (my call).
  This is still kind to bankruptcies, which often trade lower afterwards
  off-exchange, and the report banner says so.
- The benchmark is run once with and once without dead stocks, so the size of the old bias is on
  record. After that the with-dead universe is the standard, and the incumbent model is re-judged
  on it under the usual rule.

**Done when** the two benchmark runs are on record and the incumbent has been re-judged.

## Time budget

Both workflows rebuild the training data before they train, so new history downloads count against
the same limits. Each plan measures its added build and benchmark time on real data. If a job would
pass 80% of its limit, the plan stops and comes back to the owner; no timeout is raised and no row
is dropped without asking.

## Order

7a, 7b, 7c, 7d, then 7e. 7a needs no new data and decides whether rank picks work at all. 7b, 7c and
7d each add data groups; their rows can share one monthly benchmark run once all three are in. 7e
changes every number, so it goes last and re-bases the comparison once.

## Left out, and why

- **Option-implied features.** No free source covers the universe. DoltHub has implied volatility
  for about 1,500 large and mid caps from 2019, sparse before 2025, kept by a volunteer. Revisit
  after 7b shows whether a new data group can pass the acceptance rule.
- **Estimate revisions.** Snapshots only; history would have to be stored for years first.
- **The date a future earnings report was announced.** No free source keeps it; 7d estimates the
  date from the year before instead.
- **News and sentiment.** Collected live only, with no free history to train on.
- **Insider plan trades (10b5-1).** SEC flags them only from 2023, so 2018–2022 cannot tell them
  apart.
- **TSX short positions.** The regulator's site blocks plain requests.
- **More than three seeds.** Time limit, and no evidence of gain.

## Left to the builder

- How a dead stock is named so that every join keyed on `symbol` still works.
- Exact function signatures, the migration number, and where the top-slice measure lives.
- How the FINRA and Yahoo history downloads are batched, cached and retried.
- The 7e prototype's method.
