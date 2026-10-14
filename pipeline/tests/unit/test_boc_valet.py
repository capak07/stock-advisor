import json
from datetime import UTC, date, datetime

import httpx
import pytest

from advisor.collectors.base import PartialFetch
from advisor.collectors.boc_valet import SERIES, BankOfCanadaValet, parse_observations

AS_OF = datetime(2026, 10, 14, 12, 15, tzinfo=UTC)  # 120-day lookback starts 2026-06-16


def payload(fixtures_dir) -> dict:
    path = fixtures_dir / "boc" / "valet_observations_recent10.json"
    return json.loads(path.read_text(encoding="utf-8"))


def serving(handler) -> BankOfCanadaValet:
    return BankOfCanadaValet(httpx.Client(transport=httpx.MockTransport(handler)))


def test_parse_reads_every_series_and_skips_days_without_a_value(fixtures_dir):
    records = parse_observations(payload(fixtures_dir), list(SERIES))
    by_series: dict[str, list] = {}
    for record in records:
        by_series.setdefault(record.series, []).append(record)
    assert {name: len(rows) for name, rows in by_series.items()} == {name: 10 for name in SERIES}
    fx = by_series["FXUSDCAD"]
    assert (fx[-1].day, fx[-1].value) == (date(2026, 10, 13), 1.4222)
    assert date(2026, 10, 12) not in {r.day for r in fx}  # Canadian Thanksgiving: no FX rate
    assert [r.value for r in by_series["V39079"] if r.day == date(2026, 10, 12)] == [2.25]
    assert by_series["BD.CDN.10YR.DQ.YLD"][-1].value == 3.87


def test_fetch_asks_once_for_every_series_since_the_lookback(fixtures_dir):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url)
        return httpx.Response(200, json=payload(fixtures_dir))

    records = serving(handler).fetch([], AS_OF)
    [url] = seen
    assert url.path == "/valet/observations/FXUSDCAD,V39079,BD.CDN.2YR.DQ.YLD,BD.CDN.10YR.DQ.YLD/json"
    assert url.params["start_date"] == "2026-06-16"
    assert len(records) == 40


def test_a_series_with_no_observations_is_a_partial_result(fixtures_dir):
    data = payload(fixtures_dir)
    for observation in data["observations"]:
        observation.pop("BD.CDN.2YR.DQ.YLD", None)
    with pytest.raises(PartialFetch, match="no observations for BD.CDN.2YR.DQ.YLD") as caught:
        serving(lambda request: httpx.Response(200, json=data)).fetch([], AS_OF)
    assert len(caught.value.records) == 30


def test_an_unknown_series_fails_the_source():
    collector = serving(lambda request: httpx.Response(404, json={"message": "Series NOPE not found."}))
    with pytest.raises(httpx.HTTPStatusError, match="HTTP 404"):
        collector.fetch([], AS_OF)
