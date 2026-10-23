import numpy as np
import pandas as pd
import pytest

from advisor.model.fundamentals import first_reported, fundamental_features, ttm

REV = "us-gaap:Revenues"
REV2 = "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"


def fact(metric, start, end, value, filed, concept=REV, cik=1):
    return {"cik": cik, "metric": metric, "concept": concept, "unit": "USD", "start": start, "end": end,
            "value": value, "filed": filed, "form": "10-Q", "accession": "a"}


def frame(*rows) -> pd.DataFrame:
    return pd.DataFrame(list(rows))


REVENUE = frame(
    fact("revenue", "2022-01-01", "2022-09-30", 260.0, "2022-11-01"),
    fact("revenue", "2022-01-01", "2022-12-31", 360.0, "2023-02-10"),
    fact("revenue", "2023-01-01", "2023-09-30", 290.0, "2023-11-01"),
    fact("revenue", "2023-01-01", "2023-12-31", 400.0, "2024-02-10"),
    fact("revenue", "2024-01-01", "2024-09-30", 320.0, "2024-11-01"),
)


def test_each_period_keeps_its_first_reported_value_of_the_best_concept():
    facts = frame(
        fact("revenue", "2023-01-01", "2023-12-31", 100.0, "2024-02-01"),
        fact("revenue", "2023-01-01", "2023-12-31", 90.0, "2025-02-01"),  # restated a year later
        fact("revenue", "2023-01-01", "2023-12-31", 95.0, "2024-01-15", concept=REV2),  # a lower-priority concept
    )
    kept = first_reported(facts)
    assert kept[["value", "filed"]].values.tolist() == [[100.0, pd.Timestamp("2024-02-01")]]


def test_ttm_comes_from_year_to_date_facts():
    t = ttm(first_reported(REVENUE)).sort_values("period")
    got = [(str(r.period), r.ttm, r.known.date().isoformat(), None if np.isnan(r.ttm_1y) else r.ttm_1y)
           for r in t.itertuples()]
    assert got == [
        ("2022-12", 360.0, "2023-02-10", None),
        ("2023-09", 390.0, "2023-11-01", None),  # 290 + 360 - 260; no 2022-09 TTM
        ("2023-12", 400.0, "2024-02-10", 360.0),
        ("2024-09", 430.0, "2024-11-01", 390.0),  # 320 + 400 - 290
    ]


def test_a_filing_counts_from_the_next_day():
    days = pd.DatetimeIndex(["2024-11-01", "2024-11-04"], name="day")
    close = pd.DataFrame({"X": [10.0, 10.0]}, index=days)
    splits = close * 0 + 1.0
    f = fundamental_features(REVENUE, pd.DataFrame({"symbol": ["X"], "cik": [1]}), days, close, splits)
    assert f["rev_growth"]["X"].round(4).tolist() == [round(400 / 360 - 1, 4), round(430 / 390 - 1, 4)]


def test_a_split_after_the_filing_keeps_market_cap():
    days = pd.DatetimeIndex(["2024-08-15", "2024-09-03"], name="day")
    facts = frame(fact("shares_outstanding", None, "2024-06-30", 100.0, "2024-07-31",
                       concept="dei:EntityCommonStockSharesOutstanding"))
    close = pd.DataFrame({"X": [50.0, 50.0]}, index=days)  # in today's shares: traded at 200, then 50 after 4:1
    # splits after each day: 4 until the split on 2024-08-31, then none; the shares' period end reads 4
    splits = pd.DataFrame({"X": [4.0, 4.0, 1.0]}, index=pd.DatetimeIndex(["2024-06-28", "2024-08-15", "2024-09-03"]))
    f = fundamental_features(facts, pd.DataFrame({"symbol": ["X"], "cik": [1]}), days, close, splits)
    assert f["log_mcap"]["X"].tolist() == pytest.approx([np.log(20_000.0)] * 2)


def test_missing_figures_stay_missing():
    days = pd.DatetimeIndex(["2024-12-02"], name="day")
    close = pd.DataFrame({"X": [10.0]}, index=days)
    f = fundamental_features(REVENUE, pd.DataFrame({"symbol": ["X"], "cik": [1]}), days, close, close * 0 + 1.0)
    assert np.isnan(f["gross_margin"]["X"].iloc[0])  # no gross profit filed (a bank, say)
    assert np.isnan(f["earnings_yield"]["X"].iloc[0])  # no shares, so no market cap


def test_eps_growth_is_on_todays_shares_and_debt_uses_the_fallback_pieces():
    days = pd.DatetimeIndex(["2024-03-01"], name="day")
    close = pd.DataFrame({"X": [10.0]}, index=days)
    eps = "us-gaap:EarningsPerShareDiluted"
    facts = frame(
        fact("eps_diluted", "2022-01-01", "2022-12-31", 4.0, "2023-02-01", concept=eps),  # before a 2:1 split
        fact("eps_diluted", "2023-01-01", "2023-12-31", 3.0, "2024-02-01", concept=eps),
        fact("equity", None, "2023-12-31", 100.0, "2024-02-01", concept="us-gaap:StockholdersEquity"),
        fact("long_term_debt_noncurrent", None, "2023-12-31", 30.0, "2024-02-01", concept="us-gaap:LongTermDebtNoncurrent"),
        fact("debt_current", None, "2023-12-31", 10.0, "2024-02-01", concept="us-gaap:LongTermDebtCurrent"),
        fact("commercial_paper", None, "2023-12-31", 10.0, "2024-02-01", concept="us-gaap:CommercialPaper"),
    )
    splits = pd.DataFrame({"X": [2.0, 2.0, 1.0]}, index=pd.DatetimeIndex(["2022-12-31", "2023-06-01", "2023-07-01"]))
    f = fundamental_features(facts, pd.DataFrame({"symbol": ["X"], "cik": [1]}), days, close, splits)
    assert f["eps_growth"]["X"].iloc[0] == pytest.approx((3.0 - 2.0) / 2.0)  # 4.0 became 2.0 per today's share
    assert f["debt_to_equity"]["X"].iloc[0] == pytest.approx(0.5)


def one_stock(facts, day):
    days = pd.DatetimeIndex([day], name="day")
    close = pd.DataFrame({"X": [10.0]}, index=days)
    return fundamental_features(facts, pd.DataFrame({"symbol": ["X"], "cik": [1]}), days, close, close * 0 + 1.0)


def test_periods_first_reported_on_one_date_read_the_newest():
    facts = frame(  # a first filing with comparative years, newest listed first
        fact("revenue", "2023-01-01", "2023-12-31", 180.0, "2024-03-01"),
        fact("revenue", "2022-01-01", "2022-12-31", 120.0, "2024-03-01"),
        fact("revenue", "2021-01-01", "2021-12-31", 100.0, "2024-03-01"),
    )
    assert one_stock(facts, "2024-03-04")["rev_growth"]["X"].iloc[0] == pytest.approx(0.5)


def test_margins_need_matching_periods():
    facts = frame(
        fact("gross_profit", "2015-01-01", "2015-12-31", 40.0, "2016-02-01", concept="us-gaap:GrossProfit"),
        fact("revenue", "2023-01-01", "2023-12-31", 400.0, "2024-02-01"),
    )
    assert np.isnan(one_stock(facts, "2024-03-01")["gross_margin"]["X"].iloc[0])


def test_a_stale_figure_stops_carrying_forward():
    facts = frame(
        fact("revenue", "2021-01-01", "2021-12-31", 300.0, "2022-02-01"),
        fact("revenue", "2022-01-01", "2022-12-31", 360.0, "2023-02-01"),
    )
    assert one_stock(facts, "2023-06-01")["rev_growth"]["X"].iloc[0] == pytest.approx(0.2)
    assert np.isnan(one_stock(facts, "2024-08-01")["rev_growth"]["X"].iloc[0])  # ended 2022-12, over 18 months
