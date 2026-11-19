from datetime import UTC, date, datetime

import numpy as np
import pandas as pd
import pytest

from advisor.collectors.base import CollectorResult, CollectorStatus
from advisor.collectors.sec_insiders import InsiderTrade
from advisor.collectors.sec_xbrl import FinancialFact
from advisor.collectors.yfinance_analyst import AnalystView, RatingEvent
from advisor.model.analyst import ANALYST_FEATURES
from advisor.model.dataset import WARMUP, load_market
from advisor.model.groups import ALL_GROUP_FEATURES, load_history
from advisor.model.insider import INSIDER_FEATURES
from advisor.model.live import (
    LIVE_WINDOW,
    VOLUME_FEATURES,
    bars_frame,
    facts_frame,
    live_features,
    split_events,
)
from advisor.model.live_groups import history_from_records
from advisor.models import DailyBar, Market
from model_data import write_group_histories, write_market


def live_inputs(tmp_path, market):
    prices = pd.read_parquet(tmp_path / f"prices_{market}.parquet")
    sectors = pd.read_parquet(tmp_path / "sectors.parquet")
    return prices, sectors


def test_live_features_match_the_training_rows_on_the_same_day(tmp_path):
    write_market(tmp_path, Market.TSX, stocks=5, days=700)
    data = load_market(tmp_path, Market.TSX)
    day = data.calendar[WARMUP + 300]  # a sample day well inside the history
    prices, sectors = live_inputs(tmp_path, Market.TSX)
    window = prices[pd.to_datetime(prices["day"]) >= day - LIVE_WINDOW]
    live = live_features(window, Market.TSX, day, sectors=sectors, partial_day=False)
    training = data.rows[data.rows["day"] == day].set_index("symbol")
    assert set(training.index) == set(live.index[live["eligible"]])
    names = list(data.features) + list(data.extras)
    pd.testing.assert_frame_equal(
        live.loc[training.index, names], training[names], check_exact=False, rtol=1e-6, atol=1e-9,
    )


def test_us_live_features_match_the_training_rows_with_earnings(tmp_path):
    from advisor.model.earnings import EARNINGS_FEATURES

    stocks = write_market(tmp_path, Market.US, stocks=3, days=700)
    rows = []
    for i, end in enumerate(pd.date_range("2016-03-31", periods=12, freq="QE")):
        start, filed = (end - pd.Timedelta(days=89)).date(), (end + pd.Timedelta(days=30)).date()
        for metric, concept, value in (
            ("revenue", "us-gaap:Revenues", 100.0 + 5 * i + (i % 3)),
            ("operating_income", "us-gaap:OperatingIncomeLoss", 10.0 + i),
            ("eps_diluted", "us-gaap:EarningsPerShareDiluted", 1.0 + 0.1 * i + 0.05 * (i % 2)),
        ):
            rows.append({"cik": 1, "metric": metric, "concept": concept, "unit": "USD", "start": start,
                         "end": end.date(), "value": value, "filed": filed, "form": "10-Q", "accession": f"a{i}"})
    pd.DataFrame(rows).to_parquet(tmp_path / "fundamentals.parquet", index=False)
    tickers = pd.DataFrame({"symbol": [stocks[0]], "cik": pd.Series([1], dtype="int32")})
    tickers.to_parquet(tmp_path / "tickers.parquet", index=False)
    data = load_market(tmp_path, Market.US)
    day = data.calendar[WARMUP + 300]
    prices, sectors = live_inputs(tmp_path, Market.US)
    window = prices[pd.to_datetime(prices["day"]) >= day - LIVE_WINDOW]
    live = live_features(window, Market.US, day, sectors=sectors, partial_day=False,
                         facts=pd.read_parquet(tmp_path / "fundamentals.parquet"), tickers=tickers)
    training = data.rows[data.rows["day"] == day].set_index("symbol")
    assert training.loc[stocks[0], EARNINGS_FEATURES].notna().all()  # the comparison reads real values
    names = list(data.features) + list(data.extras)
    pd.testing.assert_frame_equal(
        live.loc[training.index, names], training[names], check_exact=False, rtol=1e-6, atol=1e-9,
    )


def _group_fixture(tmp_path):
    """The parity fixture: three US stocks, every group's history for the first, and its sample day."""
    stocks = write_market(tmp_path, Market.US, stocks=3, days=700)
    write_group_histories(tmp_path, stocks)  # new helper in tests/model_data.py: one small file per source
    data = load_market(tmp_path, Market.US)
    day = data.calendar[WARMUP + 300]
    prices, sectors = live_inputs(tmp_path, Market.US)
    window = prices[pd.to_datetime(prices["day"]) >= day - LIVE_WINDOW]
    return stocks, data, day, window, sectors


def _us_live(tmp_path, window, day, sectors, history):
    return live_features(window, Market.US, day, sectors=sectors, partial_day=False,
                         facts=pd.read_parquet(tmp_path / "fundamentals.parquet"),
                         tickers=pd.read_parquet(tmp_path / "tickers.parquet"), history=history)


def test_us_live_features_match_the_training_rows_with_every_group(tmp_path):
    stocks, data, day, window, sectors = _group_fixture(tmp_path)
    live = _us_live(tmp_path, window, day, sectors, load_history(tmp_path))
    training = data.rows[data.rows["day"] == day].set_index("symbol")
    assert training.loc[stocks[0], ALL_GROUP_FEATURES].notna().all()  # the comparison reads real values
    pd.testing.assert_frame_equal(live.loc[training.index, ALL_GROUP_FEATURES], training[ALL_GROUP_FEATURES],
                                  check_exact=False, rtol=1e-6, atol=1e-9)
    names = list(data.features) + list(data.extras)  # and nothing else moved
    pd.testing.assert_frame_equal(live.loc[training.index, names], training[names],
                                  check_exact=False, rtol=1e-6, atol=1e-9)


def _form4(symbol: str, filed: date) -> InsiderTrade:
    return InsiderTrade(
        symbol=symbol, accession="0000000000-19-000001", form="4", filing_date=filed,
        accepted_at=datetime(filed.year, filed.month, filed.day, 21, tzinfo=UTC), trade_date=filed,
        owners=["DOE JANE"], director=False, officer=True, ten_percent_owner=False, code="P", acquired=True,
        shares=1_000.0, price=10.0, direct=True, derivative=False, planned=False,
    )


def test_a_source_that_was_not_ok_reads_missing_in_the_features(tmp_path):
    """Review Focus 1 (Ruling R3, F16): a source that did not run cleanly gives NaN, never 0, even for a
    covered symbol whose OK source would read 0."""
    stocks, _, day, window, sectors = _group_fixture(tmp_path)
    trade = _form4(stocks[0], (day - pd.Timedelta(days=10)).date())
    view = AnalystView(symbol=stocks[0], as_of=day.date(), oldest_event=datetime(2018, 1, 2, 15), event_count=1,
                       events=[RatingEvent(graded_at=datetime(2018, 1, 2, 15), action="up")])

    def run(name, status, records):
        result = CollectorResult(name, status, records, 0, None if status is CollectorStatus.OK else "x")
        return _us_live(tmp_path, window, day, sectors, history_from_records({name: result})).loc[stocks[0]]

    partial = run("sec_form4", CollectorStatus.PARTIAL, [trade])
    assert partial[INSIDER_FEATURES].isna().all()
    assert run("sec_form4", CollectorStatus.OK, [])[INSIDER_FEATURES].tolist() == [0.0, 0.0, 0.0]  # covered
    assert run("sec_form4", CollectorStatus.OK, [trade])["insider_buyers_90d"] == 1.0
    failed = run("yfinance_analyst", CollectorStatus.FAILED, [])
    assert failed[ANALYST_FEATURES].isna().all()
    assert run("yfinance_analyst", CollectorStatus.OK, [view])[ANALYST_FEATURES[:3]].tolist() == [0.0, 0.0, 0.0]


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
    assert partial["dollar_volume_20"].tolist() == pytest.approx(complete["dollar_volume_20"].tolist())
    full_today = live_features(prices, Market.TSX, today, sectors=sectors, partial_day=False)
    assert partial["ret_5"].tolist() == pytest.approx(full_today["ret_5"].tolist())  # prices use today's bar


@pytest.mark.parametrize("partial_day", [False, True])
def test_a_stock_without_a_bar_on_the_day_is_not_eligible(tmp_path, partial_day):
    symbols = write_market(tmp_path, Market.TSX, stocks=2, days=500)
    prices, sectors = live_inputs(tmp_path, Market.TSX)
    today = pd.Timestamp(prices["day"].max())
    stale, traded = symbols
    gap = prices[~((prices["symbol"] == stale) & (pd.to_datetime(prices["day"]) == today))]
    live = live_features(gap, Market.TSX, today, sectors=sectors, partial_day=partial_day)
    full = live_features(prices, Market.TSX, today, sectors=sectors, partial_day=partial_day)
    assert full.loc[stale, "eligible"]  # it was eligible until its bar went missing
    assert not live.loc[stale, "eligible"]  # in partial mode yesterday's flag alone would pass it
    assert live.loc[traded, "eligible"] == full.loc[traded, "eligible"]


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


def test_a_day_the_benchmark_has_no_bar_for_is_a_readable_error(tmp_path):
    write_market(tmp_path, Market.TSX, stocks=2, days=400)
    prices, sectors = live_inputs(tmp_path, Market.TSX)
    last = prices["day"].max()
    gap = prices[~((prices["symbol"] == "XIU.TO") & (prices["day"] == last))]
    with pytest.raises(ValueError, match=f"no XIU.TO bar for {pd.Timestamp(last):%Y-%m-%d}"):
        live_features(gap, Market.TSX, pd.Timestamp(last), sectors=sectors, partial_day=True)


def fact(metric, end, value, filed, start=None, concept="us-gaap:Revenues"):
    return FinancialFact(symbol="ZZZ", metric=metric, concept=concept, unit="USD", start=start, end=end,
                         value=value, filed=filed, form="10-Q", accession="a")


def test_the_runs_sec_facts_become_the_training_layout():
    facts, tickers = facts_frame([fact("revenue", date(2025, 12, 31), 400.0, date(2026, 2, 10), start=date(2025, 1, 1))])
    assert list(facts.columns) == ["cik", "metric", "concept", "unit", "start", "end", "value", "filed", "form", "accession"]
    assert tickers.to_dict("records") == [{"symbol": "ZZZ", "cik": facts["cik"].iloc[0]}]


def test_live_split_events_keep_market_cap_after_a_split():
    # 100 shares filed for 2025-06-30; a 4:1 split on 2025-08-01; today the close (in today's shares) is 50
    days = pd.bdate_range("2025-07-01", "2025-09-30", name="day")
    prices = pd.concat([
        pd.DataFrame({"symbol": s, "day": [d.date() for d in days], "open": 50.0, "high": 50.0, "low": 50.0,
                      "close": 50.0, "volume": 1e6}) for s in ("ZZZ", "SPY")
    ])
    facts, tickers = facts_frame([fact("shares_outstanding", date(2025, 6, 30), 100.0, date(2025, 7, 15),
                                       concept="dei:EntityCommonStockSharesOutstanding")])
    events = pd.DataFrame({"symbol": ["ZZZ"], "day": [date(2025, 8, 1)], "dividend": [0.0], "split": [4.0]})
    sectors = pd.DataFrame({"symbol": ["ZZZ"], "sector": [None], "industry": [None]})
    row = live_features(prices, Market.US, days[-1], sectors=sectors, partial_day=False,
                        events=events, facts=facts, tickers=tickers).loc["ZZZ"]
    assert row["log_mcap"] == pytest.approx(np.log(50.0 * 400))


def test_split_events_ask_for_three_years_of_the_symbols():
    asked = []

    def download(tickers, start, end):
        asked.append((tickers, start, end))
        return pd.DataFrame()

    out = split_events(["AAA", "BBB"], date(2026, 10, 26), download=download, sleep=lambda _s: None)
    assert asked[0][0] == ["AAA", "BBB"]
    assert asked[0][1] == date(2026, 10, 26) - pd.Timedelta(days=3 * 365)
    assert list(out.columns) == ["symbol", "day", "dividend", "split"]
    assert out.empty
