import math
from datetime import UTC, date, datetime, timedelta

import pandas as pd

from advisor.model.crypto import BTC, CRYPTO_FEATURES, CRYPTO_HORIZONS, CRYPTO_WARMUP
from advisor.model.crypto_live import forecast_coins
from advisor.models import DailyBar

END = date(2026, 10, 28)
AS_OF = datetime(2026, 10, 29, tzinfo=UTC)


def _bars(symbol: str, n: int) -> list[DailyBar]:
    start = END - timedelta(days=n - 1)
    return [
        DailyBar(
            symbol=symbol, day=start + timedelta(days=i), open=10.0, high=11.0, low=9.0,
            close=10.0 + i * 0.01, volume=2_000_000.0 + (i % 7) * 50_000.0, source="coinbase",
        )
        for i in range(n)
    ]


class _Model:
    features = list(CRYPTO_FEATURES)
    horizons = CRYPTO_HORIZONS

    def predict(self, x: pd.DataFrame) -> pd.DataFrame:
        parts = [
            pd.DataFrame(
                {"horizon": h, "q10": -0.02, "q50": 0.05, "q90": 0.10, "p_beat": 0.70},
                index=x.index,
            )
            for h in self.horizons
        ]
        return pd.concat(parts)


def test_forecast_coins_gives_five_horizons_and_the_right_benchmark():
    bars = {BTC: _bars(BTC, 400), "ETH": _bars("ETH", 400)}
    rows, why = forecast_coins(_Model(), bars, 500.0, AS_OF)
    assert why == {}
    assert [r.horizon_days for r in rows["ETH"]] == list(CRYPTO_HORIZONS)
    assert {r.benchmark for r in rows["ETH"]} == {"BTC"}
    assert {r.benchmark for r in rows[BTC]} == {"SPY"}


def test_a_short_history_and_a_run_without_btc_say_why():
    short = {BTC: _bars(BTC, 400), "ETH": _bars("ETH", 200), "NEW": []}
    rows, why = forecast_coins(_Model(), short, 500.0, AS_OF)
    assert "ETH" not in rows
    assert why["ETH"] == f"only 200 days of history (needs {CRYPTO_WARMUP})"
    assert why["NEW"] == "no daily candles"
    missing = {"ETH": _bars("ETH", 400)}
    rows, why = forecast_coins(_Model(), missing, None, AS_OF)
    assert rows == {}
    assert why == {"ETH": "no BTC candles this run"}


def test_a_model_trained_on_amihud_gets_the_column():
    class Recording(_Model):
        features = [*CRYPTO_FEATURES, "amihud_20"]
        seen: pd.DataFrame | None = None

        def predict(self, x: pd.DataFrame) -> pd.DataFrame:
            type(self).seen = x
            return super().predict(x)

    bars = {BTC: _bars(BTC, 400), "ETH": _bars("ETH", 400)}
    rows, why = forecast_coins(Recording(), bars, 500.0, AS_OF)
    assert why == {} and "ETH" in rows
    assert Recording.seen is not None and "amihud_20" in Recording.seen.columns
    assert Recording.seen["amihud_20"].map(math.isfinite).all()
