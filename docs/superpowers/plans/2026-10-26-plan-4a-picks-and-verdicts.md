# Plan 4a: Picks and Watchlist Verdicts — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Each run turns the model's forecasts into the spec's picks and watchlist verdicts.
- **Picks:** per market, at most 10 Swing and 10 Position, with a risk level, a stop-loss, an exit-by date, the top factors and catalysts.
- **Watchlist verdicts:** Buy / Hold / Avoid for every watched symbol.

Both are written to `picks` and `watchlist_verdicts`, and a market whose backtest failed gets no picks.

**Architecture:**
- **A new package, `advisor.recommend`, with one module per step:**
  - `risk` (spec §6.4);
  - `picks` (§6.1–§6.3 and §6.5);
  - `verdicts` (§6.5 watchlist).

  Each is a pure function over a per-market frame of forecasts and features, so it is testable without a run.
- **Stage 8 in `run.py`** builds that frame from what stage 7 already computed (forecasts, model features, last closes), plus each stock's news sentiment and the run's catalyst records. It then calls the three modules and writes the results. A failure degrades the run per market and never fails it.
- **The universe sheds non-common listings first** (Task 1), so they are never trained on, screened or picked.

**Tech Stack:** Python 3.12, pandas, numpy, LightGBM (`pred_contrib` for top factors), pandas-market-calendars, psycopg; pytest; ruff.

**Spec:** `docs/superpowers/specs/2026-10-09-stock-advisor-design.md` (rev 2):
- §6.1 qualifying, §6.2 hold time, §6.3 stop-loss, §6.4 risk level, §6.5 limits and watchlist verdicts, §6.6 disabling picks;
- §3 Markets (costs);
- §8 (`picks`, `watchlist_verdicts`).

Also read `docs/superpowers/deferred.md` ("Plan 4: recommendations", "Plan 3b known limits", "Plan 3c known limits").

**Owner's decisions this plan relies on:**
- **The order of Plan 4** (2026-10-26):
  - 4a: picks and verdicts (this plan);
  - 4b: the dashboard that shows them;
  - 4c: holding actions, exit-early and grading.
- **The universe drops these** (2026-10-26):
  - US partnership units (LP/MLP: TFSA withholding on US partnership distributions);
  - closed-end funds and BDCs;
  - ETNs, structured trust certificates and named preferred classes.

  Held ones stay priced through the holdings phase.
- **Earlier rules that still apply:**
  - Only usable horizons give P(beat), and a model failure degrades the run (2026-10-26).
  - A stock the model may not score gets no forecast, and therefore no pick or Buy (Plan 3c).

**Prototype findings** (on the NASDAQ Trader and TMX directories saved earlier):

| Pattern | US listings caught (after today's filter) | False hits |
|---|---|---|
| ETN / exchange-traded note | 14 (AMUB, BDCZ, DGP, DJP, FNGD…) | none |
| Structured trust certificates (STRATS, CorTS, PPlus, "Corp Backed Tr Certs") | 9 (GJH…GJT, JBK, KTN, PYT) | none |
| Word "fund" (closed-end funds, BDCs labelled "Closed End Fund", commodity pools) | about 500 | none among the 20 not obviously funds (all commodity pools or venture funds) |
| "Preferred Class/Series", "Perpetual Preferred" | CHSCN and others | a bare "Preferred" would hit PFBC (Preferred Bank common stock), so the pattern needs the class/series word |
| LP units ("L.P.", "LP", "limited partner(ship) interests", "common units") | 32 (ET, EPD, PAA, ARLP…) | — |
| "Shares of beneficial interest" | 133, mostly REITs | not excluded |

TSX: the TMX filter already drops "Fund", "ETF", "Split", "Notes" and similar. Eight non-operating vehicles remain: CEF, PHYS, PSLV, SPPP (Sprott physical trusts), EVT (an investment trust), MIPC ("Income Plus Class"), PBY ("ActivETF") and PIC-A ("Premium Income Corporation").

## Global Constraints

- **Rules are the spec's, with its exact values.**
  - P(beat) ≥ **0.58** and q50 > the market's round-trip cost to qualify.
  - Avoid when P ≤ **0.42** at every usable horizon.
  - Hold time: the qualifying horizon with the best **q50 / (q90 − q10)**.
  - Swing stop: entry − **2 × ATR(14)**. Position stop: entry − **3 × ATR(14)**, never more than **15%** below entry.
  - Risk weights: vol 60d **0.30**, range width **0.20**, signal disagreement **0.15**, illiquidity **0.15**, event risk **0.10**, small size **0.10**.
  - Levels by score percentile: Low **< 30**, Medium **30–65**, High **65–90**, Very High **≥ 90**. Max position **5 / 3 / 1.5 / 0.5%**.
  - Floors: market cap under **$300M** is at least High; a stock missing more than half its market's feature groups is at least Medium.
  - Per market at most **10 Swing + 10 Position**, at most **3 per sector** per list.
- **One cost rule:** costs come from `advisor.model.backtest.round_trip_cost` with `settings.usd_fx_fee_pct`, so the backtest gate and live picks agree.
- **Picks need an enabled market.** A market whose active model's `metrics["picks_enabled"]` is false gets no picks, and its `picks_reason` goes in the summary (§6.6). Watchlist verdicts still come (§6.6: "Watchlist verdicts and holdings actions remain"), each with `details.market_picks_enabled: false`.
- **Usable horizons only.** P(beat) appears only where `predictions` has a row. A stock with no forecast gets no pick, and its verdict is Hold with the reason.
- **No harm.** Stage 8 runs after every earlier stage's writes. A failure degrades the run per market (`summary["picks"][market] = {"failed": ...}`) and never fails it.
- **Tests run in Docker**, from `pipeline/`: `scripts/in-docker.sh uv run pytest -q` and `scripts/in-docker.sh uv run ruff check .`. Integration tests need the `advisor-pg` container.
- **Commits:** `git commit` in a command of its own (a hook misreads `-n`); never skip hooks; end messages with the `Co-Authored-By:` trailer.
- **Never put a real email address** in code, tests or docs.

## Decisions this plan makes (the spec leaves them open)

1. **Risk population.** Percentile ranks are taken within the market's stocks forecast this run (holdings, watchlist and shortlist). Range width only exists for those.
2. **Representative horizon.** A stock that isn't picked takes its risk width and event window from its best-ratio usable horizon.
3. **Signal disagreement** is `1 − |mean of signs|` over the directions available:
   - technical: `ex_bench_63`;
   - fundamental (US): `rev_growth`;
   - sentiment: `news_sentiment_mean`.

   It needs at least two. A missing component drops out, and the remaining weights are renormalised.
4. **Event risk** is 1 when an earnings report (`yfinance_earnings`) or a phase 2/3 trial completion (`clinical_trials.next_completion`) falls after the feature day and on or before the exit-by date, otherwise 0.
5. **Small size and its floor** use `log_mcap`, which only US stocks have. A TSX stock has no size component and no market-cap floor.
6. **Feature groups for the Medium floor:**
   - price/volume, relative strength and news (both markets);
   - fundamentals (US only).

   A group is missing when all its features are.
7. **Picks exclude stocks already held.** Those get Add / Hold in Plan 4c. Watched stocks can be picks too.
8. **Sanity checks (§6.1):**
   - the stock's last bar is on the market's feature day;
   - the close is positive;
   - the three quantiles are finite;
   - no flagged jump in the last 5 sessions (`jump_5d`).
9. **Entry reference price** is the feature day's close. At the pre-close run that's the 3:15 PM price.
10. **Top factors** are the 3 features with the largest absolute LightGBM contribution (`pred_contrib`) to the chosen horizon's q50, in excess-return units.
11. **Catalysts:**
    - earnings and trial completions within the hold;
    - 8-K filings in the last 3 days.
12. **Watched coins** get Hold with "no crypto model yet" (the crypto model, spec §5.4, isn't built).

## Review Focus

1. **A pick that breaks a spec limit:**
   - an 11th in a list;
   - a 4th in a sector;
   - a held stock;
   - a stop below 85% of entry for Position;
   - a jump day;
   - a disabled market.

   Covered by Task 3: `test_each_list_keeps_ten_with_three_per_sector`, `test_a_position_stop_is_never_more_than_fifteen_percent_below_entry`, `test_held_stocks_and_jump_days_are_never_picked`, and Task 5: `test_a_disabled_market_gets_verdicts_but_no_picks`.
2. **A risk level that ignores a floor**, or a score built from a missing input (TSX has no market cap). Covered by Task 2: `test_floors_lift_the_level` and `test_missing_components_drop_out_and_weights_renormalise`.
3. **An exit-by date on a holiday or weekend.** Covered by Task 2: `test_exit_by_counts_the_markets_own_trading_days`.
4. **A watched stock with no forecast shown as a Buy or an Avoid.** Covered by Task 4: `test_a_watched_stock_without_a_forecast_is_hold_with_the_reason`.
5. **A failure in stage 8 stopping the run.** Covered by Task 5: `test_a_recommender_failure_degrades_the_run_and_prices_still_publish`.

## Files

| File | Task | What it is |
|---|---|---|
| `pipeline/src/advisor/collectors/nasdaq_symbols.py`, `tmx_symbols.py` + their tests | 1 | Non-common listings out of the universe |
| `pipeline/src/advisor/schedule.py`, `pipeline/src/advisor/recommend/__init__.py`, `risk.py` + `tests/unit/test_recommend_risk.py`, `tests/unit/test_schedule.py` | 2 | Trading days, risk level |
| `pipeline/src/advisor/recommend/picks.py`, `pipeline/src/advisor/model/train.py` + `tests/unit/test_recommend_picks.py` | 3 | Qualify, hold time, stops, rank, factors, catalysts |
| `pipeline/src/advisor/recommend/verdicts.py` + `tests/unit/test_recommend_verdicts.py` | 4 | Watchlist verdicts |
| `pipeline/src/advisor/run.py`, `pipeline/src/advisor/store/repo.py`, `pipeline/src/advisor/models.py` + `tests/integration/test_run.py`, `tests/integration/test_repo.py` | 5 | Stage 8 |
| spec, `docs/superpowers/deferred.md`, `pipeline/README.md` | 6 | Docs |

---

### Task 1: Non-common listings out of the universe

**Files:**
- Modify: `pipeline/src/advisor/collectors/nasdaq_symbols.py`, `pipeline/src/advisor/collectors/tmx_symbols.py`
- Test: `pipeline/tests/unit/test_nasdaq_symbols.py`, `pipeline/tests/unit/test_tmx_symbols.py` (the collectors' existing test files)

**Interfaces:**
- Produces:
  - in `nasdaq_symbols`, new patterns used by `is_excluded_name(name) -> bool`:
    - `ETN = r"\bETNs?\b|exchange[- ]traded notes?"`;
    - `STRUCTURED = r"trust certificates|\btr certs?\b|\btr ctf\b|corp(orate)? backed|\bSTRATS\b|\bCorTS\b|\bPPlus\b|\bSATURNS\b|trust securities"`;
    - `PREFERRED_CLASS = r"\bpreferred (class|series)\b|\bperpetual preferred\b"`;
    - `FUND = r"\bfunds?\b"`;
    - `LP_UNITS = r"\bL\.P\.|\bLP\b|limited partner(ship)? interests?|\bcommon units\b"`.

    All case-insensitive, except `LP_UNITS` and `ETN`, whose short forms must be upper case: `ETN`, `LP`.
  - in `tmx_symbols`, `NON_OPERATING = r"\bPhysical\b.*\bTrust\b|\bActivETF\b|\bIncome (Plus )?Class\b|\bPremium Income Corporation\b|\bInvestment Trust Limited\b"`, checked against the company name in `keep_instrument`.

- [ ] **Step 1: Write the failing tests**

Append to `pipeline/tests/unit/test_nasdaq_symbols.py`:

```python
@pytest.mark.parametrize("name", [
    "ETRACS Alerian MLP Index ETN Series B due July 18, 2042",
    "iPath Bloomberg Commodity Index Total Return ETN",
    "Synthetic Fixed-Income Securities Inc 6.375% (STRATS) Cl A-1",
    "Lehman ABS 3.50 3.50% Adjustable Corp Backed Tr Certs GS Cap I",
    "Structured Products Corp 8.205% CorTS 8.205% Corporate Backed Trust Securities (CorTS)",
    "PPlus Tr GSC-2 Tr Ctf Fltg Rate",
    "CHS Inc - Preferred Class B Series 2 Reset Rate",
    "Ares Capital Corporation - Closed End Fund",
    "Nuveen Preferred & Income Opportunities Fund",
    "United States Natural Gas Fund LP",
    "Energy Transfer LP Common Units",
    "Enterprise Products Partners L.P. Common Stock",
    "Alliance Resource Partners, L.P. - Common Units Representing Limited Partnership Interests",
])
def test_non_common_listings_are_left_out(name):
    assert is_excluded_name(name)


@pytest.mark.parametrize("name", [
    "Preferred Bank - Common Stock",
    "Dillard's, Inc. Common Stock",
    "Diversified Healthcare Trust  - Common Shares of Beneficial Interest",
    "Empire State Realty Trust, Inc. Class A Common Stock",
    "Fundamental Global Inc. Common Stock",
    "Help Line Corp. Common Stock",
])
def test_common_stocks_stay(name):
    assert not is_excluded_name(name)
```

Append to `pipeline/tests/unit/test_tmx_symbols.py`:

```python
@pytest.mark.parametrize(("symbol", "name"), [
    ("PHYS", "Sprott Physical Gold Trust"), ("CEF", "Sprott Physical Gold and Silver Trust"),
    ("PBY", "Lysander-Canso Credit Income ActivETF"), ("MIPC", "Middlefield Income Plus Class"),
    ("PIC.A", "Premium Income Corporation"), ("EVT", "Economic Investment Trust Limited"),
])
def test_tsx_non_operating_vehicles_are_left_out(symbol, name):
    assert not keep_instrument(symbol, "", name)


@pytest.mark.parametrize(("symbol", "name"), [
    ("REI.UN", "RioCan Real Estate Investment Trust"), ("EIF", "Exchange Income Corporation"),
    ("RY", "Royal Bank of Canada"),
])
def test_tsx_operating_companies_and_reits_stay(symbol, name):
    assert keep_instrument(symbol, "", name)
```

(Use the files' existing imports; add `pytest` and the function under test if they're missing.)

- [ ] **Step 2: Run them to verify they fail**

Run: `scripts/in-docker.sh uv run pytest -q tests/unit/test_nasdaq_symbols.py tests/unit/test_tmx_symbols.py`
Expected: FAIL on the new exclusions.

- [ ] **Step 3: Implement the patterns** (interfaces above), in `is_excluded_name` and `keep_instrument`

- [ ] **Step 4: Run the tests to verify they pass**

Run: `scripts/in-docker.sh uv run pytest -q && scripts/in-docker.sh uv run ruff check .`
Expected: all pass, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add pipeline/src/advisor/collectors/nasdaq_symbols.py pipeline/src/advisor/collectors/tmx_symbols.py pipeline/tests/unit/test_nasdaq_symbols.py pipeline/tests/unit/test_tmx_symbols.py
```
```bash
git commit -m "feat: leave ETNs, funds, partnership units and structured notes out of the universe"
```

---

### Task 2: Trading days and the risk level

**Files:**
- Modify: `pipeline/src/advisor/schedule.py`
- Create: `pipeline/src/advisor/recommend/__init__.py` (docstring only), `pipeline/src/advisor/recommend/risk.py`
- Test: `pipeline/tests/unit/test_schedule.py`, `pipeline/tests/unit/test_recommend_risk.py`

**Interfaces:**
- Produces:
  - in `advisor.schedule`: `sessions_after(market: Market, day: date, n: int) -> date`, the n-th trading session of the market after `day`;
  - in `advisor.recommend.risk`:
    - `WEIGHTS = {"vol_60": 0.30, "width": 0.20, "disagreement": 0.15, "illiquidity": 0.15, "event": 0.10, "size": 0.10}`;
    - `LEVELS = (("low", 30, 5.0), ("medium", 65, 3.0), ("high", 90, 1.5), ("very_high", 101, 0.5))`, each the level, the score-percentile limit below which it applies, and the max position in percent;
    - `SMALL_CAP = 300_000_000`;
    - `disagreement(technical: float, fundamental: float, sentiment: float) -> float` (NaN when fewer than two signs are available);
    - `risk_levels(frame: pd.DataFrame) -> pd.DataFrame`. The input is indexed by symbol, with the columns `vol_60, width, disagreement, log_adv20, event, log_mcap, groups_missing_share`. The output adds `risk_score` (0–100), `risk_level` and `max_position_pct`.

- [ ] **Step 1: Write the failing tests**

`pipeline/tests/unit/test_schedule.py` (append):

```python
def test_exit_by_counts_the_markets_own_trading_days():
    # US: Wed 2026-11-25, then Thanksgiving (26th), Fri 27th, Mon 30th
    assert sessions_after(Market.US, date(2026, 11, 25), 2) == date(2026, 11, 30)
    # TSX trades on US Thanksgiving but not on Boxing Day
    assert sessions_after(Market.TSX, date(2026, 11, 25), 1) == date(2026, 11, 26)
    assert sessions_after(Market.TSX, date(2026, 12, 24), 1) == date(2026, 12, 29)
```

`pipeline/tests/unit/test_recommend_risk.py`:

```python
import math

import numpy as np
import pandas as pd
import pytest

from advisor.recommend.risk import disagreement, risk_levels

NAN = float("nan")


def frame(rows: dict[str, dict]) -> pd.DataFrame:
    base = {"vol_60": 0.3, "width": 0.1, "disagreement": 0.0, "log_adv20": 18.0, "event": 0.0,
            "log_mcap": 23.0, "groups_missing_share": 0.0}
    return pd.DataFrame({s: base | r for s, r in rows.items()}).T.astype(float)


def test_signals_that_split_evenly_disagree_fully():
    assert disagreement(0.1, -0.2, NAN) == 1.0
    assert disagreement(0.1, 0.2, 0.3) == 0.0
    assert disagreement(0.1, -0.2, 0.3) == pytest.approx(2 / 3)
    assert math.isnan(disagreement(0.1, NAN, NAN))  # one direction can't disagree


def test_the_riskiest_stock_by_every_measure_ranks_very_high():
    rows = {f"S{i}": {"vol_60": 0.1 + i / 100, "width": 0.05 + i / 1000, "log_adv20": 20 - i / 10,
                      "log_mcap": 25 - i / 10} for i in range(20)}
    out = risk_levels(frame(rows))
    assert out.loc["S19", "risk_level"] == "very_high" and out.loc["S19", "max_position_pct"] == 0.5
    assert out.loc["S0", "risk_level"] == "low" and out.loc["S0", "max_position_pct"] == 5.0
    assert out["risk_score"].between(0, 100).all()


def test_floors_lift_the_level():
    rows = {f"S{i}": {} for i in range(10)}
    rows["TINY"] = {"log_mcap": np.log(250e6)}  # under $300M: at least High
    rows["SPARSE"] = {"groups_missing_share": 0.75}  # missing over half its groups: at least Medium
    out = risk_levels(frame(rows))
    assert out.loc["TINY", "risk_level"] in {"high", "very_high"}
    assert out.loc["SPARSE", "risk_level"] in {"medium", "high", "very_high"}


def test_missing_components_drop_out_and_weights_renormalise():
    rows = {f"T{i}": {"log_mcap": NAN, "disagreement": NAN, "vol_60": 0.1 + i / 50} for i in range(10)}
    out = risk_levels(frame(rows))  # a TSX market: no size, no disagreement
    assert out["risk_score"].notna().all()
    assert list(out.sort_values("risk_score").index) == [f"T{i}" for i in range(10)]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `scripts/in-docker.sh uv run pytest -q tests/unit/test_schedule.py tests/unit/test_recommend_risk.py`
Expected: `ImportError` for `sessions_after` and `advisor.recommend`.

- [ ] **Step 3: Implement** (interfaces above)

**`sessions_after`** uses `_calendar(market).valid_days(day + 1, day + n·2 + 10)`, the n-th of them.

**`risk_levels`:**
- **Components:** each is the percentile rank (`rank(pct=True) × 100`) within the frame of:
  - `vol_60`, `width` and `disagreement` as they are;
  - illiquidity = `−log_adv20`;
  - `event`;
  - size = `−log_mcap`.
- **Score:** the weighted mean of the available components, with weights renormalised per stock. Ties share ranks (method `average`).
- **Level:** the level of the score's own percentile within the frame.
- **Floors:** applied after the level.
  - `log_mcap < log(SMALL_CAP)` lifts to at least `high`.
  - `groups_missing_share > 0.5` lifts to at least `medium`.
- **Max position:** follows the final level.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `scripts/in-docker.sh uv run pytest -q tests/unit/test_schedule.py tests/unit/test_recommend_risk.py && scripts/in-docker.sh uv run ruff check .`
Expected: PASS, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add pipeline/src/advisor/schedule.py pipeline/src/advisor/recommend pipeline/tests/unit/test_schedule.py pipeline/tests/unit/test_recommend_risk.py
```
```bash
git commit -m "feat: risk levels and trading-day exit dates for picks"
```

---

### Task 3: Picks

**Files:**
- Create: `pipeline/src/advisor/recommend/picks.py`
- Modify: `pipeline/src/advisor/model/train.py` (add `FinalModel.contributions`)
- Test: `pipeline/tests/unit/test_recommend_picks.py`, `pipeline/tests/unit/test_model_train.py`

**Interfaces:**
- Consumes:
  - Task 2;
  - `advisor.model.backtest`: `P_MIN`, `SWING_HORIZONS`, `PICKS_PER_STYLE`, `PER_SECTOR`, `round_trip_cost`;
  - `advisor.models.PredictionRow`.
- Produces:
  - in `train.py`: `FinalModel.contributions(x: pd.DataFrame, horizon: int, top: int = 3) -> dict[str, list[dict]]`, keyed by the index of `x`. Each value is `[{"feature": name, "contribution": float}, ...]`: the `top` largest by absolute value of the q50 booster's `pred_contrib` (the bias column excluded);
  - in `advisor.recommend.picks`:
    - `SWING_ATR = 2.0`, `POSITION_ATR = 3.0`, `POSITION_MAX_DROP = 0.15`;
    - `@dataclass(frozen=True) class Choice`, with `symbol, horizon, style, p_beat, q10, q50, q90, ratio, cost`;
    - `choose(rows: Sequence[PredictionRow], cost: float, sane: bool) -> Choice | None`. It returns the best-ratio qualifying horizon, or None;
    - `best_horizon(rows: Sequence[PredictionRow]) -> PredictionRow | None`, the best ratio among all rows (for a stock that doesn't qualify);
    - `stop_price(style: str, entry: float, atr_pct: float) -> float`;
    - `rank_picks(choices: Sequence[Choice], sectors: Mapping[str, str | None]) -> list[tuple[Choice, int]]`. Per style it ranks by ratio and keeps at most 3 per sector and 10 per list. A stock with no sector counts alone, as in the backtest. Each choice comes back with its rank within its style, starting at 1.

- [ ] **Step 1: Write the failing tests**

`pipeline/tests/unit/test_recommend_picks.py`:

```python
import pytest

from advisor.models import PredictionRow
from advisor.recommend.picks import best_horizon, choose, rank_picks, stop_price


def row(h, p, q10, q50, q90, symbol="AAA"):
    return PredictionRow(symbol, h, q10, q50, q90, p, "SPY", "v1")


def test_the_best_ratio_qualifying_horizon_is_the_hold():
    rows = [row(10, 0.60, -0.02, 0.01, 0.03), row(63, 0.62, -0.05, 0.04, 0.10), row(126, 0.57, -0.1, 0.2, 0.3)]
    c = choose(rows, cost=0.001, sane=True)
    assert (c.horizon, c.style) == (63, "position")  # 126 has the best ratio but P is below 0.58
    assert choose(rows, cost=0.05, sane=True) is None  # q50 never clears a 5% cost
    assert choose(rows, cost=0.001, sane=False) is None  # failed sanity checks: never a pick
    assert best_horizon(rows).horizon_days == 126


def test_a_position_stop_is_never_more_than_fifteen_percent_below_entry():
    assert stop_price("swing", 100.0, 0.02) == pytest.approx(96.0)
    assert stop_price("position", 100.0, 0.02) == pytest.approx(94.0)
    assert stop_price("position", 100.0, 0.08) == pytest.approx(85.0)  # 3 × 8% = 24%, capped at 15%


def test_each_list_keeps_ten_with_three_per_sector():
    choices = [choose([row(20, 0.65, -0.02, 0.02 + i / 1000, 0.06, f"E{i}")], 0.001, True) for i in range(5)]
    choices += [choose([row(20, 0.65, -0.02, 0.01, 0.06, f"T{i}")], 0.001, True) for i in range(12)]
    sectors = {f"E{i}": "Energy" for i in range(5)} | {f"T{i}": f"Sector{i}" for i in range(12)}
    ranked = rank_picks(choices, sectors)
    assert len(ranked) == 10
    assert [c.symbol for c, _ in ranked[:3]] == ["E4", "E3", "E2"]
    assert [r for _, r in ranked] == list(range(1, 11))


def test_held_stocks_and_jump_days_are_never_picked():
    rows = [row(20, 0.70, -0.02, 0.03, 0.06)]
    assert choose(rows, cost=0.001, sane=False) is None
```

The held-stock half of this Review Focus item is tested in Task 5, where the run removes held stocks before calling `choose`. The jump day is part of the `sane` flag.

Append to `pipeline/tests/unit/test_model_train.py`:

```python
def test_contributions_name_the_features_that_moved_the_forecast(tmp_path):
    write_market(tmp_path, Market.TSX, stocks=20, days=1100)
    data = load_market(tmp_path, Market.TSX)
    model = fit_final(data, walk_forward(data, FAST), FAST)
    x = data.rows.drop_duplicates("symbol").set_index("symbol")[data.features].head(3)
    out = model.contributions(x, 63)
    assert set(out) == set(x.index)
    for parts in out.values():
        assert len(parts) == 3 and {p["feature"] for p in parts} <= set(data.features)
        assert abs(parts[0]["contribution"]) >= abs(parts[-1]["contribution"])
```

- [ ] **Step 2: Run them to verify they fail**

Run: `scripts/in-docker.sh uv run pytest -q tests/unit/test_recommend_picks.py tests/unit/test_model_train.py`
Expected: `ImportError` and `AttributeError` (`contributions`).

- [ ] **Step 3: Implement** (interfaces above)

- **Qualifying:** `p_beat >= P_MIN`, `q50 > cost`, `sane`, and a positive width.
- **Ratio:** `q50 / (q90 − q10)`.
- **Swing:** a horizon in `SWING_HORIZONS`.
- **Stops:**
  - Swing: `entry × (1 − SWING_ATR × atr_pct)`.
  - Position: `max(entry × (1 − POSITION_ATR × atr_pct), entry × (1 − POSITION_MAX_DROP))`.
- **Ranking:** best ratio first, ties by symbol.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `scripts/in-docker.sh uv run pytest -q tests/unit/test_recommend_picks.py tests/unit/test_model_train.py && scripts/in-docker.sh uv run ruff check .`
Expected: PASS, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add pipeline/src/advisor/recommend/picks.py pipeline/src/advisor/model/train.py pipeline/tests/unit/test_recommend_picks.py pipeline/tests/unit/test_model_train.py
```
```bash
git commit -m "feat: choose, stop and rank picks by the spec's rules"
```

---

### Task 4: Watchlist verdicts

**Files:**
- Create: `pipeline/src/advisor/recommend/verdicts.py`
- Test: `pipeline/tests/unit/test_recommend_verdicts.py`

**Interfaces:**
- Consumes: Task 3's `choose`, `best_horizon` and `Choice`; `PredictionRow`.
- Produces, in `advisor.recommend.verdicts`:
  - `AVOID_P = 0.42`;
  - `@dataclass(frozen=True) class Verdict`, with `symbol: str`, `asset_type: str`, `verdict: str` (`buy`, `hold` or `avoid`), `reasons: list[str]` and `details: dict`;
  - `stock_verdict(symbol: str, rows: Sequence[PredictionRow], cost: float, sane: bool, pick_details: dict | None, why_no_forecast: str | None) -> Verdict`;
  - `coin_verdict(symbol: str) -> Verdict`.

**The rules:**
1. **No forecast** (`rows` empty): `hold`, with reasons `[why_no_forecast]`.
2. **Qualifies** (`choose` returns a choice): `buy`. `details` is `pick_details` (the same fields as a pick, from the run). The reasons are:
   - `f"P(beat {benchmark}) {p:.2f} over {h} trading days"`;
   - `f"expected {q50:.1%} against {cost:.1%} round-trip costs"`.
3. **Avoid:** every row has `p_beat <= AVOID_P`. The verdict is `avoid`, with reason `f"P(beat {benchmark}) at most {max_p:.2f} at every horizon"`.
4. **Otherwise:** `hold`. `details` describes the best-ratio horizon's forecast (`horizon`, `p_beat`, `q10`, `q50`, `q90`), and the reasons are `"doesn't qualify as a buy"` plus the first failing check.

**Coins:** `hold`, with reasons `["no crypto model yet"]`.

- [ ] **Step 1: Write the failing tests**

`pipeline/tests/unit/test_recommend_verdicts.py`:

```python
from advisor.models import PredictionRow
from advisor.recommend.verdicts import coin_verdict, stock_verdict


def row(h, p, q50=0.04):
    return PredictionRow("AAA", h, q50 - 0.05, q50, q50 + 0.06, p, "SPY", "v1")


def test_a_qualifying_watched_stock_is_a_buy_with_the_picks_fields():
    v = stock_verdict("AAA", [row(63, 0.62)], 0.031, True, {"stop": 94.0, "risk_level": "medium"}, None)
    assert v.verdict == "buy" and v.details == {"stop": 94.0, "risk_level": "medium"}
    assert v.reasons[0] == "P(beat SPY) 0.62 over 63 trading days"


def test_low_odds_at_every_horizon_is_avoid():
    v = stock_verdict("AAA", [row(21, 0.40), row(63, 0.42)], 0.001, True, None, None)
    assert (v.verdict, v.reasons) == ("avoid", ["P(beat SPY) at most 0.42 at every horizon"])


def test_anything_else_is_hold():
    v = stock_verdict("AAA", [row(21, 0.40), row(63, 0.55, q50=0.06)], 0.001, True, None, None)
    assert v.verdict == "hold" and v.details["horizon"] == 63  # 63 has the better q50/(q90 - q10)


def test_a_watched_stock_without_a_forecast_is_hold_with_the_reason():
    v = stock_verdict("AAA", [], 0.001, True, None, "not eligible for the model (under $1, thin trading or new)")
    assert (v.verdict, v.reasons) == ("hold", ["not eligible for the model (under $1, thin trading or new)"])


def test_a_watched_coin_waits_for_the_crypto_model():
    assert coin_verdict("ETH").reasons == ["no crypto model yet"]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `scripts/in-docker.sh uv run pytest -q tests/unit/test_recommend_verdicts.py`
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement** (interfaces above). The benchmark in reasons comes from the rows' `benchmark` field.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `scripts/in-docker.sh uv run pytest -q tests/unit/test_recommend_verdicts.py && scripts/in-docker.sh uv run ruff check .`
Expected: PASS, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add pipeline/src/advisor/recommend/verdicts.py pipeline/tests/unit/test_recommend_verdicts.py
```
```bash
git commit -m "feat: buy, hold and avoid verdicts for the watchlist"
```

---

### Task 5: Stage 8 in the run

**Files:**
- Modify: `pipeline/src/advisor/run.py`, `pipeline/src/advisor/store/repo.py`, `pipeline/src/advisor/models.py`
- Test: `pipeline/tests/integration/test_run.py`, `pipeline/tests/integration/test_repo.py`

**Interfaces:**
- Consumes: Tasks 2–4; `forecast_market`'s features and prediction rows; `repo.fee_settings`; the active model's `metrics["picks_enabled"]` and `["picks_reason"]`; the run's `results`: `yfinance_earnings` (`EarningsReport.report_at`), `clinical_trials` (`TrialActivity.next_completion`) and `sec_8k` (`MaterialEvent.filing_date`, `items`).
- Produces:
  - in `advisor.models`: `@dataclass(frozen=True) class PickRow`, with `symbol, market, style, horizon_days, exit_by, entry_ref_price, stop, risk_level, risk_score, max_position_pct, rank, top_factors, catalysts`;
  - in `repo`:
    - `write_picks(conn, run_id, rows: Sequence[PickRow]) -> None`;
    - `write_watchlist_verdicts(conn, run_id, verdicts: Sequence[Verdict]) -> None`;
    - `news_sentiment(conn, run_id, symbols) -> dict[str, float]`, read from `features_live` (`news_sentiment_mean`);
  - in `run.py`:
    - `forecast_market` also returns the market's features frame and prediction rows, for stage 8;
    - `recommend_market(...)`, which builds the risk frame (decisions 1–6), chooses, stops and ranks picks (decisions 7–11), and returns `(PickRow list, pick details by symbol, summary)`;
    - stage 8 runs after Phase 3.5. Each market's picks are wrapped in their own `try`, and its summary goes to `summary["picks"][market]`:
      - `{"swing", "position"}` counts;
      - or `{"disabled": picks_reason}`;
      - or `{"skipped": ...}` when there is no model;
      - or `{"failed": ...}`.
    - Then the verdicts for every watched symbol go into `watchlist_verdicts`, inside their own `try` (a failure there goes to `summary["verdicts"]`).
    - The status is at least degraded when any `"failed"` appears.

- [ ] **Step 1: Write the failing tests**

Append to `pipeline/tests/integration/test_repo.py` a round trip for `write_picks` and `write_watchlist_verdicts`: one row each, read back, with `market` set and `catalysts`/`reasons` as JSON lists.

Append to `pipeline/tests/integration/test_run.py`. The file already has `make_deps`, `hold`, `tsx_model_files`, `activate_tsx`, `NOW`, `SMALL` and `run_row`. Every model here forecasts `predict_rows` high for TSX through `monkeypatch`, so picks qualify:

```python
from advisor.models import PredictionRow


def confident(active, features, benchmark):
    return [PredictionRow(s, 63, -0.05, 0.04, 0.10, 0.65, benchmark, active.version) for s in features.index]


def test_qualifying_forecasts_become_picks_and_watched_stocks_get_verdicts(db, tmp_path, tsx_model_files, monkeypatch):
    activate_tsx(db, tsx_model_files)
    db.execute("update models set metrics = metrics || '{\"picks_enabled\": true}'::jsonb")
    db.execute("insert into watchlist (symbol, asset_type) values ('TD.TO', 'stock'), ('ETH', 'crypto')")
    hold(db, "RY.TO")
    monkeypatch.setattr("advisor.run.predict_rows", confident)
    outcome = execute_run(make_deps(db, tmp_path), RunKind.PRE_OPEN, NOW, min_universe=SMALL)
    assert outcome.status is RunStatus.SUCCESS
    picks = db.execute("select symbol, market, style, horizon_days, stop, entry_ref_price, rank from picks"
                       " where run_id = %s", (outcome.run_id,)).fetchall()
    assert [p["symbol"] for p in picks] == ["TD.TO"]  # RY.TO is held: never a pick
    assert picks[0]["style"] == "position" and picks[0]["market"] == "TSX" and picks[0]["rank"] == 1
    assert picks[0]["stop"] >= picks[0]["entry_ref_price"] * 0.85
    verdicts = {r["symbol"]: r["verdict"] for r in db.execute(
        "select symbol, verdict from watchlist_verdicts where run_id = %s", (outcome.run_id,)).fetchall()}
    assert verdicts == {"TD.TO": "buy", "ETH": "hold"}
    assert outcome.summary["picks"]["TSX"] == {"swing": 0, "position": 1}


def test_a_disabled_market_gets_verdicts_but_no_picks(db, tmp_path, tsx_model_files, monkeypatch):
    activate_tsx(db, tsx_model_files)
    db.execute("update models set metrics = metrics || '{\"picks_enabled\": false, \"picks_reason\": \"only 12 backtest picks (needs 30)\"}'::jsonb")
    db.execute("insert into watchlist (symbol, asset_type) values ('TD.TO', 'stock')")
    monkeypatch.setattr("advisor.run.predict_rows", confident)
    outcome = execute_run(make_deps(db, tmp_path), RunKind.PRE_OPEN, NOW, min_universe=SMALL)
    assert db.execute("select count(*) as n from picks").fetchone()["n"] == 0
    assert outcome.summary["picks"]["TSX"] == {"disabled": "only 12 backtest picks (needs 30)"}
    verdict = db.execute("select verdict, details from watchlist_verdicts where symbol = 'TD.TO'").fetchone()
    assert verdict["verdict"] == "buy" and verdict["details"]["market_picks_enabled"] is False


def test_a_recommender_failure_degrades_the_run_and_prices_still_publish(db, tmp_path, tsx_model_files, monkeypatch):
    activate_tsx(db, tsx_model_files)
    db.execute("update models set metrics = metrics || '{\"picks_enabled\": true}'::jsonb")
    monkeypatch.setattr("advisor.run.predict_rows", confident)

    def broken(*args, **kwargs):
        raise RuntimeError("risk frame broke")

    monkeypatch.setattr("advisor.run.risk_levels", broken)
    outcome = execute_run(make_deps(db, tmp_path), RunKind.PRE_OPEN, NOW, min_universe=SMALL)
    assert outcome.status is RunStatus.DEGRADED
    assert outcome.summary["picks"]["TSX"]["failed"].startswith("RuntimeError")
    assert run_row(db, outcome.run_id)["published"] is True
```

(The `update models` statements set the metric, because `activate_tsx` stores only `usable_horizons`. `run.py` must import `risk_levels` by name, `from advisor.recommend.risk import risk_levels`, so the failure test can patch `advisor.run.risk_levels`.)

- [ ] **Step 2: Run them to verify they fail**

Run: `scripts/in-docker.sh uv run pytest -q tests/integration/test_run.py tests/integration/test_repo.py -k "pick or verdict or recommender"`
Expected: FAIL, because there's no stage 8 and no repo writers.

- [ ] **Step 3: Implement** (interfaces above)

- **Where it runs:** stage 8 runs only when the run is enriched, as Phase 3.5 is, and only for markets with an active model.
- **Inputs:** take the feature day and the bars as Phase 3.5 does. A stock's ATR percentage is `features["atr_14_pct"]`, and its sector comes from `model.sectors`.
- **Verdict wiring:**
  - Watched stocks of a market without a model get `stock_verdict(..., why_no_forecast="no active model")`.
  - A watched stock not in the features (not priced) gets `"not priced this run"`.
  - A watched stock with `model_eligible` false gets `"not eligible for the model (under $1, thin trading or new)"`.
- **Existing tests:** update the whole-summary test to include `"picks"` (`{"skipped": "no active model"}` per market). Add `"verdicts"` only if a failure occurs.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `scripts/in-docker.sh uv run pytest -q && scripts/in-docker.sh uv run ruff check .`
Expected: all pass, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add pipeline/src/advisor/run.py pipeline/src/advisor/store/repo.py pipeline/src/advisor/models.py pipeline/tests/integration/test_run.py pipeline/tests/integration/test_repo.py
```
```bash
git commit -m "feat: write each run's picks and watchlist verdicts"
```

---

### Task 6: Docs

**Files:**
- Modify: `docs/superpowers/specs/2026-10-09-stock-advisor-design.md`, `docs/superpowers/deferred.md`, `pipeline/README.md`

- [ ] **Step 1: Spec**

- **Revision history:** a 2026-10-26 Plan 4a line, with the owner's universe decisions.
- **§2 R2 / §3 Markets:** the US universe leaves out partnership units, closed-end funds and BDCs, ETNs, structured notes and preferred classes. The TSX leaves out physical-metal trusts and similar vehicles.
- **§6.4:** record decisions 1–6 (the population, the representative horizon, disagreement, event risk, size on US only, feature groups).
- **§6.5:**
  - held stocks are never picks;
  - top factors and catalysts as decided;
  - a watched stock without a forecast or a coin gets Hold with the reason.
- **§4.3 stage 8:** stage 8 failures degrade the run per market.

- [ ] **Step 2: deferred.md**

- Replace "Plan 4: recommendations" with what's left:
  - for 4b, the dashboard: Today's Picks, watchlist verdicts, the Ticker forecast range and top factors, paper badges;
  - for 4c: holding actions, exit-early, grading, holding-action outcomes.
- Record that the TMX filter also drops operating income funds (Chemtrade Logistics Income Fund, Boston Pizza Royalties Income Fund). That predates this plan; it's the owner's call whether to readmit them.
- Record that US partnership units (including Bermuda partnerships listed in the US) are dropped as a group.

- [ ] **Step 3: README**

Add `summary.picks` and `summary.verdicts` under the run section.

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-10-09-stock-advisor-design.md docs/superpowers/deferred.md pipeline/README.md
```
```bash
git commit -m "docs: record Plan 4a's picks, verdicts and universe decisions"
```
