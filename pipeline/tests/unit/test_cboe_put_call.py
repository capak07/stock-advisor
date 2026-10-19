from datetime import UTC, date, datetime

import httpx
import pytest

from advisor.collectors.cboe_put_call import CboePutCall, parse_day, weekdays
from advisor.models import Market

AS_OF = datetime(2026, 10, 19, 15, 30, tzinfo=UTC)  # Monday 11:30 ET
ACCESS_DENIED = "<?xml version=\"1.0\" encoding=\"UTF-8\"?><Error><Code>AccessDenied</Code></Error>"


def daily(equity_puts: int = 2_000_000) -> dict:
    """A day's file in Cboe's shape, with made-up numbers (Cboe's terms limit storing its files)."""

    def group(calls: int, puts: int) -> list[dict]:
        return [
            {"name": "VOLUME", "call": calls, "put": puts, "total": calls + puts},
            {"name": "OPEN INTEREST", "call": 10 * calls, "put": 10 * puts, "total": 10 * (calls + puts)},
        ]

    return {
        "ratios": [{"name": "TOTAL PUT/CALL RATIO", "value": "0.90"}],
        "SUM OF ALL PRODUCTS": group(10_000_000, 9_000_000),
        "INDEX OPTIONS": list(reversed(group(5_000_000, 5_500_000))),  # entries matched by name
        "EQUITY OPTIONS": group(3_200_000, equity_puts),
        "CBOE VOLATILITY INDEX (VIX)": group(800_000, 250_000),
    }


def cboe(days: dict[str, dict], asked: list[str], status: int = 403) -> httpx.Client:
    """Cboe's CDN: a file for each day in `days`, and `status` (403, as S3 answers) for the rest."""

    def handler(request: httpx.Request) -> httpx.Response:
        day = request.url.path.rsplit("/", 1)[-1].removesuffix("_daily_options")
        asked.append(day)
        if day in days:
            return httpx.Response(200, json=days[day])
        return httpx.Response(status, text=ACCESS_DENIED)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_a_days_ratios_are_puts_over_calls_found_by_group_name():
    rows = {row.series: row.value for row in parse_day(daily(), date(2026, 10, 16))}
    assert rows == {
        "cboe_total_put_call": pytest.approx(0.9),
        "cboe_equity_put_call": pytest.approx(0.625),
        "cboe_index_put_call": pytest.approx(1.1),
    }  # this file has no exchange-traded products group
    with pytest.raises(ValueError, match="none of its put/call groups"):
        parse_day({"ratios": []}, date(2026, 10, 16))


def test_the_last_ten_days_are_asked_for_weekdays_only():
    assert weekdays(AS_OF) == [
        date(2026, 10, 12), date(2026, 10, 13), date(2026, 10, 14), date(2026, 10, 15),
        date(2026, 10, 16), date(2026, 10, 19),
    ]


def test_days_without_a_file_are_skipped():
    asked: list[str] = []
    files = {"2026-10-15": daily(), "2026-10-16": daily(equity_puts=3_200_000)}
    with cboe(files, asked) as client:
        rows = CboePutCall(client).fetch([], AS_OF)
    assert len(asked) == 6  # today's file isn't posted until the evening
    equity = [(row.day, row.value) for row in rows if row.series == "cboe_equity_put_call"]
    assert equity == [(date(2026, 10, 15), 0.625), (date(2026, 10, 16), 1.0)]


def test_no_file_in_ten_days_means_cboe_moved_or_blocked_them():
    with cboe({}, []) as client, pytest.raises(RuntimeError, match="no put/call file"):
        CboePutCall(client).fetch([], AS_OF)


def test_other_http_errors_fail_the_fetch():
    with cboe({}, [], status=404) as client, pytest.raises(httpx.HTTPStatusError, match="404"):
        CboePutCall(client).fetch([], AS_OF)


def test_the_source_is_us_market_wide_daily_and_best_effort():
    collector = CboePutCall(httpx.Client())
    assert (collector.scope, collector.cadence, collector.best_effort) == ("market", "daily", True)
    assert collector.markets == frozenset({Market.US})
