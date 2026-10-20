import json
from datetime import date

import httpx
import pytest

from advisor.collectors import boc_valet, fred
from advisor.training.macro import COLUMNS, macro_history

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
