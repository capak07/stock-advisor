from datetime import date, timedelta

from advisor.collectors.sec_xbrl import FinancialFact
from advisor.monitor.quarters import single_quarters


def fact(
    metric, start, end, value, filed=None, form="10-Q", accession="a-1", concept="us-gaap:X"
):
    return FinancialFact(
        symbol="AAA",
        metric=metric,
        concept=concept,
        unit="USD",
        start=start,
        end=end,
        value=value,
        filed=filed or end + timedelta(days=30),
        form=form,
        accession=accession,
    )


def test_quarters_from_10q_durations_ignore_year_to_date():
    facts = [
        fact("revenue", date(2024, 4, 1), date(2024, 6, 30), 11),
        fact("revenue", date(2024, 1, 1), date(2024, 6, 30), 21),
    ]
    rows = single_quarters(facts)
    assert [(r.period_end, r.revenue) for r in rows] == [(date(2024, 6, 30), 11)]
    assert rows[0].derived is False


def test_q4_is_annual_minus_three_quarters():
    facts = [
        fact("revenue", date(2023, 10, 1), date(2023, 12, 30), 10),
        fact("revenue", date(2023, 12, 31), date(2024, 3, 30), 11),
        fact("revenue", date(2024, 3, 31), date(2024, 6, 29), 12),
        fact("revenue", date(2023, 10, 1), date(2024, 9, 28), 50, form="10-K", accession="k"),
        fact("eps_diluted", date(2023, 10, 1), date(2023, 12, 30), 1.0),
        fact("eps_diluted", date(2023, 12, 31), date(2024, 3, 30), 1.1),
        fact("eps_diluted", date(2024, 3, 31), date(2024, 6, 29), 1.2),
        fact("eps_diluted", date(2023, 10, 1), date(2024, 9, 28), 5.0, form="10-K", accession="k"),
    ]
    rows = single_quarters(facts)
    q4 = rows[-1]
    assert q4.revenue == 17
    assert abs(q4.eps_diluted - 1.7) < 1e-9
    assert q4.derived is True
    assert q4.fiscal_period == "Q4"
    assert q4.fiscal_year == 2024
    assert q4.period_start == date(2024, 6, 30)
    assert q4.period_end == date(2024, 9, 28)
    assert q4.form == "10-K" and q4.accession == "k"
    assert [r.fiscal_period for r in rows] == ["Q1", "Q2", "Q3", "Q4"]


def test_real_q4_is_used_not_derived():
    facts = [
        fact("revenue", date(2024, 1, 1), date(2024, 3, 31), 10),
        fact("revenue", date(2024, 4, 1), date(2024, 6, 30), 11),
        fact("revenue", date(2024, 7, 1), date(2024, 9, 30), 12),
        fact("revenue", date(2024, 10, 1), date(2024, 12, 31), 13),
        fact("revenue", date(2024, 1, 1), date(2024, 12, 31), 46, form="10-K"),
    ]
    rows = single_quarters(facts)
    assert [r.revenue for r in rows] == [10, 11, 12, 13]
    assert not any(r.derived for r in rows)


def test_q4_derived_only_for_metrics_with_all_inputs():
    facts = [
        fact("revenue", date(2024, 1, 1), date(2024, 3, 31), 10),
        fact("revenue", date(2024, 4, 1), date(2024, 6, 30), 11),
        fact("revenue", date(2024, 7, 1), date(2024, 9, 30), 12),
        fact("revenue", date(2024, 1, 1), date(2024, 12, 31), 50, form="10-K"),
        fact("net_income", date(2024, 1, 1), date(2024, 12, 31), 5, form="10-K"),
    ]
    q4 = single_quarters(facts)[-1]
    assert q4.revenue == 17
    assert q4.net_income is None
    assert q4.derived is True


def test_restated_quarter_keeps_latest_filing():
    s, e = date(2024, 4, 1), date(2024, 6, 30)
    facts = [
        fact("revenue", s, e, 10, filed=date(2024, 8, 1), accession="old"),
        fact("revenue", s, e, 12, filed=date(2025, 8, 1), accession="new"),
    ]
    rows = single_quarters(facts)
    assert len(rows) == 1
    assert rows[0].revenue == 12
    assert rows[0].accession == "new"
    assert rows[0].filed == date(2025, 8, 1)


def test_gross_profit_falls_back_to_revenue_minus_cost():
    s, e = date(2024, 4, 1), date(2024, 6, 30)
    rows = single_quarters([fact("revenue", s, e, 100), fact("cost_of_revenue", s, e, 60)])
    assert rows[0].gross_profit == 40


def test_instant_facts_are_ignored():
    assert single_quarters([fact("revenue", None, date(2024, 6, 30), 5)]) == []


def test_non_december_fiscal_year_labels():
    # fiscal year ends 30 Sep 2024 (FY2024); the next quarter ends 31 Dec 2024 (Q1 of FY2025)
    facts = [
        fact("revenue", date(2023, 10, 1), date(2023, 12, 31), 10),
        fact("revenue", date(2024, 1, 1), date(2024, 3, 31), 11),
        fact("revenue", date(2024, 4, 1), date(2024, 6, 30), 12),
        fact("revenue", date(2023, 10, 1), date(2024, 9, 30), 50, form="10-K"),
        fact("revenue", date(2024, 10, 1), date(2024, 12, 31), 14),
    ]
    got = [(r.period_end, r.fiscal_year, r.fiscal_period) for r in single_quarters(facts)]
    assert got == [
        (date(2023, 12, 31), 2024, "Q1"),
        (date(2024, 3, 31), 2024, "Q2"),
        (date(2024, 6, 30), 2024, "Q3"),
        (date(2024, 9, 30), 2024, "Q4"),
        (date(2024, 12, 31), 2025, "Q1"),
    ]


def test_quarters_before_any_annual_period_have_no_fiscal_label():
    rows = single_quarters([fact("revenue", date(2024, 4, 1), date(2024, 6, 30), 10)])
    assert rows[0].fiscal_year is None and rows[0].fiscal_period is None


def test_keeps_newest_twelve_oldest_first():
    facts = []
    for i in range(16):
        s = date(2020 + i // 4, 1 + 3 * (i % 4), 1)
        e = date(2020 + (i + 1) // 4, 1 + 3 * ((i + 1) % 4), 1) - timedelta(days=1)
        facts.append(fact("revenue", s, e, float(i)))
    rows = single_quarters(facts)
    assert len(rows) == 12
    assert [r.revenue for r in rows] == [float(i) for i in range(4, 16)]
    assert single_quarters(facts, keep=3)[0].revenue == 13.0


def test_missing_first_quarter_does_not_shift_labels():
    facts = [
        fact("revenue", date(2023, 10, 1), date(2024, 9, 30), 50, form="10-K"),
        fact("revenue", date(2024, 1, 1), date(2024, 3, 31), 11),
        fact("revenue", date(2024, 4, 1), date(2024, 6, 30), 12),
    ]
    rows = [r for r in single_quarters(facts) if not r.derived]
    assert [r.fiscal_period for r in rows] == ["Q2", "Q3"]


def test_higher_priority_concept_wins_over_later_filing():
    s, e = date(2024, 4, 1), date(2024, 6, 30)
    facts = [
        fact("net_income", s, e, 5, filed=date(2024, 8, 1), concept="us-gaap:NetIncomeLoss"),
        fact("net_income", s, e, 9, filed=date(2024, 9, 1), concept="us-gaap:ProfitLoss"),
    ]
    assert single_quarters(facts)[0].net_income == 5


def test_derived_q4_does_not_mix_concepts():
    nil, pl = "us-gaap:NetIncomeLoss", "us-gaap:ProfitLoss"
    facts = [
        fact("net_income", date(2024, 1, 1), date(2024, 3, 31), 1, concept=nil),
        fact("net_income", date(2024, 4, 1), date(2024, 6, 30), 2, concept=nil),
        fact("net_income", date(2024, 7, 1), date(2024, 9, 30), 3, concept=nil),
        fact("net_income", date(2024, 1, 1), date(2024, 12, 31), 100, concept=pl, form="10-K"),
    ]
    assert not any(r.derived for r in single_quarters(facts))
    facts.append(fact("net_income", date(2024, 1, 1), date(2024, 12, 31), 10, concept=nil))
    assert single_quarters(facts)[-1].net_income == 4


def test_gross_profit_fallback_takes_provenance_from_one_fact():
    s, e = date(2024, 4, 1), date(2024, 6, 30)
    facts = [
        fact("revenue", s, e, 100, filed=date(2024, 8, 1), form="10-Q", accession="r"),
        fact("cost_of_revenue", s, e, 60, filed=date(2024, 9, 1), form="10-Q/A", accession="c"),
    ]
    row = single_quarters(facts)[0]
    assert (row.form, row.filed, row.accession) == ("10-Q/A", date(2024, 9, 1), "c")


def test_cost_only_period_is_not_a_quarter():
    s, e = date(2024, 4, 1), date(2024, 6, 30)
    assert single_quarters([fact("cost_of_revenue", s, e, 60)]) == []
