import numpy as np
import pandas as pd
import pytest

from advisor.model.earnings import (
    EARNINGS_FEATURES,
    earnings_features,
    eps_quarters,
    single_quarters,
)
from advisor.model.fundamentals import first_reported

CONCEPT = {"revenue": "us-gaap:Revenues", "operating_income": "us-gaap:OperatingIncomeLoss",
           "eps_diluted": "us-gaap:EarningsPerShareDiluted"}
TICKERS = pd.DataFrame({"symbol": ["X"], "cik": [1]})


def fact(metric, start, end, value, filed, cik=1):
    return {"cik": cik, "metric": metric, "concept": CONCEPT[metric], "unit": "USD", "start": start, "end": end,
            "value": value, "filed": filed, "form": "10-Q", "accession": "a"}


def earnings_quarters_eps(facts, splits):
    q = eps_quarters(first_reported(facts), TICKERS, splits)
    return q[q["end"] == pd.Timestamp("2022-12-31")]


def frame(*rows) -> pd.DataFrame:
    return pd.DataFrame(list(rows))


NO_SPLITS = pd.DataFrame({"X": [1.0]}, index=pd.DatetimeIndex(["2010-01-01"]))


def feats(facts, *days, splits=NO_SPLITS):
    return earnings_features(facts, TICKERS, pd.DatetimeIndex(list(days), name="day"), ["X"], splits)


def at(f, name, i=0):
    return f[name]["X"].iloc[i]


# a September fiscal year (Apple-like): Q1 ends late December, the fiscal year late September
SEPT = frame(
    fact("revenue", "2022-09-25", "2022-12-31", 100.0, "2023-02-01"),
    fact("operating_income", "2022-09-25", "2022-12-31", 20.0, "2023-02-01"),
    fact("revenue", "2023-10-01", "2023-12-30", 120.0, "2024-02-02"),
    fact("operating_income", "2023-10-01", "2023-12-30", 30.0, "2024-02-02"),
)


def test_quarter_from_a_three_month_fact():
    q = single_quarters(first_reported(SEPT))
    rev = q[q["metric"] == "revenue"].sort_values("end")
    assert list(q.columns) == ["cik", "metric", "end", "value", "known"]
    assert rev["value"].tolist() == [100.0, 120.0]
    assert rev["known"].tolist() == [pd.Timestamp("2023-02-01"), pd.Timestamp("2024-02-02")]


def test_fourth_quarter_is_the_fiscal_year_minus_nine_months():
    facts = frame(
        fact("revenue", "2022-09-25", "2023-06-24", 300.0, "2023-08-01"),
        fact("revenue", "2022-09-25", "2023-09-30", 420.0, "2023-11-03"),
    )
    q = single_quarters(first_reported(facts))
    q4 = q[q["end"] == pd.Timestamp("2023-09-30")]
    assert q4["value"].tolist() == [120.0]
    assert q4["known"].tolist() == [pd.Timestamp("2023-11-03")]


def test_september_year_matches_the_year_ago_quarter_by_end_date():
    f = feats(SEPT, "2024-03-01")
    assert at(f, "rev_growth_q") == pytest.approx(0.2)
    assert at(f, "op_margin_q_chg") == pytest.approx(25.0 - 20.0)


def test_filing_day_does_not_see_it_the_next_day_does():
    f = feats(SEPT, "2024-02-02", "2024-02-03")
    assert np.isnan(at(f, "rev_growth_q", 0))  # only the 2022 quarter, no year-ago
    assert at(f, "rev_growth_q", 1) == pytest.approx(0.2)


def test_days_since_report_counts_from_known_and_caps():
    f = feats(SEPT, "2024-02-12", "2024-08-01")
    assert at(f, "days_since_report", 0) == 10
    assert at(f, "days_since_report", 1) == 120


def test_restated_value_is_ignored():
    facts = pd.concat([SEPT, frame(fact("revenue", "2023-10-01", "2023-12-30", 999.0, "2024-05-01"))])
    assert at(feats(facts, "2024-06-01"), "rev_growth_q") == pytest.approx(0.2)


def test_stale_after_548_days():
    f = feats(SEPT, "2025-06-29", "2025-07-01")  # 2023-12-30 + 548 = 2025-06-30
    assert at(f, "rev_growth_q", 0) == pytest.approx(0.2)
    assert np.isnan(at(f, "rev_growth_q", 1))
    assert np.isnan(at(f, "days_since_report", 1))


def eps_history(values):
    rows = []
    for i, v in enumerate(values):
        y = 2014 + i
        rows.append(fact("eps_diluted", f"{y}-01-01", f"{y}-03-31", v, f"{y}-05-01"))
    return frame(*rows)


def test_sue_with_eight_prior_changes():
    eps = [1.0, 1.1, 1.3, 1.2, 1.6, 1.5, 1.9, 2.0, 2.4, 2.9]
    changes = np.diff(eps)
    expected = changes[-1] / np.std(changes[:-1][-8:], ddof=1)
    f = feats(eps_history(eps), "2023-06-01")
    assert at(f, "sue") == pytest.approx(min(expected, 5.0))
    assert expected < 5.0


def test_sue_needs_four_prior_changes_others_still_computed():
    facts = pd.concat([eps_history([1.0, 1.1, 1.3, 1.2, 1.6]),
                       frame(fact("revenue", "2017-01-01", "2017-03-31", 10.0, "2017-05-01"),
                             fact("revenue", "2018-01-01", "2018-03-31", 11.0, "2018-05-01"))])
    f = feats(facts, "2018-06-01")  # 4 changes, so 3 prior to the latest
    assert np.isnan(at(f, "sue"))
    assert at(f, "rev_growth_q") == pytest.approx(0.1)
    assert at(eps_feats := feats(eps_history([1.0, 1.1, 1.3, 1.2, 1.6, 1.5]), "2019-06-01"), "sue") == \
        pytest.approx(-0.1 / np.std(np.diff([1.0, 1.1, 1.3, 1.2, 1.6]), ddof=1))
    assert set(eps_feats) == set(EARNINGS_FEATURES)


def test_sue_clipped():
    f = feats(eps_history([1.0, 1.1, 1.2, 1.31, 1.4, 9.0]), "2019-06-01")
    assert at(f, "sue") == 5.0


def test_unknown_symbols_read_nan():
    f = earnings_features(SEPT, TICKERS, pd.DatetimeIndex(["2024-03-01"]), ["X", "TSX.TO"], NO_SPLITS)
    assert list(f["sue"].columns) == ["X", "TSX.TO"]
    assert np.isnan(f["rev_growth_q"]["TSX.TO"].iloc[0])
    g = earnings_features(SEPT, TICKERS, pd.DatetimeIndex(["2024-03-01"]), ["BTC-USD"], NO_SPLITS)
    assert np.isnan(g["rev_growth_q"]["BTC-USD"].iloc[0])


def test_a_split_between_quarters_leaves_sue_unchanged():
    eps = [1.0, 1.1, 1.3, 1.2, 1.6, 1.5, 1.9, 2.0, 2.4, 2.9]
    plain = at(feats(eps_history(eps), "2023-06-01"), "sue")
    # 2-for-1 on 2023-01-15: the 2023 quarter is reported on the new share basis
    reported = eps[:-1] + [eps[-1] / 2]
    splits = pd.DataFrame({"X": [2.0, 1.0]}, index=pd.DatetimeIndex(["2010-01-01", "2023-01-15"]))
    assert at(feats(eps_history(reported), "2023-06-01", splits=splits), "sue") == pytest.approx(plain)


def test_a_split_between_nine_months_and_fiscal_year_drops_that_q4_eps():
    # fiscal years end in December; Q4 2022 = FY 2022 - 9M 2022, with a 2-for-1 split between the two filings
    rows = [fact(m, f"{y}-01-01", f"{y}-12-31", v, f"{y + 1}-02-10")
            for y in (2021, 2022) for m, v in (("revenue", 400.0 + 40 * (y - 2021)), ("eps_diluted", 4.0))]
    rows += [fact(m, f"{y}-01-01", f"{y}-09-30", v, f"{y}-11-01")
             for y in (2021, 2022) for m, v in (("revenue", 300.0), ("eps_diluted", 3.0))]
    splits = pd.DataFrame({"X": [2.0, 1.0]}, index=pd.DatetimeIndex(["2010-01-01", "2022-12-01"]))
    f = feats(frame(*rows), "2023-03-01", splits=splits)
    assert at(f, "rev_growth_q") == pytest.approx(140 / 100 - 1)  # revenue Q4 still used
    assert np.isnan(at(f, "sue"))
    # without the split the same Q4 EPS is kept (one change only, so sue is NaN anyway): check the quarter table
    from_split = earnings_quarters_eps(frame(*rows), splits)
    assert from_split.empty
    assert len(earnings_quarters_eps(frame(*rows), NO_SPLITS)) == 1
