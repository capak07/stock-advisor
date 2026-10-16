"""Held and watched crypto, priced in the holdings phase (spec §4.3 stage 1, §7.2).

- CoinGecko's CAD quote values a holding (spec §7.4 shows values in CAD).
- Coinbase's finished daily USD candles feed the price features.
- Kraken's candle for Coinbase's latest day cross-checks it: one exchange's bad print would
  otherwise go unnoticed. This is crypto's counterpart of the stock jump rule (spec §10), and
  an unconfirmed latest price blocks a Buy the same way (Plans 4 and 5).
"""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta

from advisor.collectors.coingecko import MAX_QUOTE_AGE, CryptoQuote
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
                quote_updated_at=quote.updated_at.isoformat(),
                quote_stale=as_of - quote.updated_at > MAX_QUOTE_AGE,  # e.g. served from cache
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
