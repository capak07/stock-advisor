# Plan 6k: Earnings Features Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an optional, point-in-time `earnings` feature group (quarter-over-year-ago growth, margin change, a self-derived earnings surprise, days since the report) and one benchmark row `ranker+earnings`.

**Architecture:** A pure function in `model/fundamentals.py` (or a sibling `model/earnings.py`) builds wide day × symbol frames from the same first-reported XBRL facts the fundamentals use. `dataset.feature_frames` adds them to the optional columns (like `EXTRA_FEATURES`), training joins them when `ModelConfig.earnings` is on, live prediction computes them through the shared path, and the benchmark runs one new row.

**Tech Stack:** Python 3.12, pandas, numpy, LightGBM, pytest.

**Spec:** `docs/superpowers/specs/2026-11-10-earnings-features-design.md`

## Global Constraints

- Features (exact names): `rev_growth_q`, `op_margin_q_chg`, `sue`, `days_since_report`.
- Point-in-time: a day reads only facts with `filed` strictly before it (`allow_exact_matches=False`, as `fundamentals.py`); first-reported values, best-priority concept (`first_reported`); values whose quarter ended more than `STALE_DAYS` (548) before the day are NaN.
- Quarter = 80–100 day duration; fiscal Q4 = fiscal-year value (350–380 days) − the 9-month YTD ending inside it, known when the later of the two was filed.
- Year-ago quarter = the quarter whose end is 365 ± 20 days before; `sue` needs ≥ 4 prior year-over-year EPS changes (uses up to 8), std > 0, clipped to ±5; `days_since_report` capped at 120; `op_margin_q_chg` in percentage points.
- US only; TSX and crypto rows NaN; no `earnings` ablation row for TSX or crypto.
- `ModelConfig.earnings: bool = False`; `CONFIG_VERSION = 4` with `_KEYS[4]` adding "earnings"; versions 1–3 load with it off; `name` includes "earnings" in its parts order after "extras".
- One new ablation row `"ranker+earnings": ModelConfig(ranker=True, earnings=True)` before `"full+policy"`.
- Live and training share the feature code (the existing parity test in `tests/unit/test_model_live.py` must keep passing and cover the new group).
- No change to the baseline, accepted configs, Picks, acceptance rule, or the US/TSX/crypto existing rows.
- Python tests via `pipeline/scripts/in-docker.sh`; `ruff check .` passes; LF line endings.

## Review Focus

1. A company with a non-December fiscal year (e.g. AAPL, September): Q4 derivation and year-ago matching by period end.
2. A restated quarter: the first-reported value is used (no look-ahead).
3. A day exactly on a filing date: the filing is not yet known that day.
4. A company with fewer than 4 prior year-over-year changes: `sue` NaN, the others still computed.
5. The benchmark time budget: one more US row (~430 s) must keep the projected US benchmark inside `benchmark.yml`'s limit.

---

### Task 1: The earnings feature frames

**Files:** Create `pipeline/src/advisor/model/earnings.py`; Test `pipeline/tests/unit/test_model_earnings.py`

**Interfaces — Produces:**
- `EARNINGS_FEATURES = ["rev_growth_q", "op_margin_q_chg", "sue", "days_since_report"]`
- `single_quarters(facts: pd.DataFrame) -> pd.DataFrame` — from `fundamentals.first_reported(...)` rows: columns `cik, metric, end, value, known` (known = filed of the fact, or the later of the FY and 9M facts for a derived Q4), metrics revenue, operating_income, eps_diluted.
- `earnings_features(facts: pd.DataFrame, tickers: pd.DataFrame, days: pd.DatetimeIndex, symbols: Sequence[str]) -> dict[str, pd.DataFrame]` — same signature and output shape as `fundamentals.fundamental_features` (check it and match its tickers/CIK join), one wide frame per name.

- [ ] **Step 1: Failing tests:** quarter from a 3-month fact; Q4 = FY − 9M; Sept fiscal year matches year-ago by end date; rev_growth_q and op_margin_q_chg values; sue with 8 prior changes (exact value), NaN with 3; clip at ±5; a day equal to the filed date does not see it, the next day does; days_since_report counts from known and caps at 120; restated value ignored (first reported kept); stale after 548 days.
- [ ] **Step 2: Run** `bash pipeline/scripts/in-docker.sh uv run pytest -q tests/unit/test_model_earnings.py` — FAIL.
- [ ] **Step 3: Implement.** **Step 4:** PASS. **Step 5: Commit** `feat: earnings feature frames`.

### Task 2: Config, dataset, training, live and the benchmark row

**Files:** Modify `pipeline/src/advisor/model/variants.py`, `dataset.py`, `train.py` (`_feature_list`), `live.py` if needed, `benchmark/job.py` (ABLATIONS, market filter); Tests: `tests/unit/test_model_variants.py` (or where ModelConfig is tested), `tests/unit/test_model_live.py`, `tests/unit/test_benchmark_job*.py`.

- [ ] **Step 1: Failing tests:** ModelConfig round-trip with earnings, version 3 loads with earnings False, name "ranker+earnings"; the dataset rows carry the four columns for US (NaN for TSX); a config with earnings trains on them and stores them in the model's feature list; live/training parity covers the new columns; ABLATIONS has "ranker+earnings" and it is not run for TSX or crypto.
- [ ] **Step 2: Run** — FAIL. **Step 3: Implement.** **Step 4:** the touched tests, then the FULL suite and `ruff check .` — PASS. Check the benchmark time projection (Plan 6g's cap in `benchmark.yml`/its tests) still holds with one more US row; if not, report it.
- [ ] **Step 5: Commit** `feat: earnings feature group and benchmark row`.
