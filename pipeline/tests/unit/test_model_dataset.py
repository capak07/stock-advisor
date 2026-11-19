import json

import numpy as np
import pandas as pd
import pytest

from advisor.markets import MARKETS
from advisor.model.dataset import SAMPLE_EVERY, WARMUP, load_market
from advisor.model.features import EXTRA_FEATURES, HORIZONS, PRICE_FEATURES, RS_FEATURES
from advisor.model.fundamentals import FUNDAMENTAL_FEATURES
from advisor.model.groups import ALL_GROUP_FEATURES
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


def test_shares_after_a_split_are_not_scaled_by_it_again(tmp_path):
    """The split factor is read on the daily calendar, not on the sampled days (every tenth session)."""
    stocks = write_market(tmp_path, Market.US, stocks=2, days=400)
    calendar = pd.bdate_range("2017-01-02", periods=400)
    split_day, cover, filed, sample = calendar[305], calendar[306], calendar[308], calendar[312]
    assert sample in calendar[WARMUP::SAMPLE_EVERY] and calendar[302] in calendar[WARMUP::SAMPLE_EVERY]
    pd.DataFrame({"symbol": [stocks[0]], "day": [split_day.date()], "dividend": [0.0], "split": [4.0]}
                 ).to_parquet(tmp_path / "events_US.parquet", index=False)
    pd.DataFrame([{"cik": 1, "metric": "shares_outstanding", "concept": "dei:EntityCommonStockSharesOutstanding",
                   "unit": "shares", "start": None, "end": cover.date().isoformat(), "value": 400.0,
                   "filed": filed.date().isoformat(), "form": "10-Q", "accession": "a"}]
                 ).to_parquet(tmp_path / "fundamentals.parquet", index=False)
    pd.DataFrame({"symbol": [stocks[0]], "cik": pd.Series([1], dtype="int32")}).to_parquet(
        tmp_path / "tickers.parquet", index=False)
    prices = pd.read_parquet(tmp_path / "prices_US.parquet")
    close = prices[(prices["symbol"] == stocks[0]) & (pd.to_datetime(prices["day"]) == sample)]["close"].iloc[0]
    data = load_market(tmp_path, Market.US)
    row = data.rows[(data.rows["day"] == sample) & (data.rows["symbol"] == stocks[0])].iloc[0]
    assert row["log_mcap"] == pytest.approx(np.log(close * 400.0))


def test_a_failed_build_is_never_trained_on(tmp_path):
    write_market(tmp_path, Market.TSX, stocks=1, days=400)
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    manifest["failed"] = {"step": "macro", "error": "macro step failed: FRED did not answer"}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="the training data build failed: macro step failed"):
        load_market(tmp_path, Market.TSX)


def test_training_rows_carry_the_extras_but_the_baseline_names_do_not_change(tmp_path):
    write_market(tmp_path, Market.TSX, stocks=3, days=400)
    data = load_market(tmp_path, Market.TSX)
    assert data.extras == (*EXTRA_FEATURES, *ALL_GROUP_FEATURES)
    assert set(EXTRA_FEATURES) <= set(data.rows.columns)
    assert data.features == PRICE_FEATURES + RS_FEATURES
    assert data.rows["amihud_20"].notna().all()


def test_us_rows_carry_every_group_column_and_tsx_reads_them_missing(tmp_path):
    write_market(tmp_path / "us", Market.US, stocks=2, days=400)
    write_market(tmp_path / "tsx", Market.TSX, stocks=2, days=400)
    us, tsx = load_market(tmp_path / "us", Market.US), load_market(tmp_path / "tsx", Market.TSX)
    for data in (us, tsx):
        assert set(ALL_GROUP_FEATURES) <= set(data.rows.columns)
        assert not set(ALL_GROUP_FEATURES) & set(data.features)  # only configs that name them train on them
    assert tsx.rows[ALL_GROUP_FEATURES].isna().all().all()
    assert tsx.groups == frozenset()
    assert us.rows[ALL_GROUP_FEATURES].isna().all().all()  # no history files: missing, never zero
    assert us.groups == {"earnings"}


def test_load_market_records_which_groups_were_built(tmp_path):
    write_market(tmp_path, Market.US, stocks=2, days=400)
    pd.DataFrame({"symbol": ["QAA"], "settlement": pd.to_datetime(["2017-12-01"]), "short_interest": [1000.0],
                  "days_to_cover": [2.0]}).to_parquet(tmp_path / "short_interest.parquet", index=False)
    pd.DataFrame({"symbol": ["QAA"], "day": pd.to_datetime(["2017-03-15"]), "short_volume": [10.0],
                  "total_volume": [100.0]}).to_parquet(tmp_path / "short_volume.parquet", index=False)
    data = load_market(tmp_path, Market.US)
    assert data.groups == {"short", "earnings"}
    assert data.rows["days_to_cover"].notna().any()  # the report is read once its 12th session has passed
    assert data.rows["insider_net_buy_90d"].isna().all()  # a group not built stays missing
    (tmp_path / "short_volume.parquet").unlink()  # half a group is not a group
    assert load_market(tmp_path, Market.US).groups == {"earnings"}
