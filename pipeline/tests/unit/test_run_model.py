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
