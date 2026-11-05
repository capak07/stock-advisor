from datetime import UTC, date, datetime, timedelta

import numpy as np
import pandas as pd

from advisor.model.crypto import BTC, CRYPTO_FEATURES, CRYPTO_HORIZONS
from advisor.model.crypto_live import forecast_coins
from advisor.model.dataset import load_market
from advisor.model.garch import GarchParams, garch_vol, live_garch_vol
from advisor.model.live import live_garch
from advisor.model.train import PARAMS, TrainConfig, fit_final, walk_forward
from advisor.models import DailyBar, Market
from model_data import write_market

FAST = TrainConfig(horizons=(5, 63), rounds=20, params={**PARAMS, "min_data_in_leaf": 50, "num_threads": 2})
P = GarchParams(mu=0.0002, omega=2e-6, alpha=0.08, beta=0.90, nu=6.0, var0=1.5e-4)


def test_live_garch_vol_is_the_windows_last_day_forecast():
    rng = np.random.default_rng(3)
    days = pd.bdate_range("2024-01-01", periods=300)
    closes = pd.DataFrame(
        {"A": 50 * np.exp(np.cumsum(rng.normal(0, 0.01, 300))), "B": 20 * np.exp(np.cumsum(rng.normal(0, 0.02, 300)))},
        index=days,
    )
    out = live_garch_vol(closes, {"A": P, "B": None}, (5, 21))
    assert list(out.index) == ["A", "B"] and list(out.columns) == ["garch_vol_5", "garch_vol_21", "garch_vol"]
    expected = garch_vol(np.log(closes["A"] / closes["A"].shift(1)), P, (5, 21)).iloc[-1]
    np.testing.assert_allclose(out.loc["A", list(expected.index)].to_numpy(dtype=float), expected.to_numpy(), rtol=1e-12)
    assert out.loc["B"].isna().all()
    assert live_garch_vol(closes, {}, (5,)).isna().all().all()  # a symbol the model never fitted


def test_live_garch_matches_training_on_the_same_day(tmp_path):
    write_market(tmp_path, Market.TSX, stocks=20, days=1100)
    data = load_market(tmp_path, Market.TSX, with_garch=True)
    model = fit_final(data, walk_forward(data, FAST, garch=True), FAST, garch=True)
    day = pd.DatetimeIndex(sorted(data.rows["day"].unique()))[-5]
    prices = pd.read_parquet(tmp_path / "prices_TSX.parquet")
    when = pd.to_datetime(prices["day"])
    window = prices[(when <= day) & (when > day - pd.Timedelta(days=400))]  # the live run's LIVE_WINDOW
    live = live_garch(window, Market.TSX, day, model.garch, FAST.horizons)
    compared = 0
    for symbol, params in model.garch.items():
        if params is None:
            continue
        trained = garch_vol(data.returns[symbol], params, FAST.horizons).loc[day]
        np.testing.assert_allclose(live.loc[symbol, list(trained.index)].to_numpy(dtype=float), trained.to_numpy(), rtol=1e-9)
        compared += 1
    assert compared >= 10


END = date(2026, 10, 28)


def _bars(symbol: str, n: int) -> list[DailyBar]:
    start = END - timedelta(days=n - 1)
    return [
        DailyBar(symbol=symbol, day=start + timedelta(days=i), open=10.0, high=11.0, low=9.0,
                 close=10.0 + i * 0.01 + (i % 3) * 0.02, volume=2_000_000.0 + (i % 7) * 50_000.0, source="coinbase")
        for i in range(n)
    ]


class _GarchModel:
    features = list(CRYPTO_FEATURES)
    horizons = CRYPTO_HORIZONS
    garch = {"ETH": P, BTC: None}

    def __init__(self):
        self.seen = []

    def predict(self, x: pd.DataFrame) -> pd.DataFrame:
        self.seen.append(x.copy())
        return pd.concat([
            pd.DataFrame({"horizon": h, "q10": -0.02, "q50": 0.05, "q90": 0.10, "p_beat": 0.70}, index=x.index)
            for h in self.horizons
        ])


def test_coins_carry_garch_columns_for_a_garch_model():
    model = _GarchModel()
    rows, _ = forecast_coins(model, {BTC: _bars(BTC, 400), "ETH": _bars("ETH", 400)}, 500.0, datetime(2026, 10, 29, tzinfo=UTC))
    x = model.seen[0]
    assert {f"garch_vol_{h}" for h in CRYPTO_HORIZONS} <= set(x.columns)
    assert np.isfinite(x.loc["ETH", "garch_vol_7"]) and np.isnan(x.loc[BTC, "garch_vol_7"])
    assert "ETH" in rows and BTC in rows  # a coin without GARCH still gets its forecast


def test_live_output_names_the_month_ahead_volatility_for_explanations():
    days = pd.bdate_range("2024-01-01", periods=300)
    closes = pd.DataFrame({"A": 50 * np.exp(np.cumsum(np.random.default_rng(5).normal(0, 0.01, 300)))}, index=days)
    out = live_garch_vol(closes, {"A": P}, (5, 21, 63))
    assert out.loc["A", "garch_vol"] == out.loc["A", "garch_vol_21"]  # the horizon nearest 21: what's stored
    coins = live_garch_vol(closes, {"A": P}, CRYPTO_HORIZONS)
    assert coins.loc["A", "garch_vol"] == coins.loc["A", "garch_vol_14"]


def test_no_symbols_give_an_empty_frame_not_an_error():
    out = live_garch_vol(pd.DataFrame(index=pd.bdate_range("2024-01-01", periods=5)), {}, (5, 21))
    assert out.empty and list(out.columns) == ["garch_vol_5", "garch_vol_21", "garch_vol"]
