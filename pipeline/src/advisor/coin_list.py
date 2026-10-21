"""The coins the dashboard's search offers: CoinGecko's top coins by market cap.

The watchlist only accepts what its search lists, and stocks come with names from the stock
directories, but coins have no list of their own. So the run stores the top COIN_LIST_SIZE coins
in `symbols` once per ET day: two keyless `/coins/markets` requests. Many tokens share a ticker,
and the best-ranked one is the real one. Refreshing is best-effort: a failure is noted in the
run summary and never changes the run's status, and yesterday's list stays in place.
"""

import re
from collections.abc import Sequence
from datetime import datetime
from typing import Any

import httpx
import psycopg

from advisor.collectors.base import RateLimiter, get_with_retries
from advisor.collectors.coingecko import COINGECKO_PER_MINUTE, MARKETS_URL
from advisor.models import ET
from advisor.store import repo

COIN_LIST_SIZE = 300
PAGE = 250  # CoinGecko's largest page
COIN_SYMBOL = re.compile(r"[A-Z0-9]{2,10}")  # the symbols table's crypto format


def _rank(row: dict[str, Any]) -> tuple[bool, int]:
    rank = row.get("market_cap_rank")
    return rank is None, rank or 0


def top_coins(rows: Sequence[dict[str, Any]], size: int = COIN_LIST_SIZE) -> list[tuple[str, str]]:
    """(symbol, name) of the best-ranked coin per ticker, best first, at most `size`; tickers the
    app can't store and coins without a name are left out."""
    coins: list[tuple[str, str]] = []
    seen: set[str] = set()
    for row in sorted(rows, key=_rank):
        symbol = str(row.get("symbol") or "").upper()
        name = str(row.get("name") or "").strip()
        if not name or symbol in seen or not COIN_SYMBOL.fullmatch(symbol):
            continue
        seen.add(symbol)
        coins.append((symbol, name))
        if len(coins) == size:
            break
    return coins


def fetch_top_coins(
    client: httpx.Client, limiter: RateLimiter | None = None, size: int = COIN_LIST_SIZE
) -> list[tuple[str, str]]:
    rows: list[dict[str, Any]] = []
    for page in (1, 2):
        response = get_with_retries(
            client,
            MARKETS_URL,
            params={"vs_currency": "usd", "order": "market_cap_desc", "per_page": PAGE, "page": page},
            limiter=limiter,
        )
        rows.extend(response.json())
    coins = top_coins(rows, size)
    if not coins:
        raise ValueError("CoinGecko sent no coins")
    return coins


def refresh_coin_list(conn: psycopg.Connection, client: httpx.Client, now: datetime) -> str | int:
    """Store today's top coins unless today's list is stored already: the number stored, "fresh",
    or "failed: …". Never raises."""
    if repo.coins_refreshed_on(conn) == now.astimezone(ET).date():
        return "fresh"
    try:
        coins = fetch_top_coins(client, RateLimiter(per_minute=COINGECKO_PER_MINUTE))
        repo.upsert_coins(conn, coins, now)
    except Exception as exc:
        return f"failed: {type(exc).__name__}: {exc}"[:200]
    return len(coins)
