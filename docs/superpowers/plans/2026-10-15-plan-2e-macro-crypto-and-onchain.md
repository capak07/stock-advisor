# Stock Advisor — Plan 2e: Macro, Crypto and On-chain Sources Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add nine keyless sources and price the owner's crypto in the holdings phase:
- **Macro:**
  - FRED series (#20, core);
  - FOMC statements, minutes and meeting dates (#21);
  - CNN Fear & Greed (#22, best-effort);
  - the Crypto Fear & Greed index (#23).
- **Crypto prices:**
  - CoinGecko CAD quotes (#4, core for crypto);
  - Coinbase daily candles (#5);
  - Kraken daily candles as a cross-check (#6).
- **On-chain:**
  - DefiLlama chain TVL (#52);
  - blockchain.com Bitcoin network stats (#53).
- **Held and watched crypto** are priced and saved before the rest of the run, valued in CAD.

**Architecture:**
- **Collectors.** Each source is one collector module that follows the existing `Collector` protocol, the HTTP helpers and `collect_per_symbol`.
  - Day-by-day series share a `SeriesObservation` record, moved out of `boc_valet.py` into a new `collectors/series.py`. That covers FRED, both Fear & Greed indexes and blockchain.com.
- **Crypto in the holdings phase.** `advisor/crypto_prices.py` turns the three crypto price sources into one features row per coin. `run.py` runs those three sources in the holdings phase (phase 1), right after held and watched stocks, and leaves them out of enrichment.
  - A held coin with no CAD quote degrades the run, the same way a held stock without a price does.
- **Enrichment skips idle crypto sources.** Crypto-only market-wide sources (the Crypto Fear & Greed index and blockchain.com) run only when some crypto is held or watched.
- **Tests run against responses recorded live on 2026-10-15.** They are committed with this plan under `pipeline/tests/fixtures/{fred,fomc,cnn,alternative,blockchain,defillama,coingecko,coinbase,kraken}/`.
  - Every code block and expected value below was run on 2026-10-15: the full suite passed (458 tests) and ruff was clean, in a scratch worktree.
  - The same code fetched all nine live sources that day.

**Tech Stack:** Python 3.12, uv, httpx, pydantic v2, `xml.etree.ElementTree`, `email.utils`, pytest, ruff, Docker.

**Spec:** `docs/superpowers/specs/2026-10-09-stock-advisor-design.md` (rev 2). Read:
- §2 R7;
- §3 design rules 3 and 5;
- §4.1;
- §4.2 sources 4–7, 20–23, 52 and 53, and the notes under the table;
- §4.3 stage 1;
- §5.1 (the macro row);
- §5.4;
- §7.2 and §7.4;
- §10.

The research behind this plan is in `.superpowers/research/plan-2e/` (`macro.md`, `crypto.md`, `onchain.md`), git-ignored and local.

## Roadmap

| Plan | Delivers |
|---|---|
| 2a–2d | Done |
| **2e (this plan)** | Macro (FRED, FOMC, CNN and crypto Fear & Greed), crypto prices (CoinGecko, Coinbase, Kraken), on-chain (DefiLlama, blockchain.com), crypto priced in the holdings phase |
| 2f | News and social sources, de-duplication, ticker mapping, FinBERT |
| 2g | SEC 13F institutional ownership |
| 2h | Options (Yahoo chains, CBOE put/call), catalysts (openFDA, ClinicalTrials.gov, USAspending.gov, House Clerk reports), Canadian short positions. Split out of 2e, see below |

## Plan-level decisions

- **The roadmap's 2e is split in two.** It named 16 sources.
  - This plan keeps the nine that describe the market as a whole or the owner's crypto.
  - Options, catalysts and Canadian short positions move to a new Plan 2h. Each of them needs a company-name → symbol map, or a PDF and file format still to be confirmed, which is a different shape of work.
- **FRED (core): one request per series.**
  - Several series in one request come back as a ZIP when their dates differ, and a multi-series start date (`cosd`) is silently ignored.
  - The plan asks for 9 series over 450 days, which is 13 months of the monthly series plus their release lag, so CPI and unemployment can be compared year over year.
  - Rows outside the window are dropped in code, because FRED returns the whole history for a bad `cosd`.
  - Anything that isn't the series' CSV fails that series alone. That covers an error page, a ZIP, or a bot challenge sent with HTTP 200.
- **FOMC: two requests.**
  - The monetary-policy RSS feed gives the latest releases. A statement is the exact title "Federal Reserve issues FOMC statement"; the discount-rate minutes are not FOMC minutes.
  - The calendar page has no feed. It is read by its `fomc-meeting__month` and `fomc-meeting__date` classes, and the decision day is a meeting's last day.
  - The source runs every run, because a statement lands at 14:00 ET, before the pre-close run.
  - A calendar that can't be read keeps the releases and reports PARTIAL.
- **CNN Fear & Greed is best-effort.**
  - The endpoint answers 418 unless the request carries CNN's own Referer and Origin; no browser User-Agent is needed.
  - The latest reading of a day wins.
- **Crypto is valued in CAD from CoinGecko.**
  - One `/coins/markets?vs_currency=cad&symbols=…` request prices every coin. With `symbols=`, CoinGecko returns the top-ranked coin for each ticker; 12 coins call themselves "btc".
  - The keyless limit is tiny and shared per IP, so the call is tried at most twice, the retry honouring Retry-After.
  - A quote not updated for a day is a dead listing and counts as missing.
  - Coinbase lists no CAD products for these coins, so its USD candles feed only the price features (returns, volatility), which don't depend on currency. Stops and graded returns do, so Plans 4 and 5 must convert (see `deferred.md`).
- **MATIC is priced and charted as POL.** Polygon renamed it in 2024, and exchanges price only POL. The rename lives in one small module, `collectors/coins.py`.
- **Kraken cross-checks Coinbase.** It plays the role the jump rule plays for stocks (spec §10).
  - When Kraken's close for Coinbase's latest finished day differs by more than 2%, `unconfirmed_price` is true.
  - Kraken names Bitcoin XBT and Dogecoin XDG.
- **Point in time, per source:**
  - FRED keeps observation dates up to `as_of`'s ET day.
  - FOMC releases are kept only if published by `as_of`.
  - Fear & Greed readings are kept up to `as_of`'s instant (CNN) or UTC day (alternative.me).
  - Daily aggregates (candles, TVL, network stats) keep only UTC days that finished before `as_of`'s UTC day.
- **DefiLlama: chain TVL only.**
  - The TVL of a coin's own chain covers ETH, SOL, AVAX, BNB, TRX, ADA, POL and BTC.
  - Protocol TVL, for DeFi tokens such as UNI or AAVE, is left until Plan 3 defines the crypto features (recorded in `deferred.md`).
  - The coin → chain map is hard-coded, because DefiLlama's own symbols are unreliable.
- **Crypto-only market-wide sources run only when some crypto is held or watched.** The daily health check still checks them, so breakage is noticed either way.
- **Terms of use, recorded for the owner** (and in `deferred.md`):
  - FRED's FAQ says "Don't do any data mining, scraping or extraction", while its terms forbid only disruptive scraping. This plan makes 9 small requests a day, cached for the day.
  - CNN allows downloads "for your personal use only".
  - CoinGecko requires the credit "Data provided by CoinGecko" wherever its data is shown, and forbids storing its data beyond a daily-refreshed cache.
  - None of the three forbids this personal, low-volume use outright, so all stay (spec §4.2 terms rule).

## Global Constraints

- **No data source may need an API key or an account** (spec R7, §4.2).
- **Collector contract (spec §4.1):**
  - `fetch` returns validated records or raises, and never touches the database.
  - SYMBOLS-scope records carry the canonical requested `symbol`.
  - `PartialFetch(records, error)` reports partial failures; an empty one counts as a failure.
- **HTTP goes through `get_with_retries`.** Loops over requests call `check_deadline()`. Each provider has one `RateLimiter`, built in the registry.
- **Point in time:** no record may be dated after the run's `as_of` (spec §3, design rule 3).
- **Testing:** collectors are tested against recorded real responses, with no live network in tests (spec §11).
- **Docker only:** tests and lint run only in Docker, via `pipeline/scripts/in-docker.sh`.
- **Python and lint:** Python 3.12; ruff with line length 100 and rules E, F, I, UP and B.
- **Crypto symbols** match `^[A-Z0-9]{2,10}$` (spec §8). Crypto belongs to no stock market, so crypto collectors have `markets = frozenset()`.
- **Best-effort sources** are fetched at low volume, cached, and used only for personal, non-commercial purposes (spec §4.2).
- **No real email address** goes in code, tests or docs.

## Review Focus

The five conditions most likely to hurt the owner that the per-source tests alone wouldn't catch. Each has a test in the task that owns it.

1. **CoinGecko is rate-limited at the moment the crypto is priced.** GitHub's runners share IPs. The holding must still be valued from its last quote (2-day freshness), and the run is degraded rather than failed. Task 8: `test_a_failing_coingecko_values_holdings_from_its_last_quote`.
2. **The owner holds MATIC and POL at once.** Both must be priced from POL's quote, with one ticker in the request. Task 6: `test_matic_and_pol_held_together_are_both_priced_from_one_ticker`.
3. **A coin one exchange doesn't list.** Wealthsimple lists coins that Coinbase or Kraken may not. Its 404, or Kraken's "Unknown asset pair", means no candles, not a failure, and the coin still gets a features row from its quote.
   - Task 7: `test_a_coin_coinbase_does_not_list_has_no_candles` and `test_a_coin_kraken_does_not_list_has_no_candles`.
   - Task 8: `test_a_coin_with_only_a_quote_or_old_candles_still_gets_a_row`.
4. **FRED answers a page that is not the series' CSV**, such as a bot challenge sent with HTTP 200. Only that series fails; the rest of the macro data still arrives. Task 1: `test_anything_but_the_series_csv_is_an_error` and `test_a_failing_series_is_a_partial_result`.
5. **A stock-only owner.** No crypto source may make a request, in the holdings phase or in enrichment.
   - Task 8: `test_without_crypto_no_crypto_source_is_asked` and `test_a_crypto_market_source_runs_only_when_crypto_is_held_or_watched`.

---

## File structure

| File | Responsibility | Task |
|---|---|---|
| `pipeline/src/advisor/collectors/series.py` | `SeriesObservation`: one value per series per day, shared by several sources | 1 |
| `pipeline/src/advisor/collectors/boc_valet.py` | imports `SeriesObservation` instead of defining it | 1 |
| `pipeline/src/advisor/collectors/fred.py` | FRED CSV series (core) | 1 |
| `pipeline/src/advisor/collectors/fomc.py` | FOMC releases (RSS) and meetings (calendar page) | 2 |
| `pipeline/src/advisor/collectors/cnn_fear_greed.py` | CNN Fear & Greed history | 3 |
| `pipeline/src/advisor/collectors/crypto_fear_greed.py` | alternative.me Crypto Fear & Greed | 3 |
| `pipeline/src/advisor/collectors/blockchain_stats.py` | five daily Bitcoin network charts | 4 |
| `pipeline/src/advisor/collectors/defillama_tvl.py` | TVL of a coin's own chain | 5 |
| `pipeline/src/advisor/collectors/coins.py` | today's ticker for renamed coins (MATIC → POL) | 6 |
| `pipeline/src/advisor/collectors/coingecko.py` | CAD quotes (core for crypto) | 6 |
| `pipeline/src/advisor/collectors/coinbase_candles.py` | daily USD candles | 7 |
| `pipeline/src/advisor/collectors/kraken_ohlc.py` | daily USD candles for the cross-check | 7 |
| `pipeline/src/advisor/crypto_prices.py` | crypto features rows and the cross-check rule | 8 |
| `pipeline/src/advisor/run.py` | crypto priced in the holdings phase; summary; holdings check | 8 |
| `pipeline/src/advisor/enrich.py` | crypto-only market-wide sources wait for crypto | 8 |
| `pipeline/src/advisor/collectors/registry.py` | each new collector and its rate limiter | 1–7 |
| `pipeline/tests/unit/test_registry.py` | one `EXPECTED` row per new source | 1–7 |
| `docs/superpowers/deferred.md`, spec row 15 | Plan 2e items resolved; Plan 2h recorded | 8 |

The registry keeps the order of the tasks. Each task appends its collector after the previous task's last line. Keep imports sorted: `ruff check --fix` sorts them (I001).

---

### Task 1: Shared series record and FRED (source 20, core)

**Files:**
- Create: `pipeline/src/advisor/collectors/series.py`, `pipeline/src/advisor/collectors/fred.py`, `pipeline/tests/unit/test_fred.py`
- Modify: `pipeline/src/advisor/collectors/boc_valet.py`, `pipeline/src/advisor/collectors/registry.py`, `pipeline/tests/unit/test_registry.py`
- Fixtures (already committed): `pipeline/tests/fixtures/fred/fred_<SERIES>.csv` for the 9 series. `fred_DGS10.csv` and `fred_DGS2.csv` were split from one two-series response; their format is identical to a single-series answer.

**Interfaces:**
- Consumes: `get_with_retries`, `check_deadline`, `PartialFetch`, `RateLimiter`, `Cadence`, `Category` and `Scope` from `advisor.collectors.base`; `ET`, `AssetType` and `Market` from `advisor.models`.
- Produces:
  - `advisor.collectors.series.SeriesObservation(series: str, day: date, value: float)`, frozen. Tasks 3 and 4 use it, and `boc_valet` imports it.
  - `Fred(client, limiter=None)` named `fred`: core, DAILY, MARKET, freshness 7 days, markets US and TSX.
  - `FRED_PER_MINUTE = 30`, `SERIES`, `LOOKBACK = timedelta(days=450)` and `parse_csv(series, text, start, end)`.

- [ ] **Step 1: Write the failing tests**

Create `pipeline/tests/unit/test_fred.py`:

```python
from datetime import UTC, date, datetime

import httpx
import pytest

from advisor.collectors.base import PartialFetch
from advisor.collectors.fred import SERIES, Fred, parse_csv

AS_OF = datetime(2026, 10, 15, 12, 15, tzinfo=UTC)  # the 450-day lookback starts 2025-07-22


def csv_text(fixtures_dir, series: str) -> str:
    return (fixtures_dir / "fred" / f"fred_{series}.csv").read_text(encoding="utf-8")


def serving(fixtures_dir, seen: list | None = None, broken: frozenset[str] = frozenset()) -> Fred:
    def handler(request: httpx.Request) -> httpx.Response:
        series = request.url.params["id"]
        if seen is not None:
            seen.append((series, request.url.params["cosd"]))
        if series in broken:
            return httpx.Response(404, text="<!DOCTYPE html><title>Error - St. Louis Fed</title>")
        return httpx.Response(200, text=csv_text(fixtures_dir, series))

    return Fred(httpx.Client(transport=httpx.MockTransport(handler)))


def test_parse_skips_days_without_a_value(fixtures_dir):
    rows = parse_csv("T10Y2Y", csv_text(fixtures_dir, "T10Y2Y"), date(2025, 7, 22), date(2026, 10, 15))
    assert len(rows) == 123
    assert (rows[0].day, rows[0].value) == (date(2026, 4, 20), 0.54)
    assert (rows[-1].day, rows[-1].value) == (date(2026, 10, 14), 0.37)
    assert date(2026, 10, 12) not in {r.day for r in rows}  # Columbus Day: an empty field


def test_parse_keeps_only_the_window_because_fred_may_ignore_the_start(fixtures_dir):
    rows = parse_csv("T10Y2Y", csv_text(fixtures_dir, "T10Y2Y"), date(2026, 10, 1), date(2026, 10, 13))
    assert [r.day for r in rows][0] == date(2026, 10, 1)
    assert rows[-1].day == date(2026, 10, 13)  # 2026-10-14 is after `end`


@pytest.mark.parametrize(
    "body",
    [
        "<!DOCTYPE html><title>Error - St. Louis Fed</title>",  # an error page
        "PK\x03\x04 fredgraph.zip",  # several series with different dates come back zipped
        "observation_date,DGS2\n2026-10-13,4.79\n",  # someone else's series
        "",
    ],
)
def test_anything_but_the_series_csv_is_an_error(body):
    with pytest.raises(ValueError, match="FRED sent no CSV for DGS10"):
        parse_csv("DGS10", body, date(2026, 1, 1), date(2026, 10, 15))


def test_fetch_asks_once_per_series_from_the_lookback(fixtures_dir):
    seen: list = []
    records = serving(fixtures_dir, seen).fetch([], AS_OF)
    assert seen == [(series, "2025-07-22") for series in SERIES]
    assert len(records) == 950
    cpi = [r for r in records if r.series == "CPIAUCSL"]
    assert (len(cpi), cpi[0].day, cpi[-1].day, cpi[-1].value) == (
        13, date(2025, 8, 1), date(2026, 9, 1), 336.298
    )  # September 2025 is in the window: year-over-year needs it
    assert {r.series for r in records} == set(SERIES)


def test_a_failing_series_is_a_partial_result(fixtures_dir):
    failed = "1 of 9 FRED series failed; first: VIXCLS: HTTPStatusError"
    with pytest.raises(PartialFetch, match=failed) as caught:
        serving(fixtures_dir, broken=frozenset({"VIXCLS"})).fetch([], AS_OF)
    assert len(caught.value.records) == 950 - 128
    assert "VIXCLS" not in {r.series for r in caught.value.records}


def test_every_series_failing_fails_the_source(fixtures_dir):
    with pytest.raises(PartialFetch, match="9 of 9 FRED series failed") as caught:
        serving(fixtures_dir, broken=frozenset(SERIES)).fetch([], AS_OF)
    assert caught.value.records == []  # an empty PartialFetch counts as a failure
```

In `pipeline/tests/unit/test_registry.py`:
- after the `BOTH = …` line, add:

  ```python
  NONE: frozenset[Market] = frozenset()  # crypto belongs to no stock market
  ```

- add this row at the end of `EXPECTED`:

  ```python
      "fred": (True, Scope.MARKET, True, BOTH),
  ```

`NONE` is used from Task 3 on. ruff does not flag an unused module constant.

- [ ] **Step 2: Run them to verify they fail**

Run: `pipeline/scripts/in-docker.sh uv run pytest tests/unit/test_fred.py tests/unit/test_registry.py -q`
Expected:
- `ModuleNotFoundError: No module named 'advisor.collectors.fred'`;
- the registry test fails on the missing `fred` row.

- [ ] **Step 3: Implement**

Create `pipeline/src/advisor/collectors/series.py`:

```python
"""Day-by-day numbers shared by sources that publish one value per series per day."""

from datetime import date

from pydantic import BaseModel, ConfigDict


class SeriesObservation(BaseModel):
    model_config = ConfigDict(frozen=True)

    series: str
    day: date
    value: float
```

In `pipeline/src/advisor/collectors/boc_valet.py`:
- delete the `class SeriesObservation(BaseModel): …` block (8 lines, with its two trailing blank lines) and the now-unused `from pydantic import BaseModel, ConfigDict` line;
- add `from advisor.collectors.series import SeriesObservation` after the `from advisor.collectors.base import (…)` block.

Nothing else in the file changes. The existing Valet tests keep passing.

Create `pipeline/src/advisor/collectors/fred.py`:

```python
"""US macro series from FRED's public CSV download (spec source 20; core).

One keyless request per series. Several series in one request come back as a ZIP when their
dates differ, and a multi-series start date is silently ignored, so FRED is asked one series at
a time and rows outside the window are dropped here. Dates are observation dates, not release
dates (September's CPI is published in mid-October): Plan 3 applies the release lags. A day
without a value (a bond-market holiday) is an empty field.
"""

import math
from collections.abc import Sequence
from datetime import date, datetime, timedelta

import httpx

from advisor.collectors.base import (
    Cadence,
    Category,
    PartialFetch,
    RateLimiter,
    Scope,
    check_deadline,
    get_with_retries,
)
from advisor.collectors.series import SeriesObservation
from advisor.models import ET, AssetType, Market

FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
FRED_PER_MINUTE = 30
SERIES = {
    "T10Y2Y": "10-year minus 2-year Treasury yield, percentage points",
    "T10Y3M": "10-year minus 3-month Treasury yield, percentage points",
    "DGS10": "10-year Treasury yield",
    "DGS2": "2-year Treasury yield",
    "VIXCLS": "VIX close",
    "BAMLH0A0HYM2": "ICE BofA US high-yield option-adjusted spread",
    "DFF": "effective federal funds rate, daily",
    "CPIAUCSL": "CPI for all urban consumers, monthly, seasonally adjusted",
    "UNRATE": "unemployment rate, monthly",
}
LOOKBACK = timedelta(days=450)  # 13 months of a monthly series plus its release lag, for YoY
HEADER = "observation_date"


def parse_csv(series: str, text: str, start: date, end: date) -> list[SeriesObservation]:
    """One series' values from `start` to `end`; anything but FRED's CSV is an error."""
    lines = text.lstrip("﻿").splitlines()
    if not lines or lines[0].split(",") != [HEADER, series]:
        raise ValueError(f"FRED sent no CSV for {series}")
    rows: list[SeriesObservation] = []
    for line in lines[1:]:
        day_text, _, raw = line.partition(",")
        day = date.fromisoformat(day_text)
        try:
            value = float(raw)
        except ValueError:  # "" (or ".") marks a day without a value
            continue
        if start <= day <= end and math.isfinite(value):
            rows.append(SeriesObservation(series=series, day=day, value=value))
    return rows


class Fred:
    name = "fred"
    category = Category.MACRO
    core = True
    best_effort = False
    cadence = Cadence.DAILY
    asset_types = frozenset({AssetType.STOCK})
    markets = frozenset({Market.US, Market.TSX})  # US rates and risk appetite move both markets
    record_type = SeriesObservation
    freshness = timedelta(days=7)
    scope = Scope.MARKET
    canary: tuple[str, ...] = ()
    canary_requires_records = True
    max_symbols = None

    def __init__(self, client: httpx.Client, limiter: RateLimiter | None = None) -> None:
        self._client = client
        self._limiter = limiter

    def fetch(self, symbols: Sequence[str], as_of: datetime) -> list[SeriesObservation]:
        end = as_of.astimezone(ET).date()
        start = end - LOOKBACK
        records: list[SeriesObservation] = []
        failures: list[str] = []
        for series in SERIES:
            check_deadline()
            try:
                response = get_with_retries(
                    self._client,
                    FRED_URL,
                    params={"id": series, "cosd": start.isoformat()},
                    limiter=self._limiter,
                )
                rows = parse_csv(series, response.text, start, end)
            except (httpx.HTTPError, ValueError) as exc:
                failures.append(f"{series}: {type(exc).__name__}: {exc}"[:200])
                continue
            if not rows:
                failures.append(f"{series}: no values since {start}")
            records.extend(rows)
        if failures:
            raise PartialFetch(
                records, f"{len(failures)} of {len(SERIES)} FRED series failed; first: {failures[0]}"
            )
        return records
```

In `pipeline/src/advisor/collectors/registry.py`:
- add `from advisor.collectors.fred import FRED_PER_MINUTE, Fred`;
- add this line after `SecHolders(sec),`:

  ```python
          Fred(client, RateLimiter(per_minute=FRED_PER_MINUTE, burst=3)),
  ```

- [ ] **Step 4: Run the tests and lint**

Run:
- `pipeline/scripts/in-docker.sh uv run pytest tests/unit/test_fred.py tests/unit/test_boc_valet.py tests/unit/test_registry.py -q`;
- then the full suite, `pipeline/scripts/in-docker.sh uv run pytest -q`;
- then `pipeline/scripts/in-docker.sh uv run ruff check .`.

Expected: everything passes, and ruff reports `All checks passed!`.

- [ ] **Step 5: Commit**

```bash
git add pipeline/src/advisor/collectors/series.py pipeline/src/advisor/collectors/fred.py \
  pipeline/src/advisor/collectors/boc_valet.py pipeline/src/advisor/collectors/registry.py \
  pipeline/tests/unit/test_fred.py pipeline/tests/unit/test_registry.py
git commit -m "feat: add FRED macro series as a core source; share the series record"
```

End the message with your `Co-Authored-By:` trailer.

---

### Task 2: FOMC releases and meetings (source 21)

**Files:**
- Create: `pipeline/src/advisor/collectors/fomc.py`, `pipeline/tests/unit/test_fomc.py`
- Modify: `pipeline/src/advisor/collectors/registry.py`, `pipeline/tests/unit/test_registry.py`
- Fixtures (already committed):
  - `pipeline/tests/fixtures/fomc/fomc_press_monetary.xml`: the feed's first 10 items. It starts with a UTF-8 BOM, which ElementTree accepts.
  - `fomc_calendars_2026_excerpt.html`: the page's 2026 panel.

**Interfaces:**
- Consumes: the base helpers as in Task 1.
- Produces:
  - `FomcEvent(kind, day, title, url, published_at=None)`, where `kind` is one of `statement`, `minutes`, `projections`, `other` or `meeting`;
  - `Fomc(client, limiter=None)` named `fomc`: PER_RUN, MARKET, freshness 7 days, markets US and TSX;
  - `RSS_URL`, `CALENDAR_URL`, `release_kind`, `parse_releases(xml, as_of)`, `decision_day(year, month_cell, date_cell)` and `parse_calendar(html, as_of)`.

- [ ] **Step 1: Write the failing tests**

Create `pipeline/tests/unit/test_fomc.py`:

```python
from datetime import UTC, date, datetime

import httpx
import pytest

from advisor.collectors.base import PartialFetch
from advisor.collectors.fomc import (
    CALENDAR_URL,
    RSS_URL,
    Fomc,
    decision_day,
    parse_calendar,
    parse_releases,
)

AS_OF = datetime(2026, 10, 15, 12, 15, tzinfo=UTC)


def feed(fixtures_dir) -> bytes:
    return (fixtures_dir / "fomc" / "fomc_press_monetary.xml").read_bytes()  # starts with a BOM


def calendar(fixtures_dir) -> str:
    return (fixtures_dir / "fomc" / "fomc_calendars_2026_excerpt.html").read_text(encoding="utf-8")


def serving(routes: dict[str, httpx.Response]) -> Fomc:
    def handler(request: httpx.Request) -> httpx.Response:
        return routes.get(str(request.url), httpx.Response(404))

    return Fomc(httpx.Client(transport=httpx.MockTransport(handler)))


def test_releases_are_told_apart_by_title(fixtures_dir):
    events = parse_releases(feed(fixtures_dir), AS_OF)
    assert [(e.kind, e.day) for e in events] == [
        ("other", date(2026, 10, 13)),  # minutes of the Board's discount rate meetings
        ("minutes", date(2026, 10, 7)),
        ("statement", date(2026, 9, 16)),
        ("projections", date(2026, 9, 16)),
        ("other", date(2026, 8, 25)),
        ("minutes", date(2026, 8, 19)),
        ("statement", date(2026, 7, 29)),
        ("other", date(2026, 7, 14)),
        ("other", date(2026, 7, 9)),
        ("minutes", date(2026, 7, 8)),
    ]
    statement = events[2]
    assert statement.published_at == datetime(2026, 9, 16, 18, 0, tzinfo=UTC)  # 14:00 ET
    assert statement.url == "https://www.federalreserve.gov/newsevents/pressreleases/monetary20260916a.htm"


def test_releases_after_as_of_are_left_out(fixtures_dir):
    events = parse_releases(feed(fixtures_dir), datetime(2026, 9, 16, 17, 59, tzinfo=UTC))
    assert [e.day for e in events if e.kind == "statement"] == [date(2026, 7, 29)]


@pytest.mark.parametrize(
    ("year", "month_cell", "date_cell", "expected"),
    [
        (2026, "October", "27-28", date(2026, 10, 28)),
        (2026, "March", "17-18*", date(2026, 3, 18)),
        (2019, "Apr/May", "30-1", date(2019, 5, 1)),
        (2025, "January", "22 (notation vote)", date(2025, 1, 22)),
    ],
)
def test_the_decision_comes_on_a_meetings_last_day(year, month_cell, date_cell, expected):
    assert decision_day(year, month_cell, date_cell) == expected


def test_the_calendar_keeps_upcoming_and_recent_meetings(fixtures_dir):
    meetings = parse_calendar(calendar(fixtures_dir), AS_OF)
    assert [(m.kind, m.day, m.title) for m in meetings] == [
        ("meeting", date(2026, 9, 16), "FOMC meeting, September 15-16, 2026"),
        ("meeting", date(2026, 10, 28), "FOMC meeting, October 27-28, 2026"),
        ("meeting", date(2026, 12, 9), "FOMC meeting, December 8-9, 2026"),
    ]


def test_fetch_returns_releases_then_meetings(fixtures_dir):
    events = serving({
        RSS_URL: httpx.Response(200, content=feed(fixtures_dir)),
        CALENDAR_URL: httpx.Response(200, text=calendar(fixtures_dir)),
    }).fetch([], AS_OF)
    assert len(events) == 13
    assert [e.kind for e in events[-3:]] == ["meeting"] * 3


@pytest.mark.parametrize(
    ("page", "message"),
    [
        (httpx.Response(404), "FOMC calendar unreadable: HTTPStatusError"),
        (httpx.Response(200, text="<html>a redesigned page</html>"), "lists no upcoming"),
    ],
)
def test_an_unreadable_calendar_keeps_the_releases(fixtures_dir, page, message):
    with pytest.raises(PartialFetch, match=message) as caught:
        serving({RSS_URL: httpx.Response(200, content=feed(fixtures_dir)), CALENDAR_URL: page}).fetch(
            [], AS_OF
        )
    assert len(caught.value.records) == 10


def test_a_missing_feed_fails_the_source(fixtures_dir):
    with pytest.raises(httpx.HTTPStatusError, match="HTTP 404"):
        serving({CALENDAR_URL: httpx.Response(200, text=calendar(fixtures_dir))}).fetch([], AS_OF)
```

Add this row at the end of `EXPECTED` in `pipeline/tests/unit/test_registry.py`:

```python
    "fomc": (False, Scope.MARKET, True, BOTH),
```

- [ ] **Step 2: Run them to verify they fail**

Run: `pipeline/scripts/in-docker.sh uv run pytest tests/unit/test_fomc.py tests/unit/test_registry.py -q`
Expected: `ModuleNotFoundError: No module named 'advisor.collectors.fomc'`, and the registry lacks `fomc`.

- [ ] **Step 3: Implement**

Create `pipeline/src/advisor/collectors/fomc.py`:

```python
"""FOMC statements, minutes and meeting dates from the Federal Reserve (spec source 21).

Two keyless requests per run:
- the monetary-policy press-release RSS feed, which holds the last 15 or so releases;
- the meeting calendar page, which has no feed; it is read by its stable `fomc-meeting__*`
  class names. A meeting's decision comes at 14:00 ET on its last day.

A statement is the release titled exactly "Federal Reserve issues FOMC statement"; "Minutes of
the Board's discount rate meetings" are not FOMC minutes.
"""

import re
import xml.etree.ElementTree as ElementTree
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict

from advisor.collectors.base import (
    Cadence,
    Category,
    PartialFetch,
    RateLimiter,
    Scope,
    get_with_retries,
)
from advisor.models import ET, AssetType, Market

RSS_URL = "https://www.federalreserve.gov/feeds/press_monetary.xml"
CALENDAR_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
STATEMENT = "Federal Reserve issues FOMC statement"
MINUTES = "Minutes of the Federal Open Market Committee"
RECENT = timedelta(days=60)  # past meetings kept, besides every upcoming one

YEAR = re.compile(r">(\d{4}) FOMC Meetings<")
MONTH_CELL = re.compile(r"fomc-meeting__month[^>]*>\s*<strong>([^<]+)</strong>")
DATE_CELL = re.compile(r"fomc-meeting__date[^>]*>([^<]+)<")
MONTHS = {
    name: number
    for number, name in enumerate(
        ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"),
        start=1,
    )
}

Kind = Literal["statement", "minutes", "projections", "other", "meeting"]


class FomcEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Kind
    day: date  # the release's ET date, or the meeting's decision day
    title: str
    url: str
    published_at: datetime | None = None  # releases only


def release_kind(title: str) -> Kind:
    if title == STATEMENT:
        return "statement"
    if title.startswith(MINUTES):
        return "minutes"
    if "economic projections" in title.lower():
        return "projections"
    return "other"


def parse_releases(xml: bytes, as_of: datetime) -> list[FomcEvent]:
    """Releases published by `as_of`, newest first as the feed lists them."""
    events: list[FomcEvent] = []
    for item in ElementTree.fromstring(xml).iter("item"):
        title = (item.findtext("title") or "").strip()
        published = parsedate_to_datetime((item.findtext("pubDate") or "").strip())
        if published > as_of:
            continue
        events.append(FomcEvent(
            kind=release_kind(title),
            day=published.astimezone(ET).date(),
            title=title,
            url=(item.findtext("link") or "").strip(),
            published_at=published,
        ))
    return events


def decision_day(year: int, month_cell: str, date_cell: str) -> date:
    """The meeting's last day: "27-28" in "October", "30-1" in "Apr/May", "22 (notation vote)"."""
    month = MONTHS[month_cell.split("/")[-1].strip()[:3].lower()]
    return date(year, month, int(re.findall(r"\d+", date_cell)[-1]))


def parse_calendar(html: str, as_of: datetime) -> list[FomcEvent]:
    """Upcoming meetings and those of the last 60 days, from each year's panel in page order."""
    cutoff = as_of.astimezone(ET).date() - RECENT
    years = list(YEAR.finditer(html))
    events: list[FomcEvent] = []
    for index, heading in enumerate(years):
        end = years[index + 1].start() if index + 1 < len(years) else len(html)
        panel = html[heading.end():end]
        year = int(heading.group(1))
        cells = zip(MONTH_CELL.findall(panel), DATE_CELL.findall(panel), strict=True)
        for month_cell, date_cell in cells:
            day = decision_day(year, month_cell, date_cell)
            if day >= cutoff:
                days = date_cell.replace("*", "").strip()  # * marks a meeting with projections
                events.append(FomcEvent(
                    kind="meeting",
                    day=day,
                    title=f"FOMC meeting, {month_cell.strip()} {days}, {year}",
                    url=CALENDAR_URL,
                ))
    return sorted(events, key=lambda event: event.day)


class Fomc:
    name = "fomc"
    category = Category.MACRO
    core = False
    best_effort = False
    cadence = Cadence.PER_RUN  # a statement lands at 14:00 ET, before the pre-close run
    asset_types = frozenset({AssetType.STOCK})
    markets = frozenset({Market.US, Market.TSX})
    record_type = FomcEvent
    freshness = timedelta(days=7)
    scope = Scope.MARKET
    canary: tuple[str, ...] = ()
    canary_requires_records = True
    max_symbols = None

    def __init__(self, client: httpx.Client, limiter: RateLimiter | None = None) -> None:
        self._client = client
        self._limiter = limiter

    def fetch(self, symbols: Sequence[str], as_of: datetime) -> list[FomcEvent]:
        feed = get_with_retries(self._client, RSS_URL, limiter=self._limiter)
        releases = parse_releases(feed.content, as_of)
        try:
            page = get_with_retries(self._client, CALENDAR_URL, limiter=self._limiter)
            meetings = parse_calendar(page.text, as_of)
        except (httpx.HTTPError, ValueError, KeyError, IndexError) as exc:
            raise PartialFetch(
                releases, f"FOMC calendar unreadable: {type(exc).__name__}: {exc}"[:300]
            ) from exc
        if not meetings:
            raise PartialFetch(releases, "the FOMC calendar lists no upcoming or recent meetings")
        return releases + meetings
```

In `registry.py`:
- add `from advisor.collectors.fomc import Fomc`;
- add `Fomc(client),` after the `Fred(…)` line.

- [ ] **Step 4: Run the tests and lint**

Run the focused tests, then the full suite and `ruff check .` (commands as in Task 1).
Expected: everything passes, and ruff is clean.

- [ ] **Step 5: Commit**

```bash
git add pipeline/src/advisor/collectors/fomc.py pipeline/src/advisor/collectors/registry.py \
  pipeline/tests/unit/test_fomc.py pipeline/tests/unit/test_registry.py
git commit -m "feat: add FOMC statements, minutes and meeting dates"
```

End the message with your `Co-Authored-By:` trailer.

---

### Task 3: Fear & Greed indexes (sources 22 and 23)

**Files:**
- Create: `pipeline/src/advisor/collectors/cnn_fear_greed.py`, `pipeline/src/advisor/collectors/crypto_fear_greed.py`, `pipeline/tests/unit/test_cnn_fear_greed.py`, `pipeline/tests/unit/test_crypto_fear_greed.py`
- Modify: `registry.py`, `test_registry.py`
- Fixtures (already committed):
  - `pipeline/tests/fixtures/cnn/cnn_graphdata.json`: every top-level key, with each history trimmed to its last 30 points. 2026-10-15 appears twice: at 00:00 UTC and live at 19:12 UTC.
  - `pipeline/tests/fixtures/alternative/alternative_fng_limit30.json`.

**Interfaces:**
- Consumes: `SeriesObservation` (Task 1) and the base helpers.
- Produces:
  - `CnnFearGreed(client, limiter=None)` named `cnn_fear_greed`: best-effort, PER_RUN, MARKET, markets US, series `fear_greed`;
  - `CryptoFearGreed(client, limiter=None)` named `crypto_fear_greed`: DAILY, MARKET, asset type crypto, no markets, series `crypto_fear_greed`;
  - `parse_history(payload, as_of)` and `parse_index(payload, as_of)`.

- [ ] **Step 1: Write the failing tests**

Create `pipeline/tests/unit/test_cnn_fear_greed.py`:

```python
import json
from datetime import UTC, date, datetime

import httpx
import pytest

from advisor.collectors.cnn_fear_greed import CnnFearGreed, parse_history

AFTER_CLOSE = datetime(2026, 10, 15, 19, 20, tzinfo=UTC)


def payload(fixtures_dir) -> dict:
    return json.loads((fixtures_dir / "cnn" / "cnn_graphdata.json").read_text(encoding="utf-8"))


def test_one_reading_per_day_and_the_live_one_wins(fixtures_dir):
    rows = parse_history(payload(fixtures_dir), AFTER_CLOSE)
    assert len(rows) == 29  # 30 points; 2026-10-15 appears at 00:00 UTC and live at 19:12 UTC
    assert (rows[0].day, rows[0].series) == (date(2026, 9, 4), "fear_greed")
    assert (rows[-2].day, rows[-2].value) == (date(2026, 10, 14), 26.6566893424036)
    assert (rows[-1].day, rows[-1].value) == (date(2026, 10, 15), 31.2857142857143)


def test_readings_after_as_of_are_left_out(fixtures_dir):
    rows = parse_history(payload(fixtures_dir), datetime(2026, 10, 15, 12, 15, tzinfo=UTC))
    assert (rows[-1].day, rows[-1].value) == (date(2026, 10, 15), 31.3142857142857)


def test_no_readings_is_an_error(fixtures_dir):
    data = payload(fixtures_dir)
    data["fear_and_greed_historical"]["data"] = []
    with pytest.raises(ValueError, match="no Fear & Greed readings"):
        parse_history(data, AFTER_CLOSE)


def test_fetch_sends_cnns_referer_and_origin(fixtures_dir):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers.get("Referer") != "https://www.cnn.com/" or not request.headers.get("Origin"):
            return httpx.Response(418, text="I'm a teapot. You're a bot.")
        return httpx.Response(200, json=payload(fixtures_dir))

    rows = CnnFearGreed(httpx.Client(transport=httpx.MockTransport(handler))).fetch([], AFTER_CLOSE)
    assert len(rows) == 29


def test_a_bot_answer_fails_the_source():
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(418, text="bot")))
    with pytest.raises(httpx.HTTPStatusError, match="HTTP 418"):
        CnnFearGreed(client).fetch([], AFTER_CLOSE)
```

Create `pipeline/tests/unit/test_crypto_fear_greed.py`:

```python
import json
from datetime import UTC, date, datetime

import httpx
import pytest

from advisor.collectors.crypto_fear_greed import CryptoFearGreed, parse_index

AS_OF = datetime(2026, 10, 15, 19, 20, tzinfo=UTC)


def payload(fixtures_dir) -> dict:
    path = fixtures_dir / "alternative" / "alternative_fng_limit30.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_values_are_read_oldest_first(fixtures_dir):
    rows = parse_index(payload(fixtures_dir), AS_OF)
    assert len(rows) == 30
    assert {row.series for row in rows} == {"crypto_fear_greed"}
    assert [(r.day, r.value) for r in rows[-2:]] == [(date(2026, 10, 14), 62.0), (date(2026, 10, 15), 53.0)]


def test_values_after_as_of_are_left_out(fixtures_dir):
    rows = parse_index(payload(fixtures_dir), datetime(2026, 10, 14, 23, 59, tzinfo=UTC))
    assert (len(rows), rows[-1].day) == (29, date(2026, 10, 14))


def test_an_error_answer_is_an_error():
    answer = {"name": "Fear and Greed Index", "data": [], "metadata": {"error": "invalid 'limit' qualifier"}}
    with pytest.raises(ValueError, match="alternative.me: invalid 'limit' qualifier"):
        parse_index(answer, AS_OF)


def test_fetch_asks_for_30_days(fixtures_dir):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url)
        return httpx.Response(200, json=payload(fixtures_dir))

    rows = CryptoFearGreed(httpx.Client(transport=httpx.MockTransport(handler))).fetch([], AS_OF)
    [url] = seen
    assert (url.path, url.params["limit"], url.params["format"]) == ("/fng/", "30", "json")
    assert len(rows) == 30
```

Add these rows at the end of `EXPECTED`:

```python
    "cnn_fear_greed": (False, Scope.MARKET, True, US),
    "crypto_fear_greed": (False, Scope.MARKET, True, NONE),
```

- [ ] **Step 2: Run them to verify they fail**

Run: `pipeline/scripts/in-docker.sh uv run pytest tests/unit/test_cnn_fear_greed.py tests/unit/test_crypto_fear_greed.py tests/unit/test_registry.py -q`
Expected: `ModuleNotFoundError` for both modules, and the registry lacks both rows.

- [ ] **Step 3: Implement**

Create `pipeline/src/advisor/collectors/cnn_fear_greed.py`:

```python
"""CNN's Fear & Greed index for US stocks (spec source 22; unofficial, best-effort).

The endpoint answers 418 ("You're a bot") unless a request carries CNN's own Referer and Origin;
no browser User-Agent is needed. Daily points sit at 00:00 UTC of their day and the last point
is the live reading, so a day can appear twice: the later reading wins.
"""

import math
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx

from advisor.collectors.base import Cadence, Category, RateLimiter, Scope, get_with_retries
from advisor.collectors.series import SeriesObservation
from advisor.models import AssetType, Market

CNN_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
CNN_HEADERS = {"Referer": "https://www.cnn.com/", "Origin": "https://www.cnn.com"}
SERIES_NAME = "fear_greed"
LOOKBACK = timedelta(days=60)


def parse_history(payload: Mapping[str, Any], as_of: datetime) -> list[SeriesObservation]:
    """One reading per UTC day from the last 60 days up to `as_of`, oldest first."""
    cutoff_ms = as_of.timestamp() * 1000
    start = as_of.astimezone(UTC).date() - LOOKBACK
    latest: dict[date, tuple[float, float]] = {}  # day -> (timestamp in ms, score)
    for point in payload["fear_and_greed_historical"]["data"]:
        stamp, score = float(point["x"]), float(point["y"])
        day = datetime.fromtimestamp(stamp / 1000, UTC).date()
        if stamp > cutoff_ms or day < start or not math.isfinite(score):
            continue
        if day not in latest or stamp > latest[day][0]:
            latest[day] = (stamp, score)
    if not latest:
        raise ValueError("CNN sent no Fear & Greed readings")
    return [
        SeriesObservation(series=SERIES_NAME, day=day, value=score)
        for day, (_, score) in sorted(latest.items())
    ]


class CnnFearGreed:
    name = "cnn_fear_greed"
    category = Category.MACRO
    core = False
    best_effort = True
    cadence = Cadence.PER_RUN  # the reading moves during the session
    asset_types = frozenset({AssetType.STOCK})
    markets = frozenset({Market.US})
    record_type = SeriesObservation
    freshness = timedelta(days=3)
    scope = Scope.MARKET
    canary: tuple[str, ...] = ()
    canary_requires_records = True
    max_symbols = None

    def __init__(self, client: httpx.Client, limiter: RateLimiter | None = None) -> None:
        self._client = client
        self._limiter = limiter

    def fetch(self, symbols: Sequence[str], as_of: datetime) -> list[SeriesObservation]:
        response = get_with_retries(
            self._client, CNN_URL, headers=CNN_HEADERS, limiter=self._limiter
        )
        return parse_history(response.json(), as_of)
```

Create `pipeline/src/advisor/collectors/crypto_fear_greed.py`:

```python
"""The Crypto Fear & Greed index from alternative.me (spec source 23).

One keyless call returns the last 30 daily values, newest first. Values and timestamps are
strings; a timestamp is 00:00 UTC of its day, and the day's value is published soon after. An
error comes back as HTTP 200 with `metadata.error` set and no data.
"""

import math
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from advisor.collectors.base import Cadence, Category, RateLimiter, Scope, get_with_retries
from advisor.collectors.series import SeriesObservation
from advisor.models import AssetType, Market

FNG_URL = "https://api.alternative.me/fng/"
SERIES_NAME = "crypto_fear_greed"
DAYS = 30


def parse_index(payload: Mapping[str, Any], as_of: datetime) -> list[SeriesObservation]:
    """Daily values up to `as_of`'s UTC day, oldest first."""
    error = (payload.get("metadata") or {}).get("error")
    if error:
        raise ValueError(f"alternative.me: {error}")
    today = as_of.astimezone(UTC).date()
    rows: list[SeriesObservation] = []
    for point in payload.get("data") or []:
        day = datetime.fromtimestamp(int(point["timestamp"]), UTC).date()
        value = float(point["value"])
        if day <= today and math.isfinite(value):
            rows.append(SeriesObservation(series=SERIES_NAME, day=day, value=value))
    if not rows:
        raise ValueError("alternative.me sent no Fear & Greed values")
    return sorted(rows, key=lambda row: row.day)


class CryptoFearGreed:
    name = "crypto_fear_greed"
    category = Category.MACRO
    core = False
    best_effort = False
    cadence = Cadence.DAILY
    asset_types = frozenset({AssetType.CRYPTO})
    markets: frozenset[Market] = frozenset()  # crypto belongs to no stock market
    record_type = SeriesObservation
    freshness = timedelta(days=3)
    scope = Scope.MARKET
    canary: tuple[str, ...] = ()
    canary_requires_records = True
    max_symbols = None

    def __init__(self, client: httpx.Client, limiter: RateLimiter | None = None) -> None:
        self._client = client
        self._limiter = limiter

    def fetch(self, symbols: Sequence[str], as_of: datetime) -> list[SeriesObservation]:
        response = get_with_retries(
            self._client,
            FNG_URL,
            params={"limit": DAYS, "format": "json"},
            limiter=self._limiter,
        )
        return parse_index(response.json(), as_of)
```

In `registry.py`:
- add `from advisor.collectors.cnn_fear_greed import CnnFearGreed` and `from advisor.collectors.crypto_fear_greed import CryptoFearGreed`;
- add these lines after `Fomc(client),`:

  ```python
          CnnFearGreed(client),
          CryptoFearGreed(client),
  ```

- [ ] **Step 4: Run the tests and lint**

Run the focused tests, then the full suite and `ruff check .`.
Expected: everything passes, and ruff is clean.

- [ ] **Step 5: Commit**

```bash
git add pipeline/src/advisor/collectors/cnn_fear_greed.py \
  pipeline/src/advisor/collectors/crypto_fear_greed.py pipeline/src/advisor/collectors/registry.py \
  pipeline/tests/unit/test_cnn_fear_greed.py pipeline/tests/unit/test_crypto_fear_greed.py \
  pipeline/tests/unit/test_registry.py
git commit -m "feat: add the CNN and crypto Fear & Greed indexes"
```

End the message with your `Co-Authored-By:` trailer.

---

### Task 4: Bitcoin network stats from blockchain.com (source 53)

**Files:**
- Create: `pipeline/src/advisor/collectors/blockchain_stats.py`, `pipeline/tests/unit/test_blockchain_stats.py`
- Modify: `registry.py`, `test_registry.py`
- Fixtures (already committed): `pipeline/tests/fixtures/blockchain/blockchain_chart_<name>_90d.json` for the five charts. Each has 90 daily points ending 2026-10-14.

**Interfaces:**
- Consumes: `SeriesObservation` (Task 1), the base helpers, and `fakes.FakeClock`.
- Produces:
  - `BlockchainStats(client, limiter=None)` named `blockchain_stats`: DAILY, MARKET, asset type crypto, no markets;
  - `BLOCKCHAIN_PER_MINUTE = 6`, `CHARTS`, `TIMESPAN = "60days"` and `parse_chart(name, payload, as_of)`.

- [ ] **Step 1: Write the failing tests**

Create `pipeline/tests/unit/test_blockchain_stats.py`:

```python
import json
from datetime import UTC, date, datetime

import httpx
import pytest

from advisor.collectors.base import PartialFetch, RateLimiter
from advisor.collectors.blockchain_stats import CHARTS, BlockchainStats, parse_chart
from fakes import FakeClock

AS_OF = datetime(2026, 10, 15, 12, 15, tzinfo=UTC)


def chart(fixtures_dir, name: str) -> dict:
    path = fixtures_dir / "blockchain" / f"blockchain_chart_{name}_90d.json"
    return json.loads(path.read_text(encoding="utf-8"))


def serving(fixtures_dir, seen: list, broken: str | None = None, limiter=None) -> BlockchainStats:
    def handler(request: httpx.Request) -> httpx.Response:
        name = request.url.path.removeprefix("/charts/")
        seen.append((name, request.url.params["timespan"]))
        if name == broken:
            return httpx.Response(404, json={"status": "not-found", "error": None})
        return httpx.Response(200, json=chart(fixtures_dir, name))

    return BlockchainStats(httpx.Client(transport=httpx.MockTransport(handler)), limiter)


def test_a_chart_is_read_as_finished_days(fixtures_dir):
    rows = parse_chart("hash-rate", chart(fixtures_dir, "hash-rate"), AS_OF)
    assert (len(rows), rows[0].day) == (90, date(2026, 7, 17))
    assert (rows[-1].series, rows[-1].day, rows[-1].value) == (
        "hash-rate", date(2026, 10, 14), 1062173070.0244452
    )


def test_a_day_not_finished_by_as_of_is_left_out(fixtures_dir):
    rows = parse_chart("hash-rate", chart(fixtures_dir, "hash-rate"), datetime(2026, 10, 14, 12, tzinfo=UTC))
    assert (len(rows), rows[-1].day) == (89, date(2026, 10, 13))


def test_a_not_found_answer_is_an_error():
    with pytest.raises(ValueError, match="chart nope answered 'not-found'"):
        parse_chart("nope", {"status": "not-found", "error": None}, AS_OF)


def test_fetch_asks_for_each_chart_ten_seconds_apart(fixtures_dir):
    seen: list = []
    clock = FakeClock()
    limiter = RateLimiter(per_minute=6, burst=1, clock=clock, sleep=clock.sleep)
    records = serving(fixtures_dir, seen, limiter=limiter).fetch([], AS_OF)
    assert seen == [(name, "60days") for name in CHARTS]
    assert clock.sleeps == [10.0] * 4
    assert len(records) == 450


def test_a_failing_chart_is_a_partial_result(fixtures_dir):
    failed = "1 of 5 blockchain.com charts failed; first: difficulty: HTTPStatusError"
    with pytest.raises(PartialFetch, match=failed) as caught:
        serving(fixtures_dir, [], broken="difficulty").fetch([], AS_OF)
    assert len(caught.value.records) == 360
```

Add this row at the end of `EXPECTED`:

```python
    "blockchain_stats": (False, Scope.MARKET, True, NONE),
```

- [ ] **Step 2: Run them to verify they fail**

Run: `pipeline/scripts/in-docker.sh uv run pytest tests/unit/test_blockchain_stats.py tests/unit/test_registry.py -q`
Expected: `ModuleNotFoundError: No module named 'advisor.collectors.blockchain_stats'`, and the registry lacks the row.

- [ ] **Step 3: Implement**

Create `pipeline/src/advisor/collectors/blockchain_stats.py`:

```python
"""Bitcoin network activity from blockchain.com's chart API (spec source 53).

One keyless request per chart (several charts in one request answer 404), spaced about 10 s
apart. Each daily point sits at 00:00 UTC and the last one is yesterday's, so every point is a
finished day. The chart API reports hash rate in TH/s.
"""

import math
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from advisor.collectors.base import (
    Cadence,
    Category,
    PartialFetch,
    RateLimiter,
    Scope,
    check_deadline,
    get_with_retries,
)
from advisor.collectors.series import SeriesObservation
from advisor.models import AssetType, Market

CHART_URL = "https://api.blockchain.info/charts/{name}"
BLOCKCHAIN_PER_MINUTE = 6  # one chart every 10 s
CHARTS = {
    "hash-rate": "network hash rate, TH/s",
    "difficulty": "mining difficulty",
    "n-transactions": "confirmed transactions per day",
    "transaction-fees-usd": "transaction fees paid per day, USD",
    "estimated-transaction-volume-usd": "estimated value moved on chain per day, USD",
}
TIMESPAN = "60days"


def parse_chart(name: str, payload: Mapping[str, Any], as_of: datetime) -> list[SeriesObservation]:
    """A chart's finished days before `as_of`'s UTC day, oldest first."""
    if payload.get("status") != "ok":
        raise ValueError(f"blockchain.com chart {name} answered {payload.get('status')!r}")
    today = as_of.astimezone(UTC).date()
    rows: list[SeriesObservation] = []
    for point in payload.get("values") or []:
        day = datetime.fromtimestamp(point["x"], UTC).date()
        value = float(point["y"])
        if day < today and math.isfinite(value):
            rows.append(SeriesObservation(series=name, day=day, value=value))
    return rows


class BlockchainStats:
    name = "blockchain_stats"
    category = Category.ONCHAIN
    core = False
    best_effort = False
    cadence = Cadence.DAILY
    asset_types = frozenset({AssetType.CRYPTO})
    markets: frozenset[Market] = frozenset()
    record_type = SeriesObservation
    freshness = timedelta(days=3)
    scope = Scope.MARKET
    canary: tuple[str, ...] = ()
    canary_requires_records = True
    max_symbols = None

    def __init__(self, client: httpx.Client, limiter: RateLimiter | None = None) -> None:
        self._client = client
        self._limiter = limiter

    def fetch(self, symbols: Sequence[str], as_of: datetime) -> list[SeriesObservation]:
        records: list[SeriesObservation] = []
        failures: list[str] = []
        for name in CHARTS:
            check_deadline()
            try:
                response = get_with_retries(
                    self._client,
                    CHART_URL.format(name=name),
                    params={"timespan": TIMESPAN, "format": "json", "sampled": "false"},
                    limiter=self._limiter,
                )
                rows = parse_chart(name, response.json(), as_of)
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                failures.append(f"{name}: {type(exc).__name__}: {exc}"[:200])
                continue
            if not rows:
                failures.append(f"{name}: no finished days")
            records.extend(rows)
        if failures:
            raise PartialFetch(
                records,
                f"{len(failures)} of {len(CHARTS)} blockchain.com charts failed; first: {failures[0]}",
            )
        return records
```

In `registry.py`:
- add `from advisor.collectors.blockchain_stats import BLOCKCHAIN_PER_MINUTE, BlockchainStats`;
- add this line after `CryptoFearGreed(client),`:

  ```python
          BlockchainStats(client, RateLimiter(per_minute=BLOCKCHAIN_PER_MINUTE, burst=1)),
  ```

- [ ] **Step 4: Run the tests and lint**

Run the focused tests, then the full suite and `ruff check .`.
Expected: everything passes, and ruff is clean.

- [ ] **Step 5: Commit**

```bash
git add pipeline/src/advisor/collectors/blockchain_stats.py pipeline/src/advisor/collectors/registry.py \
  pipeline/tests/unit/test_blockchain_stats.py pipeline/tests/unit/test_registry.py
git commit -m "feat: add Bitcoin network stats from blockchain.com"
```

End the message with your `Co-Authored-By:` trailer.

---

### Task 5: Chain TVL from DefiLlama (source 52)

**Files:**
- Create: `pipeline/src/advisor/collectors/defillama_tvl.py`, `pipeline/tests/unit/test_defillama_tvl.py`
- Modify: `registry.py`, `test_registry.py`
- Fixtures (already committed): `pipeline/tests/fixtures/defillama/defillama_historical_{Ethereum,Solana}_trimmed.json`. Each has the last 120 points; the last one (2026-10-15) is a live partial day.

**Interfaces:**
- Consumes: the base helpers, including `collect_per_symbol`.
- Produces:
  - `ChainTvl(symbol, chain, day, tvl_usd)`;
  - `DefiLlamaTvl(client, limiter=None)` named `defillama_tvl`: DAILY, SYMBOLS, asset type crypto, no markets, canary `("ETH",)`;
  - `DEFILLAMA_PER_MINUTE = 60`, `CHAINS` and `parse_history(symbol, chain, points, as_of)`.

- [ ] **Step 1: Write the failing tests**

Create `pipeline/tests/unit/test_defillama_tvl.py`:

```python
import json
from datetime import UTC, date, datetime

import httpx
import pytest

from advisor.collectors.base import PartialFetch
from advisor.collectors.defillama_tvl import DefiLlamaTvl, parse_history

AS_OF = datetime(2026, 10, 15, 12, 15, tzinfo=UTC)


def points(fixtures_dir, chain: str) -> list[dict]:
    path = fixtures_dir / "defillama" / f"defillama_historical_{chain}_trimmed.json"
    return json.loads(path.read_text(encoding="utf-8"))


def serving(fixtures_dir, seen: list) -> DefiLlamaTvl:
    def handler(request: httpx.Request) -> httpx.Response:
        chain = request.url.path.removeprefix("/v2/historicalChainTvl/")
        seen.append(chain)
        if chain not in ("Ethereum", "Solana"):
            return httpx.Response(404, text="<html><center>404 Not Found</center></html>")
        return httpx.Response(200, json=points(fixtures_dir, chain))

    return DefiLlamaTvl(httpx.Client(transport=httpx.MockTransport(handler)))


def test_the_last_60_finished_days_are_kept(fixtures_dir):
    rows = parse_history("ETH", "Ethereum", points(fixtures_dir, "Ethereum"), AS_OF)
    assert (len(rows), rows[0].day) == (60, date(2026, 8, 16))
    assert (rows[-1].symbol, rows[-1].chain, rows[-1].day, rows[-1].tvl_usd) == (
        "ETH", "Ethereum", date(2026, 10, 14), 50917908224.0
    )  # 2026-10-15 is still moving


def test_days_without_tvl_are_dropped():
    zeros = [{"date": 1791849600, "tvl": 0}, {"date": 1791936000, "tvl": 0}]  # a chain with no TVL
    assert parse_history("DOT", "Polkadot", zeros, AS_OF) == []


def test_each_coin_with_a_chain_gets_one_request(fixtures_dir):
    seen: list = []
    rows = serving(fixtures_dir, seen).fetch(["SOL", "LINK", "ETH"], AS_OF)
    assert seen == ["Solana", "Ethereum"]  # LINK has no chain of its own: no request
    assert [(symbol, len([r for r in rows if r.symbol == symbol])) for symbol in ("SOL", "ETH")] == [
        ("SOL", 60), ("ETH", 60)
    ]


def test_a_failing_chain_is_a_partial_result(fixtures_dir):
    with pytest.raises(PartialFetch, match="1 of 2 symbols failed; first: AVAX: HTTPStatusError") as caught:
        serving(fixtures_dir, []).fetch(["AVAX", "ETH"], AS_OF)
    assert {r.symbol for r in caught.value.records} == {"ETH"}
```

Add this row at the end of `EXPECTED`:

```python
    "defillama_tvl": (False, Scope.SYMBOLS, True, NONE),
```

- [ ] **Step 2: Run them to verify they fail**

Run: `pipeline/scripts/in-docker.sh uv run pytest tests/unit/test_defillama_tvl.py tests/unit/test_registry.py -q`
Expected: `ModuleNotFoundError: No module named 'advisor.collectors.defillama_tvl'`, and the registry lacks the row.

- [ ] **Step 3: Implement**

Create `pipeline/src/advisor/collectors/defillama_tvl.py`:

```python
"""Total value locked on a coin's own chain, from DefiLlama's free API (spec source 52).

One keyless request per held or watched coin that has a chain. The coin -> chain map is
hard-coded: `/v2/chains` symbols are unreliable (Polygon is POL, TON shows GRAM, and many
chains have none). Each point is 00:00 UTC of its day and the last one is a live partial day,
so only finished days are kept. A chain with no TVL answers zeros, which are dropped.
"""

import math
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict

from advisor.collectors.base import (
    Cadence,
    Category,
    RateLimiter,
    Scope,
    collect_per_symbol,
    get_with_retries,
)
from advisor.models import AssetType, Market

CHAIN_URL = "https://api.llama.fi/v2/historicalChainTvl/{chain}"
DEFILLAMA_PER_MINUTE = 60
CHAINS = {
    "ETH": "Ethereum",
    "SOL": "Solana",
    "AVAX": "Avalanche",
    "BNB": "BSC",
    "TRX": "Tron",
    "ADA": "Cardano",
    "POL": "Polygon",
    "MATIC": "Polygon",  # MATIC became POL
    "BTC": "Bitcoin",
}
LOOKBACK = timedelta(days=60)


class ChainTvl(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    chain: str
    day: date
    tvl_usd: float


def parse_history(
    symbol: str, chain: str, points: Sequence[dict[str, Any]], as_of: datetime
) -> list[ChainTvl]:
    """Finished days of the last 60, oldest first; days without TVL are dropped."""
    today = as_of.astimezone(UTC).date()
    start = today - LOOKBACK
    rows: list[ChainTvl] = []
    for point in points:
        day = datetime.fromtimestamp(point["date"], UTC).date()
        tvl = float(point["tvl"])
        if start <= day < today and tvl > 0 and math.isfinite(tvl):
            rows.append(ChainTvl(symbol=symbol, chain=chain, day=day, tvl_usd=tvl))
    return rows


class DefiLlamaTvl:
    name = "defillama_tvl"
    category = Category.ONCHAIN
    core = False
    best_effort = False
    cadence = Cadence.DAILY
    asset_types = frozenset({AssetType.CRYPTO})
    markets: frozenset[Market] = frozenset()
    record_type = ChainTvl
    freshness = timedelta(days=3)
    scope = Scope.SYMBOLS
    canary = ("ETH",)
    canary_requires_records = True
    max_symbols = None

    def __init__(self, client: httpx.Client, limiter: RateLimiter | None = None) -> None:
        self._client = client
        self._limiter = limiter

    def fetch(self, symbols: Sequence[str], as_of: datetime) -> list[ChainTvl]:
        def one(symbol: str) -> list[ChainTvl]:
            chain = CHAINS.get(symbol)
            if chain is None:
                return []  # a token without a chain of its own (LINK, DOGE, ...)
            response = get_with_retries(
                self._client, CHAIN_URL.format(chain=chain), limiter=self._limiter
            )
            return parse_history(symbol, chain, response.json(), as_of)

        return collect_per_symbol(symbols, one)
```

In `registry.py`:
- add `from advisor.collectors.defillama_tvl import DEFILLAMA_PER_MINUTE, DefiLlamaTvl`;
- add this line after the `BlockchainStats(…)` line:

  ```python
          DefiLlamaTvl(client, RateLimiter(per_minute=DEFILLAMA_PER_MINUTE, burst=2)),
  ```

- [ ] **Step 4: Run the tests and lint**

Run the focused tests, then the full suite and `ruff check .`.
Expected: everything passes, and ruff is clean.

- [ ] **Step 5: Commit**

```bash
git add pipeline/src/advisor/collectors/defillama_tvl.py pipeline/src/advisor/collectors/registry.py \
  pipeline/tests/unit/test_defillama_tvl.py pipeline/tests/unit/test_registry.py
git commit -m "feat: add chain TVL from DefiLlama"
```

End the message with your `Co-Authored-By:` trailer.

---

### Task 6: CoinGecko CAD quotes (source 4, core for crypto)

**Files:**
- Create: `pipeline/src/advisor/collectors/coins.py`, `pipeline/src/advisor/collectors/coingecko.py`, `pipeline/tests/unit/test_coingecko.py`
- Modify: `registry.py`, `test_registry.py`
- Fixtures (already committed): `pipeline/tests/fixtures/coingecko/coingecko_markets_cad_symbols_top.json`.
  - This is the live answer to `/coins/markets?vs_currency=cad&symbols=btc,eth,sol,matic,pol,link,doge,notacoin`: one row per known ticker.
  - "matic" is the dead `matic-network` listing, last updated in February 2026.

**Interfaces:**
- Consumes: the base helpers.
- Produces:
  - `advisor.collectors.coins.listed_as(symbol) -> str` (`RENAMED = {"MATIC": "POL"}`), used again in Task 7;
  - `CryptoQuote(symbol, coin_id, price_cad, market_cap_cad, volume_24h_cad, change_24h_pct, market_cap_rank, updated_at)`;
  - `CoinGecko(client, limiter=None, *, sleep=time.sleep)` named `coingecko`: core, best-effort, PER_RUN, SYMBOLS, asset type crypto, freshness 2 days, canary `("BTC",)`;
  - `COINGECKO_PER_MINUTE = 5`, `ATTEMPTS = 2`, `MAX_QUOTE_AGE` and `parse_quotes(symbols, rows, as_of)`.

  Task 8 imports `CryptoQuote`.

- [ ] **Step 1: Write the failing tests**

Create `pipeline/tests/unit/test_coingecko.py`:

```python
import json
from datetime import UTC, datetime

import httpx
import pytest

from advisor.collectors.base import PartialFetch
from advisor.collectors.coingecko import CoinGecko, parse_quotes

AS_OF = datetime(2026, 10, 15, 19, 25, tzinfo=UTC)


def rows(fixtures_dir) -> list[dict]:
    path = fixtures_dir / "coingecko" / "coingecko_markets_cad_symbols_top.json"
    return json.loads(path.read_text(encoding="utf-8"))


def serving(answer, seen: list | None = None, sleeps: list | None = None) -> CoinGecko:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request.url)
        return answer(request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    return CoinGecko(client, sleep=(sleeps.append if sleeps is not None else lambda s: None))


def test_each_ticker_is_priced_by_its_top_ranked_coin(fixtures_dir):
    quotes = parse_quotes(["BTC", "ETH", "SOL", "DOGE", "LINK", "POL"], rows(fixtures_dir), AS_OF)
    assert [(q.symbol, q.coin_id) for q in quotes] == [
        ("BTC", "bitcoin"), ("ETH", "ethereum"), ("SOL", "solana"),
        ("DOGE", "dogecoin"), ("LINK", "chainlink"), ("POL", "polygon-ecosystem-token"),
    ]
    btc = quotes[0]
    assert (btc.price_cad, btc.market_cap_rank, btc.change_24h_pct) == (117087, 1, 0.56002)
    assert btc.updated_at == datetime(2026, 10, 15, 19, 22, 52, tzinfo=UTC)


def test_matic_is_priced_as_pol(fixtures_dir):
    [quote] = parse_quotes(["MATIC"], rows(fixtures_dir), AS_OF)
    assert (quote.symbol, quote.coin_id, quote.price_cad) == ("MATIC", "polygon-ecosystem-token", 0.135977)


def test_a_bridged_token_sharing_the_ticker_loses_to_the_ranked_coin(fixtures_dir):
    bitcoin = next(row for row in rows(fixtures_dir) if row["id"] == "bitcoin")
    bridged = {**bitcoin, "id": "mezo-wrapped-btc", "market_cap_rank": None, "current_price": 116000}
    [quote] = parse_quotes(["BTC"], [bridged, bitcoin], AS_OF)
    assert quote.coin_id == "bitcoin"


def test_a_quote_not_updated_for_a_day_counts_as_missing(fixtures_dir):
    bitcoin = next(row for row in rows(fixtures_dir) if row["id"] == "bitcoin")
    assert parse_quotes(["BTC"], [{**bitcoin, "last_updated": "2026-10-14T19:00:00.000Z"}], AS_OF) == []


def test_fetch_asks_once_in_cad_for_every_ticker(fixtures_dir):
    seen: list = []
    quotes = serving(lambda r: httpx.Response(200, json=rows(fixtures_dir)), seen).fetch(
        ["ETH", "MATIC", "BTC"], AS_OF
    )
    [url] = seen
    assert (url.path, url.params["vs_currency"], url.params["symbols"]) == (
        "/api/v3/coins/markets", "cad", "btc,eth,pol"
    )
    assert [q.symbol for q in quotes] == ["ETH", "MATIC", "BTC"]


def test_a_coin_coingecko_does_not_price_is_a_partial_result(fixtures_dir):
    with pytest.raises(PartialFetch, match="no current CAD quote for NOTACOIN") as caught:
        serving(lambda r: httpx.Response(200, json=rows(fixtures_dir))).fetch(["BTC", "NOTACOIN"], AS_OF)
    assert [q.symbol for q in caught.value.records] == ["BTC"]


def test_a_rate_limited_call_is_retried_once_after_the_wait_coingecko_asks_for():
    seen: list = []
    sleeps: list = []
    limited = httpx.Response(429, headers={"Retry-After": "60"}, json={"status": {"error_code": 429}})
    with pytest.raises(httpx.HTTPStatusError, match="HTTP 429"):
        serving(lambda r: limited, seen, sleeps).fetch(["BTC"], AS_OF)
    assert (len(seen), sleeps) == (2, [60.0])


def test_matic_and_pol_held_together_are_both_priced_from_one_ticker(fixtures_dir):
    seen: list = []
    quotes = serving(lambda r: httpx.Response(200, json=rows(fixtures_dir)), seen).fetch(
        ["MATIC", "POL"], AS_OF
    )
    assert seen[0].params["symbols"] == "pol"
    assert [(q.symbol, q.coin_id) for q in quotes] == [
        ("MATIC", "polygon-ecosystem-token"), ("POL", "polygon-ecosystem-token")
    ]
```

Add this row at the end of `EXPECTED`:

```python
    "coingecko": (True, Scope.SYMBOLS, True, NONE),
```

- [ ] **Step 2: Run them to verify they fail**

Run: `pipeline/scripts/in-docker.sh uv run pytest tests/unit/test_coingecko.py tests/unit/test_registry.py -q`
Expected: `ModuleNotFoundError: No module named 'advisor.collectors.coingecko'`, and the registry lacks the row.

- [ ] **Step 3: Implement**

Create `pipeline/src/advisor/collectors/coins.py`:

```python
"""Coin tickers as exchanges list them today, shared by the crypto price collectors."""

RENAMED = {"MATIC": "POL"}  # Polygon's MATIC became POL in 2024; exchanges price only POL


def listed_as(symbol: str) -> str:
    """The ticker a coin trades under now ("MATIC" -> "POL"); others are unchanged."""
    return RENAMED.get(symbol, symbol)
```

Create `pipeline/src/advisor/collectors/coingecko.py`:

```python
"""Crypto quotes in CAD from CoinGecko's keyless public API (spec source 4; core for crypto).

One request per run prices every held and watched coin: `/coins/markets` with `symbols=` returns
the top-ranked coin for each ticker. Many tokens share a ticker (12 coins call themselves "btc"),
and the top-ranked one is the real one. The keyless limit is small, unpublished and shared per
IP, and failed calls count toward it too, so the request is tried at most twice, the retry
honouring Retry-After. A quote not updated for a day is a dead listing and counts as missing.
"""

import time
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from advisor.collectors.base import (
    Cadence,
    Category,
    PartialFetch,
    RateLimiter,
    Scope,
    get_with_retries,
)
from advisor.collectors.coins import listed_as
from advisor.models import AssetType, Market

MARKETS_URL = "https://api.coingecko.com/api/v3/coins/markets"
COINGECKO_PER_MINUTE = 5
ATTEMPTS = 2
MAX_QUOTE_AGE = timedelta(days=1)


class CryptoQuote(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    coin_id: str
    price_cad: float = Field(gt=0)
    market_cap_cad: float | None = None
    volume_24h_cad: float | None = None
    change_24h_pct: float | None = None
    market_cap_rank: int | None = None
    updated_at: datetime


def _rank(row: dict[str, Any]) -> tuple[bool, int, float]:
    """Sort key: ranked coins first, best rank first, then the biggest market cap."""
    rank = row.get("market_cap_rank")
    return rank is None, rank or 0, -(row.get("market_cap") or 0.0)


def parse_quotes(
    symbols: Sequence[str], rows: Sequence[dict[str, Any]], as_of: datetime
) -> list[CryptoQuote]:
    """A current quote for each requested symbol CoinGecko prices, in the requested order."""
    best: dict[str, dict[str, Any]] = {}
    for row in rows:
        ticker = str(row.get("symbol") or "").upper()
        if ticker not in best or _rank(row) < _rank(best[ticker]):
            best[ticker] = row
    quotes: list[CryptoQuote] = []
    for symbol in symbols:
        row = best.get(listed_as(symbol))
        if row is None or not row.get("current_price") or not row.get("last_updated"):
            continue
        updated = datetime.fromisoformat(row["last_updated"].replace("Z", "+00:00"))
        if as_of - updated > MAX_QUOTE_AGE:
            continue  # a dead listing keeps its last price forever
        quotes.append(CryptoQuote(
            symbol=symbol,
            coin_id=row["id"],
            price_cad=row["current_price"],
            market_cap_cad=row.get("market_cap"),
            volume_24h_cad=row.get("total_volume"),
            change_24h_pct=row.get("price_change_percentage_24h"),
            market_cap_rank=row.get("market_cap_rank"),
            updated_at=updated,
        ))
    return quotes


class CoinGecko:
    name = "coingecko"
    category = Category.PRICES
    core = True  # spec §4.2: core for crypto; it only runs when crypto is held or watched
    best_effort = True
    cadence = Cadence.PER_RUN
    asset_types = frozenset({AssetType.CRYPTO})
    markets: frozenset[Market] = frozenset()
    record_type = CryptoQuote
    freshness = timedelta(days=2)
    scope = Scope.SYMBOLS
    canary = ("BTC",)
    canary_requires_records = True
    max_symbols = None

    def __init__(
        self,
        client: httpx.Client,
        limiter: RateLimiter | None = None,
        *,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = client
        self._limiter = limiter
        self._sleep = sleep

    def fetch(self, symbols: Sequence[str], as_of: datetime) -> list[CryptoQuote]:
        wanted = list(dict.fromkeys(symbols))
        tickers = sorted({listed_as(symbol).lower() for symbol in wanted})
        response = get_with_retries(
            self._client,
            MARKETS_URL,
            params={"vs_currency": "cad", "symbols": ",".join(tickers)},
            limiter=self._limiter,
            attempts=ATTEMPTS,
            sleep=self._sleep,
        )
        quotes = parse_quotes(wanted, response.json(), as_of)
        priced = {quote.symbol for quote in quotes}
        missing = [symbol for symbol in wanted if symbol not in priced]
        if missing:
            raise PartialFetch(quotes, f"CoinGecko has no current CAD quote for {', '.join(missing)}")
        return quotes
```

In `registry.py`:
- add `from advisor.collectors.coingecko import COINGECKO_PER_MINUTE, CoinGecko`;
- add this line after the `DefiLlamaTvl(…)` line:

  ```python
          CoinGecko(client, RateLimiter(per_minute=COINGECKO_PER_MINUTE, burst=1)),
  ```

- [ ] **Step 4: Run the tests and lint**

Run the focused tests, then the full suite and `ruff check .`.
Expected: everything passes, and ruff is clean.

- [ ] **Step 5: Commit**

```bash
git add pipeline/src/advisor/collectors/coins.py pipeline/src/advisor/collectors/coingecko.py \
  pipeline/src/advisor/collectors/registry.py pipeline/tests/unit/test_coingecko.py \
  pipeline/tests/unit/test_registry.py
git commit -m "feat: add CoinGecko CAD quotes for held and watched crypto"
```

End the message with your `Co-Authored-By:` trailer.

---

### Task 7: Coinbase and Kraken daily candles (sources 5 and 6)

**Files:**
- Create: `pipeline/src/advisor/collectors/coinbase_candles.py`, `pipeline/src/advisor/collectors/kraken_ohlc.py`, `pipeline/tests/unit/test_coinbase_candles.py`, `pipeline/tests/unit/test_kraken_ohlc.py`
- Modify: `registry.py`, `test_registry.py`
- Fixtures (already committed):
  - `pipeline/tests/fixtures/coinbase/coinbase_candles_BTC-USD_daily.json`: the newest 120 rows, newest first, the first row being 2026-10-15's moving candle.
  - `pipeline/tests/fixtures/kraken/kraken_ohlc_XBTUSD_daily_trimmed.json`: the last 120 rows, oldest first, with `last` = 2026-10-14.

**Interfaces:**
- Consumes: `listed_as` (Task 6), `DailyBar` from `advisor.models`, and the base helpers.
- Produces:
  - `CoinbaseCandles(client, limiter=None)` named `coinbase_candles` and `KrakenOhlc(client, limiter=None)` named `kraken_ohlc`. Both are DAILY, SYMBOLS, asset type crypto, freshness 3 days, canary `("BTC",)`, and return `DailyBar` with `source` `coinbase` or `kraken`.
  - `COINBASE_PER_MINUTE = 300`, `HISTORY_DAYS = 290`, `KRAKEN_PER_MINUTE = 40`, `CHECK_DAYS = 35`, `kraken_pair(symbol)`, `parse_candles(symbol, rows, as_of)` and `parse_ohlc(symbol, payload, as_of)`.

- [ ] **Step 1: Write the failing tests**

Create `pipeline/tests/unit/test_coinbase_candles.py`:

```python
import json
from datetime import UTC, date, datetime

import httpx
import pytest

from advisor.collectors.base import PartialFetch
from advisor.collectors.coinbase_candles import CoinbaseCandles, parse_candles

AS_OF = datetime(2026, 10, 15, 19, 25, tzinfo=UTC)


def candles(fixtures_dir) -> list[list[float]]:
    path = fixtures_dir / "coinbase" / "coinbase_candles_BTC-USD_daily.json"
    return json.loads(path.read_text(encoding="utf-8"))  # newest first, today's candle included


def serving(answer, seen: list) -> CoinbaseCandles:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url)
        return answer(request)

    return CoinbaseCandles(httpx.Client(transport=httpx.MockTransport(handler)))


def test_finished_days_come_oldest_first(fixtures_dir):
    bars = parse_candles("BTC", candles(fixtures_dir), AS_OF)
    assert (len(bars), bars[0].day) == (119, date(2026, 6, 18))  # 120 rows less today's
    last = bars[-1]
    assert (last.day, last.open, last.high, last.low, last.close, last.volume, last.source) == (
        date(2026, 10, 14), 83101.99, 84062.11, 81332.15, 81566.29, 6527.90385989, "coinbase"
    )


def test_fetch_asks_for_290_days_of_the_usd_product(fixtures_dir):
    seen: list = []
    bars = serving(lambda r: httpx.Response(200, json=candles(fixtures_dir)), seen).fetch(["BTC"], AS_OF)
    [url] = seen
    assert url.path == "/products/BTC-USD/candles"
    assert dict(url.params) == {
        "granularity": "86400", "start": "2025-12-29T00:00:00Z", "end": "2026-10-15T00:00:00Z"
    }
    assert len(bars) == 119


def test_matic_is_asked_for_as_pol(fixtures_dir):
    seen: list = []
    serving(lambda r: httpx.Response(200, json=candles(fixtures_dir)), seen).fetch(["MATIC"], AS_OF)
    assert seen[0].path == "/products/POL-USD/candles"


def test_a_coin_coinbase_does_not_list_has_no_candles():
    seen: list = []
    answer = serving(lambda r: httpx.Response(404, json={"message": "NotFound"}), seen)
    assert answer.fetch(["WSCOIN"], AS_OF) == []


def test_another_error_fails_only_that_coin(fixtures_dir):
    def answer(request: httpx.Request) -> httpx.Response:
        if "ETH-USD" in request.url.path:
            return httpx.Response(400, json={"message": "Unsupported granularity"})
        return httpx.Response(200, json=candles(fixtures_dir))

    with pytest.raises(PartialFetch, match="1 of 2 symbols failed; first: ETH: HTTPStatusError") as caught:
        serving(answer, []).fetch(["ETH", "BTC"], AS_OF)
    assert {bar.symbol for bar in caught.value.records} == {"BTC"}
```

Create `pipeline/tests/unit/test_kraken_ohlc.py`:

```python
import json
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest

from advisor.collectors.base import PartialFetch
from advisor.collectors.kraken_ohlc import KrakenOhlc, kraken_pair, parse_ohlc

AS_OF = datetime(2026, 10, 15, 19, 25, tzinfo=UTC)


def payload(fixtures_dir) -> dict:
    path = fixtures_dir / "kraken" / "kraken_ohlc_XBTUSD_daily_trimmed.json"
    return json.loads(path.read_text(encoding="utf-8"))  # oldest first; the last row is today


def serving(answer, seen: list) -> KrakenOhlc:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url)
        return answer(request)

    return KrakenOhlc(httpx.Client(transport=httpx.MockTransport(handler)))


@pytest.mark.parametrize(
    ("symbol", "pair"), [("BTC", "XBTUSD"), ("DOGE", "XDGUSD"), ("MATIC", "POLUSD"), ("SOL", "SOLUSD")]
)
def test_kraken_names_bitcoin_xbt_and_dogecoin_xdg(symbol, pair):
    assert kraken_pair(symbol) == pair


def test_finished_candles_are_read_from_strings(fixtures_dir):
    bars = parse_ohlc("BTC", payload(fixtures_dir), AS_OF)
    assert (len(bars), bars[0].day) == (119, date(2026, 6, 18))
    assert (bars[-1].day, bars[-1].close, bars[-1].volume, bars[-1].source) == (
        date(2026, 10, 14), 81576.4, 2598.87867869, "kraken"
    )


def test_candles_after_the_last_finished_one_are_still_moving(fixtures_dir):
    data = payload(fixtures_dir)
    data["result"]["last"] = 1791849600  # 2026-10-13
    assert parse_ohlc("BTC", data, AS_OF)[-1].day == date(2026, 10, 13)


def test_fetch_asks_for_the_last_35_days(fixtures_dir):
    seen: list = []
    bars = serving(lambda r: httpx.Response(200, json=payload(fixtures_dir)), seen).fetch(["BTC"], AS_OF)
    [url] = seen
    since = int((AS_OF - timedelta(days=35)).timestamp())
    assert dict(url.params) == {"pair": "XBTUSD", "interval": "1440", "since": str(since)}
    assert len(bars) == 119


def test_a_coin_kraken_does_not_list_has_no_candles():
    unknown = httpx.Response(200, json={"error": ["EQuery:Unknown asset pair"]})
    assert serving(lambda r: unknown, []).fetch(["WSCOIN"], AS_OF) == []


def test_another_kraken_error_fails_the_coin():
    invalid = httpx.Response(200, json={"error": ["EGeneral:Invalid arguments"]})
    with pytest.raises(PartialFetch, match="BTC: ValueError: Kraken: EGeneral:Invalid arguments"):
        serving(lambda r: invalid, []).fetch(["BTC"], AS_OF)
```

Add these rows at the end of `EXPECTED`:

```python
    "coinbase_candles": (False, Scope.SYMBOLS, True, NONE),
    "kraken_ohlc": (False, Scope.SYMBOLS, True, NONE),
```

- [ ] **Step 2: Run them to verify they fail**

Run: `pipeline/scripts/in-docker.sh uv run pytest tests/unit/test_coinbase_candles.py tests/unit/test_kraken_ohlc.py tests/unit/test_registry.py -q`
Expected: `ModuleNotFoundError` for both modules, and the registry lacks both rows.

- [ ] **Step 3: Implement**

Create `pipeline/src/advisor/collectors/coinbase_candles.py`:

```python
"""Daily crypto candles in USD from Coinbase Exchange's public API (spec source 5).

Rows are [time, low, high, open, close, volume], newest first, one per UTC day starting 00:00
UTC. Today's candle is still moving and is dropped. One request may span at most 300 days.
Coinbase lists USD products only (its one CAD product is USDC-CAD); CAD values come from
CoinGecko. A coin Coinbase doesn't list (404) simply has no candles.
"""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import httpx

from advisor.collectors.base import (
    Cadence,
    Category,
    RateLimiter,
    Scope,
    collect_per_symbol,
    get_with_retries,
)
from advisor.collectors.coins import listed_as
from advisor.models import AssetType, DailyBar, Market

CANDLES_URL = "https://api.exchange.coinbase.com/products/{product}/candles"
COINBASE_PER_MINUTE = 300  # the documented public limit is 10 per second
HISTORY_DAYS = 290  # one request; Coinbase refuses more than 300 candles
ONE_DAY = 86400


def parse_candles(symbol: str, rows: Sequence[Sequence[float]], as_of: datetime) -> list[DailyBar]:
    """Finished days before `as_of`'s UTC day, oldest first."""
    today = as_of.astimezone(UTC).date()
    bars: list[DailyBar] = []
    for start, low, high, open_, close, volume in rows:
        day = datetime.fromtimestamp(start, UTC).date()
        if day < today:
            bars.append(DailyBar(
                symbol=symbol, day=day, open=open_, high=high, low=low, close=close,
                volume=volume, source="coinbase",
            ))
    return sorted(bars, key=lambda bar: bar.day)


class CoinbaseCandles:
    name = "coinbase_candles"
    category = Category.PRICES
    core = False
    best_effort = False
    cadence = Cadence.DAILY
    asset_types = frozenset({AssetType.CRYPTO})
    markets: frozenset[Market] = frozenset()
    record_type = DailyBar
    freshness = timedelta(days=3)
    scope = Scope.SYMBOLS
    canary = ("BTC",)
    canary_requires_records = True
    max_symbols = None

    def __init__(self, client: httpx.Client, limiter: RateLimiter | None = None) -> None:
        self._client = client
        self._limiter = limiter

    def fetch(self, symbols: Sequence[str], as_of: datetime) -> list[DailyBar]:
        today = as_of.astimezone(UTC).date()
        window = {
            "granularity": ONE_DAY,
            "start": f"{today - timedelta(days=HISTORY_DAYS)}T00:00:00Z",
            "end": f"{today}T00:00:00Z",
        }

        def one(symbol: str) -> list[DailyBar]:
            product = f"{listed_as(symbol)}-USD"
            try:
                response = get_with_retries(
                    self._client,
                    CANDLES_URL.format(product=product),
                    params=window,
                    limiter=self._limiter,
                )
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    return []  # not listed on Coinbase
                raise
            return parse_candles(symbol, response.json(), as_of)

        return collect_per_symbol(symbols, one)
```

Create `pipeline/src/advisor/collectors/kraken_ohlc.py`:

```python
"""Daily crypto candles in USD from Kraken's public API, to cross-check Coinbase (spec source 6).

Kraken names Bitcoin XBT and Dogecoin XDG. Rows are [time, open, high, low, close, vwap, volume,
count] with prices as strings, oldest first; `last` is the start of the last finished candle,
and later rows are still moving. Errors come back as HTTP 200 with an `error` list; an unknown
pair means Kraken doesn't list the coin.
"""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from advisor.collectors.base import (
    Cadence,
    Category,
    RateLimiter,
    Scope,
    collect_per_symbol,
    get_with_retries,
)
from advisor.collectors.coins import listed_as
from advisor.models import AssetType, DailyBar, Market

OHLC_URL = "https://api.kraken.com/0/public/OHLC"
KRAKEN_PER_MINUTE = 40  # Kraken asks for at most one public call per second
KRAKEN_NAMES = {"BTC": "XBT", "DOGE": "XDG"}
UNKNOWN_PAIR = "EQuery:Unknown asset pair"
CHECK_DAYS = 35


def kraken_pair(symbol: str) -> str:
    base = listed_as(symbol)
    return f"{KRAKEN_NAMES.get(base, base)}USD"


def parse_ohlc(symbol: str, payload: Mapping[str, Any], as_of: datetime) -> list[DailyBar]:
    """Finished days before `as_of`'s UTC day, oldest first."""
    errors = payload.get("error") or []
    if errors:
        raise ValueError(f"Kraken: {', '.join(errors)}")
    result = payload["result"]
    last = int(result["last"])
    rows = next(value for key, value in result.items() if key != "last")
    today = as_of.astimezone(UTC).date()
    bars: list[DailyBar] = []
    for start, open_, high, low, close, _vwap, volume, _count in rows:
        day = datetime.fromtimestamp(start, UTC).date()
        if start <= last and day < today:
            bars.append(DailyBar(
                symbol=symbol, day=day, open=float(open_), high=float(high), low=float(low),
                close=float(close), volume=float(volume), source="kraken",
            ))
    return bars


class KrakenOhlc:
    name = "kraken_ohlc"
    category = Category.PRICES
    core = False
    best_effort = False
    cadence = Cadence.DAILY
    asset_types = frozenset({AssetType.CRYPTO})
    markets: frozenset[Market] = frozenset()
    record_type = DailyBar
    freshness = timedelta(days=3)
    scope = Scope.SYMBOLS
    canary = ("BTC",)
    canary_requires_records = True
    max_symbols = None

    def __init__(self, client: httpx.Client, limiter: RateLimiter | None = None) -> None:
        self._client = client
        self._limiter = limiter

    def fetch(self, symbols: Sequence[str], as_of: datetime) -> list[DailyBar]:
        since = int((as_of - timedelta(days=CHECK_DAYS)).timestamp())

        def one(symbol: str) -> list[DailyBar]:
            response = get_with_retries(
                self._client,
                OHLC_URL,
                params={"pair": kraken_pair(symbol), "interval": 1440, "since": since},
                limiter=self._limiter,
            )
            payload = response.json()
            if UNKNOWN_PAIR in (payload.get("error") or []):
                return []  # not listed on Kraken
            return parse_ohlc(symbol, payload, as_of)

        return collect_per_symbol(symbols, one)
```

In `registry.py`:
- add `from advisor.collectors.coinbase_candles import COINBASE_PER_MINUTE, CoinbaseCandles` and `from advisor.collectors.kraken_ohlc import KRAKEN_PER_MINUTE, KrakenOhlc`;
- add these lines after the `CoinGecko(…)` line:

  ```python
          CoinbaseCandles(client, RateLimiter(per_minute=COINBASE_PER_MINUTE, burst=3)),
          KrakenOhlc(client, RateLimiter(per_minute=KRAKEN_PER_MINUTE, burst=1)),
  ```

After this task, `registry.py` must equal:

```python
"""Every collector the pipeline runs, keyed by name, with one rate limiter per provider."""

import httpx

from advisor.collectors.base import Collector, RateLimiter
from advisor.collectors.blockchain_stats import BLOCKCHAIN_PER_MINUTE, BlockchainStats
from advisor.collectors.boc_valet import BankOfCanadaValet
from advisor.collectors.cnn_fear_greed import CnnFearGreed
from advisor.collectors.coinbase_candles import COINBASE_PER_MINUTE, CoinbaseCandles
from advisor.collectors.coingecko import COINGECKO_PER_MINUTE, CoinGecko
from advisor.collectors.crypto_fear_greed import CryptoFearGreed
from advisor.collectors.defillama_tvl import DEFILLAMA_PER_MINUTE, DefiLlamaTvl
from advisor.collectors.finra_short_interest import FinraShortInterest
from advisor.collectors.finra_short_volume import FinraShortVolume
from advisor.collectors.fomc import Fomc
from advisor.collectors.fred import FRED_PER_MINUTE, Fred
from advisor.collectors.kraken_ohlc import KRAKEN_PER_MINUTE, KrakenOhlc
from advisor.collectors.nasdaq_symbols import NasdaqSymbols
from advisor.collectors.sec import SEC_PER_MINUTE, SecEdgar
from advisor.collectors.sec_events import SecEvents
from advisor.collectors.sec_holders import SecHolders
from advisor.collectors.sec_insiders import SecInsiders
from advisor.collectors.sec_xbrl import SecXbrl
from advisor.collectors.tmx_symbols import TmxSymbols
from advisor.collectors.yahoo import YAHOO_PER_MINUTE
from advisor.collectors.yfinance_analyst import YFinanceAnalyst
from advisor.collectors.yfinance_bars import YFinanceBars
from advisor.collectors.yfinance_earnings import YFinanceEarnings
from advisor.config import Settings

FINRA_PER_MINUTE = 60


def build_registry(settings: Settings, client: httpx.Client) -> dict[str, Collector]:
    finra = RateLimiter(per_minute=FINRA_PER_MINUTE, burst=2)  # shared by FINRA's collectors
    yahoo = RateLimiter(per_minute=YAHOO_PER_MINUTE, burst=2)  # shared by Yahoo's per-symbol collectors
    sec = SecEdgar(  # shared by every SEC collector
        client,
        settings.sec_user_agent,
        RateLimiter(per_minute=SEC_PER_MINUTE, burst=5),
        documents=settings.cache_dir / "sec-documents",
    )
    collectors: list[Collector] = [
        NasdaqSymbols(client),
        TmxSymbols(client),
        YFinanceBars(),
        FinraShortVolume(client, finra),
        FinraShortInterest(client, finra),
        YFinanceAnalyst(limiter=yahoo),
        YFinanceEarnings(limiter=yahoo),
        BankOfCanadaValet(client),
        SecXbrl(sec),
        SecEvents(sec),
        SecInsiders(sec),
        SecHolders(sec),
        Fred(client, RateLimiter(per_minute=FRED_PER_MINUTE, burst=3)),
        Fomc(client),
        CnnFearGreed(client),
        CryptoFearGreed(client),
        BlockchainStats(client, RateLimiter(per_minute=BLOCKCHAIN_PER_MINUTE, burst=1)),
        DefiLlamaTvl(client, RateLimiter(per_minute=DEFILLAMA_PER_MINUTE, burst=2)),
        CoinGecko(client, RateLimiter(per_minute=COINGECKO_PER_MINUTE, burst=1)),
        CoinbaseCandles(client, RateLimiter(per_minute=COINBASE_PER_MINUTE, burst=3)),
        KrakenOhlc(client, RateLimiter(per_minute=KRAKEN_PER_MINUTE, burst=1)),
    ]
    return {collector.name: collector for collector in collectors}
```

- [ ] **Step 4: Run the tests and lint**

Run the focused tests, then the full suite and `ruff check .`.
Expected: everything passes, and ruff is clean.

- [ ] **Step 5: Commit**

```bash
git add pipeline/src/advisor/collectors/coinbase_candles.py pipeline/src/advisor/collectors/kraken_ohlc.py \
  pipeline/src/advisor/collectors/registry.py pipeline/tests/unit/test_coinbase_candles.py \
  pipeline/tests/unit/test_kraken_ohlc.py pipeline/tests/unit/test_registry.py
git commit -m "feat: add Coinbase and Kraken daily crypto candles"
```

End the message with your `Co-Authored-By:` trailer.

---

### Task 8: Crypto priced in the holdings phase; deferred list

**Files:**
- Create: `pipeline/src/advisor/crypto_prices.py`, `pipeline/tests/unit/test_crypto_prices.py`
- Modify: `pipeline/src/advisor/run.py`, `pipeline/src/advisor/enrich.py`, `pipeline/tests/integration/test_run.py`, `pipeline/tests/unit/test_enrich.py`, `docs/superpowers/deferred.md`, `docs/superpowers/specs/2026-10-09-stock-advisor-design.md` (row 15 only)

**Interfaces:**
- Consumes:
  - `CryptoQuote` (Task 6) and `DailyBar`;
  - `group_bars` from `advisor.prices`;
  - the registry names `coingecko`, `coinbase_candles` and `kraken_ohlc` (Tasks 6 and 7);
  - `fakes.FakeCollector`, `bar` and `history`.
- Produces:
  - `advisor.crypto_prices`: `QUOTES`, `BARS`, `CHECK`, `CRYPTO_STAGE`, `CROSS_CHECK_LIMIT = 0.02`, `unconfirmed(bars, checks) -> bool | None` and `crypto_feature_rows(symbols, quotes, bars, checks, as_of)`;
  - `advisor.enrich.wanted(collector, symbols, targets) -> bool`;
  - run summary keys `crypto` and `crypto_unquoted`.
- **Rule:** a held coin without a CAD quote makes `holdings_ok` false, so the run is degraded. A watched-only coin without one is only listed in `crypto_unquoted`.
- **Note:** `run.py` runs a crypto stage source only when it is registered (`name in deps.collectors`). The integration fakes register only the price sources they need; the registry test pins the real names.

- [ ] **Step 1: Write the failing tests**

Create `pipeline/tests/unit/test_crypto_prices.py`:

```python
from datetime import UTC, date, datetime

from advisor.collectors.coingecko import CryptoQuote
from advisor.crypto_prices import crypto_feature_rows, unconfirmed
from advisor.models import AssetRef, AssetType
from fakes import bar, history

NOW = datetime(2026, 10, 14, 12, 15, tzinfo=UTC)
QUOTE = CryptoQuote(
    symbol="BTC", coin_id="bitcoin", price_cad=117087.0, market_cap_cad=2.35e12,
    volume_24h_cad=5.8e10, change_24h_pct=0.56, market_cap_rank=1, updated_at=NOW,
)
DAY = date(2026, 10, 13)


def test_a_latest_close_within_two_percent_of_kraken_is_confirmed():
    assert unconfirmed([bar("BTC", DAY, 82000.0)], [bar("BTC", DAY, 81000.0)]) is False  # 1.2%


def test_a_latest_close_more_than_two_percent_from_kraken_is_unconfirmed():
    assert unconfirmed([bar("BTC", DAY, 82000.0)], [bar("BTC", DAY, 80000.0)]) is True  # 2.5%


def test_without_krakens_close_for_that_day_nothing_is_known():
    assert unconfirmed([bar("BTC", DAY, 82000.0)], [bar("BTC", date(2026, 10, 12), 1.0)]) is None
    assert unconfirmed([], [bar("BTC", DAY, 82000.0)]) is None


def test_a_coin_with_a_quote_and_candles_gets_every_feature():
    candles = history("BTC", 30, close=82000.0, source="coinbase", start=date(2026, 9, 14))
    [(ref, features)] = crypto_feature_rows(
        ["BTC"], {"BTC": QUOTE}, {"BTC": candles}, {"BTC": [bar("BTC", DAY, 82100.0)]}, NOW
    )
    assert ref == AssetRef("BTC", AssetType.CRYPTO)
    assert features == {
        "price_cad": 117087.0, "market_cap_cad": 2.35e12, "volume_24h_cad": 5.8e10,
        "change_24h_pct": 0.56, "market_cap_rank": 1,
        "last_close_usd": 82000.0, "history_days": 30, "last_day": "2026-10-13",
        "stale": False, "unconfirmed_price": False,
    }


def test_a_coin_with_only_a_quote_or_old_candles_still_gets_a_row():
    old = history("ETH", 30, close=3400.0, source="coinbase", start=date(2026, 9, 1))  # ends 09-30
    rows = dict(crypto_feature_rows(["BTC", "ETH", "XYZ"], {"BTC": QUOTE}, {"ETH": old}, {}, NOW))
    assert set(rows) == {AssetRef("BTC", AssetType.CRYPTO), AssetRef("ETH", AssetType.CRYPTO)}
    assert "last_close_usd" not in rows[AssetRef("BTC", AssetType.CRYPTO)]
    eth = rows[AssetRef("ETH", AssetType.CRYPTO)]
    assert (eth["stale"], eth["unconfirmed_price"], "price_cad" in eth) == (True, None, False)
```

Append to `pipeline/tests/unit/test_enrich.py`:

```python
def test_a_crypto_market_source_runs_only_when_crypto_is_held_or_watched(tmp_path):
    for crypto, expected in (([], []), (["BTC"], [[]])):
        fear = FakeCollector("fear", scope=Scope.MARKET, asset_types=frozenset({AssetType.CRYPTO}))
        tracker = SourceTracker({"fear": fear}, DiskCache(tmp_path), NOW, {})
        targets = EnrichTargets(priority_stocks=["OTCX"], crypto=crypto, ranked_stocks=["AAA"])
        run_enrichment(tracker, {"fear": fear}, ["fear"], targets)
        assert fear.calls == expected
```

In `pipeline/tests/integration/test_run.py`:
- change the first import to `from datetime import UTC, date, datetime, timedelta`;
- add `from advisor.collectors.coingecko import CryptoQuote` after the `DiskCache` import;
- in `test_successful_run_is_published_with_a_per_market_summary`, add the line `"crypto": 0, "crypto_unquoted": [],` after the line `"priority": 0, "priority_unpriced": [], "unconfirmed_jumps": 0, "shortlist": 5,` in the expected summary;
- append:

```python
CRYPTO = frozenset({AssetType.CRYPTO})


def crypto_sources(quoted=("BTC",), kraken_close=82100.0) -> dict[str, FakeCollector]:
    """CoinGecko, Coinbase and Kraken fakes: Coinbase's 30 finished days end 2026-10-13 at 82,000."""

    def quote(symbol: str) -> CryptoQuote:
        return CryptoQuote(
            symbol=symbol, coin_id=symbol.lower(), price_cad=117087.0, market_cap_rank=1,
            updated_at=NOW,
        )

    def candles(symbols):
        start = date(2026, 9, 14)
        return [b for s in symbols for b in history(s, 30, 82000.0, source="coinbase", start=start)]

    return {
        "coingecko": FakeCollector(
            "coingecko", asset_types=CRYPTO, record_type=CryptoQuote,
            records_for=lambda symbols: [quote(s) for s in symbols if s in quoted],
        ),
        "coinbase_candles": FakeCollector(
            "coinbase_candles", core=False, asset_types=CRYPTO, records_for=candles
        ),
        "kraken_ohlc": FakeCollector(
            "kraken_ohlc", core=False, asset_types=CRYPTO,
            records_for=lambda symbols: [
                bar(s, date(2026, 10, 13), kraken_close, source="kraken") for s in symbols
            ],
        ),
    }


def hold_crypto(db, symbol="BTC"):
    db.execute(
        "insert into lots (account, symbol, asset_type, qty, price, currency, bought_at)"
        " values ('crypto', %s, 'crypto', 0.5, 100000, 'CAD', '2026-09-01')",
        (symbol,),
    )


def test_held_crypto_is_priced_in_the_holdings_phase(db, tmp_path):
    hold_crypto(db)
    extra = crypto_sources()
    outcome = execute_run(
        make_deps(db, tmp_path, extra=extra), RunKind.PRE_OPEN, NOW, min_universe=SMALL
    )

    assert outcome.status is RunStatus.SUCCESS
    for name in extra:  # once each, for the coins, and not again in enrichment
        assert extra[name].calls == [["BTC"]]
    row = db.execute(
        "select asset_type, features from features_live where run_id = %s and symbol = 'BTC'",
        (outcome.run_id,),
    ).fetchone()
    assert row["asset_type"] == "crypto"
    assert row["features"] == {
        "price_cad": 117087.0, "market_cap_cad": None, "volume_24h_cad": None,
        "change_24h_pct": None, "market_cap_rank": 1,
        "last_close_usd": 82000.0, "history_days": 30, "last_day": "2026-10-13",
        "stale": False, "unconfirmed_price": False,
    }
    assert (outcome.summary["crypto"], outcome.summary["crypto_unquoted"]) == (1, [])


def test_a_held_coin_without_a_cad_quote_degrades_the_run(db, tmp_path):
    hold_crypto(db)
    outcome = execute_run(
        make_deps(db, tmp_path, extra=crypto_sources(quoted=())), RunKind.PRE_OPEN, NOW,
        min_universe=SMALL,
    )
    assert outcome.status is RunStatus.DEGRADED  # the holding can't be valued in CAD
    assert outcome.summary["crypto_unquoted"] == ["BTC"]


def test_a_watched_coin_without_a_quote_stays_summary_only(db, tmp_path):
    db.execute("insert into watchlist (symbol, asset_type) values ('ETH', 'crypto')")
    outcome = execute_run(
        make_deps(db, tmp_path, extra=crypto_sources(quoted=())), RunKind.PRE_OPEN, NOW,
        min_universe=SMALL,
    )
    assert outcome.status is RunStatus.SUCCESS
    assert outcome.summary["crypto_unquoted"] == ["ETH"]


def test_exchanges_that_disagree_leave_the_latest_crypto_price_unconfirmed(db, tmp_path):
    hold_crypto(db)
    outcome = execute_run(
        make_deps(db, tmp_path, extra=crypto_sources(kraken_close=90000.0)), RunKind.PRE_OPEN,
        NOW, min_universe=SMALL,
    )
    assert market_features(db, outcome.run_id)["BTC"]["unconfirmed_price"] is True


def test_a_failing_coingecko_values_holdings_from_its_last_quote(db, tmp_path):
    hold_crypto(db)
    extra = crypto_sources()
    extra["coingecko"].freshness = timedelta(days=2)  # as the real source: quotes are cached
    execute_run(make_deps(db, tmp_path, extra=extra), RunKind.PRE_OPEN, NOW, min_universe=SMALL)
    extra["coingecko"].error = httpx.HTTPStatusError(
        "HTTP 429", request=httpx.Request("GET", "https://api.coingecko.com"),
        response=httpx.Response(429),
    )
    outcome = execute_run(
        make_deps(db, tmp_path, extra=extra), RunKind.PRE_CLOSE, NOW, min_universe=SMALL
    )
    assert outcome.status is RunStatus.DEGRADED  # a core source served from cache
    assert outcome.summary["crypto_unquoted"] == []
    assert ("coingecko", "stale") in health(db, outcome.run_id)
    assert market_features(db, outcome.run_id)["BTC"]["price_cad"] == 117087.0


def test_without_crypto_no_crypto_source_is_asked(db, tmp_path):
    hold(db)
    extra = crypto_sources()
    outcome = execute_run(
        make_deps(db, tmp_path, extra=extra), RunKind.PRE_OPEN, NOW, min_universe=SMALL
    )
    assert outcome.status is RunStatus.SUCCESS
    assert [extra[name].calls for name in extra] == [[], [], []]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `pipeline/scripts/in-docker.sh uv run pytest tests/unit/test_crypto_prices.py tests/unit/test_enrich.py tests/integration/test_run.py -q`
Expected:
- `ModuleNotFoundError: No module named 'advisor.crypto_prices'`;
- the enrichment test fails (`fear` is called without crypto);
- the run tests fail, because no crypto is priced and the summary lacks `crypto`.

- [ ] **Step 3: Implement**

Create `pipeline/src/advisor/crypto_prices.py`:

```python
"""Held and watched crypto, priced in the holdings phase (spec §4.3 stage 1, §7.2).

- CoinGecko's CAD quote values a holding (spec §7.4 shows values in CAD).
- Coinbase's finished daily USD candles feed the price features.
- Kraken's candle for Coinbase's latest day cross-checks it: one exchange's bad print would
  otherwise go unnoticed. This is crypto's counterpart of the stock jump rule (spec §10), and
  an unconfirmed latest price blocks a Buy the same way (Plans 4 and 5).
"""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta

from advisor.collectors.coingecko import CryptoQuote
from advisor.models import AssetRef, AssetType, DailyBar

QUOTES = "coingecko"
BARS = "coinbase_candles"
CHECK = "kraken_ohlc"
CRYPTO_STAGE = frozenset({QUOTES, BARS, CHECK})
CROSS_CHECK_LIMIT = 0.02  # closes further apart than 2% are unconfirmed


def unconfirmed(bars: Sequence[DailyBar], checks: Sequence[DailyBar]) -> bool | None:
    """Whether Kraken's close for Coinbase's latest day is more than 2% away; None if it has none."""
    if not bars:
        return None
    latest = bars[-1]
    theirs = next((check.close for check in checks if check.day == latest.day), None)
    if theirs is None:
        return None
    return abs(latest.close / theirs - 1) > CROSS_CHECK_LIMIT


def crypto_feature_rows(
    symbols: Sequence[str],
    quotes: Mapping[str, CryptoQuote],
    bars: Mapping[str, Sequence[DailyBar]],
    checks: Mapping[str, Sequence[DailyBar]],
    as_of: datetime,
) -> list[tuple[AssetRef, dict]]:
    """One features row per coin with a quote or candles; a coin with neither gets none."""
    yesterday = as_of.astimezone(UTC).date() - timedelta(days=1)
    rows: list[tuple[AssetRef, dict]] = []
    for symbol in symbols:
        quote, history = quotes.get(symbol), list(bars.get(symbol) or [])
        if quote is None and not history:
            continue
        features: dict = {}
        if quote is not None:
            features.update(
                price_cad=quote.price_cad,
                market_cap_cad=quote.market_cap_cad,
                volume_24h_cad=quote.volume_24h_cad,
                change_24h_pct=quote.change_24h_pct,
                market_cap_rank=quote.market_cap_rank,
            )
        if history:
            last = history[-1]
            features.update(
                last_close_usd=last.close,
                history_days=len(history),
                last_day=last.day.isoformat(),
                stale=last.day < yesterday,  # crypto trades daily: yesterday must be finished
                unconfirmed_price=unconfirmed(history, checks.get(symbol) or []),
            )
        rows.append((AssetRef(symbol, AssetType.CRYPTO), features))
    return rows
```

In `pipeline/src/advisor/enrich.py`, add `wanted` before `run_enrichment`, and use it in `run_enrichment`'s loop:

```python
def wanted(collector: Collector, symbols: Sequence[str], targets: EnrichTargets) -> bool:
    """SYMBOLS collectors need targets; a crypto-only market-wide source needs some crypto."""
    if collector.scope is Scope.SYMBOLS:
        return bool(symbols)
    return AssetType.STOCK in collector.asset_types or bool(targets.crypto)
```

`run_enrichment`'s docstring and loop become:

```python
    """Run each named collector once, concurrently, skipping those with nothing to do."""
    jobs: dict[str, list[str]] = {}
    for name in names:
        symbols = symbols_for(collectors[name], targets)
        if wanted(collectors[name], symbols, targets):
            jobs[name] = symbols
```

In `pipeline/src/advisor/run.py`, make four changes.

1. **Imports.** Add `from advisor.collectors.coingecko import CryptoQuote` after the `DiskCache` import, and `from advisor.crypto_prices import BARS, CHECK, CRYPTO_STAGE, QUOTES, crypto_feature_rows` after the `Settings` import. Change the prices import to `from advisor.prices import PriceFetch, fetch_daily_bars, group_bars`.
2. **Crypto pricing.** Right after phase 1's `repo.write_features_live(conn, run_id, live_feature_rows(priority_rows, flagged, floors), now_utc)` call, and before the `# Phase 2:` comment, insert:

```python
        # Held and watched crypto too; CoinGecko's CAD quote is what values a crypto holding.
        quotes: dict[str, CryptoQuote] = {}
        if crypto:

            def crypto_records(name: str) -> list:
                return list(tracker.run(name, crypto).records) if name in deps.collectors else []

            quotes = {quote.symbol: quote for quote in crypto_records(QUOTES)}
            candles, checks = group_bars(crypto_records(BARS)), group_bars(crypto_records(CHECK))
            repo.write_features_live(
                conn, run_id, crypto_feature_rows(crypto, quotes, candles, checks, now_utc), now_utc
            )
```

3. **Enrichment.** In the `run_enrichment(…)` call, the names become `[name for name in deps.collectors if name not in PRICE_STAGE | CRYPTO_STAGE]`.
4. **Summary and holdings check.** Add two keys at the end of `summary`, after `"shortlist": …,`:

```python
            "crypto": len(crypto),
            "crypto_unquoted": sorted(set(crypto) - quotes.keys()),
```

and the holdings check becomes:

```python
        held_stocks = {ref.symbol for ref in held if ref.asset_type is AssetType.STOCK}
        held_crypto = {ref.symbol for ref in held if ref.asset_type is AssetType.CRYPTO}
        status = decide_status(
            tracker.merged(),
            deps.collectors,
            universe_ok=universe_ok,
            prices_ok=prices_ok,
            holdings_ok=held_stocks <= bars.keys() and held_crypto <= quotes.keys(),
        )
```

- [ ] **Step 4: Update the deferred list and the spec's source table**

In `docs/superpowers/specs/2026-10-09-stock-advisor-design.md`, row 15 of the §4.2 table: replace `(Plan 2e)` with `(Plan 2h)`. Nothing else in the spec changes.

In `docs/superpowers/deferred.md`, make five edits.

1. In the intro, replace `Plan 2b, Plan 2c and Plan 2d reviews` with `Plan 2b, Plan 2c, Plan 2d and Plan 2e reviews`.
2. Replace the whole `## Plan 2e` section (its heading and two bullets) with:

```markdown
## Plan 2f: news and social

- **Collectors covering both stocks and crypto** (Reddit, ApeWisdom; LINK, SOL and COMP exist as both): keep the asset types apart in symbol lists and cache keys before the first such collector. Plan 2e's crypto sources are crypto-only.

## Plan 2h: options, catalysts and Canadian short positions

- **Split out of Plan 2e**, which kept macro, crypto and on-chain. Sources: Yahoo option chains (18) and CBOE put/call ratios (19); openFDA (48), ClinicalTrials.gov (49), USAspending.gov (50) and House Clerk periodic transaction reports (51); the Canadian short-position report (15), kept only if a keyless file is confirmed.
- **Catalysts name companies, not tickers:** drug sponsors, trial sponsors and contract recipients need a company-name → symbol map for both markets. Plan 2f's news mapping needs the same dictionary, so build it once.
- **House Clerk reports are PDFs.** Check that electronically filed reports read as text before committing to source 51.
```

3. Add these bullets at the end of `## Plan 3: model and features`, after the "Amendments" bullet:

```markdown
- **FRED dates are observation dates.** A month's CPI and unemployment rate are published about two weeks into the next month and are later revised. Backtests must apply release lags; point-in-time vintages (ALFRED) need a key.
- **Crypto history:** Coinbase gives 290 finished daily USD candles per coin in one request. 12-month momentum needs 365, so fetch a second window when the crypto model needs it. Altcoins are measured against BTC (spec §5.4), so price BTC whenever any crypto is held or watched.
- **Macro event:** "days to the next FOMC decision" comes from the `fomc` source's `meeting` records. The decision is at 14:00 ET on the meeting's last day.
- **Protocol TVL** (spec source 52 names chain and protocol TVL): Plan 2e collects chain TVL only. DeFi tokens such as UNI or AAVE belong to a protocol rather than a chain, and DefiLlama's `/protocols` list has a `symbol` per protocol. Add it if the crypto model's features need it.
```

4. Add these bullets at the top of `## Plans 4 and 5: recommendations and dashboard`, before the "holding-action outcomes" bullet:

```markdown
- **Crypto Buy and Add:** a coin whose `unconfirmed_price` is true (Coinbase and Kraken more than 2% apart on the latest day) is blocked like a stock's `unconfirmed_jump`.
- **Source credits:** CoinGecko requires "Data provided by CoinGecko" wherever its data is shown, and FRED asks to be cited. alternative.me, DefiLlama and blockchain.com welcome a credit. Put a sources footer on the dashboard.
- **`runs.summary`** gained `crypto` (held and watched coins) and `crypto_unquoted` in Plan 2e.
```

5. Add these bullets at the end of `## Operational and minor`:

```markdown
- **CoinGecko's keyless limit** is unpublished and shared per IP, and GitHub's runners share IPs. The source makes one call per run, with one retry after Retry-After. If 429s become common, holdings are valued from the last quote (2-day freshness) and the run is degraded. A free Demo key would need an account, which R7 rules out.
- **Terms to watch:**
  - FRED's FAQ says "Don't do any data mining, scraping or extraction of FRED data", while its terms forbid only disruptive scraping. The pipeline makes 9 requests a day, cached for the day, for personal use.
  - CNN's terms allow downloads "for your personal use only". Its endpoint is unofficial and gated by a Referer check.
  - CoinGecko's terms forbid storing its data beyond a cache refreshed daily; only each run's features keep a quote.
- **blockchain.com** documents a newer gateway API, so the legacy `api.blockchain.info/charts` endpoints used here may be retired.
- **FOMC calendar** is read from the page's `fomc-meeting__month` and `fomc-meeting__date` classes. A redesign makes the source PARTIAL; releases still arrive.
```

- [ ] **Step 5: Run everything**

Run: `pipeline/scripts/in-docker.sh uv run pytest -q`, then `pipeline/scripts/in-docker.sh uv run ruff check .`
Expected: 458 passed (386 before this plan), and `All checks passed!`.

- [ ] **Step 6: Commit**

```bash
git add pipeline/src/advisor/crypto_prices.py pipeline/src/advisor/run.py pipeline/src/advisor/enrich.py \
  pipeline/tests/unit/test_crypto_prices.py pipeline/tests/unit/test_enrich.py \
  pipeline/tests/integration/test_run.py docs/superpowers/deferred.md \
  docs/superpowers/specs/2026-10-09-stock-advisor-design.md
git commit -m "feat: price held and watched crypto in the holdings phase; record Plan 2h"
```

End the message with your `Co-Authored-By:` trailer.

---

## After this plan

- **Live check.** Use a scratch database with the Supabase stub, migrate it, then insert one crypto lot: account `crypto`, symbol `BTC`, currency `CAD`. Then run a health check and two forced runs.
  - All 21 sources should be `ok`.
  - In the first run's holdings phase, `coingecko`, `coinbase_candles` and `kraken_ohlc` should each be called once, for BTC.
  - BTC's features row should have `price_cad` and `unconfirmed_price: false`.
  - `blockchain_stats` takes about 40 s, inside the enrichment stage.
  - The second run should serve the DAILY sources from their window cache.
  - Also run once with no crypto lot or watchlist coin: `crypto_fear_greed` and `blockchain_stats` should not run.
- **Deployment:** nothing new. No source needs a secret.
- **Next:** Plan 2f (news and social), then 2g (13F) and 2h (options, catalysts, Canadian short positions).
