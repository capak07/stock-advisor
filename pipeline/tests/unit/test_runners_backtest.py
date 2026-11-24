import json
from dataclasses import astuple, replace
from datetime import date

import pandas as pd
import pytest

from advisor.runners import backtest
from advisor.runners.backtest import (
    cutoff_of,
    load_series,
    report,
    run_backtest,
    sessions_of,
    trades,
    variants,
)
from advisor.runners.rule import STARTING, series_of
from runner_data import AKAN_AFTER, akan, daily, more_flat_days, weekdays

NO_EVENTS = pd.DataFrame({"symbol": [], "day": [], "dividend": [], "split": []})


def sessions_from(series):
    return sorted({day for s in series.values() for day in s.days})


def test_prices_as_traded_are_rebuilt_from_later_splits():
    days = [date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7)]
    flat = {"open": [10.0] * 3, "high": [10.0] * 3, "low": [10.0] * 3, "close": [10.0] * 3, "volume": [1.0] * 3}
    prices = pd.concat([pd.DataFrame({"symbol": [name] * 3, "day": days, **flat}) for name in ("X", "BIG")])
    events = pd.DataFrame({"symbol": ["X"], "day": [date(2026, 1, 7)], "dividend": [0.0], "split": [0.1]})
    got = load_series(prices, events)             # X: a 1-for-10 reverse split on Jan 7, so it traded at 1.00 before
    assert list(got) == ["X"]                     # BIG never traded inside $0.50-$5
    assert got["X"].raw_close.tolist() == [1.0, 1.0, 10.0] and got["X"].close.tolist() == [10.0] * 3


def test_a_missing_volume_drops_that_day_and_keeps_later_signals():
    bars = more_flat_days([*akan(), *(daily("AKAN", b) for b in AKAN_AFTER)], 12)
    prices = pd.DataFrame([b.model_dump(include={"symbol", "day", "open", "high", "low", "close", "volume"}) for b in bars])
    prices.loc[5, "volume"] = float("nan")       # one NaN would poison the running volume sums
    series = load_series(prices, NO_EVENTS)
    assert len(series["AKAN"].days) == len(bars) - 1 and bars[5].day not in series["AKAN"].days
    [row] = trades(series, sessions_of(prices), STARTING).to_dict("records")
    assert (row["signal_day"], row["status"]) == (date(2026, 11, 13), "target")


def test_sessions_are_every_day_any_symbol_traded():
    prices = pd.DataFrame({"symbol": ["A", "B", "A"], "day": [date(2026, 1, 7), date(2026, 1, 5), date(2026, 1, 5)]})
    assert sessions_of(prices) == [date(2026, 1, 5), date(2026, 1, 7)]


def test_a_trade_is_found_and_settled_as_live_does():
    series = {"AKAN": series_of(more_flat_days([*akan(), *(daily("AKAN", b) for b in AKAN_AFTER)], 12))}
    rows = trades(series, sessions_from(series), STARTING)
    [row] = rows.to_dict("records")
    assert (row["signal_day"], row["entry_day"], row["status"]) == (date(2026, 11, 13), date(2026, 11, 16), "target")
    assert row["gross_r"] == pytest.approx(2.0) and row["net_r"] == pytest.approx(2.0 - row["cost_r"])


def test_a_gap_over_the_limit_is_a_skip_not_a_trade():
    series = {"AKAN": series_of(more_flat_days([*akan(), *(daily("AKAN", b) for b in AKAN_AFTER)], 12))}
    [row] = trades(series, sessions_from(series), replace(STARTING, gap_skip=0.15)).to_dict("records")
    assert (row["status"], row["skip_reason"]) == ("skipped", "gapped up at the open")   # opened 41% over D's close


def test_a_signal_too_close_to_the_end_of_the_data_is_dropped():
    series = {"AKAN": series_of([*akan(), daily("AKAN", AKAN_AFTER[0])])}
    assert trades(series, sessions_from(series), STARTING).empty


def test_fifteen_variants_each_change_one_setting():
    got = variants(STARTING)
    assert len(got) == 15 and got[0] == ("starting values", STARTING)
    assert all(sum(a != b for a, b in zip(astuple(rule), astuple(STARTING), strict=True)) == 1 for _, rule in got[1:])


def test_report_counts_trades_not_skips():
    rows = pd.DataFrame([
        {"symbol": "A", "signal_day": date(2026, 1, 5), "status": "target", "skip_reason": None, "gross_r": 2.0, "cost_r": 0.1, "net_r": 1.9},
        {"symbol": "B", "signal_day": date(2026, 1, 6), "status": "stop", "skip_reason": None, "gross_r": -1.5, "cost_r": 0.1, "net_r": -1.6},
        {"symbol": "C", "signal_day": date(2026, 1, 7), "status": "skipped", "skip_reason": "gapped up at the open", "gross_r": None, "cost_r": 0.1, "net_r": None},
    ])
    got = report(rows)
    assert (got["signals"], got["skipped_gap"], got["target"], got["stop"]) == (2, 1, 1, 1)
    assert got["avg_net_r"] == pytest.approx(0.15) and got["lost_over_1r"] == 0.5
    assert got["worst"][0] == {"symbol": "B", "signal_day": "2026-01-06", "net_r": -1.6}
    assert report(rows.iloc[0:0])["avg_net_r"] is None


def test_the_newest_third_starts_at_the_cutoff():
    days = weekdays(300)
    assert cutoff_of(days) == days[200]


def test_too_few_signals_keeps_the_starting_values():
    series = {"AKAN": series_of(more_flat_days([*akan(), *(daily("AKAN", b) for b in AKAN_AFTER)], 12))}
    got = run_backtest(series, sessions_from(series), None)
    assert (got["pick"]["name"], got["pick"]["note"], got["variants_tried"], got["frozen"]) == ("starting values", "too few signals to choose", 15, None)
    assert got["pick"]["newer"]["signals"] == 1 and json.loads(json.dumps(got)) == got      # stores as JSON unchanged


def test_the_pick_is_the_best_older_average_among_variants_with_200_trades(monkeypatch):
    days = weekdays(300)                                         # the cutoff is days[200]
    def rows(n, net_r):
        return pd.DataFrame({"symbol": "A", "signal_day": [days[0]] * n, "entry_day": days[1], "status": "target",
                             "skip_reason": None, "gross_r": net_r, "cost_r": 0.0, "net_r": net_r})
    def fake(series, sessions, rule):
        if rule.hold_sessions == 20:
            return rows(250, 0.3)
        if rule.volume_x == 20.0:
            return rows(150, 0.9)                                # the best average, but under 200 trades
        return rows(250, 0.1)
    monkeypatch.setattr(backtest, "trades", fake)
    got = run_backtest({}, days, STARTING)
    assert (got["pick"]["name"], got["pick"]["note"]) == ("hold 20", None)
    assert got["pick"]["older"]["signals"] == 250 and got["pick"]["newer"]["signals"] == 0
    assert got["frozen"]["older"]["avg_net_r"] == pytest.approx(0.1) and got["cutoff"] == days[200].isoformat()
