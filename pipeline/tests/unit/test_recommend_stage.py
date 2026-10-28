import math
from dataclasses import replace
from datetime import date, datetime

import pandas as pd
import pytest

from advisor.collectors.base import CollectorResult, CollectorStatus
from advisor.collectors.clinical_trials import TrialActivity
from advisor.collectors.yfinance_earnings import EarningsReport
from advisor.model.features import PRICE_FEATURES, RS_FEATURES
from advisor.model.fundamentals import FUNDAMENTAL_FEATURES
from advisor.model.market_run import Forecast, MarketModel
from advisor.model.predict import ActiveModel
from advisor.models import ET, AssetRef, AssetType, Market, PredictionRow
from advisor.policy import DEFAULT_POLICY, policy_of
from advisor.recommend.stage import (
    StockInputs,
    hold_events,
    is_sane,
    recommend_market,
    risk_frame,
    scheduled_events,
    watch_verdicts,
)
from fakes import bar

NAN = float("nan")
DAY = date(2026, 10, 13)  # the feature day
EXIT = date(2026, 11, 10)


def features(rows: dict[str, dict], names: list[str]) -> pd.DataFrame:
    """Every named feature 0.1 unless a row says otherwise."""
    return pd.DataFrame({s: dict.fromkeys(names, 0.1) | r for s, r in rows.items()}).T.astype(float)


def results(earnings=(), trials=()) -> dict[str, CollectorResult]:
    return {
        "yfinance_earnings": CollectorResult("yfinance_earnings", CollectorStatus.OK, list(earnings), 0),
        "clinical_trials": CollectorResult("clinical_trials", CollectorStatus.OK, list(trials), 0),
    }


def report(symbol: str, day: date) -> EarningsReport:
    return EarningsReport(symbol=symbol, report_at=datetime(day.year, day.month, day.day, 7, 0, tzinfo=ET))


def readout(symbol: str, day: date) -> TrialActivity:
    return TrialActivity(symbol=symbol, as_of=DAY, next_completion=day)


US_NAMES = PRICE_FEATURES + RS_FEATURES + FUNDAMENTAL_FEATURES
TSX_NAMES = PRICE_FEATURES + RS_FEATURES


def test_the_us_risk_frame_has_every_component():
    f = features({
        "AAA": {"ex_bench_63": 0.05, "rev_growth": -0.1, "log_mcap": 22.0},  # 3 signals, split 2:1
        "BBB": {"ex_bench_63": 0.05, **dict.fromkeys(FUNDAMENTAL_FEATURES, NAN)},  # no fundamentals
    }, US_NAMES)
    news = {"AAA": 0.3, "BBB": -0.2}
    events = hold_events(scheduled_events(results([report("AAA", date(2026, 10, 29))])),
                         {"AAA": (DAY, EXIT), "BBB": (DAY, EXIT)}, same_day=False)
    out = risk_frame(Market.US, f, {"AAA": 0.15, "BBB": 0.2}, events, news)
    assert out.loc["AAA", "disagreement"] == pytest.approx(2 / 3)
    assert out.loc["BBB", "disagreement"] == 1.0  # up technically, down on the news: 2 signals
    assert (out.loc["AAA", "event"], out.loc["BBB", "event"]) == (1.0, 0.0)
    assert out.loc["AAA", "log_mcap"] == 22.0
    assert math.isnan(out.loc["BBB", "log_mcap"])
    assert out.loc["AAA", "groups_missing_share"] == 0.0
    assert list(out["width"]) == [0.15, 0.2]


def test_a_us_stock_without_news_or_fundamentals_misses_half_its_groups():
    f = features({"AAA": dict.fromkeys(FUNDAMENTAL_FEATURES, NAN)}, US_NAMES)
    out = risk_frame(Market.US, f, {"AAA": 0.1}, {"AAA": []}, {})
    assert out.loc["AAA", "groups_missing_share"] == 0.5  # fundamentals and news of 4 groups
    assert math.isnan(out.loc["AAA", "disagreement"])  # the technical signal alone can't disagree


def test_a_tsx_stock_has_three_groups_and_no_size_term():
    # a stray log_mcap must not give a TSX stock a size component or the small-cap floor
    f = features({"RY.TO": {"log_mcap": 18.0}, "TD.TO": {"ex_bench_63": -0.02}}, [*TSX_NAMES, "log_mcap"])
    out = risk_frame(Market.TSX, f, {"RY.TO": 0.1, "TD.TO": 0.1}, {"RY.TO": [], "TD.TO": []}, {"TD.TO": 0.4})
    assert out["log_mcap"].isna().all()
    assert out.loc["RY.TO", "groups_missing_share"] == pytest.approx(1 / 3)  # news, of 3 groups
    assert out.loc["TD.TO", "groups_missing_share"] == 0.0
    assert out.loc["TD.TO", "disagreement"] == 1.0  # technical down, news up
    assert math.isnan(out.loc["RY.TO", "disagreement"])  # one signal


def test_events_count_only_inside_the_hold():
    scheduled = scheduled_events(results(
        [report("AAA", date(2026, 10, 29)), report("BBB", date(2026, 11, 11)), report("CCC", DAY)],
        [readout("DDD", EXIT), readout("EEE", date(2026, 9, 30))],
    ))
    windows = {s: (DAY, EXIT) for s in ["AAA", "BBB", "CCC", "DDD", "EEE"]}
    inside = {s for s, found in hold_events(scheduled, windows, same_day=False).items() if found}
    assert inside == {"AAA", "DDD"}  # the exit-by day counts; the day after and the feature day don't
    f = features({s: {} for s in windows}, TSX_NAMES)
    out = risk_frame(Market.TSX, f, dict.fromkeys(windows, 0.1), hold_events(scheduled, windows, same_day=False), {})
    assert list(out["event"]) == [1.0, 0.0, 0.0, 1.0, 0.0]


def test_at_a_pre_close_run_an_event_on_the_feature_day_is_inside_the_hold():
    # the entry is today's 3:15 price, so tonight's report lands during the hold
    scheduled = scheduled_events(results([report("CCC", DAY)]))
    assert hold_events(scheduled, {"CCC": (DAY, EXIT)}, same_day=True)["CCC"][0][1] == {
        "type": "earnings", "date": "2026-10-13",
    }
    assert hold_events(scheduled, {"CCC": (DAY, EXIT)}, same_day=False)["CCC"] == []


def test_a_stock_without_a_hold_has_no_event_value():
    f = features({"AAA": {}}, TSX_NAMES)
    out = risk_frame(Market.TSX, f, {"AAA": NAN}, {}, {})
    assert math.isnan(out.loc["AAA", "event"])


@pytest.mark.parametrize(("atr", "sane"), [(0.04, True), (0.49, True), (0.5, False), (0.8, False), (NAN, False)])
def test_sanity_needs_an_atr_that_keeps_a_swing_stop_above_zero(atr, sane):
    f = features({"AAA": {"atr_14_pct": atr, "jump_5d": 0.0}}, TSX_NAMES)
    bars = {"AAA": [bar("AAA", DAY, 10.0)]}
    assert is_sane("AAA", f, bars, {}, DAY) is sane


class _Model:
    features = ["vol_60"]

    def contributions(self, frame, horizon):
        return {str(symbol): [] for symbol in frame.index}


def _stage(metrics):
    symbol = "AAA.TO"
    row = PredictionRow(symbol, 5, -0.02, 0.04, 0.10, 0.55, "XIU.TO", "v1")
    names = [*TSX_NAMES, "eligible"]
    frame = features({symbol: {"atr_14_pct": 0.04, "jump_5d": 0.0, "eligible": 1.0}}, names)
    forecast = Forecast(frame, [row])
    model = MarketModel(
        ActiveModel("v", _Model(), (5,)),
        pd.DataFrame({"symbol": [symbol], "sector": ["Tech"]}),
        metrics,
    )
    inputs = StockInputs(DAY, False, {symbol: [row]}, {symbol: True}, {symbol: 0.001})
    bars = {symbol: [bar(symbol, DAY, 10.0)], "XIU.TO": [bar("XIU.TO", DAY, 30.0)]}
    picks, details, *_ = recommend_market(
        Market.TSX, model, forecast, inputs, bars, set(), {}, {}, DAY,
    )
    verdicts = watch_verdicts(
        {AssetRef(symbol, AssetType.STOCK)}, set(), {Market.TSX: forecast}, {Market.TSX: inputs},
        {Market.TSX: details}, {Market.TSX: True}, {}, policies={Market.TSX: policy_of(metrics)},
    )
    return picks, verdicts


def test_the_models_stored_policy_makes_the_pick_and_the_watched_buy():
    loose = replace(DEFAULT_POLICY, p_buy=0.54)
    picks, verdicts = _stage({"picks_enabled": True, "config": {"policy": loose.to_json()}})
    assert [p.symbol for p in picks] == ["AAA.TO"]
    assert verdicts[0].verdict == "buy"


def test_an_invalid_stored_policy_behaves_as_the_default():
    invalid = _stage({"picks_enabled": True, "config": {"policy": {"bad": 1}}})
    default = _stage({"picks_enabled": True})
    assert invalid[0] == default[0] == []
    assert invalid[1][0].verdict == default[1][0].verdict == "hold"


def test_a_wider_swing_multiple_rejects_an_atr_the_default_allows():
    f = features({"AAA": {"atr_14_pct": 0.4, "jump_5d": 0.0}}, TSX_NAMES)
    bars = {"AAA": [bar("AAA", DAY, 10.0)]}
    assert is_sane("AAA", f, bars, {}, DAY, policy=replace(DEFAULT_POLICY, swing_atr=2.0)) is True
    assert is_sane("AAA", f, bars, {}, DAY, policy=replace(DEFAULT_POLICY, swing_atr=3.0)) is False


def test_sanity_fails_a_jump_a_stale_bar_or_a_flagged_bar():
    f = features({"AAA": {"atr_14_pct": 0.04, "jump_5d": 0.0}, "JMP": {"atr_14_pct": 0.04, "jump_5d": 1.0},
                  "NAJ": {"atr_14_pct": 0.04, "jump_5d": NAN}}, TSX_NAMES)
    bars = {s: [bar(s, DAY, 10.0)] for s in ["AAA", "JMP", "NAJ"]}
    assert is_sane("AAA", f, bars, {}, DAY) is True
    assert is_sane("JMP", f, bars, {}, DAY) is False
    assert is_sane("NAJ", f, bars, {}, DAY) is False  # stricter than the backtest, on purpose
    assert is_sane("AAA", f, bars, {}, date(2026, 10, 14)) is False  # no bar on the feature day
    assert is_sane("AAA", f, bars, {"AAA": {DAY}}, DAY) is False
