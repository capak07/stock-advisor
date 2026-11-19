# Plan 7b–7d: every US data group the app collects — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build point-in-time history for the US data groups `short`, `analyst`, `insider`, `events`, `holders`, `estimates` and `catalysts` (plus the existing `earnings`), compute the same features live from the collectors, and judge one benchmark row per group on `garch+ranker+forest` against that base row and the baseline, plus one row with every group that passed.

**Architecture:** Each group has a pure feature module in `pipeline/src/advisor/model/` in the style of `model/earnings.py`: a long history frame in, wide day × symbol frames out, and a row reads only what was known strictly before its day. `training/build.py` writes one Parquet history per source: the weekly `history.yml` runs it with `--history-only` into an actions cache, and the benchmark and train builds copy the files from that cache with `--no-history-download` (Ruling R0). `model/groups.py` carries them as a `GroupHistory`, which `dataset.feature_frames` turns into extra columns for training and live alike; `model/live_groups.py` builds the same `GroupHistory` from the run's collector records. `ModelConfig` gains one flag per group. `benchmark/job.py` adds the rows, a generalised base-row rule, a combined row built in the same run from the groups that passed, and retires four rows that the stored results rejected everywhere.

**Tech Stack:** Python 3.12, pandas, LightGBM, httpx, yfinance, pytest. Tests run in Docker from the repo root: `bash pipeline/scripts/in-docker.sh uv run pytest tests/unit/<file> -q` (integration tests need the `advisor-pg` container).

**Spec:** `docs/superpowers/specs/2026-11-19-prediction-improvements-design.md` — "Plan 7b", "Plan 7c", "Plan 7d", "Benchmark rows for 7b–7d", "Every source in the app", "Time budget". Not 7a (done) and not 7e.

## Global Constraints

- US only. TSX and crypto get no new features: their rows read the new columns as NaN and run no new row.
- Point in time: every record has a `known` date K. A row on day D reads it only when K < D (strictly before), as `fundamentals._asof` does (`allow_exact_matches=False`). A window of N days is `D − N days ≤ K < D`.
- Known dates, the same in training and live:
  - SEC filing (8-K, 13D/G, Form 4): the ET date of the true acceptance time (`sec.true_acceptance`); when it is missing, `schedule.sessions_after(Market.US, filing_date, 1)`.
  - FINRA short interest: `sessions_after(Market.US, settlement, 12)`. This is a fixed rule, because the true publication dates of old files cannot be recovered.
  - FINRA daily short volume: the trade date. The file is published that evening and read from the next session.
  - Yahoo rating change: the ET date of its timestamp. Yahoo earnings report: its ET report date (read from the first session after it).
  - 13F quarter: the later of period end + 45 days and the data set's window end + 30 days (`holders.quarter_known`; SEC's listing shows no publication date, Ruling R6). Live applies the same rule to the same data sets (Ruling R3).
  - openFDA approval or recall: its date + `FDA_LAG_DAYS = 7`. openFDA refreshes weekly, so live sees an event up to a week late, and training waits the same week.
- Missing, not zero:
  - A symbol with no SEC facts (its CIK is not among the CIKs in `fundamentals.parquet` or in the run's `sec_xbrl` facts) reads NaN for `insider` and `events`. A symbol with SEC facts and no filings reads 0 counts.
  - `analyst` is NaN before a symbol's first recorded event.
  - `holders` is NaN without a quarter-on-quarter pair.
  - `estimates` is NaN without reports.
  - `catalysts` is 0 for every US symbol whenever the openFDA history is present.
- Share counts on today's basis: a share count dated T is multiplied by `fundamentals._split_at(splits, symbol, T)` before it is compared with another (short interest, 13F shares, shares outstanding).
- Live: a source whose run status is not `CollectorStatus.OK` contributes NaN for its features in that run, never zeros. Live uses the same feature function and the same code path as training (`feature_frames`), with the training known dates and windows everywhere, so its collectors fetch enough to fill them: three FINRA settlements, 21 short-volume files, 187 openFDA days and three 13F data sets (Ruling R3, Task 11).
- `ModelConfig` gets the flags `short, analyst, insider, events, holders, estimates, catalysts` (default False; `earnings` exists). There is one bump: `CONFIG_VERSION = 6`. Versions 1–5 load with the new flags off.
- Variant names match `^[a-z+]{1,40}$` (`supabase/migrations/0010_benchmarks.sql:14`).
- Acceptance limits are unchanged: `PINBALL_TOLERANCE`, `MIN_FOLDS_IMPROVED`, `MAX_CALIBRATION_PTS`, `INCUMBENT_CALIBRATION_PTS` and the policy limits. A rejected row is a result, not something to retry.
- Time budget: `benchmark.yml` has `timeout-minutes: 360`, `train.yml` 180 and the new `history.yml` 180, all pinned by `pipeline/tests/unit/test_benchmark_workflow.py`. Group history is downloaded only by the weekly `history.yml`, into an actions cache that `benchmark.yml` and `train.yml` restore and never refill (Ruling R0, Task 9). Projection after R0 (Task 0 ledger): history job about 98 min (54% of 180), benchmark about 210 min (58% of 360: 202.6 plus one incumbent row of about 7), train about 57 min (32% of 180). If a projection passes 80% (288 for the benchmark, 144 for train and for history), stop and come back to the owner. No timeout is raised and no row is dropped without asking; `catalysts` is the row proposed first.
- Free data only, and no keys in the repo. `SEC_USER_AGENT` is read from the environment and never printed. Locally it is loaded with `export SEC_USER_AGENT="$(sed -n 's/^SEC_USER_AGENT=//p' pipeline/.env.local)"` (Ruling R1: the `grep | xargs` form splits the value on its space and prints part of it). Nasdaq.com's earnings history is not used.
- `git commit` runs as its own shell command (a hook blocks any `-n` flag in the same command). Never `--no-verify`. No push, no merge.
- Commit trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. A live run where the Form 4 document budget runs out, or Yahoo stops answering: the affected source's features must be NaN for every symbol in that run, never zero counts. (Task 11)
2. A split between two short-interest reports or two 13F quarters: `short_chg` and `inst_shares_chg` must not show the split as a change. (Tasks 2, 6)
3. A row dated exactly on a known date (an 8-K accepted that morning, a short-interest file's 12th session, a report day): it must not read the new record. (Tasks 1–8)
4. A month where the active config is the combined row and this run's passing groups differ, or where the active config is a retired row: the incumbent must still be scored and judged under the incumbent rule. (Task 12)
5. An old source file in an older layout (a 2017 FINRA header, a 2018 13F data set without a FIGI column, a quarterly 13F file name): the build reads it by column name or records the gap. It does not crash. (Tasks 2, 6)
6. A benchmark or train run whose history cache is missing, or holds a group written more than 21 days ago: that group is recorded in `manifest["unavailable"]`, its benchmark rows read "no data" and a config that needs it fails closed in training; nothing trains on stale or empty files. A non-due Sunday touches no cache, and a failed history run still saves what it downloaded. (Task 9)

---

### Task 0: verify the unverified sources and project the time (throwaway)

**Files:**
- Create (not committed): `pipeline/.cache/probe_7b.py` (`pipeline/.cache/` is git-ignored). Downloads go to a new, empty `pipeline/.cache/probe-7b/`.
- Modify: the "Task 0 ledger" in this plan.

**Interfaces — Produces:** the ledger values that later tasks read: whether the overflow pages are inside `submissions.zip`, the Form 3/4/5 link regex, the older 13F file-name pattern and FIGI column, the 13F publication-date rule, `ANALYST_CAP_ROWS`, the 2017 FINRA header, openFDA's depth, and the per-source seconds.

- [ ] **Step 1: Load the SEC user agent without printing it.** From the repo root: `export SEC_USER_AGENT="$(sed -n 's/^SEC_USER_AGENT=//p' pipeline/.env.local)"` (Ruling R1). Never echo it. The probe sends it only to sec.gov hosts.
- [ ] **Step 2: Write the probe.** Write one function per question. Each prints a one-line answer and its seconds. The questions:
  1. `https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip`: its size from `HEAD`. Download it once, which also gives the download time. Count the entries, and count the entries matching `-submissions-\d{3}\.json$`. Answer: are the overflow pages inside the zip?
  2. Form 3/4/5 data sets: fetch `https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets`. Find a regex that matches every quarterly zip link, 2006Q1–2026Q3. Download `2018q1`. Print the headers of SUBMISSION, REPORTINGOWNER and NONDERIV_TRANS, and say whether REPORTINGOWNER has `RPTOWNERNAME`.
  3. 13F: the link names on `sec_13f.LISTING_URL` for 2018 (quarterly `2018q1_form13f.zip` style, or window style). Download one 2018 set and print the INFOTABLE and COVERPAGE headers: is `FIGI` present, and is `AMENDMENTTYPE`? Time `sec_13f.aggregate` on it (patched to skip a missing FIGI column). Does the listing show a publication date for each set?
  4. Yahoo, for `AAPL`, `MSFT` and `CRUS`: from `yf.Ticker(s).get_earnings_dates(limit=100)`, the row count, the rows since 2018-01-01 and the columns. From `upgrades_downgrades`, the row count and the oldest date (the cap). The seconds per call over 50 universe symbols, for each call, at `YAHOO_PER_MINUTE = 120`.
  5. FINRA: the first and last settlement from the partitions API `https://api.finra.org/partitions/group/otcMarket/name/consolidatedShortInterest` (Ruling R6; the `/data/group/.../partitions` path of the first draft answers 404). The header of `shrt20171229.csv` compared with `finra_short_interest.HEADER`. Whether `CNMSshvol20180801.txt` exists, and its header. The seconds per file.
  6. openFDA: `meta.results.total` for `drug/enforcement.json?search=report_date:[20180101 TO 20181231]` and for `drug/drugsfda.json?search=submissions.submission_status_date:[20180101 TO 20181231]`. Whether `https://api.fda.gov/download.json` lists bulk files for both.
  7. OpenFIGI: the seconds per batch of 10 tickers at `OPENFIGI_PER_MINUTE = 25`.
- [ ] **Step 3: Run it.** `bash pipeline/scripts/in-docker.sh uv run python -I .cache/probe_7b.py` — every question prints an answer.
- [ ] **Step 4: Fill in the ledger and the projection.**
  - The projected added build minutes per source on the full universe (`tickers.parquet` had 5,612 rows on 2026-11-01). Give two numbers: the first build (empty cache) and the steady state (warm cache, Task 9).
  - The benchmark projection: the last US run's 141.5 min, minus the 41.8 min retired in Task 12, plus 9 rows × the measured `garch+ranker+forest` time (358.8 s on 2026-11-15), plus TSX 11.7 min, crypto 7.4 min, today's build (about 30 min) and the added build.
  - The train projection: today's job plus the added build of the groups an accepted config needs (none today).
- [ ] **Step 5: Apply the stop rule.** If either projection passes 80% (288 / 144 min), stop here and report the numbers to the owner, proposing `catalysts` first. Otherwise continue. Commit only the ledger: `docs: plan 7b task 0 ledger`.

**Task 0 ledger** (fill in; later tasks read these):

| Question | Answer |
|---|---|
| submissions.zip size / download seconds | 1,576,924,647 bytes (1.47 GiB; last-modified 2026-11-19 04:34 GMT) / 304.0 s on the dev machine (5.2 MB/s). |
| Overflow pages inside the zip | **Yes.** 999,057 entries, 5,430 match `-submissions-\d{3}\.json$` (e.g. `CIK0000005981-submissions-001.json`). For the 5,566 CIKs in `tickers.parquet`: all 5,566 main pages and 2,548 overflow pages read from the zip in 15.5 s (the zip opens in 5.9 s). No per-page SEC request is needed. |
| Form 3/4/5 link regex; first and last quarter; `RPTOWNERNAME` present | `href="(?P<path>[^"]*?(?P<name>\d{4}q[1-4])_form345\.zip)"` — 83 links, exactly `2006q1` … `2026q3`, none missing or extra. The links sit in two folders (`/files/structureddata/...` older, `/files/datastandardsinnovation/...` newer): read each path from the page, never build it. `RPTOWNERNAME` **present** in `REPORTINGOWNER.tsv` (2018q1). `SUBMISSION.tsv`: ACCESSION_NUMBER, FILING_DATE, PERIOD_OF_REPORT, DATE_OF_ORIG_SUB, NO_SECURITIES_OWNED, NOT_SUBJECT_SEC16, FORM3_HOLDINGS_REPORTED, FORM4_TRANS_REPORTED, DOCUMENT_TYPE, ISSUERCIK, ISSUERNAME, ISSUERTRADINGSYMBOL, REMARKS. `REPORTINGOWNER.tsv`: ACCESSION_NUMBER, RPTOWNERCIK, RPTOWNERNAME, RPTOWNER_RELATIONSHIP, RPTOWNER_TITLE, RPTOWNER_TXT, RPTOWNER_STREET1/2, _CITY, _STATE, _ZIPCODE, _STATE_DESC, FILE_NUMBER. `NONDERIV_TRANS.tsv`: ACCESSION_NUMBER, NONDERIV_TRANS_SK, SECURITY_TITLE, TRANS_DATE, DEEMED_EXECUTION_DATE, TRANS_FORM_TYPE, TRANS_CODE, EQUITY_SWAP_INVOLVED, TRANS_TIMELINESS, TRANS_SHARES, TRANS_PRICEPERSHARE, TRANS_ACQUIRED_DISP_CD, SHRS_OWND_FOLWNG_TRANS, VALU_OWND_FOLWNG_TRANS, DIRECT_INDIRECT_OWNERSHIP, NATURE_OF_OWNERSHIP (each with `_FN` footnote columns). |
| 13F 2018 file-name pattern; FIGI column in 2018; AMENDMENTTYPE in 2018 | Quarterly names `\d{4}q[1-4]_form13f\.zip` for 2013q2–2023q4 (2018 = `2018q1`…`2018q4`, about 43–48 MB each); window names `\d{2}[a-z]{3}\d{4}-\d{2}[a-z]{3}\d{4}_form13f\.zip` from `01jan2024-29feb2024` (11 sets, newest `01jun2026-31aug2026`, 96 MB). Older and newer files sit in different folders (`/files/structureddata/...`, `/files/datastandardsinnovation/...`). `FIGI` column **present** in 2018q1 and 2018q4 INFOTABLE, but **empty**: 0 rows with a FIGI in 2018q1 (1.88M rows), 2018q4 (2.04M), 2019q4, 2021q4, 2022q4. First filled in 2023q1 (203,746 of 2.79M rows, 7%); 2023q4 7%; newest window 447,779 of 3.83M (12%). So old quarters cast no FIGI votes: the CUSIP map must come from the newest quarter (as Task 6 has it). `AMENDMENTTYPE` **present** in COVERPAGE of 2018q1 and 2018q4 (and the newest window). Other headers: INFOTABLE has ACCESSION_NUMBER, INFOTABLE_SK, NAMEOFISSUER, TITLEOFCLASS, CUSIP, FIGI, VALUE, SSHPRNAMT, SSHPRNAMTTYPE, PUTCALL, ...; SUBMISSION has ACCESSION_NUMBER, FILING_DATE, SUBMISSIONTYPE, CIK, PERIODOFREPORT. |
| 13F publication date shown on the listing | **Not shown.** The listing table has only File, Format and Size columns (the title reads "2018 Q1 13F" or "2026 June July August 13F"). Use the rule: window end + 30 days. A quarterly file `2018q4` holds the filings of Oct–Dec 2018 (its reports are for 2018-09-30), so its window end is the calendar quarter's last day. |
| `aggregate` seconds per data set | 15.5 s for 2018q4 (2.04M rows, ran unpatched, no column missing); 21.3 s for the newest window (3.83M rows). Download 3.2 s (48 MB) / about 7 s (96 MB). The 35 sets from 2018q1 (24 quarterly + 11 window) take about 12.7 min. |
| Yahoo earnings rows since 2018 (AAPL / MSFT / CRUS) | 37 / 37 / 37, from `get_earnings_dates(limit=100)`, which returns exactly 100 rows each (oldest 2002-04 to 2002-07; newest is the future report, 2027-01-28 / 2027-01-27 / 2027-02-02), so the limit reaches back well past 2018. Columns: `EPS Estimate`, `Reported EPS`, `Surprise(%)`, indexed by report time in ET. |
| Yahoo `upgrades_downgrades` cap (`ANALYST_CAP_ROWS`) | No exact cap seen: AAPL 971 rows (oldest 2012-09-12), MSFT 955 (2012-10-01), CRUS 190 (2012-02-24). Use `ANALYST_CAP_ROWS = 1000`. |
| Seconds per Yahoo call (analyst / earnings) | Over 50 universe symbols at `YAHOO_PER_MINUTE = 120`, one limiter token per symbol: analyst `upgrades_downgrades` 0.49 s per symbol (call itself 0.11 s; limiter-bound), the project's full 3-call analyst load 0.51 s (call 0.29 s); earnings `get_earnings_dates(limit=100)` 0.56 s (call 0.54 s). 0 errors, no rate limit; empty answers 10 / 0 / 9 of 50. |
| FINRA first settlement; 2017 header equals `HEADER`; first short-volume day | The partitions URL given in the brief (`/data/group/otcMarket/name/consolidatedShortInterest/partitions`) answers **404**. The working one is `https://api.finra.org/partitions/group/otcMarket/name/consolidatedShortInterest` (200; `availablePartitions[].partitions[0]` holds the date; 213 dates, newest first): first **2017-12-29**, last 2026-10-30. `cdn.finra.org/.../shrt20171229.csv` header **equals `HEADER`** (14 columns, 1.5 MB). Earlier CDN files (2017-09-29 and before) answer 403. First short-volume day **2018-08-01** (`CNMSshvol20180731.txt` is 403; header `Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market`). Seconds per file incl. parse: 0.29 s short interest, 0.14 s short volume. |
| openFDA 2018 totals (enforcement / drugsfda); bulk files listed | `meta.results.total`: enforcement `report_date` 2018 = **1,426**; drugsfda `submissions.submission_status_date` 2018 = **2,788** applications. `download.json` **lists bulk files for both**, one partition each, exported 2026-11-19: `https://download.open.fda.gov/drug/enforcement/drug-enforcement-0001-of-0001.json.zip` (18,166 records, 4.1 MB) and `.../drug/drugsfda/drug-drugsfda-0001-of-0001.json.zip` (29,468 records, 9.4 MB); download 0.7 s + 0.6 s, parse 0.2 s + 1.1 s. Use the bulk files. |
| OpenFIGI seconds per 10 tickers | 2.4 s steady (the 25 per minute limiter; 3 batches took 4.9 s with the first on the burst token; 30 of 30 symbols mapped). 5,612 symbols = 562 batches = 22.5 min. |
| Projected added build, first / steady (min) | **98 / 98** wall-clock (the Yahoo thread alone, never cached: analyst 5,612 × 0.49 s = 45.8 min plus estimates 5,612 × 0.56 s = 52.4 min). The other thread: first 50.5 min (short 6.2, events 6.4, insider 1.7, holders 35.2 = 12.7 for 35 data sets + 22.5 OpenFIGI, catalysts 1.0), steady 30.8 min (short 0.3, events 6.4, insider 0.1, holders 23.0 as the plan's cache list leaves the OpenFIGI book out, catalysts 1.0). Work summed over both threads: 149 / 129 min. |
| Projected benchmark job / train job (min) | **Benchmark 300.8 min = 83.6% of 360 (over the 80% line of 288), first and steady:** 141.5 − 41.8 + 9 × 358.8 s (53.8) + 11.7 + 7.4 + 30 (today's build: 30.3 min, sum of the `seconds` in the 2026-11-01 manifest, macro included) + 98.2. **Train 57 min = 32% of 180** (30 build + 23.2 US + 1.2 TSX + about 2 crypto and setup; added build 0, since the accepted config needs no new group). Stop rule applies to the benchmark job. |
| Projection after Ruling R0 (history / benchmark / train, min) | **History job about 98 min = 54% of 180** (the Yahoo thread, first and steady; the other thread is 50.5 first and about 8 steady, since the OpenFIGI book is now cached (30.8 − 22.5)). **Benchmark about 210 min = 58% of 360**: 202.6 (the formula above without the 98.2 added build; copying the cached files takes seconds) + one incumbent row of about 7. **Train about 57 min = 32% of 180**, unchanged. All under 80%. Task 12 Step 5 replaces these with measured numbers. |

### Task 1: shared point-in-time helpers

**Files:**
- Create: `pipeline/src/advisor/model/groups.py`
- Modify: `pipeline/src/advisor/model/fundamentals.py` (extract `shares_outstanding`; `fundamental_features` uses it)
- Test: `pipeline/tests/unit/test_model_groups.py`, `pipeline/tests/unit/test_model_fundamentals.py`

**Interfaces — Produces:**
- `fundamentals.shares_outstanding(facts, tickers, days: pd.DatetimeIndex, symbols: Sequence[str], splits: pd.DataFrame) -> pd.DataFrame` — wide days × symbols: the latest first-reported `shares_outstanding` filed strictly before each day, stale after `STALE_DAYS`, times `_split_at(splits, symbol, shares_end)` (today's basis). `fundamental_features`' `mcap` becomes `price × shares_outstanding(...)` with identical values.
- `groups.sec_known(accepted_at: pd.Series, filing_date: pd.Series) -> pd.Series` (datetime64 days): the ET date of `accepted_at`, or else `sessions_after(Market.US, filing_date, 1)`.
- `groups.window_count(events: pd.DataFrame, days: pd.DatetimeIndex, symbols: Sequence[str], window_days: int, weight: str | None = None) -> pd.DataFrame` — for each day and symbol, the count of rows of `events` (`symbol`, `known`) with `D − window_days ≤ known < D`, or the sum of column `weight` over them. 0 where there are none.
- `groups.days_since(events: pd.DataFrame, days, symbols, cap: int) -> pd.DataFrame` — the days from the latest `known < D` to D, capped at `cap`. NaN where there is no such row.
- `groups.covered_symbols(facts: pd.DataFrame, tickers: pd.DataFrame) -> set[str]` — the symbols whose CIK has at least one fact.

- [ ] **Step 1: Write the failing tests.**

```python
def test_a_record_known_on_the_row_day_is_not_read():
    events = pd.DataFrame({"symbol": ["A", "A"], "known": pd.to_datetime(["2026-03-02", "2026-03-10"])})
    counts = window_count(events, pd.DatetimeIndex(["2026-03-10", "2026-03-11"]), ["A", "B"], 90)
    assert counts.loc["2026-03-10", "A"] == 1 and counts.loc["2026-03-11", "A"] == 2
    assert counts["B"].tolist() == [0, 0]


def test_the_window_drops_a_record_after_its_days():
    events = pd.DataFrame({"symbol": ["A"], "known": pd.to_datetime(["2026-01-01"])})
    counts = window_count(events, pd.DatetimeIndex(["2026-03-31", "2026-04-01", "2026-04-02"]), ["A"], 90)
    assert counts["A"].tolist() == [1, 1, 0]  # 2026-04-01 - 90 days = 2026-01-01, still inside


def test_days_since_caps_and_is_missing_before_the_first_record():
    events = pd.DataFrame({"symbol": ["A"], "known": pd.to_datetime(["2025-01-02"])})
    out = days_since(events, pd.DatetimeIndex(["2025-01-02", "2025-01-12", "2026-01-12"]), ["A"], 120)
    assert np.isnan(out["A"].iloc[0]) and out["A"].iloc[1] == 10 and out["A"].iloc[2] == 120


def test_an_sec_filing_without_an_acceptance_time_is_known_one_session_after_filing():
    known = sec_known(pd.Series([pd.NaT, pd.Timestamp("2026-07-02 21:30", tz="UTC")]),
                      pd.Series(pd.to_datetime(["2026-07-02", "2026-07-02"])))
    assert known.tolist() == [pd.Timestamp("2026-07-06"), pd.Timestamp("2026-07-02")]  # July 3 is a holiday
```

In `test_model_fundamentals.py`, add `test_shares_outstanding_is_on_todays_basis_after_a_split`: a 2-for-1 split between the shares fact's end and the day doubles the value. The existing `fundamental_features` tests must still pass unchanged.

- [ ] **Step 2: Run them and see them fail.** `bash pipeline/scripts/in-docker.sh uv run pytest tests/unit/test_model_groups.py tests/unit/test_model_fundamentals.py -q` — ImportError.
- [ ] **Step 3: Implement** the five functions. `window_count` and `days_since` use `merge_asof` or cumulative counts on the sorted `known`, not a Python loop over days.
- [ ] **Step 4: Run them, plus the fundamentals and earnings tests.** The same command plus `tests/unit/test_model_earnings.py` — all pass.
- [ ] **Step 5: Commit.** `feat: shared point-in-time helpers for the new data groups`

### Task 2: `short` — FINRA short interest and daily short volume

**Files:**
- Create: `pipeline/src/advisor/model/short.py`, `pipeline/src/advisor/training/finra_history.py`
- Modify:
  - `pipeline/src/advisor/collectors/finra_short_interest.py` (`parse_short_interest` reads its columns by name; `wanted=None` keeps every row)
  - `pipeline/src/advisor/collectors/finra_short_volume.py` (`parse_short_volume` with `wanted=None` keeps every row)
- Test: `pipeline/tests/unit/test_model_short.py`, `pipeline/tests/unit/test_training_finra_history.py`, `pipeline/tests/unit/test_finra_short_interest.py`, `pipeline/tests/unit/test_finra_short_volume.py`

**Interfaces:**
- Consumes: Task 1's `shares_outstanding` and `window_count`; `finra_short_interest.FINRA_SHORT_INTEREST_URL`; `finra_short_volume.FINRA_SHORT_VOLUME_URL` and `parse_short_volume`; `symbols.requested_by_key` and `symbol_key`.
- Produces:
  - History files:
    - `short_interest.parquet`: `symbol` string, `settlement` date, `short_interest` int64, `avg_daily_volume` float64, `days_to_cover` float64 (NaN for FINRA's `999.99` or for no volume).
    - `short_volume.parquet`: `symbol`, `day` date, `short_volume` float64, `total_volume` float64.
  - `parse_short_interest(text: str, wanted: Mapping[str, str] | None) -> list[ShortInterest]` and `parse_short_volume(text: str, wanted: Mapping[str, str] | None) -> list[ShortVolume]`. With `wanted=None`, every row is kept and `symbol` is FINRA's symbol as written (`BRK/B`).
  - `finra_history.PARTITIONS_URL = "https://api.finra.org/partitions/group/otcMarket/name/consolidatedShortInterest"` (Ruling R6; the `/data/group/.../partitions` path answers 404).
  - `finra_history.settlement_dates(client: httpx.Client) -> list[date]`, ascending, from `availablePartitions[].partitions[0]` of that URL.
  - `finra_history.FINRA_CACHE_AFTER_DAYS = 90`: a file dated more than 90 days before `today` never changes again and goes into the cache.
  - `finra_history.short_interest_history(client, dates, symbols, cache: HistoryCache | None, limiter, today: date) -> pd.DataFrame` and `finra_history.short_volume_history(client, days, symbols, cache, limiter, today: date) -> pd.DataFrame`:
    - Each file is parsed in full (`wanted=None`). A cacheable file is stored whole, keyed by FINRA symbol: `cache.put("finra_interest", "2017-12-29", frame)`, `cache.put("finra_volume", "2018-08-01", frame)`.
    - On read, fetched or cached, the rows are mapped to the universe with `requested_by_key(symbols)`, so a symbol that joins the universe later still finds its cached rows (Ruling R2, F13).
    - A day answering 403 or 404 is skipped.
  - `HistoryCache` is defined in Task 9. Until then the tests pass a dict-backed fake with the same `get(kind, key)` and `put(kind, key, frame)`.
  - `short.SHORT_FEATURES = ["short_pct_shares", "days_to_cover", "short_chg", "short_vol_ratio_20d"]`, with `SHORT_KNOWN_SESSIONS = 12`, `SHORT_STALE_DAYS = 45`, `VOLUME_SESSIONS = 20` and `VOLUME_MIN = 10`.
  - `short.short_features(interest: pd.DataFrame | None, volume: pd.DataFrame | None, shares: pd.DataFrame, splits: pd.DataFrame, days: pd.DatetimeIndex, symbols: Sequence[str]) -> dict[str, pd.DataFrame]`. When `interest` is None, its three columns are NaN; when `volume` is None, its column is.
- Rules:
  - `short_pct_shares` = the latest known short interest (today's basis) / `shares`.
  - `short_chg` = (that − the symbol's previous settlement, both on today's basis) / `shares`.
  - `days_to_cover` is FINRA's value.
  - All three are NaN when the latest settlement is more than `SHORT_STALE_DAYS` before the day.
  - `short_vol_ratio_20d` (Ruling R3, F7): take the last `VOLUME_SESSIONS` FINRA file days strictly before D (the distinct `day` values of the whole frame, not the symbol's own rows). Over the symbol's rows with `total_volume > 0` among those days, take the mean of `short_volume / total_volume`. It is NaN with fewer than `VOLUME_MIN` such rows. Live fetches enough file days to fill the same window (Task 11).

- [ ] **Step 1: Write the failing tests.**

```python
def test_short_interest_is_read_after_its_12th_session():
    interest = _interest("A", ["2026-05-29", "2026-06-15"], [1_000_000, 1_500_000])
    # known: 2026-05-29 -> 2026-06-16; 2026-06-15 -> 2026-07-02 (June 19 and July 3 are holidays)
    days = pd.DatetimeIndex(["2026-06-17", "2026-07-02", "2026-07-06"])
    out = short_features(interest, None, _shares(days, "A", 10_000_000), _no_splits(), days, ["A"])
    assert out["short_pct_shares"]["A"].tolist() == pytest.approx([0.10, 0.10, 0.15])
    assert out["short_chg"]["A"].iloc[2] == pytest.approx(0.05)


def test_a_split_between_two_reports_is_not_a_change():
    day = pd.DatetimeIndex(["2026-03-02"])  # after 2026-02-18 (the 2026-01-30 report's 12th session), within 45 days
    interest = _interest("A", ["2026-01-15", "2026-01-30"], [1_000_000, 2_000_000])
    splits = _split("A", "2026-01-20", 2.0)  # 2-for-1: the first report is 2,000,000 on today's basis
    out = short_features(interest, None, _shares(day, "A", 20_000_000), splits, day, ["A"])
    assert out["short_chg"]["A"].iloc[0] == pytest.approx(0.0)


def test_short_volume_ratio_needs_ten_of_twenty_sessions():
    nine = _volume("A", _sessions_before("2026-06-30", 9), short=40, total=100)
    ten = _volume("A", _sessions_before("2026-06-30", 10), short=40, total=100)
    assert np.isnan(_ratio_on(nine, "2026-06-30"))
    assert _ratio_on(ten, "2026-06-30") == pytest.approx(0.40)


def test_short_volume_ratio_reads_the_last_twenty_file_days_not_the_symbols_last_rows():
    sessions = _sessions_before("2026-06-30", 30)  # oldest first
    b = _volume("B", sessions, short=50, total=100)  # B makes all 30 sessions file days
    old = _volume("A", sessions[:10], short=90, total=100)
    twelve = pd.concat([b, old, _volume("A", sessions[-12:], short=30, total=100)])
    nine = pd.concat([b, old, _volume("A", sessions[-9:], short=30, total=100)])
    assert _ratio_on(twelve, "2026-06-30") == pytest.approx(0.30)  # A's ten older rows are outside the window
    assert np.isnan(_ratio_on(nine, "2026-06-30"))
```

The helpers `_interest`, `_shares`, `_split`, `_volume`, `_sessions_before` and `_ratio_on` are local to the test file (`_ratio_on` reads `short_vol_ratio_20d` of `A`). Also add:
- `test_a_symbol_finra_does_not_list_reads_missing`
- `test_a_report_older_than_45_days_reads_missing`
- In `test_finra_short_interest.py`:
  - `test_an_older_header_with_the_named_columns_still_parses`, using the 2017 header from the ledger (or extra and reordered columns). Keep `test_an_unexpected_header_is_rejected`, changed to a header missing `currentShortPositionQuantity`.
  - `test_parsing_without_a_wanted_list_keeps_every_finra_symbol`: the fixture parsed with `wanted=None` has a row whose `symbol == "BRK/B"`.
- In `test_finra_short_volume.py`: `test_parsing_without_a_wanted_list_keeps_every_finra_symbol`, the same for the short-volume fixture.
- In `test_training_finra_history.py`:
  - `test_the_history_maps_finra_symbols_to_the_universe` (`BRK/B` → `BRK.B`)
  - `test_an_unpublished_day_is_skipped` (a fake client answering 403)
  - `test_settlement_dates_read_the_partitions_api`: a fake client answering `PARTITIONS_URL` with `{"availablePartitions": [{"partitions": ["2026-10-30"]}, {"partitions": ["2017-12-29"]}]}` gives `[date(2017, 12, 29), date(2026, 10, 30)]` (the fixture copies the live answer's date format).
  - `test_a_cached_file_holds_every_finra_symbol_and_maps_on_read`: with `today = date(2026, 11, 19)`, the 2017-12-29 file read once for `["AAPL"]` puts every FINRA symbol into the fake cache; a second read for `["AAPL", "BRK.B"]` makes no request and returns BRK.B's row. A file dated within 90 days of `today` is not put.

- [ ] **Step 2: Run them and see them fail.** `bash pipeline/scripts/in-docker.sh uv run pytest tests/unit/test_model_short.py tests/unit/test_training_finra_history.py tests/unit/test_finra_short_interest.py tests/unit/test_finra_short_volume.py -q`
- [ ] **Step 3: Implement** three things:
  - `parse_short_interest`, reading columns by name. The required columns are `symbolCode`, `currentShortPositionQuantity`, `previousShortPositionQuantity`, `averageDailyVolumeQuantity`, `daysToCoverQuantity` and `settlementDate`. Both parse functions accept `wanted=None`.
  - The two history functions. They fetch through `get_with_retries` with the FINRA limiter and call `check_deadline()` once per file.
  - `short_features`.
- [ ] **Step 4: Run them; all pass.**
- [ ] **Step 5: Commit.** `feat: short interest and short volume history and features`

### Task 3: `analyst` — Yahoo rating changes

**Files:**
- Create: `pipeline/src/advisor/model/analyst.py`, `pipeline/src/advisor/training/yahoo_history.py`
- Test: `pipeline/tests/unit/test_model_analyst.py`, `pipeline/tests/unit/test_training_yahoo_history.py`

**Interfaces:**
- Consumes:
  - The third frame of `yfinance_analyst.read_ticker`: columns `Action` and `priceTargetAction`, indexed by grade time in naive UTC.
  - `yahoo.rate_limited`, `yahoo.SilentFailure` and `YAHOO_PER_MINUTE`. Not `collect_yahoo`: its empty-share and empty-streak rules were tuned for the shortlist and would stop a whole-universe history (Ruling R5, F12).
  - Task 1's `window_count` and `days_since`.
- Produces:
  - `analyst_events.parquet`: `symbol`, `graded_at` (datetime64[ns], naive UTC), `firm`, `action`, `from_grade`, `to_grade`, `price_target_action`.
  - `yahoo_history.YAHOO_CANARIES = ("AAPL", "MSFT")`.
  - `yahoo_history.analyst_history(symbols: Sequence[str], load: Callable[[str], pd.DataFrame], limiter: RateLimiter | None) -> tuple[pd.DataFrame, int]` — the events and the count of symbols Yahoo had nothing for. One call and one limiter token per symbol. A symbol Yahoo has nothing for adds no rows. It stops (re-raises) only on an error `yahoo.rate_limited` recognises. It raises `SilentFailure` when a canary among `symbols` returns no rows. Task 9 records the count in `manifest["empty"]["analyst"]`.
  - `analyst.ANALYST_FEATURES = ["net_upgrades_30d", "net_upgrades_90d", "net_target_raises_90d", "days_since_downgrade"]`, with `ANALYST_CAP_ROWS = 1000` (Task 0 ledger: no exact cap seen) and `DOWNGRADE_CAP = 365`.
  - `analyst.coverage_from(oldest: pd.Series, rows: pd.Series) -> pd.DataFrame` (Ruling R3, F19): both Series are indexed by symbol; `oldest` is the naive-UTC grade time of the symbol's oldest event. It returns the columns `symbol`, `oldest` (that time's ET date, the known day) and `rows`. This is the only place the ET conversion of coverage happens: `coverage` below and Task 11's `history_from_records` both call it.
  - `analyst.coverage(events: pd.DataFrame) -> pd.DataFrame` — `coverage_from` over each symbol's oldest `graded_at` and row count.
  - `analyst.analyst_features(events: pd.DataFrame | None, coverage: pd.DataFrame | None, days, symbols) -> dict[str, pd.DataFrame]`.
- Rules:
  - `known` is the ET date of `graded_at`.
  - Net upgrades = the count of `action == "up"` minus the count of `"down"`. Net target raises = the count of `"Raises"` minus the count of `"Lowers"`.
  - All four features are NaN on days up to and including the symbol's `oldest`.
  - For a capped symbol (`rows >= ANALYST_CAP_ROWS`), the three counts stay NaN on days D ≤ `oldest + 90 days`, and `days_since_downgrade` stays NaN on days D ≤ `oldest + DOWNGRADE_CAP days`, because a downgrade before the truncated `oldest` would be invisible (Ruling R3, F11).
  - `days_since_downgrade` = the days since the latest known `"down"`, capped at `DOWNGRADE_CAP`. It is NaN when there has been none yet.

- [ ] **Step 1: Write the failing tests.**
  - `test_counts_are_missing_before_the_first_recorded_event`
  - `test_net_upgrades_over_30_and_90_days`: events up at D−10, up at D−40 and down at D−50 give 30d = 1 and 90d = 1.
  - `test_target_raises_minus_cuts`
  - `test_an_event_graded_on_the_row_day_is_not_read`
  - `test_a_capped_symbol_reads_missing_until_its_window_is_covered`: with rows = `ANALYST_CAP_ROWS`, oldest 2020-01-02 and a `"down"` graded 2020-06-01, the counts are NaN on 2020-03-31 and numbers on 2020-04-02; `days_since_downgrade` is NaN on 2020-12-31 and 217 on 2021-01-04 (2020-01-02 + 365 days = 2021-01-01).
  - `test_days_since_downgrade_caps_at_365`
  - `test_coverage_from_takes_the_et_date_of_the_oldest_grade`: oldest `2020-01-02 03:00` (naive UTC) with 7 rows gives `oldest == 2020-01-01` and `rows == 7`.
  - `test_the_history_keeps_one_row_per_event_and_symbol`: a fake loader with two symbols.
  - `test_the_history_stops_only_on_a_rate_limit`: a loader with no rows for 60 of 100 symbols (past `collect_yahoo`'s 0.5 share and 25 streak) returns the other 40 symbols' rows and an empty count of 60; a loader raising a rate-limit error re-raises it; a loader with no rows for `AAPL` raises `SilentFailure`.
- [ ] **Step 2: Run them and see them fail.** `bash pipeline/scripts/in-docker.sh uv run pytest tests/unit/test_model_analyst.py tests/unit/test_training_yahoo_history.py -q`
- [ ] **Step 3: Implement.** The history loader reads only `Ticker.upgrades_downgrades` (one request), with `_quietly` for symbols Yahoo lacks.
- [ ] **Step 4: Run them; all pass.**
- [ ] **Step 5: Commit.** `feat: analyst rating history and features`

### Task 4: `events` — 8-K items and Schedule 13D/13G from `submissions.zip`

**Files:**
- Create: `pipeline/src/advisor/model/events.py`, `pipeline/src/advisor/training/sec_history.py`
- Modify: `pipeline/src/advisor/collectors/sec.py` (one URL constant)
- Test: `pipeline/tests/unit/test_model_events.py`, `pipeline/tests/unit/test_training_sec_history.py`

**Interfaces:**
- Consumes:
  - `sec.parse_filings`, for each filing's `form`, `items`, `file_number`, `accepted_at` and `filing_date`. It reads `payload["filings"]["recent"]` (`collectors/sec.py:86`).
  - `sec_events.EVENT_FORMS`, `sec_holders.HOLDER_FORMS` and `sec_holders.SUBJECT_FILE_NUMBER`.
  - Task 1's `sec_known`, `window_count`, `days_since` and `covered_symbols`.
- Produces:
  - `sec.SUBMISSIONS_ZIP_URL = "https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip"`.
  - `sec_history.SUBMISSION_FORMS = EVENT_FORMS | HOLDER_FORMS | {"4", "4/A"}` (Ruling R2, F14: bank 424B2 filings must not fill memory).
  - `sec_history.reduce_submissions(zip_path: Path, ciks: Iterable[int], since: date, page: Callable[[str], Mapping] | None = None, forms: frozenset[str] | None = None) -> pd.DataFrame`. It returns `cik, accession, form, filing_date, accepted_at (datetime64[ns, UTC]), items (list[str]), file_number` for filings on or after `since`, and only the forms in `forms` when it is given. It reads each company's `filings.recent` plus each `filings.files` page. The ledger says the pages are inside the zip, so `page` (one SEC request each) is only a fallback for a page the zip lacks. Task 9 calls it once per history run, with `forms=SUBMISSION_FORMS`, and passes the frame to both `events` and `insider` (Task 5).
  - `sec_history.material_events(filings, tickers) -> pd.DataFrame`, written as `material_events.parquet`: `symbol, accession, form, filing_date, accepted_at, items`. Forms in `EVENT_FORMS` only.
  - `sec_history.large_holder_filings(filings, tickers) -> pd.DataFrame`, written as `large_holders.parquet`: `symbol, accession, form, filing_date, accepted_at, activist`. Forms in `HOLDER_FORMS` whose `file_number` starts with `"005-"`; `activist` is true when the form contains "13D". No document is opened and no issuer is checked; live counts the same filing-list rows (Ruling R4, Task 11).
  - `events.EVENT_ITEMS = ("5.02", "1.01", "2.01", "4.02", "3.01")`.
  - `events.EVENTS_FEATURES = ["ev_502_90d", "ev_101_90d", "ev_201_90d", "ev_402_90d", "ev_301_90d", "days_since_8k", "activist_13d_180d", "passive_13g_90d"]`, with `DAYS_SINCE_8K_CAP = 120` (the live `sec_events.LOOKBACK`).
  - `events.events_features(filings_8k: pd.DataFrame | None, holders_13dg: pd.DataFrame | None, covered: set[str], days, symbols) -> dict[str, pd.DataFrame]`.
- Rules:
  - An item count counts the filings whose `items` include that code.
  - `activist_13d_180d` and `passive_13g_90d` are 1/0 indicators.
  - Every feature is NaN for a symbol not in `covered`.
  - `days_since_8k` reads `DAYS_SINCE_8K_CAP` for a covered symbol with no 8-K in that span (`fillna` after `days_since`), so live (which sees 120 days) agrees.

- [ ] **Step 1: Write the failing tests.**
  - `test_item_counts_over_90_days_by_acceptance`: an 8-K with items `["5.02", "9.01"]` accepted 2026-03-02 21:00 UTC is counted from 2026-03-03, not on 2026-03-02.
  - `test_an_8k_without_acceptance_time_waits_one_session_after_filing`
  - `test_days_since_8k_is_120_for_a_covered_symbol_without_one`, which also asserts NaN for an uncovered symbol.
  - `test_13d_and_13g_indicators_use_their_own_windows`: a 13D at D−170 gives 1; a 13G at D−100 gives 0.
  - `test_new_and_legacy_schedule_names_both_count`: `"SCHEDULE 13D/A"` and `"SC 13D"`.
  - `test_a_13dg_without_the_subject_file_number_is_ignored`: `file_number=""`.
  - `test_reduce_reads_recent_and_overflow_pages`: a tiny zip built in the test, one company with `recent` and one `files` page inside the zip; `page` is never called.
  - `test_filings_before_since_are_dropped`
  - `test_reduce_keeps_only_the_wanted_forms`: with `forms=SUBMISSION_FORMS`, a `424B2` in the same company's list is dropped and its 8-K and Form 4 are kept.
- [ ] **Step 2: Run them and see them fail.** `bash pipeline/scripts/in-docker.sh uv run pytest tests/unit/test_model_events.py tests/unit/test_training_sec_history.py -q`
- [ ] **Step 3: Implement.** Pass each company JSON to `sec.parse_filings` as it is, and wrap each `files` page as `{"filings": {"recent": page}}` first, since pages carry the same parallel arrays at the top level. `parse_filings` does not change (Ruling R2, F22). Call `check_deadline()` every 200 companies, as `reduce_companyfacts` does.
- [ ] **Step 4: Run them; all pass.**
- [ ] **Step 5: Commit.** `feat: 8-K and Schedule 13D/G history and features`

### Task 5: `insider` — Form 4 open-market trades from SEC's quarterly data sets

**Files:**
- Create: `pipeline/src/advisor/model/insider.py`
- Modify: `pipeline/src/advisor/training/sec_history.py`
- Test: `pipeline/tests/unit/test_model_insider.py`, `pipeline/tests/unit/test_training_sec_history.py`

**Interfaces:**
- Consumes: the `filings` frame of Task 4's `reduce_submissions(..., forms=SUBMISSION_FORMS)` (acceptance times by accession). Task 9 reduces once and hands the same frame to `events` and `insider` (Ruling R2, F14). Task 1's helpers and `shares_outstanding` (for the market value below).
- Produces:
  - `sec_history.INSIDER_LISTING_URL = "https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets"`.
  - `sec_history.insider_data_sets(html: str) -> list[tuple[str, str]]` — a quarter such as `"2018q1"` and its absolute URL. The links are read from the page with the ledger's regex, never built.
  - `sec_history.reduce_insider_set(zip_path: Path) -> pd.DataFrame` — one row per non-derivative transaction of a Form `4` or `4/A`, with `code` in `{"P", "S"}` only. Columns: `accession, issuer_cik, filed_ticker, filing_date, trade_date, code, shares, price, owners (list[str]), officer, director, ten_percent_owner`.
    - `FILING_DATE` is `DD-MON-YYYY`; parse it with `sec_13f.sec_date`.
    - Owners and roles come from REPORTINGOWNER: `RPTOWNERNAME`, and `RPTOWNER_RELATIONSHIP` containing "Officer", "Director" or "TenPercentOwner".
    - `filed_ticker` is SUBMISSION's `ISSUERTRADINGSYMBOL`.
    - No "common stock" filter on `SECURITY_TITLE`: live Form 4 records do not carry the title (`collectors/sec_insiders.py:84-102`), so neither side filters, and Task 14 records the deviation from the spec (Ruling R3, F21).
  - `sec_history.insider_history(sets: Sequence[pd.DataFrame], filings: pd.DataFrame, tickers) -> pd.DataFrame`, written as `insider_trades.parquet`: `symbol, accession, filing_date, accepted_at, trade_date, code, shares, price, owners, officer, director, ten_percent_owner, filed_ticker` (Ruling R3, F21: the roles and the ticker as filed are kept). The symbol comes from `issuer_cik` through `tickers`. `accepted_at` is joined by accession and is NaT when missing.
  - `insider.INSIDER_FEATURES = ["insider_net_buy_90d", "insider_buyers_90d", "officer_buy_180d"]`.
  - `insider.insider_features(trades: pd.DataFrame | None, market_value: pd.DataFrame, covered: set[str], days, symbols) -> dict[str, pd.DataFrame]`, where `market_value` is the split-adjusted close × `shares_outstanding` (wide).
- Rules:
  - Dollars = shares × price. A row without a price adds 0 dollars but still counts as a buyer.
  - Net buy = (P dollars − S dollars) over 90 days / market value.
  - Buyers = the distinct owner names in P trades over 90 days (its own code: `window_count` counts rows, not names).
  - `officer_buy_180d` = 1 if any P trade with `officer` falls in the last 180 days.
  - Covered symbols without trades read 0s; uncovered ones read NaN.
  - 10b5-1 plan trades are not separated (the spec: SEC flags them only from 2023).

- [ ] **Step 1: Write the failing tests.**

```python
def test_net_buying_is_a_share_of_market_value():
    trades = _trades([("A", "P", 10_000, 50.0, D - 10), ("A", "S", 2_000, 50.0, D - 20)])  # (.., known day)
    out = insider_features(trades, _value(D, ["A"], 1e9), {"A"}, pd.DatetimeIndex([D]), ["A"])
    assert out["insider_net_buy_90d"].loc[D, "A"] == pytest.approx(400_000 / 1e9)


def test_a_covered_symbol_without_trades_reads_zero_and_an_uncovered_one_missing():
    out = insider_features(_trades([]), _value(D, ["A", "B"], 1e9), {"A"}, pd.DatetimeIndex([D]), ["A", "B"])
    assert out["insider_buyers_90d"].loc[D, "A"] == 0 and np.isnan(out["insider_buyers_90d"].loc[D, "B"])
```

Also add:
- `test_distinct_buyers_count_each_owner_once`: one owner buying twice plus a joint filing by two other owners gives 3.
- `test_an_officer_buy_counts_for_180_days`
- `test_a_trade_accepted_on_the_row_day_is_not_read`
- `test_reduce_keeps_only_open_market_trades_of_form_4`: a fixture zip with a Form 3 row, an `A` award and a `P` purchase gives 1 row, whose `filed_ticker`, `director` and `ten_percent_owner` come from the fixture.
- `test_history_joins_acceptance_by_accession_and_maps_the_issuer_cik`: the output columns are exactly the `insider_trades.parquet` list above.

- [ ] **Step 2: Run them and see them fail.** `bash pipeline/scripts/in-docker.sh uv run pytest tests/unit/test_model_insider.py tests/unit/test_training_sec_history.py -q`
- [ ] **Step 3: Implement.** Read the tab-separated files by column name, as `sec_13f._rows` does.
- [ ] **Step 4: Run them; all pass.**
- [ ] **Step 5: Commit.** `feat: insider trade history and features`

### Task 6: `holders` — 13F quarter-on-quarter changes

**Files:**
- Create: `pipeline/src/advisor/model/holders.py`, `pipeline/src/advisor/training/holders_history.py`
- Modify: `pipeline/src/advisor/collectors/sec_13f.py`. `parse_listing` also matches the ledger's quarterly file-name pattern, and `aggregate` tolerates a missing `FIGI` or `AMENDMENTTYPE` column.
- Modify: this plan's Task 0 ledger (the CUSIP coverage, Step 5)
- Test: `pipeline/tests/unit/test_model_holders.py`, `pipeline/tests/unit/test_training_holders_history.py`, `pipeline/tests/unit/test_sec_13f.py`

**Interfaces:**
- Consumes: `sec_13f.parse_listing`, `aggregate`, `save_quarter`, `load_quarter`, `Quarter.period`, `Quarter.figis` and `Quarter.cusip_for`; `openfigi.FigiBook.lookup`.
- Produces:
  - `parse_listing` gives a quarterly name such as `2018q4_form13f.zip` the `DataSet` name `"2018q4"` and `end` = the calendar quarter's last day (`date(2018, 12, 31)`; ledger). `DataSet` gains no other field: SEC's listing shows no publication date (ledger, Ruling R6).
  - `holders.quarter_known(period: date, window_end: date) -> date` = the later of `period + 45 days` and `window_end + 30 days` (Ruling R6). Training and live both use it (Task 11; Ruling R3, F5).
  - `holders_history.cusip_map(quarters: Sequence[tuple[DataSet, Quarter]], figis: Mapping[str, Sequence[str]]) -> dict[str, str]` — symbol → CUSIP through `Quarter.cusip_for`, from the newest data set whose `Quarter.figis` is not empty (Ruling R6: every set before 2023q1 has an empty FIGI column). It is found once and used for every quarter.
  - `holders_history.holders_history(quarters: Sequence[tuple[DataSet, Quarter]], cusips: Mapping[str, str]) -> pd.DataFrame`, written as `holders.parquet`: `symbol, cusip, period, known, shares, holders`, with `known = quarter_known(quarter.period, data_set.end)`.
  - `holders.HOLDERS_FEATURES = ["holder_count_chg", "inst_shares_chg"]`.
  - `holders.holders_features(quarters: pd.DataFrame | None, shares: pd.DataFrame, splits, days, symbols) -> dict[str, pd.DataFrame]`.
- Rules:
  - On day D, take the symbol's latest quarter known before D, and the quarter whose period ends 80–100 days earlier (also known before D).
  - `holder_count_chg` = holders − previous holders.
  - `inst_shares_chg` = (shares × `_split_at(period)` − previous shares × `_split_at(previous period)`) / `shares`.
  - Both are NaN without the pair.

- [ ] **Step 1: Write the failing tests.**
  - `test_a_quarter_is_known_at_the_later_of_45_days_after_its_end_and_30_days_after_its_window`: `quarter_known(date(2025, 3, 31), date(2025, 5, 31)) == date(2025, 6, 30)` and `quarter_known(date(2018, 9, 30), date(2018, 12, 31)) == date(2019, 1, 30)`; in `holders_features`, a quarter with `known = 2025-06-30` is not read on 2025-06-30 and is read on 2025-07-01.
  - `test_changes_need_the_previous_quarter`
  - `test_a_split_between_quarters_is_not_a_change_in_shares`
  - `test_a_symbol_without_a_cusip_reads_missing`
  - `test_the_cusip_map_comes_from_the_newest_data_set_with_figis`: a newer set with empty `figis` and an older set whose `figis` map AAPL's FIGI to its CUSIP give `{"AAPL": <that CUSIP>}`.
  - In `test_sec_13f.py`:
    - `test_the_listing_reads_quarterly_file_names_too`: update `test_the_listing_gives_the_data_sets_newest_window_first`, whose comment says the 2023q4 file is skipped; the fixture listing now gives four data sets, the fourth `DataSet("2023q4", <its URL on the page>, date(2023, 12, 31))`.
    - `test_a_data_set_without_figis_still_totals_its_holdings`.
- [ ] **Step 2: Run them and see them fail.** `bash pipeline/scripts/in-docker.sh uv run pytest tests/unit/test_model_holders.py tests/unit/test_training_holders_history.py tests/unit/test_sec_13f.py -q`
- [ ] **Step 3: Implement.** The build reuses `Sec13f._quarter`'s download, reduce and save path, with the folder set to Task 9's `HistoryCache.sec13f_folder` (`root/sec_13f/`), and the `FigiBook` at `HistoryCache.figi_path` (`root/openfigi.json`), so both survive between history runs (Ruling R2, F3). The build never calls `Sec13f.fetch`: its `_prune` deletes every totals file except the newest (`collectors/sec_13f.py:330-335`).
- [ ] **Step 4: Run them; all pass.**
- [ ] **Step 5: Measure the CUSIP coverage (Ruling R6).** Load the agent with `export SEC_USER_AGENT="$(sed -n 's/^SEC_USER_AGENT=//p' pipeline/.env.local)"` (never echo it). In a one-off `bash pipeline/scripts/in-docker.sh uv run python -I -c ...` (nothing committed), download the newest data set with FIGIs (`01jun2026-31aug2026`, 96 MB) into a new, empty `pipeline/.cache/probe-7b-13f/`, reduce it, look up every 11th symbol of the newest local `tickers.parquet` (about 510 symbols, about 2 minutes of OpenFIGI) and count the symbols `cusip_map` maps to a CUSIP with holdings. Write the share into the ledger's 13F row. It is a measurement, not a stop rule; Task 14 records it.
- [ ] **Step 6: Commit.** `feat: 13F holder history and features` (the code and the ledger line).

### Task 7: `estimates` — Yahoo earnings dates, consensus and reported EPS

**Files:**
- Create: `pipeline/src/advisor/model/estimates.py`
- Modify: `pipeline/src/advisor/training/yahoo_history.py`
- Test: `pipeline/tests/unit/test_model_estimates.py`, `pipeline/tests/unit/test_training_yahoo_history.py`

**Interfaces:**
- Consumes: `yfinance_earnings.parse_earnings` (one report per ET day; the reported row wins); Task 3's `YAHOO_CANARIES` and stop rule (`yahoo.rate_limited`, `SilentFailure`; not `collect_yahoo`, Ruling R5, F12).
- Produces:
  - `yahoo_history.estimates_history(symbols, load: Callable[[str], pd.DataFrame | None], limiter) -> tuple[pd.DataFrame, int]` — the reports and the count of symbols Yahoo had nothing for, under the same stop rule as `analyst_history` (only a rate limit stops it; a canary without rows raises `SilentFailure`). The loader calls `get_earnings_dates(limit=100)`. Written as `earnings_estimates.parquet`: `symbol, report_day (ET date), timing, eps_estimate, eps_actual`. Task 9 records the count in `manifest["empty"]["estimates"]`.
  - `estimates.report_timing(report_at: pd.Series) -> pd.Series` (ET timestamps in, strings out): `"before-open"` before 09:30, `"after-close"` at or after 16:00, and None at exactly 00:00 (no time given) or in between. The spec's before-open or after-close column (Ruling R3, F21); no feature reads it yet. Task 11 calls the same function live.
  - `estimates.ESTIMATES_FEATURES = ["eps_surprise_last", "eps_beat_streak", "days_to_next_report"]`, with `SURPRISE_CLIP = 1.0`, `STREAK_REPORTS = 4`, `NEXT_REPORT_DAYS = 364` and `ESTIMATE_STALE_DAYS = 200`.
  - `estimates.estimates_features(reports: pd.DataFrame | None, days, symbols) -> dict[str, pd.DataFrame]`.
- Rules (only reports with `report_day < D` are read):
  - `eps_surprise_last` = (actual − estimate) / |estimate| for the latest report with both numbers, clipped to ±`SURPRISE_CLIP`. It is NaN when the estimate is 0 or that report is more than `ESTIMATE_STALE_DAYS` old.
  - `eps_beat_streak` = how many of the last 4 such reports had actual > estimate. It is NaN with fewer than 4.
  - `days_to_next_report` = the minimum, over past reports r with `r + 364 days ≥ D`, of `(r + 364 days − D).days`. It is NaN when there is none. The actual date of a future report is never read.

- [ ] **Step 1: Write the failing tests.**
  - `test_a_report_is_read_from_the_session_after_it`
  - `test_surprise_is_against_the_absolute_consensus_and_clipped`: estimate −0.50 with actual −0.40 gives +0.20; estimate 0.10 with actual 0.50 gives 1.0.
  - `test_the_streak_needs_four_reports`
  - `test_next_report_is_last_years_same_quarter_plus_364_days`: reports on 2025-01-29, 2025-04-30, 2025-07-30 and 2025-10-29 with D = 2025-11-19 give 2026-01-28 − D = 70.
  - `test_a_scheduled_future_report_is_never_read`: a row for 2025-12-01 with no actual changes no feature on 2025-11-19.
  - `test_report_timing_reads_before_open_after_close_and_unknown`: ET 07:00 → `"before-open"`, 16:05 → `"after-close"`, 00:00 → None, 12:00 → None.
  - `test_the_history_keeps_reported_and_scheduled_rows`: a fake loader; the frame has the `timing` column.
  - `test_the_estimates_history_stops_only_on_a_rate_limit`: as Task 3's test, for `estimates_history`.
- [ ] **Step 2: Run them and see them fail.** `bash pipeline/scripts/in-docker.sh uv run pytest tests/unit/test_model_estimates.py tests/unit/test_training_yahoo_history.py -q`
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them; all pass.**
- [ ] **Step 5: Commit.** `feat: earnings estimate history and features`

### Task 8: `catalysts` — openFDA approvals and recalls (last priority)

**Files:**
- Create: `pipeline/src/advisor/model/catalysts.py`, `pipeline/src/advisor/training/fda_history.py`
- Modify: `pipeline/src/advisor/collectors/openfda.py` (three constants only; `WINDOW_DAYS` changes in Task 11)
- Test: `pipeline/tests/unit/test_model_catalysts.py`, `pipeline/tests/unit/test_training_fda_history.py`

**Interfaces:**
- Consumes: `openfda.approvals` (the counted kinds), `openfda.fda_date`, `APPROVALS_URL`, `RECALLS_URL` and `OPENFDA_PER_MINUTE`; `sponsors.SponsorMatcher`.
- Produces:
  - `openfda.FDA_LAG_DAYS = 7`, `openfda.APPROVAL_WINDOW_DAYS = 180` and `openfda.RECALL_WINDOW_DAYS = 90`. They live in the collector so that Task 11's `WINDOW_DAYS = APPROVAL_WINDOW_DAYS + FDA_LAG_DAYS` reads them without a model import; `catalysts` imports them, never retypes them (Ruling R3, F4).
  - `fda_history.fda_history(client, names: Mapping[str, str], since: date, limiter) -> pd.DataFrame`, written as `fda_events.parquet`: `symbol, kind ("approval" | "recall"), day, event_id`.
    - Source: the bulk files listed in `https://api.fda.gov/download.json` (the ledger confirms both: `drug/enforcement` and `drug/drugsfda`, one partition each).
    - Approvals: the `original` and `new_indication` kinds only (`new_molecule` is a subset of `original`).
    - Recalls: one row per distinct `event_id`.
    - Names are the directory names of the whole US universe (`SponsorMatcher(names)`).
  - `catalysts.CATALYSTS_FEATURES = ["fda_approvals_180d", "fda_recalls_90d"]`, counted over `APPROVAL_WINDOW_DAYS` and `RECALL_WINDOW_DAYS`.
  - `catalysts.catalysts_features(events: pd.DataFrame | None, days, symbols) -> dict[str, pd.DataFrame]`. `known = day + FDA_LAG_DAYS`. Symbols without events read 0 when `events` is not None.

- [ ] **Step 1: Write the failing tests.**
  - `test_an_approval_counts_a_week_after_its_date_for_180_days`
  - `test_one_recall_event_listing_three_products_counts_once`
  - `test_every_symbol_reads_zero_without_events_and_missing_without_the_source`
  - `test_the_history_matches_sponsor_names_against_the_whole_universe` (Ruling R5, F18, following `sponsors.py:116-121`): two different companies whose name keys both extend the sponsor name give no match; two share classes with the same exact key (one company) both get the event.
- [ ] **Step 2: Run them and see them fail.** `bash pipeline/scripts/in-docker.sh uv run pytest tests/unit/test_model_catalysts.py tests/unit/test_training_fda_history.py -q`
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them; all pass.**
- [ ] **Step 5: Commit.** `feat: openFDA catalyst history and features`

### Task 9: a weekly workflow builds the group histories into a cache; the benchmark and train builds read it

Ruling R0: group history is downloaded only by a new weekly `history.yml`, into an actions cache. `benchmark.yml` and `train.yml` restore that cache and never download group history, so neither job pays the 98-minute Yahoo download (Task 0 ledger).

**Files:**
- Create: `pipeline/src/advisor/training/history.py`, `.github/workflows/history.yml`
- Modify: `pipeline/src/advisor/model/groups.py` (`GROUP_FILES`), `pipeline/src/advisor/training/build.py`, `.github/workflows/benchmark.yml`, `.github/workflows/train.yml`
- Test: `pipeline/tests/unit/test_training_history.py`, `pipeline/tests/unit/test_training_build.py`, `pipeline/tests/unit/test_benchmark_workflow.py`

**Interfaces:**
- Consumes: every history function from Tasks 2–8:
  - `finra_history.settlement_dates`, `short_interest_history`, `short_volume_history` (with `cache` and `today`)
  - `yahoo_history.analyst_history`, `estimates_history`, each returning `(frame, empty_count)`
  - `sec_history.reduce_submissions` with `SUBMISSION_FORMS`, `material_events`, `large_holder_filings`, `insider_data_sets`, `reduce_insider_set`, `insider_history`
  - `holders_history.cusip_map`, `holders_history.holders_history` and `Sec13f._quarter`
  - `fda_history.fda_history`
- Produces:
  - `groups.GROUP_FILES: dict[str, tuple[str, ...]]` in `pipeline/src/advisor/model/groups.py`, so that the training layer imports the model layer and never the reverse (Ruling R5, F15). Each group's Parquet files:
    - `short`: `short_interest.parquet`, `short_volume.parquet`
    - `analyst`: `analyst_events.parquet`
    - `events`: `material_events.parquet`, `large_holders.parquet`
    - `insider`: `insider_trades.parquet`
    - `holders`: `holders.parquet`
    - `estimates`: `earnings_estimates.parquet`
    - `catalysts`: `fda_events.parquet`
    - `earnings` needs only `fundamentals.parquet` and is not a key.
  - `history.HistoryCache(root: Path)`:
    - `get(kind: str, key: str) -> pd.DataFrame | None` and `put(kind, key, frame) -> None` (zstd Parquet under `root/kind/key.parquet`), for pieces that never change: FINRA files older than 90 days (the full parse keyed by FINRA symbol, Task 2) and past insider quarters (`reduce_insider_set` output, kind `insider`, key `2018q1`).
    - `figi_path = root / "openfigi.json"` (the `FigiBook` file) and `sec13f_folder = root / "sec_13f"` (the `Sec13f` totals, `*.json.gz`). The class docstring says these two live outside `get`/`put` (Ruling R2, F3).
    - `groups_dir = root / "groups"`: each group's newest Parquet files plus `written.json`, `{group: ISO UTC time its files were written}`.
    - `submissions.zip`, Yahoo and openFDA are fetched on every history run.
  - `history.MAX_HISTORY_AGE_DAYS = 21`.
  - `history.wanted_groups(choice: str) -> frozenset[str]`: `"all"` → every key of `GROUP_FILES`; `"none"` → empty; a comma list → those groups; an unknown name raises `ValueError`. (`accepted` arrives in Task 10, Ruling R5, F15.)
  - `history.build_history(cache: HistoryCache, groups: frozenset[str], deps: HistoryDeps, tickers: pd.DataFrame, symbols: list[str], names: Mapping[str, str], since: date, now: datetime, manifest: dict) -> None`:
    - It writes each wanted group's files into `cache.groups_dir` (each file under a temporary name, then renamed), then sets the group's time in `written.json`. It records `manifest["seconds"][f"history_{group}"]` for each group and `manifest["empty"][group]` for `analyst` and `estimates`.
    - A failing group goes into `manifest.setdefault("unavailable", {})[group]`, merged with macro's entry and never assigned over it (`training/build.py:126` assigns). Its previous files and time stay, and the other groups go on, as the build does for macro.
    - Groups run in two threads: Yahoo (`analyst`, `estimates`) and everything else, in the spec's priority order with `catalysts` last.
    - When `events` or `insider` is wanted, the non-Yahoo thread first downloads `submissions.zip` (`SecEdgar.download`) and runs `reduce_submissions(..., forms=SUBMISSION_FORMS)` once; both groups read that frame, and the zip is deleted after. A failure there marks both wanted groups unavailable with the same message (Ruling R2, F14).
    - It takes no facts: the covered set is applied at feature time (`covered_symbols`), so a history run needs no `companyfacts.zip`.
  - `history.copy_history(cache: HistoryCache, out: Path, groups: frozenset[str], now: datetime, manifest: dict) -> frozenset[str]`: for each wanted group whose `written.json` time is at most `MAX_HISTORY_AGE_DAYS` days before `now` and whose files all exist, it copies the files into `out` and records `manifest["history_age_days"][group]`. A group with no time or a missing file gets `manifest.setdefault("unavailable", {})[group] = "no cached history"`; an older one gets `f"cached history is {days} days old"`. Neither is copied, so `load_market` leaves the group out of `MarketData.groups` and its rows fail closed (Task 10's `missing_groups`; Task 12's "no data"). It returns the copied groups.
  - A `HistoryDeps` dataclass: the FINRA, Yahoo, openFDA and OpenFIGI clients, `SecEdgar`, the limiters, the Yahoo loaders, the `FigiBook` (at `cache.figi_path`), and `cache: HistoryCache`.
  - `build.HistoryPlan`, a frozen dataclass: `groups: frozenset[str]`, `cache: Path`, `only: bool = False`, `download: bool = True`.
  - `build(out, now, deps, limit=None, history: HistoryPlan | None = None)` and `BuildDeps.history: HistoryDeps | None = None`. `history=None` means no history step, so today's tests keep passing.
    - `only=True`: the universe step and `tickers.parquet` (one SEC request), then `build_history`. It writes only `manifest.json` and `tickers.parquet` into `out`: no sectors, macro, prices, fundamentals or crypto.
    - `only=False, download=True` (a local build): the full build, then `build_history`, then `copy_history`.
    - `download=False`: the full build, then `copy_history` only. It calls no history function and needs no `HistoryDeps`.
    - Every mode with groups also writes `manifest["history_groups"]` (the wanted groups, sorted).
  - CLI options (`build.parse_args`):
    - `--groups CHOICE`, default `all`, parsed by `wanted_groups`.
    - `--history-cache DIR`: the cache root. Without it, the root is `<out>/history-cache`.
    - `--history-only`: `HistoryPlan(only=True)`. Used by `history.yml`.
    - `--no-history-download`: `HistoryPlan(download=False)`. Used by `benchmark.yml` and `train.yml`.
    - The two options exclude each other (an argparse mutually exclusive group), and each needs `--history-cache` (`parser.error`).
    - History starts at `history_start(start, years=1)`, or at the source's first date if that is later.
  - Workflows. All three use the same cache path, `${{ runner.temp }}/history-cache`, since `actions/cache` matches on the path as well as the key:
    - New `.github/workflows/history.yml`:
      - `on: schedule: - cron: "0 2 * * 6"` (Saturday 02:00 UTC) and `workflow_dispatch`; `permissions: contents: read`; `concurrency: group: history, cancel-in-progress: false`.
      - One job, `history`, `runs-on: ubuntu-latest`, `timeout-minutes: 180`, `working-directory: pipeline`.
      - Steps: checkout; `astral-sh/setup-uv` at the same pinned SHA as the other workflows; `uv sync --locked --no-dev`; `actions/cache/restore@v4` with `path: ${{ runner.temp }}/history-cache`, `key: history-${{ github.run_id }}`, `restore-keys: history-`; the build, with `SEC_USER_AGENT: ${{ secrets.SEC_USER_AGENT }}`: `uv run python -m advisor.training.build --out "$RUNNER_TEMP/history-run" --no-db --history-only --history-cache "$RUNNER_TEMP/history-cache"`; `actions/cache/save@v4` with `if: always()`, the same path and `key: history-${{ github.run_id }}`, so a failed or timed-out run still keeps what it downloaded (Ruling R2, F24); `actions/upload-artifact@v4` with `if: always()`, name `history-report`, `${{ runner.temp }}/history-run/manifest.json`, 30 days.
      - Why Saturday 02:00 UTC: train runs Saturday 10:00 UTC and the benchmark on the first Sunday at 09:00 UTC, so a Saturday-morning run serves both. A run of about 98 minutes ends near 03:40; even one that reaches its 180-minute limit ends by 05:00, five hours before train, which absorbs GitHub's late scheduled starts. A run that still starts late only leaves that week's train on the previous week's cache, well within 21 days. A Sunday slot cannot precede Saturday's train.
    - `benchmark.yml`: one `actions/cache/restore@v4` step before the build, with the same path, key and restore-keys, gated by `if: steps.due.outputs.run == 'true'` (Ruling R2, F24: a non-due Sunday touches no cache). The build adds `--no-history-download --history-cache "$RUNNER_TEMP/history-cache"` and builds all groups. No save step.
    - `train.yml`: the same restore step (ungated) and the same two build options. No save step. (`--groups accepted` arrives in Task 10.)

- [ ] **Step 1: Write the failing tests.**
  - In `test_training_history.py`:
    - `test_each_wanted_group_writes_its_files_and_seconds`: `build_history` with fake deps for `{"short", "catalysts"}` writes `short_interest.parquet`, `short_volume.parquet` and `fda_events.parquet` into `cache.groups_dir`; `written.json` gives both groups `now`; `manifest["seconds"]` has `history_short` and `history_catalysts`.
    - `test_a_failing_group_is_recorded_and_the_others_still_write`: the manifest starts as `{"unavailable": {"macro": "FRED stalled"}, "seconds": {}}`; a raising FDA loader leaves `manifest["unavailable"]` with both `macro` and `catalysts`, the earlier `fda_events.parquet` and its `written.json` time unchanged, and `short` written.
    - `test_submissions_are_reduced_once_for_events_and_insider`: a counting fake reduce is called once, with `forms=SUBMISSION_FORMS`, for `{"events", "insider"}`; a raising one puts both groups in `manifest["unavailable"]` with the same message.
    - `test_a_cached_finra_file_is_not_fetched_again`: a fake client counts the requests.
    - `test_the_figi_book_and_13f_totals_live_under_the_cache_root`: `HistoryCache(root).figi_path == root / "openfigi.json"`, `.sec13f_folder == root / "sec_13f"` and `.groups_dir == root / "groups"`.
    - `test_fresh_groups_are_copied_and_stale_or_missing_ones_are_unavailable`: with `short` written at `now − 21 days`, `holders` at `now − 22 days` and no time for `analyst`, `copy_history(..., {"short", "holders", "analyst"}, now, manifest)` returns `{"short"}`, copies only the short files, and sets `manifest["unavailable"]["holders"] == "cached history is 22 days old"` and `manifest["unavailable"]["analyst"] == "no cached history"`.
    - `test_wanted_groups_reads_all_none_and_a_list`: `wanted_groups("all") == frozenset(GROUP_FILES)`, `wanted_groups("none") == frozenset()`, `wanted_groups("short,holders") == frozenset({"short", "holders"})`, and `wanted_groups("short,bogus")` raises `ValueError`.
  - In `test_training_build.py`:
    - `test_a_build_without_history_deps_writes_what_it_wrote_before`.
    - `test_history_only_writes_the_group_cache_and_no_training_files`: `out` holds exactly `manifest.json` and `tickers.parquet`, the price downloader is never called, and `cache.groups_dir / "written.json"` exists; with the default `--groups all`, `manifest["history_groups"] == sorted(GROUP_FILES)`.
    - `test_no_history_download_copies_fresh_groups_without_fetching`: `deps.history = None`, a cache with fresh `short` files and `holders` written 30 days ago: `out` has the two short files, `manifest["unavailable"]["holders"] == "cached history is 30 days old"`, and the build returns normally.
    - `test_the_history_options_exclude_each_other_and_need_a_cache`: `parse_args` with both `--history-only` and `--no-history-download`, or with either one and no `--history-cache`, raises `SystemExit`.
  - In `test_benchmark_workflow.py`:
    - `test_the_history_workflow_downloads_weekly_and_saves_the_cache_even_on_failure`: `history.yml` has `cron: "0 2 * * 6"`, `--history-only`, `--history-cache "$RUNNER_TEMP/history-cache"`, `actions/cache/restore@v4`, `key: history-${{ github.run_id }}` and `restore-keys: history-`, and `re.search(r"uses: actions/cache/save@v4\n\s+if: always\(\)", text)` matches.
    - `test_benchmark_and_train_only_restore_the_history_cache`: both files contain `actions/cache/restore@v4`, `restore-keys: history-`, `--no-history-download` and `--history-cache "$RUNNER_TEMP/history-cache"`; neither contains `actions/cache/save` or `--history-only`.
    - In `test_the_benchmark_runs_on_the_first_sunday_only_or_on_demand`, the guard count becomes `>= 6` (the gated restore step).
    - `test_the_workflows_have_time_for_the_extra_benchmark_rows` pins all three: `timeout-minutes: 360` in `benchmark.yml`, `timeout-minutes: 180` in `train.yml`, and `timeout-minutes: 180` in `history.yml`.
- [ ] **Step 2: Run them and see them fail.** `bash pipeline/scripts/in-docker.sh uv run pytest tests/unit/test_training_history.py tests/unit/test_training_build.py tests/unit/test_benchmark_workflow.py -q`
- [ ] **Step 3: Implement:**
  - `GROUP_FILES` in `model/groups.py`, and `history.py`.
  - In `build.py`: the `--history-only` path right after the universe step, and the history step after `fundamentals` (`build.py:174-192`).
  - `main()` builds the real `HistoryDeps` only when the plan downloads, with names from the `NasdaqSymbols` infos and the `FigiBook` at `cache.figi_path`.
  - `history.yml`, and the `benchmark.yml` and `train.yml` edits.
- [ ] **Step 4: Run them and the whole unit suite.** `bash pipeline/scripts/in-docker.sh uv run pytest tests/unit -q` and `bash pipeline/scripts/in-docker.sh uv run ruff check .` — clean.
- [ ] **Step 5: Commit.** `feat: a weekly history workflow builds the US data group histories into a cache`

### Task 10: training reads the groups (dataset and config), and train builds only the accepted groups

**Files:**
- Modify:
  - `pipeline/src/advisor/model/groups.py`
  - `pipeline/src/advisor/model/dataset.py` (`MarketData`, `feature_frames` at lines 84–125, `load_market` at 128–177; Ruling R5, F17)
  - `pipeline/src/advisor/model/variants.py`
  - `pipeline/src/advisor/training/history.py` and `pipeline/src/advisor/training/build.py` (`--groups accepted`, moved here from Task 9 because it needs this task's v6 `ModelConfig`; Ruling R5, F15)
  - `.github/workflows/train.yml`
- Test: `pipeline/tests/unit/test_model_dataset.py`, `pipeline/tests/unit/test_model_variants.py`, `pipeline/tests/unit/test_model_groups.py`, `pipeline/tests/unit/test_training_history.py`, `pipeline/tests/unit/test_training_build.py`, `pipeline/tests/unit/test_benchmark_workflow.py`

**Interfaces:**
- Consumes: the feature functions and lists from Tasks 2–8; Task 9's `groups.GROUP_FILES` and `history.wanted_groups`; `repo.active_config(conn, "US") -> AcceptedConfig | None` (its `config` is the stored JSON).
- Produces:
  - `groups.GroupHistory`, a frozen dataclass whose fields are all `pd.DataFrame | None = None`: `short_interest, short_volume, analyst_events, analyst_coverage, material_events, large_holders, insider_trades, holders, estimates, fda_events`.
  - `groups.FILE_FIELDS: dict[str, str]`, each file of `GROUP_FILES` → its `GroupHistory` field: the file stem, except `earnings_estimates.parquet` → `estimates`.
  - `groups.DATA_GROUPS = ("short", "analyst", "insider", "events", "holders", "earnings", "estimates", "catalysts")`.
  - `groups.GROUP_FEATURES: dict[str, list[str]]`, with earnings → `EARNINGS_FEATURES`.
  - `groups.ALL_GROUP_FEATURES`: the lists concatenated, in that order.
  - `groups.LETTERS = {"short": "s", "analyst": "a", "insider": "i", "events": "v", "holders": "h", "earnings": "e", "estimates": "t", "catalysts": "c"}`.
  - `groups.load_history(data_dir: Path) -> GroupHistory` reads the files of `GROUP_FILES` that exist (through `FILE_FIELDS`) and builds `analyst_coverage` with `analyst.coverage`.
  - `groups.present(history: GroupHistory) -> frozenset[str]`: the groups whose every source frame is present. `earnings` is always present for US.
  - `groups.group_features(history: GroupHistory, facts, tickers, split_adjusted: pd.DataFrame, splits, days, symbols) -> dict[str, pd.DataFrame]`: every name in `ALL_GROUP_FEATURES` except the four earnings names, with NaN frames for absent sources.
  - `feature_frames(..., history: GroupHistory | None = None)`. US adds `group_features`; TSX gets NaN frames for every new name. `extras = EXTRA_FEATURES + ALL_GROUP_FEATURES` (the earnings names are already among them).
  - `MarketData.groups: frozenset[str] = frozenset()`. `load_market` passes `load_history(data_dir)` for US and sets `groups = present(...)`. A group the build left out (not built, failed, or stale in the cache: Task 9's `copy_history`) is simply absent.
  - `ModelConfig` gains `short, analyst, insider, events, holders, estimates, catalysts: bool = False`. `CONFIG_VERSION = 6`; `_KEYS[6]` is version 5's keys plus the seven new ones. `to_json` and `from_json` carry them.
  - `ModelConfig.name` lists its parts in the order `factors, garch, ranker, forest, extras`, then `DATA_GROUPS` in order, then `bagged`. If that name passes 40 characters, the data groups become one `data` part followed by each group's letter: `garch+ranker+forest+data+s+a+i+v+h+e+t+c`, exactly 40.
  - `variants.data_groups(config) -> tuple[str, ...]`.
  - `extra_features` returns the market extras when `extras` is on, and each group's features for each group that is on.
  - `variants.missing_groups(data, config) -> list[str]`: the groups the config needs that `data.groups` lacks. `extra_features` raises `ValueError(f"{config.name} needs the {group} data, which this build did not write")` for the first one.
  - `history.accepted_groups(stored: Mapping | None) -> frozenset[str]`: the data groups of `ModelConfig.from_json(stored)` that have files (`frozenset(data_groups(config)) & set(GROUP_FILES)`); empty for None.
  - `build.parse_args` accepts `--groups accepted`; `main()` reads `repo.active_config(conn, "US")` and passes `accepted_groups(row.config if row else None)` as the plan's groups. `--groups accepted` with `--no-db` is a `parser.error`, since it needs the database.
  - `train.yml`'s build passes `--groups accepted` next to Task 9's `--no-history-download --history-cache "$RUNNER_TEMP/history-cache"`, so train copies only the groups its accepted config needs, and a stale group it does not need is not recorded.

- [ ] **Step 1: Write the failing tests.**

```python
def test_a_version_5_config_loads_with_the_new_groups_off():
    stored = ModelConfig(ranker=True, garch=True, forest=True).to_json() | {"version": 5}
    for key in ("short", "analyst", "insider", "events", "holders", "estimates", "catalysts"):
        stored.pop(key)
    assert ModelConfig.from_json(stored) == ModelConfig(ranker=True, garch=True, forest=True)


def test_a_name_that_would_pass_40_characters_uses_the_group_letters():
    every = ModelConfig(garch=True, ranker=True, forest=True, short=True, analyst=True, insider=True, events=True,
                        holders=True, earnings=True, estimates=True, catalysts=True)
    assert every.name == "garch+ranker+forest+data+s+a+i+v+h+e+t+c"
    assert re.fullmatch(r"[a-z+]{1,40}", every.name)
    assert ModelConfig(garch=True, ranker=True, forest=True, short=True).name == "garch+ranker+forest+short"
```

Also add:
- `test_each_group_config_trains_on_only_its_own_columns`, like the existing extras and earnings test.
- `test_a_config_whose_group_was_not_built_is_refused_by_name`: data without `insider_trades.parquet` and a config with `insider=True` raise the `ValueError` above.
- Update the two version tests in `test_model_variants.py` (Ruling R7):
  - `test_configs_name_themselves_and_round_trip`: `BASELINE.to_json()` becomes `{"version": 6, "factors": False, "garch": False, "ranker": False, "forest": False, "extras": False, "bagged": False, "earnings": False, "short": False, "analyst": False, "insider": False, "events": False, "holders": False, "estimates": False, "catalysts": False, "policy": None}`.
  - In the refusal parametrize, the unknown-version case `{"version": 6, ...}` (match `"version"`) becomes `{"version": 7, ...}`: under v6, a version-6 dict without the new keys is a keys error, not a version error.
- In `test_model_dataset.py`:
  - `test_us_rows_carry_every_group_column_and_tsx_reads_them_missing`
  - Update `test_training_rows_carry_the_extras_but_the_baseline_names_do_not_change` to `(*EXTRA_FEATURES, *ALL_GROUP_FEATURES)`.
  - `test_load_market_records_which_groups_were_built`: writing only `short_interest.parquet` and `short_volume.parquet` gives `{"short", "earnings"}`.
- In `test_model_groups.py`: `test_every_group_file_has_a_history_field`: `set(FILE_FIELDS) == {f for files in GROUP_FILES.values() for f in files}` and every value is a `GroupHistory` field.
- In `test_training_history.py`: `test_accepted_builds_only_the_groups_of_the_us_config`: `accepted_groups(ModelConfig(garch=True, ranker=True, forest=True, short=True, earnings=True).to_json()) == frozenset({"short"})` (earnings has no files) and `accepted_groups(None) == frozenset()`.
- In `test_training_build.py`: `test_accepted_groups_need_the_database`: `parse_args(["--out", "x", "--groups", "accepted", "--no-db"])` raises `SystemExit`.
- In `test_benchmark_workflow.py`: `test_train_builds_only_the_accepted_groups`: `--groups accepted` is in `train.yml` and in neither `benchmark.yml` nor `history.yml`.

- [ ] **Step 2: Run them and see them fail.** `bash pipeline/scripts/in-docker.sh uv run pytest tests/unit/test_model_variants.py tests/unit/test_model_dataset.py tests/unit/test_model_groups.py tests/unit/test_training_history.py tests/unit/test_training_build.py tests/unit/test_benchmark_workflow.py -q`
- [ ] **Step 3: Implement.** `train.py` and `live.py` need no edit: the columns arrive through `extra_features` (`train._feature_list` at line 394), as they did for earnings.
- [ ] **Step 4: Run the whole unit suite and ruff.** All pass.
- [ ] **Step 5: Commit.** `feat: configs and training rows for the US data groups`

### Task 11: live features from the collectors

Live reads every group under the training rules: the same known dates and the same windows (Ruling R3). Where a collector fetched too little to fill a training window, it fetches more.

**Files:**
- Create: `pipeline/src/advisor/model/live_groups.py`
- Modify:
  - `pipeline/src/advisor/model/live.py` (`live_features`, `_day_row`)
  - `pipeline/src/advisor/run.py` (`model_features` at line 339, `forecast_market` at line 408)
  - The collectors `finra_short_interest.py`, `finra_short_volume.py`, `yfinance_analyst.py`, `sec_insiders.py`, `openfda.py`, `sec_13f.py` and `sec_holders.py`
  - `pipeline/tests/model_data.py` (a new helper, `write_group_histories`)
- Test: `pipeline/tests/unit/test_model_live.py`, `pipeline/tests/unit/test_model_live_groups.py`, `pipeline/tests/unit/test_run_model.py`, and the seven collectors' test files

**Interfaces:**
- Consumes: Task 10's `GroupHistory` and `group_features` (through `feature_frames`); Task 3's `analyst.coverage_from`; Task 6's `holders.quarter_known`; Task 7's `estimates.report_timing`; Task 8's `openfda.FDA_LAG_DAYS` and `APPROVAL_WINDOW_DAYS`; Task 2's `short.VOLUME_SESSIONS`.
- Produces:
  - `live_features(..., history: GroupHistory | None = None)` and `model_features(..., history=None)` pass it on to `feature_frames`.
  - `live_groups.history_from_records(results: Mapping[str, CollectorResult]) -> GroupHistory`. It takes no run day: every known date comes from the records under the training rules (Ruling R3, F5). A source whose result is missing or not `CollectorStatus.OK` gives None. Each frame has the training file's columns. The sources are:
    - `finra_short_interest` (three settlements) and `finra_short_volume` (21 file days).
    - `yfinance_analyst`: `analyst_events` from `AnalystView.events`, and `analyst_coverage` from `analyst.coverage_from(oldest_event, event_count)`, the same helper training uses (Ruling R3, F19).
    - `sec_8k`.
    - `sec_13dg`: every record, including those with `other_issuer=True`, so the 13D/G counts follow the filing list exactly as training does, with no issuer check (Ruling R4).
    - `yfinance_earnings`, with `timing` from `estimates.report_timing(report_at)`.
    - `sec_form4`: only `derivative=False` trades with codes P or S, with `officer`, `director` and `ten_percent_owner` from the record and `filed_ticker` null (the live record does not keep it; no feature reads it).
    - `sec_13f`: one `holders` row per entry of `InstitutionalOwnership.quarters` that has shares, with `known = holders.quarter_known(period, window_end)`, the training rule (Ruling R3, F5). A record cached before this change has no `quarters`, so it gives no rows and the group reads NaN until the next fetch.
    - `openfda`: one `approval` row per date in `approval_days` and one `recall` row per entry of `recall_days`, read by `catalysts_features` with the same `FDA_LAG_DAYS`.
  - `forecast_market` passes `history_from_records(results)` for US.
  - Collector changes (the spec's lookbacks and caps, and the training windows):
    - `FinraShortInterest.fetch` returns the three newest published settlements, skipping unpublished days over `settlement_dates(as_of)`: when the newest is under 12 sessions old, the latest known report is the second newest and `short_chg` needs the third (Ruling R3, F6). It raises only when none is published.
    - `FinraShortVolume.fetch` returns the newest `VOLUME_SESSIONS + 1 = 21` published days within `LOOKBACK_WEEKDAYS = 30`. On a pre-open run the newest file has trade date D and is dropped by `K < D`, leaving the 20 file days training reads (Ruling R3, F7). It raises only when none is published.
    - `YFinanceAnalyst.max_symbols = 600`, which covers 300 US and 100 TSX shortlisted stocks plus holdings. `AnalystView` gains three fields:
      - `events: list[RatingEvent] = []`: the last 365 days, plus the latest downgrade.
      - `oldest_event: datetime | None = None` (naive UTC, as `graded_at`).
      - `event_count: int = 0`.

      `RatingEvent` has `graded_at, firm, action, from_grade, to_grade, price_target_action`.
    - `sec_insiders.LOOKBACK = timedelta(days=180)`. `MAX_DOCUMENTS` stays 1000: the new Form 4s for about 300 symbols in steady state are far fewer, and a run that runs out is PARTIAL, so the group is NaN for that run.
    - `openfda.WINDOW_DAYS = APPROVAL_WINDOW_DAYS + FDA_LAG_DAYS` (187; the constants are imported, not retyped): `fda_approvals_180d` counts `day + 7` in `[D − 180, D)`, so live needs approvals back to D − 187 (Ruling R3, F4). The existing `*_90d` fields still count the last 90 days. Matching uses every US name in `CompanyNames`, as training does. `DrugEvents` gains `approval_days: list[date] = []` (original and new-indication approvals) and `recall_days: dict[str, date] = {}` (event id → report date). Records are kept only for the requested symbols.
    - `sec_13f.QUARTERS = 3`, so the previous pair still exists while the newest data set is not yet known (Ruling R3, F5). `InstitutionalOwnership` gains `quarters: list[HeldQuarter] = []`, newest first, one per data set fetched, with `HeldQuarter(period: date, window_end: date, shares: int | None, holders: int | None)` (`window_end` is the data set's `end`). The existing fields keep describing the newest two quarters.
    - `LargeHolding` gains `other_issuer: bool = False`. `SecHolders.fetch` returns a structured filing whose document names another issuer as its `holding_header` with `other_issuer=True`, instead of dropping it (Ruling R4). `parse_schedule` does not change. A malformed document is still dropped and fetched again next run (rare; Task 14 records it).
    - `sec_events.LOOKBACK` (120), `sec_holders.LOOKBACK` (365) and `yfinance_earnings.REPORTS` (12) already cover the windows, so they do not change.

- [ ] **Step 1: Write the failing tests.**

```python
def test_us_live_features_match_the_training_rows_with_every_group(tmp_path):
    stocks = write_market(tmp_path, Market.US, stocks=3, days=700)
    write_group_histories(tmp_path, stocks)  # new helper in tests/model_data.py: one small file per source
    data = load_market(tmp_path, Market.US)
    day = data.calendar[WARMUP + 300]
    prices, sectors = live_inputs(tmp_path, Market.US)
    window = prices[pd.to_datetime(prices["day"]) >= day - LIVE_WINDOW]
    live = live_features(window, Market.US, day, sectors=sectors, partial_day=False,
                         facts=pd.read_parquet(tmp_path / "fundamentals.parquet"),
                         tickers=pd.read_parquet(tmp_path / "tickers.parquet"), history=load_history(tmp_path))
    training = data.rows[data.rows["day"] == day].set_index("symbol")
    assert training.loc[stocks[0], ALL_GROUP_FEATURES].notna().all()  # the comparison reads real values
    pd.testing.assert_frame_equal(live.loc[training.index, ALL_GROUP_FEATURES], training[ALL_GROUP_FEATURES],
                                  check_exact=False, rtol=1e-6, atol=1e-9)


def test_a_source_that_was_not_ok_this_run_reads_missing_not_zero():
    results = {"sec_form4": CollectorResult("sec_form4", CollectorStatus.PARTIAL, [_trade("AAPL")], 0, "budget")}
    assert history_from_records(results).insider_trades is None
```

`write_group_histories` also writes `fundamentals.parquet` (quarterly facts plus `shares_outstanding`) and `tickers.parquet`, as the earnings parity test does (`tests/unit/test_model_live.py:42-70`): the `notna()` line covers the earnings names, `days_since_downgrade`, `eps_beat_streak` and the holder pair, which need them.

Also add:
- `test_a_source_that_was_not_ok_reads_missing_in_the_features` (Ruling R3, F16, the first review focus): on the parity fixture, `live_features(..., history=history_from_records({"sec_form4": <PARTIAL result>}))` gives NaN, not 0, for the three `INSIDER_FEATURES` of `stocks[0]`, a covered symbol; `{"yfinance_analyst": <FAILED result>}` gives NaN for the four `ANALYST_FEATURES`.
- `test_records_become_the_training_layout`, one per source: the frame's columns equal its Task's file layout.
- `test_trimmed_analyst_records_give_the_full_history_features`: the features from `AnalystView.events` equal the features from the full event list on the same day.
- `test_live_13f_rows_use_the_training_known_date`: a record whose `quarters` are periods 2026-06-30, 2026-03-31 and 2025-12-31 (window ends 2026-08-31, 2026-05-31 and 2026-02-28) with holders 5, 4 and 2 gives knowns 2026-09-30, 2026-06-30 and 2026-03-30; `holder_count_chg` reads 2 on 2026-09-30 (the March and December quarters: the third quarter is what makes the pair) and 1 on 2026-10-01.
- `test_live_13dg_counts_filings_about_other_issuers_as_training_does`: a `sec_13dg` record with `other_issuer=True`, a 13G accepted 10 days before D, gives `passive_13g_90d == 1`.
- In the collector tests, the new tests:
  - `test_fetch_returns_twenty_one_days_of_short_volume`: with every weekday published, the fetch reads 21 files and stops.
  - `test_insider_lookback_covers_180_days`
  - `test_openfda_matches_against_every_us_name_and_lists_dates`
- The existing collector tests this task breaks, updated (Ruling R7 names the first five; F5's `QUARTERS = 3` and Ruling R4 break the last four):
  - `test_finra_short_interest.py`: `test_fetch_takes_the_newest_published_settlement` becomes `test_fetch_takes_the_three_newest_published_settlements`: 403 for 2026-09-30 and the fixture served at 2026-09-15, 2026-08-31 and 2026-08-14 give `seen` = those four URLs in that order, and three `AAPL` records.
  - `test_finra_short_volume.py`: `test_fetch_falls_back_from_an_unpublished_day` keeps its routes (only 2026-10-09 published): `seen[:2]` is the 2026-10-12 and 2026-10-09 URLs, `len(seen) == 30` (it looks for 21 files through all 30 weekdays), and the records are `["AAPL"]`.
  - `test_openfda.py`: `test_both_searches_cover_the_last_ninety_days_in_one_page_each` becomes `test_both_searches_cover_187_days_in_one_page_each`, with `[20260415 TO 20261019]` in both searches and `limit` still `{"1000"}`.
  - `test_sec_insiders.py`: `test_fetch_reads_the_last_90_days_of_form_4s` becomes `test_fetch_reads_the_last_180_days_of_form_4s`; its numbers stay (11 trades, 5 documents: the fixture's only older Form 4 is a 2022 4/A).
  - `test_yfinance_analyst.py`: `test_yahoo_analyst_covers_both_markets_and_is_capped` asserts `max_symbols == 600`.
  - `test_sec_13f.py`:
    - The `collector` helper serves a third data set, `EARLIER` (`01dec2025-28feb2026`, `quarter_zip("31-DEC-2025", 90)`).
    - `test_symbols_get_the_latest_quarter_and_the_one_before`: `seen` is `[LISTING_URL, LATEST, PREVIOUS, EARLIER]`, and the expected records gain `quarters`; AAPL's are `[HeldQuarter(date(2026, 6, 30), date(2026, 8, 31), 120, 1), HeldQuarter(date(2026, 3, 31), date(2026, 5, 31), 100, 1), HeldQuarter(date(2025, 12, 31), date(2026, 2, 28), 90, 1)]`.
    - `test_a_data_set_is_downloaded_once_and_old_totals_are_dropped`: the kept files add `01dec2025-28feb2026.json.gz`.
    - `test_a_listing_with_fewer_than_two_data_sets_fails` is renamed `..._fewer_than_three_...`; its match (`names 1 data sets`) still holds.
  - `test_sec_holders.py`: `test_only_filings_about_the_company_are_read` becomes `test_filings_about_another_issuer_come_back_flagged`: after the AAPL pair (`other_issuer=False`) the list has `("PFE", "0002100119-26-001294", "SCHEDULE 13G")` and `("PFE", "0000102909-26-002101", "SCHEDULE 13G/A")` with `other_issuer=True` and no reporting persons; the document count stays 4.
- In `test_run_model.py`: `test_forecast_market_passes_the_group_history_for_us_only`.

- [ ] **Step 2: Run them and see them fail.** `bash pipeline/scripts/in-docker.sh uv run pytest tests/unit/test_model_live.py tests/unit/test_model_live_groups.py tests/unit/test_run_model.py tests/unit/test_finra_short_interest.py tests/unit/test_finra_short_volume.py tests/unit/test_yfinance_analyst.py tests/unit/test_sec_insiders.py tests/unit/test_openfda.py tests/unit/test_sec_13f.py tests/unit/test_sec_holders.py -q`
- [ ] **Step 3: Implement.** `AnalystView`, `DrugEvents`, `InstitutionalOwnership` and `LargeHolding` records cached before this change lack the new fields. Their defaults (`[]`, `{}`, `0`, `None`, `False`) must let them load. Such a record yields no events, so the symbol's features read NaN until the next fetch.
- [ ] **Step 4: Run the whole unit suite, the integration tests and ruff.** `bash pipeline/scripts/in-docker.sh uv run pytest -q` and `bash pipeline/scripts/in-docker.sh uv run ruff check .` — clean.
- [ ] **Step 5: Measure the added live run time (Ruling R3, F20).** Load the agent with `export SEC_USER_AGENT="$(sed -n 's/^SEC_USER_AGENT=//p' pipeline/.env.local)"` (never echo it). In a one-off `bash pipeline/scripts/in-docker.sh uv run python -I -c ...` (nothing committed), time each changed collector's `fetch` over 300 real US symbols (the newest stored forecast shortlist, or the first 300 of the newest local `tickers.parquet`), once with the new code and once with the old settings: set the constants back (`YFinanceAnalyst.max_symbols = 200`, `sec_insiders.LOOKBACK = timedelta(days=90)`, `openfda.WINDOW_DAYS = 90`, `sec_13f.QUARTERS = 2`); for the two FINRA collectors the old cost is one file each, timed with one `get_with_retries` of the newest file. Write the added seconds into Task 14's deferred entry. If the added time takes a run past 80% of `run.yml`'s `timeout-minutes: 40` (32 minutes), measured from the last runs' wall clock, stop and tell the owner.
- [ ] **Step 6: Commit.** `feat: live runs compute the US data group features from the collectors`

### Task 12: benchmark rows, the base-row rule, the combined row, retired rows and the report

**Files:**
- Modify:
  - `pipeline/src/advisor/benchmark/job.py` (`ABLATIONS` at line 57, `US_ONLY` at 72, `bagging_twins` at 80, `_benchmark_market` at 158)
  - `pipeline/src/advisor/benchmark/accept.py` (the `choose_model` docstring only)
  - `pipeline/src/advisor/benchmark/report.py` (`_ABLATION_ORDER` at line 9, `render_markdown` at 261)
- Test: `pipeline/tests/unit/test_benchmark_rows.py`, `pipeline/tests/unit/test_benchmark_accept.py`, `pipeline/tests/unit/test_benchmark_report.py`, `pipeline/tests/integration/test_benchmark_job.py`

**Retired rows.** These were rejected in every market they ran in by both of the last two stored benchmarks: 2026-11-03 (`75718a3`, `pipeline/.cache/benchmark-2026-11-03/last-benchmark-report.md`) and 2026-11-15 (run 17, `859bd27`, `pipeline/.cache/last-benchmark-raw.txt`).

| Row | 2026-11-03, US / TSX / crypto | 2026-11-15, US / TSX / crypto | US seconds saved |
|---|---|---|---|
| `factors` | rejected ×3 | rejected ×3 | 394 |
| `extras` | rejected ×3 | rejected ×3 | 367 |
| `ranker+extras` | rejected ×3 | rejected ×3 | 433 |
| `ranker+extras+bagged` | rejected ×3 | rejected ×3 | 1,313 |
| `factors+garch` (**kept**) | not built ("arrives with Plan 6d") | rejected ×3 | — |

`factors+garch` has only one benchmark of evidence, so it stays. The retired rows save 2,507 s for US (41.8 min), 282 s for TSX and 51 s for crypto.

**Interfaces:**
- Consumes: Task 10's `ModelConfig` flags, `DATA_GROUPS` and `variants.missing_groups`.
- Produces:
  - `ABLATIONS`, in report order: `baseline, ranker, garch, factors+garch, garch+ranker, garch+ranker+forest, ranker+earnings`, then the eight group rows (`garch+ranker+forest+short`, `…+analyst`, `…+insider`, `…+events`, `…+holders`, `…+earnings`, `…+estimates`, `…+catalysts`), then `full+policy`.
  - `GROUP_BASE = "garch+ranker+forest"`. `US_ONLY = {"ranker+earnings", *the eight group rows}`.
  - `job.base_row(config: ModelConfig) -> ModelConfig | None`: the config with `bagged=False` and every data group off, or None when that equals the config.
  - `job.base_rows(ablations) -> dict[str, str]` replaces `bagging_twins` and raises `ValueError(f"{name} has no base row")`. `BASE_ROWS` replaces `BAGGING_TWINS`. The rule applies to `ranker+earnings` too (its base is `ranker`).
  - `job.combined_config(passed: Sequence[str]) -> ModelConfig | None`: `GROUP_BASE`'s config with each passed group on. None with fewer than 2 groups.
  - In `_benchmark_market` for US:
    1. Run the fixed rows. Then `choose_model(baseline, others, None, BASE_ROWS)` gives the group rows that pass strictly.
    2. When `combined_config` is not None, run the combined row (named by its `config.name`).
    3. Run the final `choose_model` over every row, with `twins` = `BASE_ROWS` plus the combined row's base.
    - A row whose `missing_groups` is not empty gets `{"status": "no data", "groups": [...]}` and no decision. With Ruling R0 this includes a group whose cached history was missing or older than 21 days (Task 9's `copy_history`).
    - If the active config's name is not among this market's rows and it can run on this data, it runs as one more row, so the incumbent rule still applies.
    - `_benchmark_market` keeps a local `configs: dict[str, ModelConfig]` holding every row it ran: the fixed rows, the combined row and the incumbent row. The policy row and the stored config read the chosen row from it; today's `model_config = ABLATIONS[chosen]` (`benchmark/job.py:224`) raises `KeyError` for the combined or incumbent row (Ruling R5, F10).
  - `report._ablation_row` renders a `"no data"` row as `no data: <groups>` (comma-joined), and `_decision` shows `no data`. Today every non-run status renders as `arrives with {plan}` (`benchmark/report.py:74-75`), which would read "arrives with " (Ruling R5, F10).
  - `report._new_data_table(market: Mapping) -> list[str]`, rendered right after the "Chosen" line when the market has a `garch+ranker+forest` row and at least one group row:

```
### Did the new data help?

| Group | Rank IC vs base | Top 5% vs base | Decision |
| --- | --- | --- | --- |
| short | +0.004 | +0.12% | rejected: not better than garch+ranker+forest |
```

  - How the table's numbers are computed:
    - Rank IC: the row's `summary["pooled"]["rank_ic"]` minus the base's.
    - Top 5%: the mean of pooled `top_slice[h]["top_excess"]` over the horizons both rows have, minus the base's.
    - A missing number renders as `—`.
    - The combined row is the last line, labelled by its name.
  - `_ABLATION_ORDER` follows the new `ABLATIONS` order. A stored report's retired rows still render, after the known ones.

- [ ] **Step 1: Write the failing tests.**

```python
def test_every_group_row_is_judged_against_the_base_row_and_bagging_against_its_twin():
    rows = base_rows(ABLATIONS)
    assert rows["garch+ranker+forest+short"] == "garch+ranker+forest"
    assert rows["ranker+earnings"] == "ranker"
    assert base_rows({"ranker+extras": ModelConfig(ranker=True, extras=True),
                      "ranker+extras+bagged": ModelConfig(ranker=True, extras=True, bagged=True)}) == {
        "ranker+extras+bagged": "ranker+extras"}


def test_the_retired_rows_are_gone_and_factors_garch_stays():
    assert not {"factors", "extras", "ranker+extras", "ranker+extras+bagged"} & set(ABLATIONS)
    assert "factors+garch" in ABLATIONS


def test_the_group_rows_run_for_us_only_before_the_policy_row():
    names = list(ABLATIONS)
    groups = [n for n in names if n.startswith("garch+ranker+forest+")]
    assert len(groups) == 8 and names.index(POLICY_ROW) == len(names) - 1
    for market in (Market.TSX, CRYPTO):
        assert not set(groups) & set(rows_for(market))


def test_the_combined_row_needs_two_groups_that_passed():
    assert combined_config(["short"]) is None
    assert combined_config(["short", "estimates"]).name == "garch+ranker+forest+short+estimates"
```

Also:
- In `test_benchmark_accept.py`, keep the `TWINS` tests and add `test_a_group_row_that_only_beats_the_baseline_is_rejected`: base scores 0.089 and the group row 0.0891 with 2 of 4 folds better give `reasons[0] == "not better than garch+ranker+forest"`.
- Replace `test_every_bagged_row_is_judged_against_the_same_row_without_bagging` and `test_a_bagged_row_without_its_twin_is_refused` with the `base_rows` tests.
- Update `test_the_earnings_row_sits_before_the_policy_row_and_runs_for_us_only` to the new order.
- In `test_benchmark_report.py`: `test_the_new_data_table_opens_each_market_with_a_group_row` (a two-row fixture giving +0.004 and +0.12%) and `test_a_market_without_group_rows_has_no_new_data_table`.
- In `test_benchmark_report.py`: `test_a_row_without_its_data_reads_no_data_and_its_groups`: a row `{"status": "no data", "groups": ["insider"]}` renders a line containing `no data: insider` and no line containing `arrives with` (Ruling R5, F10).
- In `tests/integration/test_benchmark_job.py`:
  - `test_the_combined_row_runs_when_two_groups_pass`: monkeypatch `ABLATIONS` and `BASE_ROWS` (computed at import) to the baseline, the base and two group rows on synthetic data, with `choose_model` patched to pass them. When the patched final `choose_model` picks the combined row, the market stores that row's config, with no `KeyError` (Ruling R5, F10).
  - `test_an_active_config_without_a_row_is_still_scored`.

- [ ] **Step 2: Run them and see them fail.** `bash pipeline/scripts/in-docker.sh uv run pytest tests/unit/test_benchmark_rows.py tests/unit/test_benchmark_accept.py tests/unit/test_benchmark_report.py -q`
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the whole suite and ruff.** `bash pipeline/scripts/in-docker.sh uv run pytest -q` (with `advisor-pg` up) and `bash pipeline/scripts/in-docker.sh uv run ruff check .` — clean.
- [ ] **Step 5: Measure on real data, in the Ruling R0 layout.**
  1. Load the agent from the repo root: `export SEC_USER_AGENT="$(sed -n 's/^SEC_USER_AGENT=//p' pipeline/.env.local)"` (Ruling R1; never echo it).
  2. The history job on an empty cache: `bash pipeline/scripts/in-docker.sh uv run python -m advisor.training.build --out .cache/history-run-7b --no-db --history-only --history-cache .cache/history-7b`. Read its wall clock and `manifest.json` `seconds` (the first run). Run it again on the warm cache for the steady state.
  3. The benchmark's build: `bash pipeline/scripts/in-docker.sh uv run python -m advisor.training.build --out .cache/train-7b --no-db --no-history-download --history-cache .cache/history-7b`. Read its `seconds`; `manifest["unavailable"]` must name no group.
  4. Time two rows in a one-off `uv run python -c` that loads `load_market(Path(".cache/train-7b"), Market.US, with_factors=True, with_garch=True)`: first `garch+ranker+forest` (it fills `garch_cache`), then `garch+ranker+forest+short` with `run_variant`. Only the second is the group row's time.
  5. Write the measured projection into the Task 0 ledger's "Projection after Ruling R0" row:
     - History job = step 2's wall clock, first and steady, against 180 (the ledger projects about 98 min, 54%).
     - Benchmark = 141.5 − 41.8 + 9 × step 4's group row + one incumbent row (the same time) + 11.7 + 7.4 + step 3's build, against 360 (the ledger projects about 210 min, 58%).
     - Train = today's 57 min plus step 3's copy time (train downloads no group history), against 180.

     If any passes 80% (144 / 288 / 144 min), stop and report to the owner before committing.
- [ ] **Step 6: Commit.** `feat: benchmark rows for every US data group, judged against their base row`

### Task 13: news and option summaries stay on record for a later test

**Files:**
- Modify: `pipeline/src/advisor/run.py` (after enrichment, store each US forecast symbol's `yfinance_options` summary in `features_live`)
- Test: `pipeline/tests/unit/test_run_model.py` (or the run test that already checks `merge_features_live` calls), `pipeline/tests/integration/test_schema.py`

**Findings this task starts from** (checked 2026-11-19):
- News features are merged into `features_live` on every run (`run.py:255`, `news/stage.py:184-190`): `news_stories_48h`, `news_outlets_48h`, `news_sentiment_mean`, `news_sentiment_trend` and `news_volume_z`.
- Option summaries are **not**. `OptionsView` records (`collectors/yfinance_options.py:65`) reach no table, and the source is capped at `max_symbols = 40` a run.
- Nothing deletes `runs` or `features_live`. `features_live.run_id` cascades only from a deleted run. `repo.py` prunes news items after 90 days, plus `screen_ranks`, models, filings, insider trades and earnings rows, but never runs.

**Interfaces — Produces:**
- `run.option_feature_rows(records: Sequence[OptionsView]) -> list[tuple[AssetRef, dict]]`, with the keys `opt_atm_iv_near`, `opt_atm_iv_mid`, `opt_skew_near`, `opt_put_call_volume` and `opt_put_call_open_interest` (finite values only), merged with `repo.merge_features_live` in the same run.
- `test_schema.py` gains `test_features_live_rows_are_kept_with_their_run` (Ruling R5, F9): it inserts a run and a `features_live` row dated 2020-01-01, before every retention window, calls every prune path (`repo.prune_models`, `prune_news_items`, `prune_holding_monitor`, `prune_daily_closes`, `prune_daytrade`) and `sweep_abandoned_runs` with arguments that would delete the oldest rows, and asserts that the row is still there.

- [ ] **Step 1: Write the failing tests.**
  - `test_option_summaries_are_stored_with_the_run`: a fake `yfinance_options` result for `AAPL` gives a `features_live` row with `opt_atm_iv_near == 0.24`.
  - `test_a_missing_option_value_is_left_out`
  - `test_features_live_rows_are_kept_with_their_run`, as above. It pins today's behaviour, so it passes at once.
- [ ] **Step 2: Run them and see the first two fail.** `bash pipeline/scripts/in-docker.sh uv run pytest tests/unit/test_run_model.py tests/integration/test_schema.py -q` (with `advisor-pg` up).
- [ ] **Step 3: Implement.** Do not raise the 40-symbol cap here (run budget); the deferred entry says so.
- [ ] **Step 4: Run the unit and integration suites; all pass.** `bash pipeline/scripts/in-docker.sh uv run pytest -q` (with `advisor-pg` up) and `bash pipeline/scripts/in-docker.sh uv run ruff check .`.
- [ ] **Step 5: Commit.** `feat: keep option summaries in features_live for a later test`

### Task 14: record the change

**Files:**
- Modify:
  - `docs/superpowers/deferred.md`: a new section, "Plans 7b–7d: every US data group".
  - `pipeline/README.md`: under Training, the weekly `history.yml`, the build options `--groups`, `--history-cache`, `--history-only` and `--no-history-download`, and the new files.
  - `README.md`: no change, since no new secret or migration is needed.

- [ ] **Step 1: Add the deferred entries:**
  - FINRA re-issues files, so the short-interest history holds revised values. This is a small look-ahead that cannot be removed.
  - A FINRA ticker change (FB → META) reads NaN before the change: missing, not wrong.
  - Yahoo shows the final consensus before each report.
  - 13D/G counts follow each company's filing list, in training and live alike, with no issuer check (Ruling R4). A listed asset manager or bank that files 13D/Gs about other issuers has them counted as its own. This noise is accepted; live and training agree. Live still drops a malformed structured document (rare).
  - Insider trades are not filtered to common stock, although the spec says "of common stock": live Form 4 records do not carry the security title, so neither side filters (Ruling R3, F21).
  - The 13F CUSIP map comes from the newest data set with FIGIs and is used for every older quarter; Task 6 Step 5 measured its coverage at the share written in the ledger.
  - Matching sponsor names against the whole universe is noisier than the old shortlist-only matching.
  - News features become testable after about 12 months of stored runs (from 2026-11), and option summaries about 12 months after Task 13 merges. Both samples are the forecast shortlist (300 US stocks plus holdings, with options capped at 40 a run), not every stock, so a test must read them with care.
  - Group history is downloaded weekly by `history.yml` (Saturday 02:00 UTC) into an actions cache (Ruling R0). The benchmark and train read histories up to a week old; a group whose cache is missing or older than 21 days is unavailable for that run. The first history run pays the whole download (the ledger's first-build minutes).
  - The live run time added by Task 11, as measured in its Step 5.
- [ ] **Step 2: Update `pipeline/README.md`** with `history.yml`, the four build options and the history files.
- [ ] **Step 3: Commit.** `docs: plan 7b–7d, every US data group` (this plan, `deferred.md` and `pipeline/README.md`).
- [ ] **Step 4: Tell the owner** to run `history.yml` (workflow_dispatch) first, so that the cache exists, and then `benchmark.yml` (workflow_dispatch) to see the "Did the new data help?" tables. Nothing is pushed.

---

## Controller rulings (2026-11-19)

Binding; the task text above carries them. Source: `.superpowers/sdd/2026-11-19-plan-7b-all-us-data/progress.md` and `preflight.md` (F1–F24).

- **R0** (time; Task 0, F2, F23): group history moves to a weekly `history.yml` (Saturday 02:00 UTC, timeout 180) that saves an actions cache even on failure; benchmark and train only restore it (`--no-history-download`), and a group missing or older than 21 days is unavailable. Tasks 9, 10, 12, 14; Global Constraints, Review Focus 6, ledger.
- **R1** (F1): the SEC agent is loaded with `export SEC_USER_AGENT="$(sed -n 's/^SEC_USER_AGENT=//p' pipeline/.env.local)"`. Tasks 0, 6, 11, 12; Global Constraints.
- **R2** (F3, F13, F14, F22, F24): the FIGI book and 13F totals live in the cache root; FINRA files are cached whole and mapped on read; `reduce_submissions` runs once with a forms filter; overflow pages are wrapped for `parse_filings`; cache steps are gated and saved on failure. Tasks 2, 4, 5, 6, 9.
- **R3** (F4, F5, F6, F7, F11, F16, F19, F20, F21): live uses the training known dates and windows (187 openFDA days, three FINRA settlements, 21 short-volume files, three 13F sets); the capped downgrade rule; NaN tests at feature level; one coverage helper; the live run time is measured; thicker file columns. Tasks 2, 3, 5, 6, 7, 8, 11, 14; Global Constraints.
- **R4** (F8): live counts 13D/13G from the filing list as training does (`LargeHolding.other_issuer`); the noise is recorded. Tasks 4, 11, 14.
- **R5** (F9, F10, F12, F15, F17, F18): the `features_live` test asserts; `configs` dict and the "no data" render; Yahoo history stops only on a rate limit; `GROUP_FILES` in `model/groups.py` and `--groups accepted` in Task 10; dataset line numbers; the sponsor test. Tasks 3, 7, 8, 9, 10, 12, 13.
- **R6**: the FINRA partitions URL; the 13F CUSIP map from the newest set with FIGIs, coverage measured; 13F known date = later of period end + 45 days and window end + 30 days. Tasks 0, 2, 6, 11; Global Constraints.
- **R7**: Task 10 updates the two version tests in `test_model_variants.py`; Task 11 updates the five collector tests it breaks, plus the four that F5 (`QUARTERS = 3`) and R4 break in `test_sec_13f.py` and `test_sec_holders.py`. Tasks 10, 11.
