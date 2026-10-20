# Plan 3a: Training History — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A weekly `train.yml` job that rebuilds, from scratch, the data the stock model trains on: about 8 years of daily bars for both markets (with benchmarks and sector ETFs), Yahoo sectors, US fundamentals as filed, and macro series.

**Architecture:**
- **One command.** `python -m advisor.training.build --out DIR` writes Parquet files and a `manifest.json` into DIR. It uses a new package, `advisor.training`, with one module per data set: `prices`, `macro`, `fundamentals`, `sectors` and `build`.
- **Rebuilt each week, not stored** (owner's decision, 2026-10-20). Plan 3b trains in the same job from DIR. If a source fails that week, the build fails, the job fails, and the active model stays in use.
- **Reuses the live pipeline's pieces:**
  - Yahoo's batched `yf.download` and its share-class mapping;
  - the FRED and Bank of Canada parsers;
  - SEC access through `SecEdgar`, gaining a streaming download;
  - the `sec_xbrl` concept table, factored into a shared generator so live and training fundamentals keep one schema.
- **Sectors.** They come from Yahoo's screener, about 300 requests. They are also written to `symbols.sector` and `symbols.industry`.

**Tech Stack:** Python 3.12, pandas, pyarrow (new), httpx, yfinance, psycopg; pytest; ruff.

**Spec:** `docs/superpowers/specs/2026-10-09-stock-advisor-design.md` (rev 2): §3 (architecture, `train.yml`), §4.3 stage 2 (sectors), §5.1 (features this data serves), §5.2 (training data). Also read `docs/superpowers/deferred.md`, "Plan 3", and the research in `.superpowers/research/plan-3a/` (git-ignored, on the owner's machine): `prices.md`, `fundamentals.md`, `sectors.md`, `storage.md`.

**Owner's decisions (2026-10-20):**
- Plan 3 is split into 3a (this plan: training history), 3b (features, models, walk-forward backtest, promotion) and 3c (live predictions). Plan 4 makes the picks.
- The first model uses only the "fast path" feature groups: price/volume, relative strength, macro and US fundamentals.
- The training data is rebuilt every week rather than stored in Supabase Storage, so no storage key or new GitHub secret is needed.

**Prototype:** every file below was built and tested on branch `plan-3a-proto` (2026-10-20): 790 pipeline tests pass and ruff is clean. A live `--limit 50 --no-db` build took 4 min 40 s. Per step:

| Step | Time | Result |
|---|---|---|
| Yahoo sector screen | 171 s | 1 of 100 stocks unclassified |
| Prices | about 3 s per market | 98,712 US rows and 96,717 TSX rows (2.2 and 1.9 MB), no stock missing |
| SEC download | 90 s for 1.4 GB | 43,013 facts for 50 companies |
| Macro | 5 s | 21,966 observations |

The research extrapolates a full build to roughly 15–20 minutes, with about 250 MB of price Parquet.

## Global Constraints

- **Keyless data sources** (spec R7). SEC requests send the owner's contact from `SEC_USER_AGENT`, through `SecEdgar` and its rate limiter (`SEC_PER_MINUTE`).
- **Point in time** (spec design rule 3). Facts keep every re-report with its `filed` date; nothing is coalesced at build time.
- **Never fabricate.** A value a company doesn't report stays absent: banks have no gross profit, and some issuers have no EPS.
- **Tests run in Docker**, from `pipeline/`: `scripts/in-docker.sh uv run pytest -q` and `scripts/in-docker.sh uv run ruff check .`. Integration tests need the `advisor-pg` container running.
- **Commits:**
  - Run `git commit` in a command of its own: a plugin hook mistakes any `-n` flag in the same command for skipping hooks.
  - Never skip hooks.
  - End messages with the `Co-Authored-By:` trailer.
- **Never put a real email address** in code, tests or docs. Tests use `stock-advisor test@example.com`.

## Review Focus

1. **Yahoo throttling, or a dead symbol.** Three empty downloads in a row stop the download with `YahooThrottled`. A market with more than 20% of its stocks missing fails the build, and so does any missing benchmark or sector ETF. A few missing stocks (delistings) are only listed in the manifest. Covered by:
   - Task 1, `test_three_empty_downloads_in_a_row_mean_yahoo_is_throttling`;
   - Task 5, `test_yahoo_missing_many_stocks_fails_the_build` and `test_a_missing_etf_fails_the_build`.
2. **Restated or repeated facts.** Each re-report stays a separate row with its own `filed`, so a past day sees only what was public then. Covered by Task 3, `test_every_re_report_keeps_its_own_filing_date`.
3. **Share classes.** BRK.B is asked from Yahoo as BRK-B and from SEC as BRK-B, and GOOG and GOOGL share one CIK. Covered by:
   - Task 1, `test_a_wide_download_becomes_one_row_per_symbol_and_day`;
   - Task 3, `test_share_classes_map_to_their_company`;
   - Task 4, `test_the_universe_is_matched_in_yahoos_form`.
4. **A screener that refuses, or a week with a partial screen.** More than 10% failed queries fail the build. A stock unclassified this week keeps last week's sector in `symbols`. Covered by Task 4: `test_a_refusing_screener_fails_rather_than_leaving_the_universe_unclassified` and `test_sectors_are_set_on_known_stocks_and_kept_when_unclassified`.
5. **A dropped 1.4 GB download, or a truncated universe directory.** The download restarts up to three times. A universe smaller than the market's `min_universe` fails the full build. Covered by:
   - Task 3, `test_a_dropped_download_is_tried_again`;
   - Task 5, `test_a_short_universe_fails_the_full_build`.

**Known limits** (recorded in `deferred.md` for Plan 3b):
- **Survivorship.** The data covers only stocks listed today, since Yahoo has nothing for delisted tickers and SEC's ticker map is current-only.
- **Short series.** FRED's HY spread starts in 2023, and XLC in June 2018.
- **No analyst estimates.** XBRL carries none, so "surprise" has to be self-derived.

## Files

| File | Task | What it is |
|---|---|---|
| `pipeline/pyproject.toml`, `pipeline/uv.lock` | 1 | pyarrow, for Parquet |
| `pipeline/src/advisor/training/__init__.py`, `prices.py` + `tests/unit/test_training_prices.py` | 1 | 8 years of bars from Yahoo, as a long frame |
| `pipeline/src/advisor/training/macro.py` + `tests/unit/test_training_macro.py` | 2 | FRED and Bank of Canada history |
| `pipeline/src/advisor/collectors/sec_xbrl.py`, `sec.py`, `pipeline/src/advisor/training/fundamentals.py` + `tests/unit/test_training_fundamentals.py` | 3 | Shared fact generator, streaming download, bulk-zip reduction |
| `pipeline/src/advisor/training/sectors.py`, `pipeline/src/advisor/store/repo.py` + `tests/unit/test_training_sectors.py`, `tests/integration/test_repo.py` | 4 | Yahoo sectors and sector ETFs |
| `pipeline/src/advisor/training/build.py` + `tests/unit/test_training_build.py`, `.github/workflows/train.yml` | 5 | The build command and the weekly job |
| `docs/superpowers/specs/2026-10-09-stock-advisor-design.md`, `docs/superpowers/deferred.md` | 6 | Docs |

---

### Task 1: Download eight years of bars from Yahoo

**Files:**
- Modify: `pipeline/pyproject.toml`, `pipeline/uv.lock`
- Create: `pipeline/src/advisor/training/__init__.py` (empty), `pipeline/src/advisor/training/prices.py`
- Test: `pipeline/tests/unit/test_training_prices.py`

**Interfaces:**
- Consumes, from `advisor.collectors.yfinance_bars`: `yahoo_download`, the `Downloader` type `(tickers, start, end) -> DataFrame`, `to_yahoo`, `SYMBOLS_PER_DOWNLOAD` (100) and `MAX_CONSECUTIVE_EMPTY` (3). Also `check_deadline` from `collectors.base`.
- Produces, in `advisor.training.prices` (Task 5 uses all of these):
  - `HISTORY_YEARS = 8`, `PAUSE_SECONDS = 3.0`, `PRICE_COLUMNS = ["open", "high", "low", "close"]`, `COLUMNS = ["symbol", "day", *PRICE_COLUMNS, "volume"]`;
  - `class YahooThrottled(Exception)`;
  - `@dataclass(frozen=True) class PriceHistory`, with fields `bars: DataFrame` and `missing: list[str]`;
  - `history_start(today: date, years: int = HISTORY_YEARS) -> date`, which is `today - round(years * 365.25)` days;
  - `bars_frame(frame, yahoo_to_symbol) -> DataFrame`;
  - `download_history(symbols, start, end, *, download=yahoo_download, sleep=time.sleep, pause=PAUSE_SECONDS) -> PriceHistory`.

- [ ] **Step 1: Add pyarrow**

Run (from `pipeline/`): `scripts/in-docker.sh uv add "pyarrow>=17"`
Expected: `+ pyarrow==…`. `pyproject.toml` gains `"pyarrow>=17",`, and `uv.lock` is updated.

- [ ] **Step 2: Write the failing tests**

`pipeline/tests/unit/test_training_prices.py`:

```python
from datetime import date

import numpy as np
import pandas as pd
import pytest

from advisor.training.prices import (
    COLUMNS,
    YahooThrottled,
    bars_frame,
    download_history,
    history_start,
)

FIELDS = ["Open", "High", "Low", "Close", "Volume"]
DAYS = pd.to_datetime(["2026-10-15", "2026-10-16"])


def yahoo_frame(tickers: dict[str, list[list[float]]]) -> pd.DataFrame:
    """yf.download's wide frame: one (ticker, field) column per pair, one row per trading day."""
    columns = pd.MultiIndex.from_product([list(tickers), FIELDS], names=["Ticker", "Price"])
    rows = [sum((tickers[t][i] for t in tickers), []) for i in range(len(DAYS))]
    return pd.DataFrame(rows, index=pd.Index(DAYS, name="Date"), columns=columns)


def test_eight_years_back_from_today():
    assert history_start(date(2026, 10, 20)) == date(2018, 10, 20)


def test_a_wide_download_becomes_one_row_per_symbol_and_day():
    frame = yahoo_frame({
        "BRK-B": [[500, 505, 498, 503.5, 3_000_000], [503, 510, 501, 509, 2_500_000]],
        "AAPL": [[340, 345, 338, 343, 50_000_000], [np.nan, np.nan, np.nan, np.nan, np.nan]],
    })
    bars = bars_frame(frame, {"BRK-B": "BRK.B", "AAPL": "AAPL"})
    assert list(bars.columns) == COLUMNS
    assert list(bars.itertuples(index=False, name=None)) == [
        ("AAPL", date(2026, 10, 15), 340.0, 345.0, 338.0, 343.0, 50_000_000),
        ("BRK.B", date(2026, 10, 15), 500.0, 505.0, 498.0, 503.5, 3_000_000),
        ("BRK.B", date(2026, 10, 16), 503.0, 510.0, 501.0, 509.0, 2_500_000),
    ]  # AAPL's empty day is dropped, and BRK-B is the pipeline's BRK.B
    assert {str(bars[c].dtype) for c in ("open", "high", "low", "close")} == {"float32"}


def test_bars_with_a_non_positive_price_are_dropped():
    frame = yahoo_frame({"X": [[1.0, 1.1, 0.0, 1.05, 100], [1.0, 1.2, 0.9, 1.1, 200]]})
    assert list(bars_frame(frame, {"X": "X"})["day"]) == [date(2026, 10, 16)]


def test_a_single_ticker_download_has_flat_columns():
    flat = yahoo_frame({"RY.TO": [[150, 151, 149, 150.5, 1e6], [150.5, 152, 150, 151, 1.2e6]]})["RY.TO"]
    assert list(bars_frame(flat, {"RY.TO": "RY.TO"})["symbol"]) == ["RY.TO", "RY.TO"]


def test_symbols_are_downloaded_a_hundred_at_a_time_with_a_pause_between():
    asked, pauses = [], []

    def download(tickers, start, end):
        asked.append((len(tickers), start, end))
        return yahoo_frame({t: [[1, 1, 1, 1, 10], [1, 1, 1, 1, 10]] for t in tickers[:1]})

    symbols = [f"S{i:03d}" for i in range(250)]
    history = download_history(
        symbols, date(2018, 10, 20), date(2026, 10, 19), download=download, sleep=pauses.append, pause=2.0
    )
    assert asked == [(100, date(2018, 10, 20), date(2026, 10, 20))] * 2 + [(50, date(2018, 10, 20), date(2026, 10, 20))]
    assert pauses == [2.0, 2.0]
    assert sorted(set(history.bars["symbol"])) == ["S000", "S100", "S200"]
    assert len(history.missing) == 247 and history.missing[0] == "S001"


def test_three_empty_downloads_in_a_row_mean_yahoo_is_throttling():
    calls = []

    def download(tickers, start, end):
        calls.append(tickers)
        return pd.DataFrame() if len(calls) > 1 else yahoo_frame({tickers[0]: [[1, 1, 1, 1, 1]] * 2})

    with pytest.raises(YahooThrottled, match="3 Yahoo downloads"):
        download_history([f"S{i:03d}" for i in range(500)], date(2018, 1, 1), date(2026, 1, 1),
                         download=download, sleep=lambda s: None)
    assert len(calls) == 4  # the 5th download is never sent


def test_the_long_frame_round_trips_through_parquet(tmp_path):
    frame = yahoo_frame({"AAPL": [[340, 345, 338, 343, 5e7], [343, 346, 341, 345, 4e7]]})
    bars = bars_frame(frame, {"AAPL": "AAPL"})
    bars.to_parquet(tmp_path / "prices.parquet", compression="zstd", index=False)
    back = pd.read_parquet(tmp_path / "prices.parquet")
    assert back["close"].tolist() == [343.0, 345.0]
    assert list(back.columns) == COLUMNS
```

- [ ] **Step 3: Run them and see them fail**

Run: `scripts/in-docker.sh uv run pytest -q tests/unit/test_training_prices.py`
Expected: `1 error during collection`: `ModuleNotFoundError: No module named 'advisor.training'`.

- [ ] **Step 4: Write `advisor/training/prices.py`**

The module docstring should say three things:
- the whole history is downloaded again each week, because Yahoo rescales old closes after every split and dividend;
- bars are adjusted (`auto_adjust`), so returns are total returns;
- several empty downloads in a row mean throttling.

The functions:
- **`bars_frame`** turns yf.download's wide frame, with (ticker, field) columns, into long rows:
  - Use `frame.stack(level=0, future_stack=True)`, then reset the index.
  - Map each ticker to the pipeline's symbol, and drop unmapped tickers and rows with a missing or non-positive open/high/low/close.
  - Dtypes: `symbol` as `string`, `day` as `datetime.date`, prices as `float32`, and `volume` as `int64` (NaN becomes 0, clipped at 0).
  - Sort by symbol, then day.
  - An empty or `None` frame gives an empty frame with the same columns. A single ticker's flat columns are wrapped under its name first, as `yfinance_bars.parse_frame` does.
- **`download_history`**:
  - Deduplicate the symbols, keeping their order.
  - Ask `SYMBOLS_PER_DOWNLOAD` symbols per request, in Yahoo's form, with `end + 1 day`, because yfinance's end is exclusive.
  - Call `check_deadline()` and then `sleep(pause)` before every request except the first.
  - Raise `YahooThrottled(f"{n} Yahoo downloads in a row came back empty")` once `MAX_CONSECUTIVE_EMPTY` requests in a row return no bars.
  - `missing` lists the requested symbols without a single bar, in request order.

- [ ] **Step 5: Run the tests**

Run: `scripts/in-docker.sh uv run pytest -q tests/unit/test_training_prices.py`
Expected: `7 passed`.

Run: `scripts/in-docker.sh uv run pytest -q`, then `scripts/in-docker.sh uv run ruff check .`
Expected: `772 passed` (765 before this plan), then `All checks passed!`.

- [ ] **Step 6: Commit**

```bash
git add pipeline/pyproject.toml pipeline/uv.lock pipeline/src/advisor/training pipeline/tests/unit/test_training_prices.py
git commit -m "feat: download eight years of daily bars for training"
```

---

### Task 2: Fetch the macro series' history

**Files:**
- Create: `pipeline/src/advisor/training/macro.py`
- Test: `pipeline/tests/unit/test_training_macro.py`

**Interfaces:**
- Consumes:
  - `fred.SERIES`, `fred.FRED_URL` and `fred.parse_csv(series, text, start, end)`;
  - `boc_valet.SERIES`, `boc_valet.VALET_URL` and `boc_valet.parse_observations(payload, series)`;
  - `get_with_retries` and `check_deadline` (`collectors.base`);
  - `SeriesObservation` (`collectors.series`).
- Produces: `COLUMNS = ["series", "day", "value"]` and `macro_history(client, start, end, limiter=None) -> DataFrame`, sorted by series, then day.

- [ ] **Step 1: Write the failing tests**

`pipeline/tests/unit/test_training_macro.py`:

```python
import json
from datetime import date

import httpx
import pytest

from advisor.collectors import boc_valet, fred
from advisor.training.macro import COLUMNS, macro_history

START, END = date(2026, 4, 1), date(2026, 10, 15)


def sources(fixtures_dir, asked: list[httpx.Request], fred_missing: str | None = None) -> httpx.Client:
    """FRED and the Bank of Canada answering from the live collectors' recorded fixtures."""
    valet = json.loads((fixtures_dir / "boc" / "valet_observations_recent10.json").read_text(encoding="utf-8"))

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(request)
        if request.url.host == "fred.stlouisfed.org":
            series = request.url.params["id"]
            if series == fred_missing:
                return httpx.Response(200, text=f"observation_date,{series}\n")
            text = (fixtures_dir / "fred" / f"fred_{series}.csv").read_text(encoding="utf-8")
            return httpx.Response(200, text=text)
        return httpx.Response(200, json=valet)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_every_live_series_is_fetched_from_the_start(fixtures_dir):
    asked: list[httpx.Request] = []
    with sources(fixtures_dir, asked) as client:
        frame = macro_history(client, START, END)
    assert list(frame.columns) == COLUMNS
    assert set(frame["series"]) == set(fred.SERIES) | set(boc_valet.SERIES)
    fred_asks = [r for r in asked if r.url.host == "fred.stlouisfed.org"]
    assert [r.url.params["id"] for r in fred_asks] == list(fred.SERIES)
    assert {r.url.params["cosd"] for r in fred_asks} == {"2026-04-01"}
    valet_ask = next(r for r in asked if r.url.host != "fred.stlouisfed.org")
    assert (valet_ask.url.params["start_date"], valet_ask.url.params["end_date"]) == ("2026-04-01", "2026-10-15")
    assert frame["day"].min() >= START and frame["day"].max() <= END
    assert frame.equals(frame.sort_values(["series", "day"], ignore_index=True))


def test_a_series_without_values_fails_the_build(fixtures_dir):
    with sources(fixtures_dir, [], fred_missing="VIXCLS") as client, pytest.raises(ValueError, match="VIXCLS"):
        macro_history(client, START, END)
```

- [ ] **Step 2: Run them and see them fail**

Run: `scripts/in-docker.sh uv run pytest -q tests/unit/test_training_macro.py`
Expected: `1 error during collection`: `ModuleNotFoundError: No module named 'advisor.training.macro'`.

- [ ] **Step 3: Write `advisor/training/macro.py`**

Fetch the series in this order:
1. Each FRED series, in `fred.SERIES` order. Send one request per series with `params={"id": series, "cosd": start.isoformat()}`, and call `check_deadline()` before each.
2. One Bank of Canada request for all of `boc_valet.SERIES`, with `params={"start_date": …, "end_date": …}`.

Any series with no values raises `ValueError` naming it ("FRED sent no values for VIXCLS", "Bank of Canada sent no values for …"). A model trained without a series would differ from the live one.

The docstring should say:
- the series names match the live collectors';
- dates are observation dates, so features apply release lags;
- the HY spread reaches back only to 2023.

- [ ] **Step 4: Run the tests**

Run: `scripts/in-docker.sh uv run pytest -q tests/unit/test_training_macro.py`
Expected: `2 passed`.

Run: `scripts/in-docker.sh uv run pytest -q`, then `scripts/in-docker.sh uv run ruff check .`
Expected: `774 passed`, then `All checks passed!`.

- [ ] **Step 5: Commit**

```bash
git add pipeline/src/advisor/training/macro.py pipeline/tests/unit/test_training_macro.py
git commit -m "feat: fetch the macro series' history for training"
```

---

### Task 3: Reduce SEC's bulk company facts to the US universe

**Files:**
- Modify: `pipeline/src/advisor/collectors/sec_xbrl.py`, `pipeline/src/advisor/collectors/sec.py`
- Create: `pipeline/src/advisor/training/fundamentals.py`
- Test: `pipeline/tests/unit/test_training_fundamentals.py` (the existing `tests/unit/test_sec_xbrl.py` must keep passing)

**Interfaces:**
- Consumes: `METRICS`, `FORMS` and `extract_facts` (`sec_xbrl.py`); `SecEdgar`, `parse_tickers` and `sec_ticker` (`sec.py`); `check_deadline`.
- Produces:
  - In `sec_xbrl.py`: `metric_facts(payload) -> Iterator[tuple[str, str, str, Mapping]]`, which yields `(metric, "taxonomy:Concept", unit, raw fact)` for every `METRICS` concept's fact whose `form` is in `FORMS`. `extract_facts` keeps its signature and behaviour, and is rewritten to use it.
  - In `sec.py`:
    - `COMPANYFACTS_ZIP_URL = "https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip"`;
    - `DOWNLOAD_TIMEOUT = httpx.Timeout(60.0, read=120.0)`;
    - `DOWNLOAD_CHUNK = 1 << 20`;
    - `SecEdgar.download(url, path, attempts=3) -> int`, which returns the bytes written.
  - In `advisor.training.fundamentals`:
    - `COLUMNS = ["cik", "metric", "concept", "unit", "start", "end", "value", "filed", "form", "accession"]`;
    - `CHECK_EVERY = 200`;
    - `entry_name(cik) -> "CIK##########.json"`;
    - `fact_rows(cik, payload, since) -> list[tuple]`;
    - `facts_frame(rows) -> DataFrame`;
    - `reduce_companyfacts(zip_path, ciks, since) -> tuple[DataFrame, list[int]]`;
    - `universe_ciks(tickers_payload, symbols) -> DataFrame`, with columns `symbol` (string) and `cik` (int32).

- [ ] **Step 1: Write the failing tests**

`pipeline/tests/unit/test_training_fundamentals.py`:

```python
import json
import zipfile
from datetime import date

import httpx
import pytest

from advisor.collectors.sec import SecEdgar
from advisor.training.fundamentals import COLUMNS, reduce_companyfacts, universe_ciks

COMPANIES = {"AAPL": 320193, "JPM": 19617, "BRK_B": 1067983, "GOOGL": 1652044}
AGENT = "stock-advisor test@example.com"


def companyfacts(fixtures_dir, name: str) -> dict:
    return json.loads((fixtures_dir / "sec" / f"companyfacts_{name}_trimmed.json").read_text())


@pytest.fixture
def bulk_zip(fixtures_dir, tmp_path):
    """A small companyfacts.zip: SEC's real (trimmed) company JSONs under SEC's entry names."""
    path = tmp_path / "companyfacts.zip"
    with zipfile.ZipFile(path, "w") as archive:
        for name, cik in COMPANIES.items():
            archive.writestr(f"CIK{cik:010d}.json", json.dumps(companyfacts(fixtures_dir, name)))
    return path


def test_the_universes_companies_are_read_from_the_bulk_zip(bulk_zip):
    facts, absent = reduce_companyfacts(bulk_zip, [320193, 19617, 1067983, 999999], date(2016, 1, 1))
    assert list(facts.columns) == COLUMNS
    assert absent == [999999]  # no entry: a company SEC has no XBRL for
    assert facts.groupby("cik").size().to_dict() == {19617: 26, 320193: 148, 1067983: 23}
    assert set(facts["metric"]) >= {"revenue", "net_income", "eps_diluted", "equity"}


def test_every_re_report_keeps_its_own_filing_date(bulk_zip):
    facts, _ = reduce_companyfacts(bulk_zip, [320193], date(2016, 1, 1))
    q2 = facts[(facts["concept"] == "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax")
               & (facts["start"] == date(2024, 9, 29)) & (facts["end"] == date(2025, 3, 29))]
    assert list(zip(q2["filed"], q2["accession"], strict=True)) == [
        (date(2025, 5, 2), "0000320193-25-000057"),  # first reported
        (date(2026, 5, 1), "0000320193-26-000013"),  # repeated a year later as the comparative
    ]
    assert set(q2["value"]) == {219_659_000_000.0}


def test_periods_ending_before_the_history_starts_are_left_out(bulk_zip):
    facts, _ = reduce_companyfacts(bulk_zip, [320193], date(2025, 6, 1))
    assert len(facts) == 112 and facts["end"].min() >= date(2025, 6, 1)


def test_share_classes_map_to_their_company(fixtures_dir):
    payload = json.loads((fixtures_dir / "sec" / "company_tickers.json").read_text())
    mapping = universe_ciks(payload, ["AAPL", "GOOG", "GOOGL", "BRK.B", "BF.B", "SPYX"])
    assert list(mapping.itertuples(index=False, name=None)) == [
        ("AAPL", 320193), ("GOOG", 1652044), ("GOOGL", 1652044), ("BRK.B", 1067983), ("BF.B", 14693),
    ]  # SPYX isn't in SEC's map and is left out


def test_the_bulk_zip_is_streamed_to_disk_with_the_contact(tmp_path):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers["User-Agent"])
        return httpx.Response(200, content=b"PK" + b"\0" * (3 << 20))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        size = SecEdgar(client, AGENT).download("https://www.sec.gov/x.zip", tmp_path / "sub" / "x.zip")
    assert size == (3 << 20) + 2 and (tmp_path / "sub" / "x.zip").stat().st_size == size
    assert seen == [AGENT]


def test_a_dropped_download_is_tried_again(tmp_path):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ReadError("connection reset")
        return httpx.Response(200, content=b"zip")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        sec = SecEdgar(client, AGENT, sleep=lambda s: None)
        assert sec.download("https://www.sec.gov/x.zip", tmp_path / "x.zip") == 3
    assert len(calls) == 2
```

- [ ] **Step 2: Run them and see them fail**

Run: `scripts/in-docker.sh uv run pytest -q tests/unit/test_training_fundamentals.py`
Expected: `1 error during collection`: `ModuleNotFoundError: No module named 'advisor.training.fundamentals'`.

- [ ] **Step 3: Factor out the fact generator**

In `sec_xbrl.py`, add `metric_facts` (Interfaces above), and import `Iterator` from `collections.abc`. Rewrite `extract_facts` to loop over it, keeping its LOOKBACK and `filed <= as_of` filters.

Run: `scripts/in-docker.sh uv run pytest -q tests/unit/test_sec_xbrl.py`
Expected: `7 passed` (unchanged).

- [ ] **Step 4: Add the streaming download**

`SecEdgar.download(url, path, attempts=3)` works as follows:
- It calls `require_contact()` first, so it raises `MissingCredential` without a contact.
- It creates `path.parent`.
- On each attempt, it takes a limiter token, then streams `GET url` with the contact User-Agent and `DOWNLOAD_TIMEOUT`, calls `raise_for_status()`, and writes `DOWNLOAD_CHUNK`-sized chunks to `path`. It returns the bytes written.
- On `httpx.TransportError`, it sleeps `5.0 * attempt` (through the injected `sleep`) and starts the file again. On the last attempt it re-raises.

- [ ] **Step 5: Write `advisor/training/fundamentals.py`**

- **`fact_rows`:** keeps the `metric_facts` whose `end >= since`. It builds `(cik, metric, concept, unit, start or None, end, float(val), filed, form, accn)`, with dates parsed from ISO.
- **`facts_frame`:** makes a DataFrame with dtypes `cik` int32, `value` float64 and string for the text columns. It is sorted by `cik, metric, end, filed`.
- **`reduce_companyfacts`:**
  - Opens the zip once, and reads `entry_name(cik)` for each distinct CIK, in sorted order.
  - Calls `check_deadline()` every `CHECK_EVERY` companies.
  - Returns the facts and the CIKs that have no entry.
- **`universe_ciks`:** maps each symbol through `sec_ticker` and `parse_tickers`, in symbol order, and leaves out unmapped symbols.

The docstring should say:
- the zip is rebuilt nightly by SEC and is about 1.4 GB;
- facts are keyed by CIK, so share classes share one company;
- the ticker map is current-only.

- [ ] **Step 6: Run the tests**

Run: `scripts/in-docker.sh uv run pytest -q tests/unit/test_training_fundamentals.py tests/unit/test_sec_xbrl.py`
Expected: `13 passed`.

Run: `scripts/in-docker.sh uv run pytest -q`, then `scripts/in-docker.sh uv run ruff check .`
Expected: `780 passed`, then `All checks passed!`.

- [ ] **Step 7: Commit**

```bash
git add pipeline/src/advisor/collectors/sec_xbrl.py pipeline/src/advisor/collectors/sec.py pipeline/src/advisor/training/fundamentals.py pipeline/tests/unit/test_training_fundamentals.py
git commit -m "feat: reduce SEC's bulk company facts to the US universe, as filed"
```

---

### Task 4: Label every stock with Yahoo's sector and industry

**Files:**
- Create: `pipeline/src/advisor/training/sectors.py`
- Modify: `pipeline/src/advisor/store/repo.py`
- Test: `pipeline/tests/unit/test_training_sectors.py`, `pipeline/tests/integration/test_repo.py`

**Interfaces:**
- Consumes: `to_yahoo` (`yfinance_bars`), `MARKETS[market].benchmark` (`advisor.markets`), `check_deadline`, and yfinance's `EquityQuery`, `screen` and `const.EQUITY_SCREENER_EQ_MAP`.
- Produces:
  - In `advisor.training.sectors`:
    - the constants `PAGE = 250`, `PAUSE_SECONDS = 0.4`, `US_EXCHANGES`, `TSX_EXCHANGE = "TOR"` and `MAX_FAILED_SHARE = 0.1`;
    - `SECTOR_ETFS` (exact values below);
    - `class ScreenerRefused(Exception)`;
    - the `Screen` type, `(query, offset) -> Sequence[str]`;
    - `sector_etf(market, sector) -> str`;
    - `all_sector_etfs() -> dict[Market, list[str]]`, sorted;
    - `industries() -> dict[str, str]`, mapping industry to sector;
    - `screen_industries(industry_sectors, *, screen=…, query=…, sleep=…, pause=…) -> dict[str, tuple[str, str]]`, mapping a Yahoo symbol to (sector, industry);
    - `classify(symbols, found) -> DataFrame`, with columns `symbol, sector, industry` as object dtype, so unclassified stocks have `None`.
  - In `repo.py`: `write_sectors(conn, rows: Sequence[tuple[str, str, str | None]]) -> int`.

- [ ] **Step 1: Write the failing tests**

`pipeline/tests/unit/test_training_sectors.py`:

```python
import pytest

from advisor.models import Market
from advisor.training.sectors import (
    PAGE,
    SECTOR_ETFS,
    ScreenerRefused,
    classify,
    industries,
    screen_industries,
    sector_etf,
)


def test_every_us_sector_has_its_spdr_fund_and_tsx_falls_back_to_its_benchmark():
    assert len(SECTOR_ETFS[Market.US]) == 11
    assert sector_etf(Market.US, "Technology") == "XLK"
    assert sector_etf(Market.TSX, "Energy") == "XEG.TO"
    assert sector_etf(Market.TSX, "Industrials") == "XIU.TO"  # no iShares TSX industrials fund
    assert sector_etf(Market.US, None) == "SPY"  # unclassified


def test_yfinance_lists_the_industries_of_the_eleven_sectors():
    by_industry = industries()
    assert len(by_industry) >= 140
    assert set(by_industry.values()) == set(SECTOR_ETFS[Market.US])
    assert by_industry["Gold"] == "Basic Materials"


def test_each_industry_is_screened_per_market_and_paged_to_the_end():
    asked = []

    def query(industry, market):
        return (industry, market)

    def screen(q, offset):
        asked.append((q, offset))
        industry, market = q
        if industry == "Banks" and market is Market.US:
            return [f"B{offset + i}" for i in range(PAGE if offset == 0 else 3)]
        return ["RY.TO"] if industry == "Banks" else ["AAPL"]

    found = screen_industries(
        {"Banks": "Financial Services", "Consumer Electronics": "Technology"},
        screen=screen, query=query, sleep=lambda s: None,
    )
    assert [(q[0], q[1].value, o) for q, o in asked] == [
        ("Banks", "US", 0), ("Banks", "US", PAGE), ("Banks", "TSX", 0),
        ("Consumer Electronics", "US", 0), ("Consumer Electronics", "TSX", 0),
    ]
    assert found["B252"] == ("Financial Services", "Banks")
    assert found["RY.TO"] == ("Financial Services", "Banks")
    assert found["AAPL"] == ("Technology", "Consumer Electronics")


def test_a_refusing_screener_fails_rather_than_leaving_the_universe_unclassified():
    def screen(q, offset):
        raise RuntimeError("401 Unauthorized")

    with pytest.raises(ScreenerRefused, match="4 of 4"):
        screen_industries({"Banks": "Financial Services", "Gold": "Basic Materials"},
                          screen=screen, query=lambda i, m: i, sleep=lambda s: None)


def test_the_universe_is_matched_in_yahoos_form():
    found = {"BRK-B": ("Financial Services", "Insurance—Diversified"), "RCI-B.TO": ("Communication Services", "Telecom Services")}
    frame = classify(["BRK.B", "RCI-B.TO", "ODD"], found)
    assert list(frame.itertuples(index=False, name=None)) == [
        ("BRK.B", "Financial Services", "Insurance—Diversified"),
        ("RCI-B.TO", "Communication Services", "Telecom Services"),
        ("ODD", None, None),
    ]
```

In `pipeline/tests/integration/test_repo.py`, add this test directly before `test_load_held_symbols_nets_sells`:

```python
def test_sectors_are_set_on_known_stocks_and_kept_when_unclassified(db):
    repo.upsert_symbols(db, Market.US, [info("AAPL"), info("JPM"), info("ODD")])
    repo.write_sectors(db, [("AAPL", "Technology", "Consumer Electronics"), ("JPM", "Financial Services", "Banks—Diversified")])
    repo.write_sectors(db, [("AAPL", "Technology", "Consumer Electronics"), ("JPM", None, None), ("NEW", "Energy", "Oil & Gas E&P")])
    rows = db.execute("select symbol, sector, industry from symbols order by symbol").fetchall()
    assert [(r["symbol"], r["sector"], r["industry"]) for r in rows] == [
        ("AAPL", "Technology", "Consumer Electronics"),
        ("JPM", "Financial Services", "Banks—Diversified"),  # unclassified this week: kept
        ("ODD", None, None),
    ]  # NEW isn't in the universe table, so nothing is inserted
```

- [ ] **Step 2: Run them and see them fail**

Run: `scripts/in-docker.sh uv run pytest -q tests/unit/test_training_sectors.py`
Expected: `1 error during collection`: `ModuleNotFoundError: No module named 'advisor.training.sectors'`.

- [ ] **Step 3: Write `advisor/training/sectors.py`**

The research checked these values against Yahoo:

```python
PAGE = 250  # the screener's largest page
PAUSE_SECONDS = 0.4
US_EXCHANGES = ("NMS", "NYQ", "NGM", "NCM", "ASE", "PCX", "BTS")
TSX_EXCHANGE = "TOR"
MAX_FAILED_SHARE = 0.1  # more failed queries than this means Yahoo is refusing the screener
SECTOR_ETFS: dict[Market, dict[str, str]] = {
    Market.US: {
        "Technology": "XLK", "Financial Services": "XLF", "Healthcare": "XLV",
        "Consumer Cyclical": "XLY", "Industrials": "XLI", "Communication Services": "XLC",
        "Consumer Defensive": "XLP", "Energy": "XLE", "Real Estate": "XLRE",
        "Basic Materials": "XLB", "Utilities": "XLU",
    },
    Market.TSX: {
        "Energy": "XEG.TO", "Financial Services": "XFN.TO", "Technology": "XIT.TO",
        "Basic Materials": "XMA.TO", "Real Estate": "XRE.TO", "Utilities": "XUT.TO",
        "Consumer Defensive": "XST.TO",
    },
}
```

The functions:
- **`sector_etf`** returns the market's ETF for the sector, or else `MARKETS[market].benchmark`. It covers unclassified stocks (`None`) and the four TSX sectors that have no fund.
- **`industries()`** flattens `EQUITY_SCREENER_EQ_MAP["industry"]`, which maps a sector to a set of industries. Import yfinance lazily inside the function.
- **The default `query(industry, market)`** is `EquityQuery("and", [EquityQuery("eq", ["industry", industry]), exchange])`. The exchange filter is `EquityQuery("is-in", ["exchange", *US_EXCHANGES])` for US and `EquityQuery("eq", ["exchange", TSX_EXCHANGE])` for TSX.
- **The default `screen(query, offset)`** calls `yf.screen(query, offset=offset, size=PAGE, sortField="intradaymarketcap", sortAsc=False)` and returns the quotes' `symbol`s.
- **`screen_industries`:**
  - For each industry, and for each market in `Market` order, it pages until a page is shorter than `PAGE`, sleeping `pause` before every request.
  - The first label a symbol gets is kept.
  - A query that raises counts as failed. More than `MAX_FAILED_SHARE` of the queries failing raises `ScreenerRefused(f"{failed} of {asked} Yahoo screener queries failed")`.
- **`classify`** matches each symbol through `to_yahoo`.

The module docstring should cover:
- the request count, about 300 (about 3 minutes);
- coverage, about 99% of US stocks and 96% of TSX stocks;
- the ETF fallback.

- [ ] **Step 4: Write `repo.write_sectors`**

Insert it before `load_held_symbols`. In one transaction, it runs `update symbols set sector = %s, industry = %s, updated_at = now() where symbol = %s and asset_type = 'stock'` for the rows whose sector isn't None, and returns the cursor's rowcount. Rows without a sector are skipped, so a stock left unclassified this week keeps what it had.

- [ ] **Step 5: Run the tests**

Run: `scripts/in-docker.sh uv run pytest -q tests/unit/test_training_sectors.py tests/integration/test_repo.py`
Expected: every test passes. The sectors file gives `5 passed`, and the repo file adds one test.

Run: `scripts/in-docker.sh uv run pytest -q`, then `scripts/in-docker.sh uv run ruff check .`
Expected: `786 passed`, then `All checks passed!`.

- [ ] **Step 6: Commit**

```bash
git add pipeline/src/advisor/training/sectors.py pipeline/src/advisor/store/repo.py pipeline/tests/unit/test_training_sectors.py pipeline/tests/integration/test_repo.py
git commit -m "feat: label every stock with Yahoo's sector and industry"
```

---

### Task 5: Build the training data weekly

**Files:**
- Create: `pipeline/src/advisor/training/build.py`, `.github/workflows/train.yml`
- Test: `pipeline/tests/unit/test_training_build.py`

**Interfaces:**
- Consumes:
  - Tasks 1–4's functions;
  - `NasdaqSymbols(client).fetch([], now)` and `TmxSymbols(client).fetch([], now)`, which return `SymbolInfo` lists;
  - `MARKETS[market].min_universe` and `.benchmark`;
  - `SecEdgar.get(TICKERS_URL)`, `SEC_PER_MINUTE`, `RateLimiter` and `make_client`;
  - `Settings.from_env()` and `connect` (`advisor.store.db`);
  - `repo.write_sectors`.
- Produces, in `advisor.training.build`:
  - `MAX_MISSING_SHARE = 0.2` and `FUNDAMENTALS_SINCE_YEARS = 2`;
  - `class BuildFailed(Exception)`;
  - `@dataclass class BuildDeps`, with fields:
    - `http`;
    - `sec`;
    - `universe: Callable[[Market], list[str]]`;
    - `conn = None`;
    - `download = yahoo_download`;
    - `screen_sectors`, which defaults to `screen_industries(industries())`;
    - `sleep = time.sleep`.
  - `build(out, now, deps, limit=None) -> dict` (the manifest).
  - `main(argv)`, with the options `--out DIR` (required), `--limit N` and `--no-db`.
  - Plan 3b reads `DIR` (file formats in `deferred.md`).

- [ ] **Step 1: Write the failing tests**

`pipeline/tests/unit/test_training_build.py`:

```python
import io
import json
import zipfile
from datetime import UTC, datetime

import httpx
import pandas as pd
import pytest

from advisor.collectors.sec import SecEdgar
from advisor.models import Market
from advisor.training.build import BuildDeps, BuildFailed, build

NOW = datetime(2026, 10, 24, 14, tzinfo=UTC)  # a Saturday
UNIVERSE = {Market.US: ["JPM", "AAPL", "BRK.B"], Market.TSX: ["RY.TO"]}
FIELDS = ["Open", "High", "Low", "Close", "Volume"]


def yahoo(asked: list[list[str]], silent: frozenset[str] = frozenset()):
    """yf.download: two days of bars for every ticker but the `silent` ones."""

    def download(tickers, start, end):
        asked.append(list(tickers))
        live = [t for t in tickers if t not in silent]
        columns = pd.MultiIndex.from_product([live, FIELDS])
        index = pd.to_datetime(["2026-10-22", "2026-10-23"])
        return pd.DataFrame([[10.0, 11.0, 9.0, 10.5, 1000.0] * len(live)] * 2, index=index, columns=columns)

    return download


def web(fixtures_dir) -> httpx.Client:
    """SEC (ticker map, bulk zip), FRED and the Bank of Canada, from recorded fixtures."""
    sec = fixtures_dir / "sec"
    bulk = io.BytesIO()
    with zipfile.ZipFile(bulk, "w") as archive:
        for name, cik in {"AAPL": 320193, "JPM": 19617, "BRK_B": 1067983}.items():
            archive.writestr(f"CIK{cik:010d}.json", (sec / f"companyfacts_{name}_trimmed.json").read_text())

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("company_tickers.json"):
            return httpx.Response(200, content=(sec / "company_tickers.json").read_bytes())
        if request.url.path.endswith("companyfacts.zip"):
            return httpx.Response(200, content=bulk.getvalue())
        if request.url.host == "fred.stlouisfed.org":
            series = request.url.params["id"]
            return httpx.Response(200, text=(fixtures_dir / "fred" / f"fred_{series}.csv").read_text())
        return httpx.Response(200, content=(fixtures_dir / "boc" / "valet_observations_recent10.json").read_bytes())

    return httpx.Client(transport=httpx.MockTransport(handler))


def deps(client, asked, silent=frozenset()) -> BuildDeps:
    return BuildDeps(
        http=client,
        sec=SecEdgar(client, "stock-advisor test@example.com"),
        universe=UNIVERSE.__getitem__,
        download=yahoo(asked, silent),
        screen_sectors=lambda: {"AAPL": ("Technology", "Consumer Electronics"), "RY.TO": ("Financial Services", "Banks—Diversified")},
        sleep=lambda s: None,
    )


def test_a_build_writes_every_file_and_a_manifest(fixtures_dir, tmp_path):
    asked: list[list[str]] = []
    with web(fixtures_dir) as client:
        manifest = build(tmp_path, NOW, deps(client, asked), limit=10)
    assert set(manifest["files"]) == {
        "sectors.parquet", "prices_US.parquet", "prices_TSX.parquet",
        "tickers.parquet", "fundamentals.parquet", "macro.parquet",
    }
    assert (manifest["start"], manifest["end"]) == ("2018-10-24", "2026-10-24")
    assert json.loads((tmp_path / "manifest.json").read_text()) == manifest
    assert not (tmp_path / "companyfacts.zip").exists()  # the 1.4 GB download is deleted
    # each market's stocks come with its benchmark and sector ETFs
    assert asked[0][:3] == ["AAPL", "BRK-B", "JPM"] and {"SPY", "XLK", "XLF", "XLC"} <= set(asked[0])
    assert asked[1][0] == "RY.TO" and {"XIU.TO", "XFN.TO", "XEG.TO"} <= set(asked[1])
    assert manifest["unclassified"] == 2  # BRK.B and JPM had no label in this fake screen
    facts = pd.read_parquet(tmp_path / "fundamentals.parquet")
    assert set(facts["cik"]) == {320193, 19617, 1067983}
    tickers = pd.read_parquet(tmp_path / "tickers.parquet")
    assert list(tickers["symbol"]) == ["AAPL", "BRK.B", "JPM"]


def test_a_missing_etf_fails_the_build(fixtures_dir, tmp_path):
    with web(fixtures_dir) as client, pytest.raises(BuildFailed, match="XLC"):
        build(tmp_path, NOW, deps(client, [], silent=frozenset({"XLC"})), limit=10)


def test_yahoo_missing_many_stocks_fails_the_build(fixtures_dir, tmp_path):
    with web(fixtures_dir) as client, pytest.raises(BuildFailed, match="no bars for 2 of 3 US stocks"):
        build(tmp_path, NOW, deps(client, [], silent=frozenset({"AAPL", "JPM"})), limit=10)


def test_a_short_universe_fails_the_full_build(fixtures_dir, tmp_path):
    with web(fixtures_dir) as client, pytest.raises(BuildFailed, match="universe too small"):
        build(tmp_path, NOW, deps(client, []))
```

- [ ] **Step 2: Run them and see them fail**

Run: `scripts/in-docker.sh uv run pytest -q tests/unit/test_training_build.py`
Expected: `1 error during collection`: `ModuleNotFoundError: No module named 'advisor.training.build'`.

- [ ] **Step 3: Write `advisor/training/build.py`**

`build(out, now, deps, limit)` does these steps in order. It creates `out`, and records each step's seconds in `manifest["seconds"]`.

1. **The dates.** `today` is `now`'s ET date, and `start = history_start(today)`. The manifest starts as `{"built_at", "start", "end", "files": {}, "missing": {}, "seconds": {}}`.
2. **The universes.** For each market, take `sorted(deps.universe(market))[:limit]`. Without a limit, a market below `min_universe` raises `BuildFailed("<market> universe too small: N")`.
3. **Sectors.** `classify` every stock of both markets, write `sectors.parquet`, and set `manifest["unclassified"]`. When `deps.conn` is set, call `repo.write_sectors`.
4. **Prices, per market.** Download the stocks, then the benchmark and `all_sector_etfs()[market]`, in one `download_history` call. It fails the build in two cases:
   - stocks missing beyond `MAX_MISSING_SHARE` raise `BuildFailed(f"Yahoo sent no bars for {n} of {total} {market} stocks")`;
   - any missing benchmark or ETF raises `BuildFailed` naming it.

   Write `prices_<market>.parquet`, and put the missing symbols in `manifest["missing"][market]`.
5. **Fundamentals.**
   - Write `tickers.parquet` from `universe_ciks(sec.get(TICKERS_URL).json(), US stocks)`.
   - Download the zip to `out/companyfacts.zip`, and reduce it with `since = history_start(start, years=FUNDAMENTALS_SINCE_YEARS)`. Delete the zip in a `finally`.
   - Write `fundamentals.parquet`, and set `manifest["missing"]["ciks"]` to the absent count.
6. **Macro.** Write `macro.parquet` from `macro_history(deps.http, start, today)`.
7. **The manifest.** Write `manifest.json` with indent 2, and return it.

Each file entry is `{"rows", "bytes"}`, and every Parquet file is zstd-compressed with no index.

`main` uses `make_client(timeout=60.0)`. It sets up SEC with `SecEdgar(client, os.environ.get("SEC_USER_AGENT"), RateLimiter(per_minute=SEC_PER_MINUTE, burst=5))`. The universe comes from `NasdaqSymbols`/`TmxSymbols`. A database connection is opened only without `--no-db`. It prints the manifest without `missing` as one JSON line, and returns 0. An exception exits non-zero.

- [ ] **Step 4: Write `.github/workflows/train.yml`**

```yaml
name: train

# Weekly, on Saturday when neither market trades: rebuild the training data from scratch
# (Plan 3a). Nothing is kept between weeks; Plan 3b trains, backtests and promotes the model in
# this same job. A failed build fails the job (GitHub emails the owner) and the active model
# stays in use.
on:
  schedule:
    - cron: "0 10 * * 6"  # Saturday 10:00 UTC
  workflow_dispatch:

permissions:
  contents: read

concurrency:
  group: train
  cancel-in-progress: false

jobs:
  train:
    runs-on: ubuntu-latest
    timeout-minutes: 120
    defaults:
      run:
        working-directory: pipeline
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@d0cc045d04ccac9d8b7881df0226f9e82c39688e # v6.8.0
      - run: uv sync --locked --no-dev
      - name: Build training data
        env:
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
          SEC_USER_AGENT: ${{ secrets.SEC_USER_AGENT }}
        run: uv run python -m advisor.training.build --out "$RUNNER_TEMP/training"
      - uses: actions/upload-artifact@v4  # what was built and what was missing, for 30 days
        if: always()
        with:
          name: training-manifest
          path: ${{ runner.temp }}/training/manifest.json
          retention-days: 30
          if-no-files-found: ignore
```

- [ ] **Step 5: Run the tests**

Run: `scripts/in-docker.sh uv run pytest -q tests/unit/test_training_build.py`
Expected: `4 passed`.

Run: `scripts/in-docker.sh uv run pytest -q`, then `scripts/in-docker.sh uv run ruff check .`
Expected: `790 passed`, then `All checks passed!`.

- [ ] **Step 6: Check a small build live**

This makes real requests:
- about 300 to Yahoo's screener;
- 2 Yahoo downloads;
- SEC's ticker map, plus the 1.4 GB zip;
- 10 to FRED and the Bank of Canada.

Run: `SEC_USER_AGENT="stock-advisor-dev research@example.com" scripts/in-docker.sh uv run python -m advisor.training.build --out .check-3a --limit 50 --no-db`

Expected: about 5 minutes, then one JSON line. On 2026-10-20 it showed:
- `"seconds": {"sectors": 170.7, "prices_US": 3.1, "prices_TSX": 2.8, "companyfacts_download": 90.2, "fundamentals": 1.1, "macro": 5.4}`;
- `"unclassified": 1`;
- `prices_US.parquet` with about 98,700 rows, `prices_TSX.parquet` with about 96,700, `fundamentals.parquet` with about 43,000 and `macro.parquet` with about 22,000.

`.check-3a/manifest.json` lists no missing stocks.

Then delete it: `rm -rf .check-3a`.

- [ ] **Step 7: Commit**

```bash
git add pipeline/src/advisor/training/build.py pipeline/tests/unit/test_training_build.py .github/workflows/train.yml
git commit -m "feat: rebuild the training data in a weekly job"
```

---

### Task 6: Record what Plan 3a built and decided

**Files:**
- Modify: `docs/superpowers/specs/2026-10-09-stock-advisor-design.md`, `docs/superpowers/deferred.md`

- [ ] **Step 1: Update the spec**

In `docs/superpowers/specs/2026-10-09-stock-advisor-design.md`, make these edits:
- In the §3 diagram, delete the line `  Storage:  Parquet history for training (prices, fundamentals)`.
- Replace `   - Map sectors from Yahoo metadata, cached weekly.` with `   - Sectors and industries come from Yahoo's screener; \`train.yml\` refreshes them weekly.`
- In §5.2, replace `It's stored as Parquet in Supabase Storage.` with ``\`train.yml\` rebuilds it from scratch each week, as Parquet in the job's workspace; nothing is stored between weeks (owner's decision, 2026-10-20).``
- In §8, replace the bullet `- **Storage:** training Parquet (prices, fundamentals) goes in a private Supabase Storage bucket, kept under about 600 MB.` with `- **Training data** isn't stored: \`train.yml\` rebuilds it each week (§5.2).`
- In §10, replace `  - Training data lives in Storage.` with `  - Training data is rebuilt each week, not stored.`

- [ ] **Step 2: Update the deferred list**

In `docs/superpowers/deferred.md`, replace:

```markdown
  - Waiting for data no plan collects yet: the sector warning (`symbols.sector` is never filled; a fundamentals plan should fill it) and the note on US dividend payers in a TFSA.
```

with:

```markdown
  - Waiting for data no plan collects yet: the note on US dividend payers in a TFSA. The sector warning can now be built: `train.yml` fills `symbols.sector` and `industry` weekly (Plan 3a).
```

and insert this directly before the `- **Data quality:**` bullet in the Plan 3 section:

```markdown
- **Training data (Plan 3a).** `python -m advisor.training.build --out DIR` writes Parquet files that Plan 3b's training reads in the same weekly job:
  - `prices_US.parquet` and `prices_TSX.parquet`: `symbol, day, open, high, low, close, volume`, adjusted for splits and dividends, about 8 years. They include each market's benchmark and sector ETFs.
  - `sectors.parquet`: `symbol, sector, industry` (Yahoo's names). Use `training.sectors.sector_etf(market, sector)` for the relative-strength ETF. Four TSX sectors and unclassified stocks fall back to XIU.TO or SPY.
  - `fundamentals.parquet`: `cik, metric, concept, unit, start, end, value, filed, form, accession`, every re-report kept. `tickers.parquet` maps `symbol` to `cik`. Pick a concept per period by `METRICS` priority and the latest `filed` on or before the day, as the live `sec_xbrl` records need too.
  - `macro.parquet`: `series, day, value` for the live collectors' FRED and Bank of Canada series.
  - `manifest.json`: sizes, timings and missing symbols.
- **What the training data lacks:**
  - It covers only stocks listed today (survivorship bias, spec §5.2). Yahoo has nothing for delisted tickers, and SEC's ticker map is current-only.
  - FRED's HY spread starts in 2023.
  - XLC (communication services) starts in June 2018, so its first months are missing.
  - Banks have no gross profit or operating income, and some issuers have no EPS: leave such features missing, never fabricated.
  - "Surprise from the last filing" can't be analyst surprise (XBRL has no estimates). Derive it from the company's own history, e.g. EPS against the same quarter a year earlier, scaled by the spread of past changes.
```

- [ ] **Step 3: Run every test**

Run: `scripts/in-docker.sh uv run pytest -q`, then `scripts/in-docker.sh uv run ruff check .`
Expected: `790 passed`, then `All checks passed!`.

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-10-09-stock-advisor-design.md docs/superpowers/deferred.md
git commit -m "docs: record the weekly training data and its limits"
```
