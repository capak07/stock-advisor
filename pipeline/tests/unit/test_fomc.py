from datetime import UTC, date, datetime

import httpx
import pytest

from advisor.collectors.base import PartialFetch
from advisor.collectors.fomc import (
    CALENDAR_URL,
    RSS_URL,
    Fomc,
    decision_day,
    parse_calendar,
    parse_releases,
)

AS_OF = datetime(2026, 10, 15, 12, 15, tzinfo=UTC)


def feed(fixtures_dir) -> bytes:
    return (fixtures_dir / "fomc" / "fomc_press_monetary.xml").read_bytes()  # starts with a BOM


def calendar(fixtures_dir) -> str:
    return (fixtures_dir / "fomc" / "fomc_calendars_2026_excerpt.html").read_text(encoding="utf-8")


def serving(routes: dict[str, httpx.Response]) -> Fomc:
    def handler(request: httpx.Request) -> httpx.Response:
        return routes.get(str(request.url), httpx.Response(404))

    return Fomc(httpx.Client(transport=httpx.MockTransport(handler)))


def test_releases_are_told_apart_by_title(fixtures_dir):
    events = parse_releases(feed(fixtures_dir), AS_OF)
    assert [(e.kind, e.day) for e in events] == [
        ("other", date(2026, 10, 13)),  # minutes of the Board's discount rate meetings
        ("minutes", date(2026, 10, 7)),
        ("statement", date(2026, 9, 16)),
        ("projections", date(2026, 9, 16)),
        ("other", date(2026, 8, 25)),
        ("minutes", date(2026, 8, 19)),
        ("statement", date(2026, 7, 29)),
        ("other", date(2026, 7, 14)),
        ("other", date(2026, 7, 9)),
        ("minutes", date(2026, 7, 8)),
    ]
    statement = events[2]
    assert statement.published_at == datetime(2026, 9, 16, 18, 0, tzinfo=UTC)  # 14:00 ET
    assert statement.url == "https://www.federalreserve.gov/newsevents/pressreleases/monetary20260916a.htm"


def test_releases_after_as_of_are_left_out(fixtures_dir):
    events = parse_releases(feed(fixtures_dir), datetime(2026, 9, 16, 17, 59, tzinfo=UTC))
    assert [e.day for e in events if e.kind == "statement"] == [date(2026, 7, 29)]


@pytest.mark.parametrize(
    ("year", "month_cell", "date_cell", "expected"),
    [
        (2026, "October", "27-28", date(2026, 10, 28)),
        (2026, "March", "17-18*", date(2026, 3, 18)),
        (2019, "Apr/May", "30-1", date(2019, 5, 1)),
        (2025, "January", "22 (notation vote)", date(2025, 1, 22)),
    ],
)
def test_the_decision_comes_on_a_meetings_last_day(year, month_cell, date_cell, expected):
    assert decision_day(year, month_cell, date_cell) == expected


def test_the_calendar_keeps_upcoming_and_recent_meetings(fixtures_dir):
    meetings = parse_calendar(calendar(fixtures_dir), AS_OF)
    assert [(m.kind, m.day, m.title) for m in meetings] == [
        ("meeting", date(2026, 9, 16), "FOMC meeting, September 15-16, 2026"),
        ("meeting", date(2026, 10, 28), "FOMC meeting, October 27-28, 2026"),
        ("meeting", date(2026, 12, 9), "FOMC meeting, December 8-9, 2026"),
    ]


def test_fetch_returns_releases_then_meetings(fixtures_dir):
    events = serving({
        RSS_URL: httpx.Response(200, content=feed(fixtures_dir)),
        CALENDAR_URL: httpx.Response(200, text=calendar(fixtures_dir)),
    }).fetch([], AS_OF)
    assert len(events) == 13
    assert [e.kind for e in events[-3:]] == ["meeting"] * 3


@pytest.mark.parametrize(
    ("page", "message"),
    [
        (httpx.Response(404), "FOMC calendar unreadable: HTTPStatusError"),
        (httpx.Response(200, text="<html>a redesigned page</html>"), "lists no upcoming"),
    ],
)
def test_an_unreadable_calendar_keeps_the_releases(fixtures_dir, page, message):
    with pytest.raises(PartialFetch, match=message) as caught:
        serving({RSS_URL: httpx.Response(200, content=feed(fixtures_dir)), CALENDAR_URL: page}).fetch(
            [], AS_OF
        )
    assert len(caught.value.records) == 10


def test_a_missing_feed_fails_the_source(fixtures_dir):
    with pytest.raises(httpx.HTTPStatusError, match="HTTP 404"):
        serving({CALENDAR_URL: httpx.Response(200, text=calendar(fixtures_dir))}).fetch([], AS_OF)


def test_an_odd_row_in_an_old_years_panel_is_ignored(fixtures_dir):
    old = (
        '<h4><a id="1">2019 FOMC Meetings</a></h4>'
        '<div class="fomc-meeting__month"><strong>January</strong></div>'
        '<div class="fomc-meeting__month"><strong>March</strong></div>'
        '<div class="fomc-meeting__date">29-30</div>'
    )
    meetings = parse_calendar(old + calendar(fixtures_dir), AS_OF)
    assert [m.day for m in meetings] == [date(2026, 9, 16), date(2026, 10, 28), date(2026, 12, 9)]
