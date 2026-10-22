# Plan 3b: The Stock Model and Its Backtest — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Each Saturday, `train.yml` trains one LightGBM stock model per market on Plan 3a's training data. It backtests the model walk-forward after costs, decides whether the market's picks may be shown, stores the model in Postgres, and promotes it only when its probabilities are honest and its ranking is no worse than the active model's.

**Architecture:**
- **A new package, `advisor.model`, with one module per step:**
  - `features`: price/volume and relative-strength features on wide (day × symbol) frames;
  - `fundamentals`: point-in-time US fundamentals;
  - `dataset`: one market's training rows;
  - `train`: walk-forward fits, calibration, the final model and its files;
  - `backtest`: the spec's pick rules after costs, and the gate;
  - `weekly`: the command `train.yml` runs.
- **Wide frames serve both paths.** Features are computed on wide frames, so Plan 3c can compute the same features for a live run from the last ~300 sessions.
- **Models live in Postgres** (owner's decision, 2026-10-21): a new `model_files` table holds each model's gzip-compressed files beside its `models` row. One market's model is about 6 MB.
- **Forecasts and picks are decided separately.** A promoted model forecasts for every holding and watched stock (Plans 3c and 4). Whether its market may show picks is a separate decision, stored in the model's metrics (spec §6.6).

**Tech Stack:** Python 3.12, pandas, numpy, LightGBM (new, MIT), SciPy's `isotonic_regression` (comes with LightGBM), pyarrow, psycopg; pytest; ruff.

**Spec:** `docs/superpowers/specs/2026-10-09-stock-advisor-design.md` (rev 2):
- §5.1 features, §5.2 base model;
- §6.1 qualifying, §6.2 hold time and §6.5 limits (the backtest simulates them);
- §6.6 disabling picks;
- §3 Markets (costs);
- §8 data model.

Also read `docs/superpowers/deferred.md`, "Plan 3", and Plan 3a (`docs/superpowers/plans/2026-10-20-plan-3a-training-history.md`), whose files this plan reads.

**Owner's decisions (2026-10-21), after the prototype:**
- **Build it with honest gates.** The prototype says US picks will likely stay off and TSX picks will be few. The model is still built, because holdings and the watchlist need its forecasts.
- **Macro levels are not stock-model features.** In the prototype they let the model time the market by date: picks bunched on a few days and swung from year to year. Spec §5.1 is updated (Task 8).
- **Trained models are kept in Postgres**, not the Actions cache.

**Prototype:** branch `plan-3b-proto` (commit `da6ecf6`, not for merging). It ran on 2,000 US and 676 TSX stocks over 8 years, with 4 walk-forward test periods after 2 training years.

| Measure | TSX | US |
|---|---|---|
| Training rows (every 10th session) | 46,364 | 193,216 |
| Fit time, 2 cores, 96 fits (6 horizons × 4 folds × 4 models) | 33 s | 135 s (about 7 min for the full universe) |
| Calibration error after isotonic, by horizon | 1.2–2.9 points | 1.6–4.2 points |
| Rank IC of q50 (same-day ranking) | 0.02–0.03 | 0.05–0.07 |
| Weekly top 10 by q50, after costs | +0.6% (10 days) to +10.2% (126 days) | −3.0% to −4.2% (the 3.1% currency round trip) |
| Picks meeting P ≥ 0.58 | rare | almost none |
| Model files (4 models, gzip) | 1.0 MB | 1.0 MB |

What the prototype taught, and this plan keeps:
- **Isotonic calibration overstates the tail.** A few extreme raw scores that happened to win were mapped to P ≈ 0.85–0.9, and those picks lost 13–20%. `Calibrator` clips to the hit rates that bins of at least 500 rows support.
- **Time.** Point-in-time fundamentals done one filing at a time took over 45 minutes. A vectorized "first reported" version takes 7 seconds.
- **The static sector label is out.** Today's sector applied to 8 years is a mild look-ahead, and it ranked first by importance. `sector_rank_63`, which moves with time, stays.
- **LightGBM needs `libgomp1`.** GitHub's runners have it; the slim Docker test image doesn't (Task 5).

## Global Constraints

- **Point in time** (spec design rule 3). A feature for day t uses nothing after t. A filing counts from the day after it was filed (`filed < day`). Training rows end a horizon before each test period (the embargo).
- **Never fabricate.** A figure a company doesn't report stays missing (NaN). LightGBM handles missing values.
- **Costs** (spec §3):
  - US: 2 × the USD conversion fee plus spread.
  - TSX: spread only.
  - Spread: 0.10% when 20-day dollar volume is at least 10M, else 0.30%.
  - The USD fee comes from `settings.usd_fx_fee_pct` (default 1.5).
  - The spec gives the US spread only as "plus spread"; this plan uses the TSX rule in USD.
- **Horizons** `(5, 10, 20, 21, 63, 126)` trading days. Swing is 5, 10 and 20; position is 21, 63 and 126 (spec R6, §5.2).
- **Tests run in Docker**, from `pipeline/`: `scripts/in-docker.sh uv run pytest -q` and `scripts/in-docker.sh uv run ruff check .`. Integration tests need the `advisor-pg` container.
- **Commits:**
  - Run `git commit` in a command of its own: a plugin hook mistakes any `-n` in the same command for skipping hooks.
  - Never skip hooks.
  - End messages with the `Co-Authored-By:` trailer.
- **Never put a real email address** in code, tests or docs.

## Review Focus

1. **Look-ahead.** A feature that reads a later bar, or a filing on its filing day, inflates the backtest silently. Covered by:
   - Task 2, `test_features_on_a_day_ignore_everything_after_it`;
   - Task 3, `test_a_filing_counts_from_the_next_day`.
2. **Overlapping training and test labels.** A training row's target window must end before its test period starts. Covered by Task 5, `test_training_rows_end_a_horizon_before_the_test_period`.
3. **Overconfident probabilities**, as in the prototype: a stated P must be a hit rate that enough history supports. Covered by:
   - Task 5, `test_calibration_never_claims_more_than_the_data_supports`;
   - Task 6, `test_the_gate_needs_enough_profitable_honestly_calibrated_picks` (stated against observed for the picks themselves).
4. **Splits.** Prices are adjusted to today's shares, while filed share counts and EPS are not. P/E-style ratios and the $1 filter must use like with like. Covered by:
   - Task 2, `test_as_traded_undoes_yahoos_split_and_dividend_adjustment`;
   - Task 3, `test_a_split_after_the_filing_keeps_market_cap`.
5. **A bad week mustn't replace a good model.** A worse or failed training keeps the active model, and one market's failure doesn't stop the other. Covered by Task 7: `test_a_worse_model_is_stored_but_the_active_one_stays` and `test_a_market_that_fails_to_train_is_reported_and_the_rest_carry_on`.

**Known limits** (recorded in `deferred.md`, Task 8):
- **Survivorship bias** inflates every backtest number (spec §5.2).
- **The US currency round trip** (3.1%) is larger than the model's US edge.
- **No "surprise" feature yet.** It needs single-quarter EPS.
- **The non-common instruments** in deferred.md are still in the training data.

## Files

| File | Task | What it is |
|---|---|---|
| `supabase/migrations/0008_model_files.sql`, `pipeline/src/advisor/store/repo.py`, `pipeline/src/advisor/models.py` + `tests/integration/test_repo.py`, `tests/integration/test_schema.py` | 1 | Model storage and settings |
| `pipeline/src/advisor/model/__init__.py`, `features.py` + `tests/unit/test_model_features.py` | 2 | Price/volume and relative strength |
| `pipeline/src/advisor/model/fundamentals.py` + `tests/unit/test_model_fundamentals.py` | 3 | Point-in-time US fundamentals |
| `pipeline/src/advisor/model/dataset.py`, `pipeline/tests/model_data.py` + `tests/unit/test_model_dataset.py` | 4 | One market's training rows; synthetic training data for tests |
| `pipeline/pyproject.toml`, `uv.lock`, `pipeline/scripts/test-image.Dockerfile`, `pipeline/scripts/in-docker.sh`, `pipeline/src/advisor/model/train.py` + `tests/unit/test_model_train.py` | 5 | LightGBM, walk-forward, calibration, model files |
| `pipeline/src/advisor/model/backtest.py` + `tests/unit/test_model_backtest.py` | 6 | Picks after costs, the gate |
| `pipeline/src/advisor/model/weekly.py`, `pipeline/src/advisor/training/build.py`, `.github/workflows/train.yml` + `tests/unit/test_model_weekly.py`, `tests/integration/test_model_weekly.py`, `tests/unit/test_training_build.py` | 7 | The weekly command, promotion, the job |
| `docs/superpowers/specs/2026-10-09-stock-advisor-design.md`, `docs/superpowers/deferred.md`, `pipeline/README.md` | 8 | Docs |

---

### Task 1: Store models and their files

**Files:**
- Create: `supabase/migrations/0008_model_files.sql`
- Modify: `pipeline/src/advisor/models.py` (add `StoredModel`), `pipeline/src/advisor/store/repo.py`
- Test: `pipeline/tests/integration/test_repo.py`, `pipeline/tests/integration/test_schema.py`

**Interfaces:**
- Consumes: the `models` table (`version` primary key, `kind` in `stock_us`/`stock_tsx`/`crypto`, `trained_at`, `metrics` jsonb, `calibration_error`, `active`, and one active per kind), and the seeded `settings` row.
- Produces (Task 7 uses all of these):
  - in `advisor.models`: `@dataclass(frozen=True) class StoredModel`, with `version: str`, `kind: str`, `trained_at: datetime`, `metrics: dict[str, Any]`, `calibration_error: float | None`, `active: bool`;
  - in `advisor.store.repo`:
    - `save_model(conn, version: str, kind: str, trained_at: datetime, metrics: Mapping[str, Any], calibration_error: float | None, files: Mapping[str, bytes]) -> None`, which inserts it inactive with its files, in one transaction;
    - `active_model(conn, kind: str) -> StoredModel | None`;
    - `activate_model(conn, kind: str, version: str) -> None`. In one transaction it retires the kind's active model and activates `version`, and it raises `ValueError(f"no {kind} model {version}")` when there is no such row;
    - `load_model_files(conn, version: str) -> dict[str, bytes]`;
    - `prune_models(conn, kind: str, keep: int = 2) -> int`. It keeps the active model plus the newest by `trained_at` until `keep` remain, deletes the rest (their files go by cascade), and returns how many it deleted;
    - `fee_settings(conn) -> tuple[float, float]`, which returns `(usd_fx_fee_pct, crypto_fee_pct)` as floats in percent.

- [ ] **Step 1: Write the failing tests**

Append to `pipeline/tests/integration/test_repo.py` (add `import pytest` and `from datetime import UTC, datetime` if absent):

```python
def test_a_saved_model_is_inactive_until_activated_and_keeps_its_files(db):
    trained = datetime(2026, 10, 24, 11, 0, tzinfo=UTC)
    files = {"h5_q50": b"\x1f\x8bmodel", "meta": b"{}"}
    repo.save_model(db, "stock_tsx-202610241100", "stock_tsx", trained, {"mean_rank_ic": 0.02}, 2.5, files)
    assert repo.active_model(db, "stock_tsx") is None
    repo.activate_model(db, "stock_tsx", "stock_tsx-202610241100")
    active = repo.active_model(db, "stock_tsx")
    assert (active.version, active.metrics, active.calibration_error, active.trained_at, active.active) == (
        "stock_tsx-202610241100", {"mean_rank_ic": 0.02}, 2.5, trained, True,
    )
    assert repo.load_model_files(db, "stock_tsx-202610241100") == files


def test_activating_a_model_retires_only_its_kinds_old_one(db):
    at = datetime(2026, 10, 24, tzinfo=UTC)
    for version, kind in (("us-1", "stock_us"), ("us-2", "stock_us"), ("tsx-1", "stock_tsx")):
        repo.save_model(db, version, kind, at, {}, 1.0, {})
    repo.activate_model(db, "stock_us", "us-1")
    repo.activate_model(db, "stock_tsx", "tsx-1")
    repo.activate_model(db, "stock_us", "us-2")
    assert repo.active_model(db, "stock_us").version == "us-2"
    assert repo.active_model(db, "stock_tsx").version == "tsx-1"
    with pytest.raises(ValueError, match="no stock_tsx model us-1"):
        repo.activate_model(db, "stock_tsx", "us-1")


def test_pruning_keeps_the_active_model_and_the_newest_others(db):
    for i in range(4):
        repo.save_model(db, f"us-{i}", "stock_us", datetime(2026, 10, 1 + i, tzinfo=UTC), {}, 1.0, {"meta": b"x"})
    repo.activate_model(db, "stock_us", "us-0")
    assert repo.prune_models(db, "stock_us", keep=2) == 2
    assert [r["version"] for r in db.execute("select version from models order by version")] == ["us-0", "us-3"]
    assert db.execute("select count(*) as n from model_files").fetchone()["n"] == 2  # files go with their model


def test_fee_settings_are_read_in_percent(db):
    assert repo.fee_settings(db) == (1.5, 2.0)
```

Append to `pipeline/tests/integration/test_schema.py`:

```python
def test_the_owner_reads_model_files_and_only_the_pipeline_writes_them(owned_db):
    owned_db.execute("insert into models (version, kind, trained_at) values ('v1', 'stock_tsx', now())")
    owned_db.execute("insert into model_files (version, name, body) values ('v1', 'meta', '\\x7b7d')")
    with acting_as(owned_db, "authenticated", OWNER):
        assert [r["name"] for r in owned_db.execute("select name from model_files").fetchall()] == ["meta"]
        assert owned_db.execute("delete from model_files").rowcount == 0
    with acting_as(owned_db, "authenticated", STRANGER):
        assert owned_db.execute("select * from model_files").fetchall() == []
    with acting_as(owned_db, "pipeline_rw"):
        assert owned_db.execute("update model_files set body = '\\x00'").rowcount == 1
    with pytest.raises(psycopg.errors.CheckViolation):
        owned_db.execute("insert into model_files (version, name, body) values ('v1', 'Bad Name', '\\x00')")
```

- [ ] **Step 2: Run them to verify they fail**

Run: `scripts/in-docker.sh uv run pytest -q tests/integration/test_repo.py tests/integration/test_schema.py -k "model or fee"`
Expected: FAIL. The repo functions don't exist (`AttributeError`), and `model_files` doesn't exist.

- [ ] **Step 3: Write the migration**

`supabase/migrations/0008_model_files.sql`:

```sql
-- Plan 3b: each trained stock model's files (gzip-compressed LightGBM text, calibration and
-- metadata), kept beside its `models` row (owner's decision, 2026-10-21: Postgres rather than
-- Storage or the Actions cache, so no new secret). About 6 MB a market; the weekly job keeps the
-- active model and one other per kind.
create table model_files (
  version text not null references models (version) on delete cascade,
  name text not null check (name ~ '^[a-z0-9_]{1,40}$'),
  body bytea not null,
  primary key (version, name)
);

alter table model_files enable row level security;
create policy owner_read on model_files for select to authenticated using ((select public.is_owner()));
create policy pipeline_write on model_files for all to pipeline_rw using (true) with check (true);
grant select, insert, update, delete on model_files to pipeline_rw;
```

- [ ] **Step 4: Add `StoredModel` and the repo functions** (signatures above)

Put them before `write_sectors` in `repo.py`.
- `metrics` is written with `Jsonb`, and `files` with `executemany` into `model_files`.
- `prune_models` deletes `where kind = %s and not active and version not in (the newest keep-1 inactive versions by trained_at)`. When the kind has no active model it keeps the newest `keep`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `scripts/in-docker.sh uv run pytest -q tests/integration/test_repo.py tests/integration/test_schema.py`
Expected: PASS. This includes `test_every_table_except_migrations_has_a_pipeline_policy` and `test_every_public_table_has_row_level_security`.

- [ ] **Step 6: Commit**

```bash
git add supabase/migrations/0008_model_files.sql pipeline/src/advisor/models.py pipeline/src/advisor/store/repo.py pipeline/tests/integration/test_repo.py pipeline/tests/integration/test_schema.py
```
```bash
git commit -m "feat: store trained models and their files in Postgres"
```

---

### Task 2: Price/volume and relative-strength features

**Files:**
- Create: `pipeline/src/advisor/model/__init__.py` (docstring only), `pipeline/src/advisor/model/features.py`
- Test: `pipeline/tests/unit/test_model_features.py`

**Interfaces:**
- Consumes: `advisor.prices.JUMP_LIMIT` (0.5); and from `advisor.screener`, `MIN_PRICE` (1.0), `MIN_DOLLAR_VOLUME` (1e6), `ADV_WINDOW` (20) and `MIN_HISTORY_DAYS` (60).
- Produces, in `advisor.model.features` (Tasks 3–5 use these):
  - `HORIZONS = (5, 10, 20, 21, 63, 126)`;
  - `PRICE_FEATURES = ["ret_5", "ret_21", "ret_63", "ret_126", "mom_12_1", "rsi_14", "atr_14_pct", "vol_20", "vol_60", "dist_52w_high", "dist_52w_low", "volume_z", "gap", "jump_5d", "log_adv20"]`;
  - `RS_FEATURES = ["ex_bench_21", "ex_bench_63", "ex_sector_21", "ex_sector_63", "sector_rank_63"]`;
  - `@dataclass(frozen=True) class Wide`, with fields `open, high, low, close, volume: pd.DataFrame`. Each frame is indexed by a `DatetimeIndex` named `day`, with one column per symbol;
  - `to_wide(prices: pd.DataFrame) -> Wide`, from Plan 3a's long `symbol, day, open, high, low, close, volume`;
  - `split_factor(index: pd.DatetimeIndex, columns: Sequence[str], events: pd.DataFrame) -> pd.DataFrame`, the product of split ratios strictly after each day (1 where none);
  - `as_traded(wide: Wide, events: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]`, which returns `(split_adjusted_close, traded_close)`;
  - `jump_days(close: pd.DataFrame) -> pd.DataFrame` (bool);
  - `price_features(wide: Wide, dollar_volume: pd.DataFrame, jumps: pd.DataFrame) -> dict[str, pd.DataFrame]`, keyed by `PRICE_FEATURES`;
  - `relative_strength(features: Mapping[str, pd.DataFrame], benchmark: str, etf_of: Mapping[str, str], etfs: Sequence[str]) -> dict[str, pd.DataFrame]`, keyed by `RS_FEATURES`;
  - `forward_excess(close: pd.DataFrame, benchmark: str, horizons: Sequence[int] = HORIZONS) -> dict[int, pd.DataFrame]`;
  - `eligible(traded_close: pd.DataFrame, dollar_volume: pd.DataFrame) -> pd.DataFrame` (bool).

- [ ] **Step 1: Write the failing tests**

`pipeline/tests/unit/test_model_features.py`:

```python
import numpy as np
import pandas as pd
import pytest

from advisor.model.features import (
    PRICE_FEATURES,
    Wide,
    as_traded,
    eligible,
    forward_excess,
    jump_days,
    price_features,
    relative_strength,
    to_wide,
)

DAYS = pd.bdate_range("2025-01-06", periods=320, name="day")


def wide(closes: dict[str, list[float]], volume: float = 1_000_000.0) -> Wide:
    n = len(next(iter(closes.values())))
    frame = pd.DataFrame(closes, index=DAYS[:n], dtype=float)
    return Wide(open=frame, high=frame, low=frame, close=frame, volume=frame * 0 + volume)


def inputs(closes: np.ndarray) -> tuple[Wide, pd.DataFrame, pd.DataFrame]:
    w = wide({"X": list(closes)})
    return w, w.close * w.volume, jump_days(w.close)


def test_the_long_frame_becomes_wide_frames_by_day_and_symbol():
    prices = pd.DataFrame({
        "symbol": ["A", "B", "A"], "day": [DAYS[0].date(), DAYS[0].date(), DAYS[1].date()],
        "open": [1.0, 2.0, 1.1], "high": [1.2, 2.2, 1.3], "low": [0.9, 1.9, 1.0], "close": [1.1, 2.1, 1.2],
        "volume": [100.0, 200.0, 300.0],
    })
    w = to_wide(prices)
    assert list(w.close.columns) == ["A", "B"] and w.close.index.name == "day"
    assert w.close.loc[DAYS[1], "A"] == 1.2 and np.isnan(w.close.loc[DAYS[1], "B"])


def test_as_traded_undoes_yahoos_split_and_dividend_adjustment():
    # Traded: 100, 100, then a 2:1 split (50), then a 1.00 dividend goes ex (49).
    # Yahoo's auto-adjusted closes are all 49.
    w = wide({"X": [49.0, 49.0, 49.0, 49.0]})
    events = pd.DataFrame({
        "symbol": ["X", "X"], "day": [DAYS[2].date(), DAYS[3].date()], "dividend": [0.0, 1.0], "split": [2.0, 0.0],
    })
    split_adjusted, traded = as_traded(w, events)
    assert split_adjusted["X"].round(6).tolist() == [50.0, 50.0, 50.0, 49.0]
    assert traded["X"].round(6).tolist() == [100.0, 100.0, 50.0, 49.0]


def test_jump_days_follow_the_live_rule():
    w = wide({"X": [10, 10.2, 30, 10.3, 10.1, 25, 26, 27]})
    # 30 is a bad print (back to 10.3 next day); 25 starts a new level, so only its first day flags
    assert jump_days(w.close)["X"].tolist() == [False, False, True, False, False, True, False, False]


def test_price_features_on_a_steady_climb():
    climb = 50 * 1.01 ** np.arange(300)
    f = price_features(*inputs(climb))
    t = DAYS[299]
    assert f["ret_5"].loc[t, "X"] == pytest.approx(1.01**5 - 1)
    assert f["mom_12_1"].loc[t, "X"] == pytest.approx(1.01**231 - 1)
    assert f["rsi_14"].loc[t, "X"] == pytest.approx(100.0)
    assert f["vol_20"].loc[t, "X"] == pytest.approx(0.0, abs=1e-9)
    assert f["dist_52w_high"].loc[t, "X"] == pytest.approx(0.0)
    assert f["dist_52w_low"].loc[t, "X"] == pytest.approx(1.01**251 - 1)
    assert f["jump_5d"].loc[t, "X"] == 0.0
    assert f["log_adv20"].loc[t, "X"] == pytest.approx(np.log1p((climb[280:300] * 1e6).mean()))
    assert set(f) == set(PRICE_FEATURES)


def test_features_on_a_day_ignore_everything_after_it():
    rng = np.random.default_rng(3)
    base = 50 * np.exp(np.cumsum(rng.normal(0, 0.02, 320)))
    changed = base.copy()
    changed[300:] *= 3  # whatever happens later
    a, b = price_features(*inputs(base)), price_features(*inputs(changed))
    for name in PRICE_FEATURES:
        pd.testing.assert_series_equal(a[name]["X"].iloc[:300], b[name]["X"].iloc[:300], check_names=False)


def test_relative_strength_is_measured_against_the_benchmark_and_the_sector_etf():
    day = DAYS[:1]
    returns = {"X": [0.10], "Y": [0.02], "B": [0.03], "E": [0.05], "F": [0.01]}
    feats = {"ret_21": pd.DataFrame(returns, index=day), "ret_63": pd.DataFrame(returns, index=day)}
    rs = relative_strength(feats, "B", {"X": "E"}, ["E", "F"])  # Y has no sector ETF: its benchmark
    assert rs["ex_bench_21"].loc[day[0], "X"] == pytest.approx(0.07)
    assert rs["ex_sector_21"].loc[day[0], "X"] == pytest.approx(0.05)
    assert rs["ex_sector_21"].loc[day[0], "Y"] == pytest.approx(-0.01)
    assert rs["sector_rank_63"].loc[day[0], "X"] == 1.0  # E led the market's sector ETFs
    assert np.isnan(rs["sector_rank_63"].loc[day[0], "Y"])  # the benchmark isn't ranked


def test_the_target_is_the_forward_return_over_the_benchmarks():
    w = wide({"X": [10.0, 11.0, 12.0], "B": [100.0, 100.0, 110.0]})
    y = forward_excess(w.close, "B", (1,))[1]
    assert y["X"].iloc[0] == pytest.approx(0.1)
    assert y["X"].iloc[1] == pytest.approx(12 / 11 - 1 - 0.1)
    assert np.isnan(y["X"].iloc[2])
    assert (y["B"].dropna() == 0).all()


def test_eligibility_needs_a_dollar_a_million_a_day_and_sixty_sessions():
    w = wide({"OK": [5.0] * 80, "CHEAP": [0.9] * 80, "THIN": [5.0] * 80})
    dollar_volume = w.close * w.volume
    dollar_volume["THIN"] = 500_000.0
    ok = eligible(w.close, dollar_volume)
    assert ok["OK"].tolist() == [False] * 59 + [True] * 21
    assert not ok["CHEAP"].any() and not ok["THIN"].any()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `scripts/in-docker.sh uv run pytest -q tests/unit/test_model_features.py`
Expected: FAIL with `ModuleNotFoundError: advisor.model`.

- [ ] **Step 3: Implement `advisor.model.features`** (signatures above)

**Formulas** (c is the close, t the day):
- `ret_k = c/c.shift(k) − 1`;
- `mom_12_1 = c.shift(21)/c.shift(252) − 1`;
- RSI is Wilder's (`ewm(alpha=1/14, adjust=False, min_periods=14)`), written `100·up/(up+down)` so a steady climb reads 100;
- ATR is Wilder's average of the true range, divided by c;
- `vol_n` is the rolling std of daily log returns × √252;
- `dist_52w_high = c / high.rolling(252, min_periods=126).max() − 1` (low likewise);
- `volume_z` is (log1p volume − its mean over the previous 20 days) ÷ their std, clipped to ±10;
- `gap = open/c.shift(1) − 1`;
- `jump_5d` is 1.0 when any of the last 5 days is a jump day;
- `log_adv20 = log1p` of the 20-day mean dollar volume.

**Relative strength:**
- `ex_bench_k` is `ret_k` minus the benchmark column.
- `ex_sector_k` is `ret_k` minus the stock's ETF column. The ETF comes from `etf_of`; a symbol without one uses the benchmark.
- `sector_rank_63` is the ETF's percentile rank (`rank(pct=True)`) among `etfs` by `ret_63` that day. It is NaN when the stock's ETF is the benchmark.

**`as_traded`** inverts Yahoo's adjustment.
- yfinance's dividends are already in today's share scale, and its auto-adjusted prices are split-adjusted, then multiplied by `m_e = 1 − dividend_e / c_{e−1}` for every ex-date after the day.
- Recover per symbol, walking events newest to oldest with a running product `D` (start 1). For each dividend at ex-date e:
  - `m_e = 1 / (1 + dividend_e · D / adj_{e−1})`;
  - then `D *= m_e` for the days before e.
- The results are `split_adjusted = adj / D` and `traded = split_adjusted × split_factor`.

**`jump_days`** is `advisor.prices.find_jumps` per column. A day is flagged when its close is more than `JUMP_LIMIT` away from both the last unflagged close and the previous close. NaN days are skipped. The loop over numpy arrays is fine: about 10 s for 6,000 symbols × 2,000 days.

**`eligible`** is `traded ≥ MIN_PRICE`, the 20-day mean dollar volume `≥ MIN_DOLLAR_VOLUME`, and at least `MIN_HISTORY_DAYS` closes so far.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `scripts/in-docker.sh uv run pytest -q tests/unit/test_model_features.py && scripts/in-docker.sh uv run ruff check .`
Expected: PASS, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add pipeline/src/advisor/model pipeline/tests/unit/test_model_features.py
```
```bash
git commit -m "feat: compute the stock model's price and relative-strength features"
```

---

### Task 3: Point-in-time US fundamentals

**Files:**
- Create: `pipeline/src/advisor/model/fundamentals.py`
- Test: `pipeline/tests/unit/test_model_fundamentals.py`

**Interfaces:**
- Consumes:
  - `advisor.collectors.sec_xbrl.METRICS`, whose concepts are written `f"{taxonomy}:{concept}"` as in `fundamentals.parquet`;
  - Plan 3a's `fundamentals.parquet` (`cik, metric, concept, unit, start, end, value, filed, form, accession`) and `tickers.parquet` (`symbol, cik`);
  - `split_factor` and the split-adjusted close from Task 2.
- Produces, in `advisor.model.fundamentals` (Task 4):
  - `FUNDAMENTAL_FEATURES = ["rev_growth", "gross_margin", "op_margin", "gross_margin_trend", "op_margin_trend", "eps_growth", "earnings_yield", "sales_yield", "fcf_yield", "debt_to_equity", "log_mcap"]`;
  - `first_reported(facts: pd.DataFrame) -> pd.DataFrame`. Per `(cik, metric, start, end)` it keeps one row, from the best-priority concept and the earliest `filed` (columns `cik, metric, start, end, value, filed`, as Timestamps);
  - `ttm(facts: pd.DataFrame) -> pd.DataFrame`, with columns `cik, metric, period` (a monthly `Period` of the end), `end`, `ttm`, `known`, `ttm_1y`;
  - `fundamental_features(facts, tickers, days: pd.DatetimeIndex, split_adjusted_close: pd.DataFrame, splits: pd.DataFrame) -> dict[str, pd.DataFrame]`, as wide frames over `days` × the symbols in both `tickers` and the close.

- [ ] **Step 1: Write the failing tests**

`pipeline/tests/unit/test_model_fundamentals.py`:

```python
import numpy as np
import pandas as pd
import pytest

from advisor.model.fundamentals import first_reported, fundamental_features, ttm

REV = "us-gaap:Revenues"
REV2 = "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"


def fact(metric, start, end, value, filed, concept=REV, cik=1):
    return {"cik": cik, "metric": metric, "concept": concept, "unit": "USD", "start": start, "end": end,
            "value": value, "filed": filed, "form": "10-Q", "accession": "a"}


def frame(*rows) -> pd.DataFrame:
    return pd.DataFrame(list(rows))


REVENUE = frame(
    fact("revenue", "2022-01-01", "2022-09-30", 260.0, "2022-11-01"),
    fact("revenue", "2022-01-01", "2022-12-31", 360.0, "2023-02-10"),
    fact("revenue", "2023-01-01", "2023-09-30", 290.0, "2023-11-01"),
    fact("revenue", "2023-01-01", "2023-12-31", 400.0, "2024-02-10"),
    fact("revenue", "2024-01-01", "2024-09-30", 320.0, "2024-11-01"),
)


def test_each_period_keeps_its_first_reported_value_of_the_best_concept():
    facts = frame(
        fact("revenue", "2023-01-01", "2023-12-31", 100.0, "2024-02-01"),
        fact("revenue", "2023-01-01", "2023-12-31", 90.0, "2025-02-01"),  # restated a year later
        fact("revenue", "2023-01-01", "2023-12-31", 95.0, "2024-01-15", concept=REV2),  # a lower-priority concept
    )
    kept = first_reported(facts)
    assert kept[["value", "filed"]].values.tolist() == [[100.0, pd.Timestamp("2024-02-01")]]


def test_ttm_comes_from_year_to_date_facts():
    t = ttm(first_reported(REVENUE)).sort_values("period")
    got = [(str(r.period), r.ttm, r.known.date().isoformat(), None if np.isnan(r.ttm_1y) else r.ttm_1y)
           for r in t.itertuples()]
    assert got == [
        ("2022-12", 360.0, "2023-02-10", None),
        ("2023-09", 390.0, "2023-11-01", None),  # 290 + 360 - 260; no 2022-09 TTM
        ("2023-12", 400.0, "2024-02-10", 360.0),
        ("2024-09", 430.0, "2024-11-01", 390.0),  # 320 + 400 - 290
    ]


def test_a_filing_counts_from_the_next_day():
    days = pd.DatetimeIndex(["2024-11-01", "2024-11-04"], name="day")
    close = pd.DataFrame({"X": [10.0, 10.0]}, index=days)
    splits = close * 0 + 1.0
    f = fundamental_features(REVENUE, pd.DataFrame({"symbol": ["X"], "cik": [1]}), days, close, splits)
    assert f["rev_growth"]["X"].round(4).tolist() == [round(400 / 360 - 1, 4), round(430 / 390 - 1, 4)]


def test_a_split_after_the_filing_keeps_market_cap():
    days = pd.DatetimeIndex(["2024-08-15", "2024-09-03"], name="day")
    facts = frame(fact("shares_outstanding", None, "2024-06-30", 100.0, "2024-07-31",
                       concept="dei:EntityCommonStockSharesOutstanding"))
    close = pd.DataFrame({"X": [50.0, 50.0]}, index=days)  # in today's shares: traded at 200, then 50 after 4:1
    # splits after each day: 4 until the split on 2024-08-31, then none; the shares' period end reads 4
    splits = pd.DataFrame({"X": [4.0, 4.0, 1.0]}, index=pd.DatetimeIndex(["2024-06-28", "2024-08-15", "2024-09-03"]))
    f = fundamental_features(facts, pd.DataFrame({"symbol": ["X"], "cik": [1]}), days, close, splits)
    assert f["log_mcap"]["X"].tolist() == pytest.approx([np.log(20_000.0)] * 2)


def test_missing_figures_stay_missing():
    days = pd.DatetimeIndex(["2024-12-02"], name="day")
    close = pd.DataFrame({"X": [10.0]}, index=days)
    f = fundamental_features(REVENUE, pd.DataFrame({"symbol": ["X"], "cik": [1]}), days, close, close * 0 + 1.0)
    assert np.isnan(f["gross_margin"]["X"].iloc[0])  # no gross profit filed (a bank, say)
    assert np.isnan(f["earnings_yield"]["X"].iloc[0])  # no shares, so no market cap
```

- [ ] **Step 2: Run them to verify they fail**

Run: `scripts/in-docker.sh uv run pytest -q tests/unit/test_model_fundamentals.py`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `advisor.model.fundamentals`** (signatures above)

**`first_reported`:**
- Rank concepts by their position in `METRICS[metric]`; an unknown concept ranks 99.
- Sort by `(rank, filed)` and keep the first row per `(cik, metric, start, end)`.
- Restatements are ignored. This is still point in time: a period's value is known on one date and never changes later. The deferred.md line about "the latest fact filed on or before" is replaced in Task 8.

**`ttm`**, for flow metrics (`revenue, gross_profit, operating_income, net_income, operating_cash_flow, capex, eps_diluted`):
- Duration facts of 350–380 days are fiscal years (FY); 81–349 days are year to date (YTD).
- A YTD fact at end E gets `TTM = YTD(E) + FY ending in the month of (YTD start − 1 day) − YTD ending 12 months before E with the same length in months`. `known` is the latest `filed` of the three.
- An FY fact is its own TTM.
- Keep the earliest `known` per `(cik, metric, period)`.
- `ttm_1y` is the TTM of the period 12 months earlier. Blank it if it was known later than the row.

Use table merges, not loops: the prototype's per-filing loop took over 45 minutes, and merges take seconds.

**`fundamental_features`:**
- Build the grid of (symbol, day) for symbols in both `tickers` and the close. Read every flow's latest `ttm`/`ttm_1y`, and the balances (`equity`, the debt metrics and `shares_outstanding`, instant facts with no start), with `pd.merge_asof(..., left_on="day", right_on="known", by="cik", allow_exact_matches=False)`. Use `filed` as `known` for balances.
- **Market cap** = split-adjusted close × filed shares × the split factor at the shares' period end (`merge_asof` on `splits` by date, carrying the last value). The same factor scales EPS onto today's shares before `eps_growth` is computed.
- **Features** (division by zero gives NaN):
  - `rev_growth = rev/rev_1y − 1`;
  - margins are gross profit and operating income over revenue, and `*_trend` is the margin minus the year-ago margin;
  - `eps_growth = (eps − eps_1y)/|eps_1y|`, clipped to ±5;
  - `earnings_yield = net_income/mcap`, `sales_yield = revenue/mcap`, `fcf_yield = (operating_cash_flow − capex)/mcap`;
  - `debt_to_equity = debt/equity`, with equity > 0 only. Debt is `long_term_debt`, or `long_term_debt_noncurrent + debt_current` when it's missing, plus `short_term_borrowings + commercial_paper`;
  - `log_mcap = log(mcap)`, for mcap > 0.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `scripts/in-docker.sh uv run pytest -q tests/unit/test_model_fundamentals.py && scripts/in-docker.sh uv run ruff check .`
Expected: PASS, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add pipeline/src/advisor/model/fundamentals.py pipeline/tests/unit/test_model_fundamentals.py
```
```bash
git commit -m "feat: point-in-time US fundamentals for the stock model"
```

---

### Task 4: One market's training rows

**Files:**
- Create: `pipeline/src/advisor/model/dataset.py`, `pipeline/tests/model_data.py`
- Test: `pipeline/tests/unit/test_model_dataset.py`

**Interfaces:**
- Consumes:
  - Tasks 2 and 3;
  - `MARKETS[market].benchmark`, and `SECTOR_ETFS` / `sector_etf` from `advisor.training.sectors`;
  - Plan 3a's files `prices_{M}.parquet`, `events_{M}.parquet`, `sectors.parquet`, and, for US, `fundamentals.parquet` and `tickers.parquet`;
  - `manifest.json`'s `end` (the build's ET date).
- Produces, in `advisor.model.dataset` (Tasks 5–7):
  - `SAMPLE_EVERY = 10`, `WARMUP = 252`;
  - `@dataclass(frozen=True) class MarketData`, with `market: Market`, `rows: pd.DataFrame`, `features: list[str]` and `calendar: pd.DatetimeIndex`;
  - `load_market(data_dir: Path, market: Market) -> MarketData`. `rows` has the columns `day, symbol, sector, dollar_volume_20`, `y_{h}` for every h in `HORIZONS`, and the features. It covers eligible stocks only: the benchmark and sector ETFs never.
- Produces, in `pipeline/tests/model_data.py` (Tasks 5 and 7 use it):
  - `write_market(out: Path, market: Market, stocks: int = 40, days: int = 2340, seed: int = 7, signal: float = 1.0, penny: bool = False) -> list[str]`, which writes one market's files and a `manifest.json`, and returns the stock symbols.

- [ ] **Step 1: Write the test data helper**

`pipeline/tests/model_data.py`:

```python
"""Synthetic training data in Plan 3a's file layout, for the model tests.

Each stock drifts at its own constant daily rate (drawn with sd 0.0012 × `signal`) plus noise, so
past returns predict future excess returns when `signal` > 0 and nothing does when it is 0.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

from advisor.markets import MARKETS
from advisor.models import Market
from advisor.training.sectors import SECTOR_ETFS


def _bars(symbol: str, closes: np.ndarray, days: pd.DatetimeIndex) -> pd.DataFrame:
    return pd.DataFrame({
        "symbol": symbol, "day": [d.date() for d in days], "open": closes, "high": closes * 1.01,
        "low": closes * 0.99, "close": closes, "volume": 1_000_000.0,
    })


def write_market(out: Path, market: Market, stocks: int = 40, days: int = 2340, seed: int = 7,
                 signal: float = 1.0, penny: bool = False) -> list[str]:
    out.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    calendar = pd.bdate_range("2017-01-02", periods=days, name="day")
    suffix = ".TO" if market == Market.TSX else ""
    sectors = list(SECTOR_ETFS[market])[:2]
    symbols = [f"Q{chr(65 + i // 26)}{chr(65 + i % 26)}{suffix}" for i in range(stocks)]

    def walk(drift: float) -> np.ndarray:
        return 50 * np.exp(np.cumsum(drift + rng.normal(0, 0.02, days)))

    frames = [_bars(MARKETS[market].benchmark, walk(0.0003), calendar)]
    frames += [_bars(etf, walk(0.0003), calendar) for etf in SECTOR_ETFS[market].values()]
    frames += [_bars(s, walk(rng.normal(0, 0.0012 * signal)), calendar) for s in symbols]
    labels = [(s, sectors[i % 2], "Industry") for i, s in enumerate(symbols)]
    if penny:
        frames.append(_bars(f"QZZ{suffix}", np.full(days, 0.5), calendar))
        labels.append((f"QZZ{suffix}", sectors[0], "Industry"))
    pd.concat(frames).to_parquet(out / f"prices_{market}.parquet", index=False)
    pd.DataFrame({"symbol": [], "day": [], "dividend": [], "split": []}).to_parquet(out / f"events_{market}.parquet", index=False)
    pd.DataFrame(labels, columns=["symbol", "sector", "industry"]).to_parquet(out / "sectors.parquet", index=False)
    if market == Market.US:
        pd.DataFrame(columns=["cik", "metric", "concept", "unit", "start", "end", "value", "filed", "form", "accession"]
                     ).to_parquet(out / "fundamentals.parquet", index=False)
        pd.DataFrame({"symbol": pd.Series([], dtype=str), "cik": pd.Series([], dtype="int32")}).to_parquet(out / "tickers.parquet", index=False)
    # built during the last day's session: its bar is partial and must be left out
    (out / "manifest.json").write_text(json.dumps({"end": calendar[-1].date().isoformat()}))
    return symbols
```

(`sectors.parquet` is rewritten for each market, so a test that needs both markets writes them into different directories.)

- [ ] **Step 2: Write the failing tests**

`pipeline/tests/unit/test_model_dataset.py`:

```python
import pandas as pd
import pytest

from advisor.markets import MARKETS
from advisor.model.dataset import SAMPLE_EVERY, WARMUP, load_market
from advisor.model.features import HORIZONS, PRICE_FEATURES, RS_FEATURES
from advisor.model.fundamentals import FUNDAMENTAL_FEATURES
from advisor.models import Market
from model_data import write_market


def test_a_market_becomes_one_row_per_eligible_stock_and_sample_day(tmp_path):
    stocks = write_market(tmp_path, Market.TSX, stocks=3, days=400, penny=True)
    data = load_market(tmp_path, Market.TSX)
    assert data.features == PRICE_FEATURES + RS_FEATURES
    assert sorted(data.rows["symbol"].unique()) == sorted(stocks)  # no benchmark, ETF or penny stock
    assert len(data.calendar) == 399  # the build day's partial bar is left out
    assert pd.DatetimeIndex(sorted(data.rows["day"].unique())).equals(data.calendar[WARMUP::SAMPLE_EVERY])
    assert {f"y_{h}" for h in HORIZONS} <= set(data.rows.columns)
    assert data.rows["sector"].notna().all() and (data.rows["dollar_volume_20"] > 1e6).all()


def test_the_target_is_read_from_the_closes(tmp_path):
    stocks = write_market(tmp_path, Market.TSX, stocks=1, days=400)
    data = load_market(tmp_path, Market.TSX)
    prices = pd.read_parquet(tmp_path / "prices_TSX.parquet")
    close = prices.pivot(index="day", columns="symbol", values="close")
    day = data.calendar[WARMUP]
    i = list(close.index).index(day.date())
    row = data.rows[(data.rows["day"] == day)].iloc[0]
    bench = MARKETS[Market.TSX].benchmark
    expected = close[stocks[0]].iloc[i + 5] / close[stocks[0]].iloc[i] - close[bench].iloc[i + 5] / close[bench].iloc[i]
    assert row["y_5"] == pytest.approx(expected)


def test_us_rows_carry_fundamentals(tmp_path):
    write_market(tmp_path, Market.US, stocks=2, days=400)
    data = load_market(tmp_path, Market.US)
    assert data.features == PRICE_FEATURES + RS_FEATURES + FUNDAMENTAL_FEATURES
    assert data.rows["log_mcap"].isna().all()  # this data has no filings: missing, never zero
```

- [ ] **Step 3: Run them to verify they fail**

Run: `scripts/in-docker.sh uv run pytest -q tests/unit/test_model_dataset.py`
Expected: FAIL with `ModuleNotFoundError: advisor.model.dataset`.

- [ ] **Step 4: Implement `load_market`** (signature above)

1. Read the manifest's `end`, and drop price rows on or after it.
2. Make `to_wide` frames, then compute `split_adjusted, traded = as_traded(...)` and `dollar_volume = split_adjusted × volume` (yfinance's volume is split-adjusted).
3. The calendar is the days with a benchmark close.
4. Sample days are `calendar[WARMUP::SAMPLE_EVERY]`.
5. Features:
   - `price_features(wide, dollar_volume, jump_days(wide.close))`;
   - `relative_strength(...)`, with `etf_of = {s: sector_etf(market, sector)}` from `sectors.parquet` and `etfs = sorted(SECTOR_ETFS[market].values())`;
   - for US, also `fundamental_features(...)` over the sample days, with `split_factor(...)`.
6. Targets are `forward_excess(wide.close, benchmark)`.
7. Stack at the sample days for every column that is neither the benchmark nor an ETF, and keep the rows where `eligible(traded, dollar_volume)` holds.
8. `dollar_volume_20` is the 20-day mean dollar volume.
9. `sector` comes from `sectors.parquet` (it may be None). It isn't a feature: the backtest uses it for the sector cap.

Fundamental frames are reindexed to every stock, so a stock without filings has NaN, never a missing column. An empty `events` file (no splits or dividends) leaves prices as they are.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `scripts/in-docker.sh uv run pytest -q tests/unit/test_model_dataset.py && scripts/in-docker.sh uv run ruff check .`
Expected: PASS, ruff clean.

- [ ] **Step 6: Commit**

```bash
git add pipeline/src/advisor/model/dataset.py pipeline/tests/model_data.py pipeline/tests/unit/test_model_dataset.py
```
```bash
git commit -m "feat: assemble one market's training rows from the weekly data"
```

---

### Task 5: Walk-forward training, calibration and the model's files

**Files:**
- Modify: `pipeline/pyproject.toml`, `pipeline/uv.lock`, `pipeline/scripts/in-docker.sh`
- Create: `pipeline/scripts/test-image.Dockerfile`, `pipeline/src/advisor/model/train.py`
- Test: `pipeline/tests/unit/test_model_train.py`

**Interfaces:**
- Consumes: `MarketData`, `load_market` (Task 4); `HORIZONS`, `PRICE_FEATURES` and `RS_FEATURES` (Task 2); `model_data.write_market`.
- Produces, in `advisor.model.train` (Tasks 6 and 7):
  - `QUANTILES = (0.1, 0.5, 0.9)`;
  - `PARAMS = {"learning_rate": 0.075, "num_leaves": 31, "min_data_in_leaf": 500, "feature_fraction": 0.8, "bagging_fraction": 0.8, "bagging_freq": 1, "lambda_l2": 1.0, "seed": 7, "verbose": -1}`;
  - `MIN_BIN = 500`, `SCREENER_HORIZON = 21`;
  - `@dataclass(frozen=True) class TrainConfig`, with `horizons: tuple[int, ...] = HORIZONS`, `rounds: int = 200`, `folds: int = 4`, `min_train_years: float = 2.0`, and `params: dict` (default: a copy of `PARAMS`);
  - `@dataclass(frozen=True) class Fold`, with `start: pd.Timestamp` and `end: pd.Timestamp` (end exclusive);
  - `make_folds(days: pd.DatetimeIndex, config: TrainConfig) -> list[Fold]`;
  - `training_rows(rows: pd.DataFrame, calendar: pd.DatetimeIndex, horizon: int, start: pd.Timestamp) -> pd.DataFrame`;
  - `class Calibrator`, with `fit(p_raw, beat, min_bin=MIN_BIN) -> Calibrator` (a classmethod), `__call__(p_raw: np.ndarray) -> np.ndarray`, `to_json() -> dict` and `from_json(d) -> Calibrator` (a classmethod);
  - `calibration_error(p: np.ndarray, beat: np.ndarray, bins: int = 10) -> float`, in percentage points: the mean, weighted by count, over equal-count bins of |mean p − hit rate|;
  - `rank_ic(frame: pd.DataFrame, pred: str, actual: str) -> float`, the mean over days of the Spearman correlation;
  - `@dataclass class WalkForward`, with `predictions: pd.DataFrame` (columns `day, symbol, sector, dollar_volume_20, horizon, fold, y, q10, q50, q90, p_raw, p`) and `metrics: dict[int, dict]`. Each horizon's metrics hold `calibration_pts`, `max_bin_gap_pts`, `rank_ic`, `coverage_10_90` and `base_rate`;
  - `walk_forward(data: MarketData, config: TrainConfig = TrainConfig()) -> WalkForward`;
  - `class FinalModel`, with `features: list[str]`, `horizons: tuple[int, ...]`, `predict(x: pd.DataFrame) -> pd.DataFrame` and `screen(x: pd.DataFrame) -> np.ndarray`. `predict` returns one row per input row per horizon, keeping the input's index, with the columns `horizon, q10, q50, q90, p_beat`;
  - `fit_final(data: MarketData, wf: WalkForward, config: TrainConfig = TrainConfig()) -> FinalModel`;
  - `to_files(model: FinalModel) -> dict[str, bytes]` and `from_files(files: Mapping[str, bytes]) -> FinalModel`.

- [ ] **Step 1: Add LightGBM and a test image that can run it**

Run (from `pipeline/`): `uv add --no-sync "lightgbm>=4.5"`
Expected: `pyproject.toml` gains `"lightgbm>=4.5",`. `uv.lock` gains `lightgbm` 4.7.0, `scipy` and `narwhals`.

Create `pipeline/scripts/test-image.Dockerfile`:

```dockerfile
# The pipeline's test image: uv's Python image plus the OpenMP runtime LightGBM needs.
# GitHub's runners have libgomp1 already; the slim image doesn't.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
```

In `pipeline/scripts/in-docker.sh`:
- Before `docker run`, add `image=advisor-pipeline-test:1` and `docker image inspect "$image" >/dev/null 2>&1 || docker build -q -t "$image" - < scripts/test-image.Dockerfile`.
- Replace the image name in `docker run` with `"$image"`.
- Add a comment: bump the tag when the Dockerfile changes.

- [ ] **Step 2: Write the failing tests**

`pipeline/tests/unit/test_model_train.py`:

```python
import lightgbm as lgb
import numpy as np
import pandas as pd
import pytest

from advisor.model.dataset import load_market
from advisor.model.train import (
    PARAMS,
    Calibrator,
    TrainConfig,
    calibration_error,
    fit_final,
    from_files,
    make_folds,
    to_files,
    training_rows,
    walk_forward,
)
from advisor.models import Market
from model_data import write_market

FAST = TrainConfig(horizons=(5, 63), rounds=40, params={**PARAMS, "min_data_in_leaf": 50, "num_threads": 2})


def test_lightgbm_trains_in_this_environment():
    x = np.arange(200, dtype=float).reshape(-1, 1)
    booster = lgb.train({"objective": "binary", "verbose": -1, "min_data_in_leaf": 5},
                        lgb.Dataset(x, (x[:, 0] > 100).astype(int)), num_boost_round=5)
    low, high = booster.predict(np.array([[10.0], [190.0]]))
    assert low < 0.5 < high


def test_four_equal_test_periods_follow_two_years_of_training():
    days = pd.bdate_range("2018-01-01", "2025-12-31")
    folds = make_folds(days, TrainConfig())
    assert len(folds) == 4
    assert folds[0].start == pd.Timestamp("2020-01-01")
    assert folds[-1].end > days[-1]
    assert all(a.end == b.start for a, b in zip(folds, folds[1:], strict=False))


def test_training_rows_end_a_horizon_before_the_test_period():
    calendar = pd.bdate_range("2024-01-01", periods=100, name="day")
    rows = pd.DataFrame({"day": calendar[::5], "y_5": 0.01})
    rows.loc[1, "y_5"] = np.nan
    kept = training_rows(rows, calendar, 5, calendar[50])
    assert kept["day"].max() == calendar[40]  # day 45's 5-day target ends on the test period's first day
    assert calendar[5] not in set(kept["day"])  # no target, no training row


def test_calibration_never_claims_more_than_the_data_supports():
    rng = np.random.default_rng(1)
    p_raw = np.concatenate([rng.uniform(0.3, 0.6, 20_000), np.full(10, 0.95)])
    beat = np.concatenate([rng.random(20_000) < p_raw[:20_000], np.ones(10, dtype=bool)])
    cal = Calibrator.fit(p_raw, beat)
    assert cal(np.array([0.95]))[0] <= 0.65  # ten lucky rows don't make a 95% (or 100%) promise
    assert cal(np.array([0.45]))[0] == pytest.approx(0.45, abs=0.05)
    assert np.all(np.diff(cal(np.linspace(0, 1, 101))) >= 0)
    back = Calibrator.from_json(cal.to_json())
    assert back(np.array([0.5]))[0] == pytest.approx(cal(np.array([0.5]))[0])


def test_calibration_error_is_in_percentage_points():
    rng = np.random.default_rng(2)
    p = rng.uniform(0.2, 0.8, 50_000)
    assert calibration_error(p, rng.random(50_000) < p) < 1.0
    assert calibration_error(np.full(50_000, 0.8), rng.random(50_000) < 0.5) == pytest.approx(30, abs=1.5)


def test_walk_forward_finds_a_real_signal_and_calibrates_out_of_sample(tmp_path):
    write_market(tmp_path, Market.TSX, stocks=40)
    wf = walk_forward(load_market(tmp_path, Market.TSX), FAST)
    assert set(wf.metrics) == {5, 63}
    assert wf.metrics[63]["rank_ic"] > 0.1
    first = wf.predictions[wf.predictions["fold"] == 0]
    later = wf.predictions[wf.predictions["fold"] > 0]
    assert first["p"].isna().all()  # nothing earlier to calibrate the first period on
    assert later["p"].between(0, 1).all()
    assert (later["q10"] <= later["q50"]).all() and (later["q50"] <= later["q90"]).all()
    assert wf.metrics[63]["calibration_pts"] < 10


def test_a_final_model_round_trips_through_its_files(tmp_path):
    write_market(tmp_path, Market.TSX, stocks=20, days=1100)
    data = load_market(tmp_path, Market.TSX)
    model = fit_final(data, walk_forward(data, FAST), FAST)
    files = to_files(model)
    assert set(files) == {"meta", "calibration", "screener"} | {
        f"h{h}_{part}" for h in (5, 63) for part in ("q10", "q50", "q90", "beat")
    }
    back = from_files(files)
    x = data.rows[data.features].head(50)
    pd.testing.assert_frame_equal(back.predict(x), model.predict(x))
    np.testing.assert_allclose(back.screen(x), model.screen(x))
    assert back.horizons == (5, 63) and back.features == data.features
```

- [ ] **Step 3: Run them to verify they fail**

Run: `scripts/in-docker.sh uv run pytest -q tests/unit/test_model_train.py`
Expected: the image is built once, then the tests FAIL with `ModuleNotFoundError: advisor.model.train`.

- [ ] **Step 4: Implement `advisor.model.train`** (signatures above)

**`make_folds`:**
- The test span runs from `days.min() + DateOffset(years=min_train_years)` to `days.max() + 1 day`.
- Split it into `config.folds` equal periods with `pd.date_range(..., periods=folds + 1)`.

**`training_rows`:**
- Keep rows whose calendar position plus `horizon` is less than `start`'s position, and whose `y_{horizon}` isn't NaN.
- `start`'s position is the first calendar day on or after it.

**`walk_forward`**, per horizon and per fold:
- Fit the three quantile boosters (`objective="quantile"`, `alpha=q`) and one binary booster on `y > 0`, with `lgb.train(config.params | {...}, Dataset(x, y), num_boost_round=config.rounds)`.
- Predict the fold's test rows (day in `[start, end)` with a target).
- Sort the three quantiles per row, so q10 ≤ q50 ≤ q90 even when the boosters cross.
- Calibrate fold k with a `Calibrator` fitted on the predictions of folds before k. Fold 0 keeps `p` NaN and is left out of the metrics and the backtest.
- A fold with no training or no test rows is skipped. This happens to the last folds of the longest horizons, whose targets reach past the data. A fold with no earlier predictions keeps `p` NaN.
- The metrics use the rows with `p`.

**`Calibrator.fit`:**
- Fit isotonic regression with `scipy.optimize.isotonic_regression` on the beats sorted by `p_raw`, and keep `(xs, ys)` for `np.interp`.
- Then cut `p_raw` into `min(20, max(1, n // min_bin))` equal-count bins and set `lo, hi` to the lowest and highest hit rate among them. `__call__` clips the interpolation to `[lo, hi]`.

**`fit_final`:**
- Fit the same four boosters per horizon on every row with a target.
- Each horizon's calibrator comes from all of its out-of-sample predictions in `wf` (folds > 0).
- The screener is a binary booster on `PRICE_FEATURES + RS_FEATURES` for `y_{SCREENER_HORIZON} > 0`. Its raw score only ranks; Plan 3c uses it to shortlist.

**`to_files`:**
- Each booster is `gzip.compress(booster.model_to_string().encode())`, named `h{h}_q10`, `h{h}_q50`, `h{h}_q90`, `h{h}_beat`, plus `screener`.
- `calibration` is the gzip of the JSON `{str(h): calibrator.to_json()}`.
- `meta` is the gzip of the JSON `{"features", "screener_features", "horizons", "params", "rounds"}`.
- `from_files` reverses it with `lgb.Booster(model_str=...)`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `scripts/in-docker.sh uv run pytest -q tests/unit/test_model_train.py && scripts/in-docker.sh uv run ruff check .`
Expected: PASS (about 30 s), ruff clean.

- [ ] **Step 6: Commit**

```bash
git add pipeline/pyproject.toml pipeline/uv.lock pipeline/scripts/test-image.Dockerfile pipeline/scripts/in-docker.sh pipeline/src/advisor/model/train.py pipeline/tests/unit/test_model_train.py
```
```bash
git commit -m "feat: train the stock model walk-forward with honest calibration"
```

---

### Task 6: Backtest the pick rules after costs, and gate the market

**Files:**
- Create: `pipeline/src/advisor/model/backtest.py`
- Test: `pipeline/tests/unit/test_model_backtest.py`

**Interfaces:**
- Consumes: `WalkForward.predictions` (Task 5).
- Produces, in `advisor.model.backtest` (Task 7):
  - `P_MIN = 0.58`, `SWING_HORIZONS = frozenset({5, 10, 20})`, `PICKS_PER_STYLE = 10`, `PER_SECTOR = 3`, `MIN_PICKS = 30`, `MAX_CALIBRATION_PTS = 5.0`, `LARGE_DOLLAR_VOLUME = 10_000_000.0`, `SPREAD_LARGE = 0.001`, `SPREAD_SMALL = 0.003`;
  - `round_trip_cost(market: Market, dollar_volume_20: np.ndarray, usd_fx_fee_pct: float) -> np.ndarray`, as a fraction;
  - `simulate_picks(predictions: pd.DataFrame, market: Market, usd_fx_fee_pct: float) -> pd.DataFrame`. It has one row per pick, with `day, symbol, sector, horizon, style, p, q50, ratio, y, cost, net`;
  - `pick_metrics(picks: pd.DataFrame) -> dict[str, dict]`. Its keys are `"all"`, `"swing"` and `"position"`, each `{"picks", "mean_net_pct", "hit_rate_net", "beat_rate", "mean_p"}`. The rates are fractions, and an empty group has `picks` 0 and the rest None;
  - `gate(metrics: Mapping[str, Any], calibration_pts: float) -> tuple[bool, str]`.

- [ ] **Step 1: Write the failing tests**

`pipeline/tests/unit/test_model_backtest.py`:

```python
import numpy as np
import pandas as pd
import pytest

from advisor.model.backtest import gate, pick_metrics, round_trip_cost, simulate_picks
from advisor.models import Market

DAY = pd.Timestamp("2025-03-03")


def frame(rows) -> pd.DataFrame:
    return pd.DataFrame(
        [{"day": DAY, "symbol": s, "sector": sec, "horizon": h, "p": p, "q10": q10, "q50": q50, "q90": q90, "y": y,
          "dollar_volume_20": 2e7} for s, sec, h, p, q10, q50, q90, y in rows]
    )


def test_round_trip_costs_follow_the_market_rules():
    dollar_volume = np.array([2e7, 5e6])
    assert round_trip_cost(Market.US, dollar_volume, 1.5) == pytest.approx([0.031, 0.033])
    assert round_trip_cost(Market.TSX, dollar_volume, 1.5) == pytest.approx([0.001, 0.003])


def test_a_stock_is_picked_once_at_its_best_qualifying_horizon():
    picks = simulate_picks(frame([
        ("AAA.TO", "Energy", 10, 0.60, -0.02, 0.01, 0.03, 0.02),  # q50/(q90-q10) = 0.20
        ("AAA.TO", "Energy", 63, 0.62, -0.05, 0.04, 0.10, 0.06),  # 0.27: the better hold
        ("BBB.TO", "Energy", 20, 0.57, -0.02, 0.03, 0.05, 0.01),  # P below 0.58
        ("CCC.TO", "Energy", 20, 0.70, -0.02, 0.0005, 0.05, 0.01),  # q50 below the 0.10% cost
    ]), Market.TSX, 1.5)
    assert picks[["symbol", "horizon", "style"]].values.tolist() == [["AAA.TO", 63, "position"]]
    assert picks["net"].iloc[0] == pytest.approx(0.06 - 0.001)


def test_each_style_takes_ten_with_at_most_three_per_sector():
    rows = [(f"E{i}.TO", "Energy", 20, 0.65, -0.02, 0.02 + i / 1000, 0.06, 0.0) for i in range(5)]
    rows += [(f"T{i}.TO", f"Sector{i}", 20, 0.65, -0.02, 0.01, 0.06, 0.0) for i in range(12)]
    picks = simulate_picks(frame(rows), Market.TSX, 1.5)
    assert len(picks) == 10 and set(picks["style"]) == {"swing"}
    assert sorted(picks.loc[picks["sector"] == "Energy", "symbol"]) == ["E2.TO", "E3.TO", "E4.TO"]


def test_pick_metrics_are_per_style_and_overall():
    picks = pd.DataFrame({"style": ["swing", "swing", "position"], "net": [0.02, -0.01, 0.05],
                          "y": [0.021, -0.009, 0.051], "p": [0.6, 0.6, 0.7]})
    m = pick_metrics(picks)
    assert m["all"]["picks"] == 3
    assert m["all"]["mean_net_pct"] == pytest.approx(2.0)
    assert m["all"]["hit_rate_net"] == pytest.approx(2 / 3)
    assert m["all"]["beat_rate"] == pytest.approx(2 / 3)
    assert m["all"]["mean_p"] == pytest.approx(0.6333, abs=1e-3)
    assert m["swing"]["picks"] == 2 and m["position"]["mean_net_pct"] == pytest.approx(5.0)
    empty = pick_metrics(picks.iloc[:0])
    assert empty["all"] == {"picks": 0, "mean_net_pct": None, "hit_rate_net": None, "beat_rate": None, "mean_p": None}


def test_the_gate_needs_enough_profitable_honestly_calibrated_picks():
    def m(picks, net, p, beat):
        return {"all": {"picks": picks, "mean_net_pct": net, "hit_rate_net": beat, "beat_rate": beat, "mean_p": p}}

    assert gate(m(40, 0.8, 0.62, 0.60), 3.0) == (True, "40 backtest picks gained 0.80% after costs")
    assert gate(m(12, 0.8, 0.62, 0.60), 3.0) == (False, "only 12 backtest picks (needs 30)")
    assert gate(m(40, -1.2, 0.62, 0.60), 3.0) == (False, "backtest picks lost 1.20% after costs")
    assert gate(m(40, 0.8, 0.62, 0.60), 6.1) == (False, "probabilities off by 6.1 points (limit 5)")
    assert gate(m(40, 0.8, 0.66, 0.51), 3.0) == (
        False, "picks claimed 66% but beat their benchmark 51% of the time",
    )
    assert gate(pick_metrics(pd.DataFrame(columns=["style", "net", "y", "p"])), 2.0) == (
        False, "only 0 backtest picks (needs 30)",
    )
```

- [ ] **Step 2: Run them to verify they fail**

Run: `scripts/in-docker.sh uv run pytest -q tests/unit/test_model_backtest.py`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `advisor.model.backtest`** (signatures above)

**Cost:** the spread is `SPREAD_LARGE` when dollar volume is at least `LARGE_DOLLAR_VOLUME`, else `SPREAD_SMALL`. US adds `2 × usd_fx_fee_pct / 100`.

**`simulate_picks`** follows spec §6.1, §6.2 and §6.5:
- **Qualify:** `p ≥ P_MIN` and `q50 > cost`, with `ratio = q50 / (q90 − q10)` (NaN when the width isn't positive).
- **Hold time:** per (day, symbol), keep the qualifying horizon with the best ratio.
- **Style:** swing when the horizon is in `SWING_HORIZONS`, else position.
- **Limits:** per (day, style), rank by ratio (best first), keep at most `PER_SECTOR` per sector, then the first `PICKS_PER_STYLE`.
- `net = y − cost`.

**`pick_metrics`:**
- `mean_net_pct` is the mean of `net` × 100, and `hit_rate_net` is the share with `net > 0`.
- `beat_rate` is the share with `y > 0`, and `mean_p` the mean of `p`.

**`gate`**, checks in this order, each with its exact message:
1. At least `MIN_PICKS` picks: `"only {n} backtest picks (needs 30)"`.
2. `mean_net_pct > 0`: `"backtest picks lost {abs:.2f}% after costs"`.
3. `calibration_pts ≤ MAX_CALIBRATION_PTS`: `"probabilities off by {x:.1f} points (limit 5)"`.
4. `|mean_p − beat_rate| × 100 ≤ 5`: `"picks claimed {p:.0%} but beat their benchmark {b:.0%} of the time"`.
5. Otherwise: `(True, "{n} backtest picks gained {net:.2f}% after costs")`.

The first two are spec criterion 1; the last two are criterion 2.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `scripts/in-docker.sh uv run pytest -q tests/unit/test_model_backtest.py && scripts/in-docker.sh uv run ruff check .`
Expected: PASS, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add pipeline/src/advisor/model/backtest.py pipeline/tests/unit/test_model_backtest.py
```
```bash
git commit -m "feat: backtest the pick rules after costs and gate each market"
```

---

### Task 7: The weekly command, promotion and the job

**Files:**
- Create: `pipeline/src/advisor/model/weekly.py`
- Modify: `pipeline/src/advisor/training/build.py`, `.github/workflows/train.yml`
- Test: `pipeline/tests/unit/test_model_weekly.py`, `pipeline/tests/integration/test_model_weekly.py`, `pipeline/tests/unit/test_training_build.py`

**Interfaces:**
- Consumes: Tasks 1, 4, 5 and 6; `advisor.store.db.connect`; `Settings.from_env().database_url`.
- Produces, in `advisor.model.weekly`:
  - `IC_TOLERANCE = 0.005`, `KIND = {Market.US: "stock_us", Market.TSX: "stock_tsx"}`, `REPORT = "model-report.json"`;
  - `version_for(market: Market, trained_at: datetime) -> str`, which is `f"{KIND[market]}-{trained_at:%Y%m%d%H%M}"`;
  - `should_promote(metrics: Mapping[str, Any], calibration_pts: float, active: StoredModel | None) -> tuple[bool, str]`;
  - `run(data_dir: Path, markets: Sequence[Market], conn, now: datetime, config: TrainConfig = TrainConfig()) -> dict[str, dict]`, a report per market;
  - `exit_code(report: Mapping[str, Mapping]) -> int`, which is 1 when any market has an `error`, else 0;
  - `main(argv: Sequence[str] | None = None) -> int`, for `python -m advisor.model.weekly --data DIR [--market US|TSX ...]`.

- [ ] **Step 1: Write the failing tests**

`pipeline/tests/unit/test_model_weekly.py`:

```python
from datetime import UTC, datetime

from advisor.model.weekly import should_promote, version_for
from advisor.models import Market, StoredModel


def stored(ic: float) -> StoredModel:
    return StoredModel("stock_us-202610171000", "stock_us", datetime(2026, 10, 17, 10, tzinfo=UTC),
                       {"mean_rank_ic": ic}, 3.0, True)


def test_versions_name_the_market_and_the_minute():
    assert version_for(Market.TSX, datetime(2026, 10, 24, 10, 5, tzinfo=UTC)) == "stock_tsx-202610241005"


def test_a_new_model_needs_honest_probabilities_and_no_worse_ranking():
    assert should_promote({"mean_rank_ic": 0.05}, 3.0, None) == (True, "first model")
    assert should_promote({"mean_rank_ic": 0.05}, 5.4, None) == (False, "probabilities off by 5.4 points (limit 5)")
    assert should_promote({"mean_rank_ic": 0.047}, 3.0, stored(0.05)) == (True, "rank IC 0.047 vs the active 0.050")
    assert should_promote({"mean_rank_ic": 0.040}, 3.0, stored(0.05)) == (False, "rank IC 0.040 vs the active 0.050")
```

`pipeline/tests/integration/test_model_weekly.py`:

```python
from datetime import UTC, datetime, timedelta

from advisor.model import weekly
from advisor.model.train import PARAMS, TrainConfig, from_files
from advisor.models import Market
from advisor.store import repo
from model_data import write_market

NOW = datetime(2026, 10, 24, 10, 0, tzinfo=UTC)
FAST = TrainConfig(horizons=(5, 63), rounds=40, params={**PARAMS, "min_data_in_leaf": 50, "num_threads": 2})


def test_the_weekly_job_trains_promotes_and_stores_a_market(db, tmp_path):
    write_market(tmp_path, Market.TSX, stocks=40)
    report = weekly.run(tmp_path, [Market.TSX], db, NOW, FAST)
    assert report["TSX"]["promoted"] is True and report["TSX"]["reason"] == "first model"
    active = repo.active_model(db, "stock_tsx")
    assert active.version == "stock_tsx-202610241000"
    assert active.metrics["mean_rank_ic"] > 0.05
    assert {"horizons", "backtest", "picks_enabled", "picks_reason", "rows", "features"} <= set(active.metrics)
    assert active.calibration_error <= 5
    model = from_files(repo.load_model_files(db, active.version))
    assert model.horizons == (5, 63)


def test_a_worse_model_is_stored_but_the_active_one_stays(db, tmp_path):
    good, noise = tmp_path / "good", tmp_path / "noise"
    write_market(good, Market.TSX, stocks=40)
    write_market(noise, Market.TSX, stocks=40, signal=0.0, seed=8)
    weekly.run(good, [Market.TSX], db, NOW, FAST)
    report = weekly.run(noise, [Market.TSX], db, NOW + timedelta(days=7), FAST)
    assert report["TSX"]["promoted"] is False
    assert repo.active_model(db, "stock_tsx").version == "stock_tsx-202610241000"
    assert db.execute("select count(*) as n from models").fetchone()["n"] == 2


def test_a_market_that_fails_to_train_is_reported_and_the_rest_carry_on(db, tmp_path):
    write_market(tmp_path, Market.TSX, stocks=40)  # no US files
    report = weekly.run(tmp_path, [Market.US, Market.TSX], db, NOW, FAST)
    assert report["US"]["error"].startswith("FileNotFoundError")
    assert report["TSX"]["promoted"] is True
    assert weekly.exit_code(report) == 1
    assert repo.active_model(db, "stock_us") is None
```

Append to `pipeline/tests/unit/test_training_build.py` (Plan 3a's open follow-up). Add the imports `from advisor.training import build as build_module` and `from advisor.training.prices import YahooThrottled`:

```python
def test_yahoo_throttling_the_second_ask_counts_its_symbols_as_missing(fixtures_dir, tmp_path, monkeypatch):
    real = build_module.download_history
    calls = []

    def throttled_retry(symbols, *args, **kwargs):
        calls.append(list(symbols))
        if len(calls) == 2:  # the market's retry of what it missed
            raise YahooThrottled("3 Yahoo downloads in a row came back empty")
        return real(symbols, *args, **kwargs)

    monkeypatch.setattr(build_module, "download_history", throttled_retry)
    with web(fixtures_dir) as client, pytest.raises(BuildFailed, match="no bars for 1 of 3 US stocks"):
        build(tmp_path, NOW, deps(client, [], silent_once=frozenset({"JPM"})), limit=10)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `scripts/in-docker.sh uv run pytest -q tests/unit/test_model_weekly.py tests/integration/test_model_weekly.py tests/unit/test_training_build.py`
Expected:
- `ModuleNotFoundError: advisor.model.weekly`.
- The build test fails with `YahooThrottled` raised instead of `BuildFailed`.

- [ ] **Step 3: Catch the throttled retry in `training/build.py`**

Wrap the retry `download_history(history.missing, ...)` in `try/except YahooThrottled`. On that exception, keep the first answer: the symbols stay missing and the market's missing-share rule decides.

- [ ] **Step 4: Implement `advisor.model.weekly`** (signatures above)

**`should_promote`**, in order:
1. `calibration_pts > 5`: `(False, "probabilities off by {x:.1f} points (limit 5)")`.
2. No active model: `(True, "first model")`.
3. Compare with `metrics["mean_rank_ic"] ≥ active.metrics["mean_rank_ic"] − IC_TOLERANCE`. The result is that boolean with `"rank IC {new:.3f} vs the active {old:.3f}"`.

Spec §5.2 says "at least as good". The tolerance absorbs week-to-week noise from one more week of data; without it a good model would rarely be replaced.

**`run`**, for each market inside `try`:
1. `load_market`.
2. `walk_forward`.
3. `simulate_picks` on the predictions that have a calibrated `p` (folds after the first), with `repo.fee_settings(conn)[0]`.
4. `pick_metrics`.
5. `calibration_pts` is the maximum over horizons of `metrics[h]["calibration_pts"]`.
6. `gate(...)` gives `picks_enabled` and `picks_reason`.
7. `fit_final` and `to_files`.
8. `repo.save_model(...)`, with metrics:
   - `{"horizons": {str(h): …}, "mean_rank_ic": mean over horizons, "backtest": pick_metrics, "picks_enabled", "picks_reason", "rows", "folds": [[start, end], …], "features", "importance": {str(h): top 10 features by gain of the beat booster}, "seconds": {...}}`.
9. `should_promote` against `repo.active_model(conn, kind)`. If it says yes, `repo.activate_model`.
10. `repo.prune_models(conn, kind)`.

The market's report is `{"version", "promoted", "reason", "picks_enabled", "picks_reason", "calibration_pts", "mean_rank_ic", "seconds"}`. On any exception it is `{"error": f"{type(e).__name__}: {e}"}`, and the next market still runs.

**`main`:**
- Parse `--data` and `--market` (default both).
- Connect with `Settings.from_env().database_url`, then call `run(..., datetime.now(UTC))`.
- Write the report to `DIR/model-report.json`, print it, and return `exit_code(report)`.

- [ ] **Step 5: Add the step to `train.yml`**

After "Build training data":

```yaml
      - name: Train, backtest and promote the stock models
        env:
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
        run: uv run python -m advisor.model.weekly --data "$RUNNER_TEMP/training"
```

Change the artifact's `path` to list both `${{ runner.temp }}/training/manifest.json` and `${{ runner.temp }}/training/model-report.json`, and rename it `training-report`. Update the header comment: the job now trains, backtests and promotes. A failed market fails the job (GitHub emails the owner) while its active model stays.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `scripts/in-docker.sh uv run pytest -q && scripts/in-docker.sh uv run ruff check .`
Expected: all tests pass (806 before this plan, plus this plan's), ruff clean.

- [ ] **Step 7: Commit**

```bash
git add pipeline/src/advisor/model/weekly.py pipeline/src/advisor/training/build.py .github/workflows/train.yml pipeline/tests/unit/test_model_weekly.py pipeline/tests/integration/test_model_weekly.py pipeline/tests/unit/test_training_build.py
```
```bash
git commit -m "feat: train, backtest and promote the stock models every Saturday"
```

---

### Task 8: Docs

**Files:**
- Modify: `docs/superpowers/specs/2026-10-09-stock-advisor-design.md`, `docs/superpowers/deferred.md`, `pipeline/README.md`

- [ ] **Step 1: Update the spec**

- **Revision history:** add a line for 2026-10-21, Plan 3b: macro dropped from the stock model; models stored in Postgres; gate definitions.
- **§4.3 stage 3:** "about 6,000 US symbols and 1,500 TSX symbols" becomes about 700 TSX symbols (deferred.md, Plan 3).
- **§5.1 Macro regime row:** add "Not used by the stock model (owner's decision, 2026-10-21): in the Plan 3b prototype, levels that are the same for every stock let the model time the market by date. Collected for the crypto model and a later form."
- **§5.1 Fundamentals row:** "surprise from the last filing" waits for single-quarter EPS (deferred).
- **§5.1, below the table:** the sector label isn't a feature (today's labels over 8 years); `sector_rank_63` is.
- **§5.2:**
  - Training rows are every 10th session after a 252-session warm-up.
  - The walk-forward has 4 equal test periods after 2 training years, with a horizon-long embargo.
  - Calibration is isotonic regression fitted on earlier periods only, clipped to the hit rates of 500-row bins.
  - Promotion needs calibration within 5 points and a mean rank IC no more than 0.005 below the active model's.
  - The screener model is a 21-day beat classifier on price/volume and relative strength.
  - Models are stored in `model_files`.
- **§6.6 Disabling picks:** a market's picks are shown only when its latest backtest has at least 30 picks, a positive mean return after costs, calibration within 5 points, and a mean stated P within 5 points of the picks' beat rate. The reason is stored in the model's metrics.
- **§8:** add the row `| model_files | version (→ models, cascade), name, body (gzip). The active model and one other per kind |`.
- **§12:** `features/ model/ … train.py` becomes `model/{features, fundamentals, dataset, train, backtest, weekly}.py`.
- **§13, risk "The model doesn't beat a market's benchmark":** add "Plan 3b's prototype: the US edge (+0.2–0.6% before costs) is smaller than the 3.1% currency round trip; a USD account (spec R12 setting) would change that."

- [ ] **Step 2: Update deferred.md**

- **Header:** add Plan 3a and Plan 3b to the list of reviews.
- **"Plan 3" section:** remove what this plan did (the jump indicator feature, training data use, the TSX universe size). Replace the XBRL line's "latest fact filed on or before `as_of`" with the first-reported, `filed < day` rule.
- **New section "Plan 3c: live predictions":**
  - Live features need at least 260 sessions of bars per symbol (`mom_12_1`, the 52-week range). Check the live Yahoo window.
  - Load the active model per market with `repo.active_model` and `load_model_files` → `from_files`, and write `predictions` (q10, q50, q90, p_beat per horizon, `model_version`).
  - Rank the screener's survivors with `FinalModel.screen`.
  - The pre-close run's partial bar.
  - US fundamentals live must use `advisor.model.fundamentals` on `sec_xbrl` facts, so training and live agree.
- **New section "Plan 4":**
  - Exclude non-common instruments before any pick, and from training (the list already in deferred.md).
  - Block Buy on `jump_5d`.
  - Read `picks_enabled` from the active model's metrics.
- **Known limits:**
  - Survivorship.
  - The US cost finding.
  - "Surprise", the earnings group, and ownership and flow (insiders, short interest, 13F) come with a later history plan; until then they're live only (the owner's fast-path decision, 2026-10-20).
  - Macro could return as interactions or a separate regime model, never as raw levels.

- [ ] **Step 3: README**

In `pipeline/README.md`, under the training section:
- `python -m advisor.model.weekly --data DIR [--market TSX]` trains, backtests and promotes. It needs `DATABASE_URL` and the files from `advisor.training.build`.
- `model-report.json` is what it decided.
- The test image (`scripts/test-image.Dockerfile`) is built on first use.

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-10-09-stock-advisor-design.md docs/superpowers/deferred.md pipeline/README.md
```
```bash
git commit -m "docs: record Plan 3b's model, gates and what Plan 3c needs"
```

---

## After the plan

The owner dispatches `train.yml` once by hand, outside market hours, and reads `training-report`:
- each market's `picks_enabled` and `picks_reason`;
- the calibration;
- the training time on the 2-core runner (the prototype's estimate: about 20 minutes for the build plus about 10 for training).
