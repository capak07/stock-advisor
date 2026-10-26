# Plan 3c: Live Predictions — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Each twice-daily run loads each market's active stock model. It ranks the screener's survivors with the model's screener, and writes a forecast (q10, q50, q90 and P(beat) for every usable horizon) to `predictions` for holdings, the watchlist and the shortlist.

**Architecture:**
- **One feature path.** Live features are computed by the same `advisor.model` code that built the training rows. `dataset.py`'s feature step becomes a shared function that both `load_market` and the new `advisor.model.live` call.
- **A longer price window.** The bulk Yahoo download reaches back 400 calendar days instead of 100, because the features need about 260 sessions.
- **Split events for US forecasts.** For the US stocks being forecast, a small extra download brings 3 years of split events, so filed share counts and EPS line up with today's prices.
- **Failures never stop a run.** A model failure in one market is recorded in the run summary and degrades the run, but never fails it: prices and holdings still publish.

**Tech Stack:** Python 3.12, pandas, numpy, LightGBM, psycopg, yfinance; pytest; ruff.

**Spec:** `docs/superpowers/specs/2026-10-09-stock-advisor-design.md` (rev 2):
- §4.3 stages 3 (screener), 6 (features) and 7 (model);
- §5.1–§5.2;
- §8 (`predictions`, `runs.model_version`).

Also read `docs/superpowers/deferred.md`, "Plan 3c: live predictions", and Plan 3b (`docs/superpowers/plans/2026-10-21-plan-3b-model-and-backtest.md`), whose code this plan calls.

**Owner's decisions this plan relies on (2026-10-26):** a horizon whose calibration is unmeasured or more than 5 points off is unusable. It gives no P(beat), no picks and no verdicts. The active model's `metrics["usable_horizons"]` lists the usable ones.

**Prototype:** branch `plan-3c-proto` (commit `9da6573`, not for merging), run on Plan 3a's data and live Yahoo.

| Check | Result |
|---|---|
| Features on 2026-10-20 from the last 380/420/500 calendar days vs the full 8 years | Price, relative-strength and eligibility: identical for all 350 TSX and 1,352 US eligible stocks. US fundamentals differed for 9 stocks until the split factor was built from split events over a 3-year calendar, after which every feature matched |
| Live bulk download, full universe (6,644 symbols) | 400 days: 267 s, 1.76 million bars. 100 days: 210 s. Peak memory 2.75 GB |
| Live features from a 380-day window | US 2,000 stocks 5.6 s, TSX 0.4 s |

## Global Constraints

- **Training and live agree.** A live feature for day t equals the training feature for day t. The parity test in Task 1 pins this.
- **Point in time.** A filing counts from the day after it was filed. The pre-close run's bar for today is incomplete: price features use it, while volume features and eligibility use the last complete session (Task 1).
- **Usable horizons only.** `predictions` gets rows only for the active model's `metrics["usable_horizons"]`. A market whose active model lists none gets no rows (`p_beat` is NOT NULL in the schema).
- **No model, no harm.** With no active model, the screener ranks by 20-day dollar volume as today, and the market gets no forecasts. A model or prediction error is recorded per market in `summary["model"]` and makes the run at worst degraded, never failed.
- **Tests run in Docker**, from `pipeline/`: `scripts/in-docker.sh uv run pytest -q` and `scripts/in-docker.sh uv run ruff check .`. Integration tests need the `advisor-pg` container.
- **Commits:**
  - Run `git commit` in a command of its own: a plugin hook mistakes any `-n` in the same command for skipping hooks.
  - Never skip hooks.
  - End messages with the `Co-Authored-By:` trailer.
- **Never put a real email address** in code, tests or docs.

## Review Focus

1. **Training and live disagree** (window length, a calendar day only some symbols have, split events). The model was validated on training features, so any drift silently changes what it says. Covered by Task 1, `test_live_features_match_the_training_rows_on_the_same_day`.
2. **The pre-close bar.** At 3:15 PM today's volume is missing the last 45 minutes and the closing auction. Covered by Task 1, `test_a_partial_day_takes_volume_features_from_the_last_complete_session`.
3. **A split since the last filing.** Without split events, a US stock that split after its last 10-Q gets its market cap and EPS growth off by the split ratio. Covered by Task 2, `test_live_split_events_keep_market_cap_after_a_split`.
4. **An unusable horizon leaks into `predictions`** and reaches a pick or verdict in Plan 4. Covered by Task 3, `test_only_usable_horizons_are_predicted`.
5. **A broken model file or a market without a model.** Either must leave the run publishing prices. Covered by Task 5: `test_a_model_that_fails_degrades_the_run_and_prices_still_publish` and `test_a_market_without_a_model_ranks_by_dollar_volume`.

## Files

| File | Task | What it is |
|---|---|---|
| `pipeline/src/advisor/model/dataset.py`, `pipeline/src/advisor/model/live.py` + `tests/unit/test_model_live.py` | 1 | One feature step for training and live |
| `pipeline/src/advisor/model/fundamentals.py`, `pipeline/src/advisor/model/live.py` + `tests/unit/test_model_live.py`, `tests/unit/test_model_fundamentals.py` | 2 | Live fundamentals from the run's SEC facts; split events |
| `pipeline/src/advisor/model/predict.py`, `pipeline/src/advisor/models.py`, `pipeline/src/advisor/store/repo.py` + `tests/integration/test_model_predict.py` | 3 | Load the active model, predict, store |
| `pipeline/src/advisor/collectors/yfinance_bars.py`, `pipeline/src/advisor/enrich.py` + their tests | 4 | 400-day window; screener scores in the shortlist |
| `pipeline/src/advisor/run.py`, `pipeline/src/advisor/store/repo.py` + `tests/integration/test_run.py` | 5 | The run's screener and model stages |
| spec, `docs/superpowers/deferred.md`, `pipeline/README.md` | 6 | Docs |

---

### Task 1: One feature step for training and live

**Files:**
- Modify: `pipeline/src/advisor/model/dataset.py`
- Create: `pipeline/src/advisor/model/live.py`
- Test: `pipeline/tests/unit/test_model_live.py` (Task 4's `test_model_dataset.py` tests must pass unchanged)

**Interfaces:**
- Consumes: Plan 3b's `advisor.model.features` and `fundamentals` functions, `MARKETS`, `SECTOR_ETFS` and `sector_etf`.
- Produces:
  - in `advisor.model.dataset`, `feature_frames(prices: pd.DataFrame, events: pd.DataFrame, sectors: pd.DataFrame, market: Market, days: pd.DatetimeIndex, *, facts: pd.DataFrame | None = None, tickers: pd.DataFrame | None = None, split_calendar: pd.DatetimeIndex | None = None) -> FeatureFrames`. Here `prices` is Plan 3a's long layout; the calendar is the days with a benchmark close; `split_calendar` defaults to that calendar;
  - `@dataclass FeatureFrames`, with `wide: Wide`, `calendar: pd.DatetimeIndex`, `names: list[str]`, `features: dict[str, pd.DataFrame]` (full calendar for price and RS, `days` for fundamentals), `dollar_volume: pd.DataFrame` and `eligible: pd.DataFrame`;
  - `load_market` rewritten on top of `feature_frames`, with output unchanged;
  - in `advisor.model.live`:
    - `VOLUME_FEATURES = ("volume_z", "log_adv20")`;
    - `LIVE_WINDOW = timedelta(days=400)`;
    - `bars_frame(bars: Mapping[str, Sequence[DailyBar]]) -> pd.DataFrame`, the long `symbol, day, open, high, low, close, volume` layout with `day` as `date`;
    - `live_features(prices, market, day, *, sectors, partial_day, events=None, facts=None, tickers=None) -> pd.DataFrame`. It returns one row per stock (not the benchmark or ETFs), indexed by symbol, with the market's feature names (US adds fundamentals) and the columns `eligible` (bool), `dollar_volume_20` and `sector`.

- [ ] **Step 1: Write the failing tests**

`pipeline/tests/unit/test_model_live.py`:

```python
import pandas as pd
import pytest

from advisor.model.dataset import WARMUP, load_market
from advisor.model.live import LIVE_WINDOW, VOLUME_FEATURES, bars_frame, live_features
from advisor.models import DailyBar, Market
from model_data import write_market


def live_inputs(tmp_path, market):
    prices = pd.read_parquet(tmp_path / f"prices_{market}.parquet")
    sectors = pd.read_parquet(tmp_path / "sectors.parquet")
    return prices, sectors


def test_live_features_match_the_training_rows_on_the_same_day(tmp_path):
    write_market(tmp_path, Market.TSX, stocks=5, days=700)
    data = load_market(tmp_path, Market.TSX)
    day = data.calendar[WARMUP + 300]  # a sample day well inside the history
    prices, sectors = live_inputs(tmp_path, Market.TSX)
    window = prices[pd.to_datetime(prices["day"]) >= day - LIVE_WINDOW]
    live = live_features(window, Market.TSX, day, sectors=sectors, partial_day=False)
    training = data.rows[data.rows["day"] == day].set_index("symbol")
    assert set(training.index) == set(live.index[live["eligible"]])
    pd.testing.assert_frame_equal(
        live.loc[training.index, data.features], training[data.features], check_exact=False, rtol=1e-9, atol=1e-12,
    )


def test_a_partial_day_takes_volume_features_from_the_last_complete_session(tmp_path):
    write_market(tmp_path, Market.TSX, stocks=2, days=500)
    prices, sectors = live_inputs(tmp_path, Market.TSX)
    days = sorted(pd.to_datetime(prices["day"]).unique())
    today, yesterday = pd.Timestamp(days[-1]), pd.Timestamp(days[-2])
    thin = prices.copy()
    thin.loc[pd.to_datetime(thin["day"]) == today, "volume"] = 1_000.0  # 3:15 PM: most of the day's volume missing
    partial = live_features(thin, Market.TSX, today, sectors=sectors, partial_day=True)
    complete = live_features(prices, Market.TSX, yesterday, sectors=sectors, partial_day=False)
    for name in VOLUME_FEATURES:
        assert partial[name].tolist() == pytest.approx(complete[name].tolist())
    assert partial["eligible"].tolist() == complete["eligible"].tolist()
    full_today = live_features(prices, Market.TSX, today, sectors=sectors, partial_day=False)
    assert partial["ret_5"].tolist() == pytest.approx(full_today["ret_5"].tolist())  # prices use today's bar


def test_bars_become_the_training_layout():
    bars = {"X": [DailyBar(symbol="X", day=pd.Timestamp("2026-10-23").date(), open=1, high=2, low=0.5, close=1.5,
                           volume=10, source="yfinance")]}
    frame = bars_frame(bars)
    assert list(frame.columns) == ["symbol", "day", "open", "high", "low", "close", "volume"]
    assert frame.iloc[0]["close"] == 1.5


def test_a_sector_etf_yahoo_missed_leaves_its_features_missing(tmp_path):
    write_market(tmp_path, Market.TSX, stocks=2, days=400)
    prices, sectors = live_inputs(tmp_path, Market.TSX)
    gone = sectors["sector"].map({"Energy": "XEG.TO", "Financial Services": "XFN.TO"}).dropna().iloc[0]
    live = live_features(prices[prices["symbol"] != gone], Market.TSX, pd.Timestamp(prices["day"].max()),
                         sectors=sectors, partial_day=False)
    assert live["ret_5"].notna().all()  # everything else is still there
    assert live.loc[sectors.loc[sectors["sector"].map({"Energy": "XEG.TO", "Financial Services": "XFN.TO"}) == gone,
                                "symbol"], "ex_sector_21"].isna().all()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `scripts/in-docker.sh uv run pytest -q tests/unit/test_model_live.py`
Expected: FAIL with `ModuleNotFoundError: advisor.model.live`.

- [ ] **Step 3: Extract `feature_frames` and rewrite `load_market` on it**

Move `load_market`'s feature step (from `to_wide` through the fundamentals) into `feature_frames`. `load_market` keeps:
- reading the files;
- dropping the build day's bar;
- the targets, stacking, eligibility filter and columns.

The real-data split fix stays: `split_calendar` defaults to the calendar, and the factor is restricted to symbols that split. Run `tests/unit/test_model_dataset.py` and `test_model_train.py`: they must pass unchanged.

- [ ] **Step 4: Implement `advisor.model.live`** (signatures above)

Make `features.relative_strength` reindex the ETF columns (`features["ret_63"].reindex(columns=list(etfs))`) so a sector ETF Yahoo missed gives NaN sector features instead of a `KeyError`. Training never hits this: Plan 3a's build fails on a missing ETF.

`live_features` calls `feature_frames(prices, events or an empty events frame, sectors, market, DatetimeIndex([day]), facts=..., tickers=..., split_calendar=pd.bdate_range(day − 3 years, day))` and takes the `day` row.

With `partial_day`:
- compute a second time on the prices before `day`;
- take `VOLUME_FEATURES`, `eligible` and `dollar_volume_20` from the previous session's row of that second computation;
- keep every other feature from `day`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `scripts/in-docker.sh uv run pytest -q tests/unit/test_model_live.py tests/unit/test_model_dataset.py tests/unit/test_model_train.py && scripts/in-docker.sh uv run ruff check .`
Expected: PASS, ruff clean.

- [ ] **Step 6: Commit**

```bash
git add pipeline/src/advisor/model/dataset.py pipeline/src/advisor/model/live.py pipeline/tests/unit/test_model_live.py
```
```bash
git commit -m "feat: compute live features with the training code"
```

---

### Task 2: Live fundamentals and split events

**Files:**
- Modify: `pipeline/src/advisor/model/live.py`, `pipeline/src/advisor/model/fundamentals.py`
- Test: `pipeline/tests/unit/test_model_live.py`, `pipeline/tests/unit/test_model_fundamentals.py`

**Interfaces:**
- Consumes:
  - `advisor.collectors.sec_xbrl.FinancialFact` (`symbol, metric, concept, unit, start, end, value, filed, form, accession`);
  - `advisor.training.prices.download_history(symbols, start, end, *, download, sleep) -> PriceHistory`, whose `.events` holds `symbol, day, dividend, split` and which uses actions=True.
- Produces, in `advisor.model.live`:
  - `SPLIT_REACH = timedelta(days=3 * 365)`;
  - `facts_frame(facts: Sequence[FinancialFact]) -> tuple[pd.DataFrame, pd.DataFrame]`, which returns `(facts, tickers)` in Plan 3a's layout. Each symbol gets a stable synthetic `cik` (its position in the sorted symbols, as int32), and `tickers` maps symbol to cik;
  - `split_events(symbols: Sequence[str], today: date, *, download=..., sleep=...) -> pd.DataFrame`, the 3 years of split and dividend events from `download_history`.

- [ ] **Step 1: Write the failing tests**

Append to `pipeline/tests/unit/test_model_live.py`:

```python
from datetime import date

from advisor.collectors.sec_xbrl import FinancialFact
from advisor.model.live import facts_frame


def fact(metric, end, value, filed, start=None, concept="us-gaap:Revenues"):
    return FinancialFact(symbol="ZZZ", metric=metric, concept=concept, unit="USD", start=start, end=end,
                         value=value, filed=filed, form="10-Q", accession="a")


def test_the_runs_sec_facts_become_the_training_layout():
    facts, tickers = facts_frame([fact("revenue", date(2025, 12, 31), 400.0, date(2026, 2, 10), start=date(2025, 1, 1))])
    assert list(facts.columns) == ["cik", "metric", "concept", "unit", "start", "end", "value", "filed", "form", "accession"]
    assert tickers.to_dict("records") == [{"symbol": "ZZZ", "cik": facts["cik"].iloc[0]}]


def test_live_split_events_keep_market_cap_after_a_split():
    # 100 shares filed for 2025-06-30; a 4:1 split on 2025-08-01; today the close (in today's shares) is 50
    days = pd.bdate_range("2025-07-01", "2025-09-30", name="day")
    prices = pd.concat([
        pd.DataFrame({"symbol": s, "day": [d.date() for d in days], "open": 50.0, "high": 50.0, "low": 50.0,
                      "close": 50.0, "volume": 1e6}) for s in ("ZZZ", "SPY")
    ])
    facts, tickers = facts_frame([fact("shares_outstanding", date(2025, 6, 30), 100.0, date(2025, 7, 15),
                                       concept="dei:EntityCommonStockSharesOutstanding")])
    events = pd.DataFrame({"symbol": ["ZZZ"], "day": [date(2025, 8, 1)], "dividend": [0.0], "split": [4.0]})
    sectors = pd.DataFrame({"symbol": ["ZZZ"], "sector": [None], "industry": [None]})
    row = live_features(prices, Market.US, days[-1], sectors=sectors, partial_day=False,
                        events=events, facts=facts, tickers=tickers).loc["ZZZ"]
    assert row["log_mcap"] == pytest.approx(np.log(50.0 * 400))
```

(Add `import numpy as np` at the top of the file.)

Append to `pipeline/tests/unit/test_model_fundamentals.py` the EPS rule from deferred.md. ASC 260 restates reported EPS for a split between the period end and the filing, so the factor is read at the filing date:

```python
def test_eps_is_put_on_todays_shares_with_the_split_factor_at_filing():
    days = pd.DatetimeIndex(["2024-12-02"], name="day")
    facts = frame(
        fact("eps_diluted", "2023-01-01", "2023-12-31", 4.0, "2024-02-10", concept="us-gaap:EarningsPerShareDiluted"),
        fact("eps_diluted", "2022-01-01", "2022-12-31", 2.0, "2023-02-10", concept="us-gaap:EarningsPerShareDiluted"),
    )
    close = pd.DataFrame({"X": [10.0]}, index=days)
    # a 2:1 split on 2024-01-15: after FY2023's period end, before its filing, so FY2023's 4.0 is already
    # on post-split shares, while FY2022's 2.0 (filed 2023) is not
    splits = pd.DataFrame({"X": [2.0, 1.0, 1.0]}, index=pd.DatetimeIndex(["2023-12-29", "2024-02-09", "2024-12-02"]))
    f = fundamental_features(facts, pd.DataFrame({"symbol": ["X"], "cik": [1]}), days, close, splits)
    assert f["eps_growth"]["X"].iloc[0] == pytest.approx(4.0 / (2.0 / 2.0) - 1)  # 3.0
```

- [ ] **Step 2: Run them to verify they fail**

Run: `scripts/in-docker.sh uv run pytest -q tests/unit/test_model_live.py tests/unit/test_model_fundamentals.py`
Expected:
- `ImportError` for `facts_frame`;
- the EPS test fails, because the period-end factor gives 4.0/2 ÷ (2.0/2) − 1 = 1.0.

- [ ] **Step 3: Implement** `facts_frame` and `split_events` (signatures above)

In `fundamentals.py`, read EPS's split factor at the filing date (`filed`, not the period end) for both the current and year-ago EPS. Shares stay at their period end: a cover-page share count is as of its date.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `scripts/in-docker.sh uv run pytest -q tests/unit/test_model_live.py tests/unit/test_model_fundamentals.py tests/unit/test_model_dataset.py && scripts/in-docker.sh uv run ruff check .`
Expected: PASS, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add pipeline/src/advisor/model/live.py pipeline/src/advisor/model/fundamentals.py pipeline/tests/unit/test_model_live.py pipeline/tests/unit/test_model_fundamentals.py
```
```bash
git commit -m "feat: live fundamentals from the run's SEC facts, with split events"
```

---

### Task 3: Load the active model, predict and store

**Files:**
- Create: `pipeline/src/advisor/model/predict.py`
- Modify: `pipeline/src/advisor/models.py` (add `PredictionRow`), `pipeline/src/advisor/store/repo.py`
- Test: `pipeline/tests/integration/test_model_predict.py`

**Interfaces:**
- Consumes: `repo.active_model`, `repo.load_model_files`, `train.from_files`, `FinalModel.predict` / `.screen`, `weekly.KIND`, and `MARKETS[market].benchmark`.
- Produces:
  - in `advisor.models`: `@dataclass(frozen=True) class PredictionRow`, with `symbol: str`, `horizon_days: int`, `q10: float`, `q50: float`, `q90: float`, `p_beat: float`, `benchmark: str`, `model_version: str`;
  - in `advisor.store.repo`: `write_predictions(conn, run_id: int, rows: Sequence[PredictionRow]) -> None`, for stocks;
  - in `advisor.model.predict`:
    - `@dataclass(frozen=True) class ActiveModel`, with `version: str`, `model: FinalModel` and `usable: tuple[int, ...]`;
    - `load_active(conn, market: Market) -> ActiveModel | None`. It returns None when there is no active model, and also when its `usable_horizons` is empty;
    - `predict_rows(active: ActiveModel, features: pd.DataFrame, benchmark: str) -> list[PredictionRow]`, for usable horizons only, skipping rows whose quantiles or p_beat are NaN;
    - `screen_scores(active: ActiveModel, features: pd.DataFrame) -> pd.Series`, indexed by symbol.

- [ ] **Step 1: Write the failing tests**

`pipeline/tests/integration/test_model_predict.py`:

```python
from datetime import UTC, datetime

import pandas as pd
import pytest

from advisor.model.dataset import load_market
from advisor.model.predict import load_active, predict_rows, screen_scores
from advisor.model.train import PARAMS, TrainConfig, fit_final, to_files, walk_forward
from advisor.models import Market
from advisor.store import repo
from model_data import write_market

FAST = TrainConfig(horizons=(5, 63), rounds=40, params={**PARAMS, "min_data_in_leaf": 50, "num_threads": 2})


@pytest.fixture(scope="module")
def trained(tmp_path_factory):
    out = tmp_path_factory.mktemp("tsx")
    write_market(out, Market.TSX, stocks=20, days=1100)
    data = load_market(out, Market.TSX)
    return data, fit_final(data, walk_forward(data, FAST), FAST)


def store(db, model, usable):
    at = datetime(2026, 10, 24, 10, tzinfo=UTC)
    repo.save_model(db, "stock_tsx-1", "stock_tsx", at, {"usable_horizons": usable}, 3.0, to_files(model))
    repo.activate_model(db, "stock_tsx", "stock_tsx-1")


def test_only_usable_horizons_are_predicted(db, trained):
    data, model = trained
    store(db, model, [63])
    active = load_active(db, Market.TSX)
    x = data.rows.drop_duplicates("symbol").set_index("symbol")[data.features]
    rows = predict_rows(active, x, "XIU.TO")
    assert {r.horizon_days for r in rows} == {63}
    assert all(r.q10 <= r.q50 <= r.q90 and 0 <= r.p_beat <= 1 and r.model_version == "stock_tsx-1" for r in rows)
    run_id = db.execute("insert into runs (kind, et_date) values ('pre_open', '2026-10-26') returning id").fetchone()["id"]
    repo.write_predictions(db, run_id, rows)
    assert db.execute("select count(*) as n from predictions where run_id = %s", (run_id,)).fetchone()["n"] == len(x)


def test_a_model_without_usable_horizons_gives_no_forecasts(db, trained):
    _, model = trained
    store(db, model, [])
    assert load_active(db, Market.TSX) is None
    assert load_active(db, Market.US) is None  # no model at all


def test_the_screener_scores_every_stock(db, trained):
    data, model = trained
    store(db, model, [5, 63])
    x = data.rows.drop_duplicates("symbol").set_index("symbol")[data.features]
    scores = screen_scores(load_active(db, Market.TSX), x)
    assert list(scores.index) == list(x.index) and scores.between(0, 1).all()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `scripts/in-docker.sh uv run pytest -q tests/integration/test_model_predict.py`
Expected: FAIL with `ModuleNotFoundError: advisor.model.predict`.

- [ ] **Step 3: Implement** `PredictionRow`, `repo.write_predictions` (an `executemany` into `predictions` with `asset_type = 'stock'`) and `advisor.model.predict` (signatures above)

`load_active` reads `usable_horizons` from the stored metrics and keeps only horizons the model has.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `scripts/in-docker.sh uv run pytest -q tests/integration/test_model_predict.py && scripts/in-docker.sh uv run ruff check .`
Expected: PASS, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add pipeline/src/advisor/model/predict.py pipeline/src/advisor/models.py pipeline/src/advisor/store/repo.py pipeline/tests/integration/test_model_predict.py
```
```bash
git commit -m "feat: load each market's active model and store its forecasts"
```

---

### Task 4: A 400-day price window, and screener scores in the shortlist

**Files:**
- Modify: `pipeline/src/advisor/collectors/yfinance_bars.py`, `pipeline/src/advisor/enrich.py`
- Test: `pipeline/tests/unit/test_yfinance_bars.py` (or the collector's existing test file), `pipeline/tests/unit/test_enrich.py`

**Interfaces:**
- Produces:
  - `yfinance_bars.LOOKBACK = timedelta(days=400)`, which is `live.LIVE_WINDOW`; import one from the other so they can't drift;
  - `ranked_shortlist(passed, exclude, size=SHORTLIST_SIZE, scores: Mapping[str, float] | None = None) -> list[str]`. With `scores`, it sorts by score (highest first), then dollar volume, then symbol; a symbol without a score comes after every scored one. Without `scores`, it behaves as today.

- [ ] **Step 1: Write the failing tests**

In the collector's test file:

```python
def test_bars_reach_back_far_enough_for_the_models_features():
    asked = []

    def download(tickers, start, end):
        asked.append(start)
        return pd.DataFrame()

    with contextlib.suppress(Exception):  # an empty answer may raise; only the window matters here
        YFinanceBars(download=download).fetch(["AAPL", "MSFT"], datetime(2026, 10, 26, 13, tzinfo=UTC))
    assert asked == [date(2025, 9, 21)]  # 400 days before 2026-10-26 ET
```

(Add `import contextlib`, and any of `YFinanceBars`, `pd`, `datetime`, `UTC` and `date` the file doesn't import yet.)

In `pipeline/tests/unit/test_enrich.py`:

```python
def test_the_screener_score_ranks_the_shortlist_when_there_is_one():
    rows = [ScreenRow("A", 10, 9e6, 300, date(2026, 10, 23)), ScreenRow("B", 10, 5e6, 300, date(2026, 10, 23)),
            ScreenRow("C", 10, 7e6, 300, date(2026, 10, 23))]
    assert ranked_shortlist(rows, [], 3) == ["A", "C", "B"]  # dollar volume, as before
    assert ranked_shortlist(rows, [], 3, scores={"B": 0.9, "C": 0.4}) == ["B", "C", "A"]  # A has no score: last
```

- [ ] **Step 2: Run them to verify they fail**

Run: `scripts/in-docker.sh uv run pytest -q tests/unit/test_enrich.py tests/unit/test_yfinance_bars.py`
Expected: FAIL. The start date is 100 days back, and `ranked_shortlist` has no `scores` argument.

- [ ] **Step 3: Implement** both changes (interfaces above)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `scripts/in-docker.sh uv run pytest -q && scripts/in-docker.sh uv run ruff check .`
Expected: all pass, ruff clean. Existing run tests feed 70-bar histories, which are unaffected.

- [ ] **Step 5: Commit**

```bash
git add pipeline/src/advisor/collectors/yfinance_bars.py pipeline/src/advisor/enrich.py pipeline/tests/unit/test_enrich.py pipeline/tests/unit/test_yfinance_bars.py
```
```bash
git commit -m "feat: a 400-day price window and screener-ranked shortlists"
```

---

### Task 5: The run's screener and model stages

**Files:**
- Modify: `pipeline/src/advisor/run.py`, `pipeline/src/advisor/store/repo.py` (`finish_run` gains `model_version: str | None = None`)
- Test: `pipeline/tests/integration/test_run.py`

**Interfaces:**
- Consumes:
  - Tasks 1–4;
  - `RunDeps`, with a new optional field `split_download: Downloader | None = None`. Tests leave it None, so no split events are fetched; the run passes it as `download=` to `live.split_events` when set, and `run.py`'s `main` sets the real one;
  - `SECTOR_ETFS`.
- Produces, in `run.py`:
  - **Phase 1 fetches the sector ETFs** with the benchmarks: `[*priority, *BENCHMARKS, *all sector ETFs]`.
  - **Phase 2.5, the screener:** for each market with an active model, live features (price and relative strength) for the passed symbols, then `screen_scores`, then `ranked_shortlist(..., scores=...)`. A market without one ranks as today.
  - **Phase 3.5, after enrichment:**
    1. For each market with an active model, live features for its priority and ranked symbols. US gets `facts_frame` from `results["sec_xbrl"].records` and `split_events` for those US symbols, best-effort: a failure means no events and a note.
    2. Then `predict_rows`, `repo.write_predictions`, and `repo.merge_features_live` with each stock's model features (JSON-safe numbers; NaN dropped).
  - **The day and the partial bar:** the feature day is each market's last bar day. `partial_day` is true when the run is `pre_close` or `early_close` and that day is the run's ET date.
  - **`summary["model"]`**, per market: `{"version", "screened", "predicted", "horizons"}`, or `{"skipped": "no active model"}`, or `{"failed": "<Type>: <message>"[:200]}`.
  - **`runs.model_version`** is the active versions joined with `,`, or null.
  - **Status:** a market whose model stage failed makes the run at least degraded, and never failed.

- [ ] **Step 1: Write the failing tests**

Append to `pipeline/tests/integration/test_run.py` (it already has `make_deps`, `run_row`, `market_features`, `hold`, `EVERYONE`, `SMALL`):

```python
from advisor.model.dataset import load_market
from advisor.model.train import PARAMS, TrainConfig, fit_final, to_files, walk_forward
from model_data import write_market

FAST = TrainConfig(horizons=(5, 63), rounds=40, params={**PARAMS, "min_data_in_leaf": 50, "num_threads": 2})


@pytest.fixture(scope="module")
def tsx_model_files(tmp_path_factory):
    out = tmp_path_factory.mktemp("tsx-model")
    write_market(out, Market.TSX, stocks=20, days=1100)
    data = load_market(out, Market.TSX)
    return to_files(fit_final(data, walk_forward(data, FAST), FAST))


def activate_tsx(db, files, usable=(63,)):
    repo.save_model(db, "stock_tsx-1", "stock_tsx", NOW, {"usable_horizons": list(usable)}, 3.0, files)
    repo.activate_model(db, "stock_tsx", "stock_tsx-1")


def test_the_active_model_forecasts_the_tsx_shortlist_and_holdings(db, tmp_path, tsx_model_files):
    activate_tsx(db, tsx_model_files)
    hold(db, "RY.TO")
    outcome = execute_run(make_deps(db, tmp_path), RunKind.PRE_OPEN, NOW, min_universe=SMALL)
    assert outcome.status is RunStatus.SUCCESS
    rows = db.execute("select symbol, horizon_days, benchmark, model_version from predictions"
                      " where run_id = %s order by symbol", (outcome.run_id,)).fetchall()
    assert {r["symbol"] for r in rows} == {"RY.TO", "TD.TO"}
    assert {(r["horizon_days"], r["benchmark"], r["model_version"]) for r in rows} == {(63, "XIU.TO", "stock_tsx-1")}
    assert outcome.summary["model"]["TSX"]["predicted"] == 2
    assert outcome.summary["model"]["US"] == {"skipped": "no active model"}
    assert run_row(db, outcome.run_id)["model_version"] == "stock_tsx-1"
    assert "ret_5" in market_features(db, outcome.run_id)["RY.TO"]


def test_a_market_without_a_model_ranks_by_dollar_volume(db, tmp_path):
    outcome = execute_run(make_deps(db, tmp_path), RunKind.PRE_OPEN, NOW, min_universe=SMALL)
    assert outcome.status is RunStatus.SUCCESS
    assert outcome.summary["model"] == {"US": {"skipped": "no active model"}, "TSX": {"skipped": "no active model"}}
    assert db.execute("select count(*) as n from predictions").fetchone()["n"] == 0
    assert run_row(db, outcome.run_id)["model_version"] is None


def test_a_model_that_fails_degrades_the_run_and_prices_still_publish(db, tmp_path, tsx_model_files):
    activate_tsx(db, {**tsx_model_files, "h63_q50": b"not a model"})
    outcome = execute_run(make_deps(db, tmp_path), RunKind.PRE_OPEN, NOW, min_universe=SMALL)
    assert outcome.status is RunStatus.DEGRADED
    assert outcome.summary["model"]["TSX"]["failed"].startswith(("OSError", "LightGBMError", "BadGzipFile", "ValueError"))
    assert run_row(db, outcome.run_id)["published"] is True
```

- [ ] **Step 2: Run them to verify they fail**

Run: `scripts/in-docker.sh uv run pytest -q tests/integration/test_run.py -k "model or forecast or dollar_volume"`
Expected: FAIL. There's no `summary["model"]` and no predictions.

- [ ] **Step 3: Implement the stages** (interfaces above)

Wrap each market's model work in its own `try`. Load the models once, before the screener, so a load failure is recorded once and both stages skip that market. Existing run tests must keep passing. Their summaries gain a `"model"` key: update the one test that compares the whole summary dict, adding `"model": {"US": {"skipped": "no active model"}, "TSX": {"skipped": "no active model"}}`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `scripts/in-docker.sh uv run pytest -q && scripts/in-docker.sh uv run ruff check .`
Expected: all pass, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add pipeline/src/advisor/run.py pipeline/src/advisor/store/repo.py pipeline/tests/integration/test_run.py
```
```bash
git commit -m "feat: rank the shortlist with the screener and forecast every run"
```

---

### Task 6: Docs

**Files:**
- Modify: `docs/superpowers/specs/2026-10-09-stock-advisor-design.md`, `docs/superpowers/deferred.md`, `pipeline/README.md`

- [ ] **Step 1: Spec**

- **Revision history:** add a line for 2026-10-26, Plan 3c.
- **§4.3:**
  - Stage 3: the screener model ranks survivors, falling back to dollar volume without an active model, and the bulk window is 400 calendar days.
  - Stage 7: forecasts are written for usable horizons only. A model failure degrades the run per market.
- **§3 Scheduling:** the pre-close run's price features use today's partial bar, while volume features and eligibility use the last complete session.
- **§8:** `runs.model_version` holds the active versions, comma-joined.

- [ ] **Step 2: deferred.md**

- Remove the Plan 3c section's done items.
- Keep for Plan 4: picks, verdicts and actions read `predictions`, together with `features_live`'s model features (ATR for stops).
- Record the measured costs:
  - the 400-day window adds about a minute per run (267 s vs 210 s for 6,644 symbols);
  - peak memory is 2.75 GB.

- [ ] **Step 3: README**

Add one line under the run section: forecasts need an active model (from `train.yml`), and each run's `summary.model` says what it did.

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-10-09-stock-advisor-design.md docs/superpowers/deferred.md pipeline/README.md
```
```bash
git commit -m "docs: record Plan 3c's live predictions"
```
