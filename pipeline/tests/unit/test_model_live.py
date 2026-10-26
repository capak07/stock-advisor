import pandas as pd
import pytest

from advisor.model.dataset import WARMUP, load_market
from advisor.model.live import VOLUME_FEATURES, bars_frame, live_features
from advisor.models import DailyBar, Market
from model_data import write_market


def live_inputs(tmp_path, market):
    prices = pd.read_parquet(tmp_path / f"prices_{market}.parquet")
    sectors = pd.read_parquet(tmp_path / "sectors.parquet")
    return prices, sectors


def test_live_features_match_the_training_rows_on_the_same_day(tmp_path):
    write_market(tmp_path, Market.TSX, stocks=5, days=700)
    data = load_market(tmp_path, Market.TSX)
    day = data.calendar[WARMUP + 300]  # a sample day well inside the history
    prices, sectors = live_inputs(tmp_path, Market.TSX)
    window = prices[pd.to_datetime(prices["day"]) >= day - pd.Timedelta(days=400)]
    live = live_features(window, Market.TSX, day, sectors=sectors, partial_day=False)
    training = data.rows[data.rows["day"] == day].set_index("symbol")
    assert set(training.index) == set(live.index[live["eligible"]])
    pd.testing.assert_frame_equal(
        live.loc[training.index, data.features], training[data.features], check_exact=False, rtol=1e-6, atol=1e-9,
    )


def test_a_partial_day_takes_volume_features_from_the_last_complete_session(tmp_path):
    write_market(tmp_path, Market.TSX, stocks=2, days=500)
    prices, sectors = live_inputs(tmp_path, Market.TSX)
    days = sorted(pd.to_datetime(prices["day"]).unique())
    today, yesterday = pd.Timestamp(days[-1]), pd.Timestamp(days[-2])
    thin = prices.copy()
    thin.loc[pd.to_datetime(thin["day"]) == today, "volume"] = 1_000.0  # 3:15 PM: most of the day's volume missing
    partial = live_features(thin, Market.TSX, today, sectors=sectors, partial_day=True)
    complete = live_features(prices, Market.TSX, yesterday, sectors=sectors, partial_day=False)
    for name in VOLUME_FEATURES:
        assert partial[name].tolist() == pytest.approx(complete[name].tolist(), nan_ok=True)
    assert partial["eligible"].tolist() == complete["eligible"].tolist()
    full_today = live_features(prices, Market.TSX, today, sectors=sectors, partial_day=False)
    assert partial["ret_5"].tolist() == pytest.approx(full_today["ret_5"].tolist())  # prices use today's bar


def test_bars_become_the_training_layout():
    bars = {"X": [DailyBar(symbol="X", day=pd.Timestamp("2026-10-23").date(), open=1, high=2, low=0.5, close=1.5,
                           volume=10, source="yfinance")]}
    frame = bars_frame(bars)
    assert list(frame.columns) == ["symbol", "day", "open", "high", "low", "close", "volume"]
    assert frame.iloc[0]["close"] == 1.5


def test_a_sector_etf_yahoo_missed_leaves_its_features_missing(tmp_path):
    write_market(tmp_path, Market.TSX, stocks=2, days=400)
    prices, sectors = live_inputs(tmp_path, Market.TSX)
    gone = sectors["sector"].map({"Energy": "XEG.TO", "Financial Services": "XFN.TO"}).dropna().iloc[0]
    live = live_features(prices[prices["symbol"] != gone], Market.TSX, pd.Timestamp(prices["day"].max()),
                         sectors=sectors, partial_day=False)
    assert live["ret_5"].notna().all()  # everything else is still there
    assert live.loc[sectors.loc[sectors["sector"].map({"Energy": "XEG.TO", "Financial Services": "XFN.TO"}) == gone,
                                "symbol"], "ex_sector_21"].isna().all()
