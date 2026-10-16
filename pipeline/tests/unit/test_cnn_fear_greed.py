import json
from datetime import UTC, date, datetime

import httpx
import pytest

from advisor.collectors.cnn_fear_greed import CnnFearGreed, parse_history

AFTER_CLOSE = datetime(2026, 10, 15, 19, 20, tzinfo=UTC)


def payload(fixtures_dir) -> dict:
    return json.loads((fixtures_dir / "cnn" / "cnn_graphdata.json").read_text(encoding="utf-8"))


def test_one_reading_per_day_and_the_live_one_wins(fixtures_dir):
    rows = parse_history(payload(fixtures_dir), AFTER_CLOSE)
    assert len(rows) == 29  # 30 points; 2026-10-15 appears at 00:00 UTC and live at 19:12 UTC
    assert (rows[0].day, rows[0].series) == (date(2026, 9, 4), "fear_greed")
    assert (rows[-2].day, rows[-2].value) == (date(2026, 10, 14), 26.6566893424036)
    assert (rows[-1].day, rows[-1].value) == (date(2026, 10, 15), 31.2857142857143)


def test_readings_after_as_of_are_left_out(fixtures_dir):
    rows = parse_history(payload(fixtures_dir), datetime(2026, 10, 15, 12, 15, tzinfo=UTC))
    assert (rows[-1].day, rows[-1].value) == (date(2026, 10, 15), 31.3142857142857)


def test_no_readings_is_an_error(fixtures_dir):
    data = payload(fixtures_dir)
    data["fear_and_greed_historical"]["data"] = []
    with pytest.raises(ValueError, match="no Fear & Greed readings"):
        parse_history(data, AFTER_CLOSE)


def test_fetch_sends_cnns_referer_and_origin(fixtures_dir):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers.get("Referer") != "https://www.cnn.com/" or not request.headers.get("Origin"):
            return httpx.Response(418, text="I'm a teapot. You're a bot.")
        return httpx.Response(200, json=payload(fixtures_dir))

    rows = CnnFearGreed(httpx.Client(transport=httpx.MockTransport(handler))).fetch([], AFTER_CLOSE)
    assert len(rows) == 29


def test_a_bot_answer_fails_the_source():
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(418, text="bot")))
    with pytest.raises(httpx.HTTPStatusError, match="HTTP 418"):
        CnnFearGreed(client).fetch([], AFTER_CLOSE)
