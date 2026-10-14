from datetime import UTC, date, datetime

import httpx
import pytest

from advisor.collectors.finra_short_volume import (
    FINRA_SHORT_VOLUME_URL,
    FinraShortVolume,
    candidate_days,
    parse_short_volume,
)
from advisor.models import Market
from advisor.symbols import requested_by_key, symbol_key

MONDAY_PRE_OPEN = datetime(2026, 10, 12, 12, 15, tzinfo=UTC)  # 08:15 ET
TUESDAY_PRE_OPEN = datetime(2026, 10, 13, 12, 15, tzinfo=UTC)


def fixture_text(fixtures_dir) -> str:
    return (fixtures_dir / "finra" / "CNMSshvol20261009.txt").read_text(encoding="utf-8")


def client_serving(responses: dict[str, httpx.Response], seen: list[str]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return responses.get(str(request.url), httpx.Response(403, text="AccessDenied"))

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_symbol_key_ignores_share_class_separators():
    assert {symbol_key(s) for s in ("BRK.B", "BRK/B", "BRK-B", "brkb")} == {"BRKB"}
    assert requested_by_key(["BRK.B", "AAPL"]) == {"BRKB": "BRK.B", "AAPL": "AAPL"}


def test_finra_covers_only_us_stocks():
    assert FinraShortVolume.markets == frozenset({Market.US})


def test_candidate_days_skip_weekends_and_wait_for_publication():
    assert candidate_days(MONDAY_PRE_OPEN) == [
        date(2026, 10, 9), date(2026, 10, 8), date(2026, 10, 7), date(2026, 10, 6), date(2026, 10, 5),
    ]
    monday_evening = datetime(2026, 10, 12, 22, 45, tzinfo=UTC)  # 18:45 ET, after publication
    assert candidate_days(monday_evening)[0] == date(2026, 10, 12)


def test_parse_maps_provider_symbols_and_skips_header_and_trailer(fixtures_dir):
    wanted = requested_by_key(["AAPL", "BRK.B", "BF.B", "NOPE"])
    rows = {r.symbol: r for r in parse_short_volume(fixture_text(fixtures_dir), wanted)}
    assert sorted(rows) == ["AAPL", "BF.B", "BRK.B"]
    aapl = rows["AAPL"]
    assert aapl.trade_date == date(2026, 10, 9)
    assert aapl.short_volume == pytest.approx(9011284.413782)
    assert aapl.total_volume == pytest.approx(15300955.899485)
    assert rows["BRK.B"].short_volume == pytest.approx(691652.708894)


def test_fetch_falls_back_from_an_unpublished_day(fixtures_dir):
    seen: list[str] = []
    published = FINRA_SHORT_VOLUME_URL.format(day=date(2026, 10, 9))
    collector = FinraShortVolume(
        client_serving({published: httpx.Response(200, text=fixture_text(fixtures_dir))}, seen)
    )
    records = collector.fetch(["AAPL"], TUESDAY_PRE_OPEN)
    assert [r.symbol for r in records] == ["AAPL"]
    assert seen == [FINRA_SHORT_VOLUME_URL.format(day=date(2026, 10, 12)), published]


def test_fetch_gives_up_after_the_lookback():
    collector = FinraShortVolume(client_serving({}, []))
    with pytest.raises(RuntimeError, match="no FINRA short volume file"):
        collector.fetch(["AAPL"], TUESDAY_PRE_OPEN)


def test_other_http_errors_are_not_treated_as_unpublished():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="bad request")

    collector = FinraShortVolume(httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(httpx.HTTPStatusError):
        collector.fetch(["AAPL"], TUESDAY_PRE_OPEN)
