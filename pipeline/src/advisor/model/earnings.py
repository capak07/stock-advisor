"""Point-in-time US quarterly earnings features from the as-filed SEC facts, as wide day x symbol frames.

Single quarters come from 3-month facts (80-100 days); a fiscal Q4 is the fiscal year (350-380 days)
minus the 9-month year-to-date ending inside it, known when the later of the two was filed. Each
quarter is compared with the quarter whose end is 365 +/- 20 days earlier. Values are first-reported
(`fundamentals.first_reported`), a day reads only what was filed strictly before it, and quarters that
ended over STALE_DAYS before the day read NaN.

EPS is put on today's share basis as `fundamental_features` does: each value is divided by the split
factor at its filing date (`_split_at`), so a split between quarters leaves `sue` unchanged.
A derived Q4 EPS (FY - 9M) is an approximation, since diluted EPS is not additive when the share
count changes during the year; it is dropped when a split falls between the 9M and FY filings.
`days_since_report` counts from the latest filing of any of the three metrics (usually one 10-Q).
"""

from collections.abc import Sequence

import numpy as np
import pandas as pd

from advisor.model.fundamentals import _asof, _fresh, _ns, _split_at, first_reported

EARNINGS_FEATURES = ["rev_growth_q", "op_margin_q_chg", "sue", "days_since_report"]
METRICS = ("revenue", "operating_income", "eps_diluted")
SUE_CLIP = 5.0
SUE_WINDOW, SUE_MIN = 8, 4
DAYS_CAP = 120
YEAR, YEAR_TOL = pd.Timedelta(days=365), pd.Timedelta(days=20)


def single_quarters(facts: pd.DataFrame) -> pd.DataFrame:
    """One row per (cik, metric, quarter end) from `first_reported` rows: cik, metric, end, value, known."""
    return _quarters(facts).drop(columns=["filed_fy", "filed_9m"])


def _quarters(facts: pd.DataFrame) -> pd.DataFrame:
    """`single_quarters` plus filed_fy and filed_9m (NaT unless the row is a derived Q4)."""
    d = facts[facts["start"].notna() & facts["metric"].isin(METRICS)].copy()
    d["days"] = (d["end"] - d["start"]).dt.days
    q = d[d["days"].between(80, 100)].rename(columns={"filed": "known"})
    fy = d[d["days"].between(350, 380)]
    nine = d[d["days"].between(255, 290)]
    m = fy.merge(nine, on=["cik", "metric", "start"], suffixes=("", "_9m"))
    m = m[m["end_9m"] < m["end"]]
    m = m.assign(value=m["value"] - m["value_9m"], known=m[["filed", "filed_9m"]].max(axis=1), filed_fy=m["filed"])
    cols = ["cik", "metric", "end", "value", "known"]
    out = pd.concat([q[cols], m[[*cols, "filed_fy", "filed_9m"]]], ignore_index=True)
    out[["filed_fy", "filed_9m"]] = out[["filed_fy", "filed_9m"]].astype("datetime64[ns]")
    out = out.sort_values("known", kind="stable").drop_duplicates(["cik", "metric", "end"])
    return out.sort_values(["cik", "metric", "end"], kind="stable").reset_index(drop=True)


def _year_ago(q: pd.DataFrame) -> pd.DataFrame:
    """`q` (one metric) with value_1y: the quarter ending 365 +/- 20 days earlier, if known no later."""
    q = q.sort_values("end", kind="stable").reset_index(drop=True)
    left = q.assign(target=q["end"] - YEAR).sort_values("target", kind="stable")
    right = q[["cik", "end", "value", "known"]].rename(
        columns={"end": "target", "value": "value_1y", "known": "known_1y"}).sort_values("target", kind="stable")
    m = pd.merge_asof(left, right, on="target", by="cik", direction="nearest", tolerance=YEAR_TOL)
    late = m["known_1y"] > m["known"]
    m.loc[late, "value_1y"] = np.nan  # its known is still raised below; harmless, the value is blank
    m["known"] = m[["known", "known_1y"]].max(axis=1)
    return m.drop(columns=["target", "known_1y"])


def _ratio(num: pd.Series, den: pd.Series) -> pd.Series:
    return (num / den).where(den.abs() > 0)


def _sue(eps: pd.DataFrame) -> pd.DataFrame:
    """Rows of eps changes with `sue`: the change / std of up to 8 prior changes known by then (>= 4)."""
    c = eps.assign(chg=eps["value"] - eps["value_1y"]).dropna(subset=["chg"])
    c = c.sort_values(["cik", "known", "end"], kind="stable").reset_index(drop=True)
    prior = c.groupby("cik")["chg"].shift()
    std = prior.groupby(c["cik"]).rolling(SUE_WINDOW, min_periods=SUE_MIN).std(ddof=1).reset_index(level=0, drop=True)
    c["sue"] = (c["chg"] / std.where(std > 0)).clip(-SUE_CLIP, SUE_CLIP)
    return c


def _ids(tickers: pd.DataFrame) -> pd.DataFrame:
    """symbol, cik and a per-symbol integer id (sid)."""
    ids = tickers[["symbol", "cik"]].drop_duplicates("symbol").reset_index(drop=True)
    return ids.assign(cik=ids["cik"].astype("int64"), sid=ids.index.astype("int64"))


def eps_quarters(facts: pd.DataFrame, tickers: pd.DataFrame, splits: pd.DataFrame) -> pd.DataFrame:
    """Diluted-EPS quarters per symbol on today's share basis, from `first_reported` rows.

    Columns: cik (the symbol's id from `_ids`), symbol, end, value, known. A derived Q4 whose FY and 9M
    filings straddle a split is dropped (the two terms are on different share bases).
    """
    q = _quarters(facts)
    eps = q[q["metric"] == "eps_diluted"].merge(_ids(tickers), on="cik").reset_index(drop=True)
    if not eps.empty:
        eps["value"] = eps["value"].to_numpy() / _split_at(splits, eps["symbol"], eps["known"]).to_numpy()
        derived = eps["filed_9m"].notna()
        f_fy = _split_at(splits, eps["symbol"], eps["filed_fy"])
        f_9m = _split_at(splits, eps["symbol"], eps["filed_9m"])
        eps = eps[~(derived & (f_fy != f_9m)).to_numpy()]
    return eps.assign(cik=eps["sid"])[["cik", "symbol", "metric", "end", "value", "known"]].reset_index(drop=True)


def earnings_features(facts: pd.DataFrame, tickers: pd.DataFrame, days: pd.DatetimeIndex,
                      symbols: Sequence[str], splits: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Wide frames (days x symbols) of EARNINGS_FEATURES; symbols missing from `tickers` read NaN."""
    symbols = list(symbols)
    wanted = set(tickers["symbol"])
    present = [s for s in symbols if s in wanted]
    if not present or facts.empty:
        empty = pd.DataFrame(np.nan, index=days, columns=symbols)
        return {name: empty.copy() for name in EARNINGS_FEATURES}
    first = first_reported(facts)
    q = single_quarters(first)
    syms = tickers[tickers["symbol"].isin(present)][["symbol", "cik"]].drop_duplicates("symbol")
    syms["cik"] = syms["cik"].astype("int64")
    grid = syms.merge(pd.DataFrame({"day": _ns(days)}), how="cross")
    grid = grid.sort_values("day", kind="stable").reset_index(drop=True)
    out = grid[["day", "symbol"]].copy()

    rev = _year_ago(q[q["metric"] == "revenue"])
    rev["rev_growth_q"] = _ratio(rev["value"], rev["value_1y"]) - 1
    out["rev_growth_q"] = _fresh(grid, _asof(rev, grid, ["rev_growth_q", "end"]))["rev_growth_q"]

    key = ["cik", "end"]
    r = q[q["metric"] == "revenue"][[*key, "value", "known"]]
    oi = q[q["metric"] == "operating_income"][[*key, "value", "known"]]
    mg = r.merge(oi, on=key, suffixes=("_r", "_o"))
    mg = mg.assign(value=100 * _ratio(mg["value_o"], mg["value_r"]), known=mg[["known_r", "known_o"]].max(axis=1))
    mg = _year_ago(mg[[*key, "value", "known"]])
    mg["op_margin_q_chg"] = mg["value"] - mg["value_1y"]
    out["op_margin_q_chg"] = _fresh(grid, _asof(mg, grid, ["op_margin_q_chg", "end"]))["op_margin_q_chg"]

    # EPS per symbol (a CIK may list several), on today's share basis; "cik" holds a symbol id from here
    ids = _ids(syms)
    eps = eps_quarters(first, syms, splits)
    sgrid = grid.merge(ids[["symbol", "sid"]], on="symbol").assign(cik=lambda x: x["sid"])
    sgrid = sgrid.sort_values("day", kind="stable").reset_index(drop=True)
    sue = _sue(_year_ago(eps[["cik", "metric", "end", "value", "known"]]))
    s_vals = _fresh(sgrid, _asof(sue, sgrid, ["sue", "end"]))
    out = out.merge(pd.DataFrame({"day": sgrid["day"], "symbol": sgrid["symbol"], "sue": s_vals["sue"]}),
                    on=["day", "symbol"], how="left")

    last = _fresh(grid, _asof(q.assign(filed=q["known"]), grid, ["filed", "end"]))
    out["days_since_report"] = (grid["day"] - last["filed"]).dt.days.clip(upper=DAYS_CAP)

    wide = out.pivot(index="day", columns="symbol")
    return {name: wide[name].reindex(index=_ns(days), columns=symbols).set_axis(days, axis=0)
            for name in EARNINGS_FEATURES}
