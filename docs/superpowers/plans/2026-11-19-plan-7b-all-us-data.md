# Plan 7b–7d: every US data group the app collects — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build point-in-time history for the US data groups `short`, `analyst`, `insider`, `events`, `holders`, `estimates` and `catalysts` (plus the existing `earnings`), compute the same features live from the collectors, and judge one benchmark row per group on `garch+ranker+forest` against that base row and the baseline, plus one row with every group that passed.

**Architecture:** Each group has a pure feature module in `pipeline/src/advisor/model/` in the style of `model/earnings.py`: a long history frame in, wide day × symbol frames out, and a row reads only what was known strictly before its day. `training/build.py` writes one Parquet history per source. `model/groups.py` carries them as a `GroupHistory`, which `dataset.feature_frames` turns into extra columns for training and live alike; `model/live_groups.py` builds the same `GroupHistory` from the run's collector records. `ModelConfig` gains one flag per group. `benchmark/job.py` adds the rows, a generalised base-row rule, a combined row built in the same run from the groups that passed, and retires four rows that the stored results rejected everywhere.

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
  - 13F quarter: the later of period end + 45 days and the data set's publication date (the Task 0 ledger says how that date is read). Live: the run day minus one day.
  - openFDA approval or recall: its date + `FDA_LAG_DAYS = 7`. openFDA refreshes weekly, so live sees an event up to a week late, and training waits the same week.
- Missing, not zero:
  - A symbol with no SEC facts (its CIK is not among the CIKs in `fundamentals.parquet` or in the run's `sec_xbrl` facts) reads NaN for `insider` and `events`. A symbol with SEC facts and no filings reads 0 counts.
  - `analyst` is NaN before a symbol's first recorded event.
  - `holders` is NaN without a quarter-on-quarter pair.
  - `estimates` is NaN without reports.
  - `catalysts` is 0 for every US symbol whenever the openFDA history is present.
- Share counts on today's basis: a share count dated T is multiplied by `fundamentals._split_at(splits, symbol, T)` before it is compared with another (short interest, 13F shares, shares outstanding).
- Live: a source whose run status is not `CollectorStatus.OK` contributes NaN for its features in that run, never zeros. Live uses the same feature function and the same code path as training (`feature_frames`).
- `ModelConfig` gets the flags `short, analyst, insider, events, holders, estimates, catalysts` (default False; `earnings` exists). There is one bump: `CONFIG_VERSION = 6`. Versions 1–5 load with the new flags off.
- Variant names match `^[a-z+]{1,40}$` (`supabase/migrations/0010_benchmarks.sql:14`).
- Acceptance limits are unchanged: `PINBALL_TOLERANCE`, `MIN_FOLDS_IMPROVED`, `MAX_CALIBRATION_PTS`, `INCUMBENT_CALIBRATION_PTS` and the policy limits. A rejected row is a result, not something to retry.
- Time budget: `benchmark.yml` has `timeout-minutes: 360` and `train.yml` has `timeout-minutes: 180` (pinned by `pipeline/tests/unit/test_benchmark_workflow.py`). If a projection passes 80% (288 and 144 minutes), stop and come back to the owner. No timeout is raised and no row is dropped without asking; `catalysts` is the row proposed first.
- Free data only, and no keys in the repo. `SEC_USER_AGENT` is read from the environment and never printed. Nasdaq.com's earnings history is not used.
- `git commit` runs as its own shell command (a hook blocks any `-n` flag in the same command). Never `--no-verify`. No push, no merge.
- Commit trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. A live run where the Form 4 document budget runs out, or Yahoo stops answering: the affected source's features must be NaN for every symbol in that run, never zero counts. (Task 11)
2. A split between two short-interest reports or two 13F quarters: `short_chg` and `inst_shares_chg` must not show the split as a change. (Tasks 2, 6)
3. A row dated exactly on a known date (an 8-K accepted that morning, a short-interest file's 12th session, a report day): it must not read the new record. (Tasks 1–8)
4. A month where the active config is the combined row and this run's passing groups differ, or where the active config is a retired row: the incumbent must still be scored and judged under the incumbent rule. (Task 12)
5. An old source file in an older layout (a 2017 FINRA header, a 2018 13F data set without a FIGI column, a quarterly 13F file name): the build reads it by column name or records the gap. It does not crash. (Tasks 2, 6)

---

### Task 0: verify the unverified sources and project the time (throwaway)

**Files:**
- Create (not committed): `pipeline/.cache/probe_7b.py` (`pipeline/.cache/` is git-ignored). Downloads go to a new, empty `pipeline/.cache/probe-7b/`.
- Modify: the "Task 0 ledger" in this plan.

**Interfaces — Produces:** the ledger values that later tasks read: whether the overflow pages are inside `submissions.zip`, the Form 3/4/5 link regex, the older 13F file-name pattern and FIGI column, the 13F publication-date rule, `ANALYST_CAP_ROWS`, the 2017 FINRA header, openFDA's depth, and the per-source seconds.

- [ ] **Step 1: Load the SEC user agent without printing it.** From the repo root: `export $(grep '^SEC_USER_AGENT=' pipeline/.env.local | xargs)`. Never echo it. The probe sends it only to sec.gov hosts.
- [ ] **Step 2: Write the probe.** Write one function per question. Each prints a one-line answer and its seconds. The questions:
  1. `https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip`: its size from `HEAD`. Download it once, which also gives the download time. Count the entries, and count the entries matching `-submissions-\d{3}\.json$`. Answer: are the overflow pages inside the zip?
  2. Form 3/4/5 data sets: fetch `https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets`. Find a regex that matches every quarterly zip link, 2006Q1–2026Q3. Download `2018q1`. Print the headers of SUBMISSION, REPORTINGOWNER and NONDERIV_TRANS, and say whether REPORTINGOWNER has `RPTOWNERNAME`.
  3. 13F: the link names on `sec_13f.LISTING_URL` for 2018 (quarterly `2018q1_form13f.zip` style, or window style). Download one 2018 set and print the INFOTABLE and COVERPAGE headers: is `FIGI` present, and is `AMENDMENTTYPE`? Time `sec_13f.aggregate` on it (patched to skip a missing FIGI column). Does the listing show a publication date for each set?
  4. Yahoo, for `AAPL`, `MSFT` and `CRUS`: from `yf.Ticker(s).get_earnings_dates(limit=100)`, the row count, the rows since 2018-01-01 and the columns. From `upgrades_downgrades`, the row count and the oldest date (the cap). The seconds per call over 50 universe symbols, for each call, at `YAHOO_PER_MINUTE = 120`.
  5. FINRA: the first and last settlement from the partitions API `https://api.finra.org/data/group/otcMarket/name/consolidatedShortInterest/partitions`. The header of `shrt20171229.csv` compared with `finra_short_interest.HEADER`. Whether `CNMSshvol20180801.txt` exists, and its header. The seconds per file.
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
| submissions.zip size / download seconds | |
| Overflow pages inside the zip | |
| Form 3/4/5 link regex; first and last quarter; `RPTOWNERNAME` present | |
| 13F 2018 file-name pattern; FIGI column in 2018; AMENDMENTTYPE in 2018 | |
| 13F publication date shown on the listing | if not shown: window end + 30 days |
| `aggregate` seconds per data set | |
| Yahoo earnings rows since 2018 (AAPL / MSFT / CRUS) | |
| Yahoo `upgrades_downgrades` cap (`ANALYST_CAP_ROWS`) | |
| Seconds per Yahoo call (analyst / earnings) | |
| FINRA first settlement; 2017 header equals `HEADER`; first short-volume day | |
| openFDA 2018 totals (enforcement / drugsfda); bulk files listed | |
| OpenFIGI seconds per 10 tickers | |
| Projected added build, first / steady (min) | |
| Projected benchmark job / train job (min) | |

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
- Modify: `pipeline/src/advisor/collectors/finra_short_interest.py` (`parse_short_interest` reads its columns by name)
- Test: `pipeline/tests/unit/test_model_short.py`, `pipeline/tests/unit/test_training_finra_history.py`, `pipeline/tests/unit/test_finra_short_interest.py`

**Interfaces:**
- Consumes: Task 1's `shares_outstanding` and `window_count`; `finra_short_interest.FINRA_SHORT_INTEREST_URL`; `finra_short_volume.FINRA_SHORT_VOLUME_URL` and `parse_short_volume`; `symbols.requested_by_key`.
- Produces:
  - History files:
    - `short_interest.parquet`: `symbol` string, `settlement` date, `short_interest` int64, `avg_daily_volume` float64, `days_to_cover` float64 (NaN for FINRA's `999.99` or for no volume).
    - `short_volume.parquet`: `symbol`, `day` date, `short_volume` float64, `total_volume` float64.
  - `finra_history.settlement_dates(client: httpx.Client) -> list[date]`, from the partitions API.
  - `finra_history.short_interest_history(client, dates, symbols, cache: HistoryCache | None, limiter) -> pd.DataFrame`.
  - `finra_history.short_volume_history(client, days, symbols, cache, limiter) -> pd.DataFrame`. A day answering 403 or 404 is skipped.
  - `HistoryCache` is defined in Task 9. Until then, pass `None`.
  - `short.SHORT_FEATURES = ["short_pct_shares", "days_to_cover", "short_chg", "short_vol_ratio_20d"]`, with `SHORT_KNOWN_SESSIONS = 12`, `SHORT_STALE_DAYS = 45`, `VOLUME_SESSIONS = 20` and `VOLUME_MIN = 10`.
  - `short.short_features(interest: pd.DataFrame | None, volume: pd.DataFrame | None, shares: pd.DataFrame, splits: pd.DataFrame, days: pd.DatetimeIndex, symbols: Sequence[str]) -> dict[str, pd.DataFrame]`. When `interest` is None, its three columns are NaN; when `volume` is None, its column is.
- Rules:
  - `short_pct_shares` = the latest known short interest (today's basis) / `shares`.
  - `short_chg` = (that − the symbol's previous settlement, both on today's basis) / `shares`.
  - `days_to_cover` is FINRA's value.
  - All three are NaN when the latest settlement is more than `SHORT_STALE_DAYS` before the day.
  - `short_vol_ratio_20d` = the mean of daily `short_volume / total_volume` over the last `VOLUME_SESSIONS` trade dates strictly before the day (sessions with `total_volume > 0`). It is NaN with fewer than `VOLUME_MIN`.

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
    interest = _interest("A", ["2026-01-15", "2026-01-30"], [1_000_000, 2_000_000])
    splits = _split("A", "2026-01-20", 2.0)  # 2-for-1: the first report is 2,000,000 on today's basis
    out = short_features(interest, None, _shares(DAY, "A", 20_000_000), splits, DAY, ["A"])
    assert out["short_chg"]["A"].iloc[0] == pytest.approx(0.0)


def test_short_volume_ratio_needs_ten_of_twenty_sessions():
    nine = _volume("A", _sessions_before("2026-06-30", 9), short=40, total=100)
    ten = _volume("A", _sessions_before("2026-06-30", 10), short=40, total=100)
    assert np.isnan(_ratio_on(nine, "2026-06-30"))
    assert _ratio_on(ten, "2026-06-30") == pytest.approx(0.40)
```

The helpers `_interest`, `_shares`, `_split`, `_volume`, `_sessions_before` and `_ratio_on` are local to the test file. Also add:
- `test_a_symbol_finra_does_not_list_reads_missing`
- `test_a_report_older_than_45_days_reads_missing`
- In `test_finra_short_interest.py`: `test_an_older_header_with_the_named_columns_still_parses`, using the 2017 header from the ledger (or extra and reordered columns). Keep `test_an_unexpected_header_is_rejected`, changed to a header missing `currentShortPositionQuantity`.
- In `test_training_finra_history.py`: `test_the_history_maps_finra_symbols_to_the_universe` (`BRK/B` → `BRK.B`) and `test_an_unpublished_day_is_skipped` (a fake client answering 403).

- [ ] **Step 2: Run them and see them fail.** `bash pipeline/scripts/in-docker.sh uv run pytest tests/unit/test_model_short.py tests/unit/test_training_finra_history.py tests/unit/test_finra_short_interest.py -q`
- [ ] **Step 3: Implement** three things:
  - `parse_short_interest`, reading columns by name. The required columns are `symbolCode`, `currentShortPositionQuantity`, `previousShortPositionQuantity`, `averageDailyVolumeQuantity`, `daysToCoverQuantity` and `settlementDate`.
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
  - `yahoo.collect_yahoo` and `YAHOO_PER_MINUTE`.
  - Task 1's `window_count` and `days_since`.
- Produces:
  - `analyst_events.parquet`: `symbol`, `graded_at` (datetime64[ns], naive UTC), `firm`, `action`, `from_grade`, `to_grade`, `price_target_action`.
  - `yahoo_history.analyst_history(symbols: Sequence[str], load: Callable[[str], pd.DataFrame], limiter: RateLimiter | None) -> pd.DataFrame` — one call per symbol, under `collect_yahoo`'s stop rules. A symbol Yahoo has nothing for adds no rows.
  - `analyst.ANALYST_FEATURES = ["net_upgrades_30d", "net_upgrades_90d", "net_target_raises_90d", "days_since_downgrade"]`, with `ANALYST_CAP_ROWS` (from the Task 0 ledger; 1000 if Yahoo shows no exact cap) and `DOWNGRADE_CAP = 365`.
  - `analyst.coverage(events: pd.DataFrame) -> pd.DataFrame` — columns `symbol`, `oldest` (known day) and `rows`.
  - `analyst.analyst_features(events: pd.DataFrame | None, coverage: pd.DataFrame | None, days, symbols) -> dict[str, pd.DataFrame]`.
- Rules:
  - `known` is the ET date of `graded_at`.
  - Net upgrades = the count of `action == "up"` minus the count of `"down"`. Net target raises = the count of `"Raises"` minus the count of `"Lowers"`.
  - All four features are NaN on days up to and including the symbol's `oldest`. For a capped symbol (`rows >= ANALYST_CAP_ROWS`) they stay NaN until `oldest + 90 days`.
  - `days_since_downgrade` = the days since the latest known `"down"`, capped at `DOWNGRADE_CAP`. It is NaN when there has been none yet.

- [ ] **Step 1: Write the failing tests.**
  - `test_counts_are_missing_before_the_first_recorded_event`
  - `test_net_upgrades_over_30_and_90_days`: events up at D−10, up at D−40 and down at D−50 give 30d = 1 and 90d = 1.
  - `test_target_raises_minus_cuts`
  - `test_an_event_graded_on_the_row_day_is_not_read`
  - `test_a_capped_symbol_reads_missing_until_its_window_is_covered`: with rows = `ANALYST_CAP_ROWS` and oldest 2020-01-02, the row on 2020-03-31 is NaN and the row on 2020-04-02 is a number.
  - `test_days_since_downgrade_caps_at_365`
  - `test_the_history_keeps_one_row_per_event_and_symbol`: a fake loader with two symbols.
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
  - `sec.parse_filings`, for each filing's `form`, `items`, `file_number`, `accepted_at` and `filing_date`.
  - `sec_events.EVENT_FORMS`, `sec_holders.HOLDER_FORMS` and `sec_holders.SUBJECT_FILE_NUMBER`.
  - Task 1's `sec_known`, `window_count`, `days_since` and `covered_symbols`.
- Produces:
  - `sec.SUBMISSIONS_ZIP_URL = "https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip"`.
  - `sec_history.reduce_submissions(zip_path: Path, ciks: Iterable[int], since: date, page: Callable[[str], Mapping] | None) -> pd.DataFrame`. It returns `cik, accession, form, filing_date, accepted_at, items (list[str]), file_number` for filings on or after `since`. It reads each company's `filings.recent` plus each `filings.files` page. The pages come from the zip when the ledger says they are inside it, and otherwise through `page`, one SEC request each.
  - `sec_history.material_events(filings, tickers) -> pd.DataFrame`, written as `material_events.parquet`: `symbol, accession, form, filing_date, accepted_at, items`. Forms in `EVENT_FORMS` only.
  - `sec_history.large_holder_filings(filings, tickers) -> pd.DataFrame`, written as `large_holders.parquet`: `symbol, accession, form, filing_date, accepted_at, activist`. Forms in `HOLDER_FORMS` whose `file_number` starts with `"005-"`; `activist` is true when the form contains "13D".
  - `events.EVENT_ITEMS = ("5.02", "1.01", "2.01", "4.02", "3.01")`.
  - `events.EVENTS_FEATURES = ["ev_502_90d", "ev_101_90d", "ev_201_90d", "ev_402_90d", "ev_301_90d", "days_since_8k", "activist_13d_180d", "passive_13g_90d"]`, with `DAYS_SINCE_8K_CAP = 120` (the live `sec_events.LOOKBACK`).
  - `events.events_features(filings_8k: pd.DataFrame | None, holders_13dg: pd.DataFrame | None, covered: set[str], days, symbols) -> dict[str, pd.DataFrame]`.
- Rules:
  - An item count counts the filings whose `items` include that code.
  - `activist_13d_180d` and `passive_13g_90d` are 1/0 indicators.
  - Every feature is NaN for a symbol not in `covered`.
  - `days_since_8k` reads `DAYS_SINCE_8K_CAP` for a covered symbol with no 8-K in that span, so live (which sees 120 days) agrees.

- [ ] **Step 1: Write the failing tests.**
  - `test_item_counts_over_90_days_by_acceptance`: an 8-K with items `["5.02", "9.01"]` accepted 2026-03-02 21:00 UTC is counted from 2026-03-03, not on 2026-03-02.
  - `test_an_8k_without_acceptance_time_waits_one_session_after_filing`
  - `test_days_since_8k_is_120_for_a_covered_symbol_without_one`, which also asserts NaN for an uncovered symbol.
  - `test_13d_and_13g_indicators_use_their_own_windows`: a 13D at D−170 gives 1; a 13G at D−100 gives 0.
  - `test_new_and_legacy_schedule_names_both_count`: `"SCHEDULE 13D/A"` and `"SC 13D"`.
  - `test_a_13dg_without_the_subject_file_number_is_ignored`: `file_number=""`.
  - `test_reduce_reads_recent_and_overflow_pages`: a tiny zip built in the test, one company with `recent` and one `files` page. The page is served from the zip or by a fake `page` callable, as the ledger says.
  - `test_filings_before_since_are_dropped`
- [ ] **Step 2: Run them and see them fail.** `bash pipeline/scripts/in-docker.sh uv run pytest tests/unit/test_model_events.py tests/unit/test_training_sec_history.py -q`
- [ ] **Step 3: Implement.** Reuse `sec.parse_filings` on each JSON's `recent` and on each page; pages carry the same parallel arrays at the top level. Call `check_deadline()` every 200 companies, as `reduce_companyfacts` does.
- [ ] **Step 4: Run them; all pass.**
- [ ] **Step 5: Commit.** `feat: 8-K and Schedule 13D/G history and features`

### Task 5: `insider` — Form 4 open-market trades from SEC's quarterly data sets

**Files:**
- Create: `pipeline/src/advisor/model/insider.py`
- Modify: `pipeline/src/advisor/training/sec_history.py`
- Test: `pipeline/tests/unit/test_model_insider.py`, `pipeline/tests/unit/test_training_sec_history.py`

**Interfaces:**
- Consumes: Task 4's `reduce_submissions` output (acceptance times by accession); Task 1's helpers and `shares_outstanding` (for the market value below).
- Produces:
  - `sec_history.INSIDER_LISTING_URL = "https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets"`.
  - `sec_history.insider_data_sets(html: str) -> list[tuple[str, str]]` — a quarter such as `"2018q1"` and its absolute URL. The links are read from the page with the ledger's regex, never built.
  - `sec_history.reduce_insider_set(zip_path: Path) -> pd.DataFrame` — one row per non-derivative transaction of a Form `4` or `4/A`, with `code` in `{"P", "S"}` only. Columns: `accession, issuer_cik, filed_ticker, filing_date, trade_date, code, shares, price, owners (list[str]), officer, director, ten_percent_owner`.
    - `FILING_DATE` is `DD-MON-YYYY`; parse it with `sec_13f.sec_date`.
    - Owners and roles come from REPORTINGOWNER: `RPTOWNERNAME`, and `RPTOWNER_RELATIONSHIP` containing "Officer", "Director" or "TenPercentOwner".
  - `sec_history.insider_history(sets: Sequence[pd.DataFrame], filings: pd.DataFrame, tickers) -> pd.DataFrame`, written as `insider_trades.parquet`: `symbol, accession, filing_date, accepted_at, trade_date, code, shares, price, owners, officer`. The symbol comes from `issuer_cik` through `tickers`. `accepted_at` is joined by accession and is NaT when missing.
  - `insider.INSIDER_FEATURES = ["insider_net_buy_90d", "insider_buyers_90d", "officer_buy_180d"]`.
  - `insider.insider_features(trades: pd.DataFrame | None, market_value: pd.DataFrame, covered: set[str], days, symbols) -> dict[str, pd.DataFrame]`, where `market_value` is the split-adjusted close × `shares_outstanding` (wide).
- Rules:
  - Dollars = shares × price. A row without a price adds 0 dollars but still counts as a buyer.
  - Net buy = (P dollars − S dollars) over 90 days / market value.
  - Buyers = the distinct owner names in P trades over 90 days.
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
- `test_reduce_keeps_only_open_market_trades_of_form_4`: a fixture zip with a Form 3 row, an `A` award and a `P` purchase gives 1 row.
- `test_history_joins_acceptance_by_accession_and_maps_the_issuer_cik`

- [ ] **Step 2: Run them and see them fail.** `bash pipeline/scripts/in-docker.sh uv run pytest tests/unit/test_model_insider.py tests/unit/test_training_sec_history.py -q`
- [ ] **Step 3: Implement.** Read the tab-separated files by column name, as `sec_13f._rows` does.
- [ ] **Step 4: Run them; all pass.**
- [ ] **Step 5: Commit.** `feat: insider trade history and features`

### Task 6: `holders` — 13F quarter-on-quarter changes

**Files:**
- Create: `pipeline/src/advisor/model/holders.py`, `pipeline/src/advisor/training/holders_history.py`
- Modify: `pipeline/src/advisor/collectors/sec_13f.py`. `parse_listing` also matches the ledger's older file-name pattern, and `aggregate` tolerates a missing `FIGI` or `AMENDMENTTYPE` column.
- Test: `pipeline/tests/unit/test_model_holders.py`, `pipeline/tests/unit/test_training_holders_history.py`, `pipeline/tests/unit/test_sec_13f.py`

**Interfaces:**
- Consumes: `sec_13f.parse_listing`, `aggregate`, `save_quarter`, `load_quarter` and `Quarter.cusip_for`; `openfigi.FigiBook.lookup`.
- Produces:
  - `DataSet` gains `published: date | None`, read from the listing when it shows one (ledger).
  - `holders_history.holders_history(quarters: Sequence[tuple[DataSet, Quarter]], cusips: Mapping[str, str]) -> pd.DataFrame`, written as `holders.parquet`: `symbol, cusip, period, known, shares, holders`.
    - `known = max(period + 45 days, published or window end + 30 days)`.
    - `cusips` maps symbol → CUSIP. It is found once, from the newest quarter's FIGI votes (as live), and used for every quarter.
  - `holders.HOLDERS_FEATURES = ["holder_count_chg", "inst_shares_chg"]`.
  - `holders.holders_features(quarters: pd.DataFrame | None, shares: pd.DataFrame, splits, days, symbols) -> dict[str, pd.DataFrame]`.
- Rules:
  - On day D, take the symbol's latest quarter known before D, and the quarter whose period ends 80–100 days earlier (also known before D).
  - `holder_count_chg` = holders − previous holders.
  - `inst_shares_chg` = (shares × `_split_at(period)` − previous shares × `_split_at(previous period)`) / `shares`.
  - Both are NaN without the pair.

- [ ] **Step 1: Write the failing tests.**
  - `test_a_quarter_counts_from_45_days_after_its_end_or_its_publication`: period 2025-03-31 published 2025-05-30 is read from 2025-05-31.
  - `test_changes_need_the_previous_quarter`
  - `test_a_split_between_quarters_is_not_a_change_in_shares`
  - `test_a_symbol_without_a_cusip_reads_missing`
  - In `test_sec_13f.py`: `test_the_listing_reads_quarterly_file_names_too` and `test_a_data_set_without_figis_still_totals_its_holdings`.
- [ ] **Step 2: Run them and see them fail.** `bash pipeline/scripts/in-docker.sh uv run pytest tests/unit/test_model_holders.py tests/unit/test_training_holders_history.py tests/unit/test_sec_13f.py -q`
- [ ] **Step 3: Implement.** The build reuses `Sec13f._quarter`'s download, reduce and save path; Task 9 points its folder at the history cache.
- [ ] **Step 4: Run them; all pass.**
- [ ] **Step 5: Commit.** `feat: 13F holder history and features`

### Task 7: `estimates` — Yahoo earnings dates, consensus and reported EPS

**Files:**
- Create: `pipeline/src/advisor/model/estimates.py`
- Modify: `pipeline/src/advisor/training/yahoo_history.py`
- Test: `pipeline/tests/unit/test_model_estimates.py`, `pipeline/tests/unit/test_training_yahoo_history.py`

**Interfaces:**
- Consumes: `yfinance_earnings.parse_earnings` (one report per ET day; the reported row wins).
- Produces:
  - `yahoo_history.estimates_history(symbols, load: Callable[[str], pd.DataFrame | None], limiter) -> pd.DataFrame`. The loader calls `get_earnings_dates(limit=100)`. Written as `earnings_estimates.parquet`: `symbol, report_day (ET date), eps_estimate, eps_actual`.
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
  - `test_the_history_keeps_reported_and_scheduled_rows`: a fake loader.
- [ ] **Step 2: Run them and see them fail.** `bash pipeline/scripts/in-docker.sh uv run pytest tests/unit/test_model_estimates.py tests/unit/test_training_yahoo_history.py -q`
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them; all pass.**
- [ ] **Step 5: Commit.** `feat: earnings estimate history and features`

### Task 8: `catalysts` — openFDA approvals and recalls (last priority)

**Files:**
- Create: `pipeline/src/advisor/model/catalysts.py`, `pipeline/src/advisor/training/fda_history.py`
- Test: `pipeline/tests/unit/test_model_catalysts.py`, `pipeline/tests/unit/test_training_fda_history.py`

**Interfaces:**
- Consumes: `openfda.approvals` (the counted kinds), `openfda.fda_date`, `APPROVALS_URL`, `RECALLS_URL` and `OPENFDA_PER_MINUTE`; `sponsors.SponsorMatcher`.
- Produces:
  - `fda_history.fda_history(client, names: Mapping[str, str], since: date, limiter) -> pd.DataFrame`, written as `fda_events.parquet`: `symbol, kind ("approval" | "recall"), day, event_id`.
    - Source: the bulk files from `download.json` if the ledger confirms them. Otherwise the search API, one request pair per calendar quarter, paged by `PAGE = 1000`.
    - Approvals: the `original` and `new_indication` kinds only (`new_molecule` is a subset of `original`).
    - Recalls: one row per distinct `event_id`.
    - Names are the directory names of the whole US universe (`SponsorMatcher(names)`).
  - `catalysts.CATALYSTS_FEATURES = ["fda_approvals_180d", "fda_recalls_90d"]`, with `FDA_LAG_DAYS = 7`.
  - `catalysts.catalysts_features(events: pd.DataFrame | None, days, symbols) -> dict[str, pd.DataFrame]`. `known = day + FDA_LAG_DAYS`. Symbols without events read 0 when `events` is not None.

- [ ] **Step 1: Write the failing tests.**
  - `test_an_approval_counts_a_week_after_its_date_for_180_days`
  - `test_one_recall_event_listing_three_products_counts_once`
  - `test_every_symbol_reads_zero_without_events_and_missing_without_the_source`
  - `test_the_history_matches_sponsor_names_against_the_whole_universe`: two universe names sharing a key give no match, as the `SponsorMatcher` rules say.
- [ ] **Step 2: Run them and see them fail.** `bash pipeline/scripts/in-docker.sh uv run pytest tests/unit/test_model_catalysts.py tests/unit/test_training_fda_history.py -q`
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them; all pass.**
- [ ] **Step 5: Commit.** `feat: openFDA catalyst history and features`

### Task 9: the build writes the histories (groups, cache, threads, workflows)

**Files:**
- Create: `pipeline/src/advisor/training/history.py`
- Modify: `pipeline/src/advisor/training/build.py`, `.github/workflows/benchmark.yml`, `.github/workflows/train.yml`
- Test: `pipeline/tests/unit/test_training_history.py`, `pipeline/tests/unit/test_training_build.py`, `pipeline/tests/unit/test_benchmark_workflow.py`

**Interfaces:**
- Consumes: every history function from Tasks 2–8.
- Produces:
  - `history.SOURCES: dict[str, tuple[str, ...]]`, each group's Parquet files:
    - `short`: `short_interest.parquet`, `short_volume.parquet`
    - `analyst`: `analyst_events.parquet`
    - `events`: `material_events.parquet`, `large_holders.parquet`
    - `insider`: `insider_trades.parquet`
    - `holders`: `holders.parquet`
    - `estimates`: `earnings_estimates.parquet`
    - `catalysts`: `fda_events.parquet`
    - `earnings` needs only `fundamentals.parquet`.
  - `history.HistoryCache(root: Path)`, with `get(kind: str, key: str) -> pd.DataFrame | None` and `put(kind, key, frame) -> None` (zstd Parquet under `root/kind/key.parquet`). It holds only pieces that never change: FINRA files older than 90 days, past insider quarters, and 13F data-set totals (the `Sec13f` folder). `submissions.zip`, Yahoo and openFDA are always fetched.
  - `history.build_history(out: Path, groups: frozenset[str], deps: HistoryDeps, tickers: pd.DataFrame, facts_ciks: set[int], symbols: list[str], names: Mapping[str, str], since: date, manifest: dict) -> None`:
    - It writes each wanted group's files and records `manifest["seconds"][f"history_{group}"]` for each group.
    - A failing group is recorded in `manifest["unavailable"][group]` and its files are not written. The build goes on, as it does for macro.
    - Groups run in two threads: Yahoo (`analyst`, `estimates`) and everything else, in the spec's priority order (`catalysts` last).
  - A `HistoryDeps` dataclass: the clients, `SecEdgar`, the limiters, the Yahoo loaders, `FigiBook`, and `cache: HistoryCache | None`. `BuildDeps.history: HistoryDeps | None = None`; None means no history step, so today's tests keep passing.
  - CLI options:
    - `--groups`: `all` (the default), `accepted`, `none`, or a comma list. `accepted` reads `repo.active_config(conn, "US")` and builds the groups its `ModelConfig` turns on.
    - `--history-cache DIR`.
    - History starts at `history_start(start, years=1)`, or at the source's first date if that is later.
  - Workflows:
    - Both workflows restore and save `${{ runner.temp }}/history-cache` with `actions/cache/restore@v4` and `actions/cache/save@v4`, key `history-${{ github.run_id }}`, restore-keys `history-`. Both pass `--history-cache "$RUNNER_TEMP/history-cache"`.
    - `train.yml` passes `--groups accepted`.
    - `benchmark.yml` builds all groups.

- [ ] **Step 1: Write the failing tests.**
  - In `test_training_history.py`:
    - `test_each_wanted_group_writes_its_files_and_seconds`
    - `test_a_failing_group_is_recorded_and_the_others_still_write`
    - `test_a_cached_finra_file_is_not_fetched_again`: a fake client counts the requests.
    - `test_accepted_builds_only_the_groups_of_the_us_config`: a stored v6 config with `short=True` gives `{"short"}`; with none stored, the set is empty.
  - In `test_training_build.py`: `test_a_build_without_history_deps_writes_what_it_wrote_before`.
  - In `test_benchmark_workflow.py`: `test_both_workflows_keep_the_history_cache_and_train_builds_only_accepted_groups`. It asserts `history-cache` and `--history-cache` in both files, and `--groups accepted` in `train.yml` but not in `benchmark.yml`. The two timeout assertions stay.
- [ ] **Step 2: Run them and see them fail.** `bash pipeline/scripts/in-docker.sh uv run pytest tests/unit/test_training_history.py tests/unit/test_training_build.py tests/unit/test_benchmark_workflow.py -q`
- [ ] **Step 3: Implement:**
  - `history.py`.
  - The build step after `fundamentals` (`build.py:174-192`), which needs `tickers` and the facts' CIKs.
  - The real `HistoryDeps` in `main()`, with names from the `NasdaqSymbols` infos.
  - The workflow edits.
- [ ] **Step 4: Run them and the whole unit suite.** `bash pipeline/scripts/in-docker.sh uv run pytest tests/unit -q` and `bash pipeline/scripts/in-docker.sh uv run ruff check .` — clean.
- [ ] **Step 5: Commit.** `feat: the training build writes the US data group histories`

### Task 10: training reads the groups (dataset and config)

**Files:**
- Modify: `pipeline/src/advisor/model/groups.py`, `pipeline/src/advisor/model/dataset.py` (`MarketData`, `feature_frames` at lines 232-273, `load_market` at 276-325), `pipeline/src/advisor/model/variants.py`
- Test: `pipeline/tests/unit/test_model_dataset.py`, `pipeline/tests/unit/test_model_variants.py`, `pipeline/tests/unit/test_model_groups.py`

**Interfaces:**
- Consumes: the feature functions and lists from Tasks 2–8; Task 9's `history.SOURCES`.
- Produces:
  - `groups.GroupHistory`, a frozen dataclass whose fields are all `pd.DataFrame | None = None`: `short_interest, short_volume, analyst_events, analyst_coverage, material_events, large_holders, insider_trades, holders, estimates, fda_events`.
  - `groups.DATA_GROUPS = ("short", "analyst", "insider", "events", "holders", "earnings", "estimates", "catalysts")`.
  - `groups.GROUP_FEATURES: dict[str, list[str]]`, with earnings → `EARNINGS_FEATURES`.
  - `groups.ALL_GROUP_FEATURES`: the lists concatenated, in that order.
  - `groups.LETTERS = {"short": "s", "analyst": "a", "insider": "i", "events": "v", "holders": "h", "earnings": "e", "estimates": "t", "catalysts": "c"}`.
  - `groups.load_history(data_dir: Path) -> GroupHistory` reads the files that exist and builds `analyst_coverage` with `analyst.coverage`.
  - `groups.present(history: GroupHistory) -> frozenset[str]`: the groups whose every source frame is present. `earnings` is always present for US.
  - `groups.group_features(history: GroupHistory, facts, tickers, split_adjusted: pd.DataFrame, splits, days, symbols) -> dict[str, pd.DataFrame]`: every name in `ALL_GROUP_FEATURES` except the four earnings names, with NaN frames for absent sources.
  - `feature_frames(..., history: GroupHistory | None = None)`. US adds `group_features`; TSX gets NaN frames for every new name. `extras = EXTRA_FEATURES + ALL_GROUP_FEATURES` (the earnings names are already among them).
  - `MarketData.groups: frozenset[str] = frozenset()`. `load_market` passes `load_history(data_dir)` for US and sets `groups = present(...)`.
  - `ModelConfig` gains `short, analyst, insider, events, holders, estimates, catalysts: bool = False`. `CONFIG_VERSION = 6`; `_KEYS[6]` is version 5's keys plus the seven new ones. `to_json` and `from_json` carry them.
  - `ModelConfig.name` lists its parts in the order `factors, garch, ranker, forest, extras`, then `DATA_GROUPS` in order, then `bagged`. If that name passes 40 characters, the data groups become one `data` part followed by each group's letter: `garch+ranker+forest+data+s+a+i+v+h+e+t+c`, exactly 40.
  - `variants.data_groups(config) -> tuple[str, ...]`.
  - `extra_features` returns the market extras when `extras` is on, and each group's features for each group that is on.
  - `variants.missing_groups(data, config) -> list[str]`: the groups the config needs that `data.groups` lacks. `extra_features` raises `ValueError(f"{config.name} needs the {group} data, which this build did not write")` for the first one.

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
- In `test_model_dataset.py`:
  - `test_us_rows_carry_every_group_column_and_tsx_reads_them_missing`
  - Update `test_training_rows_carry_the_extras_but_the_baseline_names_do_not_change` to `(*EXTRA_FEATURES, *ALL_GROUP_FEATURES)`.
  - `test_load_market_records_which_groups_were_built`: writing only `short_interest.parquet` and `short_volume.parquet` gives `{"short", "earnings"}`.

- [ ] **Step 2: Run them and see them fail.** `bash pipeline/scripts/in-docker.sh uv run pytest tests/unit/test_model_variants.py tests/unit/test_model_dataset.py tests/unit/test_model_groups.py -q`
- [ ] **Step 3: Implement.** `train.py` and `live.py` need no edit: the columns arrive through `extra_features` (`train._feature_list` at line 394), as they did for earnings.
- [ ] **Step 4: Run the whole unit suite and ruff.** All pass.
- [ ] **Step 5: Commit.** `feat: configs and training rows for the US data groups`

### Task 11: live features from the collectors

**Files:**
- Create: `pipeline/src/advisor/model/live_groups.py`
- Modify:
  - `pipeline/src/advisor/model/live.py` (`live_features`, `_day_row`)
  - `pipeline/src/advisor/run.py` (`model_features` at line 339, `forecast_market` at line 408)
  - The collectors `finra_short_interest.py`, `finra_short_volume.py`, `yfinance_analyst.py`, `sec_insiders.py` and `openfda.py`
- Test: `pipeline/tests/unit/test_model_live.py`, `pipeline/tests/unit/test_model_live_groups.py`, `pipeline/tests/unit/test_run_model.py`, and the five collectors' test files

**Interfaces:**
- Consumes: Task 10's `GroupHistory` and `group_features` (through `feature_frames`).
- Produces:
  - `live_features(..., history: GroupHistory | None = None)` and `model_features(..., history=None)` pass it on to `feature_frames`.
  - `live_groups.history_from_records(results: Mapping[str, CollectorResult], today: date) -> GroupHistory`. A source whose result is missing or not `CollectorStatus.OK` gives None. Each frame has the training file's columns. The sources are:
    - `finra_short_interest`, `finra_short_volume`, `yfinance_analyst`, `sec_8k`, `sec_13dg` and `yfinance_earnings`.
    - `sec_form4`: only `derivative=False` trades with codes P or S.
    - `sec_13f`: two rows per record, the latest and the previous quarter, both with `known = today − 1 day`.
    - `openfda`.
  - `forecast_market` passes `history_from_records(results, today)` for US.
  - Collector changes (the spec's lookbacks and caps):
    - `FinraShortInterest.fetch` returns the newest two published settlements, because the newest may not be 12 sessions old yet.
    - `FinraShortVolume.fetch` returns the last `VOLUME_SESSIONS = 20` published days, with `LOOKBACK_WEEKDAYS = 30`.
    - `YFinanceAnalyst.max_symbols = 600`, which covers 300 US and 100 TSX shortlisted stocks plus holdings. `AnalystView` gains three fields:
      - `events: list[RatingEvent]`: the last 365 days, plus the latest downgrade.
      - `oldest_event: datetime | None`.
      - `event_count: int = 0`.

      `RatingEvent` has `graded_at, firm, action, from_grade, to_grade, price_target_action`.
    - `sec_insiders.LOOKBACK = timedelta(days=180)`. `MAX_DOCUMENTS` stays 1000: the new Form 4s for about 300 symbols in steady state are far fewer, and a run that runs out is PARTIAL, so the group is NaN for that run.
    - `openfda.WINDOW_DAYS = 180`. Matching uses every US name in `CompanyNames`, as training does. `DrugEvents` gains `approval_days: list[date]` (original and new-indication approvals) and `recall_days: dict[str, date]` (event id → report date). Records are kept only for the requested symbols.
    - `sec_events.LOOKBACK` (120), `sec_holders.LOOKBACK` (365), `sec_13f` and `yfinance_earnings.REPORTS` (12) already cover the windows, so they do not change.

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
    assert history_from_records(results, date(2026, 11, 19)).insider_trades is None
```

Also add:
- `test_records_become_the_training_layout`, one per source: the frame equals its Task's file layout.
- `test_trimmed_analyst_records_give_the_full_history_features`: the features from `AnalystView.events` equal the features from the full event list on the same day.
- In the collector tests:
  - `test_fetch_returns_the_two_newest_published_settlements`
  - `test_fetch_returns_twenty_days_of_short_volume`
  - `test_the_analyst_cap_covers_the_forecast_set` (`max_symbols >= 400`)
  - `test_insider_lookback_covers_180_days`
  - `test_openfda_matches_against_every_us_name_and_lists_dates`
- In `test_run_model.py`: `test_forecast_market_passes_the_group_history_for_us_only`.

- [ ] **Step 2: Run them and see them fail.** `bash pipeline/scripts/in-docker.sh uv run pytest tests/unit/test_model_live.py tests/unit/test_model_live_groups.py tests/unit/test_run_model.py tests/unit/test_finra_short_interest.py tests/unit/test_finra_short_volume.py tests/unit/test_yfinance_analyst.py tests/unit/test_sec_insiders.py tests/unit/test_openfda.py -q`
- [ ] **Step 3: Implement.** `AnalystView` and `DrugEvents` records cached before this change lack the new fields. Their defaults (`[]`, `0`) must let them load. Such a record yields no events, so the symbol's analyst features read NaN until the next fetch.
- [ ] **Step 4: Run the whole unit suite, the integration tests and ruff.** `bash pipeline/scripts/in-docker.sh uv run pytest -q` and `bash pipeline/scripts/in-docker.sh uv run ruff check .` — clean.
- [ ] **Step 5: Commit.** `feat: live runs compute the US data group features from the collectors`

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
    - A row whose `missing_groups` is not empty gets `{"status": "no data", "groups": [...]}` and no decision.
    - If the active config's name is not among this market's rows and it can run on this data, it runs as one more row, so the incumbent rule still applies.
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
- In `tests/integration/test_benchmark_job.py`:
  - `test_the_combined_row_runs_when_two_groups_pass`: monkeypatch `ABLATIONS` to the baseline, the base and two group rows on synthetic data, with `choose_model` patched to pass them.
  - `test_an_active_config_without_a_row_is_still_scored`.

- [ ] **Step 2: Run them and see them fail.** `bash pipeline/scripts/in-docker.sh uv run pytest tests/unit/test_benchmark_rows.py tests/unit/test_benchmark_accept.py tests/unit/test_benchmark_report.py -q`
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the whole suite and ruff.** `bash pipeline/scripts/in-docker.sh uv run pytest -q` (with `advisor-pg` up) and `bash pipeline/scripts/in-docker.sh uv run ruff check .` — clean.
- [ ] **Step 5: Measure on real data.**
  1. Build once with every group, with `SEC_USER_AGENT` exported as in Task 0: `bash pipeline/scripts/in-docker.sh uv run python -m advisor.training.build --out .cache/train-7b --no-db --history-cache .cache/history-7b`. Read `manifest.json` `seconds` for the first build.
  2. Run the build again (warm cache) and read the steady-state seconds.
  3. Time one row: a one-off `uv run python -c` that loads `load_market(Path(".cache/train-7b"), Market.US, with_factors=True, with_garch=True)` and times `run_variant` for `garch+ranker+forest+short`.
  4. Write the projection (Task 0's formula with these numbers) into the Task 0 ledger. If either job passes 80%, stop and report to the owner before committing.
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
- `test_schema.py` gains `test_features_live_rows_are_kept_with_their_run`: no prune path deletes them.

- [ ] **Step 1: Write the failing tests.**
  - `test_option_summaries_are_stored_with_the_run`: a fake `yfinance_options` result for `AAPL` gives a `features_live` row with `opt_atm_iv_near == 0.24`.
  - `test_a_missing_option_value_is_left_out`
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.** Do not raise the 40-symbol cap here (run budget); the deferred entry says so.
- [ ] **Step 4: Run the unit and integration suites; all pass.**
- [ ] **Step 5: Commit.** `feat: keep option summaries in features_live for a later test`

### Task 14: record the change

**Files:**
- Modify:
  - `docs/superpowers/deferred.md`: a new section, "Plans 7b–7d: every US data group".
  - `pipeline/README.md`: under Training, `--groups`, `--history-cache` and the new files.
  - `README.md`: no change, since no new secret or migration is needed.

- [ ] **Step 1: Add the deferred entries:**
  - FINRA re-issues files, so the short-interest history holds revised values. This is a small look-ahead that cannot be removed.
  - Yahoo shows the final consensus before each report.
  - A structured SCHEDULE 13D/G whose issuer CIK does not match is dropped live but counted in training, because training reads filing lists, not documents.
  - Matching sponsor names against the whole universe is noisier than the old shortlist-only matching.
  - News features become testable after about 12 months of stored runs (from 2026-11), and option summaries about 12 months after Task 13 merges. Both samples are the forecast shortlist (300 US stocks plus holdings, with options capped at 40 a run), not every stock, so a test must read them with care.
  - The first benchmark after the merge pays for the whole history download (the ledger's first-build minutes); later benchmarks read the cache.
  - The live run time added by Task 11.
- [ ] **Step 2: Update `pipeline/README.md`** with the two build options and the history files.
- [ ] **Step 3: Commit.** `docs: plan 7b–7d, every US data group` (this plan, `deferred.md` and `pipeline/README.md`).
- [ ] **Step 4: Tell the owner** to run `benchmark.yml` (workflow_dispatch) to see the "Did the new data help?" tables. Nothing is pushed.
