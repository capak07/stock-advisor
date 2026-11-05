import numpy as np
import pandas as pd

from advisor.model.crypto import load_crypto
from advisor.model.dataset import load_market
from advisor.models import Market
from model_data import write_crypto, write_market


def _closes(path, calendar):
    prices = pd.read_parquet(path)
    close = prices.pivot(index="day", columns="symbol", values="close")
    close.index = pd.to_datetime(close.index)
    return close.reindex(calendar)


def test_returns_are_loaded_only_when_asked_and_leave_the_rows_alone(tmp_path):
    write_market(tmp_path, Market.TSX, stocks=3, days=400)
    plain = load_market(tmp_path, Market.TSX)
    garch = load_market(tmp_path, Market.TSX, with_garch=True)
    assert plain.returns is None and garch.garch_cache == {}
    pd.testing.assert_frame_equal(plain.rows, garch.rows)
    assert plain.features == garch.features and plain.extras == garch.extras


def test_a_markets_returns_are_daily_log_returns_of_its_rows_symbols(tmp_path):
    stocks = write_market(tmp_path, Market.TSX, stocks=3, days=400)
    data = load_market(tmp_path, Market.TSX, with_garch=True)
    assert data.returns.index.equals(data.calendar)
    assert list(data.returns.columns) == sorted(data.rows["symbol"].unique())  # no benchmark or sector ETF
    close = _closes(tmp_path / "prices_TSX.parquet", data.calendar)
    for s in stocks:
        expected = np.log(close[s] / close[s].shift(1))
        pd.testing.assert_series_equal(data.returns[s], expected, check_names=False)


def test_coins_returns_are_daily_log_returns_on_the_coin_calendar(tmp_path):
    write_crypto(tmp_path)
    plain = load_crypto(tmp_path)
    data = load_crypto(tmp_path, with_garch=True)
    assert plain.returns is None
    pd.testing.assert_frame_equal(plain.rows, data.rows)
    assert data.returns.index.equals(data.calendar)
    assert list(data.returns.columns) == sorted(data.rows["symbol"].unique())
    close = _closes(tmp_path / "prices_crypto.parquet", data.calendar)
    for s in data.returns.columns:
        pd.testing.assert_series_equal(data.returns[s], np.log(close[s] / close[s].shift(1)), check_names=False)
