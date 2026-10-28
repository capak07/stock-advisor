"""Full Coinbase USD history for the crypto model's training build.

One coin failing is counted and skipped. A 404 or an empty page means that product has no more
history. The stock build keeps going when this whole step fails.
"""

from datetime import UTC, date, datetime, timedelta

import httpx
import pandas as pd

from advisor.collectors.coinbase_candles import ONE_DAY, parse_candles

PRODUCTS_URL = "https://api.exchange.coinbase.com/products"
CANDLES_URL = "https://api.exchange.coinbase.com/products/{product}/candles"
EARLIEST = date(2015, 1, 1)
PAGE_DAYS = 300
COLUMNS = ["symbol", "day", "open", "high", "low", "close", "volume"]


def _empty() -> pd.DataFrame:
    return pd.DataFrame(columns=COLUMNS)


def _frame(bars) -> pd.DataFrame:
    return pd.DataFrame(
        [(b.symbol, b.day, b.open, b.high, b.low, b.close, b.volume) for b in bars],
        columns=COLUMNS,
    )


def list_products(client: httpx.Client) -> list[str]:
    """USD base currencies, including delisted products, sorted and de-duplicated."""
    response = client.get(PRODUCTS_URL)
    response.raise_for_status()
    bases = {
        row["base_currency"]
        for row in response.json()
        if row.get("quote_currency") == "USD" and row.get("base_currency")
    }
    return sorted(bases)


def fetch_history(client: httpx.Client, symbol: str, end: date, limiter) -> pd.DataFrame:
    """Finished daily bars before `end`, oldest first. An empty page or a 404 ends the walk."""
    as_of = datetime(end.year, end.month, end.day, tzinfo=UTC)
    cursor = end
    parts: list[pd.DataFrame] = []
    while cursor > EARLIEST:
        start = max(EARLIEST, cursor - timedelta(days=PAGE_DAYS))
        if limiter is not None:
            limiter.acquire()
        try:
            response = client.get(
                CANDLES_URL.format(product=f"{symbol}-USD"),
                params={
                    "granularity": str(ONE_DAY),
                    "start": f"{start.isoformat()}T00:00:00Z",
                    "end": f"{cursor.isoformat()}T00:00:00Z",
                },
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                break
            raise
        rows = response.json()
        if not rows:
            break
        bars = parse_candles(symbol, rows, as_of)
        if bars:
            parts.append(_frame(bars))
        if start == EARLIEST:
            break
        cursor = start
    if not parts:
        return _empty()
    out = pd.concat(parts, ignore_index=True)
    return out.drop_duplicates(["symbol", "day"]).sort_values(["symbol", "day"], ignore_index=True)[COLUMNS]


def download_crypto(client: httpx.Client, end: date, limiter) -> tuple[pd.DataFrame, dict]:
    """Every USD product's history. One coin's failure is counted and the rest continue."""
    symbols = list_products(client)
    parts: list[pd.DataFrame] = []
    failures = 0
    for symbol in symbols:
        try:
            frame = fetch_history(client, symbol, end, limiter)
        except Exception:
            failures += 1
            continue
        if not frame.empty:
            parts.append(frame)
    out = pd.concat(parts, ignore_index=True) if parts else _empty()
    coins = int(out["symbol"].nunique()) if not out.empty else 0
    return out, {"coins": coins, "rows": int(len(out)), "failures": failures}
