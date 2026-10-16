import json
from datetime import UTC, date, datetime

import httpx
import pytest

from advisor.collectors.crypto_fear_greed import CryptoFearGreed, parse_index

AS_OF = datetime(2026, 10, 15, 19, 20, tzinfo=UTC)


def payload(fixtures_dir) -> dict:
    path = fixtures_dir / "alternative" / "alternative_fng_limit30.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_values_are_read_oldest_first(fixtures_dir):
    rows = parse_index(payload(fixtures_dir), AS_OF)
    assert len(rows) == 30
    assert {row.series for row in rows} == {"crypto_fear_greed"}
    assert [(r.day, r.value) for r in rows[-2:]] == [(date(2026, 10, 14), 62.0), (date(2026, 10, 15), 53.0)]


def test_values_after_as_of_are_left_out(fixtures_dir):
    rows = parse_index(payload(fixtures_dir), datetime(2026, 10, 14, 23, 59, tzinfo=UTC))
    assert (len(rows), rows[-1].day) == (29, date(2026, 10, 14))


def test_an_error_answer_is_an_error():
    answer = {"name": "Fear and Greed Index", "data": [], "metadata": {"error": "invalid 'limit' qualifier"}}
    with pytest.raises(ValueError, match="alternative.me: invalid 'limit' qualifier"):
        parse_index(answer, AS_OF)


def test_fetch_asks_for_30_days(fixtures_dir):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url)
        return httpx.Response(200, json=payload(fixtures_dir))

    rows = CryptoFearGreed(httpx.Client(transport=httpx.MockTransport(handler))).fetch([], AS_OF)
    [url] = seen
    assert (url.path, url.params["limit"], url.params["format"]) == ("/fng/", "30", "json")
    assert len(rows) == 30
