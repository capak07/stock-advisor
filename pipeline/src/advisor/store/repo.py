"""Every SQL statement the pipeline runs. Functions take an open autocommit connection."""

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from advisor.collectors.base import Collector, CollectorResult
from advisor.collectors.runner import SourceState
from advisor.markets import MARKETS, TSX_SUFFIX, market_of
from advisor.models import (
    ET,
    AcceptedConfig,
    AssetRef,
    AssetType,
    BenchmarkResult,
    DailyClose,
    HoldingActionRow,
    LinkedPick,
    Market,
    Outcome,
    PickRow,
    PredictionRow,
    RunKind,
    RunStatus,
    StoredModel,
    SymbolInfo,
)
from advisor.news.stage import NewsRow, StoredNews
from advisor.portfolio.ledger import Trade
from advisor.recommend.verdicts import Verdict


@dataclass(frozen=True)
class OpenPick:
    """A pick still open, as grading reads it (spec §6.5)."""

    id: int
    symbol: str
    market: str
    horizon_days: int
    exit_by: date
    entry_ref_price: float
    stop: float
    # the day entry_ref_price and bench_ref_price closed; both are None on a pick made before
    # migration 0009, which can't be graded
    feature_day: date | None
    bench_ref_price: float | None
    run_kind: str  # the kind of the run that made the pick


@dataclass(frozen=True)
class ActionToGrade:
    """A stock holding action with an exit-by date and no outcome yet, as grading reads it."""

    run_id: int
    account: str
    symbol: str
    asset_type: str
    feature_day: date
    exit_by: date
    ref_price: float
    bench_ref_price: float
    trailing_stop: float | None


PUBLISHABLE = frozenset({RunStatus.SUCCESS, RunStatus.DEGRADED})
NEWS_KEPT = timedelta(days=90)  # spec §10: news is pruned after 90 days


def create_run(conn: psycopg.Connection, kind: RunKind, et_date: date) -> int:
    row = conn.execute(
        "insert into runs (kind, et_date) values (%s, %s) returning id", (kind.value, et_date)
    ).fetchone()
    return row["id"]


def finish_run(
    conn: psycopg.Connection,
    run_id: int,
    status: RunStatus,
    *,
    sources_ok: int,
    sources_total: int,
    summary: dict,
    model_version: str | None = None,
) -> None:
    publish = status in PUBLISHABLE
    with conn.transaction():
        if publish:
            conn.execute(
                "update runs set published = false"
                " where published and id <> %(id)s"
                " and (kind, et_date) = (select kind, et_date from runs where id = %(id)s)",
                {"id": run_id},
            )
        conn.execute(
            "update runs set status = %s, finished_at = now(), sources_ok = %s,"
            " sources_total = %s, summary = %s, published = %s, model_version = %s where id = %s",
            (status.value, sources_ok, sources_total, Jsonb(summary), publish, model_version, run_id),
        )


def has_published_run(conn: psycopg.Connection, kind: RunKind, et_date: date) -> bool:
    row = conn.execute(
        "select exists (select 1 from runs where published and kind = %s and et_date = %s)"
        " as found",
        (kind.value, et_date),
    ).fetchone()
    return row["found"]


def write_sources(conn: psycopg.Connection, collectors: Mapping[str, Collector]) -> None:
    """The registry's collectors, for the dashboard's Source health page (Plan 5c).

    A source that left the registry is removed, so the page lists what the pipeline runs.
    """
    rows = [
        (
            c.name, c.category.value, c.core, c.cadence.value,
            sorted(t.value for t in c.asset_types), sorted(m.value for m in c.markets),
        )
        for c in collectors.values()
    ]
    with conn.transaction():
        with conn.cursor() as cur:
            cur.executemany(
                "insert into sources (name, category, core, cadence, asset_types, markets, updated_at)"
                " values (%s, %s, %s, %s, %s, %s, now())"
                " on conflict (name) do update set category = excluded.category,"
                " core = excluded.core, cadence = excluded.cadence, asset_types = excluded.asset_types,"
                " markets = excluded.markets, updated_at = now()",
                rows,
            )
        conn.execute("delete from sources where not (name = any(%s))", ([r[0] for r in rows],))


def record_source_health(
    conn: psycopg.Connection,
    run_id: int | None,
    result: CollectorResult,
    consecutive_failures: int,
    attempted_at: datetime,
    *,
    context: str = "run",
) -> None:
    """One row per source per run (context 'run') or per daily check (context 'health', no run)."""
    conn.execute(
        "insert into source_health (run_id, source, status, latency_ms, records, error,"
        " consecutive_failures, attempted_at, context)"
        " values (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            run_id, result.name, result.status.value, result.latency_ms, len(result.records),
            result.error, consecutive_failures, attempted_at, context,
        ),
    )


def load_source_state(conn: psycopg.Connection, source: str) -> SourceState:
    row = conn.execute(
        "select"
        " (select consecutive_failures from source_health where source = %(s)s"
        "   order by attempted_at desc, id desc limit 1) as failures,"
        " (select max(attempted_at) from source_health where source = %(s)s"
        "   and status <> 'skipped') as last_attempt",
        {"s": source},
    ).fetchone()
    last_attempt = row["last_attempt"]
    return SourceState(
        consecutive_failures=row["failures"] or 0,
        last_attempt_et_date=last_attempt.astimezone(ET).date() if last_attempt else None,
    )


def load_source_states(conn: psycopg.Connection, sources: Iterable[str]) -> dict[str, SourceState]:
    return {source: load_source_state(conn, source) for source in sources}


ABANDONED_AFTER = timedelta(hours=2)  # far beyond the 40-minute job timeout


def sweep_abandoned_runs(
    conn: psycopg.Connection, now: datetime, older_than: timedelta = ABANDONED_AFTER
) -> int:
    """Mark runs still 'running' long after they started (job killed or timed out) as failed."""
    cursor = conn.execute(
        "update runs set status = 'failed', finished_at = %s, summary = summary || %s"
        " where status = 'running' and started_at < %s",
        (
            now,
            Jsonb({"error": "abandoned: no finish was recorded (job killed or timed out)"}),
            now - older_than,
        ),
    )
    return cursor.rowcount


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


def upsert_coins(
    conn: psycopg.Connection, coins: Sequence[tuple[str, str, float | None]], now: datetime
) -> None:
    """Store the coin list the dashboard's search offers, stamped `now`; coins that left it are
    deactivated."""
    if not coins:  # would deactivate every coin
        raise ValueError("refusing to upsert an empty coin list")
    with conn.transaction():
        with conn.cursor() as cur:
            cur.executemany(
                "insert into symbols"
                " (symbol, asset_type, market, name, exchange, market_cap, active, updated_at)"
                " values (%s, 'crypto', null, %s, 'CoinGecko', %s, true, %s)"
                " on conflict (symbol, asset_type) do update set name = excluded.name,"
                " exchange = excluded.exchange, market_cap = excluded.market_cap, active = true,"
                " updated_at = excluded.updated_at",
                [(symbol, name, cap, now) for symbol, name, cap in coins],
            )
        conn.execute(
            "update symbols set active = false, updated_at = %s"
            " where asset_type = 'crypto' and active and not (symbol = any(%s))",
            (now, [coin[0] for coin in coins]),
        )


def coins_refreshed_on(conn: psycopg.Connection) -> date | None:
    """The ET day the coin list was last stored, or None before the first time."""
    row = conn.execute(
        "select max(updated_at) as at from symbols where asset_type = 'crypto' and active"
    ).fetchone()
    return row["at"].astimezone(ET).date() if row and row["at"] else None


def save_model(
    conn: psycopg.Connection,
    version: str,
    kind: str,
    trained_at: datetime,
    metrics: Mapping[str, Any],
    calibration_error: float | None,
    files: Mapping[str, bytes],
) -> None:
    """Store a trained model inactive, with its files, in one transaction."""
    with conn.transaction():
        conn.execute(
            "insert into models (version, kind, trained_at, metrics, calibration_error, active)"
            " values (%s, %s, %s, %s, %s, false)",
            (version, kind, trained_at, Jsonb(dict(metrics)), calibration_error),
        )
        with conn.cursor() as cur:
            cur.executemany(
                "insert into model_files (version, name, body) values (%s, %s, %s)",
                [(version, name, body) for name, body in files.items()],
            )


def active_model(conn: psycopg.Connection, kind: str) -> StoredModel | None:
    row = conn.execute(
        "select version, kind, trained_at, metrics, calibration_error, active"
        " from models where kind = %s and active",
        (kind,),
    ).fetchone()
    return StoredModel(**row) if row else None


def activate_model(conn: psycopg.Connection, kind: str, version: str) -> None:
    """Retire the kind's active model and activate `version`, atomically."""
    with conn.transaction():
        if not conn.execute(
            "select 1 from models where kind = %s and version = %s", (kind, version)
        ).fetchone():
            raise ValueError(f"no {kind} model {version}")
        conn.execute("update models set active = false where kind = %s and active", (kind,))
        conn.execute("update models set active = true where version = %s", (version,))


def load_model_files(conn: psycopg.Connection, version: str) -> dict[str, bytes]:
    rows = conn.execute("select name, body from model_files where version = %s", (version,)).fetchall()
    return {r["name"]: bytes(r["body"]) for r in rows}


def prune_models(conn: psycopg.Connection, kind: str, keep: int = 2) -> int:
    """Keep the active model plus the newest others up to `keep`; delete the rest (files cascade)."""
    with conn.transaction():
        active = conn.execute("select 1 from models where kind = %s and active", (kind,)).fetchone()
        others = max(keep - (1 if active else 0), 0)
        return conn.execute(
            "delete from models where kind = %s and not active and version not in ("
            " select version from models where kind = %s and not active"
            " order by trained_at desc, version desc limit %s)",
            (kind, kind, others),
        ).rowcount


def write_predictions(conn: psycopg.Connection, run_id: int, rows: Sequence[PredictionRow]) -> None:
    """Store a run's stock forecasts."""
    with conn.cursor() as cur:
        cur.executemany(
            "insert into predictions (run_id, symbol, asset_type, horizon_days, q10, q50, q90, p_beat,"
            " benchmark, model_version) values (%s, %s, 'stock', %s, %s, %s, %s, %s, %s, %s)",
            [
                (run_id, r.symbol, r.horizon_days, r.q10, r.q50, r.q90, r.p_beat, r.benchmark, r.model_version)
                for r in rows
            ],
        )


def write_picks(conn: psycopg.Connection, run_id: int, rows: Sequence[PickRow]) -> None:
    """Store a run's stock picks."""
    with conn.cursor() as cur:
        cur.executemany(
            "insert into picks (run_id, symbol, asset_type, market, style, horizon_days, exit_by,"
            " entry_ref_price, stop, risk_level, risk_score, max_position_pct, rank, top_factors, catalysts,"
            " feature_day, bench_ref_price)"
            " values (%s, %s, 'stock', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            [
                (
                    run_id, r.symbol, r.market.value, r.style, r.horizon_days, r.exit_by, r.entry_ref_price,
                    r.stop, r.risk_level, r.risk_score, r.max_position_pct, r.rank,
                    Jsonb(r.top_factors), Jsonb(r.catalysts), r.feature_day, r.bench_ref_price,
                )
                for r in rows
            ],
        )


def open_picks(conn: psycopg.Connection) -> list[OpenPick]:
    """The picks still open, each with the kind of the run that made it."""
    rows = conn.execute(
        "select p.id, p.symbol, p.market, p.horizon_days, p.exit_by, p.entry_ref_price, p.stop, p.feature_day,"
        " p.bench_ref_price, r.kind from picks p join runs r on r.id = p.run_id"
        " where p.status = 'open' order by p.id"
    ).fetchall()
    return [
        OpenPick(
            r["id"], r["symbol"], r["market"], r["horizon_days"], r["exit_by"], float(r["entry_ref_price"]),
            float(r["stop"]), r["feature_day"],
            None if r["bench_ref_price"] is None else float(r["bench_ref_price"]), r["kind"],
        )
        for r in rows
    ]


def mark_exited_early(conn: psycopg.Connection, ids: Sequence[int]) -> None:
    """Close these open picks as exited early: the run that flagged them grades them at its close."""
    if ids:
        conn.execute("update picks set status = 'exited_early' where id = any(%s) and status = 'open'", (list(ids),))


def set_pick_status(conn: psycopg.Connection, ids: Sequence[int], status: str) -> None:
    """Close these picks with `status`; only a pick still open changes."""
    if ids:
        conn.execute("update picks set status = %s where id = any(%s) and status = 'open'", (status, list(ids)))


def write_pick_outcomes(conn: psycopg.Connection, rows: Sequence[tuple[int, Outcome]]) -> None:
    """Store graded picks' outcomes, by pick id."""
    with conn.cursor() as cur:
        cur.executemany(
            "insert into pick_outcomes (pick_id, exit_price, exit_reason, ret, ret_net_of_fx, bench_ret, excess,"
            " beat, hit_stop) values (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            [
                (
                    pick_id, o.exit_price, o.exit_reason, o.ret, o.ret_net_of_fx, o.bench_ret, o.excess,
                    o.beat, o.hit_stop,
                )
                for pick_id, o in rows
            ],
        )


def actions_to_grade(conn: psycopg.Connection) -> list[ActionToGrade]:
    """Stock holding actions with an exit-by date and what grading needs, not yet graded."""
    rows = conn.execute(
        "select a.run_id, a.account, a.symbol, a.asset_type, a.feature_day, a.exit_by, a.ref_price,"
        " a.bench_ref_price, a.trailing_stop from holding_actions a"
        " where a.asset_type = 'stock' and a.exit_by is not null and a.feature_day is not null"
        " and a.ref_price is not null and a.bench_ref_price is not null"
        " and not exists (select 1 from holding_action_outcomes o where (o.run_id, o.account, o.symbol,"
        "   o.asset_type) = (a.run_id, a.account, a.symbol, a.asset_type))"
        " order by a.run_id, a.account, a.symbol"
    ).fetchall()
    return [
        ActionToGrade(
            r["run_id"], r["account"], r["symbol"], r["asset_type"], r["feature_day"], r["exit_by"],
            float(r["ref_price"]), float(r["bench_ref_price"]),
            None if r["trailing_stop"] is None else float(r["trailing_stop"]),
        )
        for r in rows
    ]


def symbols_to_grade(conn: psycopg.Connection) -> list[str]:
    """The stocks grading still waits on, sorted: those with an open pick, or with an ungraded
    holding action that has an exit-by date. A stock the owner has sold stays here until graded."""
    rows = conn.execute(
        "select symbol from picks where asset_type = 'stock' and status = 'open'"
        " union select a.symbol from holding_actions a"
        " where a.asset_type = 'stock' and a.exit_by is not null"
        " and not exists (select 1 from holding_action_outcomes o where (o.run_id, o.account, o.symbol,"
        "   o.asset_type) = (a.run_id, a.account, a.symbol, a.asset_type))"
        " order by symbol"
    ).fetchall()
    return [r["symbol"] for r in rows]


def write_action_outcomes(conn: psycopg.Connection, rows: Sequence[tuple[ActionToGrade, Outcome]]) -> None:
    """Store graded holding actions' outcomes."""
    with conn.cursor() as cur:
        cur.executemany(
            "insert into holding_action_outcomes (run_id, account, symbol, asset_type, exit_price, ret,"
            " ret_net_of_fx, bench_ret, excess, beat, hit_stop)"
            " values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            [
                (
                    a.run_id, a.account, a.symbol, a.asset_type, o.exit_price, o.ret, o.ret_net_of_fx,
                    o.bench_ret, o.excess, o.beat, o.hit_stop,
                )
                for a, o in rows
            ],
        )


def load_picks(conn: psycopg.Connection, ids: Sequence[int]) -> dict[int, LinkedPick]:
    """The picks with these ids, by id: the ones holdings were bought on."""
    if not ids:
        return {}
    rows = conn.execute(
        "select id, horizon_days, exit_by, stop, status, top_factors from picks where id = any(%s)", (list(ids),)
    ).fetchall()
    return {
        r["id"]: LinkedPick(r["id"], r["horizon_days"], r["exit_by"], float(r["stop"]), r["status"], r["top_factors"])
        for r in rows
    }


def write_holding_actions(conn: psycopg.Connection, run_id: int, rows: Sequence[HoldingActionRow]) -> None:
    """Store a run's action for each holding, per account."""
    with conn.cursor() as cur:
        cur.executemany(
            "insert into holding_actions (run_id, account, symbol, asset_type, action, review, reasons, warnings,"
            " trailing_stop, q10, q50, q90, exit_by, horizon_days, feature_day, ref_price, bench_ref_price,"
            " risk_level, max_position_pct)"
            " values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            [
                (
                    run_id, r.account, r.symbol, r.asset_type.value, r.action, r.review, Jsonb(r.reasons),
                    Jsonb(r.warnings), r.trailing_stop, r.q10, r.q50, r.q90, r.exit_by, r.horizon_days,
                    r.feature_day, r.ref_price, r.bench_ref_price, r.risk_level, r.max_position_pct,
                )
                for r in rows
            ],
        )


def write_watchlist_verdicts(conn: psycopg.Connection, run_id: int, verdicts: Sequence[Verdict]) -> None:
    """Store a run's verdict for each watched symbol."""
    with conn.cursor() as cur:
        cur.executemany(
            "insert into watchlist_verdicts (run_id, symbol, asset_type, verdict, reasons, details)"
            " values (%s, %s, %s, %s, %s, %s)",
            [(run_id, v.symbol, v.asset_type, v.verdict, Jsonb(v.reasons), Jsonb(v.details)) for v in verdicts],
        )


def news_sentiment(conn: psycopg.Connection, run_id: int, symbols: Sequence[str]) -> dict[str, float]:
    """Each stock's mean news sentiment this run, for the risk score's signal disagreement.

    A stock the news stage covered but couldn't score maps to NaN; one it never covered is left
    out, which is what makes its news feature group missing.
    """
    rows = conn.execute(
        "select symbol, features from features_live"
        " where run_id = %s and asset_type = 'stock' and symbol = any(%s)",
        (run_id, list(symbols)),
    ).fetchall()
    out: dict[str, float] = {}
    for r in rows:
        if any(key.startswith("news_") for key in r["features"]):
            mean = r["features"].get("news_sentiment_mean")
            out[r["symbol"]] = float(mean) if mean is not None else float("nan")
    return out


def fee_settings(conn: psycopg.Connection) -> tuple[float, float]:
    """(USD FX fee, crypto fee) in percent."""
    row = conn.execute("select usd_fx_fee_pct, crypto_fee_pct from settings where id = 1").fetchone()
    return float(row["usd_fx_fee_pct"]), float(row["crypto_fee_pct"])


def stock_sectors(conn: psycopg.Connection, market: Market) -> list[tuple[str, str, str | None]]:
    """(symbol, sector, industry) of the market's labelled stocks: which sector ETF each is compared with."""
    rows = conn.execute(
        "select symbol, sector, industry from symbols"
        " where asset_type = 'stock' and market = %s and sector is not null order by symbol",
        (market.value,),
    ).fetchall()
    return [(r["symbol"], r["sector"], r["industry"]) for r in rows]


def write_sectors(conn: psycopg.Connection, rows: Sequence[tuple[str, str, str | None]]) -> int:
    """Set (symbol, sector, industry) on known stocks; a row without a sector keeps what it had."""
    labelled = [(sector, industry, symbol) for symbol, sector, industry in rows if sector is not None]
    with conn.transaction():
        with conn.cursor() as cur:
            cur.executemany(
                "update symbols set sector = %s, industry = %s, updated_at = now()"
                " where symbol = %s and asset_type = 'stock'",
                labelled,
            )
            return cur.rowcount


def load_held_symbols(conn: psycopg.Connection) -> set[AssetRef]:
    rows = conn.execute(
        "with bought as (select symbol, asset_type, sum(qty) as qty from lots"
        "   group by symbol, asset_type),"
        " sold as (select symbol, asset_type, sum(qty) as qty from sells"
        "   group by symbol, asset_type)"
        " select b.symbol, b.asset_type from bought b left join sold s using (symbol, asset_type)"
        " where b.qty - coalesce(s.qty, 0) > 0"
    ).fetchall()
    return {AssetRef(r["symbol"], AssetType(r["asset_type"])) for r in rows}


def load_watchlist(conn: psycopg.Connection) -> set[AssetRef]:
    rows = conn.execute("select symbol, asset_type from watchlist").fetchall()
    return {AssetRef(r["symbol"], AssetType(r["asset_type"])) for r in rows}


def write_features_live(
    conn: psycopg.Connection,
    run_id: int,
    rows: Sequence[tuple[AssetRef, dict]],
    as_of: datetime,
) -> None:
    if not rows:
        return
    with conn.cursor() as cur:
        cur.executemany(
            "insert into features_live (run_id, symbol, asset_type, features, as_of)"
            " values (%s, %s, %s, %s, %s)",
            [(run_id, ref.symbol, ref.asset_type.value, Jsonb(feats), as_of) for ref, feats in rows],
        )


def merge_features_live(
    conn: psycopg.Connection,
    run_id: int,
    rows: Sequence[tuple[AssetRef, dict]],
    as_of: datetime,
) -> None:
    """Add features to each asset's row for this run, creating the row if there is none yet."""
    if not rows:
        return
    with conn.cursor() as cur:
        cur.executemany(
            "insert into features_live (run_id, symbol, asset_type, features, as_of)"
            " values (%s, %s, %s, %s, %s)"
            " on conflict (run_id, symbol, asset_type)"
            " do update set features = features_live.features || excluded.features",
            [(run_id, ref.symbol, ref.asset_type.value, Jsonb(feats), as_of) for ref, feats in rows],
        )


def write_news_items(conn: psycopg.Connection, rows: Sequence[NewsRow]) -> None:
    """Store news rows. A row an earlier run stored is kept; it only gains a missing sentiment."""
    if not rows:
        return
    with conn.cursor() as cur:
        cur.executemany(
            "insert into news_items (symbol, asset_type, published_at, outlet, url, title,"
            " sentiment, cluster_id, story_key) values (%s, %s, %s, %s, %s, %s, %s, %s, %s)"
            " on conflict (symbol, asset_type, story_key)"
            " do update set sentiment = excluded.sentiment"
            " where news_items.sentiment is null and excluded.sentiment is not null",
            [
                (
                    row.ref.symbol, row.ref.asset_type.value, row.published_at, row.outlet,
                    row.url, row.title, row.sentiment, row.cluster_id, row.story_key,
                )
                for row in rows
            ],
        )


def prune_news_items(conn: psycopg.Connection, now: datetime, kept: timedelta = NEWS_KEPT) -> int:
    """Delete news published more than 90 days before `now`; returns how many rows went."""
    return conn.execute("delete from news_items where published_at < %s", (now - kept,)).rowcount


def news_daily_counts(
    conn: psycopg.Connection, refs: Iterable[AssetRef], since: datetime, until: datetime
) -> dict[AssetRef, list[int]]:
    """Each asset's stories per UTC day in [since, until), over the days that have any news.

    A day with news for other assets but none for this one counts as 0; a day with no news at all
    (before the pipeline started) is left out.
    """
    rows = conn.execute(
        "select symbol, asset_type, (published_at at time zone 'UTC')::date as day,"
        " count(distinct cluster_id) as stories from news_items"
        " where published_at >= %s and published_at < %s group by 1, 2, 3",
        (since, until),
    ).fetchall()
    days = sorted({row["day"] for row in rows})
    counts: dict[AssetRef, dict[date, int]] = defaultdict(dict)
    for row in rows:
        counts[AssetRef(row["symbol"], AssetType(row["asset_type"]))][row["day"]] = row["stories"]
    return {ref: [counts[ref].get(day, 0) for day in days] for ref in refs}


def recent_news(
    conn: psycopg.Connection, refs: Iterable[AssetRef], since: datetime
) -> dict[AssetRef, list[StoredNews]]:
    """The story rows earlier runs stored for these assets since `since`, oldest first."""
    wanted = set(refs)
    rows = conn.execute(
        "select symbol, asset_type, url, title, published_at, story_key from news_items"
        " where published_at >= %s order by published_at, story_key",
        (since,),
    ).fetchall()
    stored: dict[AssetRef, list[StoredNews]] = defaultdict(list)
    for row in rows:
        ref = AssetRef(row["symbol"], AssetType(row["asset_type"]))
        if ref in wanted:
            stored[ref].append(
                StoredNews(row["url"], row["title"], row["published_at"], row["story_key"])
            )
    return dict(stored)


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


def rescale_refs(conn: psycopg.Connection, ref: AssetRef, factor: float) -> None:
    """Multiply the prices recorded for a stock that grading hasn't used yet by `factor`, when its
    stored closes are rescaled: they were recorded in the same, older adjustment.

    That is open picks' entry and stop, and ungraded holding actions' reference price and trailing
    stop. A market's benchmark also moves its open picks' and ungraded actions' benchmark price.
    """
    ungraded = (
        " and not exists (select 1 from holding_action_outcomes o where (o.run_id, o.account, o.symbol,"
        "   o.asset_type) = (a.run_id, a.account, a.symbol, a.asset_type))"
    )
    conn.execute(
        "update picks set entry_ref_price = entry_ref_price * %(f)s, stop = stop * %(f)s"
        " where symbol = %(s)s and asset_type = %(t)s and status = 'open'",
        {"f": factor, "s": ref.symbol, "t": ref.asset_type.value},
    )
    conn.execute(
        "update holding_actions a set ref_price = ref_price * %(f)s, trailing_stop = trailing_stop * %(f)s"
        " where a.symbol = %(s)s and a.asset_type = %(t)s" + ungraded,
        {"f": factor, "s": ref.symbol, "t": ref.asset_type.value},
    )
    market = market_of(ref.symbol)
    if ref.asset_type is not AssetType.STOCK or ref.symbol != MARKETS[market].benchmark:
        return
    conn.execute(
        "update picks set bench_ref_price = bench_ref_price * %s where market = %s and status = 'open'",
        (factor, market.value),
    )
    tsx = market is Market.TSX
    conn.execute(
        "update holding_actions a set bench_ref_price = bench_ref_price * %s"
        " where a.asset_type = 'stock' and (a.symbol like %s) = %s" + ungraded,
        (factor, f"%{TSX_SUFFIX}", tsx),
    )


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


def previous_trailing_stops(conn: psycopg.Connection) -> dict[tuple[str, str, str], tuple[date, float]]:
    """Per holding (account, symbol, asset type), the feature day and trailing stop of its newest
    holding action that has both."""
    rows = conn.execute(
        "select distinct on (account, symbol, asset_type) account, symbol, asset_type, feature_day, trailing_stop"
        " from holding_actions where feature_day is not null and trailing_stop is not null"
        " order by account, symbol, asset_type, run_id desc"
    ).fetchall()
    return {
        (r["account"], r["symbol"], r["asset_type"]): (r["feature_day"], float(r["trailing_stop"])) for r in rows
    }


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


def latest_fx_rate(conn: psycopg.Connection) -> float | None:
    row = conn.execute("select usd_cad from fx_rates order by day desc limit 1").fetchone()
    return None if row is None else float(row["usd_cad"])


def load_fx_rates(conn: psycopg.Connection) -> dict[date, float]:
    rows = conn.execute("select day, usd_cad from fx_rates").fetchall()
    return {r["day"]: float(r["usd_cad"]) for r in rows}


def load_trades(conn: psycopg.Connection) -> list[Trade]:
    """Every buy (lots) and sell, for the ledger to put in order."""
    rows = conn.execute(
        "select 'buy' as side, account, symbol, asset_type, qty, price, currency, fx_rate_cad,"
        "   bought_at as day, pick_id from lots"
        " union all"
        " select 'sell', account, symbol, asset_type, qty, price, currency, fx_rate_cad,"
        "   sold_at, null from sells"
    ).fetchall()
    return [
        Trade(
            side=r["side"], account=r["account"], symbol=r["symbol"],
            asset_type=AssetType(r["asset_type"]), qty=float(r["qty"]), price=float(r["price"]),
            currency=r["currency"],
            fx_rate_cad=None if r["fx_rate_cad"] is None else float(r["fx_rate_cad"]),
            day=r["day"], pick_id=r["pick_id"],
        )
        for r in rows
    ]


def prune_daily_closes(conn: psycopg.Connection, before: date, keep: Iterable[str]) -> int:
    """Delete closes from before `before`, except for assets ever bought and the `keep` symbols."""
    return conn.execute(
        "delete from daily_closes c where c.day < %s and c.symbol <> all(%s)"
        " and not exists (select 1 from lots l"
        "   where l.symbol = c.symbol and l.asset_type = c.asset_type)",
        (before, list(keep)),
    ).rowcount


BENCHMARK_ABANDONED_AFTER = timedelta(hours=7)  # past Actions' 6-hour job limit


def start_benchmark_run(conn: psycopg.Connection, now: datetime, git_sha: str | None) -> int:
    """Open a benchmark run, and mark any still-running one past the job limit as failed."""
    conn.execute(
        "update benchmark_runs set status = 'failed', finished_at = %s, report = report || %s"
        " where status = 'running' and started_at < %s",
        (
            now,
            Jsonb({"error": "abandoned: no finish was recorded (job killed or timed out)"}),
            now - BENCHMARK_ABANDONED_AFTER,
        ),
    )
    row = conn.execute(
        "insert into benchmark_runs (started_at, git_sha) values (%s, %s) returning id",
        (now, git_sha),
    ).fetchone()
    return row["id"]


def finish_benchmark_run(
    conn: psycopg.Connection, run_id: int, now: datetime, status: str, report: Mapping
) -> None:
    conn.execute(
        "update benchmark_runs set finished_at = %s, status = %s, report = %s where id = %s",
        (now, status, Jsonb(dict(report)), run_id),
    )


def write_benchmark_results(
    conn: psycopg.Connection, run_id: int, rows: Sequence[BenchmarkResult]
) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            "insert into benchmark_results (run_id, market, variant, fold, metrics)"
            " values (%s, %s, %s, %s, %s)",
            [(run_id, r.market, r.variant, r.fold, Jsonb(dict(r.metrics))) for r in rows],
        )


def active_config(conn: psycopg.Connection, market: str) -> AcceptedConfig | None:
    row = conn.execute(
        "select id, market, config, reason, accepted_at, benchmark_run_id"
        " from accepted_configs where market = %s and active",
        (market,),
    ).fetchone()
    return AcceptedConfig(**row) if row else None


def accept_config(
    conn: psycopg.Connection,
    market: str,
    config: Mapping,
    reason: str,
    run_id: int,
    now: datetime,
) -> int:
    """Retire the market's active row and insert the new one, atomically."""
    with conn.transaction():
        conn.execute(
            "update accepted_configs set active = false where market = %s and active", (market,)
        )
        row = conn.execute(
            "insert into accepted_configs"
            " (market, config, reason, accepted_at, benchmark_run_id, active)"
            " values (%s, %s, %s, %s, %s, true) returning id",
            (market, Jsonb(dict(config)), reason, now, run_id),
        ).fetchone()
        return row["id"]

