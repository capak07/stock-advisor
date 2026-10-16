from datetime import UTC, date, datetime

from advisor.collectors.coingecko import CryptoQuote
from advisor.crypto_prices import crypto_feature_rows, unconfirmed
from advisor.models import AssetRef, AssetType
from fakes import bar, history

NOW = datetime(2026, 10, 14, 12, 15, tzinfo=UTC)
QUOTE = CryptoQuote(
    symbol="BTC", coin_id="bitcoin", price_cad=117087.0, market_cap_cad=2.35e12,
    volume_24h_cad=5.8e10, change_24h_pct=0.56, market_cap_rank=1, updated_at=NOW,
)
DAY = date(2026, 10, 13)


def test_a_latest_close_within_two_percent_of_kraken_is_confirmed():
    assert unconfirmed([bar("BTC", DAY, 82000.0)], [bar("BTC", DAY, 81000.0)]) is False  # 1.2%


def test_a_latest_close_more_than_two_percent_from_kraken_is_unconfirmed():
    assert unconfirmed([bar("BTC", DAY, 82000.0)], [bar("BTC", DAY, 80000.0)]) is True  # 2.5%


def test_without_krakens_close_for_that_day_nothing_is_known():
    assert unconfirmed([bar("BTC", DAY, 82000.0)], [bar("BTC", date(2026, 10, 12), 1.0)]) is None
    assert unconfirmed([], [bar("BTC", DAY, 82000.0)]) is None


def test_a_coin_with_a_quote_and_candles_gets_every_feature():
    candles = history("BTC", 30, close=82000.0, source="coinbase", start=date(2026, 9, 14))
    [(ref, features)] = crypto_feature_rows(
        ["BTC"], {"BTC": QUOTE}, {"BTC": candles}, {"BTC": [bar("BTC", DAY, 82100.0)]}, NOW
    )
    assert ref == AssetRef("BTC", AssetType.CRYPTO)
    assert features == {
        "price_cad": 117087.0, "market_cap_cad": 2.35e12, "volume_24h_cad": 5.8e10,
        "change_24h_pct": 0.56, "market_cap_rank": 1,
        "quote_updated_at": "2026-10-14T12:15:00+00:00", "quote_stale": False,
        "last_close_usd": 82000.0, "history_days": 30, "last_day": "2026-10-13",
        "stale": False, "unconfirmed_price": False,
    }


def test_a_coin_with_only_a_quote_or_old_candles_still_gets_a_row():
    old = history("ETH", 30, close=3400.0, source="coinbase", start=date(2026, 9, 1))  # ends 09-30
    rows = dict(crypto_feature_rows(["BTC", "ETH", "XYZ"], {"BTC": QUOTE}, {"ETH": old}, {}, NOW))
    assert set(rows) == {AssetRef("BTC", AssetType.CRYPTO), AssetRef("ETH", AssetType.CRYPTO)}
    assert "last_close_usd" not in rows[AssetRef("BTC", AssetType.CRYPTO)]
    eth = rows[AssetRef("ETH", AssetType.CRYPTO)]
    assert (eth["stale"], eth["unconfirmed_price"], "price_cad" in eth) == (True, None, False)


def test_a_quote_older_than_a_day_is_marked_stale():
    old = QUOTE.model_copy(update={"updated_at": datetime(2026, 10, 12, 12, 0, tzinfo=UTC)})
    [(_, features)] = crypto_feature_rows(["BTC"], {"BTC": old}, {}, {}, NOW)
    assert (features["quote_updated_at"], features["quote_stale"]) == ("2026-10-12T12:00:00+00:00", True)
