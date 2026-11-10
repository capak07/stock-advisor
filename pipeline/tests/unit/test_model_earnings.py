import numpy as np
import pandas as pd
import pytest

from advisor.model.earnings import EARNINGS_FEATURES, earnings_features, single_quarters
from advisor.model.fundamentals import first_reported

CONCEPT = {"revenue": "us-gaap:Revenues", "operating_income": "us-gaap:OperatingIncomeLoss",
           "eps_diluted": "us-gaap:EarningsPerShareDiluted"}
TICKERS = pd.DataFrame({"symbol": ["X"], "cik": [1]})


def fact(metric, start, end, value, filed, cik=1):
    return {"cik": cik, "metric": metric, "concept": CONCEPT[metric], "unit": "USD", "start": start, "end": end,
            "value": value, "filed": filed, "form": "10-Q", "accession": "a"}


def frame(*rows) -> pd.DataFrame:
    return pd.DataFrame(list(rows))


def feats(facts, *days):
    return earnings_features(facts, TICKERS, pd.DatetimeIndex(list(days), name="day"), ["X"])


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
    f = earnings_features(SEPT, TICKERS, pd.DatetimeIndex(["2024-03-01"]), ["X", "TSX.TO"])
    assert list(f["sue"].columns) == ["X", "TSX.TO"]
    assert np.isnan(f["rev_growth_q"]["TSX.TO"].iloc[0])
    g = earnings_features(SEPT, TICKERS, pd.DatetimeIndex(["2024-03-01"]), ["BTC-USD"])
    assert np.isnan(g["rev_growth_q"]["BTC-USD"].iloc[0])
