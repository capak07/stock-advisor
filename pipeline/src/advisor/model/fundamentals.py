"""Point-in-time US fundamentals from the as-filed SEC facts, as wide day x symbol frames.

Each period's value is the one first reported (best-priority concept, earliest `filed`), so a period
becomes known on one date and later restatements are ignored. A day reads only what was filed
strictly before it. Trailing twelve months at a period end E come from year-to-date facts:
TTM = YTD(E) + FY(ending before the YTD starts) - YTD(E - 12 months), known when the last of the
three was filed; a fiscal-year fact is its own TTM.
"""

from collections.abc import Sequence

import numpy as np
import pandas as pd

from advisor.collectors.sec_xbrl import METRICS

FUNDAMENTAL_FEATURES = [
    "rev_growth", "gross_margin", "op_margin", "gross_margin_trend", "op_margin_trend", "eps_growth",
    "earnings_yield", "sales_yield", "fcf_yield", "debt_to_equity", "log_mcap",
]
FLOWS = ("revenue", "gross_profit", "operating_income", "net_income", "operating_cash_flow", "capex", "eps_diluted")
BALANCES = ("equity", "long_term_debt", "long_term_debt_noncurrent", "debt_current", "short_term_borrowings",
            "commercial_paper", "shares_outstanding")
EPS_CLIP = 5.0
STALE_DAYS = 548  # a figure whose period ended over 18 months ago is no longer read

_RANK = {(metric, f"{taxonomy}:{concept}"): i
         for metric, concepts in METRICS.items() for i, (taxonomy, concept, _unit) in enumerate(concepts)}


def _ns(values):
    """Datetimes at one resolution, so merge_asof keys always match."""
    return pd.to_datetime(values).astype("datetime64[ns]")


def first_reported(facts: pd.DataFrame) -> pd.DataFrame:
    """One row per (cik, metric, start, end): the best-priority concept's earliest filing."""
    f = facts[["cik", "metric", "concept", "start", "end", "value", "filed"]].copy()
    for col in ("start", "end", "filed"):
        f[col] = _ns(f[col])
    f["rank"] = [_RANK.get(key, 99) for key in zip(f["metric"], f["concept"], strict=True)]
    f = f.sort_values(["rank", "filed"], kind="stable").drop_duplicates(["cik", "metric", "start", "end"])
    return f.drop(columns=["concept", "rank"]).reset_index(drop=True)


def ttm(facts: pd.DataFrame) -> pd.DataFrame:
    """Trailing twelve months per flow metric and period end, from `first_reported` rows.

    Columns: cik, metric, period (monthly Period of the end), end, ttm, known, ttm_1y (NaN when the
    year-ago TTM is missing or was only known after this row's).
    """
    d = facts[facts["start"].notna() & facts["metric"].isin(FLOWS)].copy()
    d["days"] = (d["end"] - d["start"]).dt.days
    d["period"] = d["end"].dt.to_period("M")
    key = ["cik", "metric", "period"]
    fy = d[d["days"].between(350, 380)].drop_duplicates(key)
    ytd = d[(d["days"] >= 81) & (d["days"] < 350)].copy()
    ytd["months"] = (ytd["days"] / 30.44).round().astype(int)
    ytd = ytd.drop_duplicates([*key, "months"])
    ytd["fy_period"] = (ytd["start"] - pd.Timedelta(days=1)).dt.to_period("M")
    ytd["prev_period"] = ytd["period"] - 12

    fy_part = fy[[*key, "value", "filed"]].rename(
        columns={"period": "fy_period", "value": "fy_value", "filed": "fy_filed"})
    prev = ytd[[*key, "months", "value", "filed"]].rename(
        columns={"period": "prev_period", "value": "prev_value", "filed": "prev_filed"})
    m = ytd.merge(fy_part, on=["cik", "metric", "fy_period"]).merge(
        prev, on=["cik", "metric", "prev_period", "months"])
    m["ttm"] = m["value"] + m["fy_value"] - m["prev_value"]
    m["known"] = m[["filed", "fy_filed", "prev_filed"]].max(axis=1)

    cols = [*key, "end", "ttm", "known"]
    t = pd.concat([fy.rename(columns={"value": "ttm", "filed": "known"})[cols], m[cols]])
    t = t.sort_values("known", kind="stable").drop_duplicates(key).reset_index(drop=True)

    ago = t[[*key, "ttm", "known"]].rename(columns={"ttm": "ttm_1y", "known": "known_1y"})
    ago["period"] = ago["period"] + 12
    t = t.merge(ago, on=key, how="left")
    t.loc[t["known_1y"] > t["known"], "ttm_1y"] = np.nan  # a year-ago figure filed later can't be used
    return t.drop(columns="known_1y")


def _asof(table: pd.DataFrame, grid: pd.DataFrame, cols: Sequence[str]) -> pd.DataFrame:
    """The latest row of `table` known strictly before each grid day, per cik."""
    right = table[["cik", "known", *cols]].copy()
    right["cik"] = right["cik"].astype("int64")
    right["known"] = right["known"].astype(grid["day"].dtype)
    right = right.sort_values(["known", "end"], kind="stable")  # same-day filings: newest period last
    out = pd.merge_asof(grid[["cik", "day"]], right, left_on="day", right_on="known", by="cik",
                        allow_exact_matches=False)
    return out[list(cols)].reset_index(drop=True)


def _fresh(grid: pd.DataFrame, vals: pd.DataFrame) -> pd.DataFrame:
    """`vals` with every column blanked where the period `end` is over STALE_DAYS before the day."""
    stale = (grid["day"] - vals["end"]).dt.days > STALE_DAYS
    return vals.apply(lambda column: column.mask(stale))


def _split_at(splits: pd.DataFrame, symbols: pd.Series, dates: pd.Series) -> pd.Series:
    """Split factor (today's shares per then-share) at each symbol's date.

    Carries the last row at or before the date; dates before the first row read the first row.
    Missing dates stay NaN; symbols without split data read 1.
    """
    long = (splits.rename_axis("date").reset_index().melt("date", var_name="symbol", value_name="factor")
            .dropna().sort_values("date", kind="stable"))
    long["date"] = long["date"].astype("datetime64[ns]")
    left = pd.DataFrame({"symbol": symbols.to_numpy(), "date": dates.to_numpy()})
    valid = left[left["date"].notna()].copy()
    valid["date"] = valid["date"].astype("datetime64[ns]").clip(lower=splits.index.min())
    valid["row"] = valid.index
    got = pd.merge_asof(valid.sort_values("date", kind="stable"), long, on="date", by="symbol")
    out = pd.Series(np.nan, index=left.index)
    out.loc[got["row"].to_numpy()] = got["factor"].fillna(1.0).to_numpy()
    return out


def _ratio(num: pd.Series, den: pd.Series) -> pd.Series:
    return (num / den).where(den.abs() > 0)


def fundamental_features(facts: pd.DataFrame, tickers: pd.DataFrame, days: pd.DatetimeIndex,
                         split_adjusted_close: pd.DataFrame, splits: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Wide frames (days x symbols) of FUNDAMENTAL_FEATURES for symbols in both `tickers` and the close."""
    first = first_reported(facts)
    t = ttm(first)
    wanted = set(tickers["symbol"])
    symbols = [s for s in split_adjusted_close.columns if s in wanted]
    syms = tickers[tickers["symbol"].isin(symbols)][["symbol", "cik"]].drop_duplicates("symbol")
    syms["cik"] = syms["cik"].astype("int64")
    grid = syms.merge(pd.DataFrame({"day": _ns(days)}), how="cross")
    grid = grid.sort_values("day", kind="stable").reset_index(drop=True)
    g = grid.copy()

    for metric in FLOWS:
        vals = _fresh(grid, _asof(t[t["metric"] == metric], grid, ["ttm", "ttm_1y", "end"]))
        g[metric], g[f"{metric}_1y"] = vals["ttm"], vals["ttm_1y"]
        g[f"{metric}_period"] = vals["end"].dt.to_period("M")
        if metric == "eps_diluted":
            g["eps_end"] = vals["end"]

    bal = first[first["start"].isna() & first["metric"].isin(BALANCES)].rename(columns={"filed": "known"})
    bal = bal.sort_values("end", kind="stable").drop_duplicates(["cik", "metric", "known"], keep="last")
    for metric in BALANCES:
        vals = _fresh(grid, _asof(bal[bal["metric"] == metric], grid, ["value", "end"]))
        g[metric] = vals["value"]
        if metric == "shares_outstanding":
            g["shares_end"] = vals["end"]

    price = split_adjusted_close.rename_axis("day").reset_index().melt("day", var_name="symbol", value_name="price")
    price["day"] = price["day"].astype(grid["day"].dtype)
    g = g.merge(price, on=["day", "symbol"], how="left")

    mcap = g["price"] * g["shares_outstanding"] * _split_at(splits, g["symbol"], g["shares_end"])
    eps = g["eps_diluted"] / _split_at(splits, g["symbol"], g["eps_end"])
    eps_1y = g["eps_diluted_1y"] / _split_at(splits, g["symbol"], g["eps_end"] - pd.DateOffset(months=12))

    long_term = g["long_term_debt"].fillna(
        g[["long_term_debt_noncurrent", "debt_current"]].sum(axis=1, min_count=1))
    debt = pd.concat([long_term, g["short_term_borrowings"], g["commercial_paper"]], axis=1).sum(axis=1, min_count=1)

    out = pd.DataFrame({"day": g["day"], "symbol": g["symbol"]})
    out["rev_growth"] = _ratio(g["revenue"], g["revenue_1y"]) - 1
    gross_ok = g["gross_profit_period"] == g["revenue_period"]  # NaT never equals
    op_ok = g["operating_income_period"] == g["revenue_period"]
    out["gross_margin"] = _ratio(g["gross_profit"], g["revenue"]).where(gross_ok)
    out["op_margin"] = _ratio(g["operating_income"], g["revenue"]).where(op_ok)
    out["gross_margin_trend"] = out["gross_margin"] - _ratio(g["gross_profit_1y"], g["revenue_1y"]).where(gross_ok)
    out["op_margin_trend"] = out["op_margin"] - _ratio(g["operating_income_1y"], g["revenue_1y"]).where(op_ok)
    out["eps_growth"] = _ratio(eps - eps_1y, eps_1y.abs()).clip(-EPS_CLIP, EPS_CLIP)
    out["earnings_yield"] = _ratio(g["net_income"], mcap)
    out["sales_yield"] = _ratio(g["revenue"], mcap)
    out["fcf_yield"] = _ratio(g["operating_cash_flow"] - g["capex"], mcap).where(
        g["operating_cash_flow_period"] == g["capex_period"])
    out["debt_to_equity"] = _ratio(debt, g["equity"].where(g["equity"] > 0))
    out["log_mcap"] = np.log(mcap.where(mcap > 0))

    wide = out.pivot(index="day", columns="symbol")
    return {name: wide[name].reindex(index=_ns(days), columns=symbols).set_axis(days, axis=0)
            for name in FUNDAMENTAL_FEATURES}
