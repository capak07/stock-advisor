import pandas as pd
import pytest

from advisor.markets import MARKETS
from advisor.model.dataset import SAMPLE_EVERY, WARMUP, load_market
from advisor.model.features import HORIZONS, PRICE_FEATURES, RS_FEATURES
from advisor.model.fundamentals import FUNDAMENTAL_FEATURES
from advisor.models import Market
from model_data import write_market


def test_a_market_becomes_one_row_per_eligible_stock_and_sample_day(tmp_path):
    stocks = write_market(tmp_path, Market.TSX, stocks=3, days=400, penny=True)
    data = load_market(tmp_path, Market.TSX)
    assert data.features == PRICE_FEATURES + RS_FEATURES
    assert sorted(data.rows["symbol"].unique()) == sorted(stocks)  # no benchmark, ETF or penny stock
    assert len(data.calendar) == 399  # the build day's partial bar is left out
    assert pd.DatetimeIndex(sorted(data.rows["day"].unique())).equals(data.calendar[WARMUP::SAMPLE_EVERY])
    assert {f"y_{h}" for h in HORIZONS} <= set(data.rows.columns)
    assert data.rows["sector"].notna().all() and (data.rows["dollar_volume_20"] > 1e6).all()


def test_the_target_is_read_from_the_closes(tmp_path):
    stocks = write_market(tmp_path, Market.TSX, stocks=1, days=400)
    data = load_market(tmp_path, Market.TSX)
    prices = pd.read_parquet(tmp_path / "prices_TSX.parquet")
    close = prices.pivot(index="day", columns="symbol", values="close")
    day = data.calendar[WARMUP]
    i = list(close.index).index(day.date())
    row = data.rows[(data.rows["day"] == day)].iloc[0]
    bench = MARKETS[Market.TSX].benchmark
    expected = close[stocks[0]].iloc[i + 5] / close[stocks[0]].iloc[i] - close[bench].iloc[i + 5] / close[bench].iloc[i]
    assert row["y_5"] == pytest.approx(expected)


def test_us_rows_carry_fundamentals(tmp_path):
    write_market(tmp_path, Market.US, stocks=2, days=400)
    data = load_market(tmp_path, Market.US)
    assert data.features == PRICE_FEATURES + RS_FEATURES + FUNDAMENTAL_FEATURES
    assert data.rows["log_mcap"].isna().all()  # this data has no filings: missing, never zero
