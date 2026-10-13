# Stock Advisor — Plan 2b: Keyless Prices and the Canada Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the pipeline keyless and two-market:
- Yahoo becomes the only stock price source, and Alpaca is removed;
- TSX stocks are scanned beside US stocks;
- the database records Wealthsimple accounts, currencies and owner-editable settings.

**Architecture:**
- **`advisor.markets`** holds spec §3's Markets table as data (calendar, universe source, minimum universe, shortlist size), plus `market_of(symbol)`: Yahoo's `.TO` suffix marks a TSX symbol.
- **Migration `0004`** does four things:
  - gives every stock a market;
  - accepts TSX symbols;
  - records account, currency and USD/CAD rate on buys and sells;
  - makes holding actions per account, picks and models per market, and adds a one-row `settings` table the owner can edit.
- **Schedule.** A slot runs when either market is open. Each market's freshness floor comes from its own calendar.
- **Prices.** `fetch_daily_bars` asks Yahoo once per phase. A >50% move is **flagged, not dropped**: there is no second source to confirm it.
- **Universes.** A new `tmx_symbols` collector loads the TSX universe from the TMX company directory.
- **Orchestrator.** Prices holdings of both markets first, loads both universes, then prices the rest in one Yahoo call. It judges each market against its own floor and minimum universe, and interleaves the two ranked shortlists for enrichment.

**Tech Stack:** Python 3.12, uv, httpx, pydantic v2, psycopg 3, pandas, pandas-market-calendars (NYSE and TSX), yfinance, pytest, ruff, Postgres 16 (Docker), Supabase, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-10-09-stock-advisor-design.md` (rev 2). Read §2 R7 and R11, §3 (Markets, Scheduling), §4.2 sources 1–3, §4.3 stages 1–4, §7.1, §8 and §10. Plans 1 and 2a built everything this plan modifies. `docs/superpowers/deferred.md` lists work earlier reviews pushed to later plans.

## Roadmap: Plan 2 after spec rev 2

| Sub-plan | Delivers |
|---|---|
| 2a. Collector stage | Done |
| **2b. Keyless prices and the Canada foundation** (this plan) | Markets module, migration 0004, two-market schedule, Yahoo-only prices with flagged jumps, TMX universe, two-market orchestrator |
| 2c. Collector infrastructure and market data | Run deadline, cadence-window cache, concurrent health check, collector contract; FINRA ×2, Yahoo analyst, Yahoo earnings, Bank of Canada FX |
| 2d. SEC | XBRL facts, 8-K, Form 4, 13F, 13D/G |
| 2e. Macro, options, crypto, catalysts | FRED, FOMC, Fear & Greed ×2, options ×2, CoinGecko, Coinbase, Kraken, on-chain ×2, catalysts ×4, Canadian short positions |
| 2f. News and social | News feeds (US and Canadian), social sources, de-duplication, ticker mapping, FinBERT |

## Plan-level decisions

These refine the spec without changing what it asks for. The spec edits that go with them are in the same commit as this plan.

- **A separate `settings` table** holds the fees and TFSA thresholds; spec §8 is updated to match. `app_config` keeps only `owner_id`, so the owner never gets write access to it. The owner may update the single `settings` row but not insert or delete rows.
- **TMX universe rules.** These were measured on the live directory on 2026-10-13: 675 equities kept.
  - Keep an instrument when its symbol is `^[A-Z]{1,5}(\.[A-Z]{1,2})?$`, its suffix is not in `{U, F, T, WT, DB, NT, RT, W, R}`, and neither the company nor the instrument name matches `\b(ETFs?|CDRs?|Funds?|Split|Portfolio|Pool|Notes?)\b`.
  - A `.UN` suffix is kept only when the company name matches `\b(REIT|Real Estate Investment Trust)\b`.
  - The canonical symbol is Yahoo's: `RCI.B` becomes `RCI-B.TO`.
  - TSX Venture is out of scope (spec §2).
- **TMX is core and best-effort.** A TMX outage serves the cached universe for up to 3 days and degrades the run (spec §11 risks).
- **Either market failing fails the run** (spec §10: "failed if a universe or prices can't be loaded"). Each failure reason names its market.
- **Enrichment order** after priority symbols and crypto: the US and TSX ranked shortlists are interleaved round-robin. A capped collector then reaches the best of both markets instead of only US names.
- **`data_conflict` is removed** from holding actions. It needed a second price source. A flagged jump now raises the Review badge (spec §7.3), in Plan 4.
- **USD trades need a USD/CAD rate.** This is enforced with a `NOT VALID` check, so rows from before rev 2 stay valid.

## Global Constraints

- Python `>=3.12,<3.13`, managed by uv, with `uv.lock` committed. Running cost is $0/month.
- **R7:** "Free data sources only, with no API keys and no accounts." No collector, setting or secret may need one.
- **Markets (spec §3):**

  | | US | TSX |
  |---|---|---|
  | Universe source | `nasdaq_symbols` | `tmx_symbols` |
  | Calendar | NYSE | TSX |
  | Minimum universe | 1000 | 300 |
  | Shortlist | 300 | 100 |
  | Hard filters | price ≥ 1, 20-day average dollar volume ≥ 1M, ≥ 60 sessions | same thresholds, in CAD |

- **Symbol formats (spec §8):**
  - US `^[A-Z]{1,5}(\.[A-Z])?$`;
  - TSX `^[A-Z]{1,5}(-[A-Z]{1,2})?\.TO$`;
  - crypto `^[A-Z0-9]{2,10}$`.
- **Scheduling (spec §3):** "A slot runs when at least one market is open that day and that market has that slot. Pre-close applies to markets closing at 16:00; early-close applies to markets closing at 13:00." Each market's freshness floor comes from its own calendar.
- **Jump rule (spec §10):** a daily move above 50%, against both the last accepted close and the previous close, is flagged as unconfirmed rather than dropped.
- **Holdings first (spec §3 rule 5):** holdings and the watchlist of both markets are priced and saved before anything else, and they come first in every collector's symbol list.
- Failed runs are never published.
- **Migrations are append-only.** Never edit `0001`–`0003`; this plan adds `0004`. Every table has RLS, an `owner_read` policy and a `pipeline_rw` policy, and tests enforce this.
- **Least privilege.** `pipeline_rw` is read-only on `lots`, `sells`, `watchlist`, `app_config` and `settings`.
- **Collectors** never touch the database. Their records carry the canonical symbol. They are tested against recorded real responses, with no live network in tests.
- **Tests run in the Linux container.** From the repo root: `pipeline/scripts/in-docker.sh uv run pytest -q`. Windows Application Control blocks psycopg's DLLs on the host, and `conftest.py` imports psycopg, so even unit tests run in the container.
- **Lint runs on the host** before every commit: `cd pipeline && uv run --no-sync ruff check .`. Use `--no-sync`, because a re-sync of `.venv` under OneDrive fails with "Access is denied".
- Never bypass git hooks: no `--no-verify`, no `-n`.
- Every commit message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. If a different model writes the commit, it names that model instead.

## Review Focus

These are the five inputs most likely to hurt the owner that no earlier test exercises. Each has a test in its owning task.

1. **One market closed while the other trades** (Canadian Thanksgiving 2026-10-12, US Thanksgiving 2026-11-26, 2026-11-27 when the NYSE closes at 13:00 and the TSX at 16:00). The right slots run, and each market's staleness is judged by its own calendar, not the NYSE's. *Tests: Task 2 schedule cases; Task 5 `test_each_market_is_judged_against_its_own_calendar`.*
2. **TMX answers with a block page, an empty list or a short list.** The collector raises, so the cached universe is served and the run degrades. It must not return a tiny universe that deactivates every TSX symbol. *Tests: Task 4.*
3. **Yahoo silently returns an empty frame for one 100-symbol download.** The source reports PARTIAL and the run is degraded, not silently OK. *Test: Task 3 `test_fetch_reports_partial_when_a_whole_download_comes_back_empty`.*
4. **A real >50% move on a held stock** (a biotech readout, a takeover). The bar is kept, the holding stays priced, and its features say `unconfirmed_jump: true`. The run is not failed. *Tests: Task 3 prices tests and `test_an_unconfirmed_jump_is_kept_and_flagged`; Task 5 again.*
5. **One market's universe comes back truncated.** The run fails unpublished. The truncated market's symbols stay active, and the other market's universe is still saved. *Tests: Task 1 `test_upsert_symbols_deactivates_only_within_its_market`; Task 5 `test_a_truncated_universe_fails_the_run_and_keeps_that_markets_symbols`.*

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `pipeline/src/advisor/markets.py` (new) | Spec §3 Markets table as data; `market_of` | 1 |
| `pipeline/src/advisor/models.py` | `Market` enum; `SymbolInfo.market` | 1 |
| `supabase/migrations/0004_markets_and_accounts.sql` (new) | Markets, TSX symbol formats, accounts and currency, per-account holding actions, per-market picks and models, `settings` | 1 |
| `pipeline/src/advisor/store/repo.py` | Per-market `upsert_symbols` | 1 |
| `pipeline/src/advisor/schedule.py` | Two-market slots; per-market sessions and floors | 2 |
| `pipeline/src/advisor/prices.py` | One Yahoo call; flag jumps | 3 |
| `pipeline/src/advisor/collectors/yfinance_bars.py` | Core price source; TSX symbols; partial downloads | 3 |
| `pipeline/src/advisor/collectors/alpaca_bars.py` | Deleted | 3 |
| `pipeline/src/advisor/config.py`, `collectors/registry.py` | No Alpaca keys | 3 |
| `pipeline/src/advisor/collectors/tmx_symbols.py` (new) | TSX universe (source 2) | 4 |
| `pipeline/src/advisor/enrich.py` | `interleave` | 5 |
| `pipeline/src/advisor/run.py` | Two-market orchestrator | 1, 3, 4, 5 |
| `pipeline/tests/fakes.py` | `info` per market; Yahoo-only and TSX fakes | 1, 3, 5 |
| `.github/workflows/*.yml`, `pipeline/scripts/in-docker.sh`, `README.md`, `docs/superpowers/deferred.md` | No Alpaca; two markets | 3, 4, 5 |

---

### Task 1: Markets module, migration 0004 and per-market symbols

**Files:**
- Create: `pipeline/src/advisor/markets.py`
- Create: `supabase/migrations/0004_markets_and_accounts.sql`
- Create: `pipeline/tests/unit/test_markets.py`
- Modify: `pipeline/src/advisor/models.py`
- Modify: `pipeline/src/advisor/collectors/nasdaq_symbols.py:72-91` (the two `SymbolInfo(...)` calls)
- Modify: `pipeline/src/advisor/store/repo.py:117-134` (`upsert_symbols`)
- Modify: `pipeline/src/advisor/run.py:121` (the `upsert_symbols` call)
- Modify: `pipeline/tests/fakes.py` (`info`)
- Test: `pipeline/tests/unit/test_models.py`, `pipeline/tests/unit/test_nasdaq_symbols.py`, `pipeline/tests/integration/test_schema.py`, `pipeline/tests/integration/test_repo.py`, `pipeline/tests/integration/test_run.py` (`hold`)

**Interfaces:**
- Consumes: nothing new.
- Produces (later tasks rely on these exact names):
  - `advisor.models.Market` — `StrEnum` with `US = "US"`, `TSX = "TSX"`, iterated in that order.
  - `advisor.models.SymbolInfo.market: Market | None` — required for stocks, `None` for crypto (validated).
  - `advisor.markets.MarketSpec(market, calendar, universe_source, min_universe, shortlist_size)`, `MARKETS: dict[Market, MarketSpec]`, `TSX_SUFFIX = ".TO"`, `market_of(symbol: str) -> Market`.
  - `repo.upsert_symbols(conn, market: Market, symbols: Sequence[SymbolInfo]) -> None`.
  - `fakes.info(symbol: str, exchange: str | None = None) -> SymbolInfo`, which infers the market from the symbol.
  - Tables `settings`, `symbols.market`, `lots/sells.account|currency|fx_rate_cad`, `holding_actions.account|warnings`, `picks.market`, `pick_outcomes.ret_net_of_fx`.

- [ ] **Step 1: Write the failing unit tests**

Create `pipeline/tests/unit/test_markets.py`:

```python
import pytest

from advisor.markets import MARKETS, market_of
from advisor.models import Market


@pytest.mark.parametrize(
    ("symbol", "market"),
    [
        ("AAPL", Market.US),
        ("BRK.B", Market.US),
        ("RY.TO", Market.TSX),
        ("RCI-B.TO", Market.TSX),
        ("REI-UN.TO", Market.TSX),
    ],
)
def test_market_of_reads_yahoos_tsx_suffix(symbol, market):
    assert market_of(symbol) is market


def test_markets_table_matches_spec_section_3():
    assert list(MARKETS) == [Market.US, Market.TSX]
    us, tsx = MARKETS[Market.US], MARKETS[Market.TSX]
    assert (us.calendar, us.universe_source, us.min_universe, us.shortlist_size) == (
        "NYSE", "nasdaq_symbols", 1000, 300,
    )
    assert (tsx.calendar, tsx.universe_source, tsx.min_universe, tsx.shortlist_size) == (
        "TSX", "tmx_symbols", 300, 100,
    )
    assert all(spec.market is market for market, spec in MARKETS.items())
```

Append to `pipeline/tests/unit/test_models.py`, and extend its import to `from advisor.models import AssetRef, AssetType, DailyBar, Market, SymbolInfo`:

```python
def test_symbol_info_needs_a_market_for_stocks_and_none_for_crypto():
    assert SymbolInfo(symbol="RY.TO", market=Market.TSX, name="Royal Bank", exchange="TSX").market is Market.TSX
    crypto = SymbolInfo(symbol="BTC", asset_type=AssetType.CRYPTO, name="Bitcoin", exchange="-")
    assert crypto.market is None
    with pytest.raises(ValidationError, match="stocks need a market and crypto has none"):
        SymbolInfo(symbol="AAPL", name="Apple", exchange="NASDAQ")
    with pytest.raises(ValidationError, match="stocks need a market and crypto has none"):
        SymbolInfo(
            symbol="BTC", asset_type=AssetType.CRYPTO, market=Market.US, name="Bitcoin", exchange="-"
        )
```

In `pipeline/tests/unit/test_nasdaq_symbols.py`, add `from advisor.models import Market` to the imports. Then add this line at the end of `test_fetch_merges_both_files_sorted_and_deduplicated`:

```python
    assert {r.market for r in records} == {Market.US}
```

- [ ] **Step 2: Write the failing integration tests**

In `pipeline/tests/integration/test_schema.py`, add this constant below `STRANGER`:

```python
AAPL_LOT = (
    "insert into lots (account, symbol, asset_type, qty, price, currency, fx_rate_cad, bought_at)"
    " values ('tfsa', 'AAPL', 'stock', 1, 100, 'USD', 1.37, '2026-10-01')"
)
```

Replace each of the five two-line literals below with `AAPL_LOT`. They appear in `test_owner_can_write_lots_but_not_runs`, `test_stranger_cannot_write_lots`, `test_owner_can_update_and_delete_lots`, `test_anon_cannot_write_lots` and the first statement of `test_pipeline_role_writes_pipeline_tables_but_only_reads_holdings`.

```python
"insert into lots (symbol, asset_type, qty, price, bought_at)"
" values ('AAPL', 'stock', 1, 100, '2026-10-01')"
```

In the denied-statement list of `test_pipeline_role_writes_pipeline_tables_but_only_reads_holdings`, replace the MSFT insert with:

```python
            "insert into lots (account, symbol, asset_type, qty, price, currency, fx_rate_cad,"
            " bought_at) values ('tfsa', 'MSFT', 'stock', 1, 100, 'USD', 1.37, '2026-10-01')",
```

Replace `test_malformed_stock_symbols_are_rejected` and `test_well_formed_stock_and_crypto_symbols_are_accepted` with:

```python
@pytest.mark.parametrize(
    "symbol", ["aapl", "BRK-B", " TSLA", "$TSLA", "ry.to", "RY.TSX", "RCI.B.TO", "REI-UNIT.TO", "RY-.TO"]
)
def test_malformed_stock_symbols_are_rejected(db, symbol):
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute("insert into watchlist (symbol, asset_type) values (%s, 'stock')", (symbol,))


@pytest.mark.parametrize("table", ["watchlist", "lots", "sells"])
def test_us_tsx_and_crypto_symbols_are_accepted_everywhere(db, table):
    for symbol, asset_type in [
        ("BRK.B", "stock"), ("RY.TO", "stock"), ("RCI-B.TO", "stock"), ("REI-UN.TO", "stock"),
        ("BTC", "crypto"),
    ]:
        if table == "watchlist":
            db.execute(
                "insert into watchlist (symbol, asset_type) values (%s, %s)", (symbol, asset_type)
            )
            continue
        day = "bought_at" if table == "lots" else "sold_at"
        db.execute(
            f"insert into {table} (account, symbol, asset_type, qty, price, currency, {day})"
            " values (%s, %s, %s, 1, 10, 'CAD', '2026-10-01')",
            ("crypto" if asset_type == "crypto" else "tfsa", symbol, asset_type),
        )
    assert db.execute(f"select count(*) as n from {table}").fetchone()["n"] == 5
```

Leave the `'alpaca_bars'` strings in `test_health_rows_have_no_run_and_run_rows_need_one` alone; Task 3 renames them.

Append these tests to `pipeline/tests/integration/test_schema.py`:

```python
def test_stocks_need_a_market_and_crypto_has_none(db):
    db.execute(
        "insert into symbols (symbol, asset_type, market, name, exchange) values"
        " ('RY.TO', 'stock', 'TSX', 'Royal Bank of Canada', 'TSX'), ('BTC', 'crypto', null, 'Bitcoin', '-')"
    )
    for values in [("AAPL", "stock", None), ("ETH", "crypto", "US"), ("VOD", "stock", "LSE")]:
        with pytest.raises(psycopg.errors.CheckViolation):
            db.execute(
                "insert into symbols (symbol, asset_type, market, name, exchange)"
                " values (%s, %s, %s, 'n', 'x')",
                values,
            )


def test_crypto_lives_only_in_the_crypto_account(db):
    lot = (
        "insert into lots (account, symbol, asset_type, qty, price, currency, bought_at)"
        " values (%s, %s, %s, 1, 10, 'CAD', '2026-10-01')"
    )
    db.execute(lot, ("crypto", "BTC", "crypto"))
    for values in [("tfsa", "ETH", "crypto"), ("crypto", "RY.TO", "stock"), ("cash", "RY.TO", "stock")]:
        with pytest.raises(psycopg.errors.CheckViolation):
            db.execute(lot, values)


def test_usd_trades_need_an_exchange_rate(db):
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(
            "insert into sells (account, symbol, asset_type, qty, price, currency, sold_at)"
            " values ('tfsa', 'AAPL', 'stock', 1, 100, 'USD', '2026-10-01')"
        )
    db.execute(
        "insert into sells (account, symbol, asset_type, qty, price, currency, sold_at)"
        " values ('tfsa', 'RY.TO', 'stock', 1, 100, 'CAD', '2026-10-01')"
    )


def test_holding_actions_are_per_account_without_data_conflict(db):
    run_id = db.execute(
        "insert into runs (kind, et_date) values ('pre_open', '2026-10-14') returning id"
    ).fetchone()["id"]
    action = (
        "insert into holding_actions (run_id, account, symbol, asset_type, action)"
        " values (%s, %s, 'AAPL', 'stock', %s)"
    )
    db.execute(action, (run_id, "tfsa", "hold"))
    db.execute(action, (run_id, "rrsp", "trim"))  # the same stock in a second account
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(action, (run_id, "fhsa", "data_conflict"))
    row = db.execute("select warnings from holding_actions where account = 'tfsa'").fetchone()
    assert row["warnings"] == []


def test_picks_and_models_are_per_market(db):
    run_id = db.execute(
        "insert into runs (kind, et_date) values ('pre_open', '2026-10-14') returning id"
    ).fetchone()["id"]
    pick = (
        "insert into picks (run_id, symbol, market, style, horizon_days, exit_by, entry_ref_price,"
        " stop, risk_level, risk_score, max_position_pct, rank)"
        " values (%s, 'RY.TO', %s, 'swing', 10, '2026-10-28', 10, 9, 'low', 0.1, 5, 1)"
    )
    db.execute(pick, (run_id, "TSX"))
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(pick, (run_id, None))
    db.execute("insert into models (version, kind, trained_at) values ('v1', 'stock_tsx', now())")
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute("insert into models (version, kind, trained_at) values ('v2', 'stock', now())")


def test_settings_has_one_seeded_row_that_only_the_owner_can_update(owned_db):
    row = owned_db.execute("select * from settings").fetchone()
    assert (
        row["usd_fx_fee_pct"], row["crypto_fee_pct"],
        row["tfsa_round_trips_warn"], row["tfsa_short_hold_share_warn"],
    ) == (1.5, 2.0, 24, 0.5)
    with acting_as(owned_db, "authenticated", OWNER):
        assert owned_db.execute("update settings set usd_fx_fee_pct = 1.0").rowcount == 1
        assert owned_db.execute("delete from settings").rowcount == 0  # no delete policy
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            owned_db.execute("insert into settings (id) values (1)")
    with acting_as(owned_db, "authenticated", STRANGER):
        assert owned_db.execute("select * from settings").fetchall() == []
        assert owned_db.execute("update settings set usd_fx_fee_pct = 9").rowcount == 0
    assert owned_db.execute("select usd_fx_fee_pct from settings").fetchone()["usd_fx_fee_pct"] == 1
    with pytest.raises(psycopg.errors.CheckViolation):
        owned_db.execute("update settings set tfsa_short_hold_share_warn = 1.5")


def test_pipeline_reads_settings_but_cannot_change_them(db):
    with acting_as(db, "pipeline_rw"):
        assert db.execute("select usd_fx_fee_pct from settings").fetchone()["usd_fx_fee_pct"] == 1.5
        for statement in (
            "update settings set usd_fx_fee_pct = 0",
            "delete from settings",
            "insert into settings (id) values (2)",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                db.execute(statement)
```

In `pipeline/tests/integration/test_repo.py`:
- add `Market` to the `advisor.models` import;
- replace `test_upsert_symbols_inserts_updates_and_deactivates` and `test_upsert_symbols_refuses_an_empty_stock_universe` with the code below;
- replace the two inserts in `test_load_held_symbols_nets_sells` with the code below. The assertion stays as it is.

```python
def test_upsert_symbols_deactivates_only_within_its_market(db):
    repo.upsert_symbols(db, Market.US, [info("AAPL"), info("GONE")])
    repo.upsert_symbols(db, Market.TSX, [info("RY.TO")])
    repo.upsert_symbols(db, Market.US, [info("AAPL", exchange="NASDAQ"), info("MSFT")])
    rows = db.execute(
        "select symbol, market, exchange, active from symbols order by symbol"
    ).fetchall()
    assert [(r["symbol"], r["market"], r["exchange"], r["active"]) for r in rows] == [
        ("AAPL", "US", "NASDAQ", True),
        ("GONE", "US", "NYSE", False),
        ("MSFT", "US", "NYSE", True),
        ("RY.TO", "TSX", "TSX", True),  # a US universe never deactivates TSX symbols
    ]


def test_upsert_symbols_refuses_empty_or_foreign_universes(db):
    repo.upsert_symbols(db, Market.US, [info("AAPL")])
    with pytest.raises(ValueError, match="refusing to upsert an empty US universe"):
        repo.upsert_symbols(db, Market.US, [])
    crypto = SymbolInfo(symbol="BTC", asset_type=AssetType.CRYPTO, name="Bitcoin", exchange="-")
    for strays in ([crypto], [info("AAPL"), info("RY.TO")]):
        with pytest.raises(ValueError, match="not US stocks"):
            repo.upsert_symbols(db, Market.US, strays)
    rows = db.execute("select symbol, active from symbols").fetchall()
    assert [(r["symbol"], r["active"]) for r in rows] == [("AAPL", True)]
```

```python
    db.execute(
        "insert into lots (account, symbol, asset_type, qty, price, currency, fx_rate_cad, bought_at)"
        " values ('tfsa', 'AAPL', 'stock', 10, 100, 'USD', 1.37, '2026-01-02'),"
        " ('tfsa', 'SOLD', 'stock', 5, 20, 'USD', 1.37, '2026-01-02'),"
        " ('crypto', 'BTC', 'crypto', 0.5, 60000, 'CAD', null, '2026-02-01')"
    )
    db.execute(
        "insert into sells (account, symbol, asset_type, qty, price, currency, fx_rate_cad, sold_at)"
        " values ('tfsa', 'AAPL', 'stock', 4, 120, 'USD', 1.36, '2026-05-01'),"
        " ('tfsa', 'SOLD', 'stock', 5, 25, 'USD', 1.36, '2026-05-01')"
    )
```

In `pipeline/tests/integration/test_run.py`, replace `hold` with:

```python
def hold(db, symbol="OTCX"):
    db.execute(
        "insert into lots (account, symbol, asset_type, qty, price, currency, fx_rate_cad, bought_at)"
        " values ('tfsa', %s, 'stock', 10, 5, 'USD', 1.37, '2026-09-01')",
        (symbol,),
    )
```

- [ ] **Step 3: Run the tests to verify they fail**

Run from the repo root: `pipeline/scripts/in-docker.sh uv run pytest tests/unit/test_markets.py tests/unit/test_models.py tests/integration/test_schema.py tests/integration/test_repo.py -q`

Expected: FAIL. `advisor.markets` doesn't exist, `Market` can't be imported, and the schema tests fail on the missing `account` column.

- [ ] **Step 4: Add `Market` and `SymbolInfo.market`**

In `pipeline/src/advisor/models.py`, change the imports and add the enum and field:

```python
from datetime import date
from enum import StrEnum
from typing import NamedTuple, Self
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator
```

```python
class Market(StrEnum):
    """Stock markets in scope (spec §3). Crypto belongs to no market."""

    US = "US"
    TSX = "TSX"
```

```python
class SymbolInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    asset_type: AssetType = AssetType.STOCK
    market: Market | None = None
    name: str
    exchange: str

    @model_validator(mode="after")
    def _market_matches_asset_type(self) -> Self:
        if (self.asset_type is AssetType.STOCK) != (self.market is not None):
            raise ValueError("stocks need a market and crypto has none")
        return self
```

Create `pipeline/src/advisor/markets.py`:

```python
"""Per-market rules (spec §3 Markets): calendar, universe source, and shortlist size.

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


MARKETS: dict[Market, MarketSpec] = {
    Market.US: MarketSpec(Market.US, "NYSE", "nasdaq_symbols", 1000, 300),
    Market.TSX: MarketSpec(Market.TSX, "TSX", "tmx_symbols", 300, 100),
}


def market_of(symbol: str) -> Market:
    """The market a stock symbol trades on: Yahoo's `.TO` suffix marks the TSX."""
    return Market.TSX if symbol.endswith(TSX_SUFFIX) else Market.US
```

In `pipeline/src/advisor/collectors/nasdaq_symbols.py`, import `Market` (`from advisor.models import AssetType, Market, SymbolInfo`). Pass `market=Market.US` in both `SymbolInfo(...)` calls:

```python
def parse_nasdaq_listed(text: str) -> list[SymbolInfo]:
    return [
        SymbolInfo(
            symbol=row["Symbol"], market=Market.US, name=row["Security Name"], exchange="NASDAQ"
        )
        for row in _rows(text)
        if _keep(row["Symbol"], row["Security Name"], row["ETF"], row["Test Issue"])
    ]


def parse_other_listed(text: str) -> list[SymbolInfo]:
    return [
        SymbolInfo(
            symbol=row["ACT Symbol"],
            market=Market.US,
            name=row["Security Name"],
            exchange=OTHER_EXCHANGES.get(row["Exchange"], row["Exchange"]),
        )
        for row in _rows(text)
        if _keep(row["ACT Symbol"], row["Security Name"], row["ETF"], row["Test Issue"])
    ]
```

In `pipeline/tests/fakes.py`, import `market_of` (`from advisor.markets import market_of`) and `Market` (`from advisor.models import AssetType, DailyBar, Market, SymbolInfo`), then replace `info`:

```python
def info(symbol: str, exchange: str | None = None) -> SymbolInfo:
    market = market_of(symbol)
    default_exchange = "TSX" if market is Market.TSX else "NYSE"
    return SymbolInfo(
        symbol=symbol,
        market=market,
        name=f"{symbol} Inc. Common Stock",
        exchange=exchange or default_exchange,
    )
```

- [ ] **Step 5: Write migration 0004**

Create `supabase/migrations/0004_markets_and_accounts.sql`. This SQL was checked against a database holding rows from before rev 2.

```sql
-- Plan 2b (spec rev 2): TSX stocks beside US stocks, Wealthsimple accounts, per-market models,
-- and owner-editable settings.

-- Every stock belongs to one market; crypto belongs to none. Rows before rev 2 are US stocks.
alter table symbols add column market text check (market in ('US', 'TSX'));
update symbols set market = 'US' where asset_type = 'stock';
alter table symbols add constraint symbols_market_matches_asset_type
  check ((asset_type = 'stock') = (market is not null));

-- Symbol formats (spec §8): US, TSX in Yahoo's form (RY.TO, RCI-B.TO, REI-UN.TO), and crypto.
do $$
declare
  t text;
begin
  foreach t in array array['watchlist', 'lots', 'sells'] loop
    execute format('alter table public.%I drop constraint %I', t, t || '_symbol_format');
    execute format($f$
      alter table public.%I add constraint %I check (
        (asset_type = 'stock' and (symbol ~ '^[A-Z]{1,5}(\.[A-Z])?$'
                                   or symbol ~ '^[A-Z]{1,5}(-[A-Z]{1,2})?\.TO$'))
        or (asset_type = 'crypto' and symbol ~ '^[A-Z0-9]{2,10}$'))$f$,
      t, t || '_symbol_format');
  end loop;
end $$;

-- Buys and sells record their account, trade currency and USD/CAD rate (spec §7.1). Rows from
-- before rev 2 are US stocks (held in the TFSA, traded in USD) or crypto (crypto account, CAD).
do $$
declare
  t text;
begin
  foreach t in array array['lots', 'sells'] loop
    execute format($f$
      alter table public.%I
        add column account text
          check (account in ('tfsa', 'rrsp', 'fhsa', 'non_registered', 'crypto')),
        add column currency text check (currency in ('CAD', 'USD')),
        add column fx_rate_cad numeric check (fx_rate_cad > 0)$f$, t);
    execute format($f$
      update public.%I set
        account = case when asset_type = 'crypto' then 'crypto' else 'tfsa' end,
        currency = case when asset_type = 'crypto' then 'CAD' else 'USD' end$f$, t);
    execute format(
      'alter table public.%I alter column account set not null, alter column currency set not null',
      t);
    execute format(
      'alter table public.%I add constraint %I check ((asset_type = ''crypto'') = (account = ''crypto''))',
      t, t || '_crypto_account');
    -- not valid: rows from before rev 2 have no rate; every new USD trade needs one.
    execute format(
      'alter table public.%I add constraint %I check (currency = ''CAD'' or fx_rate_cad is not null) not valid',
      t, t || '_usd_needs_fx_rate');
  end loop;
end $$;

-- Holding actions are per account. 'data_conflict' needed a second price source, which rev 2
-- removed. Nothing writes this table before Plan 4, so the new not-null column is safe.
alter table holding_actions
  drop column days_to_long_term,
  add column account text not null
    check (account in ('tfsa', 'rrsp', 'fhsa', 'non_registered', 'crypto')),
  add column warnings jsonb not null default '[]'::jsonb,
  drop constraint holding_actions_action_check,
  add constraint holding_actions_action_check check (action in ('sell', 'trim', 'add', 'hold')),
  add constraint holding_actions_crypto_account check ((asset_type = 'crypto') = (account = 'crypto')),
  drop constraint holding_actions_pkey,
  add primary key (run_id, account, symbol, asset_type);

-- Picks, grading and models are per market (spec §6, §8). Nothing writes these before Plan 3.
alter table picks
  add column market text check (market in ('US', 'TSX')),
  add constraint picks_market_matches_asset_type check ((asset_type = 'stock') = (market is not null));
alter table pick_outcomes add column ret_net_of_fx double precision not null;
alter table models
  drop constraint models_kind_check,
  add constraint models_kind_check check (kind in ('stock_us', 'stock_tsx', 'crypto'));

-- Owner-editable settings (spec §3, §7.5): one row the owner may update but never add or remove.
-- Kept apart from app_config so the owner never gets write access to owner_id.
create table settings (
  id int primary key default 1 check (id = 1),
  usd_fx_fee_pct numeric not null default 1.5 check (usd_fx_fee_pct between 0 and 10),
  crypto_fee_pct numeric not null default 2.0 check (crypto_fee_pct between 0 and 10),
  tfsa_round_trips_warn int not null default 24 check (tfsa_round_trips_warn > 0),
  tfsa_short_hold_share_warn numeric not null default 0.5
    check (tfsa_short_hold_share_warn > 0 and tfsa_short_hold_share_warn <= 1),
  updated_at timestamptz not null default now()
);
insert into settings (id) values (1);

alter table settings enable row level security;
create policy owner_read on settings for select to authenticated using ((select public.is_owner()));
create policy owner_update on settings for update to authenticated
  using ((select public.is_owner())) with check ((select public.is_owner()));
create policy pipeline_read on settings for select to pipeline_rw using (true);
grant select on settings to pipeline_rw;
revoke insert, update, delete on settings from pipeline_rw;
```

- [ ] **Step 6: Make `upsert_symbols` per market**

In `pipeline/src/advisor/store/repo.py`, add `Market` to the `advisor.models` import and replace `upsert_symbols`:

```python
def upsert_symbols(conn: psycopg.Connection, market: Market, symbols: Sequence[SymbolInfo]) -> None:
    """Upsert one market's stock universe; that market's stocks missing from it are deactivated."""
    if not symbols:  # would deactivate the whole market
        raise ValueError(f"refusing to upsert an empty {market} universe")
    strays = sorted(s.symbol for s in symbols if s.market is not market)
    if strays:
        raise ValueError(f"not {market} stocks: {', '.join(strays[:5])}")
    with conn.transaction():
        with conn.cursor() as cur:
            cur.executemany(
                "insert into symbols (symbol, asset_type, market, name, exchange, active, updated_at)"
                " values (%s, 'stock', %s, %s, %s, true, now())"
                " on conflict (symbol, asset_type) do update set market = excluded.market,"
                " name = excluded.name, exchange = excluded.exchange, active = true,"
                " updated_at = now()",
                [(s.symbol, market.value, s.name, s.exchange) for s in symbols],
            )
        conn.execute(
            "update symbols set active = false, updated_at = now()"
            " where asset_type = 'stock' and market = %s and active and not (symbol = any(%s))",
            (market.value, [s.symbol for s in symbols]),
        )
```

In `pipeline/src/advisor/run.py`, add `Market` to the `advisor.models` import and change the call in phase 2:

```python
        if universe_ok:
            repo.upsert_symbols(conn, Market.US, universe)
```

- [ ] **Step 7: Run the full suite and lint**

Run from the repo root: `pipeline/scripts/in-docker.sh uv run pytest -q`
Expected: every test passes, including the existing `test_every_public_table_has_row_level_security` and `test_every_table_except_migrations_has_a_pipeline_policy`, which now also cover `settings`.

Run: `cd pipeline && uv run --no-sync ruff check .`
Expected: `All checks passed!`

- [ ] **Step 8: Commit**

```bash
git add supabase/migrations/0004_markets_and_accounts.sql pipeline/src/advisor/markets.py \
  pipeline/src/advisor/models.py pipeline/src/advisor/collectors/nasdaq_symbols.py \
  pipeline/src/advisor/store/repo.py pipeline/src/advisor/run.py pipeline/tests
git commit -m "feat: add markets, TSX symbols, accounts and settings (migration 0004)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Two-market schedule

**Files:**
- Modify: `pipeline/src/advisor/schedule.py`
- Test: `pipeline/tests/unit/test_schedule.py`

**Interfaces:**
- Consumes: `Market`, `MARKETS[market].calendar` (Task 1).
- Produces:
  - `market_close_et(day: date, market: Market = Market.US) -> time | None`
  - `previous_sessions(end: date, count: int, market: Market = Market.US) -> list[date]`
  - `expected_last_session(kind: RunKind, now_utc: datetime, market: Market = Market.US) -> date`
  - `freshness_floor(kind, now_utc, allowed_lag_sessions: int = 1, *, market: Market = Market.US) -> date`

  `resolve_run_kind` and `missed_run_kind` keep their signatures and now consider both markets.

These calendar facts were verified with pandas-market-calendars on 2026-10-13. All times are ET, and the two markets' sessions are listed for each date.

| Date | NYSE | TSX |
|---|---|---|
| 2026-10-08, 10-09, 10-13, 10-14 | 16:00 | 16:00 |
| 2026-10-12 (Canadian Thanksgiving) | 16:00 | closed |
| 2026-11-26 (US Thanksgiving) | closed | 16:00 |
| 2026-11-27 | 13:00 | 16:00 |
| 2026-12-24 | 13:00 | 13:00 |
| 2026-12-25 | closed | closed |

DST ends 2026-11-01. In October, 08:15/12:15/15:15 ET are 12:15/16:15/19:15 UTC. In November and December they are 13:15/17:15/20:15 UTC.

- [ ] **Step 1: Write the failing tests**

Replace `pipeline/tests/unit/test_schedule.py` with:

```python
from datetime import UTC, date, datetime, time

import pytest

from advisor.models import Market, RunKind
from advisor.schedule import (
    expected_last_session,
    freshness_floor,
    market_close_et,
    missed_run_kind,
    previous_sessions,
    resolve_run_kind,
)


def utc(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        ("2026-10-14T12:15:00", RunKind.PRE_OPEN),     # EDT 08:15 ET
        ("2026-10-14T13:15:00", None),                 # EDT 09:15 ET (the EST cron)
        ("2026-10-14T12:40:00", RunKind.PRE_OPEN),     # 25 min late: still inside window
        ("2026-10-14T12:50:00", None),                 # 35 min late: outside window
        ("2026-10-14T19:15:00", RunKind.PRE_CLOSE),    # EDT 15:15 ET
        ("2026-10-14T16:15:00", None),                 # early-close cron on a normal day
        ("2026-12-02T13:15:00", RunKind.PRE_OPEN),     # EST 08:15 ET
        ("2026-12-02T12:15:00", None),                 # EST 07:15 ET (the EDT cron)
        ("2026-12-02T20:15:00", RunKind.PRE_CLOSE),    # EST 15:15 ET
        ("2026-10-17T12:15:00", None),                 # Saturday
        ("2026-10-12T12:15:00", RunKind.PRE_OPEN),     # Canadian Thanksgiving: the NYSE trades
        ("2026-10-12T19:15:00", RunKind.PRE_CLOSE),
        ("2026-11-26T13:15:00", RunKind.PRE_OPEN),     # US Thanksgiving: the TSX trades
        ("2026-11-26T17:15:00", None),                 # no market closes early that day
        ("2026-11-26T20:15:00", RunKind.PRE_CLOSE),    # the TSX closes at 16:00
        ("2026-11-27T13:15:00", RunKind.PRE_OPEN),
        ("2026-11-27T17:15:00", RunKind.EARLY_CLOSE),  # the NYSE closes at 13:00
        ("2026-11-27T20:15:00", RunKind.PRE_CLOSE),    # the TSX still closes at 16:00
        ("2026-12-24T17:15:00", RunKind.EARLY_CLOSE),  # both close at 13:00
        ("2026-12-24T20:15:00", None),                 # both already closed
        ("2026-12-25T13:15:00", None),                 # Christmas: both closed
    ],
)
def test_resolve_run_kind(now, expected):
    assert resolve_run_kind(utc(now)) == expected


def test_market_close_et_reports_each_markets_own_calendar():
    assert market_close_et(date(2026, 10, 14)) == time(16, 0)
    assert market_close_et(date(2026, 11, 27)) == time(13, 0)
    assert market_close_et(date(2026, 11, 26)) is None
    assert market_close_et(date(2026, 11, 26), Market.TSX) == time(16, 0)
    assert market_close_et(date(2026, 11, 27), Market.TSX) == time(16, 0)
    assert market_close_et(date(2026, 10, 12), Market.TSX) is None
    assert market_close_et(date(2026, 12, 24), Market.TSX) == time(13, 0)


@pytest.mark.parametrize(
    ("now", "resolved", "missed"),
    [
        ("2026-10-14T12:05:00", RunKind.PRE_OPEN, None),  # 08:05 ET: earliest accepted
        ("2026-10-14T12:04:00", None, None),              # 08:04 ET: too early, not missed
        ("2026-10-14T12:45:00", RunKind.PRE_OPEN, None),  # 08:45 ET: latest accepted
        ("2026-10-14T12:46:00", None, RunKind.PRE_OPEN),  # 08:46 ET: own cron running late
        ("2026-10-14T13:14:00", None, RunKind.PRE_OPEN),  # 09:14 ET: still own cron, late
        ("2026-10-14T13:15:00", None, None),              # 09:15 ET: the EST decoy cron
        ("2026-12-02T12:15:00", None, None),              # 07:15 EST: the EDT decoy cron
        ("2026-12-24T20:15:00", None, None),              # 15:15 ET when both closed at 13:00
        ("2026-11-26T13:46:00", None, RunKind.PRE_OPEN),  # US holiday: the TSX slot was missed
    ],
)
def test_missed_run_kind_flags_only_a_slots_own_late_cron(now, resolved, missed):
    assert resolve_run_kind(utc(now)) == resolved
    assert missed_run_kind(utc(now)) == missed


def test_missed_run_kind_is_none_on_closed_days():
    assert missed_run_kind(utc("2026-10-17T12:46:00")) is None  # Saturday
    assert missed_run_kind(utc("2026-12-25T13:46:00")) is None  # Christmas


def test_previous_sessions_skips_each_markets_holidays_and_is_ascending():
    assert previous_sessions(date(2026, 11, 27), 3) == [
        date(2026, 11, 24), date(2026, 11, 25), date(2026, 11, 27),
    ]
    assert previous_sessions(date(2026, 10, 13), 3, Market.TSX) == [
        date(2026, 10, 8), date(2026, 10, 9), date(2026, 10, 13),
    ]


@pytest.mark.parametrize(
    ("kind", "now", "market", "last_session", "floor"),
    [
        (RunKind.PRE_OPEN, "2026-10-14T12:15:00", Market.US, date(2026, 10, 13), date(2026, 10, 12)),
        (RunKind.PRE_CLOSE, "2026-10-14T19:15:00", Market.US, date(2026, 10, 14), date(2026, 10, 13)),
        (RunKind.PRE_OPEN, "2026-10-19T12:15:00", Market.US, date(2026, 10, 16), date(2026, 10, 15)),
        (RunKind.PRE_OPEN, "2026-11-27T13:15:00", Market.US, date(2026, 11, 25), date(2026, 11, 24)),
        # The day after Canadian Thanksgiving: the NYSE traded on 10-12, the TSX did not.
        (RunKind.PRE_OPEN, "2026-10-13T12:15:00", Market.US, date(2026, 10, 12), date(2026, 10, 9)),
        (RunKind.PRE_OPEN, "2026-10-13T12:15:00", Market.TSX, date(2026, 10, 9), date(2026, 10, 8)),
        (RunKind.PRE_OPEN, "2026-10-14T12:15:00", Market.TSX, date(2026, 10, 13), date(2026, 10, 9)),
        # A pre-close run on US Thanksgiving: only the TSX has a session today.
        (RunKind.PRE_CLOSE, "2026-11-26T20:15:00", Market.US, date(2026, 11, 25), date(2026, 11, 24)),
        (RunKind.PRE_CLOSE, "2026-11-26T20:15:00", Market.TSX, date(2026, 11, 26), date(2026, 11, 25)),
    ],
)
def test_expected_last_session_and_freshness_floor(kind, now, market, last_session, floor):
    assert expected_last_session(kind, utc(now), market) == last_session
    assert freshness_floor(kind, utc(now), market=market) == floor


def test_market_defaults_to_us():
    now = utc("2026-10-13T12:15:00")
    assert freshness_floor(RunKind.PRE_OPEN, now) == freshness_floor(
        RunKind.PRE_OPEN, now, market=Market.US
    )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pipeline/scripts/in-docker.sh uv run pytest tests/unit/test_schedule.py -q`
Expected: FAIL. The US-Thanksgiving and 2026-11-27 pre-close cases resolve to `None`, and `market_close_et` and `expected_last_session` reject the `market` argument.

- [ ] **Step 3: Implement the two-market schedule**

Replace `pipeline/src/advisor/schedule.py` with:

```python
"""Decides whether 'now' falls in a run window on a trading day of either market (spec §3).

GitHub cron is UTC-only, so each run has one cron for EDT and one for EST. This guard
accepts exactly one of them, and only on days a market calendar says are right. The NYSE
and the TSX both keep Eastern time, so one set of ET targets serves both markets.
"""

from datetime import date, datetime, time, timedelta
from functools import cache

import pandas_market_calendars as mcal

from advisor.markets import MARKETS
from advisor.models import ET, Market, RunKind

TARGETS: dict[RunKind, time] = {
    RunKind.PRE_OPEN: time(8, 15),
    RunKind.EARLY_CLOSE: time(12, 15),
    RunKind.PRE_CLOSE: time(15, 15),
}
EARLY_TOLERANCE = timedelta(minutes=10)
LATE_TOLERANCE = timedelta(minutes=30)
# A trigger 30-60 min after its target can only be that slot's own cron running late; the
# other-DST cron always lands 60 or more minutes off.
MISSED_HORIZON = timedelta(minutes=60)
NORMAL_CLOSE = time(16, 0)


@cache
def _calendar(market: Market) -> mcal.MarketCalendar:
    return mcal.get_calendar(MARKETS[market].calendar)


def market_close_et(day: date, market: Market = Market.US) -> time | None:
    """Closing time in ET for `day`, or None when `market` is closed."""
    schedule = _calendar(market).schedule(start_date=day.isoformat(), end_date=day.isoformat())
    if schedule.empty:
        return None
    return schedule.iloc[0]["market_close"].tz_convert("America/New_York").time()


def _todays_slots(now_et: datetime) -> list[tuple[RunKind, datetime]]:
    """Run slots on `now_et`'s date: pre-open when any market is open, early-close for a market
    closing before 16:00, pre-close for one closing at 16:00. A split day has both."""
    closes = [market_close_et(now_et.date(), market) for market in Market]
    open_closes = [close for close in closes if close is not None]
    if not open_closes:
        return []
    kinds = [RunKind.PRE_OPEN]
    if any(close < NORMAL_CLOSE for close in open_closes):
        kinds.append(RunKind.EARLY_CLOSE)
    if any(close >= NORMAL_CLOSE for close in open_closes):
        kinds.append(RunKind.PRE_CLOSE)
    return [(kind, datetime.combine(now_et.date(), TARGETS[kind], tzinfo=ET)) for kind in kinds]


def resolve_run_kind(now_utc: datetime) -> RunKind | None:
    now_et = now_utc.astimezone(ET)
    for kind, scheduled in _todays_slots(now_et):
        if scheduled - EARLY_TOLERANCE <= now_et <= scheduled + LATE_TOLERANCE:
            return kind
    return None


def missed_run_kind(now_utc: datetime) -> RunKind | None:
    """The slot whose own trigger arrived too late to run (past LATE_TOLERANCE), if any."""
    now_et = now_utc.astimezone(ET)
    for kind, scheduled in _todays_slots(now_et):
        if scheduled + LATE_TOLERANCE < now_et < scheduled + MISSED_HORIZON:
            return kind
    return None


def previous_sessions(end: date, count: int, market: Market = Market.US) -> list[date]:
    """The `count` most recent `market` session dates on or before `end`, ascending."""
    schedule = _calendar(market).schedule(
        start_date=(end - timedelta(days=count * 2 + 10)).isoformat(), end_date=end.isoformat()
    )
    return [stamp.date() for stamp in schedule.index][-count:]


def expected_last_session(kind: RunKind, now_utc: datetime, market: Market = Market.US) -> date:
    """Latest `market` session whose daily bar should exist: the latest one on or before today
    for pre-close and early-close runs, before today for pre-open runs."""
    today = now_utc.astimezone(ET).date()
    end = today if kind in (RunKind.PRE_CLOSE, RunKind.EARLY_CLOSE) else today - timedelta(days=1)
    return previous_sessions(end, 1, market)[0]


def freshness_floor(
    kind: RunKind,
    now_utc: datetime,
    allowed_lag_sessions: int = 1,
    *,
    market: Market = Market.US,
) -> date:
    """Oldest acceptable last-bar date in `market`: its expected session, allowing
    `allowed_lag_sessions` behind (spec §10)."""
    last = expected_last_session(kind, now_utc, market)
    return previous_sessions(last, allowed_lag_sessions + 1, market)[0]
```

- [ ] **Step 4: Run the tests and lint**

Run: `pipeline/scripts/in-docker.sh uv run pytest -q`
Expected: every test passes. `tests/unit/test_run_cli.py` still passes: 2026-10-17 is a Saturday, and 2026-10-14 08:50 ET is still a missed pre-open.

Run: `cd pipeline && uv run --no-sync ruff check .`
Expected: `All checks passed!`

- [ ] **Step 5: Commit**

```bash
git add pipeline/src/advisor/schedule.py pipeline/tests/unit/test_schedule.py
git commit -m "feat: schedule runs on NYSE and TSX trading days

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Yahoo-only prices with flagged jumps; remove Alpaca

**Files:**
- Delete: `pipeline/src/advisor/collectors/alpaca_bars.py`, `pipeline/tests/unit/test_alpaca_bars.py`
- Modify: `pipeline/src/advisor/prices.py` (rewrite)
- Modify: `pipeline/src/advisor/collectors/yfinance_bars.py`
- Modify: `pipeline/src/advisor/config.py`, `pipeline/src/advisor/collectors/registry.py`
- Modify: `pipeline/src/advisor/run.py`
- Modify: `pipeline/tests/fakes.py`
- Modify: `.github/workflows/run.yml`, `.github/workflows/health.yml`, `pipeline/scripts/in-docker.sh`, `README.md`, `docs/superpowers/deferred.md`
- Test: `pipeline/tests/unit/test_prices.py` (rewrite), `pipeline/tests/unit/test_yfinance_bars.py`, `pipeline/tests/unit/test_config.py` (rewrite), `pipeline/tests/unit/test_registry.py`, `pipeline/tests/unit/test_run_cli.py`, `pipeline/tests/integration/test_run.py`, `pipeline/tests/integration/test_run_cli_db.py`, `pipeline/tests/integration/test_health_cli.py`, `pipeline/tests/integration/test_repo.py`, `pipeline/tests/integration/test_schema.py`

**Interfaces:**
- Consumes: `market_of`, `Market` (Task 1).
- Produces:
  - `advisor.prices`:
    - `JUMP_LIMIT = 0.5`;
    - `PriceFetch(bars: dict[str, list[DailyBar]], flagged: dict[str, set[date]])`, where `flagged` holds only symbols with at least one flagged day;
    - `find_jumps(bars: Sequence[DailyBar]) -> set[date]`;
    - `fetch_daily_bars(symbols: Sequence[str], *, run: RunFn) -> PriceFetch`;
    - `group_bars` (unchanged).
  - `advisor.run.PRICES = "yfinance_bars"`. Priority features gain `"unconfirmed_jump": bool`, which is True when the latest bar is flagged, and the summary gains `"unconfirmed_jumps": int`, the number of priced symbols with any flagged day.
  - `advisor.config.Settings(database_url, cache_dir)` and `REQUIRED = ("DATABASE_URL",)`.
  - `fakes.bar(...)` and `fakes.history(...)` default to `source="yfinance"`. `fake_price_collectors(universe)` returns `nasdaq_symbols` and `yfinance_bars`; the latter is core and best-effort.

- [ ] **Step 1: Write the failing price and Yahoo tests**

Replace `pipeline/tests/unit/test_prices.py` with:

```python
from datetime import date

from advisor.collectors.base import CollectorResult, CollectorStatus
from advisor.prices import fetch_daily_bars, find_jumps
from fakes import bar, history


def day(i: int) -> date:
    return date(2026, 10, 12 + i)


def closes(*values: float) -> list:
    return [bar("X", day(i), value) for i, value in enumerate(values)]


def test_a_move_within_fifty_percent_is_not_flagged():
    assert find_jumps(closes(10.0, 14.9, 10.0)) == set()


def test_a_jump_is_flagged_not_dropped():
    assert find_jumps(closes(10.0, 16.0)) == {day(1)}


def test_a_crash_is_flagged_too():
    assert find_jumps(closes(10.0, 4.0)) == {day(1)}


def test_reversion_after_a_spike_is_not_flagged():
    assert find_jumps(closes(10.0, 30.0, 10.0)) == {day(1)}


def test_a_persistent_move_flags_only_the_jump_day():
    assert find_jumps(closes(10.0, 16.0, 16.2, 16.5)) == {day(1)}


def test_no_bars_means_no_flags():
    assert find_jumps([]) == set()


def runner(bars_by_symbol, calls, status=CollectorStatus.OK):
    def run(symbols):
        calls.append(list(symbols))
        records = [b for s in symbols for b in bars_by_symbol.get(s, [])]
        return CollectorResult("yfinance_bars", status, records, 5)
    return run


def test_fetch_daily_bars_asks_once_and_keeps_flagged_bars():
    calls = []
    jumpy = [bar("JMP", day(0), 10.0), bar("JMP", day(1), 16.0)]
    result = fetch_daily_bars(
        ["JMP", "AAA", "JMP", "NONE"], run=runner({"AAA": history("AAA", 3), "JMP": jumpy}, calls)
    )
    assert calls == [["AAA", "JMP", "NONE"]]
    assert sorted(result.bars) == ["AAA", "JMP"]
    assert [b.close for b in result.bars["JMP"]] == [10.0, 16.0]
    assert result.flagged == {"JMP": {day(1)}}


def test_fetch_daily_bars_sorts_by_day_and_keeps_the_last_bar_per_day():
    records = [bar("A", day(1), 11.0), bar("A", day(0), 10.0), bar("A", day(1), 12.0)]
    result = fetch_daily_bars(["A"], run=runner({"A": records}, []))
    assert [(b.day, b.close) for b in result.bars["A"]] == [(day(0), 10.0), (day(1), 12.0)]
```

In `pipeline/tests/unit/test_yfinance_bars.py`, change the import to `from advisor.collectors.yfinance_bars import YFinanceBars, parse_frame, to_yahoo`, add `from advisor.collectors.base import PartialFetch`, and append:

```python
def test_to_yahoo_leaves_tsx_symbols_in_yahoos_form():
    assert to_yahoo("RY.TO") == "RY.TO"
    assert to_yahoo("RCI-B.TO") == "RCI-B.TO"


def test_yahoo_is_the_core_price_source_with_a_tsx_canary():
    collector = YFinanceBars()
    assert collector.core is True
    assert "RY.TO" in collector.canary


def test_fetch_reports_partial_when_a_whole_download_comes_back_empty(monkeypatch):
    monkeypatch.setattr("advisor.collectors.yfinance_bars.SYMBOLS_PER_DOWNLOAD", 5)

    def fake_download(tickers, start, end):  # Yahoo throttles the second download silently
        return two_ticker_frame() if "AAPL" in tickers else pd.DataFrame()

    symbols = ["AAPL", "BRK.B", "C", "D", "E", "F", "G", "H", "I", "J"]
    with pytest.raises(PartialFetch, match="1 of 2 Yahoo downloads returned no bars") as caught:
        YFinanceBars(download=fake_download).fetch(symbols, AS_OF)
    assert {b.symbol for b in caught.value.records} == {"AAPL", "BRK.B"}
```

- [ ] **Step 2: Write the failing config, registry and run tests**

Replace `pipeline/tests/unit/test_config.py` with:

```python
from pathlib import Path

import pytest

from advisor.config import ConfigError, Settings


def test_from_env_reads_the_database_url_and_default_cache_dir():
    settings = Settings.from_env({"DATABASE_URL": "postgresql://u:p@h/db"})
    assert settings.database_url == "postgresql://u:p@h/db"
    assert settings.cache_dir == Path(".cache")


def test_from_env_honours_cache_dir_override():
    settings = Settings.from_env({"DATABASE_URL": "x", "ADVISOR_CACHE_DIR": "/tmp/advisor"})
    assert settings.cache_dir == Path("/tmp/advisor")


def test_from_env_requires_only_the_database_url():  # spec R7: no data source needs a key
    with pytest.raises(ConfigError, match="Missing required environment variables: DATABASE_URL$"):
        Settings.from_env({})


def test_repr_hides_the_database_url():
    settings = Settings.from_env({"DATABASE_URL": "postgresql://u:db-password-123@h/db"})
    assert "db-password-123" not in repr(settings)
```

In `pipeline/tests/unit/test_registry.py`, replace the test body from `settings = Settings(...)` through the closing `}` of the scope assertion with the code below. The canary and record-type checks after it stay.

```python
    settings = Settings("postgresql://x", Path(".cache"))
    with httpx.Client() as client:
        registry = build_registry(settings, client)
    assert sorted(registry) == ["nasdaq_symbols", "yfinance_bars"]
    assert {name: c.core for name, c in registry.items()} == {
        "nasdaq_symbols": True,
        "yfinance_bars": True,
    }
    assert all(registry[name].name == name for name in registry)
    assert {name: c.scope for name, c in registry.items()} == {
        "nasdaq_symbols": Scope.UNIVERSE,
        "yfinance_bars": Scope.SYMBOLS,
    }
```

In `pipeline/tests/unit/test_run_cli.py`, change the loop in `clear_env` to `for name in ("DATABASE_URL",):`.

In `pipeline/tests/integration/test_run_cli_db.py` and `pipeline/tests/integration/test_health_cli.py`, delete the two lines `monkeypatch.setenv("ALPACA_KEY_ID", "test")` and `monkeypatch.setenv("ALPACA_SECRET_KEY", "test")`.

In `pipeline/tests/integration/test_repo.py` and `pipeline/tests/integration/test_schema.py`, replace every `alpaca_bars` with `nasdaq_symbols`. These are only source-name strings. Afterwards, `grep -rn alpaca pipeline/` should print nothing.

In `pipeline/tests/integration/test_run.py`:
- change the import line to `from fakes import FRESH_START, FakeCollector, bar, fake_price_collectors, history`, and add `from datetime import UTC, date, datetime` in place of the existing `datetime` import;
- replace `make_deps` and the tests named below with this code;
- delete `test_primary_price_outage_falls_back_and_marks_run_degraded` and `test_partial_primary_prices_degrade_the_run_and_fall_back_for_the_rest`. The two new tests below replace them.

```python
def make_deps(db, tmp_path, *, universe=UNIVERSE, prices=None, universe_records=None, extra=None):
    collectors = fake_price_collectors(universe)
    if universe_records is not None:
        collectors["nasdaq_symbols"].records_for = universe_records
    if prices is not None:
        collectors["yfinance_bars"] = prices
    collectors.update(extra or {})
    return RunDeps(db, DiskCache(tmp_path), collectors)


def test_successful_run_is_published_with_summary(db, tmp_path):
    deps = make_deps(db, tmp_path)
    outcome = execute_run(deps, RunKind.PRE_OPEN, NOW, min_universe=3)

    assert outcome.status is RunStatus.SUCCESS
    row = run_row(db, outcome.run_id)
    assert row["published"] is True
    assert (row["sources_ok"], row["sources_total"]) == (2, 2)
    assert row["summary"] == {
        "universe": 3, "priced": 3, "passed_filters": 3, "priority": 0, "priority_unpriced": [],
        "fresh": 3, "fresh_since": "2026-10-12", "shortlist": 3, "unconfirmed_jumps": 0,
    }
    assert deps.collectors["yfinance_bars"].calls == [["AAA", "BBB", "CCC"]]
    assert health(db, outcome.run_id) == [("nasdaq_symbols", "ok"), ("yfinance_bars", "ok")]
    assert db.execute("select count(*) as n from symbols where active").fetchone()["n"] == 3


def test_holdings_are_priced_first_and_get_features(db, tmp_path):
    hold(db)
    db.execute("insert into watchlist (symbol, asset_type) values ('BTC', 'crypto')")
    deps = make_deps(db, tmp_path)
    outcome = execute_run(deps, RunKind.PRE_OPEN, NOW, min_universe=3)

    assert deps.collectors["yfinance_bars"].calls == [["OTCX"], ["AAA", "BBB", "CCC"]]
    assert health(db, outcome.run_id) == [("nasdaq_symbols", "ok"), ("yfinance_bars", "ok")]
    features = db.execute(
        "select symbol, features from features_live where run_id = %s", (outcome.run_id,)
    ).fetchall()
    assert [f["symbol"] for f in features] == ["OTCX"]
    assert features[0]["features"] == {
        "last_close": 10.0, "adv20": 2_000_000.0, "history_days": 70, "last_day": "2026-10-13",
        "stale": False, "unconfirmed_jump": False,
    }
    assert outcome.summary["priority"] == 1
    assert outcome.summary["priced"] == 4


def test_price_outage_fails_the_run(db, tmp_path):
    prices = FakeCollector("yfinance_bars", error=httpx.ConnectError("down"))
    outcome = execute_run(
        make_deps(db, tmp_path, prices=prices), RunKind.PRE_OPEN, NOW, min_universe=3
    )

    assert outcome.status is RunStatus.FAILED
    assert run_row(db, outcome.run_id)["published"] is False
    assert outcome.summary["failed_reason"] == ["too few fresh priced symbols (0 of 3)"]
    assert ("yfinance_bars", "failed") in health(db, outcome.run_id)


def test_partial_prices_degrade_the_run(db, tmp_path):
    some = [b for s in ("AAA", "BBB") for b in history(s, 70, start=FRESH_START)]
    prices = FakeCollector(
        "yfinance_bars", error=PartialFetch(some, "1 of 2 Yahoo downloads returned no bars")
    )
    outcome = execute_run(
        make_deps(db, tmp_path, prices=prices), RunKind.PRE_OPEN, NOW, min_universe=3
    )

    assert outcome.status is RunStatus.DEGRADED
    assert run_row(db, outcome.run_id)["published"] is True
    assert health(db, outcome.run_id) == [("nasdaq_symbols", "ok"), ("yfinance_bars", "partial")]
    assert outcome.summary["priced"] == 2


def test_a_source_failing_in_one_phase_reports_one_partial_row(db, tmp_path):
    hold(db)

    def records_for(symbols):
        if list(symbols) != ["OTCX"]:
            raise httpx.ConnectError("down")
        return history("OTCX", 70, start=FRESH_START)

    prices = FakeCollector("yfinance_bars", records_for=records_for)
    outcome = execute_run(
        make_deps(db, tmp_path, prices=prices), RunKind.PRE_OPEN, NOW, min_universe=3
    )
    rows = health(db, outcome.run_id)
    assert rows.count(("yfinance_bars", "partial")) == 1
    assert len([s for s, _ in rows if s == "yfinance_bars"]) == 1
    assert outcome.status is RunStatus.FAILED  # the rest of the market went unpriced
    assert outcome.summary["priced"] == 1


def test_an_unconfirmed_jump_is_kept_and_flagged(db, tmp_path):
    hold(db)

    def records_for(symbols):
        bars = [b for s in symbols for b in history(s, 70, start=FRESH_START)]
        return [  # OTCX jumps 10 -> 16 (+60%) on its latest bar
            bar(b.symbol, b.day, 16.0) if (b.symbol, b.day) == ("OTCX", date(2026, 10, 13)) else b
            for b in bars
        ]

    prices = FakeCollector("yfinance_bars", records_for=records_for)
    outcome = execute_run(
        make_deps(db, tmp_path, prices=prices), RunKind.PRE_OPEN, NOW, min_universe=3
    )

    assert outcome.status is RunStatus.SUCCESS
    assert outcome.summary["unconfirmed_jumps"] == 1
    features = db.execute(
        "select features from features_live where run_id = %s and symbol = 'OTCX'",
        (outcome.run_id,),
    ).fetchone()["features"]
    assert (features["last_close"], features["unconfirmed_jump"]) == (16.0, True)
```

In `test_enrichment_collectors_get_priority_first_then_the_shortlist`, change the final assertion to:

```python
    assert [s for s, _ in health(db, outcome.run_id)] == [
        "coins", "macro", "nasdaq_symbols", "news", "yfinance_bars",
    ]
```

In `test_stale_prices_fail_the_run_and_flag_holding_features`, replace the `alpaca = FakeCollector(...)` and `execute_run(...)` lines with:

```python
    prices = FakeCollector(  # bars end 2026-08-09: two months behind a 2026-10-14 run
        "yfinance_bars", records_for=lambda syms: [b for s in syms for b in history(s, 70)]
    )
    outcome = execute_run(
        make_deps(db, tmp_path, prices=prices), RunKind.PRE_OPEN, NOW, min_universe=3
    )
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `pipeline/scripts/in-docker.sh uv run pytest tests/unit/test_prices.py tests/unit/test_yfinance_bars.py tests/unit/test_config.py tests/unit/test_registry.py tests/integration/test_run.py -q`
Expected: FAIL. `find_jumps` can't be imported, `Settings` takes four fields, the registry lists `alpaca_bars`, and `to_yahoo("RY.TO")` returns `"RY-TO"`.

- [ ] **Step 4: Rewrite `prices.py`**

Replace `pipeline/src/advisor/prices.py` with:

```python
"""Daily stock bars from Yahoo, the only stock price source (spec R7).

Jump rule (spec §10): a close that moves more than 50% against both the last accepted close and
the previous close is flagged as an unconfirmed jump. With no second source to confirm it, the
bar is kept; features, picks and holding actions treat flagged days with care.
"""

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from itertools import pairwise

from advisor.collectors.base import CollectorResult
from advisor.models import DailyBar

JUMP_LIMIT = 0.5

RunFn = Callable[[Sequence[str]], CollectorResult]


@dataclass(frozen=True)
class PriceFetch:
    bars: dict[str, list[DailyBar]]
    flagged: dict[str, set[date]]  # only symbols with at least one unconfirmed jump


def group_bars(records: Iterable[DailyBar]) -> dict[str, list[DailyBar]]:
    by_symbol: dict[str, dict[date, DailyBar]] = {}
    for record in records:
        by_symbol.setdefault(record.symbol, {})[record.day] = record
    return {s: [days[d] for d in sorted(days)] for s, days in by_symbol.items()}


def find_jumps(bars: Sequence[DailyBar]) -> set[date]:
    """Days whose close moves >50% vs both the last unflagged close and the previous close."""
    flagged: set[date] = set()
    if not bars:
        return flagged
    last_accepted = bars[0].close
    for prev, cur in pairwise(bars):
        if (
            abs(cur.close / last_accepted - 1) > JUMP_LIMIT
            and abs(cur.close / prev.close - 1) > JUMP_LIMIT
        ):
            flagged.add(cur.day)
        else:
            last_accepted = cur.close
    return flagged


def fetch_daily_bars(symbols: Sequence[str], *, run: RunFn) -> PriceFetch:
    """One Yahoo call for `symbols`; every bar is kept and jumps are flagged."""
    bars = group_bars(run(sorted(set(symbols))).records)
    flagged = {symbol: days for symbol, history in bars.items() if (days := find_jumps(history))}
    return PriceFetch(bars=bars, flagged=flagged)
```

- [ ] **Step 5: Make Yahoo the core price source for both markets**

In `pipeline/src/advisor/collectors/yfinance_bars.py`:

1. Replace the module docstring and imports:

```python
"""Daily bars from Yahoo Finance via yfinance (source 3): the only stock price source (spec R7).

Covers both markets: US symbols map to Yahoo's share-class form (BRK.B -> BRK-B), and TSX
symbols are already stored in Yahoo's form (RCI-B.TO).
"""

from collections.abc import Callable, Sequence
from datetime import date, datetime, timedelta

import pandas as pd

from advisor.collectors.base import Cadence, Category, PartialFetch, Scope
from advisor.markets import market_of
from advisor.models import ET, AssetType, DailyBar, Market
```

2. Replace the comment above `MIN_SYMBOLS_FOR_EMPTY_CHECK`, and the `to_yahoo` function:

```python
# yf.download never raises: blocked or rate-limited requests come back as empty frames, so a
# download of at least this many symbols with no bars at all counts as failed.
MIN_SYMBOLS_FOR_EMPTY_CHECK = 5


def to_yahoo(symbol: str) -> str:
    if market_of(symbol) is Market.TSX:
        return symbol
    return symbol.replace(".", "-")
```

3. In `YFinanceBars`, set `core = True` and `canary = ("AAPL", "MSFT", "RY.TO")`, then replace `fetch`:

```python
    def fetch(self, symbols: Sequence[str], as_of: datetime) -> list[DailyBar]:
        unique = sorted(set(symbols))
        start = (as_of - LOOKBACK).astimezone(ET).date()
        end = as_of.astimezone(ET).date() + timedelta(days=1)
        chunks = [
            unique[i : i + SYMBOLS_PER_DOWNLOAD] for i in range(0, len(unique), SYMBOLS_PER_DOWNLOAD)
        ]
        bars: list[DailyBar] = []
        empty = 0
        for chunk in chunks:
            mapping = {to_yahoo(s): s for s in chunk}
            got = parse_frame(self._download(list(mapping), start, end), mapping)
            if not got and len(chunk) >= MIN_SYMBOLS_FOR_EMPTY_CHECK:
                empty += 1
            bars.extend(got)
        if empty and not bars:
            raise RuntimeError(
                f"yfinance returned no bars for {len(unique)} symbols (blocked or rate-limited?)"
            )
        if empty:
            raise PartialFetch(bars, f"{empty} of {len(chunks)} Yahoo downloads returned no bars")
        return bars
```

- [ ] **Step 6: Remove Alpaca from config, registry, fakes and the orchestrator**

Delete the two Alpaca files:

```bash
git rm pipeline/src/advisor/collectors/alpaca_bars.py pipeline/tests/unit/test_alpaca_bars.py
```

Replace `pipeline/src/advisor/config.py` with:

```python
"""Runtime settings loaded from environment variables. No data source needs a key (spec R7)."""

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Self

REQUIRED = ("DATABASE_URL",)


class ConfigError(RuntimeError):
    """Raised when required settings are missing."""


@dataclass(frozen=True)
class Settings:
    database_url: str = field(repr=False)  # holds the database password
    cache_dir: Path

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Self:
        env = os.environ if env is None else env
        missing = [name for name in REQUIRED if not env.get(name)]
        if missing:
            raise ConfigError(f"Missing required environment variables: {', '.join(missing)}")
        return cls(
            database_url=env["DATABASE_URL"],
            cache_dir=Path(env.get("ADVISOR_CACHE_DIR", ".cache")),
        )
```

Replace `pipeline/src/advisor/collectors/registry.py` with:

```python
"""Every collector the pipeline runs, keyed by name. Later plans add the remaining sources here."""

import httpx

from advisor.collectors.base import Collector
from advisor.collectors.nasdaq_symbols import NasdaqSymbols
from advisor.collectors.yfinance_bars import YFinanceBars
from advisor.config import Settings


def build_registry(settings: Settings, client: httpx.Client) -> dict[str, Collector]:
    collectors: list[Collector] = [NasdaqSymbols(client), YFinanceBars()]
    return {collector.name: collector for collector in collectors}
```

In `pipeline/tests/fakes.py`:
- change the `source` default of `bar` and `history` from `"alpaca"` to `"yfinance"`;
- replace `fake_price_collectors` with this code:

```python
def fake_price_collectors(universe: Sequence[str] = ("AAA", "BBB", "CCC")) -> dict[str, FakeCollector]:
    """Universe and Yahoo price fakes; prices are fresh 70-day histories."""
    return {
        "nasdaq_symbols": FakeCollector(
            "nasdaq_symbols",
            records_for=lambda _: [info(s) for s in universe],
            record_type=SymbolInfo,
            cadence=Cadence.DAILY,
            scope=Scope.UNIVERSE,
            freshness=timedelta(days=3),
        ),
        "yfinance_bars": FakeCollector(
            "yfinance_bars",
            best_effort=True,
            records_for=lambda syms: [b for s in syms for b in history(s, 70, start=FRESH_START)],
        ),
    }
```

In `pipeline/src/advisor/run.py`:

1. Replace the constants block:

```python
MIN_UNIVERSE = 1000  # fewer listed stocks than this means the symbol files were truncated
MIN_PRICED_FRACTION = 0.5
UNIVERSE_SOURCE = "nasdaq_symbols"
PRICES = "yfinance_bars"
PRICE_STAGE = frozenset({UNIVERSE_SOURCE, PRICES})
```

2. Replace `fetch_prices` inside `execute_run`:

```python
    def fetch_prices(symbols: Sequence[str]) -> PriceFetch:
        return fetch_daily_bars(symbols, run=lambda s: tracker.run(PRICES, s))
```

3. Replace the phase 1 block, from `bars = fetch_prices(priority).bars if priority else {}` through the end of the `repo.write_features_live(...)` call:

```python
        first = fetch_prices(priority) if priority else PriceFetch({}, {})
        bars, flagged = dict(first.bars), dict(first.flagged)
        priority_rows = [screener.price_stats(s, bars[s]) for s in priority if s in bars]
        repo.write_features_live(
            conn,
            run_id,
            [
                (
                    AssetRef(r.symbol, AssetType.STOCK),
                    {
                        **r.as_features(),
                        "stale": not r.is_fresh(floor),
                        "unconfirmed_jump": r.last_day in flagged.get(r.symbol, ()),
                    },
                )
                for r in priority_rows
            ],
            now_utc,
        )
```

4. Replace the phase 2 price merge:

```python
        if rest:
            second = fetch_prices(rest)
            bars = {**second.bars, **bars}
            flagged = {**second.flagged, **flagged}
```

5. Add `"unconfirmed_jumps": len(flagged),` to the `summary` dict, after `"shortlist"`.

- [ ] **Step 7: Remove Alpaca from workflows, the Docker script, the README and the deferred list**

In `.github/workflows/run.yml` and `.github/workflows/health.yml`, delete these two lines from the step `env:` blocks:

```yaml
          ALPACA_KEY_ID: ${{ secrets.ALPACA_KEY_ID }}
          ALPACA_SECRET_KEY: ${{ secrets.ALPACA_SECRET_KEY }}
```

In `pipeline/scripts/in-docker.sh`, change the env line to:

```bash
  -e DATABASE_URL -e ADMIN_DATABASE_URL -e ADVISOR_CACHE_DIR \
```

In `README.md`, under deployment:
- delete step 5 ("**Alpaca**: create a free account…", two lines);
- renumber the old steps 6 and 7 as 5 and 6;
- make the new step 5 read:

```markdown
5. **GitHub** (private repo): Settings → Secrets and variables → Actions. Add `DATABASE_URL`
   (the pipeline login from step 4). No data source needs an API key.
```

In "Manual run", change `` (`DATABASE_URL=...`, `ALPACA_KEY_ID=...`, `ALPACA_SECRET_KEY=...`): `` to `` (`DATABASE_URL=...`): ``.

In `docs/superpowers/deferred.md`, make these exact edits:
- `## Plan 2b, Task 0: must land before the first real enrichment source` becomes `## Plan 2c, Task 0: must land before the first real enrichment source`.
- `  - This is needed for daily caps: FMP allows 250 calls/day and Alpha Vantage 25/day.` becomes `  - This is needed for slow or capped sources such as Yahoo analyst data and Google Trends.`
- `The SEC allows 10 requests per second per IP across all SEC collectors, and Finnhub allows 60 calls per minute per key across all Finnhub collectors.` becomes `The SEC allows 10 requests per second per IP across all SEC collectors.`
- `## Plans 2c and 2d` becomes `## Plans 2c to 2e`, and `CoinGecko is core for crypto (2c).` becomes `CoinGecko is core for crypto (2e).`
- Replace the `**Jump rule refinement.**` bullet with:

  `- **Jump indicator feature** (spec §10). Plan 2b keeps flagged bars and records `unconfirmed_jump` for the latest bar of each priority symbol. Plan 3 turns flagged days into the jump feature and blocks a Buy on them (§6.1). A bad first bar in a window is never flagged, because there is no earlier close to compare.`
- `- **Partial current-day bar** at the pre-close run, from both Alpaca and yfinance.` becomes `- **Partial current-day bar** at the pre-close run, from Yahoo.`
- `- **Benchmarks** (SPY, sector ETFs)` becomes `- **Benchmarks** (SPY, XIU.TO, sector ETFs)`.

- [ ] **Step 8: Run the full suite, lint and grep**

Run: `pipeline/scripts/in-docker.sh uv run pytest -q`
Expected: every test passes.

Run: `cd pipeline && uv run --no-sync ruff check .`
Expected: `All checks passed!`

Run: `git grep -n -i alpaca -- pipeline .github README.md`
Expected: no output.

- [ ] **Step 9: Commit**

```bash
git add -A pipeline .github README.md docs/superpowers/deferred.md
git commit -m "feat: make Yahoo the only stock price source and flag jumps; remove Alpaca

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: TMX universe collector

**Files:**
- Create: `pipeline/src/advisor/collectors/tmx_symbols.py`
- Create: `pipeline/tests/unit/test_tmx_symbols.py`
- Add (already on disk, untracked): `pipeline/tests/fixtures/tmx/company_directory_trimmed.json`
- Modify: `pipeline/src/advisor/collectors/registry.py`, `pipeline/src/advisor/run.py` (`PRICE_STAGE`), `docs/superpowers/deferred.md`
- Test: `pipeline/tests/unit/test_registry.py`

**Interfaces:**
- Consumes: `Market`, `SymbolInfo.market` (Task 1); `get_with_retries`, `RateLimiter` and `Category`/`Cadence`/`Scope` from `advisor.collectors.base`.
- Produces:
  - `TmxSymbols(client, limiter=None, *, min_kept=300)` with `name = "tmx_symbols"`, `Scope.UNIVERSE`, `Cadence.DAILY`, `freshness = 3 days`, `core = True` and `best_effort = True`;
  - `DIRECTORY_URL`, `MIN_KEPT`, `canonical_symbol(tmx_symbol) -> str`, `keep_instrument(symbol, instrument_name, company_name) -> bool`, `parse_directory(payload: dict) -> list[SymbolInfo]`.

The fixture is a trimmed copy of the live answer captured on 2026-10-13: `last_updated`, `length`, and `results` of `{symbol, name, instruments: [{symbol, name}]}`. It has 13 companies covering ETFs, a CDR, preferred series, an income fund, REIT and non-REIT units, share classes, a warrant, debentures and a USD line.

- [ ] **Step 1: Write the failing tests**

Create `pipeline/tests/unit/test_tmx_symbols.py`:

```python
import json
from datetime import UTC, datetime

import httpx
import pytest

from advisor.collectors.tmx_symbols import (
    DIRECTORY_URL,
    TmxSymbols,
    canonical_symbol,
    keep_instrument,
    parse_directory,
)
from advisor.models import Market

NOW = datetime(2026, 10, 14, 12, 15, tzinfo=UTC)
KEPT = [
    "ASTL.TO", "BCE.TO", "HOM-UN.TO", "RCI-A.TO", "RCI-B.TO", "REI-UN.TO", "RY.TO", "SHOP.TO",
    "TECK-A.TO", "TECK-B.TO",
]


@pytest.fixture
def directory(fixtures_dir) -> dict:
    path = fixtures_dir / "tmx" / "company_directory_trimmed.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_parse_directory_keeps_common_shares_and_reit_units(directory):
    records = parse_directory(directory)
    assert [r.symbol for r in records] == KEPT
    assert {(r.market, r.exchange) for r in records} == {(Market.TSX, "TSX")}
    names = {r.symbol: r.name for r in records}
    assert names["RCI-B.TO"] == "Rogers Communications Inc."
    assert names["HOM-UN.TO"] == "BSR Real Estate Investment Trust"


@pytest.mark.parametrize(
    ("symbol", "instrument", "company", "kept"),
    [
        ("RY", "Royal Bank of Canada", "Royal Bank of Canada", True),
        ("RCI.B", "Rogers Comm Cl B NV", "Rogers Communications Inc.", True),
        ("REI.UN", "RioCan Rl Est Tr Un", "RioCan Real Estate Investment Trust", True),
        ("AD.UN", "Alaris Eq Part Tr Un", "Alaris Equity Partners Income Trust", False),  # not a REIT
        ("CHE.UN", "Chemtrade Logistc Un", "Chemtrade Logistics Income Fund", False),
        ("RY.PR.S", "Royal Bank Pr Ser BO", "Royal Bank of Canada", False),  # preferred
        ("ASTL.WT", "Algoma Steel Grp Wt", "Algoma Steel Group Inc.", False),  # warrant
        ("HOM.U", "BSR REIT Invest USF", "BSR Real Estate Investment Trust", False),  # USD line
        ("XYZ.DB", "XYZ Corp 6% Db", "XYZ Corp", False),  # debenture
        ("BTCQ", "3iQ Bitcoin ETF Un", "3iQ Bitcoin ETF", False),
        ("ABT", "AbbottLab CDR Hgd", "Abbott Labs CDR (CAD Hedged)", False),
        ("DFN", "Dividend 15 Split Cl A", "Dividend 15 Split Corp.", False),
        ("ry", "Royal Bank of Canada", "Royal Bank of Canada", False),
    ],
)
def test_keep_instrument(symbol, instrument, company, kept):
    assert keep_instrument(symbol, instrument, company) is kept


def test_canonical_symbol_is_yahoos_form():
    assert canonical_symbol("RY") == "RY.TO"
    assert canonical_symbol("RCI.B") == "RCI-B.TO"
    assert canonical_symbol("REI.UN") == "REI-UN.TO"


def serving(handler, **kwargs) -> TmxSymbols:
    return TmxSymbols(httpx.Client(transport=httpx.MockTransport(handler)), **kwargs)


def test_fetch_requests_the_directory_once_and_returns_kept_symbols(directory):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json=directory)

    records = serving(handler, min_kept=10).fetch([], NOW)
    assert seen == [DIRECTORY_URL]
    assert [r.symbol for r in records] == KEPT


def test_fetch_requires_three_hundred_kept_symbols_by_default(directory):
    collector = serving(lambda request: httpx.Response(200, json=directory))
    with pytest.raises(ValueError, match="only 10 symbols kept, expected at least 300"):
        collector.fetch([], NOW)


def test_fetch_rejects_an_empty_directory():
    collector = serving(lambda request: httpx.Response(200, json={"length": 0, "results": []}))
    with pytest.raises(ValueError, match="only 0 symbols kept"):
        collector.fetch([], NOW)


def test_fetch_rejects_a_block_page():
    collector = serving(lambda request: httpx.Response(200, text="<html>Access denied</html>"))
    with pytest.raises(ValueError):  # json.JSONDecodeError is a ValueError
        collector.fetch([], NOW)
```

In `pipeline/tests/unit/test_registry.py`, change the expectations to three collectors:

```python
    assert sorted(registry) == ["nasdaq_symbols", "tmx_symbols", "yfinance_bars"]
    assert {name: c.core for name, c in registry.items()} == {
        "nasdaq_symbols": True,
        "tmx_symbols": True,
        "yfinance_bars": True,
    }
    assert all(registry[name].name == name for name in registry)
    assert {name: c.scope for name, c in registry.items()} == {
        "nasdaq_symbols": Scope.UNIVERSE,
        "tmx_symbols": Scope.UNIVERSE,
        "yfinance_bars": Scope.SYMBOLS,
    }
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pipeline/scripts/in-docker.sh uv run pytest tests/unit/test_tmx_symbols.py tests/unit/test_registry.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'advisor.collectors.tmx_symbols'`.

- [ ] **Step 3: Implement the collector**

Create `pipeline/src/advisor/collectors/tmx_symbols.py`:

```python
"""TSX-listed common shares and REIT units from the TMX company directory (source 2).

One JSON call lists every TSX company with its instruments. Kept: common shares and share
classes (RCI.B), plus .UN units of REITs. Dropped: ETFs, CDRs, funds, split-share and notes
issuers, preferreds (two-dot symbols such as RY.PR.S), warrants, debentures, rights, and
USD-traded lines (.U). Symbols are stored in Yahoo's form: RCI.B becomes RCI-B.TO.
"""

import re
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

import httpx

from advisor.collectors.base import Cadence, Category, RateLimiter, Scope, get_with_retries
from advisor.markets import TSX_SUFFIX
from advisor.models import AssetType, Market, SymbolInfo

DIRECTORY_URL = "https://www.tsx.com/json/company-directory/search/tsx/%5E*"
# The live directory keeps about 675; far fewer means a truncated or changed answer.
MIN_KEPT = 300
INSTRUMENT = re.compile(r"^[A-Z]{1,5}(\.[A-Z]{1,2})?$")
EXCLUDED_SUFFIXES = frozenset({"U", "F", "T", "WT", "DB", "NT", "RT", "W", "R"})
NON_EQUITY = re.compile(r"\b(ETFs?|CDRs?|Funds?|Split|Portfolio|Pool|Notes?)\b")
REIT = re.compile(r"\b(REIT|Real Estate Investment Trust)\b")


def canonical_symbol(tmx_symbol: str) -> str:
    return tmx_symbol.replace(".", "-") + TSX_SUFFIX


def keep_instrument(symbol: str, instrument_name: str, company_name: str) -> bool:
    match = INSTRUMENT.match(symbol)
    if match is None:
        return False
    suffix = (match.group(1) or ".")[1:]
    if suffix in EXCLUDED_SUFFIXES:
        return False
    if NON_EQUITY.search(company_name) or NON_EQUITY.search(instrument_name):
        return False
    return suffix != "UN" or REIT.search(company_name) is not None


def parse_directory(payload: dict[str, Any]) -> list[SymbolInfo]:
    records: dict[str, SymbolInfo] = {}
    for company in payload["results"]:
        for instrument in company["instruments"]:
            if not keep_instrument(instrument["symbol"], instrument["name"], company["name"]):
                continue
            symbol = canonical_symbol(instrument["symbol"])
            records.setdefault(
                symbol,
                SymbolInfo(symbol=symbol, market=Market.TSX, name=company["name"], exchange="TSX"),
            )
    return sorted(records.values(), key=lambda record: record.symbol)


class TmxSymbols:
    name = "tmx_symbols"
    category = Category.PRICES
    core = True
    best_effort = True
    cadence = Cadence.DAILY
    asset_types = frozenset({AssetType.STOCK})
    record_type = SymbolInfo
    freshness = timedelta(days=3)
    scope = Scope.UNIVERSE
    canary: tuple[str, ...] = ()
    canary_requires_records = True

    def __init__(
        self, client: httpx.Client, limiter: RateLimiter | None = None, *, min_kept: int = MIN_KEPT
    ) -> None:
        self._client = client
        self._limiter = limiter
        self._min_kept = min_kept

    def fetch(self, symbols: Sequence[str], as_of: datetime) -> list[SymbolInfo]:
        response = get_with_retries(self._client, DIRECTORY_URL, limiter=self._limiter)
        records = parse_directory(response.json())
        if len(records) < self._min_kept:  # raising keeps the cached universe in use
            raise ValueError(
                f"TMX directory: only {len(records)} symbols kept,"
                f" expected at least {self._min_kept}"
            )
        return records
```

In `pipeline/src/advisor/collectors/registry.py`, import `TmxSymbols` (`from advisor.collectors.tmx_symbols import TmxSymbols`) and register it:

```python
    collectors: list[Collector] = [NasdaqSymbols(client), TmxSymbols(client), YFinanceBars()]
```

In `pipeline/src/advisor/run.py`, keep the TMX universe out of the enrichment stage until Task 5 runs it:

```python
PRICE_STAGE = frozenset({UNIVERSE_SOURCE, "tmx_symbols", PRICES})
```

In `docs/superpowers/deferred.md`, under `## Plan 3: model and features`, append this sentence to the **Exclude non-common instruments** bullet's last paragraph: `Run the same check on TSX symbols, for income trusts and closed-end funds whose names the TMX filter cannot recognise.`

- [ ] **Step 4: Run the tests and lint**

Run: `pipeline/scripts/in-docker.sh uv run pytest -q`
Expected: every test passes. `test_registry` checks that UNIVERSE collectors have no canary and that every collector requires canary records.

Run: `cd pipeline && uv run --no-sync ruff check .`
Expected: `All checks passed!`

- [ ] **Step 5: Commit**

```bash
git add pipeline/src/advisor/collectors/tmx_symbols.py pipeline/src/advisor/collectors/registry.py \
  pipeline/src/advisor/run.py pipeline/tests/unit/test_tmx_symbols.py pipeline/tests/unit/test_registry.py \
  pipeline/tests/fixtures/tmx/company_directory_trimmed.json docs/superpowers/deferred.md
git commit -m "feat: add the TSX universe from the TMX company directory

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Two-market orchestrator

**Files:**
- Modify: `pipeline/src/advisor/run.py` (`execute_run` rewritten)
- Modify: `pipeline/src/advisor/enrich.py` (`interleave`)
- Modify: `pipeline/tests/fakes.py` (`fake_price_collectors` gains a TSX universe)
- Modify: `README.md` (intro line)
- Test: `pipeline/tests/integration/test_run.py` (rewrite), `pipeline/tests/unit/test_enrich.py`, `pipeline/tests/integration/test_run_cli_db.py` (comment)

**Interfaces:**
- Consumes:
  - `MARKETS` and `market_of` (Task 1);
  - `upsert_symbols(conn, market, symbols)` (Task 1);
  - `freshness_floor(..., market=)` (Task 2);
  - `PriceFetch`, `fetch_daily_bars(symbols, *, run=)` and `PRICES` (Task 3);
  - the `tmx_symbols` collector (Task 4).
- Produces:
  - `execute_run(deps, kind, now_utc, *, min_universe: Mapping[Market, int] | None = None) -> RunOutcome`. Missing markets default to `MARKETS[m].min_universe`.
  - `MarketPass` (frozen dataclass) and `check_market(...)`.
  - `enrich.interleave(*lists: Sequence[str]) -> list[str]`.
  - Summary shape: `{"markets": {"US": {...}, "TSX": {...}}, "priority", "priority_unpriced", "unconfirmed_jumps", "shortlist"}`, plus `"failed_reason"` on failure. Each per-market entry has `universe`, `priced`, `passed_filters`, `fresh`, `fresh_since` and `shortlist`. Each failure reason starts with `"US: "` or `"TSX: "`.
  - `fake_price_collectors(universe=("AAA","BBB","CCC"), tsx=("RY.TO","TD.TO"))`.

- [ ] **Step 1: Write the failing tests**

Append to `pipeline/tests/unit/test_enrich.py`, and add `interleave` to its `advisor.enrich` import:

```python
def test_interleave_alternates_markets_and_keeps_the_longer_tail():
    assert interleave(["A1", "A2", "A3"], ["B1"]) == ["A1", "B1", "A2", "A3"]
    assert interleave([], ["B1", "B2"]) == ["B1", "B2"]
    assert interleave() == []
```

In `pipeline/tests/integration/test_run_cli_db.py`, change the comment on the `main([...]) == 1` line to `# tiny fake universes are below both minimums`.

Replace `pipeline/tests/integration/test_run.py` with:

```python
from datetime import UTC, date, datetime

import httpx
import pytest

from advisor.collectors.base import PartialFetch, Scope
from advisor.collectors.cache import DiskCache
from advisor.models import AssetType, Market, RunKind, RunStatus
from advisor.run import RunDeps, execute_run
from fakes import FRESH_START, FakeCollector, bar, fake_price_collectors, history

NOW = datetime(2026, 10, 14, 12, 15, tzinfo=UTC)
US = ["AAA", "BBB", "CCC"]
TSX = ["RY.TO", "TD.TO"]
SMALL = {Market.US: 3, Market.TSX: 2}
EVERYONE = ["AAA", "BBB", "CCC", "RY.TO", "TD.TO"]


def make_deps(db, tmp_path, *, prices=None, us_records=None, extra=None):
    collectors = fake_price_collectors(US, TSX)
    if us_records is not None:
        collectors["nasdaq_symbols"].records_for = us_records
    if prices is not None:
        collectors["yfinance_bars"] = prices
    collectors.update(extra or {})
    return RunDeps(db, DiskCache(tmp_path), collectors)


def run_row(db, run_id):
    return db.execute("select * from runs where id = %s", (run_id,)).fetchone()


def health(db, run_id):
    rows = db.execute(
        "select source, status from source_health where run_id = %s order by source", (run_id,)
    ).fetchall()
    return [(r["source"], r["status"]) for r in rows]


def hold(db, symbol="OTCX"):
    tsx = symbol.endswith(".TO")
    db.execute(
        "insert into lots (account, symbol, asset_type, qty, price, currency, fx_rate_cad, bought_at)"
        " values ('tfsa', %s, 'stock', 10, 5, %s, %s, '2026-09-01')",
        (symbol, "CAD" if tsx else "USD", None if tsx else 1.37),
    )


def market_features(db, run_id):
    rows = db.execute(
        "select symbol, features from features_live where run_id = %s order by symbol", (run_id,)
    ).fetchall()
    return {r["symbol"]: r["features"] for r in rows}


def test_successful_run_is_published_with_a_per_market_summary(db, tmp_path):
    deps = make_deps(db, tmp_path)
    outcome = execute_run(deps, RunKind.PRE_OPEN, NOW, min_universe=SMALL)

    assert outcome.status is RunStatus.SUCCESS
    row = run_row(db, outcome.run_id)
    assert row["published"] is True
    assert (row["sources_ok"], row["sources_total"]) == (3, 3)
    assert row["summary"] == {
        "markets": {
            "US": {
                "universe": 3, "priced": 3, "passed_filters": 3, "fresh": 3,
                "fresh_since": "2026-10-12", "shortlist": 3,
            },
            "TSX": {  # the TSX was closed on 2026-10-12, so its floor is 10-09
                "universe": 2, "priced": 2, "passed_filters": 2, "fresh": 2,
                "fresh_since": "2026-10-09", "shortlist": 2,
            },
        },
        "priority": 0, "priority_unpriced": [], "unconfirmed_jumps": 0, "shortlist": 5,
    }
    assert deps.collectors["yfinance_bars"].calls == [EVERYONE]  # one call for both markets
    assert health(db, outcome.run_id) == [
        ("nasdaq_symbols", "ok"), ("tmx_symbols", "ok"), ("yfinance_bars", "ok"),
    ]
    markets = db.execute(
        "select market, count(*) as n from symbols where active group by market order by market"
    ).fetchall()
    assert [(r["market"], r["n"]) for r in markets] == [("TSX", 2), ("US", 3)]


def test_holdings_of_both_markets_are_priced_first_and_get_features(db, tmp_path):
    hold(db)
    hold(db, "SHOP.TO")
    db.execute("insert into watchlist (symbol, asset_type) values ('BTC', 'crypto')")
    deps = make_deps(db, tmp_path)
    outcome = execute_run(deps, RunKind.PRE_OPEN, NOW, min_universe=SMALL)

    assert deps.collectors["yfinance_bars"].calls == [["OTCX", "SHOP.TO"], EVERYONE]
    features = market_features(db, outcome.run_id)
    assert sorted(features) == ["OTCX", "SHOP.TO"]
    assert features["OTCX"] == {
        "last_close": 10.0, "adv20": 2_000_000.0, "history_days": 70, "last_day": "2026-10-13",
        "stale": False, "unconfirmed_jump": False,
    }
    assert outcome.summary["priority"] == 2
    assert outcome.summary["markets"]["US"]["priced"] == 4
    assert outcome.summary["markets"]["TSX"]["priced"] == 3


def test_each_market_is_judged_against_its_own_calendar(db, tmp_path):
    # Pre-open on 2026-10-13: the NYSE traded 10-12 (floor 10-09); the TSX was closed for
    # Thanksgiving (last session 10-09, floor 10-08). Bars ending 10-08 are fresh only on the TSX.
    hold(db)
    hold(db, "SHOP.TO")
    prices = FakeCollector(
        "yfinance_bars",
        records_for=lambda syms: [b for s in syms for b in history(s, 70, start=date(2026, 7, 31))],
    )
    outcome = execute_run(
        make_deps(db, tmp_path, prices=prices),
        RunKind.PRE_OPEN,
        datetime(2026, 10, 13, 12, 15, tzinfo=UTC),
        min_universe=SMALL,
    )

    features = market_features(db, outcome.run_id)
    assert {s: f["stale"] for s, f in features.items()} == {"OTCX": True, "SHOP.TO": False}
    us, tsx = outcome.summary["markets"]["US"], outcome.summary["markets"]["TSX"]
    assert (us["fresh_since"], us["fresh"]) == ("2026-10-09", 0)
    assert (tsx["fresh_since"], tsx["fresh"]) == ("2026-10-08", 3)
    assert outcome.status is RunStatus.FAILED
    assert outcome.summary["failed_reason"] == ["US: too few fresh priced symbols (0 of 4)"]


def test_holdings_are_saved_even_when_a_later_stage_fails(db, tmp_path):
    hold(db)
    deps = make_deps(db, tmp_path, us_records=lambda _: [object()])
    with pytest.raises(AttributeError):
        execute_run(deps, RunKind.PRE_OPEN, NOW, min_universe={Market.US: 1, Market.TSX: 1})
    assert db.execute("select symbol from features_live").fetchone()["symbol"] == "OTCX"
    row = db.execute("select * from runs").fetchone()
    assert (row["status"], row["published"]) == ("failed", False)
    assert row["summary"]["error"].startswith("AttributeError")


def test_price_outage_fails_the_run_for_both_markets(db, tmp_path):
    prices = FakeCollector("yfinance_bars", error=httpx.ConnectError("down"))
    outcome = execute_run(
        make_deps(db, tmp_path, prices=prices), RunKind.PRE_OPEN, NOW, min_universe=SMALL
    )

    assert outcome.status is RunStatus.FAILED
    assert run_row(db, outcome.run_id)["published"] is False
    assert outcome.summary["failed_reason"] == [
        "US: too few fresh priced symbols (0 of 3)",
        "TSX: too few fresh priced symbols (0 of 2)",
    ]
    assert ("yfinance_bars", "failed") in health(db, outcome.run_id)


def test_partial_prices_degrade_the_run(db, tmp_path):
    some = [b for s in ("AAA", "BBB", "RY.TO") for b in history(s, 70, start=FRESH_START)]
    prices = FakeCollector(
        "yfinance_bars", error=PartialFetch(some, "1 of 2 Yahoo downloads returned no bars")
    )
    outcome = execute_run(
        make_deps(db, tmp_path, prices=prices), RunKind.PRE_OPEN, NOW, min_universe=SMALL
    )

    assert outcome.status is RunStatus.DEGRADED
    assert run_row(db, outcome.run_id)["published"] is True
    assert ("yfinance_bars", "partial") in health(db, outcome.run_id)
    assert outcome.summary["markets"]["US"]["priced"] == 2
    assert outcome.summary["markets"]["TSX"]["priced"] == 1


def test_a_source_failing_in_one_phase_reports_one_partial_row(db, tmp_path):
    hold(db)

    def records_for(symbols):
        if list(symbols) != ["OTCX"]:
            raise httpx.ConnectError("down")
        return history("OTCX", 70, start=FRESH_START)

    prices = FakeCollector("yfinance_bars", records_for=records_for)
    outcome = execute_run(
        make_deps(db, tmp_path, prices=prices), RunKind.PRE_OPEN, NOW, min_universe=SMALL
    )
    rows = health(db, outcome.run_id)
    assert rows.count(("yfinance_bars", "partial")) == 1
    assert len([s for s, _ in rows if s == "yfinance_bars"]) == 1
    assert outcome.status is RunStatus.FAILED
    assert market_features(db, outcome.run_id)["OTCX"]["stale"] is False


def test_an_unconfirmed_jump_is_kept_and_flagged(db, tmp_path):
    hold(db, "SHOP.TO")

    def records_for(symbols):
        bars = [b for s in symbols for b in history(s, 70, start=FRESH_START)]
        return [  # SHOP.TO jumps 10 -> 16 (+60%) on its latest bar
            bar(b.symbol, b.day, 16.0) if (b.symbol, b.day) == ("SHOP.TO", date(2026, 10, 13)) else b
            for b in bars
        ]

    prices = FakeCollector("yfinance_bars", records_for=records_for)
    outcome = execute_run(
        make_deps(db, tmp_path, prices=prices), RunKind.PRE_OPEN, NOW, min_universe=SMALL
    )

    assert outcome.status is RunStatus.SUCCESS
    assert outcome.summary["unconfirmed_jumps"] == 1
    features = market_features(db, outcome.run_id)["SHOP.TO"]
    assert (features["last_close"], features["unconfirmed_jump"]) == (16.0, True)


def test_enrichment_gets_priority_then_crypto_then_both_markets_interleaved(db, tmp_path):
    hold(db)
    db.execute("insert into watchlist (symbol, asset_type) values ('BTC', 'crypto')")
    extra = {
        "news": FakeCollector("news", core=False),
        "macro": FakeCollector("macro", scope=Scope.MARKET),
        "coins": FakeCollector("coins", asset_types=frozenset({AssetType.CRYPTO})),
        "mixed": FakeCollector("mixed", asset_types=frozenset({AssetType.STOCK, AssetType.CRYPTO})),
    }
    outcome = execute_run(
        make_deps(db, tmp_path, extra=extra), RunKind.PRE_OPEN, NOW, min_universe=SMALL
    )

    assert outcome.status is RunStatus.SUCCESS
    assert extra["news"].calls == [["OTCX", "AAA", "RY.TO", "BBB", "TD.TO", "CCC"]]
    assert extra["mixed"].calls == [["OTCX", "BTC", "AAA", "RY.TO", "BBB", "TD.TO", "CCC"]]
    assert extra["macro"].calls == [[]]
    assert extra["coins"].calls == [["BTC"]]
    assert outcome.summary["shortlist"] == 6
    assert [s for s, _ in health(db, outcome.run_id)] == [
        "coins", "macro", "mixed", "nasdaq_symbols", "news", "tmx_symbols", "yfinance_bars",
    ]


def test_a_failing_core_enrichment_source_degrades_the_run(db, tmp_path):
    extra = {"filings": FakeCollector("filings", core=True, error=httpx.ConnectError("down"))}
    outcome = execute_run(
        make_deps(db, tmp_path, extra=extra), RunKind.PRE_OPEN, NOW, min_universe=SMALL
    )
    assert outcome.status is RunStatus.DEGRADED
    assert ("filings", "failed") in health(db, outcome.run_id)


def test_a_truncated_universe_fails_the_run_and_keeps_that_markets_symbols(db, tmp_path):
    db.execute(
        "insert into symbols (symbol, asset_type, market, name, exchange)"
        " values ('OLD.TO', 'stock', 'TSX', 'Old Co', 'TSX')"
    )
    extra = {"news": FakeCollector("news")}
    outcome = execute_run(
        make_deps(db, tmp_path, extra=extra),
        RunKind.PRE_OPEN,
        NOW,
        min_universe={Market.US: 3, Market.TSX: 300},
    )

    assert outcome.status is RunStatus.FAILED
    assert outcome.summary["failed_reason"] == ["TSX: universe too small (2 < 300)"]
    assert run_row(db, outcome.run_id)["published"] is False
    rows = db.execute("select symbol, market, active from symbols order by symbol").fetchall()
    assert [(r["symbol"], r["market"], r["active"]) for r in rows] == [
        ("AAA", "US", True), ("BBB", "US", True), ("CCC", "US", True),  # US saved independently
        ("OLD.TO", "TSX", True),  # a truncated TSX universe deactivates nothing
    ]
    assert outcome.summary["markets"]["TSX"]["shortlist"] == 0
    assert outcome.summary["shortlist"] == 0
    assert extra["news"].calls == []  # a run that cannot publish spends no enrichment calls


def test_default_minimums_come_from_the_markets_table(db, tmp_path):
    outcome = execute_run(make_deps(db, tmp_path), RunKind.PRE_OPEN, NOW)
    assert outcome.summary["failed_reason"] == [
        "US: universe too small (3 < 1000)", "TSX: universe too small (2 < 300)",
    ]


def test_stale_prices_fail_the_run_and_flag_holding_features(db, tmp_path):
    hold(db)
    prices = FakeCollector(  # bars end 2026-08-09: two months behind a 2026-10-14 run
        "yfinance_bars", records_for=lambda syms: [b for s in syms for b in history(s, 70)]
    )
    outcome = execute_run(
        make_deps(db, tmp_path, prices=prices), RunKind.PRE_OPEN, NOW, min_universe=SMALL
    )

    assert outcome.status is RunStatus.FAILED
    assert run_row(db, outcome.run_id)["published"] is False
    assert outcome.summary["failed_reason"] == [
        "US: too few fresh priced symbols (0 of 4)",
        "TSX: too few fresh priced symbols (0 of 2)",
    ]
    assert market_features(db, outcome.run_id)["OTCX"]["stale"] is True


def test_unexpected_error_marks_run_failed_and_propagates(db, tmp_path):
    deps = make_deps(db, tmp_path, us_records=lambda _: [object()])
    with pytest.raises(AttributeError):
        execute_run(deps, RunKind.PRE_OPEN, NOW, min_universe={Market.US: 1, Market.TSX: 1})
    row = db.execute("select * from runs").fetchone()
    assert row["status"] == "failed"
    assert row["published"] is False
    assert row["summary"]["error"].startswith("AttributeError")
    assert ("nasdaq_symbols", "ok") in health(db, row["id"])


def test_abandoned_runs_are_swept_when_a_run_starts(db, tmp_path):
    db.execute(
        "insert into runs (kind, et_date, started_at)"
        " values ('pre_close', '2026-10-13', '2026-10-14 09:00+00')"
    )
    execute_run(make_deps(db, tmp_path), RunKind.PRE_OPEN, NOW, min_universe=SMALL)
    old = db.execute("select status from runs where kind = 'pre_close'").fetchone()
    assert old["status"] == "failed"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pipeline/scripts/in-docker.sh uv run pytest tests/integration/test_run.py tests/unit/test_enrich.py -q`
Expected: FAIL. `interleave` can't be imported, `fake_price_collectors` takes no `tsx` argument, and the summary has no `markets` key.

- [ ] **Step 3: Add `interleave` and the TSX fake universe**

In `pipeline/src/advisor/enrich.py`, add `from itertools import zip_longest` to the imports and add this function after `shortlist`:

```python
def interleave(*lists: Sequence[str]) -> list[str]:
    """Round-robin merge (a1, b1, a2, b2, ...), so capped collectors reach every market's best."""
    return [symbol for group in zip_longest(*lists) for symbol in group if symbol is not None]
```

In `pipeline/tests/fakes.py`, replace `fake_price_collectors`:

```python
def fake_price_collectors(
    universe: Sequence[str] = ("AAA", "BBB", "CCC"), tsx: Sequence[str] = ("RY.TO", "TD.TO")
) -> dict[str, FakeCollector]:
    """US and TSX universe fakes plus a Yahoo price fake returning fresh 70-day histories."""

    def directory(name: str, symbols: Sequence[str]) -> FakeCollector:
        return FakeCollector(
            name,
            records_for=lambda _: [info(s) for s in symbols],
            record_type=SymbolInfo,
            cadence=Cadence.DAILY,
            scope=Scope.UNIVERSE,
            freshness=timedelta(days=3),
        )

    return {
        "nasdaq_symbols": directory("nasdaq_symbols", universe),
        "tmx_symbols": directory("tmx_symbols", tsx),
        "yfinance_bars": FakeCollector(
            "yfinance_bars",
            best_effort=True,
            records_for=lambda syms: [b for s in syms for b in history(s, 70, start=FRESH_START)],
        ),
    }
```

- [ ] **Step 4: Rewrite the orchestrator for two markets**

In `pipeline/src/advisor/run.py`:

1. Replace the imports through the constants with:

```python
import argparse
import contextlib
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime

import psycopg

from advisor import screener
from advisor.collectors.base import Collector, CollectorResult, CollectorStatus, make_client
from advisor.collectors.cache import DiskCache
from advisor.collectors.registry import build_registry
from advisor.collectors.tracker import SourceTracker
from advisor.config import Settings
from advisor.enrich import EnrichTargets, interleave, ranked_shortlist, run_enrichment
from advisor.markets import MARKETS, market_of
from advisor.models import ET, AssetRef, AssetType, DailyBar, Market, RunKind, RunStatus, SymbolInfo
from advisor.prices import PriceFetch, fetch_daily_bars
from advisor.schedule import freshness_floor, missed_run_kind, resolve_run_kind
from advisor.screener import ScreenRow
from advisor.store import repo
from advisor.store.db import connect

MIN_PRICED_FRACTION = 0.5
PRICES = "yfinance_bars"
PRICE_STAGE = frozenset({PRICES, *(spec.universe_source for spec in MARKETS.values())})
```

2. Add this code after `RunOutcome`:

```python
@dataclass(frozen=True)
class MarketPass:
    """One market's universe and price check (spec §10: either market failing fails the run)."""

    market: Market
    universe: int
    min_universe: int
    symbols: int  # the universe plus this market's priority symbols
    priced: int
    fresh: int
    fresh_since: date
    passed: list[ScreenRow]

    @property
    def universe_ok(self) -> bool:
        return self.universe >= self.min_universe

    @property
    def prices_ok(self) -> bool:
        return self.symbols > 0 and self.fresh >= MIN_PRICED_FRACTION * self.symbols

    def failed_reasons(self) -> list[str]:
        reasons = []
        if not self.universe_ok:
            reasons.append(
                f"{self.market}: universe too small ({self.universe} < {self.min_universe})"
            )
        if not self.prices_ok:
            reasons.append(
                f"{self.market}: too few fresh priced symbols ({self.fresh} of {self.symbols})"
            )
        return reasons


def check_market(
    market: Market,
    universe: Sequence[SymbolInfo],
    min_universe: int,
    priority: Sequence[str],
    bars: Mapping[str, Sequence[DailyBar]],
    floor: date,
) -> MarketPass:
    symbols = {s for s in priority if market_of(s) is market} | {r.symbol for r in universe}
    priced = {s: bars[s] for s in symbols if s in bars}
    return MarketPass(
        market=market,
        universe=len(universe),
        min_universe=min_universe,
        symbols=len(symbols),
        priced=len(priced),
        fresh=sum(1 for history in priced.values() if history[-1].day >= floor),
        fresh_since=floor,
        passed=screener.hard_filter(priced, fresh_since=floor),
    )
```

3. Replace `execute_run` with:

```python
def execute_run(
    deps: RunDeps,
    kind: RunKind,
    now_utc: datetime,
    *,
    min_universe: Mapping[Market, int] | None = None,
) -> RunOutcome:
    conn = deps.conn
    limits = {m: MARKETS[m].min_universe for m in Market} | dict(min_universe or {})
    # spec §10: a last bar older than its own market's floor counts as missing
    floors = {m: freshness_floor(kind, now_utc, market=m) for m in Market}
    repo.sweep_abandoned_runs(conn, now_utc)
    run_id = repo.create_run(conn, kind, now_utc.astimezone(ET).date())
    tracker = SourceTracker(
        deps.collectors, deps.cache, now_utc, repo.load_source_states(conn, deps.collectors)
    )

    def fetch_prices(symbols: Sequence[str]) -> PriceFetch:
        return fetch_daily_bars(symbols, run=lambda s: tracker.run(PRICES, s))

    def record_health() -> None:
        for result, failures in tracker.health_rows():
            repo.record_source_health(conn, run_id, result, failures, now_utc)

    try:
        held, watch = repo.load_held_symbols(conn), repo.load_watchlist(conn)
        priority = priority_order(held, watch, AssetType.STOCK)
        crypto = priority_order(held, watch, AssetType.CRYPTO)

        # Phase 1: holdings and watchlist of both markets are priced and saved before anything
        # else can fail.
        first = fetch_prices(priority) if priority else PriceFetch({}, {})
        bars, flagged = dict(first.bars), dict(first.flagged)
        priority_rows = [screener.price_stats(s, bars[s]) for s in priority if s in bars]
        repo.write_features_live(
            conn,
            run_id,
            [
                (
                    AssetRef(r.symbol, AssetType.STOCK),
                    {
                        **r.as_features(),
                        "stale": not r.is_fresh(floors[market_of(r.symbol)]),
                        "unconfirmed_jump": r.last_day in flagged.get(r.symbol, ()),
                    },
                )
                for r in priority_rows
            ],
            now_utc,
        )

        # Phase 2: each market's universe, then one price fetch for everything not yet priced.
        universes: dict[Market, list[SymbolInfo]] = {}
        for market in Market:
            universes[market] = list(tracker.run(MARKETS[market].universe_source, []).records)
            if len(universes[market]) >= limits[market]:
                repo.upsert_symbols(conn, market, universes[market])
        rest = sorted({r.symbol for u in universes.values() for r in u} - set(priority))
        if rest:
            second = fetch_prices(rest)
            bars = {**second.bars, **bars}
            flagged = {**second.flagged, **flagged}

        passes = {
            m: check_market(m, universes[m], limits[m], priority, bars, floors[m]) for m in Market
        }
        universe_ok = all(p.universe_ok for p in passes.values())
        prices_ok = all(p.prices_ok for p in passes.values())

        # Phase 3: enrichment, only for a run that can still publish.
        ranked = {
            m: ranked_shortlist(p.passed, priority, MARKETS[m].shortlist_size)
            for m, p in passes.items()
        }
        targets = EnrichTargets(
            priority_stocks=priority, crypto=crypto, ranked_stocks=interleave(*ranked.values())
        )
        enriched = universe_ok and prices_ok
        if enriched:
            run_enrichment(
                tracker,
                deps.collectors,
                [name for name in deps.collectors if name not in PRICE_STAGE],
                targets,
            )

        summary = {
            "markets": {
                m.value: {
                    "universe": p.universe,
                    "priced": p.priced,
                    "passed_filters": len(p.passed),
                    "fresh": p.fresh,
                    "fresh_since": p.fresh_since.isoformat(),
                    "shortlist": len(ranked[m]) if enriched else 0,
                }
                for m, p in passes.items()
            },
            "priority": len(priority),
            "priority_unpriced": sorted(set(priority) - bars.keys()),
            "unconfirmed_jumps": len(flagged),
            "shortlist": len(targets.stocks) if enriched else 0,
        }
        status = decide_status(
            tracker.merged(), deps.collectors, universe_ok=universe_ok, prices_ok=prices_ok
        )
        if status is RunStatus.FAILED:
            summary["failed_reason"] = [
                reason for p in passes.values() for reason in p.failed_reasons()
            ]
    except Exception as exc:
        with contextlib.suppress(Exception):  # never let bookkeeping hide the real error
            record_health()
        repo.finish_run(
            conn, run_id, RunStatus.FAILED,
            sources_ok=tracker.count_healthy(),
            sources_total=len(deps.collectors),
            summary={"error": f"{type(exc).__name__}: {exc}"[:500]},
        )
        raise

    record_health()
    repo.finish_run(
        conn, run_id, status,
        sources_ok=tracker.count_healthy(),
        sources_total=len(deps.collectors),
        summary=summary,
    )
    return RunOutcome(run_id, status, summary)
```

`main` stays as it is: it calls `execute_run(deps, kind, now)`, which uses the Markets-table minimums.

In `README.md`, change the intro's second line to say `forecasts likely ranges for US and TSX stocks and watchlist crypto, and suggests buys, hold times, and`.

- [ ] **Step 5: Run the full suite and lint**

Run: `pipeline/scripts/in-docker.sh uv run pytest -q`
Expected: every test passes.

Run: `cd pipeline && uv run --no-sync ruff check .`
Expected: `All checks passed!` If the import sorter (I001) reorders an import, accept its fix with `uv run --no-sync ruff check --fix .`.

- [ ] **Step 6: Commit**

```bash
git add pipeline/src/advisor/run.py pipeline/src/advisor/enrich.py pipeline/tests README.md
git commit -m "feat: run US and TSX markets side by side with per-market checks

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## After this plan

- **Live check before the first scheduled run.** On the owner's machine, with `DATABASE_URL` pointing at the local test database:

  ```bash
  pipeline/scripts/in-docker.sh uv run python -m advisor.health
  pipeline/scripts/in-docker.sh uv run python -m advisor.run --force-kind pre_open
  ```

  Expect about 675 TSX symbols in `symbols` with `market = 'TSX'`, and a summary with both markets.
- **Deployment** (Plan 1 Task 13) is still the owner's step. It no longer needs any Alpaca secret.
- **Plan 2c** comes next: `docs/superpowers/plans/2026-10-13-plan-2c-collector-infrastructure-and-market-data.md`. It must be revised before it runs (see the banner at its top).
