import json
from datetime import date

import httpx
import pytest

from advisor.collectors import boc_valet, fred
from advisor.training.macro import (
    ATTEMPTS,
    BUDGET_SECONDS,
    COLUMNS,
    MacroRefused,
    MacroUnavailable,
    macro_history,
)

START, END = date(2026, 4, 1), date(2026, 10, 15)


def sources(fixtures_dir, asked: list[httpx.Request], fred_missing: str | None = None) -> httpx.Client:
    """FRED and the Bank of Canada answering from the live collectors' recorded fixtures."""
    valet = json.loads((fixtures_dir / "boc" / "valet_observations_recent10.json").read_text(encoding="utf-8"))

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(request)
        if request.url.host == "fred.stlouisfed.org":
            series = request.url.params["id"]
            if series == fred_missing:
                return httpx.Response(200, text=f"observation_date,{series}\n")
            text = (fixtures_dir / "fred" / f"fred_{series}.csv").read_text(encoding="utf-8")
            return httpx.Response(200, text=text)
        return httpx.Response(200, json=valet)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_every_live_series_is_fetched_from_the_start(fixtures_dir):
    asked: list[httpx.Request] = []
    with sources(fixtures_dir, asked) as client:
        frame = macro_history(client, START, END)
    assert list(frame.columns) == COLUMNS
    assert set(frame["series"]) == set(fred.SERIES) | set(boc_valet.SERIES)
    fred_asks = [r for r in asked if r.url.host == "fred.stlouisfed.org"]
    assert [r.url.params["id"] for r in fred_asks] == list(fred.SERIES)
    assert {r.url.params["cosd"] for r in fred_asks} == {"2026-04-01"}
    valet_ask = next(r for r in asked if r.url.host != "fred.stlouisfed.org")
    assert (valet_ask.url.params["start_date"], valet_ask.url.params["end_date"]) == ("2026-04-01", "2026-10-15")
    assert frame["day"].min() >= START and frame["day"].max() <= END
    assert frame.equals(frame.sort_values(["series", "day"], ignore_index=True))


def test_a_series_without_values_fails_the_build(fixtures_dir):
    with sources(fixtures_dir, [], fred_missing="VIXCLS") as client, pytest.raises(ValueError, match="VIXCLS"):
        macro_history(client, START, END)


def flaky_sources(fixtures_dir, failures: dict[str, list]) -> tuple[httpx.Client, list[str]]:
    """Like `sources`, but each FRED series first answers with its queued failures in order: an
    exception class to raise (a timeout) or a response to send (a 429)."""
    asked: list[str] = []
    healthy = sources(fixtures_dir, [])

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "fred.stlouisfed.org":
            series = request.url.params["id"]
            asked.append(series)
            queued = failures.get(series, [])
            if queued:
                failure = queued.pop(0)
                if isinstance(failure, httpx.Response):
                    return failure
                raise failure("The read operation timed out", request=request)
        return healthy._transport.handle_request(request)

    return httpx.Client(transport=httpx.MockTransport(handler)), asked


def test_a_fred_read_timeout_is_retried_and_the_build_goes_on(fixtures_dir):
    pauses: list[float] = []
    client, asked = flaky_sources(fixtures_dir, {"DGS10": [httpx.ReadTimeout, httpx.ConnectTimeout]})
    with client:
        frame = macro_history(client, START, END, sleep=pauses.append)
    assert set(frame["series"]) == set(fred.SERIES) | set(boc_valet.SERIES)
    assert asked.count("DGS10") == 3
    assert pauses == [10.0, 20.0]  # patient backoff, not the live collectors' 1 s and 2 s


def test_fred_retry_after_is_honoured(fixtures_dir):
    pauses: list[float] = []
    busy = httpx.Response(429, headers={"Retry-After": "45"})
    client, _ = flaky_sources(fixtures_dir, {"T10Y2Y": [busy]})
    with client:
        macro_history(client, START, END, sleep=pauses.append)
    assert pauses == [45.0]


def test_fred_still_down_after_every_try_fails_with_the_series_named(fixtures_dir):
    pauses: list[float] = []
    client, asked = flaky_sources(fixtures_dir, {"VIXCLS": [httpx.ReadTimeout] * ATTEMPTS})
    with client, pytest.raises(MacroUnavailable, match=r"FRED did not answer for VIXCLS after 6 tries \(ReadTimeout"):
        macro_history(client, START, END, sleep=pauses.append)
    assert asked.count("VIXCLS") == ATTEMPTS == 6
    assert pauses == [10.0, 20.0, 40.0, 80.0, 160.0]
    assert asked[-1] == "VIXCLS"  # nothing after the dead series is asked


def test_macro_requests_get_a_longer_read_timeout(fixtures_dir):
    timeouts: list[dict] = []
    healthy = sources(fixtures_dir, [])

    def handler(request: httpx.Request) -> httpx.Response:
        timeouts.append(request.extensions["timeout"])
        return healthy._transport.handle_request(request)

    with httpx.Client(transport=httpx.MockTransport(handler), timeout=60.0) as client:
        macro_history(client, START, END)
    assert {t["read"] for t in timeouts} == {120.0}
    assert {t["connect"] for t in timeouts} == {15.0}


def test_a_slow_fred_is_stopped_by_the_macro_budget(fixtures_dir):
    now = [0.0]
    healthy = sources(fixtures_dir, [])
    asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "fred.stlouisfed.org":
            asked.append(request.url.params["id"])
            now[0] += 200.0  # each series answers, but only after 200 s
        return healthy._transport.handle_request(request)

    assert BUDGET_SECONDS == 20 * 60
    with httpx.Client(transport=httpx.MockTransport(handler)) as client, pytest.raises(
        MacroUnavailable, match=r"FRED did not answer for \w+ within the macro step's 20 minutes"
    ):
        macro_history(client, START, END, sleep=lambda s: None, clock=lambda: now[0])
    assert len(asked) == 6  # the 7th would start at 1200 s


def test_a_refused_series_says_so_rather_than_timing_out(fixtures_dir):
    client, asked = flaky_sources(fixtures_dir, {"DGS10": [httpx.Response(404, text="Series not found")]})
    with client, pytest.raises(MacroRefused, match=r"FRED refused DGS10 \(HTTP 404"):
        macro_history(client, START, END, sleep=lambda s: None)
    assert asked.count("DGS10") == 1
