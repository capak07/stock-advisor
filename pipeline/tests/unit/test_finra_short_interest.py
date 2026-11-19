from datetime import UTC, date, datetime

import httpx
import pytest

from advisor.collectors.finra_short_interest import (
    FINRA_SHORT_INTEREST_URL,
    FinraShortInterest,
    parse_short_interest,
    settlement_dates,
)
from advisor.symbols import requested_by_key

AS_OF = datetime(2026, 10, 12, 12, 15, tzinfo=UTC)


def fixture_text(fixtures_dir) -> str:
    return (fixtures_dir / "finra" / "shrt20260930.csv").read_text(encoding="utf-8")


def test_settlement_dates_are_mid_month_and_month_end_sessions():
    assert settlement_dates(AS_OF) == [
        date(2026, 9, 30), date(2026, 9, 15), date(2026, 8, 31), date(2026, 8, 14),  # 15 Aug is a Saturday
    ]


def test_parse_maps_symbols_and_converts_fields(fixtures_dir):
    rows = {
        r.symbol: r
        for r in parse_short_interest(fixture_text(fixtures_dir), requested_by_key(["AAPL", "BRK.B", "NOPE"]))
    }
    assert sorted(rows) == ["AAPL", "BRK.B"]
    aapl = rows["AAPL"]
    assert (aapl.settlement_date, aapl.short_interest, aapl.previous_short_interest) == (
        date(2026, 9, 30), 120763539, 128753092,
    )
    assert aapl.avg_daily_volume == 39858260
    assert aapl.days_to_cover == pytest.approx(3.03)
    assert rows["BRK.B"].short_interest == 12370081


def test_days_to_cover_is_none_when_there_is_no_volume():
    header = (
        '"accountingYearMonthNumber"|"symbolCode"|"issueName"|"issuerServicesGroupExchangeCode"|'
        '"marketClassCode"|"currentShortPositionQuantity"|"previousShortPositionQuantity"|'
        '"stockSplitFlag"|"averageDailyVolumeQuantity"|"daysToCoverQuantity"|"revisionFlag"|'
        '"changePercent"|"changePreviousNumber"|"settlementDate"'
    )
    row = '"20260930"|"QUIET"|"Quiet Co"|"A"|"NYSE"|"100"|"90"||"0"|"999.99"||"11.1"|"10"|"2026-09-30"'
    [record] = parse_short_interest(f"{header}\n{row}\n", requested_by_key(["QUIET"]))
    assert record.days_to_cover is None
    assert record.avg_daily_volume == 0


def test_an_unexpected_header_is_rejected():
    header = (
        '"symbolCode"|"previousShortPositionQuantity"|"averageDailyVolumeQuantity"|'
        '"daysToCoverQuantity"|"settlementDate"'
    )  # no currentShortPositionQuantity
    with pytest.raises(ValueError, match="unexpected FINRA short interest header"):
        parse_short_interest(f'{header}\n"AAPL"|"1"|"2"|"3"|"2026-09-30"\n', requested_by_key(["AAPL"]))


def test_an_older_header_with_the_named_columns_still_parses():
    # an extra column and a different order: the named columns are read by name
    header = (
        '"settlementDate"|"extraColumn"|"daysToCoverQuantity"|"averageDailyVolumeQuantity"|'
        '"previousShortPositionQuantity"|"currentShortPositionQuantity"|"symbolCode"'
    )
    row = '"2017-12-29"|"x"|"2.50"|"400"|"900"|"1000"|"OLD"'
    [record] = parse_short_interest(f"{header}\n{row}\n", requested_by_key(["OLD"]))
    assert (record.symbol, record.settlement_date, record.short_interest) == ("OLD", date(2017, 12, 29), 1000)
    assert (record.previous_short_interest, record.avg_daily_volume, record.days_to_cover) == (900, 400, 2.5)


def test_parsing_without_a_wanted_list_keeps_every_finra_symbol(fixtures_dir):
    rows = parse_short_interest(fixture_text(fixtures_dir), None)
    assert {"A", "AA", "AAPL", "BRKB"} <= {r.symbol for r in rows}  # FINRA's own spelling of the share class
    assert len(rows) > len(parse_short_interest(fixture_text(fixtures_dir), requested_by_key(["AAPL"])))


def test_fetch_takes_the_three_newest_published_settlements(fixtures_dir):
    """The newest is under 12 sessions old, so the model reads the second, and its change needs the third
    (Ruling R3, F6)."""
    seen: list[str] = []
    published = {FINRA_SHORT_INTEREST_URL.format(day=d)
                 for d in (date(2026, 9, 15), date(2026, 8, 31), date(2026, 8, 14))}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if str(request.url) in published:
            return httpx.Response(200, text=fixture_text(fixtures_dir))
        return httpx.Response(403, text="AccessDenied")

    collector = FinraShortInterest(httpx.Client(transport=httpx.MockTransport(handler)))
    records = collector.fetch(["AAPL"], AS_OF)
    assert [r.symbol for r in records] == ["AAPL", "AAPL", "AAPL"]
    assert seen == [FINRA_SHORT_INTEREST_URL.format(day=d) for d in (
        date(2026, 9, 30), date(2026, 9, 15), date(2026, 8, 31), date(2026, 8, 14))]


def test_fetch_keeps_what_it_found_and_fails_only_when_nothing_is_published(fixtures_dir):
    published = FINRA_SHORT_INTEREST_URL.format(day=date(2026, 8, 14))

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == published:
            return httpx.Response(200, text=fixture_text(fixtures_dir))
        return httpx.Response(403, text="AccessDenied")

    collector = FinraShortInterest(httpx.Client(transport=httpx.MockTransport(handler)))
    assert [r.symbol for r in collector.fetch(["AAPL"], AS_OF)] == ["AAPL"]
    nothing = FinraShortInterest(httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(403))))
    with pytest.raises(RuntimeError, match="no published FINRA short interest file"):
        nothing.fetch(["AAPL"], AS_OF)
