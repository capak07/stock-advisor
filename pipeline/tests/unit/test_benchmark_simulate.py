import math
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from advisor.benchmark.simulate import DailyPanel, book_metrics, daily_panel, simulate_book
from advisor.models import Market
from advisor.policy import DEFAULT_POLICY
from model_data import write_market

TSX_COST = 0.001  # 2e7 dollar volume: the large-cap spread, no FX fee
START = pd.Timestamp("2024-01-01")


def panel(paths, atr=0.02, bench=None):
    """`paths`: symbol -> closes from START; the benchmark is flat unless given."""
    days = pd.bdate_range(START, periods=len(next(iter(paths.values()))))
    close = pd.DataFrame(paths, index=days, dtype=float)
    close["SPY"] = bench if bench is not None else 100.0
    return DailyPanel(close, pd.DataFrame(atr, index=days, columns=close.columns), "SPY")


def row(day=START, symbol="A", horizon=5, p=0.7, q50=0.05, **kw):
    return {"day": pd.Timestamp(day), "symbol": symbol, "sector": "Tech", "dollar_volume_20": 2e7,
            "horizon": horizon, "fold": 1, "y": 0.0, "q10": q50 - 0.1, "q50": q50, "q90": q50 + 0.1,
            "p_raw": p, "p": p, **kw}


def run(pnl, rows, policy=DEFAULT_POLICY, market=Market.TSX, end=None):
    end = end if end is not None else pnl.close.index[-1] + pd.Timedelta(days=1)
    return simulate_book(pd.DataFrame(rows), pnl, policy, market, 1.5, START, end)


def session(n):
    return pd.bdate_range(START, periods=n + 1)[n]


def test_a_trade_exits_at_its_exit_by_close():
    book = run(panel({"A": [100, 101, 102, 103, 104, 105, 106]}), [row()])
    (t,) = book.trades.itertuples()
    assert t.reason == "exit_by" and t.exit_day == session(5)
    assert t.net == pytest.approx(0.05 - TSX_COST)


def test_a_close_at_or_under_the_stop_exits_there():
    book = run(panel({"A": [100, 99, 96, 95, 97, 98]}), [row()])
    (t,) = book.trades.itertuples()
    assert (t.reason, t.exit_day, t.exit) == ("stop", session(2), 96.0)
    assert t.net == pytest.approx(-0.04 - TSX_COST)


def test_the_trailing_stop_only_rises_and_exits_there():
    book = run(panel({"A": [100, 110, 120, 105, 130, 130]}), [row(horizon=63)])
    (t,) = book.trades.itertuples()
    assert (t.reason, t.exit_day, t.exit) == ("trail", session(3), 105.0)


def test_a_later_forecast_at_the_sell_line_sells():
    later = [row(horizon=63), row(day=session(5), horizon=63, p=0.42)]
    pnl = panel({"A": [100.0] * 10})
    (t,) = run(pnl, later).trades.itertuples()
    assert (t.reason, t.exit_day) == ("sell", session(5))
    (t,) = run(pnl, later, replace(DEFAULT_POLICY, p_sell=0.40)).trades.itertuples()
    assert t.reason == "end"


def test_positions_still_open_close_at_end():
    pnl = panel({"A": [100, 101, 102, 103, 104, 105, 106, 107]})
    end = session(3)
    book = run(pnl, [row(horizon=63)], end=end)
    (t,) = book.trades.itertuples()
    assert (t.reason, t.exit_day) == ("end", session(2))
    assert list(book.daily.index) == list(pd.bdate_range(START, periods=3))
    later = pnl.close.copy()
    later.loc[later.index >= end] = 1.0
    changed = replace(pnl, close=later)
    again = run(changed, [row(horizon=63)], end=end)
    pd.testing.assert_frame_equal(book.trades, again.trades)
    pd.testing.assert_series_equal(book.daily, again.daily)


def test_entries_follow_the_policy():
    pnl = panel({"A": [100.0] * 10})
    # ratio prefers the 5-day row (0.05/0.2 vs 0.04/0.2 + a higher P at 63)
    rows = [row(horizon=5, p=0.60, q50=0.05), row(horizon=63, p=0.70, q50=0.04)]
    assert run(pnl, rows).trades["horizon"].tolist() == [5]
    assert run(pnl, rows, replace(DEFAULT_POLICY, rule="p")).trades["horizon"].tolist() == [63]
    assert run(pnl, rows, replace(DEFAULT_POLICY, horizons=(21, 63, 126))).trades["horizon"].tolist() == [63]
    assert run(pnl, [row(p=0.65)], replace(DEFAULT_POLICY, p_buy=0.66)).trades.empty
    assert run(panel({"A": [100.0] * 10}, atr=np.nan), [row()]).trades.empty
    assert run(pnl, [row(jump_5d=1.0)]).trades.empty


def test_one_position_per_stock_and_the_style_and_sector_caps():
    names = [f"S{i:02d}" for i in range(12)]
    pnl = panel({s: [100.0] * 10 for s in names})
    one_sector = [row(symbol=s, q50=0.05 + i / 1000) for i, s in enumerate(names)]
    assert len(run(pnl, one_sector).trades) == 3
    own_sectors = [{**r, "sector": r["symbol"]} for r in one_sector]
    assert len(run(pnl, own_sectors).trades) == 10
    again = [row(horizon=63), row(day=session(2), horizon=63)]
    assert len(run(panel({"A": [100.0] * 10}), again).trades) == 1


def test_a_missing_close_carries_forward():
    book = run(panel({"A": [100, 101, np.nan, np.nan, 104, 105, 106]}), [row()])
    (t,) = book.trades.itertuples()
    assert t.reason == "exit_by"


def test_us_costs_include_the_fx_fee():
    (t,) = run(panel({"A": [100.0] * 8}), [row()], market=Market.US).trades.itertuples()
    assert t.cost == pytest.approx(0.001 + 0.03)


def test_book_metrics():
    pnl = panel({"A": [100, 110, 110, 110, 110, 110, 110], "B": [100, 90, 90, 90, 90, 90, 90]})
    book = run(pnl, [row(symbol="A", p=0.6), row(symbol="B", p=0.8)])
    m = book_metrics(book)
    assert m["trades"] == 2 and m["trades_per_month"] == 2.0
    assert m["beat_rate"] == 0.5 and m["mean_p"] == pytest.approx(0.7)
    assert m["claimed_gap_pts"] == pytest.approx(20.0)
    assert m["hit_rate_net"] == 0.5
    assert m["max_drawdown"] >= 0
    empty = book_metrics(run(pnl, []))
    assert empty["trades"] == 0 and empty["beat_rate"] is None and math.isnan(empty["sharpe"])
    assert empty["max_drawdown"] == 0.0


def test_the_daily_panel_matches_the_training_closes(tmp_path):
    write_market(tmp_path, Market.TSX, stocks=5, days=400)
    pnl = daily_panel(tmp_path, Market.TSX)
    assert pnl.benchmark == "XIU.TO" and "XIU.TO" in pnl.close
    assert pnl.close.shape == pnl.atr_pct.shape
    assert pnl.atr_pct.iloc[-1].dropna().between(0, 1).all()
