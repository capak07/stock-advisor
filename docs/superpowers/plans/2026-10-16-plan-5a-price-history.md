# Plan 5a: Price and FX History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store daily closes and the Bank of Canada's USD/CAD rate in Supabase, so the dashboard (Plan 5b) can chart returns and value US holdings and coins in CAD.

**Architecture:**
- Migration `0006` adds two tables: `daily_closes` and `fx_rates`. The owner can read them; only the pipeline role writes them.
- A new module, `advisor/history.py`, turns each run's Yahoo bars and Coinbase candles into closes. It rescales older stored closes when Yahoo re-adjusts history after a split or dividend, and backfills a year the first time it sees a symbol short. It also stores USD/CAD.
- `execute_run` prices SPY and XIU.TO with the holdings. Only a run that can publish calls the history step, and the step's errors go into `summary["history"]`; they never fail the run.

**Tech Stack:** Python 3.12, uv, psycopg 3, pydantic v2, httpx, yfinance, pandas, Postgres (Supabase) with row-level security.

**Spec:** `docs/superpowers/specs/2026-10-09-stock-advisor-design.md` (rev 2): §3 Markets (benchmarks), §4.3 Run stages, §8 Data Model, §9 Dashboard.

**Owner decisions behind this plan (2026-10-16):**
- The dashboard needs price and FX history that the database didn't keep.
- The pipeline stores it, and the dashboard only reads it (design rule 1). The owner chose this over "no charts yet".

## Global Constraints

- No data source may need an API key or an account (spec R7). Yahoo via yfinance and the Bank of Canada Valet API are both keyless.
- The pipeline writes and the dashboard reads (design rule 1). `daily_closes` and `fx_rates` get `owner_read` for the owner and `pipeline_write` for `pipeline_rw` (spec §8 row-level security; `test_schema.py` checks every table).
- Migrations are append-only. This plan adds `0006` and edits no earlier migration.
- Stock symbols follow spec §8's formats: `^[A-Z]{1,5}(\.[A-Z])?$` for US, `^[A-Z]{1,5}(-[A-Z]{1,2})?\.TO$` for TSX, `^[A-Z0-9]{2,10}$` for crypto.
- Benchmarks (spec §3): SPY for US and XIU.TO for TSX.
- Tests use fakes and recorded fixtures, with no live network (spec §11). Tests and lint run only in Docker: `pipeline/scripts/in-docker.sh uv run pytest -q` and `pipeline/scripts/in-docker.sh uv run ruff check .` (ruff line length 100; rules E, F, I, UP, B; E501 ignored).
- The price history never fails a run. Only a run that can publish touches it, because a failed run's prices may be why it failed.
- Supabase free tier: closes reach about 15 MB at steady state (about 420 symbols over 2 years), and FX about 250 rows a year.

## Review Focus

1. **A split or dividend after closes were stored.** Older closes must be rescaled once, by the factor the oldest fresh days show, so a 2-for-1 split doesn't chart as a 50% drop. Task 2 `test_a_split_halves_older_closes`; Task 3 `test_a_split_rescales_the_stored_history`.
2. **One bad Yahoo quote among the compared days.** Nothing may be rescaled. Task 2 `test_a_single_bad_quote_changes_nothing`.
3. **Yahoo drops a symbol from the backfill download.** yfinance's cache reported "database is locked" for SPY in the live check. The symbol is named in `backfill_missing` and asked for again next run. Task 3 `test_a_symbol_yahoo_drops_from_the_backfill_is_named_and_asked_again`.
4. **The Bank of Canada is down during the FX backfill.** It's reported as `fx_error`, the run publishes, and its own rate and closes are kept. Task 3 `test_a_bank_of_canada_outage_is_reported_and_the_run_keeps_its_closes`.
5. **A run that can't publish** (for example during a TMX outage). It stores no prices and never reaches Yahoo for a backfill. Task 3 `test_a_run_that_cannot_publish_leaves_the_price_history_alone`, plus the guard in `test_run_cli_db.py`.

## Files

| File | What changes |
|---|---|
| `supabase/migrations/0006_price_history.sql` | **Create.** `daily_closes`, `fx_rates`, their policies and grants |
| `pipeline/src/advisor/models.py` | Add `DailyClose` |
| `pipeline/src/advisor/store/repo.py` | Add the price-history queries |
| `pipeline/src/advisor/markets.py` | Add each market's `benchmark` and `BENCHMARKS` |
| `pipeline/src/advisor/history.py` | **Create.** Closes, rescaling, backfill, USD/CAD and the run's history step |
| `pipeline/src/advisor/collectors/yfinance_bars.py` | A public `yahoo_download` for the backfill |
| `pipeline/src/advisor/run.py` | Price the benchmarks in phase 1; call the history step from publishable runs |
| `pipeline/tests/integration/test_repo.py`, `test_schema.py`, `test_run.py`, `test_run_cli_db.py` | Tests for the above |
| `pipeline/tests/unit/test_history.py` | **Create.** The history module's tests |
| `README.md`, `docs/superpowers/specs/2026-10-09-stock-advisor-design.md`, `docs/superpowers/deferred.md` | Upgrade note, spec rows, deferred notes |

The baseline is 618 passed. After Task 1: 629. After Task 2: 642. After Task 3: 650.

---

### Task 1: Price-history tables and their queries

**Files:**
- Create: `supabase/migrations/0006_price_history.sql`
- Modify: `pipeline/src/advisor/models.py` (add `DailyClose` after `AssetRef`)
- Modify: `pipeline/src/advisor/store/repo.py` (import `DailyClose`; append the queries)
- Test: `pipeline/tests/integration/test_repo.py`, `pipeline/tests/integration/test_schema.py`

**Interfaces:**
- Produces:
  - `DailyClose(ref: AssetRef, day: date, close: float, currency: str)`, a NamedTuple in `advisor.models`;
  - `repo.write_daily_closes(conn, closes: Sequence[DailyClose]) -> None`;
  - `repo.stored_closes(conn, refs, since: date) -> dict[AssetRef, dict[date, float]]`;
  - `repo.rescale_closes(conn, ref, before: date, factor: float) -> int`;
  - `repo.earliest_closes(conn, refs) -> dict[AssetRef, date]`;
  - `repo.first_buys(conn) -> dict[AssetRef, date]`;
  - `repo.write_fx_rates(conn, rates: Sequence[tuple[date, float]]) -> None`;
  - `repo.earliest_fx_rate(conn) -> date | None`;
  - `repo.prune_daily_closes(conn, before: date, keep: Iterable[str]) -> int`.

- [ ] **Step 1: Write the failing tests**

In `pipeline/tests/integration/test_repo.py`, change the models import to:

```python
from advisor.models import AssetRef, AssetType, DailyClose, Market, RunKind, RunStatus, SymbolInfo
```

Then append to the end of the file:

```python
AAPL = AssetRef("AAPL", AssetType.STOCK)


def daily(symbol: str, day: date, close: float, asset_type: AssetType = AssetType.STOCK) -> DailyClose:
    return DailyClose(AssetRef(symbol, asset_type), day, close, "USD")


def test_closes_are_stored_and_a_refreshed_close_replaces_the_old_one(db):
    repo.write_daily_closes(db, [daily("AAPL", date(2026, 10, 12), 227.5), daily("AAPL", date(2026, 10, 13), 228.0)])
    repo.write_daily_closes(db, [daily("AAPL", date(2026, 10, 13), 228.4)])  # Yahoo re-adjusted it
    repo.write_daily_closes(db, [])
    assert repo.stored_closes(db, [AAPL], date(2026, 10, 1)) == {
        AAPL: {date(2026, 10, 12): 227.5, date(2026, 10, 13): 228.4},
    }
    assert repo.stored_closes(db, [AAPL], date(2026, 10, 13)) == {AAPL: {date(2026, 10, 13): 228.4}}
    assert repo.earliest_closes(db, [AAPL, AssetRef("MSFT", AssetType.STOCK)]) == {AAPL: date(2026, 10, 12)}


def test_a_coin_and_a_stock_can_share_a_symbol(db):
    day = date(2026, 10, 13)
    repo.write_daily_closes(db, [daily("LINK", day, 5.1), daily("LINK", day, 24.9, AssetType.CRYPTO)])
    stock, coin = AssetRef("LINK", AssetType.STOCK), AssetRef("LINK", AssetType.CRYPTO)
    assert repo.stored_closes(db, [stock, coin], day) == {stock: {day: 5.1}, coin: {day: 24.9}}
    assert repo.stored_closes(db, [coin], day) == {coin: {day: 24.9}}


def test_closes_before_a_day_can_be_rescaled(db):
    repo.write_daily_closes(db, [daily("AAPL", date(2026, 6, d), 200.0) for d in (1, 2, 3)])
    assert repo.rescale_closes(db, AAPL, date(2026, 6, 3), 0.5) == 2
    assert repo.stored_closes(db, [AAPL], date(2026, 6, 1)) == {
        AAPL: {date(2026, 6, 1): 100.0, date(2026, 6, 2): 100.0, date(2026, 6, 3): 200.0},
    }


def test_first_buys_cover_assets_sold_since(db):
    for symbol, asset_type, account, currency, fx, day in [
        ("AAPL", "stock", "tfsa", "USD", 1.36, "2025-05-12"),
        ("AAPL", "stock", "tfsa", "USD", 1.37, "2026-01-05"),
        ("BTC", "crypto", "crypto", "CAD", None, "2026-02-01"),
    ]:
        db.execute(
            "insert into lots (account, symbol, asset_type, qty, price, currency, fx_rate_cad, bought_at)"
            " values (%s, %s, %s, 1, 10, %s, %s, %s)",
            (account, symbol, asset_type, currency, fx, day),
        )
    db.execute(
        "insert into sells (account, symbol, asset_type, qty, price, currency, fx_rate_cad, sold_at)"
        " values ('tfsa', 'AAPL', 'stock', 2, 12, 'USD', 1.38, '2026-03-02')"
    )
    assert repo.first_buys(db) == {
        AAPL: date(2025, 5, 12), AssetRef("BTC", AssetType.CRYPTO): date(2026, 2, 1),
    }


def test_usd_cad_rates_are_stored_and_revised(db):
    assert repo.earliest_fx_rate(db) is None
    repo.write_fx_rates(db, [(date(2026, 10, 12), 1.37), (date(2026, 10, 13), 1.3712)])
    repo.write_fx_rates(db, [(date(2026, 10, 13), 1.3715)])  # the bank revised it
    repo.write_fx_rates(db, [])
    rows = db.execute("select day, usd_cad from fx_rates order by day").fetchall()
    assert [(r["day"], float(r["usd_cad"])) for r in rows] == [
        (date(2026, 10, 12), 1.37), (date(2026, 10, 13), 1.3715),
    ]
    assert repo.earliest_fx_rate(db) == date(2026, 10, 12)


def test_old_closes_are_pruned_except_holdings_and_benchmarks(db):
    old, recent = date(2024, 9, 2), date(2026, 10, 13)
    repo.write_daily_closes(db, [
        daily("AAPL", old, 150.0), daily("SPY", old, 540.0), daily("PLTR", old, 30.0),
        daily("PLTR", recent, 182.7),
    ])
    db.execute(
        "insert into lots (account, symbol, asset_type, qty, price, currency, fx_rate_cad, bought_at)"
        " values ('tfsa', 'AAPL', 'stock', 1, 150, 'USD', 1.35, '2024-09-02')"
    )
    assert repo.prune_daily_closes(db, date(2024, 10, 14), ["SPY", "XIU.TO"]) == 1
    rows = db.execute("select symbol, day from daily_closes order by symbol, day").fetchall()
    assert [(r["symbol"], r["day"]) for r in rows] == [("AAPL", old), ("PLTR", recent), ("SPY", old)]
```

Append to the end of `pipeline/tests/integration/test_schema.py`:

```python
def test_the_owner_reads_price_history_and_only_the_pipeline_writes_it(owned_db):
    owned_db.execute("insert into daily_closes values ('AAPL', 'stock', '2026-10-13', 228, 'USD')")
    owned_db.execute("insert into fx_rates values ('2026-10-13', 1.3712)")
    with acting_as(owned_db, "authenticated", OWNER):
        assert len(owned_db.execute("select * from daily_closes").fetchall()) == 1
        assert len(owned_db.execute("select * from fx_rates").fetchall()) == 1
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            owned_db.execute("insert into daily_closes values ('MSFT', 'stock', '2026-10-13', 410, 'USD')")
        assert owned_db.execute("update fx_rates set usd_cad = 1").rowcount == 0
        assert owned_db.execute("delete from daily_closes").rowcount == 0
    with acting_as(owned_db, "authenticated", STRANGER):
        assert owned_db.execute("select * from daily_closes").fetchall() == []
        assert owned_db.execute("select * from fx_rates").fetchall() == []
    with acting_as(owned_db, "pipeline_rw"):
        owned_db.execute("insert into daily_closes values ('MSFT', 'stock', '2026-10-13', 410, 'USD')")
        assert owned_db.execute("update fx_rates set usd_cad = 1.3715").rowcount == 1


@pytest.mark.parametrize(
    ("symbol", "asset_type", "currency"),
    [("aapl", "stock", "USD"), ("RY.TSX", "stock", "CAD"), ("btc", "crypto", "USD"), ("AAPL", "stock", "EUR")],
)
def test_malformed_closes_are_rejected(db, symbol, asset_type, currency):
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(
            "insert into daily_closes values (%s, %s, '2026-10-13', 10, %s)", (symbol, asset_type, currency)
        )
```

- [ ] **Step 2: Run them and see them fail**

Run: `pipeline/scripts/in-docker.sh uv run pytest tests/integration/test_repo.py tests/integration/test_schema.py -q`
Expected: collection fails with `ImportError: cannot import name 'DailyClose'`.

- [ ] **Step 3: Write the migration**

Create `supabase/migrations/0006_price_history.sql`:

```sql
-- Plan 5a (owner decision 2026-10-16): price history for the dashboard. The pipeline stores daily
-- closes for holdings, the watchlist, the shortlist and the two benchmarks, and the Bank of Canada's
-- USD/CAD rate, so the dashboard can chart returns and value US holdings in CAD.
-- Stock closes are Yahoo's split- and dividend-adjusted closes; crypto closes are Coinbase's, in USD.
create table daily_closes (
  symbol text not null,
  asset_type text not null check (asset_type in ('stock', 'crypto')),
  day date not null,
  close numeric not null check (close > 0),
  currency text not null check (currency in ('USD', 'CAD')),
  constraint daily_closes_symbol_format check (
    (asset_type = 'stock' and (symbol ~ '^[A-Z]{1,5}(\.[A-Z])?$'
                               or symbol ~ '^[A-Z]{1,5}(-[A-Z]{1,2})?\.TO$'))
    or (asset_type = 'crypto' and symbol ~ '^[A-Z0-9]{2,10}$')),
  primary key (symbol, asset_type, day)
);
create index daily_closes_by_day on daily_closes (day);

create table fx_rates (
  day date primary key,
  usd_cad numeric not null check (usd_cad > 0)
);

alter table daily_closes enable row level security;
alter table fx_rates enable row level security;
create policy owner_read on daily_closes for select to authenticated using ((select public.is_owner()));
create policy owner_read on fx_rates for select to authenticated using ((select public.is_owner()));
create policy pipeline_write on daily_closes for all to pipeline_rw using (true) with check (true);
create policy pipeline_write on fx_rates for all to pipeline_rw using (true) with check (true);
grant select, insert, update, delete on daily_closes, fx_rates to pipeline_rw;
```

The test database applies every migration when the session starts (`conftest.py`). Then it grants the Supabase roles access to every table, so the new tables need no test setup.

- [ ] **Step 4: Add `DailyClose`**

In `pipeline/src/advisor/models.py`, add this right after `class AssetRef` (the file already imports `date` and `NamedTuple`):

```python
class DailyClose(NamedTuple):
    """A stored daily close (Plan 5a): Yahoo's adjusted close for a stock, Coinbase's for a coin."""

    ref: AssetRef
    day: date
    close: float
    currency: str  # "USD" or "CAD"
```

- [ ] **Step 5: Add the queries**

In `pipeline/src/advisor/store/repo.py`, replace the models import with:

```python
from advisor.models import (
    ET,
    AssetRef,
    AssetType,
    DailyClose,
    Market,
    RunKind,
    RunStatus,
    SymbolInfo,
)
```

Append to the end of the file:

```python
# Price history for the dashboard (Plan 5a).


def write_daily_closes(conn: psycopg.Connection, closes: Sequence[DailyClose]) -> None:
    """Store closes. A close already stored for that day is replaced: Yahoo re-adjusts history."""
    if not closes:
        return
    with conn.cursor() as cur:
        cur.executemany(
            "insert into daily_closes (symbol, asset_type, day, close, currency)"
            " values (%s, %s, %s, %s, %s)"
            " on conflict (symbol, asset_type, day) do update"
            " set close = excluded.close, currency = excluded.currency"
            " where daily_closes.close <> excluded.close"
            " or daily_closes.currency <> excluded.currency",
            [(c.ref.symbol, c.ref.asset_type.value, c.day, c.close, c.currency) for c in closes],
        )


def stored_closes(
    conn: psycopg.Connection, refs: Iterable[AssetRef], since: date
) -> dict[AssetRef, dict[date, float]]:
    """Each asset's stored closes on or after `since`."""
    wanted = set(refs)
    if not wanted:
        return {}
    rows = conn.execute(
        "select symbol, asset_type, day, close from daily_closes"
        " where day >= %s and symbol = any(%s)",
        (since, sorted({ref.symbol for ref in wanted})),
    ).fetchall()
    closes: dict[AssetRef, dict[date, float]] = defaultdict(dict)
    for row in rows:
        ref = AssetRef(row["symbol"], AssetType(row["asset_type"]))
        if ref in wanted:
            closes[ref][row["day"]] = float(row["close"])
    return dict(closes)


def rescale_closes(conn: psycopg.Connection, ref: AssetRef, before: date, factor: float) -> int:
    """Multiply an asset's closes before `before` by `factor`; returns how many rows changed."""
    return conn.execute(
        "update daily_closes set close = close * %s"
        " where symbol = %s and asset_type = %s and day < %s",
        (factor, ref.symbol, ref.asset_type.value, before),
    ).rowcount


def earliest_closes(conn: psycopg.Connection, refs: Iterable[AssetRef]) -> dict[AssetRef, date]:
    """The first stored day of each asset that has any closes."""
    wanted = set(refs)
    if not wanted:
        return {}
    rows = conn.execute(
        "select symbol, asset_type, min(day) as day from daily_closes"
        " where symbol = any(%s) group by symbol, asset_type",
        (sorted({ref.symbol for ref in wanted}),),
    ).fetchall()
    found = {AssetRef(r["symbol"], AssetType(r["asset_type"])): r["day"] for r in rows}
    return {ref: day for ref, day in found.items() if ref in wanted}


def first_buys(conn: psycopg.Connection) -> dict[AssetRef, date]:
    """The first buy date of every asset ever bought, held or sold since."""
    rows = conn.execute(
        "select symbol, asset_type, min(bought_at) as day from lots group by symbol, asset_type"
    ).fetchall()
    return {AssetRef(r["symbol"], AssetType(r["asset_type"])): r["day"] for r in rows}


def write_fx_rates(conn: psycopg.Connection, rates: Sequence[tuple[date, float]]) -> None:
    """Store USD/CAD by day; a revised rate replaces the stored one."""
    if not rates:
        return
    with conn.cursor() as cur:
        cur.executemany(
            "insert into fx_rates (day, usd_cad) values (%s, %s)"
            " on conflict (day) do update set usd_cad = excluded.usd_cad"
            " where fx_rates.usd_cad <> excluded.usd_cad",
            list(rates),
        )


def earliest_fx_rate(conn: psycopg.Connection) -> date | None:
    return conn.execute("select min(day) as day from fx_rates").fetchone()["day"]


def prune_daily_closes(conn: psycopg.Connection, before: date, keep: Iterable[str]) -> int:
    """Delete closes from before `before`, except for assets ever bought and the `keep` symbols."""
    return conn.execute(
        "delete from daily_closes c where c.day < %s and c.symbol <> all(%s)"
        " and not exists (select 1 from lots l"
        "   where l.symbol = c.symbol and l.asset_type = c.asset_type)",
        (before, list(keep)),
    ).rowcount
```

- [ ] **Step 6: Run the tests and lint**

Run: `pipeline/scripts/in-docker.sh uv run pytest tests/integration/test_repo.py tests/integration/test_schema.py -q`
Expected: all pass.

Run: `pipeline/scripts/in-docker.sh uv run pytest -q`, then `pipeline/scripts/in-docker.sh uv run ruff check .`
Expected: 629 passed, and `All checks passed!`.

- [ ] **Step 7: Commit**

```bash
git add supabase/migrations/0006_price_history.sql pipeline/src/advisor/models.py \
  pipeline/src/advisor/store/repo.py pipeline/tests/integration/test_repo.py \
  pipeline/tests/integration/test_schema.py
git commit -m "feat: add daily_closes and fx_rates for the dashboard"
```

End the message with your `Co-Authored-By:` trailer.

---

### Task 2: The history module

**Files:**
- Modify: `pipeline/src/advisor/markets.py` (each market's benchmark)
- Create: `pipeline/src/advisor/history.py`
- Test: `pipeline/tests/unit/test_history.py`

**Interfaces:**
- Consumes:
  - Task 1's `DailyClose` and the `repo` queries;
  - `yfinance_bars.Downloader`, `parse_frame`, `to_yahoo` and `SYMBOLS_PER_DOWNLOAD`;
  - `boc_valet.VALET_URL` and `parse_observations`;
  - `prices.group_bars`;
  - `base.get_with_retries`.
- Produces:
  - `markets.BENCHMARKS == ("SPY", "XIU.TO")` and `MarketSpec.benchmark`;
  - `history.record(conn, *, today, stocks, stock_bars, coins, coin_bars, valet, download, http) -> dict`. The summary has `closes`, `backfilled`, `fx`, `rescaled` and `pruned`, plus `backfill_missing`, `backfill_error` and `fx_error` when they apply;
  - helpers: `currency_of`, `closes_from_bars`, `rebase_factor`, `store_closes`, `backfill_starts`, `download_closes`, `usd_cad`, `fetch_usd_cad`, `fx_backfill_start` and `BENCHMARK_REFS`.

**Design notes (the code below implements them):**
- **Rescaling.** Splits and dividends happen at the new end of the fresh window. Yahoo adjusts every close before them, so the oldest fresh days carry the factor that the older stored closes need. `rebase_factor` compares the 5 oldest overlapping days. It rescales only when their median moved more than 0.2% and at least three of them, or all of them if fewer than three overlap, agree within 1%. One bad quote therefore changes nothing.
- **Backfill.** Symbols ever bought, watched stocks and the benchmarks reach a year back, or to the first buy if that's earlier. A start within a week of the stored first day counts as reached (weekends and holidays). Coins need no backfill, because every run already fetches 290 days of Coinbase candles.

- [ ] **Step 1: Write the failing tests**

Create `pipeline/tests/unit/test_history.py`:

```python
from datetime import date, timedelta

import httpx
import pandas as pd
import pytest

from advisor.collectors.series import SeriesObservation
from advisor.history import (
    BENCHMARK_REFS,
    backfill_starts,
    closes_from_bars,
    currency_of,
    download_closes,
    fetch_usd_cad,
    fx_backfill_start,
    rebase_factor,
    usd_cad,
)
from advisor.models import AssetRef, AssetType, DailyClose
from fakes import bar

TODAY = date(2026, 10, 14)
AAPL = AssetRef("AAPL", AssetType.STOCK)
RY = AssetRef("RY.TO", AssetType.STOCK)
PLTR = AssetRef("PLTR", AssetType.STOCK)
BTC = AssetRef("BTC", AssetType.CRYPTO)
SPY, XIU = BENCHMARK_REFS
FIELDS = ["Open", "High", "Low", "Close", "Volume"]


def test_closes_carry_their_markets_currency():
    assert [currency_of(ref) for ref in (AAPL, RY, BTC)] == ["USD", "CAD", "USD"]
    bars = {
        "AAPL": [bar("AAPL", date(2026, 10, 13), 228.0)],
        "RY.TO": [bar("RY.TO", date(2026, 10, 13), 184.0)],
    }
    assert closes_from_bars(bars, [AAPL, RY, BTC]) == [
        DailyClose(AAPL, date(2026, 10, 13), 228.0, "USD"),
        DailyClose(RY, date(2026, 10, 13), 184.0, "CAD"),
    ]  # BTC had no bars


def fresh(*closes: float, start: date = date(2026, 7, 1)) -> list[DailyClose]:
    return [DailyClose(AAPL, start + timedelta(days=i), c, "USD") for i, c in enumerate(closes)]


def stored(*closes: float, start: date = date(2026, 7, 1)) -> dict[date, float]:
    return {start + timedelta(days=i): c for i, c in enumerate(closes)}


def test_unchanged_history_needs_no_rescale():
    assert rebase_factor(stored(100, 101, 102), fresh(100, 101, 102, 103)) is None
    assert rebase_factor(stored(100, 101, 102), fresh(100.1, 101.1, 102.1)) is None  # within 0.2%
    assert rebase_factor({}, fresh(100, 101)) is None  # nothing stored yet


def test_a_split_halves_older_closes():
    assert rebase_factor(stored(200, 202, 204, 206, 208), fresh(100, 101, 102, 103, 104)) == 0.5


def test_a_dividend_rescales_by_its_factor():
    assert rebase_factor(stored(100, 100, 100, 100), fresh(99, 99, 99, 99)) == pytest.approx(0.99)


def test_an_ex_dividend_day_inside_the_window_uses_the_oldest_days():
    # Yahoo lowered the closes before the 4th day by 1%; the days after it are unchanged.
    factor = rebase_factor(stored(100, 100, 100, 100, 100, 100), fresh(99, 99, 99, 100, 100, 100))
    assert factor == pytest.approx(0.99)


def test_a_single_bad_quote_changes_nothing():
    assert rebase_factor(stored(100, 100, 100, 100, 100), fresh(100, 50, 100, 100, 100)) is None


def test_days_that_disagree_change_nothing():
    assert rebase_factor(stored(100, 100, 100, 100, 100), fresh(50, 80, 120, 90, 70)) is None


def test_backfill_reaches_a_year_or_the_first_buy():
    buys = {AAPL: date(2025, 5, 12), RY: date(2026, 9, 1)}
    starts = backfill_starts(TODAY, buys, [PLTR, BTC], {RY: date(2025, 10, 20)})
    assert starts == {
        AAPL: date(2025, 5, 12),  # bought more than a year ago: from the first buy
        PLTR: date(2025, 10, 14),  # watched: a year
        SPY: date(2025, 5, 12),  # the benchmarks reach the oldest buy
        XIU: date(2025, 5, 12),
    }  # RY.TO is stored from within a week of a year ago; coins need no backfill


def test_nothing_to_backfill_once_stored():
    earliest = {AAPL: date(2025, 5, 12), SPY: date(2025, 5, 13), XIU: date(2025, 5, 14)}
    assert backfill_starts(TODAY, {AAPL: date(2025, 5, 12)}, [], earliest) == {}


def test_the_backfill_downloads_each_batch_from_its_earliest_start():
    calls = []

    def download(tickers, start, end):
        calls.append((tickers, start, end))
        index = pd.DatetimeIndex([pd.Timestamp("2025-05-12"), pd.Timestamp("2025-05-13")])
        columns = pd.MultiIndex.from_product([tickers, FIELDS])
        rows = [[10, 11, 9, 10.5, 1000] * len(tickers), [10.5, 12, 10, 11.0, 2000] * len(tickers)]
        return pd.DataFrame(rows, index=index, columns=columns)

    brk = AssetRef("BRK.B", AssetType.STOCK)
    closes = download_closes({brk: date(2025, 5, 12), RY: date(2025, 10, 14)}, TODAY, download)
    assert calls == [(["BRK-B", "RY.TO"], date(2025, 5, 12), date(2026, 10, 15))]
    assert {(c.ref.symbol, c.day, c.close, c.currency) for c in closes} == {
        ("BRK.B", date(2025, 5, 12), 10.5, "USD"), ("BRK.B", date(2025, 5, 13), 11.0, "USD"),
        ("RY.TO", date(2025, 5, 12), 10.5, "CAD"), ("RY.TO", date(2025, 5, 13), 11.0, "CAD"),
    }


def test_usd_cad_comes_from_the_valet_series():
    records = [
        SeriesObservation(series="FXUSDCAD", day=date(2026, 10, 13), value=1.3712),
        SeriesObservation(series="V39079", day=date(2026, 10, 13), value=2.25),
        SeriesObservation(series="FXUSDCAD", day=date(2026, 10, 9), value=1.3698),
    ]
    assert usd_cad(records) == [(date(2026, 10, 9), 1.3698), (date(2026, 10, 13), 1.3712)]


def test_the_fx_backfill_asks_the_bank_of_canada_from_its_start(fixtures_dir):
    seen = []
    body = (fixtures_dir / "boc" / "valet_observations_recent10.json").read_bytes()

    def handler(request):
        seen.append(request)
        return httpx.Response(200, content=body)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        rates = fetch_usd_cad(client, date(2025, 5, 12))
    assert seen[0].url.params["start_date"] == "2025-05-12"
    assert "FXUSDCAD" in seen[0].url.path
    assert len(rates) == 10 and all(1.2 < rate < 1.5 for _, rate in rates)


def test_the_fx_backfill_starts_at_the_oldest_buy_or_a_year_back():
    assert fx_backfill_start(TODAY, {AAPL: date(2025, 5, 12)}, None) == date(2025, 5, 12)
    assert fx_backfill_start(TODAY, {}, date(2026, 6, 16)) == date(2025, 10, 14)  # 120 days stored
    assert fx_backfill_start(TODAY, {}, date(2025, 10, 16)) is None  # within a week of a year
```

- [ ] **Step 2: Run them and see them fail**

Run: `pipeline/scripts/in-docker.sh uv run pytest tests/unit/test_history.py -q`
Expected: collection fails with `ModuleNotFoundError: No module named 'advisor.history'`.

- [ ] **Step 3: Add the benchmarks**

Replace `pipeline/src/advisor/markets.py` with:

```python
"""Per-market rules (spec §3 Markets): calendar, universe source, shortlist size and benchmark.

Hard-filter thresholds are the same numbers in each market's own currency, so they stay in
`advisor.screener`.
"""

from dataclasses import dataclass

from advisor.models import Market

TSX_SUFFIX = ".TO"


@dataclass(frozen=True)
class MarketSpec:
    market: Market
    calendar: str  # pandas_market_calendars name
    universe_source: str  # collector that lists the market's stocks
    min_universe: int  # fewer listed stocks than this means the directory was truncated
    shortlist_size: int
    benchmark: str  # what the market's picks are graded against, and the dashboard compares to


MARKETS: dict[Market, MarketSpec] = {
    Market.US: MarketSpec(Market.US, "NYSE", "nasdaq_symbols", 1000, 300, "SPY"),
    Market.TSX: MarketSpec(Market.TSX, "TSX", "tmx_symbols", 300, 100, "XIU.TO"),
}
BENCHMARKS: tuple[str, ...] = tuple(spec.benchmark for spec in MARKETS.values())


def market_of(symbol: str) -> Market:
    """The market a stock symbol trades on: Yahoo's `.TO` suffix marks the TSX."""
    return Market.TSX if symbol.endswith(TSX_SUFFIX) else Market.US
```

- [ ] **Step 4: Write the module**

Create `pipeline/src/advisor/history.py`:

```python
"""Daily closes and USD/CAD for the dashboard's charts and CAD values (Plan 5a).

**Closes.**
- Stocks: Yahoo's split- and dividend-adjusted closes from the run's bars, for holdings, the
  watchlist, the ranked shortlist and the two benchmarks (SPY, XIU.TO).
- Crypto: Coinbase's daily closes, in USD, for held and watched coins.
- A symbol ever bought, a watched stock and the benchmarks reach back a year, or to the first buy
  if that's earlier. The first run that finds one short backfills it from Yahoo in one call. Yahoo
  sometimes drops a symbol from a download (yfinance's cache can report "database is locked");
  it stays short, so the next run asks again. Coins need no backfill: every run already fetches
  290 days of candles.
- After two years, closes are pruned, except for symbols ever bought and the benchmarks.

**Splits and dividends.** Yahoo re-adjusts every close before a split or ex-dividend day. When a
run's oldest fresh closes all differ from the stored ones by one factor, the older stored closes
are rescaled by it, so a 2-for-1 split doesn't show as a 50% drop. A lone bad quote moves one
day, not all of them, so it changes nothing.

**USD/CAD.** The Bank of Canada's daily rate, from the run's Valet call, backfilled the same way.
"""

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, timedelta
from statistics import median

import httpx
import psycopg

from advisor.collectors.base import get_with_retries
from advisor.collectors.boc_valet import VALET_URL, parse_observations
from advisor.collectors.series import SeriesObservation
from advisor.collectors.yfinance_bars import SYMBOLS_PER_DOWNLOAD, Downloader, parse_frame, to_yahoo
from advisor.markets import BENCHMARKS, market_of
from advisor.models import AssetRef, AssetType, DailyBar, DailyClose, Market
from advisor.prices import group_bars
from advisor.store import repo

HISTORY = timedelta(days=365)
KEEP = timedelta(days=730)
SLACK = timedelta(days=7)  # a start that falls on a long weekend isn't a gap
OVERLAP_DAYS = 5  # the oldest fresh days compared with stored closes
REBASE_TOLERANCE = 0.002  # within 0.2%: the same adjustment
REBASE_AGREEMENT = 0.01  # days within 1% of the median ratio agree on it
USD_CAD = "FXUSDCAD"
BENCHMARK_REFS = tuple(AssetRef(symbol, AssetType.STOCK) for symbol in BENCHMARKS)


def currency_of(ref: AssetRef) -> str:
    if ref.asset_type is AssetType.CRYPTO:
        return "USD"  # Coinbase quotes coins in USD
    return "CAD" if market_of(ref.symbol) is Market.TSX else "USD"


def closes_from_bars(
    bars: Mapping[str, Sequence[DailyBar]], refs: Iterable[AssetRef]
) -> list[DailyClose]:
    return [
        DailyClose(ref, bar.day, bar.close, currency_of(ref))
        for ref in refs
        for bar in bars.get(ref.symbol, ())
    ]


def rebase_factor(stored: Mapping[date, float], fresh: Sequence[DailyClose]) -> float | None:
    """The factor older stored closes need because Yahoo re-adjusted history, or None.

    It compares the oldest fresh days that are also stored. They're older than any split or
    ex-dividend day inside the fresh window, so they carry the same adjustment as the stored rows
    before it. Most of them (all, with fewer than three) must agree on one factor.
    """
    overlap = sorted((c.day, c.close) for c in fresh if c.day in stored)[:OVERLAP_DAYS]
    if not overlap:
        return None
    ratios = [close / stored[day] for day, close in overlap]
    factor = median(ratios)
    if abs(factor - 1) <= REBASE_TOLERANCE:
        return None
    agreeing = [r for r in ratios if abs(r / factor - 1) <= REBASE_AGREEMENT]
    return factor if len(agreeing) >= min(3, len(ratios)) else None


def store_closes(conn: psycopg.Connection, closes: Sequence[DailyClose]) -> list[str]:
    """Write closes, first rescaling older stored ones that Yahoo re-adjusted.

    Returns the rescaled symbols.
    """
    by_ref: dict[AssetRef, list[DailyClose]] = defaultdict(list)
    for close in closes:
        by_ref[close.ref].append(close)
    if not by_ref:
        return []
    stored = repo.stored_closes(conn, by_ref, min(c.day for c in closes))
    rescaled = []
    for ref, fresh in by_ref.items():
        factor = rebase_factor(stored.get(ref, {}), fresh)
        if factor is not None:
            repo.rescale_closes(conn, ref, min(c.day for c in fresh), factor)
            rescaled.append(ref.symbol)
    repo.write_daily_closes(conn, closes)
    return sorted(rescaled)


def backfill_starts(
    today: date,
    first_buys: Mapping[AssetRef, date],
    watched: Iterable[AssetRef],
    earliest: Mapping[AssetRef, date],
) -> dict[AssetRef, date]:
    """Where each stock's closes should start, for those whose stored closes don't reach it."""
    year_ago = today - HISTORY
    wanted = {ref: min(year_ago, day) for ref, day in first_buys.items()}
    for ref in watched:
        wanted.setdefault(ref, year_ago)
    oldest_buy = min(first_buys.values(), default=year_ago)
    for ref in BENCHMARK_REFS:
        wanted[ref] = min(year_ago, oldest_buy)
    return {
        ref: start
        for ref, start in wanted.items()
        if ref.asset_type is AssetType.STOCK and (ref not in earliest or earliest[ref] > start + SLACK)
    }


def download_closes(
    starts: Mapping[AssetRef, date], today: date, download: Downloader
) -> list[DailyClose]:
    """Yahoo history for the backfill, 100 symbols a call, each call from its earliest start."""
    refs = sorted(starts, key=lambda ref: (starts[ref], ref.symbol))
    closes: list[DailyClose] = []
    for i in range(0, len(refs), SYMBOLS_PER_DOWNLOAD):
        batch = refs[i : i + SYMBOLS_PER_DOWNLOAD]
        yahoo = {to_yahoo(ref.symbol): ref.symbol for ref in batch}
        frame = download(list(yahoo), min(starts[ref] for ref in batch), today + timedelta(days=1))
        closes += closes_from_bars(group_bars(parse_frame(frame, yahoo)), batch)
    return closes


def usd_cad(records: Iterable[SeriesObservation]) -> list[tuple[date, float]]:
    return sorted({record.day: record.value for record in records if record.series == USD_CAD}.items())


def fetch_usd_cad(client: httpx.Client, start: date) -> list[tuple[date, float]]:
    response = get_with_retries(
        client, VALET_URL.format(series=USD_CAD), params={"start_date": start.isoformat()}
    )
    return usd_cad(parse_observations(response.json(), [USD_CAD]))


def fx_backfill_start(
    today: date, first_buys: Mapping[AssetRef, date], earliest: date | None
) -> date | None:
    start = min(today - HISTORY, min(first_buys.values(), default=today - HISTORY))
    return start if earliest is None or earliest > start + SLACK else None


def record(
    conn: psycopg.Connection,
    *,
    today: date,
    stocks: Iterable[str],
    stock_bars: Mapping[str, Sequence[DailyBar]],
    coins: Iterable[str],
    coin_bars: Mapping[str, Sequence[DailyBar]],
    valet: Iterable[SeriesObservation],
    download: Downloader | None,
    http: httpx.Client | None,
) -> dict:
    """The run's history step. A failed backfill is reported in the summary, not raised."""
    stock_refs = [AssetRef(s, AssetType.STOCK) for s in sorted(set(stocks))]
    coin_refs = [AssetRef(c, AssetType.CRYPTO) for c in sorted(set(coins))]
    closes = closes_from_bars(stock_bars, stock_refs) + closes_from_bars(coin_bars, coin_refs)
    rescaled = store_closes(conn, closes)
    summary: dict = {"closes": len(closes), "backfilled": [], "fx": 0}

    buys = repo.first_buys(conn)
    watched = repo.load_watchlist(conn)
    history_refs = {*buys, *watched, *BENCHMARK_REFS}
    starts = backfill_starts(today, buys, watched, repo.earliest_closes(conn, history_refs))
    if starts and download is not None:
        try:
            fetched = download_closes(starts, today, download)
            rescaled += store_closes(conn, fetched)
            got = {c.ref for c in fetched}
            summary["backfilled"] = sorted(ref.symbol for ref in got)
            if missing := sorted(ref.symbol for ref in starts if ref not in got):
                summary["backfill_missing"] = missing  # still short, so the next run asks again
        except Exception as exc:  # Yahoo is unofficial: a failed backfill waits for the next run
            summary["backfill_error"] = f"{type(exc).__name__}: {exc}"[:200]

    rates = usd_cad(valet)
    repo.write_fx_rates(conn, rates)
    fx_start = fx_backfill_start(today, buys, repo.earliest_fx_rate(conn))
    if fx_start is not None and http is not None:
        try:
            older = fetch_usd_cad(http, fx_start)
            repo.write_fx_rates(conn, older)
            rates += older
        except Exception as exc:
            summary["fx_error"] = f"{type(exc).__name__}: {exc}"[:200]
    summary["fx"] = len({day for day, _ in rates})
    summary["rescaled"] = sorted(set(rescaled))
    summary["pruned"] = repo.prune_daily_closes(conn, today - KEEP, BENCHMARKS)
    return summary
```

- [ ] **Step 5: Run the tests and lint**

Run: `pipeline/scripts/in-docker.sh uv run pytest tests/unit/test_history.py -q`
Expected: 13 passed.

Run: `pipeline/scripts/in-docker.sh uv run pytest -q`, then `pipeline/scripts/in-docker.sh uv run ruff check .`
Expected: 642 passed, and `All checks passed!`.

- [ ] **Step 6: Commit**

```bash
git add pipeline/src/advisor/markets.py pipeline/src/advisor/history.py pipeline/tests/unit/test_history.py
git commit -m "feat: turn bars into stored closes, with rescaling and a one-year backfill"
```

End the message with your `Co-Authored-By:` trailer.

---

### Task 3: Store the history from each run

**Files:**
- Modify: `pipeline/src/advisor/collectors/yfinance_bars.py` (a public `yahoo_download`)
- Modify: `pipeline/src/advisor/run.py`
- Test: `pipeline/tests/integration/test_run.py`, `pipeline/tests/integration/test_run_cli_db.py`
- Docs: `README.md`, `docs/superpowers/specs/2026-10-09-stock-advisor-design.md`, `docs/superpowers/deferred.md`

**Interfaces:**
- Consumes:
  - `history.record` and `markets.BENCHMARKS` (Task 2);
  - `repo.write_daily_closes` and `repo.stored_closes` (Task 1), used by the tests.
- Produces:
  - `RunDeps.download: Downloader | None = None` and `RunDeps.http: httpx.Client | None = None`;
  - `record_history(deps, now_utc, bars, candles, stocks, coins, results) -> dict` in `run.py`;
  - `summary["history"]`, which is `{}` for a run that can't publish.

**What changes in a run:**
- Phase 1 prices SPY and XIU.TO with the holdings, so even a run without holdings makes one small Yahoo call.
- In a run that can publish, the history step runs after the news stage, over the holdings, the ranked shortlist, the benchmarks and the held and watched coins.
- `main` passes the real Yahoo download and the shared HTTP client. Tests leave both off, so no test reaches the network.

- [ ] **Step 1: Update the tests whose expectations change**

In `pipeline/tests/integration/test_run.py`:

1. Add the imports:

```python
import pandas as pd
```

```python
from advisor.collectors.series import SeriesObservation
```

   Then change the models import to:

```python
from advisor.models import AssetRef, AssetType, DailyClose, Market, RunKind, RunStatus
```

2. In `test_successful_run_is_published_with_a_per_market_summary`, add this as the last key of the expected summary, after `"news"`:

```python
        # 70 closes for each shortlisted stock and for SPY and XIU.TO
        "history": {"closes": 490, "backfilled": [], "fx": 0, "rescaled": [], "pruned": 0},
```

   Then replace the next assertion with:

```python
    # The benchmarks are priced with the holdings, then one call covers both markets.
    assert deps.collectors["yfinance_bars"].calls == [["SPY", "XIU.TO"], EVERYONE]
```

3. In `test_holdings_of_both_markets_are_priced_first_and_get_features`, the first call gains the benchmarks:

```python
    assert deps.collectors["yfinance_bars"].calls == [["OTCX", "SHOP.TO", "SPY", "XIU.TO"], EVERYONE]
```

4. In `test_a_source_failing_in_one_phase_reports_one_partial_row`, phase 1 now asks for the holding and the benchmarks. Replace `records_for` with:

```python
    def records_for(symbols):  # phase 1 (the holding and the benchmarks) works, the bulk fetch fails
        if "SPY" not in symbols:
            raise httpx.ConnectError("down")
        return [b for s in symbols for b in history(s, 70, start=FRESH_START)]
```

5. In `test_a_truncated_universe_fails_the_run_and_keeps_that_markets_symbols`, replace the calls assertion with:

```python
    # Only the benchmarks (no holdings here): no bulk Yahoo fetch for a run that cannot publish.
    assert deps.collectors["yfinance_bars"].calls == [["SPY", "XIU.TO"]]
```

6. In `test_a_run_that_cannot_publish_still_retries_unpriced_holdings`, replace `records_for` and the calls assertion with:

```python
    def records_for(symbols):  # phase 1 misses the holding (not the benchmarks); the retry finds it
        missing = {"OTCX"} if "SPY" in symbols else set()
        return [b for s in symbols if s not in missing for b in history(s, 70, start=FRESH_START)]
```

```python
    assert prices.calls == [["OTCX", "SPY", "XIU.TO"], ["OTCX"]]  # the retry, but no bulk fetch
```

7. In `test_a_holding_missed_in_phase_one_is_retried_and_saved_in_phase_two`, replace the fake's `records_for` and the calls assertion with:

```python
        records_for=lambda syms: [  # phase 1 answers only the benchmarks
            b for s in syms if not ("SPY" in syms and s == "OTCX")
            for b in history(s, 70, start=FRESH_START)
        ],
```

```python
    assert prices.calls == [["OTCX", "SPY", "XIU.TO"], ["AAA", "BBB", "CCC", "OTCX", "RY.TO", "TD.TO"]]
```

In `pipeline/tests/integration/test_run_cli_db.py`, in `test_force_kind_runs_anyway_and_a_failed_run_exits_1`, add this right after the `build_registry` monkeypatch:

```python
    monkeypatch.setattr(  # a run that cannot publish leaves the price history alone
        "advisor.run.yahoo_download", lambda *args: pytest.fail("the CLI test must not reach Yahoo")
    )
```

- [ ] **Step 2: Write the new run tests**

Append to the end of `pipeline/tests/integration/test_run.py`:

```python
def closes_by_symbol(db):
    rows = db.execute(
        "select symbol, currency, count(*) as n from daily_closes"
        " group by symbol, currency order by symbol"
    ).fetchall()
    return [(r["symbol"], r["currency"], r["n"]) for r in rows]


def test_a_run_stores_closes_for_holdings_watchlist_shortlist_and_benchmarks(db, tmp_path):
    hold(db)
    db.execute("insert into watchlist (symbol, asset_type) values ('NVDA', 'stock')")
    outcome = execute_run(make_deps(db, tmp_path), RunKind.PRE_OPEN, NOW, min_universe=SMALL)

    assert closes_by_symbol(db) == [
        ("AAA", "USD", 70), ("BBB", "USD", 70), ("CCC", "USD", 70), ("NVDA", "USD", 70),
        ("OTCX", "USD", 70), ("RY.TO", "CAD", 70), ("SPY", "USD", 70), ("TD.TO", "CAD", 70),
        ("XIU.TO", "CAD", 70),
    ]
    assert outcome.summary["history"] == {
        "closes": 630, "backfilled": [], "fx": 0, "rescaled": [], "pruned": 0,
    }  # no backfill: these tests leave the Yahoo download off


def test_held_coins_get_coinbase_closes_in_usd(db, tmp_path):
    hold_crypto(db)
    execute_run(make_deps(db, tmp_path, extra=crypto_sources()), RunKind.PRE_OPEN, NOW, min_universe=SMALL)
    row = db.execute(
        "select count(*) as n, min(currency) as currency, max(close) as close from daily_closes"
        " where symbol = 'BTC' and asset_type = 'crypto'"
    ).fetchone()
    assert (row["n"], row["currency"], float(row["close"])) == (30, "USD", 82000.0)


def valet_source(records):
    return FakeCollector(
        "boc_valet", core=False, scope=Scope.MARKET, record_type=SeriesObservation,
        records_for=lambda _: records,
    )


def test_the_first_run_backfills_a_year_of_closes_and_usd_cad(db, tmp_path, fixtures_dir):
    hold(db)  # bought 2026-09-01, so a year back is the start
    calls = []

    def download(tickers, start, end):
        calls.append((sorted(tickers), start, end))
        index = pd.DatetimeIndex([pd.Timestamp("2025-10-14"), pd.Timestamp("2025-10-15")])
        columns = pd.MultiIndex.from_product([tickers, ["Open", "High", "Low", "Close", "Volume"]])
        return pd.DataFrame([[9, 9, 9, 9.0, 100] * len(tickers)] * 2, index=index, columns=columns)

    body = (fixtures_dir / "boc" / "valet_observations_recent10.json").read_bytes()
    asked = []

    def bank(request):
        asked.append(request.url.params["start_date"])
        return httpx.Response(200, content=body)

    run_rate = SeriesObservation(series="FXUSDCAD", day=date(2026, 10, 13), value=1.3712)
    with httpx.Client(transport=httpx.MockTransport(bank)) as client:
        deps = dataclasses.replace(
            make_deps(db, tmp_path, extra={"boc_valet": valet_source([run_rate])}),
            download=download, http=client,
        )
        outcome = execute_run(deps, RunKind.PRE_OPEN, NOW, min_universe=SMALL)

    assert calls == [(["OTCX", "SPY", "XIU.TO"], date(2025, 10, 14), date(2026, 10, 15))]
    history = outcome.summary["history"]
    assert history["backfilled"] == ["OTCX", "SPY", "XIU.TO"]
    first = db.execute("select min(day) as day from daily_closes where symbol = 'SPY'").fetchone()
    assert first["day"] == date(2025, 10, 14)
    assert asked == ["2025-10-14"]  # the run had only Oct 13; the bank fills the year
    rates = db.execute("select count(*) as n, max(day) as last from fx_rates").fetchone()
    assert history["fx"] == rates["n"] >= 10 and rates["last"] == date(2026, 10, 13)
    assert outcome.status is RunStatus.SUCCESS


def test_a_failed_backfill_is_reported_and_the_run_still_publishes(db, tmp_path):
    hold(db)

    def download(tickers, start, end):
        raise RuntimeError("Yahoo said no")

    deps = dataclasses.replace(make_deps(db, tmp_path), download=download)
    outcome = execute_run(deps, RunKind.PRE_OPEN, NOW, min_universe=SMALL)

    assert outcome.status is RunStatus.SUCCESS
    assert run_row(db, outcome.run_id)["published"] is True
    history = outcome.summary["history"]
    assert history["backfill_error"] == "RuntimeError: Yahoo said no"
    assert history["closes"] == 560  # the holding, 5 shortlisted stocks and 2 benchmarks, 70 each


def test_a_split_rescales_the_stored_history(db, tmp_path):
    # Before a 2-for-1 split OTCX closed at 20; the fresh, re-adjusted bars say 10 from Aug 5.
    otcx = AssetRef("OTCX", AssetType.STOCK)
    repo.write_daily_closes(db, [
        DailyClose(otcx, date(2026, 7, 1) + timedelta(days=i), 20.0, "USD") for i in range(70)
    ])
    hold(db)
    outcome = execute_run(make_deps(db, tmp_path), RunKind.PRE_OPEN, NOW, min_universe=SMALL)

    assert outcome.summary["history"]["rescaled"] == ["OTCX"]
    stored = repo.stored_closes(db, [otcx], date(2026, 7, 1))[otcx]
    assert set(stored.values()) == {10.0}  # July rescaled, the fresh window replaced
    assert min(stored) == date(2026, 7, 1)


def test_a_symbol_yahoo_drops_from_the_backfill_is_named_and_asked_again(db, tmp_path):
    hold(db)
    calls = []

    def download(tickers, start, end):  # Yahoo leaves the holding out of the answer
        calls.append(sorted(tickers))
        answered = [t for t in tickers if t != "OTCX"]
        index = pd.DatetimeIndex([pd.Timestamp("2025-10-14")])
        columns = pd.MultiIndex.from_product([answered, ["Open", "High", "Low", "Close", "Volume"]])
        return pd.DataFrame([[9, 9, 9, 9.0, 100] * len(answered)], index=index, columns=columns)

    deps = dataclasses.replace(make_deps(db, tmp_path), download=download)
    first = execute_run(deps, RunKind.PRE_OPEN, NOW, min_universe=SMALL)
    assert first.summary["history"]["backfilled"] == ["SPY", "XIU.TO"]
    assert first.summary["history"]["backfill_missing"] == ["OTCX"]

    second = execute_run(deps, RunKind.PRE_OPEN, NOW, min_universe=SMALL)
    assert calls[-1] == ["OTCX"]  # only the one still short
    assert second.summary["history"]["backfill_missing"] == ["OTCX"]


def test_a_bank_of_canada_outage_is_reported_and_the_run_keeps_its_closes(db, tmp_path):
    hold(db)
    run_rate = SeriesObservation(series="FXUSDCAD", day=date(2026, 10, 13), value=1.3712)
    down = httpx.MockTransport(lambda request: httpx.Response(404, text="not found"))
    with httpx.Client(transport=down) as client:
        deps = dataclasses.replace(
            make_deps(db, tmp_path, extra={"boc_valet": valet_source([run_rate])}), http=client
        )
        outcome = execute_run(deps, RunKind.PRE_OPEN, NOW, min_universe=SMALL)

    assert outcome.status is RunStatus.SUCCESS
    history = outcome.summary["history"]
    assert history["fx_error"].startswith("HTTPStatusError: HTTP 404")
    assert history["fx"] == 1 and history["closes"] == 560  # the run's own rate and closes are kept


def test_a_run_that_cannot_publish_leaves_the_price_history_alone(db, tmp_path):
    hold(db)
    deps = dataclasses.replace(
        make_deps(db, tmp_path), download=lambda *args: pytest.fail("no backfill for a failed run")
    )
    outcome = execute_run(deps, RunKind.PRE_OPEN, NOW, min_universe={Market.US: 3, Market.TSX: 300})

    assert outcome.status is RunStatus.FAILED
    assert outcome.summary["history"] == {}
    assert closes_by_symbol(db) == []
```

- [ ] **Step 3: Run them and see them fail**

Run: `pipeline/scripts/in-docker.sh uv run pytest tests/integration/test_run.py tests/integration/test_run_cli_db.py -q`
Expected: failures. The run tests show no `history` key and no benchmark calls. The CLI test fails with `AttributeError: <module 'advisor.run'> has no attribute 'yahoo_download'`.

- [ ] **Step 4: Give the Yahoo download a public name**

In `pipeline/src/advisor/collectors/yfinance_bars.py`, add this right after the `_yahoo_download` function:

```python
yahoo_download: Downloader = _yahoo_download  # the price-history backfill downloads the same way
```

- [ ] **Step 5: Wire the history step into the run**

In `pipeline/src/advisor/run.py`:

1. Imports. Add `import httpx` above `import psycopg`. Add these two lines in import order:

```python
from advisor.collectors.yfinance_bars import Downloader, yahoo_download
```

```python
from advisor.history import record as record_price_history
```

   Then replace the markets import with:

```python
from advisor.markets import BENCHMARKS, MARKETS, market_of
```

   (`advisor.history` is imported under a new name because `news_stage` has a local variable called `history`.)

2. Add these two fields at the end of `RunDeps`:

```python
    # The price-history backfill's Yahoo download and Bank of Canada client; tests leave them off.
    download: Downloader | None = None
    http: httpx.Client | None = None
```

3. Add this function right before `def execute_run(`:

```python
def record_history(
    deps: RunDeps,
    now_utc: datetime,
    bars: Mapping[str, Sequence[DailyBar]],
    candles: Mapping[str, Sequence[DailyBar]],
    stocks: Sequence[str],
    coins: Sequence[str],
    results: Mapping[str, CollectorResult],
) -> dict:
    """Store the dashboard's daily closes and USD/CAD (Plan 5a). Errors land in the summary."""
    valet = results.get("boc_valet")
    try:
        return record_price_history(
            deps.conn,
            today=now_utc.astimezone(ET).date(),
            stocks=stocks,
            stock_bars=bars,
            coins=coins,
            coin_bars=candles,
            valet=valet.records if valet is not None else [],
            download=deps.download,
            http=deps.http,
        )
    except Exception as exc:  # the price history is for the dashboard; it never fails a run
        return {"error": f"{type(exc).__name__}: {exc}"[:200]}
```

4. In `execute_run`, phase 1 prices the benchmarks too. Replace the comment and the `first = ...` line with:

```python
        # Phase 1: holdings and watchlist of both markets are priced and saved before anything
        # else can fail. The benchmarks come along for the dashboard's price history.
        first = fetch_prices([*priority, *BENCHMARKS])
```

5. Keep the coin candles for the history step. Add `candles` beside `quotes`:

```python
        quotes: dict[str, CryptoQuote] = {}
        candles: dict[str, list[DailyBar]] = {}
        if crypto:
```

   Inside `if crypto:`, the existing line `candles, checks = group_bars(...), group_bars(...)` now fills this variable.

6. Make the history step the last thing in the `if enriched:` block, and start with an empty summary:

```python
        news = empty_news_summary()
        price_history: dict = {}
        if enriched:
            results = run_enrichment(
                tracker,
                deps.collectors,
                [name for name in deps.collectors if name not in PRICE_STAGE | CRYPTO_STAGE],
                targets,
            )
            # Stage 5: the news stage, over what the news sources fetched.
            coin_names = {q.symbol: q.name for q in quotes.values() if q.name}
            news = news_stage(deps, run_id, results, targets, coin_names, now_utc, deadline_at)
            # Price history for the dashboard (Plan 5a), only from a run that can publish: a failed
            # run's prices may be why it failed. Its errors land in the summary, never fail the run.
            stocks = [*priority, *targets.ranked_stocks, *BENCHMARKS]
            price_history = record_history(deps, now_utc, bars, candles, stocks, crypto, results)
```

7. Add the summary key after `"news": news,`:

```python
            "history": price_history,
```

8. In `main`, pass the real download and the shared client to `RunDeps`:

```python
            deps = RunDeps(
                conn,
                DiskCache(settings.cache_dir, clock=lambda: now),
                build_registry(settings, client, names=names),
                names=names,
                news_scorer=load_finbert,
                download=yahoo_download,
                http=client,
            )
```

- [ ] **Step 6: Update the docs**

1. `README.md`, the upgrade note. Replace `` as in step 2: `0004` for Plan 2b, `0005` for Plan 2f) `` with:

```text
as in step 2: `0004` for Plan 2b, `0005` for Plan 2f, `0006` for Plan 5a)
```

2. In `docs/superpowers/specs/2026-10-09-stock-advisor-design.md`, make two edits in §4.3 and one in §8:
   - Stage 1 ends with the new sentence `SPY and XIU.TO are priced with them.`.
   - Stage 10 becomes: `10. **Publish.** Store the day's closes and USD/CAD for the dashboard (`daily_closes`, `fx_rates`, §8). Write a run summary (per-market counts included), then set `published = true`.`
   - Add two rows to the §8 table, after `models`:

```markdown
| `daily_closes` | symbol, asset_type, day, close, currency. Yahoo's adjusted closes for holdings, the watchlist, the shortlist and SPY and XIU.TO, reaching a year back or to the first buy; Coinbase closes in USD for held and watched coins. Pruned after 2 years, except symbols ever bought and the benchmarks |
| `fx_rates` | day, usd_cad. The Bank of Canada's daily rate, reaching a year back or to the first buy |
```

3. In `docs/superpowers/deferred.md`, add this as the first bullet under `## Plans 4 and 5: recommendations and dashboard`:

```markdown
- **Price history (Plan 5a):** `daily_closes` and `fx_rates` feed the charts and CAD values.
  - Stock closes are adjusted for splits and dividends, so returns from them are total returns, and the latest close is the actual price.
  - Coin closes are in USD; convert them, and US holdings, with the `fx_rates` row of the same day (the latest one for today's value).
  - The run summary's `history` says what was stored, backfilled, rescaled after a split, or missed.
```

   Add these as the first bullets under `## Operational and minor`:

```markdown
- **yfinance cache lock:** yfinance's timezone cache sometimes reports "database is locked" during a threaded download and drops a symbol. It hit RY.TO in phase 1 of the 2026-10-16 live run (phase 2's retry priced it) and SPY in Plan 5a's backfill (the next run fetched it). If it recurs, give yfinance a per-run cache folder or download without threads.
- **Coin history** reaches 290 days, one Coinbase request. A coin bought earlier has no closes before then; fetch older candles in more requests if the portfolio chart needs them.
```

- [ ] **Step 7: Run everything**

Run: `pipeline/scripts/in-docker.sh uv run pytest -q`, then `pipeline/scripts/in-docker.sh uv run ruff check .`
Expected: 650 passed, and `All checks passed!`.

- [ ] **Step 8: Commit**

```bash
git add pipeline/src/advisor/collectors/yfinance_bars.py pipeline/src/advisor/run.py \
  pipeline/tests/integration/test_run.py pipeline/tests/integration/test_run_cli_db.py \
  README.md docs/superpowers/specs/2026-10-09-stock-advisor-design.md docs/superpowers/deferred.md
git commit -m "feat: store each publishable run's closes and USD/CAD, and price the benchmarks"
```

End the message with your `Co-Authored-By:` trailer.

---

## After this plan

- **Live check (already done on the prototype, 2026-10-16).** The real Yahoo backfill stored 252 days each for BRK.B, RY.TO and XIU.TO, and the Bank of Canada sent 250 days of USD/CAD. yfinance's cache dropped SPY with "database is locked"; the next attempt fetched only SPY and stored its 252 days. After merging, repeat with a forced run (`uv run python -m advisor.run --force-kind pre_open` against the scratch database). Expect `summary.history.backfilled` to name the holdings and both benchmarks on the first run and nothing on the second.
- **Deployment.** Apply migration `0006` in the same window as the code. The first scheduled run backfills a year of closes and USD/CAD, which takes one Yahoo call and one Bank of Canada call.
- **Next:** Plan 5b, the dashboard (`web/`), which reads these tables.
