# Plan 2h: Options and Health Catalysts — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Four new pipeline sources: Yahoo option chains (spec source 18), Cboe's daily put/call ratios (19), openFDA drug approvals and recalls (48) and ClinicalTrials.gov trial activity (49).

**Architecture:**
- **`yfinance_options`:**
  - Per US stock, through yfinance, at most 40 per run.
  - Three requests per stock: the expiry list with the nearest chain, then the expiries a week and a month out.
  - Each record: at-the-money implied volatility (IV) per expiry, a put/call skew, and put/call volume and open interest.
- **`cboe_put_call`:** market-wide. One small JSON file per trading day on Cboe's CDN gives the total, equity, index and ETP put/call ratios. These are `SeriesObservation` rows, like FRED's.
- **The catalyst sources:**
  - openFDA and ClinicalTrials.gov name companies, not tickers.
  - Each fetch asks a few market-wide questions (2 and 3 requests) and matches the sponsors' names to the run's stocks. The matcher is a new module, `advisor.sponsors`, and Plan 2j's sources will use it too.
  - `clinical_trials` keeps a small status book on disk, so a trial counts as stopped only if it was seen active first.
- **Records** are cached per symbol (or per day) like every other enrichment source, for the model (Plan 3). Nothing is written to the database.

**Tech Stack:** Python 3.12, httpx, pydantic 2, pandas, yfinance (already in the pipeline); pytest; ruff. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-10-09-stock-advisor-design.md` (rev 2), §4.1 Collector protocol and §4.2 Sources (rows 15, 18, 19, 48–51). Also read:
- `docs/superpowers/deferred.md`, "Plan 2h";
- the research in `.superpowers/research/plan-2h/` (git-ignored, on the owner's machine): `options.md`, `health.md`, `government.md` and `canada.md`.

**Owner's decisions (2026-10-19):**
- Keep ClinicalTrials.gov's documented API, although its robots.txt disallows `/api/`, and honour its `Crawl-delay: 1`.
- Keep Cboe's daily file, best-effort, storing only the ratios.
- Keep the House Clerk's reports, for personal use only.
- Split USAspending.gov (50) and the House reports (51) into a new Plan 2j.
- Drop the Canadian short-position report (15): CIRO's file sits behind a bot check, and its terms ban scraping.

**Prototype:** every file below was built and tested on branch `plan-2h-proto` (2026-10-19), with 754 pipeline tests passing and ruff clean. A live run of all four sources took about 13 s:
- `yfinance_options` gave 5 records for AAPL, MSFT, BRK.B, SPY, NVDA and AACG (AACG has no options);
- `cboe_put_call` gave 20 values, for 5 trading days;
- `openfda` matched 15 of 24 stocks;
- `clinical_trials` matched 19.

The plan transcribes those files.

**Fixtures are already in the repository.** They were recorded live on 2026-10-19, trimmed, and committed with this plan, so no task writes them:
- `pipeline/tests/fixtures/yfinance_options/`: Yahoo's answers for AAPL (the first answer and two chains) and for AACG, which has no options;
- `pipeline/tests/fixtures/openfda/`: approvals and recalls, keeping only the fields used;
- `pipeline/tests/fixtures/clinical_trials/`: the three queries' answers.

## Global Constraints

- **Keyless** (spec §4.2): no source needs an API key or an account.
- **Terms, as the owner reads them:**
  - Yahoo is unofficial and best-effort, like the other yfinance sources.
  - Cboe's terms limit storing copies of its materials, so only the ratios are kept, and its tests use made-up numbers in Cboe's shape.
  - openFDA's data is public domain (CC0).
  - ClinicalTrials.gov's requests are at least 1.2 s apart (`Crawl-delay: 1`).
- **Collector contract** (`pipeline/src/advisor/collectors/base.py`):
  - `fetch(symbols, as_of)` returns validated records or raises, and never touches the database;
  - SYMBOLS records carry the requested symbol;
  - HTTP goes through `get_with_retries`, and long loops honour the run deadline.
- **Pipeline tests run only in Docker**, from `pipeline/`:
  - `scripts/in-docker.sh uv run pytest -q`;
  - `scripts/in-docker.sh uv run ruff check .`.
- **Commits:**
  - Run `git commit` in a command of its own: a plugin hook mistakes any `-n` flag in the same command (`grep -n`, `sed -n`) for skipping hooks.
  - Never skip hooks.
  - Every commit message ends with the `Co-Authored-By:` trailer.
- **Never put a real email address** in code, tests or docs.

## Review Focus

1. **Yahoo's quirks.** Each of these should yield no record or be left out of the numbers, never break the source:
   - a stock with no options (AACG);
   - a share class Yahoo writes with a hyphen (BRK.B is `BRK-B`);
   - Yahoo's placeholder IV (`1e-05`);
   - a quote with no bid or no ask.

   Covered by Task 1: `test_a_stock_without_options_or_a_price_yields_no_record`, `test_share_classes_are_asked_in_yahoos_form`, `test_quotes_without_a_bid_or_with_yahoos_placeholder_iv_are_not_used` and `test_yahoo_takes_three_requests_and_a_token_for_each`.
2. **Cboe's missing days.** A weekend, a holiday or tonight's unposted file answers 403 and is skipped. Ten days with no file means Cboe moved or blocked the files: a clear error. Covered by Task 2: `test_days_without_a_file_are_skipped` and `test_no_file_in_ten_days_means_cboe_moved_or_blocked_them`.
3. **Sponsor names.** A subsidiary, an FDA abbreviation or a cut name should find its parent stock. An everyday word, an ambiguous name or a company outside both universes should find nothing. Covered by Task 3: `test_sponsors_match_the_runs_stocks` and `test_unknown_everyday_or_ambiguous_names_match_nothing`.
4. **openFDA's traps.** An application approved long ago that only got a labeling change matches the server's query. It must not count. An empty window answers 404 and means no events. Covered by Task 4: `test_approvals_and_recalls_are_counted_for_the_runs_stocks` (Pfizer's 1970 application) and `test_a_window_with_nothing_answers_404_and_means_no_events`.
5. **A "stopped" trial that didn't just stop.** A trial terminated in 2023 shows up when its results are posted. A real stop may be found first by the daily health check. Covered by Task 5:
   - `test_activity_from_real_answers` (Novartis's 2023 trial);
   - `test_a_stop_counts_when_the_book_saw_the_trial_active`;
   - `test_stops_found_more_than_ten_days_ago_no_longer_count`.

**Known limits, recorded in `deferred.md` for Plan 3:**
- **After-hours answers.** Yahoo's after-hours answers weren't seen in testing (the research and live checks ran at 11:30–12:30 ET).
- **One-word stock names.** A sponsor name that starts with a one-word stock name is read as that stock. "Sound Pharmaceuticals" would match a stock named "Sound". Matching only the run's few hundred stocks keeps this rare.

## Files

| File | Task | What it is |
|---|---|---|
| `pipeline/src/advisor/collectors/yfinance_options.py` + `tests/unit/test_yfinance_options.py` | 1 | `YFinanceOptions` and its summary maths |
| `pipeline/src/advisor/collectors/cboe_put_call.py` + `tests/unit/test_cboe_put_call.py` | 2 | `CboePutCall` |
| `pipeline/src/advisor/sponsors.py` + `tests/unit/test_sponsors.py` | 3 | `company_key`, `SponsorMatcher` and the alias table |
| `pipeline/src/advisor/collectors/openfda.py` + `tests/unit/test_openfda.py` | 4 | `OpenFda` |
| `pipeline/src/advisor/collectors/clinical_trials.py` + `tests/unit/test_clinical_trials.py` | 5 | `ClinicalTrials` and `StatusBook` |
| `pipeline/src/advisor/collectors/registry.py` + `tests/unit/test_registry.py` | 1, 2, 4, 5 | Each source joins the registry |
| `docs/superpowers/specs/2026-10-09-stock-advisor-design.md`, `docs/superpowers/deferred.md` | 6 | Docs |

---

### Task 1: Summarise option chains from Yahoo

**Files:**
- Create: `pipeline/src/advisor/collectors/yfinance_options.py`
- Modify: `pipeline/src/advisor/collectors/registry.py`
- Test: `pipeline/tests/unit/test_yfinance_options.py`, `pipeline/tests/unit/test_registry.py`
- Uses (already committed): `pipeline/tests/fixtures/yfinance_options/AAPL_first.json`, `AAPL_20261026.json`, `AAPL_20261120.json`, `noopts_AACG.json`. These are Yahoo's whole `/v7/finance/options` answers, trimmed to the strikes near spot.

**Interfaces:**
- Consumes:
  - `collect_yahoo(symbols, fetch_one, limiter=...)`, which stops on Yahoo's rate limit or a run of empty answers (`collectors/yahoo.py`);
  - `to_yahoo(symbol)`, so BRK.B becomes BRK-B (`yfinance_bars.py`);
  - `RateLimiter`, `Cadence`, `Category` and `Scope` (`base.py`);
  - `ET` (`advisor.models`).
- Produces:
  - `YFinanceOptions(load=None, limiter=None)`:
    - `name = "yfinance_options"`, OPTIONS, best-effort, not core, PER_RUN;
    - US stocks, SYMBOLS scope, `max_symbols = 40`, canary AAPL.
  - `OptionsView` records.
  - The `Loader` type, `(yahoo_symbol, choose) -> ChainSet | None`, with `ChainSet(quote, expiries, chains)` and `Chain(expiry, calls, puts)`.
  - Helpers: `choose_expiries(expiries, today)`, `atm_iv(chain, spot)`, `skew(chain, spot)` and `options_view(symbol, data, as_of)`.
  - `YahooChains(limiter)` is the real loader. It takes a Yahoo limiter token before every request.

- [ ] **Step 1: Write the failing tests**

`pipeline/tests/unit/test_yfinance_options.py`:

```python
import json
import sys
import types
from datetime import UTC, date, datetime

import pandas as pd
import pytest

from advisor.collectors.yfinance_options import (
    Chain,
    ChainSet,
    OptionsView,
    YFinanceOptions,
    atm_iv,
    choose_expiries,
    options_view,
)
from advisor.models import Market

AS_OF = datetime(2026, 10, 19, 15, 30, tzinfo=UTC)  # 11:30 ET, when the fixtures were taken
TODAY = date(2026, 10, 19)
COLUMNS = ["contractSymbol", "lastTradeDate", "strike", "lastPrice", "bid", "ask", "change",
           "percentChange", "volume", "openInterest", "impliedVolatility", "inTheMoney"]


def answer(fixtures_dir, name: str) -> dict:
    """One of Yahoo's /v7/finance/options answers (its `result[0]`), trimmed to strikes near spot."""
    text = (fixtures_dir / "yfinance_options" / name).read_text(encoding="utf-8")
    return json.loads(text)["optionChain"]["result"][0]


def frame(contracts: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(contracts).reindex(columns=COLUMNS)  # as yfinance builds it


def expiry_of(epoch: int) -> date:
    return datetime.fromtimestamp(epoch, UTC).date()


def chain_of(result: dict) -> Chain:
    options = result["options"][0]
    return Chain(expiry_of(options["expirationDate"]), frame(options["calls"]), frame(options["puts"]))


def aapl(fixtures_dir) -> ChainSet:
    first = answer(fixtures_dir, "AAPL_first.json")
    chains = [chain_of(first)] + [
        chain_of(answer(fixtures_dir, name)) for name in ("AAPL_20261026.json", "AAPL_20261120.json")
    ]
    return ChainSet(first["quote"], [expiry_of(e) for e in first["expirationDates"]], chains)


def test_the_near_expiry_is_a_week_out_and_the_mid_one_closest_to_a_month(fixtures_dir):
    expiries = aapl(fixtures_dir).expiries
    assert expiries[0] == TODAY  # Yahoo lists today's 0DTE expiry first
    assert choose_expiries(expiries, TODAY) == [date(2026, 10, 26), date(2026, 11, 20)]
    assert choose_expiries([date(2026, 10, 23)], TODAY) == []  # nothing a week out
    assert choose_expiries([date(2026, 11, 13)], TODAY) == [date(2026, 11, 13)]  # near is mid


def test_an_apple_summary_from_real_chains(fixtures_dir):
    view = options_view("AAPL", aapl(fixtures_dir), AS_OF)
    assert (view.near_expiry, view.mid_expiry, view.expiries) == (date(2026, 10, 26), date(2026, 11, 20), 23)
    assert view.underlying_price == pytest.approx(343.135)
    assert view.market_state == "REGULAR"
    assert view.quote_time == datetime(2026, 10, 19, 15, 28, 21, tzinfo=UTC)
    assert view.atm_iv_near == pytest.approx(0.2246, abs=5e-4)
    assert view.atm_iv_mid == pytest.approx(0.2689, abs=5e-4)
    assert view.skew_near == pytest.approx(0.0497, abs=5e-4)
    # Volume and open interest leave out today's 0DTE chain
    near_and_mid = aapl(fixtures_dir).chains[1:]
    assert view.call_volume == sum(int(c.calls["volume"].fillna(0).sum()) for c in near_and_mid)
    assert view.put_call_volume == pytest.approx(view.put_volume / view.call_volume)
    assert view.put_call_open_interest == pytest.approx(view.put_open_interest / view.call_open_interest)


def test_quotes_without_a_bid_or_with_yahoos_placeholder_iv_are_not_used():
    def side(*rows):
        return frame([{"strike": s, "bid": b, "ask": a, "impliedVolatility": iv} for s, b, a, iv in rows])

    chain = Chain(
        date(2026, 10, 26),
        side((95, 6.0, 6.2, 0.30), (100, 2.0, 2.1, 0.00001), (105, 0.0, 0.5, 0.90)),
        side((95, 0.9, 1.0, 0.34), (100, 2.4, 2.5, 0.00001), (105, 5.0, 5.2, 0.26)),
    )
    # 100 has only placeholders and 105's call has no bid: interpolate 95 (0.32) and 105 (0.26)
    assert atm_iv(chain, 100.0) == pytest.approx(0.29)
    assert atm_iv(Chain(date(2026, 10, 26), side(), side()), 100.0) is None


def test_a_stock_without_options_or_a_price_yields_no_record():
    assert options_view("AACG", ChainSet({"regularMarketPrice": 0.81}, [], []), AS_OF) is None
    assert options_view("X", ChainSet({}, [TODAY], []), AS_OF) is None


class FakeTicker:
    """yfinance's Ticker as the loader uses it, answering from the fixtures and counting requests."""

    requests: list[str] = []

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        self._first = None

    def option_chain(self, date: str | None = None):
        FakeTicker.requests.append(f"{self.symbol} {date or 'first'}")
        result = self.answers[self.symbol if date is None else f"{self.symbol} {date}"]
        if not result["options"]:
            return types.SimpleNamespace(calls=None, puts=None, underlying=None)
        self._first = self._first or result
        options = result["options"][0]
        return types.SimpleNamespace(
            calls=frame(options["calls"]), puts=frame(options["puts"]), underlying=result["quote"]
        )

    @property
    def options(self) -> tuple[str, ...]:
        return tuple(expiry_of(e).isoformat() for e in self._first["expirationDates"])


class CountingLimiter:
    def __init__(self) -> None:
        self.count = 0

    def acquire(self) -> None:
        self.count += 1


@pytest.fixture
def fake_yfinance(fixtures_dir, monkeypatch):
    FakeTicker.requests = []
    FakeTicker.answers = {
        "AAPL": answer(fixtures_dir, "AAPL_first.json"),
        "AAPL 2026-10-26": answer(fixtures_dir, "AAPL_20261026.json"),
        "AAPL 2026-11-20": answer(fixtures_dir, "AAPL_20261120.json"),
        "AACG": answer(fixtures_dir, "noopts_AACG.json"),
    }
    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=FakeTicker))
    return FakeTicker


def test_yahoo_takes_three_requests_and_a_token_for_each(fake_yfinance):
    limiter = CountingLimiter()
    records = YFinanceOptions(limiter=limiter).fetch(["AAPL", "AACG"], AS_OF)
    assert fake_yfinance.requests == ["AAPL first", "AAPL 2026-10-26", "AAPL 2026-11-20", "AACG first"]
    assert limiter.count == 4
    assert [r.symbol for r in records] == ["AAPL"]  # AACG lists no options
    assert isinstance(records[0], OptionsView)


def test_share_classes_are_asked_in_yahoos_form():
    asked = []

    def load(yahoo_symbol, choose):
        asked.append(yahoo_symbol)
        return ChainSet({"regularMarketPrice": 500.0}, [date(2026, 10, 30)], [])

    records = YFinanceOptions(load=load).fetch(["BRK.B"], AS_OF)
    assert asked == ["BRK-B"]  # "BRK.B" gets an empty stub from Yahoo
    assert [r.symbol for r in records] == ["BRK.B"]


def test_the_source_is_us_only_per_run_and_capped():
    collector = YFinanceOptions()
    assert collector.markets == frozenset({Market.US})
    assert collector.cadence == "per_run"
    assert collector.max_symbols == 40
```

In `pipeline/tests/unit/test_registry.py`, replace:

```python
    "yfinance_earnings": (True, Scope.SYMBOLS, True, BOTH),
```

with:

```python
    "yfinance_earnings": (True, Scope.SYMBOLS, True, BOTH),
    "yfinance_options": (False, Scope.SYMBOLS, True, US),
```

- [ ] **Step 2: Run them and see them fail**

Run (from `pipeline/`): `scripts/in-docker.sh uv run pytest -q tests/unit/test_yfinance_options.py tests/unit/test_registry.py`
Expected: `1 error during collection`: `ModuleNotFoundError: No module named 'advisor.collectors.yfinance_options'`.

- [ ] **Step 3: Write the collector**

`pipeline/src/advisor/collectors/yfinance_options.py`:

```python
"""Option-market summaries per US stock from Yahoo option chains via yfinance (source 18).

Yahoo answers one expiry per request. The first request also lists every expiry and returns the
nearest chain, often expiring today (0DTE). Then two more requests fetch:
- the "near" expiry, the first at least NEAR_DAYS away;
- the "mid" expiry, the one closest to MID_DAYS out of those at least MID_MIN_DAYS away.

From those chains the record keeps:
- at-the-money implied volatility (IV) per expiry;
- a put/call skew;
- put/call volume and open-interest ratios. Chains expiring today are left out: they dominate the
  day's volume.

IV is live during the session, and volume counts the day so far, so a record describes the
market at `quote_time`. A quote without a bid and an ask, or with Yahoo's 1e-05 IV placeholder,
is not used.

TSX stocks have no options on Yahoo, so the source is US only. A stock without options yields no
record, like the other Yahoo sources. The source is capped per call to the top of the shortlist.
"""

import logging
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from functools import partial
from typing import Any

import pandas as pd
from pydantic import BaseModel, ConfigDict

from advisor.collectors.base import Cadence, Category, RateLimiter, Scope
from advisor.collectors.yahoo import collect_yahoo
from advisor.collectors.yfinance_bars import to_yahoo
from advisor.models import ET, AssetType, Market

NEAR_DAYS = 7
MID_DAYS = 30
MID_MIN_DAYS = 21
MIN_IV = 0.01  # below this Yahoo is showing its 1e-05 placeholder, not a quote
SKEW_PUT = 0.95  # skew compares the put 5% below spot with the call 5% above
SKEW_CALL = 1.05
SKEW_TOLERANCE = 0.03  # the nearest quoted strike must be within 3% of spot of the target


@dataclass(frozen=True)
class Chain:
    expiry: date
    calls: pd.DataFrame
    puts: pd.DataFrame


@dataclass(frozen=True)
class ChainSet:
    quote: dict  # Yahoo's quote of the underlying, from the same responses
    expiries: list[date]
    chains: list[Chain]


Chooser = Callable[[list[date]], list[date]]
Loader = Callable[[str, Chooser], ChainSet | None]  # None: the stock has no listed options


class OptionsView(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    as_of: date  # ET date of the run
    quote_time: datetime | None = None  # when Yahoo last priced the underlying (UTC)
    market_state: str | None = None  # Yahoo's "REGULAR", "PRE", "POST", "CLOSED"...
    underlying_price: float | None = None
    expiries: int  # listed expiries
    near_expiry: date | None = None
    atm_iv_near: float | None = None  # a fraction: 0.24 is 24%
    mid_expiry: date | None = None
    atm_iv_mid: float | None = None
    skew_near: float | None = None  # IV of the 95% put minus IV of the 105% call, near expiry
    call_volume: int = 0  # over the fetched chains, leaving out any expiring today
    put_volume: int = 0
    call_open_interest: int = 0
    put_open_interest: int = 0
    put_call_volume: float | None = None
    put_call_open_interest: float | None = None


def choose_expiries(expiries: Sequence[date], today: date) -> list[date]:
    """The near expiry and the mid expiry (when they exist), deduplicated, in date order."""
    near = next((e for e in sorted(expiries) if (e - today).days >= NEAR_DAYS), None)
    later = [e for e in expiries if (e - today).days >= MID_MIN_DAYS]
    mid = min(later, key=lambda e: (abs((e - today).days - MID_DAYS), e)) if later else None
    return sorted({e for e in (near, mid) if e is not None})


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def quoted(side: pd.DataFrame) -> pd.DataFrame:
    """The contracts with a live two-sided quote and a real IV."""
    if side is None or side.empty:
        return pd.DataFrame(columns=["strike", "impliedVolatility"])
    frame = side.reindex(columns=["strike", "bid", "ask", "impliedVolatility"])
    frame = frame.apply(pd.to_numeric, errors="coerce")
    keep = (frame["bid"] > 0) & (frame["ask"] > 0) & (frame["impliedVolatility"] > MIN_IV)
    return frame[keep]


def atm_iv(chain: Chain, spot: float) -> float | None:
    """IV at the spot price: the strikes either side of spot, calls and puts averaged, interpolated."""
    both = pd.concat([quoted(chain.calls), quoted(chain.puts)])
    if both.empty:
        return None
    by_strike = both.groupby("strike")["impliedVolatility"].mean().sort_index()
    below = by_strike[by_strike.index <= spot]
    above = by_strike[by_strike.index >= spot]
    if below.empty or above.empty:
        return None
    low, high = float(below.index[-1]), float(above.index[0])
    if low == high:
        return float(below.iloc[-1])
    weight = (spot - low) / (high - low)
    return float(below.iloc[-1] + weight * (above.iloc[0] - below.iloc[-1]))


def _iv_near(side: pd.DataFrame, target: float, spot: float) -> float | None:
    live = quoted(side)
    if live.empty:
        return None
    distance = (live["strike"] - target).abs()
    nearest = live.loc[distance.idxmin()]
    if abs(nearest["strike"] - target) > SKEW_TOLERANCE * spot:
        return None
    return float(nearest["impliedVolatility"])


def skew(chain: Chain, spot: float) -> float | None:
    put = _iv_near(chain.puts, SKEW_PUT * spot, spot)
    call = _iv_near(chain.calls, SKEW_CALL * spot, spot)
    return None if put is None or call is None else put - call


def _total(side: pd.DataFrame, column: str) -> int:
    if side is None or side.empty or column not in side:
        return 0
    return int(pd.to_numeric(side[column], errors="coerce").fillna(0).sum())


def _ratio(puts: int, calls: int) -> float | None:
    return puts / calls if calls > 0 else None


def options_view(symbol: str, data: ChainSet, as_of: datetime) -> OptionsView | None:
    today = as_of.astimezone(ET).date()
    spot = _number(data.quote.get("regularMarketPrice"))
    if not data.expiries or spot is None or spot <= 0:
        return None
    chains = {chain.expiry: chain for chain in data.chains}
    wanted = choose_expiries(data.expiries, today)
    near = chains.get(wanted[0]) if wanted else None
    mid = chains.get(wanted[-1]) if len(wanted) > 1 else None
    counted = [chain for chain in data.chains if chain.expiry > today]  # not expiring today
    calls = _total_of(counted, "calls", "volume")
    puts = _total_of(counted, "puts", "volume")
    call_oi = _total_of(counted, "calls", "openInterest")
    put_oi = _total_of(counted, "puts", "openInterest")
    quote_time = _number(data.quote.get("regularMarketTime"))
    return OptionsView(
        symbol=symbol,
        as_of=today,
        quote_time=datetime.fromtimestamp(quote_time, UTC) if quote_time else None,
        market_state=data.quote.get("marketState"),
        underlying_price=spot,
        expiries=len(data.expiries),
        near_expiry=near.expiry if near else None,
        atm_iv_near=atm_iv(near, spot) if near else None,
        mid_expiry=mid.expiry if mid else None,
        atm_iv_mid=atm_iv(mid, spot) if mid else None,
        skew_near=skew(near, spot) if near else None,
        call_volume=calls,
        put_volume=puts,
        call_open_interest=call_oi,
        put_open_interest=put_oi,
        put_call_volume=_ratio(puts, calls),
        put_call_open_interest=_ratio(put_oi, call_oi),
    )


def _total_of(chains: Sequence[Chain], side: str, column: str) -> int:
    return sum(_total(getattr(chain, side), column) for chain in chains)


class YahooChains:
    """Loads chains through yfinance, taking a Yahoo limiter token before every request."""

    def __init__(self, limiter: RateLimiter | None = None) -> None:
        self._limiter = limiter

    def _request(self, read: Callable[[], Any]) -> Any:
        if self._limiter is not None:
            self._limiter.acquire()
        return read()

    def __call__(self, yahoo_symbol: str, choose: Chooser) -> ChainSet | None:
        import yfinance as yf  # imported lazily: slow import, and tests inject a fake

        logging.getLogger("yfinance").setLevel(logging.CRITICAL)
        ticker = yf.Ticker(yahoo_symbol)
        first = self._request(ticker.option_chain)  # the expiry list and the nearest chain
        if first.calls is None:
            return None
        listed = list(ticker.options)  # from the first answer: no request
        expiries = [date.fromisoformat(text) for text in listed]
        chains = [Chain(expiries[0], first.calls, first.puts)]
        for expiry in choose(expiries):
            if expiry != expiries[0]:
                chain = self._request(partial(ticker.option_chain, expiry.isoformat()))
                chains.append(Chain(expiry, chain.calls, chain.puts))
        return ChainSet(first.underlying or {}, expiries, chains)


class YFinanceOptions:
    name = "yfinance_options"
    category = Category.OPTIONS
    core = False
    best_effort = True
    cadence = Cadence.PER_RUN
    asset_types = frozenset({AssetType.STOCK})
    markets = frozenset({Market.US})
    record_type = OptionsView
    freshness = timedelta(days=3)
    scope = Scope.SYMBOLS
    canary = ("AAPL",)
    canary_requires_records = True
    max_symbols = 40  # 3 requests each: about 120 Yahoo requests a run

    def __init__(self, load: Loader | None = None, limiter: RateLimiter | None = None) -> None:
        self._load = load or YahooChains(limiter)

    def fetch(self, symbols: Sequence[str], as_of: datetime) -> list[OptionsView]:
        today = as_of.astimezone(ET).date()

        def one(symbol: str) -> list[OptionsView]:
            data = self._load(to_yahoo(symbol), lambda expiries: choose_expiries(expiries, today))
            view = options_view(symbol, data, as_of) if data else None
            return [view] if view else []

        return collect_yahoo(symbols, one, limiter=None)  # the loader takes a token per request
```

- [ ] **Step 4: Register it**

In `pipeline/src/advisor/collectors/registry.py`, replace:

```python
from advisor.collectors.yfinance_earnings import YFinanceEarnings
```

with:

```python
from advisor.collectors.yfinance_earnings import YFinanceEarnings
from advisor.collectors.yfinance_options import YFinanceOptions
```

In `pipeline/src/advisor/collectors/registry.py`, replace:

```python
        YFinanceEarnings(limiter=yahoo),
```

with:

```python
        YFinanceEarnings(limiter=yahoo),
        YFinanceOptions(limiter=yahoo),
```

- [ ] **Step 5: Run the tests**

Run: `scripts/in-docker.sh uv run pytest -q tests/unit/test_yfinance_options.py tests/unit/test_registry.py`
Expected: `10 passed`.

Run: `scripts/in-docker.sh uv run pytest -q`, then `scripts/in-docker.sh uv run ruff check .`
Expected: `700 passed` (693 before this plan, plus this task's seven), then `All checks passed!`.

- [ ] **Step 6: Commit**

```bash
git add pipeline/src/advisor/collectors/yfinance_options.py pipeline/src/advisor/collectors/registry.py pipeline/tests/unit/test_yfinance_options.py pipeline/tests/unit/test_registry.py
git commit -m "feat: summarise Yahoo option chains for the top of the shortlist"
```

---

### Task 2: Read Cboe's daily put/call ratios

**Files:**
- Create: `pipeline/src/advisor/collectors/cboe_put_call.py`
- Modify: `pipeline/src/advisor/collectors/registry.py`
- Test: `pipeline/tests/unit/test_cboe_put_call.py`, `pipeline/tests/unit/test_registry.py`

**Interfaces:**
- Consumes:
  - `get_with_retries`, which raises `httpx.HTTPStatusError` at once on a 403 (`base.py`);
  - `SeriesObservation(series, day, value)` (`collectors/series.py`);
  - `ET` (`advisor.models`).
- Produces:
  - `CboePutCall(client, limiter=None)`:
    - `name = "cboe_put_call"`, OPTIONS, best-effort, DAILY;
    - MARKET scope, US.
    - It returns the series `cboe_total_put_call`, `cboe_equity_put_call`, `cboe_index_put_call` and `cboe_etp_put_call` for each day with a file in the last 10 days.
  - `CBOE_PER_MINUTE = 60`.
  - Helpers: `parse_day(payload, day)` and `weekdays(as_of)`.

- [ ] **Step 1: Write the failing tests**

`pipeline/tests/unit/test_cboe_put_call.py`:

```python
from datetime import UTC, date, datetime

import httpx
import pytest

from advisor.collectors.cboe_put_call import CboePutCall, parse_day, weekdays
from advisor.models import Market

AS_OF = datetime(2026, 10, 19, 15, 30, tzinfo=UTC)  # Monday 11:30 ET
ACCESS_DENIED = "<?xml version=\"1.0\" encoding=\"UTF-8\"?><Error><Code>AccessDenied</Code></Error>"


def daily(equity_puts: int = 2_000_000) -> dict:
    """A day's file in Cboe's shape, with made-up numbers (Cboe's terms limit storing its files)."""

    def group(calls: int, puts: int) -> list[dict]:
        return [
            {"name": "VOLUME", "call": calls, "put": puts, "total": calls + puts},
            {"name": "OPEN INTEREST", "call": 10 * calls, "put": 10 * puts, "total": 10 * (calls + puts)},
        ]

    return {
        "ratios": [{"name": "TOTAL PUT/CALL RATIO", "value": "0.90"}],
        "SUM OF ALL PRODUCTS": group(10_000_000, 9_000_000),
        "INDEX OPTIONS": list(reversed(group(5_000_000, 5_500_000))),  # entries matched by name
        "EQUITY OPTIONS": group(3_200_000, equity_puts),
        "CBOE VOLATILITY INDEX (VIX)": group(800_000, 250_000),
    }


def cboe(days: dict[str, dict], asked: list[str], status: int = 403) -> httpx.Client:
    """Cboe's CDN: a file for each day in `days`, and `status` (403, as S3 answers) for the rest."""

    def handler(request: httpx.Request) -> httpx.Response:
        day = request.url.path.rsplit("/", 1)[-1].removesuffix("_daily_options")
        asked.append(day)
        if day in days:
            return httpx.Response(200, json=days[day])
        return httpx.Response(status, text=ACCESS_DENIED)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_a_days_ratios_are_puts_over_calls_found_by_group_name():
    rows = {row.series: row.value for row in parse_day(daily(), date(2026, 10, 16))}
    assert rows == {
        "cboe_total_put_call": pytest.approx(0.9),
        "cboe_equity_put_call": pytest.approx(0.625),
        "cboe_index_put_call": pytest.approx(1.1),
    }  # this file has no exchange-traded products group
    with pytest.raises(ValueError, match="none of its put/call groups"):
        parse_day({"ratios": []}, date(2026, 10, 16))


def test_the_last_ten_days_are_asked_for_weekdays_only():
    assert weekdays(AS_OF) == [
        date(2026, 10, 12), date(2026, 10, 13), date(2026, 10, 14), date(2026, 10, 15),
        date(2026, 10, 16), date(2026, 10, 19),
    ]


def test_days_without_a_file_are_skipped():
    asked: list[str] = []
    files = {"2026-10-15": daily(), "2026-10-16": daily(equity_puts=3_200_000)}
    with cboe(files, asked) as client:
        rows = CboePutCall(client).fetch([], AS_OF)
    assert len(asked) == 6  # today's file isn't posted until the evening
    equity = [(row.day, row.value) for row in rows if row.series == "cboe_equity_put_call"]
    assert equity == [(date(2026, 10, 15), 0.625), (date(2026, 10, 16), 1.0)]


def test_no_file_in_ten_days_means_cboe_moved_or_blocked_them():
    with cboe({}, []) as client, pytest.raises(RuntimeError, match="no put/call file"):
        CboePutCall(client).fetch([], AS_OF)


def test_other_http_errors_fail_the_fetch():
    with cboe({}, [], status=404) as client, pytest.raises(httpx.HTTPStatusError, match="404"):
        CboePutCall(client).fetch([], AS_OF)


def test_the_source_is_us_market_wide_daily_and_best_effort():
    collector = CboePutCall(httpx.Client())
    assert (collector.scope, collector.cadence, collector.best_effort) == ("market", "daily", True)
    assert collector.markets == frozenset({Market.US})
```

In `pipeline/tests/unit/test_registry.py`, replace:

```python
    "yfinance_options": (False, Scope.SYMBOLS, True, US),
```

with:

```python
    "yfinance_options": (False, Scope.SYMBOLS, True, US),
    "cboe_put_call": (False, Scope.MARKET, True, US),
```

- [ ] **Step 2: Run them and see them fail**

Run: `scripts/in-docker.sh uv run pytest -q tests/unit/test_cboe_put_call.py tests/unit/test_registry.py`
Expected: `1 error during collection`: `ModuleNotFoundError: No module named 'advisor.collectors.cboe_put_call'`.

- [ ] **Step 3: Write the collector**

`pipeline/src/advisor/collectors/cboe_put_call.py`:

```python
"""Cboe's daily put/call ratios: total, equity, index and exchange-traded products (source 19).

Cboe posts one small JSON file per trading day on its CDN, in the evening (about 21:00-23:00
ET). It has volume and open interest per product group. A day without a file answers HTTP 403,
not 404: a weekend, a holiday, or today before it's posted. So each fetch asks for the weekdays
of the last LOOKBACK_DAYS and keeps the days that have a file. If none has one, Cboe has moved
or blocked the files, and the fetch fails.

The ratios are computed from the put and call volumes, which are exact; the file's own ratio
strings are rounded to two places. "Total" covers every product listed on Cboe's exchanges,
not the whole US options market.

Cboe's terms limit storing copies of its site's materials, so only these few numbers are kept.
"""

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from typing import Any

import httpx

from advisor.collectors.base import Cadence, Category, RateLimiter, Scope, get_with_retries
from advisor.collectors.series import SeriesObservation
from advisor.models import ET, AssetType, Market

DAILY_URL = "https://cdn.cboe.com/data/us/options/market_statistics/daily/{day}_daily_options"
LOOKBACK_DAYS = 10
CBOE_PER_MINUTE = 60
GROUPS = {  # series name: Cboe's product group
    "cboe_total_put_call": "SUM OF ALL PRODUCTS",
    "cboe_equity_put_call": "EQUITY OPTIONS",
    "cboe_index_put_call": "INDEX OPTIONS",
    "cboe_etp_put_call": "EXCHANGE TRADED PRODUCTS",
}


def parse_day(payload: Mapping[str, Any], day: date) -> list[SeriesObservation]:
    """Each group's put volume over its call volume. Groups are found by name, never position."""
    rows: list[SeriesObservation] = []
    for series, group in GROUPS.items():
        volume = next(
            (entry for entry in payload.get(group) or [] if entry.get("name") == "VOLUME"), None
        )
        if volume is None:
            continue
        calls, puts = int(volume["call"]), int(volume["put"])
        if calls > 0:
            rows.append(SeriesObservation(series=series, day=day, value=puts / calls))
    if not rows:
        raise ValueError(f"Cboe's file for {day} has none of its put/call groups")
    return rows


def weekdays(as_of: datetime, days: int = LOOKBACK_DAYS) -> list[date]:
    """The weekdays of the last `days` ET days, today included, oldest first."""
    today = as_of.astimezone(ET).date()
    span = (today - timedelta(days=back) for back in range(days - 1, -1, -1))
    return [day for day in span if day.weekday() < 5]


class CboePutCall:
    name = "cboe_put_call"
    category = Category.OPTIONS
    core = False
    best_effort = True
    cadence = Cadence.DAILY
    asset_types = frozenset({AssetType.STOCK})
    markets = frozenset({Market.US})
    record_type = SeriesObservation
    freshness = timedelta(days=5)
    scope = Scope.MARKET
    canary: tuple[str, ...] = ()
    canary_requires_records = True
    max_symbols = None

    def __init__(self, client: httpx.Client, limiter: RateLimiter | None = None) -> None:
        self._client = client
        self._limiter = limiter

    def fetch(self, symbols: Sequence[str], as_of: datetime) -> list[SeriesObservation]:
        rows: list[SeriesObservation] = []
        for day in weekdays(as_of):
            try:
                response = get_with_retries(
                    self._client, DAILY_URL.format(day=day.isoformat()), limiter=self._limiter
                )
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 403:  # no file for that day
                    continue
                raise
            rows.extend(parse_day(response.json(), day))
        if not rows:
            raise RuntimeError(f"Cboe has no put/call file for the last {LOOKBACK_DAYS} days")
        return rows
```

- [ ] **Step 4: Register it**

In `pipeline/src/advisor/collectors/registry.py`, replace:

```python
from advisor.collectors.boc_valet import BankOfCanadaValet
```

with:

```python
from advisor.collectors.boc_valet import BankOfCanadaValet
from advisor.collectors.cboe_put_call import CBOE_PER_MINUTE, CboePutCall
```

In `pipeline/src/advisor/collectors/registry.py`, replace:

```python
        YFinanceOptions(limiter=yahoo),
```

with:

```python
        YFinanceOptions(limiter=yahoo),
        CboePutCall(client, RateLimiter(per_minute=CBOE_PER_MINUTE, burst=2)),
```

- [ ] **Step 5: Run the tests**

Run: `scripts/in-docker.sh uv run pytest -q tests/unit/test_cboe_put_call.py tests/unit/test_registry.py`
Expected: `9 passed`.

Run: `scripts/in-docker.sh uv run pytest -q`, then `scripts/in-docker.sh uv run ruff check .`
Expected: `706 passed`, then `All checks passed!`.

- [ ] **Step 6: Commit**

```bash
git add pipeline/src/advisor/collectors/cboe_put_call.py pipeline/src/advisor/collectors/registry.py pipeline/tests/unit/test_cboe_put_call.py pipeline/tests/unit/test_registry.py
git commit -m "feat: read Cboe's daily put/call ratios"
```

---

### Task 3: Match sponsors' names to the run's stocks

**Files:**
- Create: `pipeline/src/advisor/sponsors.py`
- Test: `pipeline/tests/unit/test_sponsors.py`

**Interfaces:**
- Consumes:
  - `search_name(directory_name)`: "Pfizer, Inc. Common Stock" becomes "Pfizer, Inc" (`advisor.company_names`);
  - `COMMON_WORDS`, one-word company names that are everyday words (`advisor.news.mapping`).
- Produces (Tasks 4 and 5, and Plan 2j, use them):
  - `company_key(name) -> str`. For example "Seagen, a wholly owned subsidiary of Pfizer" becomes "PFIZER", and "JANSSEN PHARMS" becomes "JANSSEN PHARMACEUTICALS".
  - `SponsorMatcher(names, aliases=ALIASES).symbols_for(name) -> set[str]`:
    - `names` maps the run's symbols to directory names;
    - it returns an empty set for an unknown or ambiguous name.
  - `ALIASES`, a dict from alias to symbol.

- [ ] **Step 1: Write the failing tests**

`pipeline/tests/unit/test_sponsors.py`:

```python
import pytest

from advisor.sponsors import SponsorMatcher, company_key

# Directory names as NASDAQ Trader and TMX list them (2026-10-19)
NAMES = {
    "PFE": "Pfizer, Inc. Common Stock",
    "LLY": "Eli Lilly and Company Common Stock",
    "MRK": "Merck & Company, Inc. Common Stock (new)",
    "JNJ": "Johnson & Johnson Common Stock",
    "NVS": "Novartis AG Common Stock",
    "NVO": "Novo Nordisk A/S Common Stock",
    "AZN": "AstraZeneca PLC Ordinary Shares",
    "GILD": "Gilead Sciences, Inc. - Common Stock",
    "BMY": "Bristol-Myers Squibb Company Common Stock",
    "TAK": "Takeda Pharmaceutical Company Limited American Depositary Shares (each representing 1/2 of a share of Common Stock)",
    "MRNA": "Moderna, Inc. - Common Stock",
    "BHC": "Bausch Health Companies Inc. Common Stock",
    "UTHR": "United Therapeutics Corporation - Common Stock",
    "AIG": "American International Group, Inc. New Common Stock",
    "ACAD": "ACADIA Pharmaceuticals Inc. - Common Stock",
    "ACHC": "Acadia Healthcare Company, Inc. - Common Stock",
    "JAZZ": "Jazz Pharmaceuticals plc - Ordinary Shares",
    "GUD.TO": "Knight Therapeutics Inc.",
    "GOOG": "Alphabet Inc. - Class C Capital Stock",
    "GOOGL": "Alphabet Inc. - Class A Common Stock",
}


@pytest.mark.parametrize(("name", "key"), [
    ("ELI LILLY AND CO", "ELI LILLY"),
    ("Eli Lilly and Company", "ELI LILLY"),
    ("JANSSEN PHARMS", "JANSSEN PHARMACEUTICALS"),
    ("Seagen, a wholly owned subsidiary of Pfizer", "PFIZER"),
    ("Kite, A Gilead Company", "GILEAD"),
    ("Acceleron Pharma, Inc., a wholly-owned subsidiary of Merck & Co., Inc., Rahway, NJ USA", "MERCK"),
    ("MSD SUB MERCK", "MERCK"),
    ("Knight Therapeutics (USA) Inc", "KNIGHT THERAPEUTICS"),
    ("Hoffmann-La Roche", "HOFFMANN LA ROCHE"),
    ("Novo Nordisk A/S", "NOVO NORDISK"),
    ("ASTRAZENECA AB", "ASTRAZENECA"),
])
def test_a_company_key_is_the_parent_without_legal_words(name, key):
    assert company_key(name) == key


@pytest.mark.parametrize(("sponsor", "symbols"), [
    ("PFIZER", {"PFE"}),  # FDA's drug sponsor
    ("Pfizer", {"PFE"}),  # ClinicalTrials.gov's lead sponsor
    ("ELI LILLY AND CO", {"LLY"}),
    ("DICE Therapeutics, Inc., a wholly owned subsidiary of Eli Lilly and Company", {"LLY"}),
    ("NOVARTIS PHARMACEUTICALS CORP", {"NVS"}),  # starts with a stock's name
    ("Novo Nordisk A/S", {"NVO"}),
    ("ASTRAZENECA AB", {"AZN"}),
    ("TAKEDA PHARMS USA", {"TAK"}),
    ("JAZZ", {"JAZZ"}),  # FDA cuts names short: a stock's name starts with it
    ("Bristol-Myers Squibb", {"BMY"}),
    ("Karuna Therapeutics, Inc., a Bristol Myers Squibb company", {"BMY"}),
    ("Knight Therapeutics (USA) Inc", {"GUD.TO"}),
    ("Bausch Health Americas, Inc.", {"BHC"}),  # by the "Bausch Health" prefix
    ("ModernaTX, Inc.", {"MRNA"}),  # an alias
    ("JANSSEN RESEARCH & DEVELOPMENT, LLC", {"JNJ"}),  # an alias, extended
    ("MERCK SHARP DOHME", {"MRK"}),
    ("Alphabet", {"GOOG", "GOOGL"}),  # share classes share the name
])
def test_sponsors_match_the_runs_stocks(sponsor, symbols):
    assert SponsorMatcher(NAMES).symbols_for(sponsor) == symbols


@pytest.mark.parametrize("sponsor", [
    "American Regent",  # "American" is an everyday word, and not AIG
    "United Orthopedic Corp",  # not United Therapeutics
    "Genentech, Inc.",  # Roche's: not in either universe
    "BOEHRINGER INGELHEIM",  # private
    "ACADIA",  # ACADIA Pharmaceuticals or Acadia Healthcare: ambiguous
    "",
])
def test_unknown_everyday_or_ambiguous_names_match_nothing(sponsor):
    assert SponsorMatcher(NAMES).symbols_for(sponsor) == set()


def test_an_alias_counts_only_when_its_stock_is_in_the_run():
    matcher = SponsorMatcher({"PFE": NAMES["PFE"]})
    assert matcher.symbols_for("ModernaTX, Inc.") == set()
```

- [ ] **Step 2: Run them and see them fail**

Run: `scripts/in-docker.sh uv run pytest -q tests/unit/test_sponsors.py`
Expected: `1 error during collection`: `ModuleNotFoundError: No module named 'advisor.sponsors'`.

- [ ] **Step 3: Write the matcher**

`pipeline/src/advisor/sponsors.py`:

```python
"""Matching company names in catalyst data to the run's stocks.

Drug sponsors, recalling firms and trial sponsors are names, not tickers, and they come in
several forms for one company:
- FDA shorthand: "MERCK SHARP DOHME", "JANSSEN PHARMS", "ELI LILLY AND CO";
- legal names: "Vertex Pharmaceuticals Incorporated";
- subsidiaries: "Seagen, a wholly owned subsidiary of Pfizer", "Kite, A Gilead Company",
  "MSD SUB MERCK".

Each name is reduced to a key: its parent company, first comma part, upper case, abbreviations
spelled out, and legal words dropped. A name matches a stock when the keys are equal, or when
one key starts with the other ("NOVARTIS PHARMACEUTICALS" -> Novartis). A name matching two
different companies matches none.

Only the run's stocks are matched (a few hundred names, not 13,000), which keeps collisions
rare. ALIASES covers subsidiaries and old names the rules can't reach. A one-word key that is
also an everyday word ("UNITED", "AMERICAN") matches only exactly.
"""

import re
from collections import defaultdict
from collections.abc import Mapping

from advisor.company_names import search_name
from advisor.news.mapping import COMMON_WORDS

# A subsidiary named with its parent: the parent is the company.
PARENT = (
    re.compile(r",?\s+an?\s+(?:wholly[- ]owned\s+)?subsidiary\s+of\s+(.+)$", re.IGNORECASE),
    re.compile(r",?\s+an?\s+(.+?)\s+company$", re.IGNORECASE),
    re.compile(r"^\S+\s+SUB\s+(.+)$"),  # FDA's "MSD SUB MERCK"
)
PARENTHETICAL = re.compile(r"\([^()]*\)")
ABBREVIATIONS = {
    "PHARM": "PHARMACEUTICALS", "PHARMS": "PHARMACEUTICALS", "PHARMACEUTICAL": "PHARMACEUTICALS",
    "THERAP": "THERAPEUTICS", "HLTHCARE": "HEALTHCARE", "BIOSCI": "BIOSCIENCES",
    "ONCOL": "ONCOLOGY", "LAB": "LABORATORIES", "LABS": "LABORATORIES", "INDS": "INDUSTRIES",
    "INTL": "INTERNATIONAL",
}
LEGAL = frozenset({
    "INC", "INCORPORATED", "CORP", "CORPORATION", "CO", "COMPANY", "COMPANIES", "LTD", "LIMITED",
    "LLC", "LP", "PLC", "SA", "AG", "SE", "NV", "BV", "GMBH", "HOLDINGS", "HOLDING", "GROUP",
    "AB", "ASA", "SPA", "PTE", "PTY", "KGAA", "USA", "US", "AND", "THE",
})
COMMON = frozenset(word.upper() for word in COMMON_WORDS)
# Names the rules can't reach, as keys: the stock they belong to. Used only when that stock is
# in the run. Subsidiaries of companies outside both universes (Genentech -> Roche) aren't here.
ALIASES = {
    "MERCK SHARP DOHME": "MRK",
    "MSD": "MRK",
    "MSD MERCK": "MRK",
    "JANSSEN": "JNJ",
    "ABIOMED": "JNJ",
    "BRISTOL": "BMY",
    "GLAXOSMITHKLINE": "GSK",
    "VIIV HEALTHCARE": "GSK",
    "LOXO ONCOLOGY": "LLY",
    "IMMUNEX": "AMGN",
    "MODERNATX": "MRNA",
    "HOWMEDICA OSTEONICS": "SYK",
    "BAUSCH HEALTH AMERICAS": "BHC",
    "BAXTER": "BAX",  # Baxter Healthcare
    "TEVA": "TEVA",  # Teva Branded Pharmaceutical Products, Teva Pharmaceuticals USA
    "MYLAN": "VTRS",
}


def company_key(name: str) -> str:
    """'Seagen, a wholly owned subsidiary of Pfizer' -> 'PFIZER'; 'JANSSEN PHARMS' -> 'JANSSEN PHARMACEUTICALS'."""
    name = name.strip()
    for pattern in PARENT:
        if match := pattern.search(name):
            name = match.group(1)
            break
    name = PARENTHETICAL.sub(" ", name).split(",")[0].upper()
    name = name.replace("A/S", " ").replace("&", " AND ").replace(".", "").replace("'", "")
    words = [ABBREVIATIONS.get(word, word) for word in re.split(r"[^A-Z0-9]+", name) if word]
    while words and words[-1] in LEGAL:
        words.pop()
    while words and words[0] == "THE":
        words.pop(0)
    return " ".join(words)


def _extends(longer: str, shorter: str) -> bool:
    return longer.startswith(shorter + " ") and shorter not in COMMON


class SponsorMatcher:
    def __init__(self, names: Mapping[str, str], aliases: Mapping[str, str] = ALIASES) -> None:
        """`names`: the run's stocks, symbol -> directory name ("Pfizer, Inc. Common Stock")."""
        self._symbols: dict[str, set[str]] = defaultdict(set)
        for symbol, directory_name in names.items():
            if key := company_key(search_name(directory_name)):
                self._symbols[key].add(symbol)
        for alias, symbol in aliases.items():
            if symbol in names:
                self._symbols[company_key(alias)].add(symbol)
        self._by_first_word: dict[str, list[str]] = defaultdict(list)
        for key in self._symbols:
            self._by_first_word[key.split()[0]].append(key)

    def symbols_for(self, name: str) -> set[str]:
        """The run's stocks this company name belongs to; none when unknown or ambiguous."""
        key = company_key(name)
        if not key:
            return set()
        if key in self._symbols:
            return set(self._symbols[key])
        nearby = self._by_first_word.get(key.split()[0], [])
        matches = [k for k in nearby if _extends(key, k) or _extends(k, key)]
        companies = {frozenset(self._symbols[k]) for k in matches}
        return set(next(iter(companies))) if len(companies) == 1 else set()
```

- [ ] **Step 4: Run the tests**

Run: `scripts/in-docker.sh uv run pytest -q tests/unit/test_sponsors.py`
Expected: `35 passed`.

Run: `scripts/in-docker.sh uv run pytest -q`, then `scripts/in-docker.sh uv run ruff check .`
Expected: `741 passed`, then `All checks passed!`.

- [ ] **Step 5: Commit**

```bash
git add pipeline/src/advisor/sponsors.py pipeline/tests/unit/test_sponsors.py
git commit -m "feat: match catalyst sponsors' names to the run's stocks"
```

---

### Task 4: Count drug approvals and recalls from openFDA

**Files:**
- Create: `pipeline/src/advisor/collectors/openfda.py`
- Modify: `pipeline/src/advisor/collectors/registry.py`
- Test: `pipeline/tests/unit/test_openfda.py`, `pipeline/tests/unit/test_registry.py`
- Uses (already committed): `pipeline/tests/fixtures/openfda/drugsfda.json` and `enforcement.json`.
  - These are real 90-day answers, with openFDA's `meta`.
  - The approvals cover six applications from AbbVie, Lilly, Merck, Pfizer and Genentech. Older submissions are trimmed to the original approval.
  - The recalls cover Baxter's, Pfizer's and American Regent's events.

**Interfaces:**
- Consumes:
  - From Task 3: `SponsorMatcher`.
  - `CompanyNames.get(symbol)` (`advisor.company_names`).
  - `get_with_retries` and `check_deadline` (`base.py`).
- Produces:
  - `OpenFda(client, limiter=None, *, names=None)`:
    - `name = "openfda"`, CATALYSTS, not core, DAILY;
    - US, SYMBOLS scope, canary PFE, `canary_requires_records = False`.
  - `DrugEvents` records, only for stocks with a matched event.
  - `OPENFDA_PER_MINUTE = 60`, `APPROVALS_URL` and `RECALLS_URL`.
  - The registry's docstring says the catalyst sources use `names`.

- [ ] **Step 1: Write the failing tests**

`pipeline/tests/unit/test_openfda.py`:

```python
import json
from datetime import UTC, date, datetime

import httpx
import pytest

from advisor.collectors.openfda import APPROVALS_URL, RECALLS_URL, DrugEvents, OpenFda, fda_date
from advisor.company_names import CompanyNames

AS_OF = datetime(2026, 10, 19, 15, 30, tzinfo=UTC)
NAMES = CompanyNames({
    "ABBV": "AbbVie Inc. Common Stock",
    "LLY": "Eli Lilly and Company Common Stock",
    "MRK": "Merck & Company, Inc. Common Stock (new)",
    "PFE": "Pfizer, Inc. Common Stock",
    "BAX": "Baxter International Inc. Common Stock",
    "AIG": "American International Group, Inc. New Common Stock",
    "AAPL": "Apple Inc. - Common Stock",
})
NOT_FOUND = {"error": {"code": "NOT_FOUND", "message": "No matches found!"}}


def answer(fixtures_dir, name: str) -> dict:
    """Real openFDA answers from 2026-10-19 (90 days), trimmed to a few records and the fields used."""
    return json.loads((fixtures_dir / "openfda" / name).read_text(encoding="utf-8"))


def openfda(answers: dict[str, object], asked: list[httpx.Request]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(request)
        body = answers[str(request.url.copy_with(query=None))]
        return httpx.Response(404 if body is NOT_FOUND else 200, json=body)

    return httpx.Client(transport=httpx.MockTransport(handler))


def fetch(fixtures_dir, symbols, *, approvals=None, recalls=None, asked=None) -> list[DrugEvents]:
    answers = {
        APPROVALS_URL: approvals if approvals is not None else answer(fixtures_dir, "drugsfda.json"),
        RECALLS_URL: recalls if recalls is not None else answer(fixtures_dir, "enforcement.json"),
    }
    with openfda(answers, asked if asked is not None else []) as client:
        return OpenFda(client, names=NAMES).fetch(symbols, AS_OF)


def test_approvals_and_recalls_are_counted_for_the_runs_stocks(fixtures_dir):
    events = {e.symbol: e for e in fetch(fixtures_dir, ["ABBV", "LLY", "MRK", "PFE", "BAX", "AIG", "AAPL"])}
    assert set(events) == {"ABBV", "LLY", "MRK", "PFE", "BAX"}  # American Regent isn't AIG
    abbvie, lilly, merck, pfizer, baxter = (events[s] for s in ("ABBV", "LLY", "MRK", "PFE", "BAX"))
    assert (abbvie.original_approvals_90d, abbvie.new_molecules_90d) == (1, 1)
    assert abbvie.latest_approval == date(2026, 9, 25)
    assert (lilly.original_approvals_90d, lilly.new_molecules_90d, lilly.new_indications_90d) == (1, 1, 2)
    assert lilly.latest_approval == date(2026, 10, 9)
    assert (merck.original_approvals_90d, merck.new_indications_90d) == (0, 1)  # labeling left out
    assert merck.latest_approval == date(2026, 9, 24)
    # Pfizer's application was approved in 1970 and only relabeled now: no approval counted
    assert (pfizer.original_approvals_90d, pfizer.latest_approval) == (0, None)
    assert (pfizer.recalls_90d, pfizer.class1_recalls_90d, pfizer.latest_recall) == (1, 0, date(2026, 9, 23))
    # Baxter: two Class I events, and one Class II event listed as three products
    assert (baxter.recalls_90d, baxter.class1_recalls_90d) == (3, 2)
    assert baxter.latest_recall == date(2026, 9, 16)
    assert abbvie.data_updated == date(2026, 10, 16)
    assert abbvie.as_of == date(2026, 10, 19)


def test_both_searches_cover_the_last_ninety_days_in_one_page_each(fixtures_dir):
    asked: list[httpx.Request] = []
    fetch(fixtures_dir, ["PFE"], asked=asked)
    searches = [request.url.params["search"] for request in asked]
    assert searches == [
        "submissions.submission_status_date:[20260721 TO 20261019] AND submissions.submission_status:AP"
        " AND (application_number:NDA* application_number:BLA*)",
        "report_date:[20260721 TO 20261019]",
    ]
    assert {request.url.params["limit"] for request in asked} == {"1000"}


def test_a_window_with_nothing_answers_404_and_means_no_events(fixtures_dir):
    assert fetch(fixtures_dir, ["PFE", "BAX"], approvals=NOT_FOUND, recalls=NOT_FOUND) == []


def test_a_bad_request_fails_the_fetch(fixtures_dir):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"code": "BAD_REQUEST", "message": "Invalid parameter"}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client, pytest.raises(httpx.HTTPStatusError):
        OpenFda(client, names=NAMES).fetch(["PFE"], AS_OF)


def test_more_than_a_page_is_read_page_by_page(fixtures_dir):
    page = answer(fixtures_dir, "enforcement.json")
    skips: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url.copy_with(query=None)) == APPROVALS_URL:
            return httpx.Response(404, json=NOT_FOUND)
        skips.append(request.url.params["skip"])
        rows = page["results"] if request.url.params["skip"] == "0" else page["results"][:2]
        meta = {**page["meta"], "results": {"total": len(page["results"]) + 2}}
        return httpx.Response(200, json={"meta": meta, "results": rows})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        OpenFda(client, names=NAMES).fetch(["PFE"], AS_OF)
    assert skips == ["0", str(len(page["results"]))]


def test_fda_dates():
    assert fda_date("20260925") == date(2026, 9, 25)
    assert fda_date("") is None and fda_date(None) is None
```

In `pipeline/tests/unit/test_registry.py`, replace:

```python
    "kraken_ohlc": (False, Scope.SYMBOLS, True, NONE),
```

with:

```python
    "kraken_ohlc": (False, Scope.SYMBOLS, True, NONE),
    "openfda": (False, Scope.SYMBOLS, False, US),
```

- [ ] **Step 2: Run them and see them fail**

Run: `scripts/in-docker.sh uv run pytest -q tests/unit/test_openfda.py tests/unit/test_registry.py`
Expected: `1 error during collection`: `ModuleNotFoundError: No module named 'advisor.collectors.openfda'`.

- [ ] **Step 3: Write the collector**

`pipeline/src/advisor/collectors/openfda.py`:

```python
"""Drug approvals and recalls per stock from openFDA (source 48).

openFDA can't be asked about a company; its records name sponsors and recalling firms in free
text. So each fetch makes two market-wide requests over the last WINDOW_DAYS:
- NDA and BLA applications with an approval in the window;
- drug recalls reported in the window.

The names are then matched to the run's stocks (`advisor.sponsors`). openFDA refreshes both
data sets about weekly.

Approvals counted for a stock:
- an original approval (a new drug, formulation or biologic);
- a new molecular entity (an original "TYPE 1" NDA, or an original BLA);
- a new indication (an "EFFICACY" supplement).
Labeling and manufacturing supplements are left out.

openFDA matches array fields independently. An application approved years ago with a recent
supplement matches the query, so every submission is checked here again.

A recall is one event (`event_id`) however many products it lists. An empty window answers HTTP
404 with error code NOT_FOUND.

The data is public domain (CC0). Without a key, openFDA allows 1,000 requests a day per IP.
"""

from collections import defaultdict
from collections.abc import Iterator, Mapping, Sequence
from datetime import date, datetime, timedelta
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict

from advisor.collectors.base import (
    Cadence,
    Category,
    RateLimiter,
    Scope,
    check_deadline,
    get_with_retries,
)
from advisor.company_names import CompanyNames
from advisor.models import ET, AssetType, Market
from advisor.sponsors import SponsorMatcher

APPROVALS_URL = "https://api.fda.gov/drug/drugsfda.json"
RECALLS_URL = "https://api.fda.gov/drug/enforcement.json"
WINDOW_DAYS = 90
PAGE = 1000  # openFDA's largest page
OPENFDA_PER_MINUTE = 60


class DrugEvents(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    as_of: date  # ET date of the run
    original_approvals_90d: int = 0
    new_molecules_90d: int = 0
    new_indications_90d: int = 0
    latest_approval: date | None = None
    recalls_90d: int = 0  # distinct recall events
    class1_recalls_90d: int = 0  # the most serious class
    latest_recall: date | None = None
    data_updated: date | None = None  # openFDA's last refresh of the approvals data


def fda_date(text: str | None) -> date | None:
    """openFDA's YYYYMMDD dates."""
    try:
        return datetime.strptime(text or "", "%Y%m%d").date()
    except ValueError:
        return None


def _results(client: httpx.Client, url: str, search: str, limiter: RateLimiter | None) -> tuple[list[dict], dict]:
    """Every result of a search, page by page, and the first page's `meta`; none when nothing matches."""
    results: list[dict] = []
    meta: dict = {}
    skip = 0
    while True:
        check_deadline()
        try:
            response = get_with_retries(
                client, url, params={"search": search, "limit": PAGE, "skip": skip}, limiter=limiter
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404 and "NOT_FOUND" in exc.response.text:
                return results, meta
            raise
        payload = response.json()
        meta = meta or payload.get("meta") or {}
        page = payload.get("results") or []
        results.extend(page)
        skip += len(page)
        total = ((payload.get("meta") or {}).get("results") or {}).get("total", 0)
        if not page or skip >= total:
            return results, meta


def window(as_of: datetime) -> tuple[date, date]:
    today = as_of.astimezone(ET).date()
    return today - timedelta(days=WINDOW_DAYS), today


def approvals(applications: Sequence[Mapping[str, Any]], start: date, end: date) -> Iterator[tuple[str, str, date]]:
    """(sponsor, kind, date) for each counted approval in the window; kind is "original",
    "new_molecule" (also original) or "new_indication"."""
    for application in applications:
        sponsor = application.get("sponsor_name") or ""
        biologic = str(application.get("application_number", "")).startswith("BLA")
        for submission in application.get("submissions") or []:
            day = fda_date(submission.get("submission_status_date"))
            if submission.get("submission_status") != "AP" or day is None or not start <= day <= end:
                continue
            kind = submission.get("submission_type")
            category = submission.get("submission_class_code")
            if kind == "ORIG":
                yield sponsor, "original", day
                if biologic or category == "TYPE 1":
                    yield sponsor, "new_molecule", day
            elif kind == "SUPPL" and category == "EFFICACY":
                yield sponsor, "new_indication", day


def drug_events(
    matcher: SponsorMatcher,
    applications: Sequence[Mapping[str, Any]],
    recalls: Sequence[Mapping[str, Any]],
    as_of: datetime,
    data_updated: date | None,
) -> list[DrugEvents]:
    start, end = window(as_of)
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    latest_approval: dict[str, date] = {}
    for sponsor, kind, day in approvals(applications, start, end):
        for symbol in matcher.symbols_for(sponsor):
            counts[symbol][kind] += 1
            latest_approval[symbol] = max(day, latest_approval.get(symbol, day))
    events: dict[str, set[str]] = defaultdict(set)
    serious: dict[str, set[str]] = defaultdict(set)
    latest_recall: dict[str, date] = {}
    for recall in recalls:
        day = fda_date(recall.get("report_date"))
        if day is None or not start <= day <= end:
            continue
        for symbol in matcher.symbols_for(recall.get("recalling_firm") or ""):
            event = str(recall.get("event_id") or recall.get("recall_number"))
            events[symbol].add(event)
            if recall.get("classification") == "Class I":
                serious[symbol].add(event)
            latest_recall[symbol] = max(day, latest_recall.get(symbol, day))
    return [
        DrugEvents(
            symbol=symbol,
            as_of=end,
            original_approvals_90d=counts[symbol]["original"],
            new_molecules_90d=counts[symbol]["new_molecule"],
            new_indications_90d=counts[symbol]["new_indication"],
            latest_approval=latest_approval.get(symbol),
            recalls_90d=len(events[symbol]),
            class1_recalls_90d=len(serious[symbol]),
            latest_recall=latest_recall.get(symbol),
            data_updated=data_updated,
        )
        for symbol in sorted(set(latest_approval) | set(latest_recall))
    ]


class OpenFda:
    name = "openfda"
    category = Category.CATALYSTS
    core = False
    best_effort = False
    cadence = Cadence.DAILY
    asset_types = frozenset({AssetType.STOCK})
    markets = frozenset({Market.US})
    record_type = DrugEvents
    freshness = timedelta(days=10)
    scope = Scope.SYMBOLS
    canary = ("PFE",)
    canary_requires_records = False  # the health check loads no names, so nothing matches
    max_symbols = None

    def __init__(
        self,
        client: httpx.Client,
        limiter: RateLimiter | None = None,
        *,
        names: CompanyNames | None = None,
    ) -> None:
        self._client = client
        self._limiter = limiter
        self._names = names or CompanyNames()

    def fetch(self, symbols: Sequence[str], as_of: datetime) -> list[DrugEvents]:
        start, end = window(as_of)
        span = f"[{start:%Y%m%d} TO {end:%Y%m%d}]"
        applications, meta = _results(
            self._client,
            APPROVALS_URL,
            f"submissions.submission_status_date:{span} AND submissions.submission_status:AP"
            " AND (application_number:NDA* application_number:BLA*)",
            self._limiter,
        )
        recalls, _ = _results(self._client, RECALLS_URL, f"report_date:{span}", self._limiter)
        known = {symbol: name for symbol in symbols if (name := self._names.get(symbol))}
        updated = meta.get("last_updated")
        return drug_events(
            SponsorMatcher(known),
            applications,
            recalls,
            as_of,
            date.fromisoformat(updated) if updated else None,
        )
```

- [ ] **Step 4: Register it**

In `pipeline/src/advisor/collectors/registry.py`, replace:

```python
from advisor.collectors.openfigi import OPENFIGI_PER_MINUTE, FigiBook
```

with:

```python
from advisor.collectors.openfda import OPENFDA_PER_MINUTE, OpenFda
from advisor.collectors.openfigi import OPENFIGI_PER_MINUTE, FigiBook
```

In `pipeline/src/advisor/collectors/registry.py`, replace:

```python
    """`names` is filled by the run once the universes are loaded; Google News queries by them."""
```

with:

```python
    """`names` is filled by the run once the universes are loaded.

    Google News queries by them, and the catalyst sources match sponsors' names to them.
    """
```

In `pipeline/src/advisor/collectors/registry.py`, replace:

```python
        KrakenOhlc(client, RateLimiter(per_minute=KRAKEN_PER_MINUTE, burst=1)),
```

with:

```python
        KrakenOhlc(client, RateLimiter(per_minute=KRAKEN_PER_MINUTE, burst=1)),
        OpenFda(client, RateLimiter(per_minute=OPENFDA_PER_MINUTE, burst=2), names=names),
```

- [ ] **Step 5: Run the tests**

Run: `scripts/in-docker.sh uv run pytest -q tests/unit/test_openfda.py tests/unit/test_registry.py`
Expected: `9 passed`.

Run: `scripts/in-docker.sh uv run pytest -q`, then `scripts/in-docker.sh uv run ruff check .`
Expected: `747 passed`, then `All checks passed!`.

- [ ] **Step 6: Commit**

```bash
git add pipeline/src/advisor/collectors/openfda.py pipeline/src/advisor/collectors/registry.py pipeline/tests/unit/test_openfda.py pipeline/tests/unit/test_registry.py
git commit -m "feat: count drug approvals and recalls from openFDA"
```

---

### Task 5: Count clinical-trial activity from ClinicalTrials.gov

**Files:**
- Create: `pipeline/src/advisor/collectors/clinical_trials.py`
- Modify: `pipeline/src/advisor/collectors/registry.py`
- Test: `pipeline/tests/unit/test_clinical_trials.py`, `pipeline/tests/unit/test_registry.py`
- Uses (already committed): `pipeline/tests/fixtures/clinical_trials/results.json`, `stopped.json` and `completing.json`. These are the three queries' real answers, trimmed to Lilly's (one of them by its DICE subsidiary), Pfizer's, ModernaTX's, Novartis's, Roche's and Boehringer's trials.

**Interfaces:**
- Consumes:
  - From Task 3: `SponsorMatcher`.
  - `CompanyNames`.
  - `get_with_retries` and `check_deadline` (`base.py`).
- Produces:
  - `ClinicalTrials(client, book, limiter=None, *, names=None)`:
    - `name = "clinical_trials"`, CATALYSTS, not core, WEEKLY;
    - US and TSX, SYMBOLS scope, canary PFE, `canary_requires_records = False`.
  - `StatusBook(path).update(trials, today) -> {nct_id: day the stop was found}`. The book is kept at `cache_dir/clinical-trials/statuses.json`.
  - `TrialActivity` records, and `Trial`, `trial_date(text)` and `CLINICAL_TRIALS_PER_MINUTE = 50`.

- [ ] **Step 1: Write the failing tests**

`pipeline/tests/unit/test_clinical_trials.py`:

```python
import json
from datetime import UTC, date, datetime

import httpx

from advisor.collectors.clinical_trials import (
    ClinicalTrials,
    StatusBook,
    Trial,
    trial_date,
)
from advisor.company_names import CompanyNames

AS_OF = datetime(2026, 10, 19, 15, 30, tzinfo=UTC)
NAMES = CompanyNames({
    "PFE": "Pfizer, Inc. Common Stock",
    "LLY": "Eli Lilly and Company Common Stock",
    "MRNA": "Moderna, Inc. - Common Stock",
    "NVS": "Novartis AG Common Stock",
    "AAPL": "Apple Inc. - Common Stock",
})


def answers(fixtures_dir) -> dict[str, dict]:
    """Real answers of 2026-10-19 to the three queries, trimmed to a few trials each."""
    base = fixtures_dir / "clinical_trials"
    return {name: json.loads((base / f"{name}.json").read_text(encoding="utf-8"))
            for name in ("results", "stopped", "completing")}


def which(request: httpx.Request) -> str:
    advanced = request.url.params["filter.advanced"]
    if "ResultsFirstPostDate" in advanced:
        return "results"
    return "stopped" if "LastUpdatePostDate" in advanced else "completing"


def clinicaltrials(pages: dict[str, dict], asked: list[httpx.Request]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(request)
        return httpx.Response(200, json=pages[which(request)])

    return httpx.Client(transport=httpx.MockTransport(handler))


def fetch(fixtures_dir, tmp_path, symbols, asked=None, pages=None):
    with clinicaltrials(pages or answers(fixtures_dir), asked if asked is not None else []) as client:
        collector = ClinicalTrials(client, StatusBook(tmp_path / "statuses.json"), names=NAMES)
        return {a.symbol: a for a in collector.fetch(symbols, AS_OF)}


def test_trial_dates_may_give_only_the_month():
    assert trial_date("2026-10-21") == (date(2026, 10, 21), True)
    assert trial_date("2026-11") == (date(2026, 11, 30), False)
    assert trial_date(None) == (None, True)
    assert trial_date("soon") == (None, True)


def test_activity_from_real_answers(fixtures_dir, tmp_path):
    activity = fetch(fixtures_dir, tmp_path, ["PFE", "LLY", "MRNA", "NVS", "AAPL"])
    assert set(activity) == {"PFE", "LLY", "MRNA"}
    pfizer, lilly, moderna = activity["PFE"], activity["LLY"], activity["MRNA"]
    assert (pfizer.results_posted_30d, pfizer.completions_90d, pfizer.phase3_completions_90d) == (2, 4, 3)
    assert (pfizer.next_completion, pfizer.next_completion_exact) == (date(2026, 10, 30), True)
    assert lilly.results_posted_30d == 3  # one by DICE, "a wholly owned subsidiary of Eli Lilly"
    assert (lilly.next_completion, lilly.next_completion_exact) == (date(2026, 11, 30), False)
    assert moderna.results_posted_30d == 1  # the sponsor is "ModernaTX, Inc."
    # Pfizer's and Novartis's stopped trials were never seen active: not counted as stops
    assert pfizer.stopped_10d == 0
    assert pfizer.as_of == date(2026, 10, 19)


def test_a_stop_counts_when_the_book_saw_the_trial_active(fixtures_dir, tmp_path):
    (tmp_path / "statuses.json").write_text(json.dumps({
        "NCT05070845": {"status": "ACTIVE_NOT_RECRUITING", "seen": "2026-10-12", "stopped": None},
    }))
    assert fetch(fixtures_dir, tmp_path, ["PFE"])["PFE"].stopped_10d == 1
    # The health check may find it first: the stop keeps the day it was found
    assert fetch(fixtures_dir, tmp_path, ["PFE"])["PFE"].stopped_10d == 1
    book = json.loads((tmp_path / "statuses.json").read_text())
    assert book["NCT05070845"] == {"status": "TERMINATED", "seen": "2026-10-19", "stopped": "2026-10-19"}


def test_stops_found_more_than_ten_days_ago_no_longer_count(tmp_path):
    book = StatusBook(tmp_path / "statuses.json")
    active = Trial("NCT1", "Pfizer", "RECRUITING", ("PHASE3",), date(2026, 11, 1), True)
    stopped = Trial("NCT1", "Pfizer", "TERMINATED", ("PHASE3",), date(2026, 11, 1), True)
    book.update([active], date(2026, 9, 1))
    assert book.update([stopped], date(2026, 9, 2)) == {"NCT1": date(2026, 9, 2)}
    assert book.update([stopped], date(2026, 9, 20)) == {"NCT1": date(2026, 9, 2)}


def test_a_damaged_book_starts_over(fixtures_dir, tmp_path):
    (tmp_path / "statuses.json").write_text("cut short {")
    assert fetch(fixtures_dir, tmp_path, ["PFE"])["PFE"].stopped_10d == 0
    assert "NCT05070845" in json.loads((tmp_path / "statuses.json").read_text())


def test_three_market_wide_queries_of_industry_trials(fixtures_dir, tmp_path):
    asked: list[httpx.Request] = []
    fetch(fixtures_dir, tmp_path, ["PFE"], asked)
    queries = [(r.url.params["filter.advanced"], r.url.params.get("filter.overallStatus")) for r in asked]
    assert queries == [
        ("AREA[LeadSponsorClass]INDUSTRY AND AREA[ResultsFirstPostDate]RANGE[2026-09-19,MAX]", None),
        ("AREA[LeadSponsorClass]INDUSTRY AND AREA[LastUpdatePostDate]RANGE[2026-10-09,MAX]",
         "TERMINATED|SUSPENDED|WITHDRAWN"),
        ("AREA[LeadSponsorClass]INDUSTRY AND AREA[PrimaryCompletionDate]RANGE[2026-10-19,2027-01-17]"
         " AND AREA[Phase](PHASE2 OR PHASE3)",
         "RECRUITING|ACTIVE_NOT_RECRUITING|ENROLLING_BY_INVITATION|NOT_YET_RECRUITING"),
    ]
    assert {r.url.params["pageSize"] for r in asked} == {"1000"}


def test_later_pages_follow_the_page_token(fixtures_dir, tmp_path):
    real = answers(fixtures_dir)
    asked: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(request)
        name = which(request)
        if name == "results" and "pageToken" not in request.url.params:
            return httpx.Response(200, json={"studies": real["results"]["studies"][:3], "nextPageToken": "abc"})
        if name == "results":
            return httpx.Response(200, json={"studies": real["results"]["studies"][3:]})
        return httpx.Response(200, json=real[name])

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        collector = ClinicalTrials(client, StatusBook(tmp_path / "statuses.json"), names=NAMES)
        activity = {a.symbol: a for a in collector.fetch(["PFE", "LLY"], AS_OF)}
    assert [r.url.params.get("pageToken") for r in asked[:2]] == [None, "abc"]
    assert activity["LLY"].results_posted_30d == 3
```

In `pipeline/tests/unit/test_registry.py`, replace:

```python
    "openfda": (False, Scope.SYMBOLS, False, US),
```

with:

```python
    "openfda": (False, Scope.SYMBOLS, False, US),
    "clinical_trials": (False, Scope.SYMBOLS, False, BOTH),
```

- [ ] **Step 2: Run them and see them fail**

Run: `scripts/in-docker.sh uv run pytest -q tests/unit/test_clinical_trials.py tests/unit/test_registry.py`
Expected: `1 error during collection`: `ModuleNotFoundError: No module named 'advisor.collectors.clinical_trials'`.

- [ ] **Step 3: Write the collector**

`pipeline/src/advisor/collectors/clinical_trials.py`:

```python
"""Clinical-trial activity per stock from ClinicalTrials.gov's API (source 49).

Asking per company would take hundreds of requests, and search misses names such as
"ModernaTX, Inc.". So each fetch makes three market-wide queries over industry-sponsored trials,
about one request each:
- results posted in the last RESULTS_DAYS;
- stopped (terminated, suspended, withdrawn) and updated in the last STOPPED_DAYS;
- phase 2 or 3, still active, with the primary completion due in the next COMPLETION_DAYS. A
  readout is near.

Lead sponsors are matched to the run's stocks (`advisor.sponsors`).

The API holds only a trial's current status. "Stopped and recently updated" includes trials
stopped long ago that only had results posted. So a status book on disk remembers each active
trial's status, and a stop counts only when the book saw that trial active. The detection date
is kept, so the daily health check finding a stop first doesn't hide it from the weekly run.
Trials stopped before they neared completion aren't in the book, and aren't counted.

Dates are "YYYY-MM-DD" or month-only "YYYY-MM". A month-only completion date counts as the
month's last day, and the record says it isn't exact.

robots.txt disallows /api/, but the API is documented for programs; the owner accepted it. Its
`Crawl-delay: 1` is honoured: requests are at least 1.2 s apart.
"""

import calendar
import json
import os
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict

from advisor.collectors.base import (
    Cadence,
    Category,
    RateLimiter,
    Scope,
    check_deadline,
    get_with_retries,
)
from advisor.company_names import CompanyNames
from advisor.models import ET, AssetType, Market
from advisor.sponsors import SponsorMatcher

STUDIES_URL = "https://clinicaltrials.gov/api/v2/studies"
CLINICAL_TRIALS_PER_MINUTE = 50  # Crawl-delay: 1
RESULTS_DAYS = 30
STOPPED_DAYS = 10
COMPLETION_DAYS = 90
FORGET_DAYS = 400  # book entries not seen for this long are dropped
FIELDS = "NCTId,OverallStatus,Phase,PrimaryCompletionDate,LastUpdatePostDate,ResultsFirstPostDate,LeadSponsorName"
INDUSTRY = "AREA[LeadSponsorClass]INDUSTRY"
ACTIVE = ("RECRUITING", "ACTIVE_NOT_RECRUITING", "ENROLLING_BY_INVITATION", "NOT_YET_RECRUITING")
STOPPED = ("TERMINATED", "SUSPENDED", "WITHDRAWN")


class TrialActivity(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    as_of: date  # ET date of the run
    results_posted_30d: int = 0
    stopped_10d: int = 0  # trials seen active that were found stopped in the last 10 days
    completions_90d: int = 0  # active phase 2/3 trials with primary completion due in 90 days
    phase3_completions_90d: int = 0
    next_completion: date | None = None
    next_completion_exact: bool = True  # False: only the month is known (the date is its last day)


@dataclass(frozen=True)
class Trial:
    nct_id: str
    sponsor: str
    status: str
    phases: tuple[str, ...]
    primary_completion: date | None
    completion_exact: bool


def trial_date(text: str | None) -> tuple[date | None, bool]:
    """('2026-10-21' -> that day, exact) or ('2026-10' -> the month's last day, not exact)."""
    if not text:
        return None, True
    try:
        if len(text) == 7:
            year, month = int(text[:4]), int(text[5:])
            return date(year, month, calendar.monthrange(year, month)[1]), False
        return date.fromisoformat(text), True
    except ValueError:
        return None, True


def trial(study: Mapping[str, Any]) -> Trial:
    protocol = study.get("protocolSection") or {}
    status = protocol.get("statusModule") or {}
    day, exact = trial_date((status.get("primaryCompletionDateStruct") or {}).get("date"))
    return Trial(
        nct_id=(protocol.get("identificationModule") or {}).get("nctId", ""),
        sponsor=((protocol.get("sponsorCollaboratorsModule") or {}).get("leadSponsor") or {}).get("name", ""),
        status=status.get("overallStatus", ""),
        phases=tuple((protocol.get("designModule") or {}).get("phases") or ()),
        primary_completion=day,
        completion_exact=exact,
    )


class StatusBook:
    """The last status seen per trial, and when each stop was found, in a JSON file."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def _load(self) -> dict[str, dict]:
        try:
            book = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return book if isinstance(book, dict) else {}

    def _save(self, book: dict[str, dict]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(".tmp")
        temporary.write_text(json.dumps(book, sort_keys=True), encoding="utf-8")
        os.replace(temporary, self._path)

    def update(self, trials: Sequence[Trial], today: date) -> dict[str, date]:
        """Record each trial's status; return every trial found stopped after being seen active,
        with the day the stop was found."""
        book = self._load()
        for t in trials:
            entry = book.get(t.nct_id) if isinstance(book.get(t.nct_id), dict) else None
            stopped = entry.get("stopped") if entry else None
            if t.status in STOPPED and entry and entry.get("status") in ACTIVE:
                stopped = today.isoformat()
            book[t.nct_id] = {"status": t.status, "seen": today.isoformat(), "stopped": stopped}
        forget = (today - timedelta(days=FORGET_DAYS)).isoformat()
        book = {k: v for k, v in book.items() if isinstance(v, dict) and v.get("seen", "") >= forget}
        self._save(book)
        found: dict[str, date] = {}
        for nct_id, entry in book.items():
            try:
                if entry.get("stopped"):
                    found[nct_id] = date.fromisoformat(entry["stopped"])
            except ValueError:
                continue
        return found


def trial_activity(
    matcher: SponsorMatcher,
    results: Sequence[Trial],
    stopped: Sequence[Trial],
    completing: Sequence[Trial],
    stops_found: Mapping[str, date],
    today: date,
) -> list[TrialActivity]:
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    nearest: dict[str, tuple[date, bool]] = {}
    for t in results:
        for symbol in matcher.symbols_for(t.sponsor):
            counts[symbol]["results"] += 1
    recent = today - timedelta(days=STOPPED_DAYS)
    for t in stopped:
        found = stops_found.get(t.nct_id)
        if found and found > recent:
            for symbol in matcher.symbols_for(t.sponsor):
                counts[symbol]["stopped"] += 1
    for t in completing:
        for symbol in matcher.symbols_for(t.sponsor):
            counts[symbol]["completions"] += 1
            if "PHASE3" in t.phases:
                counts[symbol]["phase3"] += 1
            if t.primary_completion and t.primary_completion >= today:
                current = nearest.get(symbol)
                if current is None or t.primary_completion < current[0]:
                    nearest[symbol] = (t.primary_completion, t.completion_exact)
    return [
        TrialActivity(
            symbol=symbol,
            as_of=today,
            results_posted_30d=c["results"],
            stopped_10d=c["stopped"],
            completions_90d=c["completions"],
            phase3_completions_90d=c["phase3"],
            next_completion=nearest[symbol][0] if symbol in nearest else None,
            next_completion_exact=nearest[symbol][1] if symbol in nearest else True,
        )
        for symbol, c in sorted(counts.items())
        if any(c.values())
    ]


class ClinicalTrials:
    name = "clinical_trials"
    category = Category.CATALYSTS
    core = False
    best_effort = False
    cadence = Cadence.WEEKLY
    asset_types = frozenset({AssetType.STOCK})
    markets = frozenset({Market.US, Market.TSX})
    record_type = TrialActivity
    freshness = timedelta(days=14)
    scope = Scope.SYMBOLS
    canary = ("PFE",)
    canary_requires_records = False  # the health check loads no names, so nothing matches
    max_symbols = None

    def __init__(
        self,
        client: httpx.Client,
        book: StatusBook,
        limiter: RateLimiter | None = None,
        *,
        names: CompanyNames | None = None,
    ) -> None:
        self._client = client
        self._book = book
        self._limiter = limiter
        self._names = names or CompanyNames()

    def _trials(self, advanced: str, statuses: Sequence[str] = ()) -> list[Trial]:
        params: dict[str, Any] = {"filter.advanced": advanced, "fields": FIELDS, "pageSize": 1000}
        if statuses:
            params["filter.overallStatus"] = "|".join(statuses)
        trials: list[Trial] = []
        while True:
            check_deadline()
            payload = get_with_retries(self._client, STUDIES_URL, params=params, limiter=self._limiter).json()
            trials.extend(trial(study) for study in payload.get("studies") or [])
            token = payload.get("nextPageToken")
            if not token:
                return trials
            params["pageToken"] = token

    def fetch(self, symbols: Sequence[str], as_of: datetime) -> list[TrialActivity]:
        today = as_of.astimezone(ET).date()

        def since(days: int) -> str:
            return f"RANGE[{today - timedelta(days=days)},MAX]"

        results = self._trials(f"{INDUSTRY} AND AREA[ResultsFirstPostDate]{since(RESULTS_DAYS)}")
        stopped = self._trials(f"{INDUSTRY} AND AREA[LastUpdatePostDate]{since(STOPPED_DAYS)}", STOPPED)
        due = f"RANGE[{today},{today + timedelta(days=COMPLETION_DAYS)}]"
        completing = self._trials(
            f"{INDUSTRY} AND AREA[PrimaryCompletionDate]{due} AND AREA[Phase](PHASE2 OR PHASE3)", ACTIVE
        )
        stops_found = self._book.update([*completing, *stopped], today)
        known = {symbol: name for symbol in symbols if (name := self._names.get(symbol))}
        return trial_activity(SponsorMatcher(known), results, stopped, completing, stops_found, today)
```

- [ ] **Step 4: Register it**

In `pipeline/src/advisor/collectors/registry.py`, replace:

```python
from advisor.collectors.cboe_put_call import CBOE_PER_MINUTE, CboePutCall
```

with:

```python
from advisor.collectors.cboe_put_call import CBOE_PER_MINUTE, CboePutCall
from advisor.collectors.clinical_trials import (
    CLINICAL_TRIALS_PER_MINUTE,
    ClinicalTrials,
    StatusBook,
)
```

In `pipeline/src/advisor/collectors/registry.py`, replace:

```python
        OpenFda(client, RateLimiter(per_minute=OPENFDA_PER_MINUTE, burst=2), names=names),
```

with:

```python
        OpenFda(client, RateLimiter(per_minute=OPENFDA_PER_MINUTE, burst=2), names=names),
        ClinicalTrials(
            client,
            StatusBook(settings.cache_dir / "clinical-trials" / "statuses.json"),
            RateLimiter(per_minute=CLINICAL_TRIALS_PER_MINUTE),
            names=names,
        ),
```

- [ ] **Step 5: Run the tests**

Run: `scripts/in-docker.sh uv run pytest -q tests/unit/test_clinical_trials.py tests/unit/test_registry.py`
Expected: `10 passed`.

Run: `scripts/in-docker.sh uv run pytest -q`, then `scripts/in-docker.sh uv run ruff check .`
Expected: `754 passed`, then `All checks passed!`.

- [ ] **Step 6: Check all four sources live**

This step makes real requests:
- about 18 to Yahoo;
- 6 to Cboe's CDN;
- 2 to openFDA;
- 3 to ClinicalTrials.gov.

Write a throwaway script, which isn't committed. It needs the NASDAQ Trader directories for company names. Download them into a throwaway folder (2 requests):

```bash
mkdir -p .live-check
curl -s -o .live-check/nasdaqlisted.txt https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt
curl -s -o .live-check/otherlisted.txt https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt
```

`pipeline/check_2h.py` (throwaway):

```python
"""Throwaway: fetch Plan 2h's four sources live and print what they return."""

import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

from advisor.collectors.base import USER_AGENT, RateLimiter
from advisor.collectors.cboe_put_call import CboePutCall
from advisor.collectors.clinical_trials import ClinicalTrials, StatusBook
from advisor.collectors.openfda import OpenFda
from advisor.collectors.yahoo import YAHOO_PER_MINUTE
from advisor.collectors.yfinance_options import YFinanceOptions
from advisor.company_names import CompanyNames

directory = {}
for listing in ("nasdaqlisted.txt", "otherlisted.txt"):
    for line in Path(".live-check", listing).read_text(encoding="utf-8").splitlines()[1:]:
        fields = line.split("|")
        if len(fields) > 2:
            directory[fields[0]] = fields[1]
STOCKS = ["PFE", "LLY", "MRK", "ABBV", "JNJ", "BMY", "AMGN", "GILD", "MRNA", "NVS", "AZN", "GSK",
          "SNY", "TAK", "REGN", "VRTX", "BIIB", "INCY", "BAX", "TEVA", "AAPL", "MSFT", "NVDA", "JPM"]
names = CompanyNames({s: directory[s] for s in STOCKS})
now = datetime.now(UTC)
with httpx.Client(timeout=30, headers={"User-Agent": USER_AGENT}) as client:
    sources = [
        (YFinanceOptions(limiter=RateLimiter(per_minute=YAHOO_PER_MINUTE, burst=2)),
         ["AAPL", "MSFT", "BRK.B", "SPY", "NVDA", "AACG"]),
        (CboePutCall(client), []),
        (OpenFda(client, names=names), STOCKS),
        (ClinicalTrials(client, StatusBook(Path(".live-check/statuses.json")),
                        RateLimiter(per_minute=50), names=names), STOCKS),
    ]
    for collector, symbols in sources:
        started = time.monotonic()
        records = collector.fetch(symbols, now)
        print(f"{collector.name}: {len(records)} records in {time.monotonic() - started:.1f} s")
        for record in records[:3]:
            print("   ", record.model_dump(exclude_none=True, mode="json"))
```

Run: `scripts/in-docker.sh uv run python check_2h.py`
Expected: about 13 seconds in all. Each source prints one line, then its first three records. The numbers move with the market and the data; on 2026-10-19 at 12:45 ET the lines were:
- `yfinance_options: 5 records in 7.5 s`: AACG has no options, and BRK.B is asked as BRK-B;
- `cboe_put_call: 20 records in 1.3 s`: four ratios for each of the last 5 trading days (today's file isn't posted until the evening);
- `openfda: 15 records in 1.7 s`: ABBV first, with one new molecule approved on 2026-09-25;
- `clinical_trials: 19 records in 3.0 s`: ABBV first, with 11 phase 2/3 trials due to complete.

Then delete the script and its folder: `rm -rf check_2h.py .live-check`.

- [ ] **Step 7: Commit**

```bash
git add pipeline/src/advisor/collectors/clinical_trials.py pipeline/src/advisor/collectors/registry.py pipeline/tests/unit/test_clinical_trials.py pipeline/tests/unit/test_registry.py
git commit -m "feat: count clinical-trial activity from ClinicalTrials.gov"
```

---

### Task 6: Record what Plan 2h built and decided

**Files:**
- Modify: `docs/superpowers/specs/2026-10-09-stock-advisor-design.md`, `docs/superpowers/deferred.md`

**Interfaces:**
- Consumes: what Tasks 1–5 built, and the owner's decisions above.
- Produces:
  - The spec's rows 15, 18, 19 and 48–51 and its decisions list say what Plan 2h built, kept and dropped.
  - `deferred.md` replaces its Plan 2h section with a Plan 2j section for USAspending and the House reports, and tells Plan 3 how to read the new records.

- [ ] **Step 1: Update the spec**

In `docs/superpowers/specs/2026-10-09-stock-advisor-design.md`, replace:

```markdown
| 15 | fundamentals | Canadian short-position report | TSX | weekly | Twice-monthly. Kept only if a keyless file is confirmed (Plan 2h) |
```

with:

```markdown
| 15 | fundamentals | Canadian short-position report | TSX | weekly | Dropped in Plan 2h: CIRO's file sits behind a bot check and its terms ban scraping |
```

In `docs/superpowers/specs/2026-10-09-stock-advisor-design.md`, replace:

```markdown
| 18 | options | Yahoo option chains ⚠ | US | per_run | Implied volatility, per-ticker put/call. Shortlist only |
| 19 | options | CBOE daily put/call ratios | US | daily | Market-wide |
```

with:

```markdown
| 18 | options | Yahoo option chains ⚠ | US | per_run | At-the-money implied volatility a week and a month out, skew, put/call volume and open interest. Top 40 of the shortlist per run |
| 19 | options | Cboe daily put/call ratios ⚠ | US | daily | Market-wide: total, equity, index and ETP. Cboe's terms limit storing copies, so only the ratios are kept |
```

In `docs/superpowers/specs/2026-10-09-stock-advisor-design.md`, replace:

```markdown
| 48 | catalysts | openFDA | US | daily | Drug approvals and recalls |
| 49 | catalysts | ClinicalTrials.gov API | US, TSX | weekly | Trial status for biotech |
| 50 | catalysts | USAspending.gov | US | weekly | Federal contract awards |
| 51 | catalysts | House Clerk periodic transaction reports | US | weekly | Congressional trades |
```

with:

```markdown
| 48 | catalysts | openFDA | US | daily | Drug approvals (originals, new molecules, new indications) and recalls. Sponsor names are matched to stocks |
| 49 | catalysts | ClinicalTrials.gov API | US, TSX | weekly | Results posted, trials stopped, phase 2/3 readouts due. Lead sponsors are matched to stocks |
| 50 | catalysts | USAspending.gov | US | weekly | Federal contract awards (Plan 2j) |
| 51 | catalysts | House Clerk periodic transaction reports | US | weekly | Congressional trades (Plan 2j). The law allows only non-commercial use; never publish them |
```

In `docs/superpowers/specs/2026-10-09-stock-advisor-design.md`, replace:

```markdown
- **Excluded** because they aren't free: X/Twitter, Bloomberg, Reuters, earnings-call transcripts, paid options flow.
```

with:

```markdown
- **Decided in Plan 2h** (owner, 2026-10-19).
  - Dropped: the Canadian short-position report (15). CIRO's file sits behind a bot check, and its terms ban scraping. No other keyless Canadian source exists.
  - Kept on the owner's reading:
    - ClinicalTrials.gov's documented API, although robots.txt disallows `/api/`. Its crawl delay is honoured.
    - Cboe's daily put/call file, keeping only the ratios.
    - The House Clerk's reports, for personal use only.
  - USAspending.gov (50) and the House Clerk's reports (51) moved to Plan 2j.
- **Excluded** because they aren't free: X/Twitter, Bloomberg, Reuters, earnings-call transcripts, paid options flow.
```

In `docs/superpowers/specs/2026-10-09-stock-advisor-design.md`, replace:

```markdown
| US (TSX short positions if source 15 is confirmed) |
```

with:

```markdown
| US |
```

- [ ] **Step 2: Update the deferred list**

In `docs/superpowers/deferred.md`, replace:

```markdown
These are items that the Plan 1, Plan 2a, Plan 2b, Plan 2c, Plan 2d, Plan 2e, Plan 2f and Plan 2g reviews deliberately pushed to later plans.
```

with:

```markdown
These are items that the Plan 1, Plan 2a, Plan 2b, Plan 2c, Plan 2d, Plan 2e, Plan 2f, Plan 2g and Plan 2h reviews deliberately pushed to later plans.
```

In `docs/superpowers/deferred.md`, replace:

```markdown
## Plan 2h: options, catalysts and Canadian short positions

- **Split out of Plan 2e**, which kept macro, crypto and on-chain. Sources: Yahoo option chains (18) and CBOE put/call ratios (19); openFDA (48), ClinicalTrials.gov (49), USAspending.gov (50) and House Clerk periodic transaction reports (51); the Canadian short-position report (15), kept only if a keyless file is confirmed.
- **Catalysts name companies, not tickers:** drug sponsors, trial sponsors and contract recipients need a company-name → symbol map for both markets. Plan 2f built one; reuse `advisor.company_names` and `advisor.news.mapping.TickerMap`.
- **House Clerk reports are PDFs.** Check that electronically filed reports read as text before committing to source 51.

## Plan 2i: social and attention
```

with:

```markdown
## Plan 2i: social and attention
```

In `docs/superpowers/deferred.md`, replace:

```markdown
## Plan 3: model and features
```

with:

```markdown
## Plan 2j: government catalysts

- **Split out of Plan 2h**, which kept options, Cboe, openFDA and ClinicalTrials.gov. The sources are USAspending.gov (50) and the House Clerk's periodic transaction reports (51). Research: `.superpowers/research/plan-2h/government.md`.
- **Match names with `advisor.sponsors.SponsorMatcher`** (Plan 2h), adding aliases for defense primes' units, such as Sikorsky → RTX and Electric Boat → GD. USAspending's own parent-company data is stale; don't use it.
- **USAspending:**
  - `POST /api/v2/search/spending_by_category/recipient/` sums a recipient's awards. `spending_by_transaction` gives single actions.
  - `recipient_search_text` matches substrings: "FORD" also finds Stafford.
  - Award amounts in `spending_by_award` are lifetime totals, so use transaction amounts for recent dollars. They can be negative.
  - Defense awards appear about 90 days late, so a 90-day window misses nearly all of a defense prime's awards. Count awards by when they first appear, or say how complete the window is.
- **House reports:**
  - The yearly index `financial-pdfs/<YEAR>FD.zip` lists filings (`FilingType` P), with one PDF each under `ptr-pdfs/<YEAR>/<DocID>.pdf`.
  - About 88% are filed electronically and read as text. Many are RC4-encrypted with an empty password. Scanned ones (DocIDs starting 8 or 9) are skipped.
  - A stock row carries its ticker in parentheses next to an `[ST]` tag. Accept a ticker only on such a row, because "(RILA)" is an annuity.
  - Decide between a small standard-library PDF reader, which the research proved on 13 reports, and `pypdf` (BSD). `pypdf` needs `cryptography` for AES.
  - Trades are filed 2–6 weeks after they happen.
  - The law bars commercial use. The owner accepted personal use (2026-10-19), so never publish the trades.
  - The Senate's site needs an agreement click-through, so it's out.

## Plan 3: model and features
```

In `docs/superpowers/deferred.md`, replace:

```markdown
- **Data quality:** `adv20` on histories shorter than 20 bars, and clamping `DailyBar` high/low inconsistencies.
```

with:

```markdown
- **Options (Plan 2h) are live only.**
  - `yfinance_options` describes the market at `quote_time`: IV moves during the day, and volume counts the day so far. So compare a run with the same run on other days.
  - Put/call ratios cover the three chains fetched (today's 0DTE chain left out), not every expiry.
  - After-hours answers weren't seen in testing. Check the first evening run for stale IV or zero volume.
- **Cboe put/call** (`cboe_put_call`) covers products listed on Cboe's exchanges, not the whole US market. A day's file appears that evening, and each fetch returns the last 10 days, so store the series for longer windows.
- **Catalyst matches are noisy.**
  - `openfda` and `clinical_trials` match sponsor names to the run's stocks. A sponsor name that starts with a one-word stock name is read as that stock: "Sound Pharmaceuticals" (private) would count for a stock named "Sound", and "Meridian Bioscience" for one named "Meridian".
  - Treat these as weak signals, and add aliases as wrong matches turn up.
  - A stock with no record had no matched event. A stock without a directory name (some holdings) is never matched.
  - openFDA refreshes about weekly.
  - Trial stops count only for trials the status book saw active: phase 2 or 3, nearing completion.
  - A month-only completion date stands for the month's last day.
- **Data quality:** `adv20` on histories shorter than 20 bars, and clamping `DailyBar` high/low inconsistencies.
```

- [ ] **Step 3: Run every test**

Run: `scripts/in-docker.sh uv run pytest -q`, then `scripts/in-docker.sh uv run ruff check .`
Expected: `754 passed`, then `All checks passed!`.

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-10-09-stock-advisor-design.md docs/superpowers/deferred.md
git commit -m "docs: record Plan 2h's sources and decisions, and plan 2j"
```
