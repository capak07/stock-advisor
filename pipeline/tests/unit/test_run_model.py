from datetime import UTC, date, datetime

import pandas as pd
import pytest

from advisor.models import Market, RunKind
from advisor.run import feature_day
from fakes import bar

PRE_CLOSE_AT = datetime(2026, 10, 14, 19, 15, tzinfo=UTC)  # 15:15 ET on Wednesday 2026-10-14


@pytest.mark.parametrize(
    ("kind", "last_bar", "partial"),
    [
        (RunKind.PRE_CLOSE, date(2026, 10, 14), True),  # today's bar, mid-session
        (RunKind.PRE_CLOSE, date(2026, 10, 13), False),  # Yahoo has no bar for today yet
        (RunKind.PRE_OPEN, date(2026, 10, 14), False),  # before the open every bar is complete
    ],
)
def test_the_feature_day_is_partial_only_for_todays_bar_during_a_session(kind, last_bar, partial):
    bars = {"SPY": [bar("SPY", date(2026, 10, 12), 500.0), bar("SPY", last_bar, 501.0)]}
    assert feature_day(Market.US, bars, kind, PRE_CLOSE_AT) == (pd.Timestamp(last_bar), partial)


def test_a_market_without_benchmark_bars_has_no_feature_day():
    with pytest.raises(ValueError, match="no SPY bars"):
        feature_day(Market.US, {}, RunKind.PRE_OPEN, PRE_CLOSE_AT)


def test_forecast_market_passes_the_group_history_for_us_only(monkeypatch):
    """US forecasts read the data groups built from the run's records; TSX has none (US-only groups)."""
    import contextlib
    from types import SimpleNamespace

    from advisor import run
    from advisor.collectors.base import CollectorResult, CollectorStatus
    from advisor.model.groups import GroupHistory

    seen: dict[Market, object] = {}

    def features(market, model, symbols, bars, kind, now_utc, *, events=None, facts=None, history=None):
        seen[market] = history
        return pd.DataFrame({"eligible": [False]}, index=pd.Index(["X"], name="symbol"))

    monkeypatch.setattr(run, "model_features", features)
    monkeypatch.setattr(run.repo, "write_predictions", lambda *args, **kwargs: None)
    monkeypatch.setattr(run.repo, "merge_features_live", lambda *args, **kwargs: None)
    conn = SimpleNamespace(transaction=contextlib.nullcontext)
    deps = run.RunDeps(conn=conn, cache=None, collectors={})
    model = SimpleNamespace(active=SimpleNamespace(model=SimpleNamespace(features=[])))
    results = {
        "sec_form4": CollectorResult("sec_form4", CollectorStatus.OK, [], 0),
        "sec_13dg": CollectorResult("sec_13dg", CollectorStatus.FAILED, [], 0, "down"),
    }
    for market in (Market.US, Market.TSX):
        run.forecast_market(deps, 1, market, model, ["X"], {}, RunKind.PRE_OPEN, PRE_CLOSE_AT, results)
    assert isinstance(seen[Market.US], GroupHistory)
    assert seen[Market.US].insider_trades is not None and seen[Market.US].insider_trades.empty
    assert seen[Market.US].large_holders is None  # the source failed this run
    assert seen[Market.US].short_interest is None  # not run at all
    assert seen[Market.TSX] is None


def _option_run(monkeypatch, view_fields: dict, status=None):
    """Runs forecast_market for AAPL with a fake yfinance_options result; returns the merged rows."""
    import contextlib
    from types import SimpleNamespace

    from advisor import run
    from advisor.collectors.base import CollectorResult, CollectorStatus
    from advisor.collectors.yfinance_options import OptionsView

    def features(market, model, symbols, bars, kind, now_utc, *, events=None, facts=None, history=None):
        return pd.DataFrame({"eligible": [True]}, index=pd.Index(["AAPL"], name="symbol"))

    merged: list = []
    monkeypatch.setattr(run, "model_features", features)
    monkeypatch.setattr(run, "predict_rows", lambda *args, **kwargs: [])
    monkeypatch.setattr(run.repo, "write_predictions", lambda *args, **kwargs: None)
    monkeypatch.setattr(run.repo, "merge_features_live", lambda conn, run_id, rows, as_of: merged.append(list(rows)))
    deps = run.RunDeps(conn=SimpleNamespace(transaction=contextlib.nullcontext), cache=None, collectors={})
    model = SimpleNamespace(active=SimpleNamespace(model=SimpleNamespace(features=[])))
    view = OptionsView(symbol="AAPL", as_of=date(2026, 11, 19), expiries=12, **view_fields)
    results = {
        "yfinance_options": CollectorResult("yfinance_options", status or CollectorStatus.OK, [view], 1),
    }
    run.forecast_market(deps, 1, Market.US, model, ["AAPL"], {}, RunKind.PRE_OPEN, PRE_CLOSE_AT, results)
    return [row for batch in merged for row in batch if any(k.startswith("opt_") for k in row[1])]


def test_option_summaries_are_stored_with_the_run(monkeypatch):
    rows = _option_run(
        monkeypatch,
        {"atm_iv_near": 0.24, "atm_iv_mid": 0.27, "skew_near": 0.05,
         "put_call_volume": 0.8, "put_call_open_interest": 1.1},
    )
    assert len(rows) == 1
    assert rows[0][1] == {
        "opt_atm_iv_near": 0.24, "opt_atm_iv_mid": 0.27, "opt_skew_near": 0.05,
        "opt_put_call_volume": 0.8, "opt_put_call_open_interest": 1.1,
    }


def test_a_missing_option_value_is_left_out(monkeypatch):
    rows = _option_run(
        monkeypatch,
        {"atm_iv_near": 0.24, "atm_iv_mid": None, "skew_near": float("nan"), "put_call_volume": float("inf")},
    )
    assert rows[0][1] == {"opt_atm_iv_near": 0.24}


def test_a_source_that_did_not_run_cleanly_stores_no_option_values(monkeypatch):
    from advisor.collectors.base import CollectorStatus

    assert _option_run(monkeypatch, {"atm_iv_near": 0.24}, status=CollectorStatus.FAILED) == []
