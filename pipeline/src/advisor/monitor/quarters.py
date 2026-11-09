"""Single-quarter results from SEC XBRL facts.

10-Qs report 3-, 6- and 9-month durations and the 10-K only the full year, so the fourth quarter
is derived as the annual value minus the three quarters inside it.

Quarter logic follows trader-analyst/facts.py from github.com/Jakeschincariol/day-trader-skill (MIT).
"""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from advisor.collectors.sec_xbrl import FinancialFact

QUARTER_DAYS = range(80, 101)
ANNUAL_DAYS = range(350, 381)
METRICS = ("revenue", "gross_profit", "operating_income", "net_income", "eps_diluted")
Period = tuple[date, date]


@dataclass(frozen=True)
class QuarterRow:
    symbol: str
    period_start: date
    period_end: date
    fiscal_year: int | None
    fiscal_period: str | None  # "Q1".."Q4"
    revenue: float | None
    gross_profit: float | None
    operating_income: float | None
    net_income: float | None
    eps_diluted: float | None
    form: str
    filed: date
    accession: str
    derived: bool


def _days(period: Period) -> int:
    return (period[1] - period[0]).days


def _plus_year(d: date) -> date:
    try:
        return d.replace(year=d.year + 1)
    except ValueError:  # 29 Feb
        return d.replace(year=d.year + 1, day=28)


def _by_period(facts: Sequence[FinancialFact]) -> dict[Period, dict[str, FinancialFact]]:
    """Per (start, end) and metric, the fact with the latest filing; gross profit falls back."""
    best: dict[tuple[str, Period], FinancialFact] = {}
    for f in facts:
        if f.start is None or f.metric not in (*METRICS, "cost_of_revenue"):
            continue
        key = (f.metric, (f.start, f.end))
        if key not in best or f.filed > best[key].filed:
            best[key] = f
    out: dict[Period, dict[str, FinancialFact]] = defaultdict(dict)
    for (metric, period), f in best.items():
        out[period][metric] = f
    for by_metric in out.values():
        rev, cost = by_metric.get("revenue"), by_metric.get("cost_of_revenue")
        if "gross_profit" not in by_metric and rev and cost:
            by_metric["gross_profit"] = rev.model_copy(
                update={
                    "metric": "gross_profit",
                    "value": rev.value - cost.value,
                    "filed": max(rev.filed, cost.filed),
                }
            )
    return out


def single_quarters(facts: Sequence[FinancialFact], keep: int = 12) -> list[QuarterRow]:
    """One symbol's single quarters, newest `keep`, oldest first (Q4 derived from the annual)."""
    by_period = _by_period(facts)
    if not by_period:
        return []
    symbol = facts[0].symbol
    quarters = sorted(p for p in by_period if _days(p) in QUARTER_DAYS)
    annuals = sorted(p for p in by_period if _days(p) in ANNUAL_DAYS)

    # period -> (metric values, facts used, derived)
    rows: dict[Period, tuple[dict[str, float], list[FinancialFact], bool]] = {}
    for p in quarters:
        used = [f for m, f in by_period[p].items() if m in METRICS]
        if used:
            rows[p] = ({f.metric: f.value for f in used}, used, False)

    for a in annuals:
        if any(q[1] == a[1] for q in quarters):  # a real 3-month Q4 exists
            continue
        inside = [q for q in quarters if q[0] >= a[0] and q[1] <= a[1]]
        if len(inside) < 3:
            continue
        three = inside[-3:]
        vals: dict[str, float] = {}
        used = []
        for m in METRICS:
            annual = by_period[a].get(m)
            parts = [by_period[q].get(m) for q in three]
            if annual is None or any(x is None for x in parts):
                continue
            vals[m] = annual.value - sum(x.value for x in parts if x is not None)
            used.append(annual)
        if vals:
            rows[(three[-1][1] + timedelta(days=1), a[1])] = (vals, used, True)

    # fiscal years: known annual periods, plus one extrapolated year after the last one
    years = [(a[0], a[1], a[1].year) for a in annuals]
    if annuals:
        nxt = _plus_year(annuals[-1][1])
        years.append((annuals[-1][1] + timedelta(days=1), nxt, nxt.year))

    out: list[QuarterRow] = []
    for period in sorted(rows, key=lambda p: p[1]):
        vals, used, derived = rows[period]
        year = next(((s, y) for s, e, y in years if s <= period[0] and period[1] <= e), None)
        fiscal_year = label = None
        if year is not None:
            fiscal_year = year[1]
            n = sum(1 for q in quarters if q[0] >= year[0] and q[1] <= period[1])
            label = "Q4" if derived else f"Q{min(max(n, 1), 4)}"
        src = max(used, key=lambda f: f.filed)
        out.append(
            QuarterRow(
                symbol=symbol,
                period_start=period[0],
                period_end=period[1],
                fiscal_year=fiscal_year,
                fiscal_period=label,
                revenue=vals.get("revenue"),
                gross_profit=vals.get("gross_profit"),
                operating_income=vals.get("operating_income"),
                net_income=vals.get("net_income"),
                eps_diluted=vals.get("eps_diluted"),
                form=src.form,
                filed=src.filed,
                accession=src.accession,
                derived=derived,
            )
        )
    return out[-keep:]
