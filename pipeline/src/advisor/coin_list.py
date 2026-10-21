"""The coins the dashboard's search offers: CoinGecko's top coins by market cap.

The watchlist only accepts what its search lists, and stocks come with names from the stock
directories, but coins have no list of their own. So the run stores the top COIN_LIST_SIZE coins
in `symbols` once per ET day: two keyless `/coins/markets` requests. Many tokens share a ticker,
and the best-ranked one is the real one. Only coins Coinbase trades in USD are listed, since its
candles are the only daily closes coins get; a coin it doesn't trade could be watched but never
priced. Refreshing is best-effort: a failure or a short answer is noted in the run summary and
never changes the run's status, and yesterday's list stays in place.
"""

import re
from collections.abc import Sequence
from datetime import datetime
from typing import Any

import httpx
import psycopg

from advisor.collectors.base import RateLimiter, get_with_retries
from advisor.collectors.coingecko import ATTEMPTS, COINGECKO_PER_MINUTE, MARKETS_URL
from advisor.collectors.coins import listed_as
from advisor.models import ET
from advisor.store import repo

COIN_LIST_SIZE = 300
PAGE = 250  # CoinGecko's largest page
COIN_SYMBOL = re.compile(r"[A-Z0-9]{2,10}")  # the symbols table's crypto format
FULL_ANSWER = 0.9  # a share of the two pages below this is a short answer, not the market
PRODUCTS_URL = "https://api.exchange.coinbase.com/products"
MIN_COINBASE_COINS = 50  # Coinbase trades a few hundred coins in USD; fewer is a broken answer


def _rank(row: dict[str, Any]) -> tuple[bool, int]:
    rank = row.get("market_cap_rank")
    return rank is None, rank or 0


Coin = tuple[str, str, float | None]  # symbol, name, market cap in USD


def top_coins(
    rows: Sequence[dict[str, Any]], size: int = COIN_LIST_SIZE, tradable: set[str] | None = None
) -> list[Coin]:
    """(symbol, name, market cap) of the best-ranked coin per ticker, best first, at most `size`;
    tickers the app can't store, coins without a name and, given `tradable`, coins whose current
    ticker isn't in it are left out."""
    coins: list[Coin] = []
    seen: set[str] = set()
    for row in sorted(rows, key=_rank):
        symbol = str(row.get("symbol") or "").upper()
        name = str(row.get("name") or "").strip()
        if not name or symbol in seen or not COIN_SYMBOL.fullmatch(symbol):
            continue
        if tradable is not None and listed_as(symbol) not in tradable:
            continue
        seen.add(symbol)
        cap = row.get("market_cap")
        coins.append((symbol, name, float(cap) if isinstance(cap, (int, float)) else None))
        if len(coins) == size:
            break
    return coins


def coinbase_usd_coins(client: httpx.Client) -> set[str]:
    """The coins Coinbase trades in USD now: its online, enabled `-USD` products."""
    products = get_with_retries(client, PRODUCTS_URL, attempts=ATTEMPTS).json()
    coins = {
        str(p.get("base_currency"))
        for p in products
        if p.get("quote_currency") == "USD" and p.get("status") == "online" and not p.get("trading_disabled")
    }
    if len(coins) < MIN_COINBASE_COINS:
        raise ValueError(f"Coinbase listed only {len(coins)} USD coins")
    return coins


def fetch_top_coins(
    client: httpx.Client,
    limiter: RateLimiter | None = None,
    size: int = COIN_LIST_SIZE,
    tradable: set[str] | None = None,
) -> list[Coin]:
    """The top coins by market cap from two pages of 250. A short answer raises: storing it would
    take the coins it left out off the list for the rest of the day."""
    rows: list[dict[str, Any]] = []
    for page in (1, 2):
        response = get_with_retries(
            client,
            MARKETS_URL,
            params={"vs_currency": "usd", "order": "market_cap_desc", "per_page": PAGE, "page": page},
            limiter=limiter,
            attempts=ATTEMPTS,
        )
        rows.extend(response.json())
    if len(rows) < 2 * PAGE * FULL_ANSWER:
        raise ValueError(f"CoinGecko sent only {len(rows)} coins")
    return top_coins(rows, size, tradable)


def refresh_coin_list(conn: psycopg.Connection, client: httpx.Client, now: datetime) -> str | int:
    """Store today's top coins unless today's list is stored already: the number stored, "fresh",
    or "failed: …". Never raises, not even past the run's deadline: the steps after it check that."""
    if repo.coins_refreshed_on(conn) == now.astimezone(ET).date():
        return "fresh"
    try:
        tradable = coinbase_usd_coins(client)
        coins = fetch_top_coins(client, RateLimiter(per_minute=COINGECKO_PER_MINUTE), tradable=tradable)
        repo.upsert_coins(conn, coins, now)
    except Exception as exc:
        return f"failed: {type(exc).__name__}: {exc}"[:200]
    return len(coins)
