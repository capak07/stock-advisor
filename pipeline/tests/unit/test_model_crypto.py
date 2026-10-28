import json

import numpy as np
import pandas as pd
import pytest

from advisor.model.crypto import CRYPTO, CRYPTO_HORIZONS, CRYPTO_WARMUP, UNIVERSE, load_crypto
from advisor.model.train import PARAMS, TrainConfig, training_rows, walk_forward

START = pd.Timestamp("2020-01-04")  # a Saturday: every row falls on one


def _bars(symbol, days, close, volume):
    close = np.asarray(close, float)
    return pd.DataFrame({"symbol": symbol, "day": [d.date() for d in days], "open": close, "high": close * 1.01,
                         "low": close * 0.99, "close": close, "volume": volume})


def write(tmp, coins=6, days=600, seed=1):
    rng = np.random.default_rng(seed)
    cal = pd.date_range(START, periods=days)
    walk = lambda sd: np.exp(np.cumsum(rng.normal(0, sd, days)))  # noqa: E731
    frames = [_bars("BTC", cal, 100 * walk(0.03), 1e6)]
    frames += [_bars(f"C{i:03d}", cal, 10 * walk(0.04), 1e5 * (i + 1)) for i in range(coins)]
    frames += [_bars("USDT", cal, np.ones(days), 1e9), _bars("FLAT", cal, np.full(days, 5.0), 1e9)]
    frames.append(_bars("YOUNG", cal[-200:], 3 * walk(0.04)[-200:], 1e9))
    pd.concat(frames).to_parquet(tmp / "prices_crypto.parquet", index=False)
    weekdays = cal[cal.dayofweek < 5]
    spy = 400 * np.exp(np.cumsum(rng.normal(0, 0.01, len(weekdays))))
    _bars("SPY", weekdays, spy, 1e7).to_parquet(tmp / "prices_US.parquet", index=False)
    (tmp / "manifest.json").write_text(json.dumps({"end": (cal[-1] + pd.Timedelta(days=1)).date().isoformat()}))
    return pd.concat(frames), _bars("SPY", weekdays, spy, 1e7)


def test_rows_are_weekly_and_in_the_universe(tmp_path):
    write(tmp_path)
    data = load_crypto(tmp_path)
    assert data.market == CRYPTO
    days = pd.DatetimeIndex(sorted(data.rows["day"].unique()))
    assert (days.to_series().diff().dropna() == pd.Timedelta(days=7)).all()
    assert days[0] >= START + pd.Timedelta(days=CRYPTO_WARMUP)
    assert not {"USDT", "FLAT", "YOUNG"} & set(data.rows["symbol"])
    assert {"BTC", "C000"} <= set(data.rows["symbol"])


def test_only_the_top_coins_by_dollar_volume_are_kept(tmp_path):
    prices, _ = write(tmp_path, coins=UNIVERSE + 5, days=400)
    data = load_crypto(tmp_path)
    counts = data.rows.groupby("day")["symbol"].count()
    assert (counts == UNIVERSE).all()
    day = data.rows["day"].iloc[0]
    wide = prices.assign(day=pd.to_datetime(prices["day"]), dv=prices["close"] * prices["volume"])
    dv30 = wide.pivot(index="day", columns="symbol", values="dv").rolling(30).mean().loc[day]
    dv30 = dv30.drop(["USDT", "FLAT", "YOUNG"], errors="ignore").dropna().sort_values(ascending=False)
    assert set(data.rows.loc[data.rows["day"] == day, "symbol"]) == set(dv30.index[:UNIVERSE])


def test_altcoins_are_judged_against_btc_and_btc_against_spy(tmp_path):
    prices, spy = write(tmp_path)
    data = load_crypto(tmp_path)
    close = prices.assign(day=pd.to_datetime(prices["day"])).pivot(index="day", columns="symbol", values="close")
    day = data.rows["day"].iloc[0]
    assert day.dayofweek == 5  # a Saturday: SPY's last close is Friday's
    later = day + pd.Timedelta(days=7)
    btc = close.at[later, "BTC"] / close.at[day, "BTC"] - 1
    alt = data.rows[(data.rows["day"] == day) & (data.rows["symbol"] == "C000")]["y_7"].item()
    assert alt == pytest.approx(close.at[later, "C000"] / close.at[day, "C000"] - 1 - btc)
    spy_close = spy.assign(day=pd.to_datetime(spy["day"])).set_index("day")["close"]
    friday, next_friday = day - pd.Timedelta(days=1), later - pd.Timedelta(days=1)
    btc_y = data.rows[(data.rows["day"] == day) & (data.rows["symbol"] == "BTC")]["y_7"].item()
    assert btc_y == pytest.approx(btc - (spy_close[next_friday] / spy_close[friday] - 1))


def test_features_and_targets_are_known_on_their_day(tmp_path):
    prices, _ = write(tmp_path)
    before = load_crypto(tmp_path).rows
    t = before["day"].iloc[len(before) // 2]
    changed = prices.copy()
    later = pd.to_datetime(changed["day"]) > t + pd.Timedelta(days=7)
    changed.loc[later, "close"] *= 1.5
    changed.loc[later, "volume"] *= 3
    changed.to_parquet(tmp_path / "prices_crypto.parquet", index=False)
    after = load_crypto(tmp_path).rows
    cols = ["day", "symbol", "y_7", *load_crypto(tmp_path).features]
    keep = lambda r: r[r["day"] <= t][cols].reset_index(drop=True)  # noqa: E731
    pd.testing.assert_frame_equal(keep(before), keep(after))


def test_the_embargo_counts_calendar_days(tmp_path):
    write(tmp_path)
    data = load_crypto(tmp_path)
    start = data.rows["day"].iloc[len(data.rows) // 2]
    kept = training_rows(data.rows, data.calendar, 30, start)
    assert not kept.empty and (kept["day"] + pd.Timedelta(days=30) < start).all()


def test_walk_forward_trains_on_crypto(tmp_path):
    write(tmp_path, coins=30, days=1300)
    config = TrainConfig(horizons=CRYPTO_HORIZONS, rounds=20, params={**PARAMS, "min_data_in_leaf": 20, "num_threads": 2})
    wf = walk_forward(load_crypto(tmp_path), config)
    assert set(wf.predictions["horizon"]) == set(CRYPTO_HORIZONS)
