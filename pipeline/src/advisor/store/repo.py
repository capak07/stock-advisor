"""Every SQL statement the pipeline runs. Functions take an open autocommit connection."""

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime, timedelta

import psycopg
from psycopg.types.json import Jsonb

from advisor.collectors.base import Collector, CollectorResult
from advisor.collectors.runner import SourceState
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
from advisor.news.stage import NewsRow, StoredNews

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
            " sources_total = %s, summary = %s, published = %s where id = %s",
            (status.value, sources_ok, sources_total, Jsonb(summary), publish, run_id),
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
