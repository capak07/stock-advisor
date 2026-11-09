"""Single-quarter results from SEC XBRL facts.

10-Qs report 3-, 6- and 9-month durations and the 10-K only the full year, so the fourth quarter
is derived as the annual value minus the three quarters inside it.

Quarter logic follows trader-analyst/facts.py from github.com/Jakeschincariol/day-trader-skill (MIT).
"""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from advisor.collectors.sec_xbrl import METRICS as XBRL_METRICS
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


_RANK = {
    (metric, f"{taxonomy}:{concept}"): i
    for metric, concepts in XBRL_METRICS.items()
    for i, (taxonomy, concept, _unit) in enumerate(concepts)
}  # same order as the model's priority: the order of sec_xbrl.METRICS


def _rank(fact: FinancialFact) -> int:
    return _RANK.get((fact.metric, fact.concept), 99)


def _by_period(
    facts: Sequence[FinancialFact],
) -> dict[Period, dict[str, dict[str, FinancialFact]]]:
    """Per (start, end), metric and concept, the fact with the latest filing.

    Gross profit falls back to revenue - cost of revenue (one synthetic concept) when the
    period has no GrossProfit fact; the fallback's form, filed and accession come from the
    later-filed of its two inputs.
    """
    out: dict[Period, dict[str, dict[str, FinancialFact]]] = defaultdict(lambda: defaultdict(dict))
    for f in facts:
        if f.start is None or f.metric not in (*METRICS, "cost_of_revenue"):
            continue
        slot = out[(f.start, f.end)][f.metric]
        if f.concept not in slot or f.filed > slot[f.concept].filed:
            slot[f.concept] = f
    for by_metric in out.values():
        if "gross_profit" in by_metric or "revenue" not in by_metric:
            continue
        if "cost_of_revenue" not in by_metric:
            continue
        rev = min(by_metric["revenue"].values(), key=lambda f: (_rank(f), -f.filed.toordinal()))
        cost = min(
            by_metric["cost_of_revenue"].values(), key=lambda f: (_rank(f), -f.filed.toordinal())
        )
        later = rev if rev.filed >= cost.filed else cost
        by_metric["gross_profit"] = {
            "derived:revenue-cost": later.model_copy(
                update={
                    "metric": "gross_profit",
                    "concept": "derived:revenue-cost",
                    "value": rev.value - cost.value,
                }
            )
        }
    return out


def _best(by_concept: dict[str, FinancialFact]) -> FinancialFact:
    """Highest-priority concept, then the latest filing (one fact per concept already)."""
    return min(by_concept.values(), key=_rank)


def single_quarters(facts: Sequence[FinancialFact], keep: int = 12) -> list[QuarterRow]:
    """One symbol's single quarters, newest `keep`, oldest first (Q4 derived from the annual)."""
    by_period = _by_period(facts)
    if not by_period:
        return []
    symbol = facts[0].symbol
    has_metric = {p for p, m in by_period.items() if any(k in METRICS for k in m)}
    quarters = sorted(p for p in has_metric if _days(p) in QUARTER_DAYS)
    annuals = sorted(p for p in has_metric if _days(p) in ANNUAL_DAYS)

    # period -> (metric values, facts used, derived)
    rows: dict[Period, tuple[dict[str, float], list[FinancialFact], bool]] = {}
    for p in quarters:
        used = [_best(c) for m, c in by_period[p].items() if m in METRICS]
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
            sets = [set(by_period[p].get(m, {})) for p in (a, *three)]
            common = set.intersection(*sets)  # one concept for the annual and all three quarters
            if not common:
                continue
            ann = by_period[a][m]
            concept = min(common, key=lambda c: _rank(ann[c]))
            vals[m] = ann[concept].value - sum(by_period[q][m][concept].value for q in three)
            used.append(ann[concept])
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
            n = round((period[1] - year[0]).days / 91.3)  # placed by date, not by what is present
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
