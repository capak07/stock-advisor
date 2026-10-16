from datetime import UTC, date, datetime

import httpx
import pytest

from advisor.collectors.base import PartialFetch
from advisor.collectors.fred import SERIES, Fred, parse_csv

AS_OF = datetime(2026, 10, 15, 12, 15, tzinfo=UTC)  # the 450-day lookback starts 2025-07-22


def csv_text(fixtures_dir, series: str) -> str:
    return (fixtures_dir / "fred" / f"fred_{series}.csv").read_text(encoding="utf-8")


def serving(fixtures_dir, seen: list | None = None, broken: frozenset[str] = frozenset()) -> Fred:
    def handler(request: httpx.Request) -> httpx.Response:
        series = request.url.params["id"]
        if seen is not None:
            seen.append((series, request.url.params["cosd"]))
        if series in broken:
            return httpx.Response(404, text="<!DOCTYPE html><title>Error - St. Louis Fed</title>")
        return httpx.Response(200, text=csv_text(fixtures_dir, series))

    return Fred(httpx.Client(transport=httpx.MockTransport(handler)))


def test_parse_skips_days_without_a_value(fixtures_dir):
    rows = parse_csv("T10Y2Y", csv_text(fixtures_dir, "T10Y2Y"), date(2025, 7, 22), date(2026, 10, 15))
    assert len(rows) == 123
    assert (rows[0].day, rows[0].value) == (date(2026, 4, 20), 0.54)
    assert (rows[-1].day, rows[-1].value) == (date(2026, 10, 14), 0.37)
    assert date(2026, 10, 12) not in {r.day for r in rows}  # Columbus Day: an empty field


def test_parse_keeps_only_the_window_because_fred_may_ignore_the_start(fixtures_dir):
    rows = parse_csv("T10Y2Y", csv_text(fixtures_dir, "T10Y2Y"), date(2026, 10, 1), date(2026, 10, 13))
    assert [r.day for r in rows][0] == date(2026, 10, 1)
    assert rows[-1].day == date(2026, 10, 13)  # 2026-10-14 is after `end`


@pytest.mark.parametrize(
    "body",
    [
        "<!DOCTYPE html><title>Error - St. Louis Fed</title>",  # an error page
        "PK\x03\x04 fredgraph.zip",  # several series with different dates come back zipped
        "observation_date,DGS2\n2026-10-13,4.79\n",  # someone else's series
        "",
    ],
)
def test_anything_but_the_series_csv_is_an_error(body):
    with pytest.raises(ValueError, match="FRED sent no CSV for DGS10"):
        parse_csv("DGS10", body, date(2026, 1, 1), date(2026, 10, 15))


def test_fetch_asks_once_per_series_from_the_lookback(fixtures_dir):
    seen: list = []
    records = serving(fixtures_dir, seen).fetch([], AS_OF)
    assert seen == [(series, "2025-07-22") for series in SERIES]
    assert len(records) == 950
    cpi = [r for r in records if r.series == "CPIAUCSL"]
    assert (len(cpi), cpi[0].day, cpi[-1].day, cpi[-1].value) == (
        13, date(2025, 8, 1), date(2026, 9, 1), 336.298
    )  # September 2025 is in the window: year-over-year needs it
    assert {r.series for r in records} == set(SERIES)


def test_a_failing_series_is_a_partial_result(fixtures_dir):
    failed = "1 of 9 FRED series failed; first: VIXCLS: HTTPStatusError"
    with pytest.raises(PartialFetch, match=failed) as caught:
        serving(fixtures_dir, broken=frozenset({"VIXCLS"})).fetch([], AS_OF)
    assert len(caught.value.records) == 950 - 128
    assert "VIXCLS" not in {r.series for r in caught.value.records}


def test_every_series_failing_fails_the_source(fixtures_dir):
    with pytest.raises(PartialFetch, match="9 of 9 FRED series failed") as caught:
        serving(fixtures_dir, broken=frozenset(SERIES)).fetch([], AS_OF)
    assert caught.value.records == []  # an empty PartialFetch counts as a failure
