from datetime import date

import httpx
import pandas as pd
import pytest

from advisor.collectors.finra_short_interest import FINRA_SHORT_INTEREST_URL
from advisor.collectors.finra_short_volume import FINRA_SHORT_VOLUME_URL
from advisor.training.finra_history import (
    FINRA_CACHE_AFTER_DAYS,
    PARTITIONS_URL,
    UNPUBLISHED_GRACE_DAYS,
    FinraMissing,
    settlement_dates,
    short_interest_history,
    short_volume_history,
)

TODAY = date(2026, 11, 19)
INTEREST_HEADER = (
    '"accountingYearMonthNumber"|"symbolCode"|"issueName"|"issuerServicesGroupExchangeCode"|'
    '"marketClassCode"|"currentShortPositionQuantity"|"previousShortPositionQuantity"|'
    '"stockSplitFlag"|"averageDailyVolumeQuantity"|"daysToCoverQuantity"|"revisionFlag"|'
    '"changePercent"|"changePreviousNumber"|"settlementDate"'
)


def interest_file(day: str) -> str:
    rows = [
        f'"{day[:4]}{day[5:7]}"|"AAPL"|"Apple"|"A"|"NASDAQ"|"1000"|"900"||"500"|"2.00"||"1"|"1"|"{day}"',
        f'"{day[:4]}{day[5:7]}"|"BRKB"|"Berkshire B"|"A"|"NYSE"|"300"|"250"||"0"|"999.99"||"1"|"1"|"{day}"',
        f'"{day[:4]}{day[5:7]}"|"ZZZZ"|"Other"|"A"|"NYSE"|"7"|"6"||"7"|"1.00"||"1"|"1"|"{day}"',
    ]
    return "\n".join([INTEREST_HEADER, *rows]) + "\n"


def volume_file(day: str) -> str:
    stamp = day.replace("-", "")
    return (
        "Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market\n"
        f"{stamp}|AAPL|40|0|100|Q\n{stamp}|BRK/B|10|0|50|N\n{stamp}|ZZZZ|1|0|2|N\n"
        "3|\n"
    )


class FakeCache:
    def __init__(self) -> None:
        self.store: dict[tuple[str, str], pd.DataFrame] = {}

    def get(self, kind: str, key: str):
        return self.store.get((kind, key))

    def put(self, kind: str, key: str, frame: pd.DataFrame) -> None:
        self.store[(kind, key)] = frame


def client_serving(files: dict[str, str], seen: list[str], status: int = 403) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        text = files.get(str(request.url))
        return httpx.Response(200, text=text) if text is not None else httpx.Response(status, text="AccessDenied")

    return httpx.Client(transport=httpx.MockTransport(handler))


def interest_url(day: str) -> str:
    return FINRA_SHORT_INTEREST_URL.format(day=date.fromisoformat(day))


def volume_url(day: str) -> str:
    return FINRA_SHORT_VOLUME_URL.format(day=date.fromisoformat(day))


def test_settlement_dates_read_the_partitions_api():
    payload = {"availablePartitions": [{"partitions": ["2026-10-30"]}, {"partitions": ["2017-12-29"]}]}

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == PARTITIONS_URL
        return httpx.Response(200, json=payload)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert settlement_dates(client) == [date(2017, 12, 29), date(2026, 10, 30)]


def test_the_history_maps_finra_symbols_to_the_universe():
    seen: list[str] = []
    client = client_serving({
        interest_url("2026-10-15"): interest_file("2026-10-15"),
        volume_url("2026-11-12"): volume_file("2026-11-12"),
    }, seen)
    interest = short_interest_history(client, [date(2026, 10, 15)], ["AAPL", "BRK.B"], None, None, TODAY)
    assert sorted(interest["symbol"]) == ["AAPL", "BRK.B"]  # FINRA's BRKB, and ZZZZ is not in the universe
    brk = interest[interest["symbol"] == "BRK.B"].iloc[0]
    assert (brk["settlement"], brk["short_interest"]) == (date(2026, 10, 15), 300)
    assert pd.isna(brk["days_to_cover"])  # FINRA's 999.99 with no volume
    assert interest["short_interest"].dtype == "int64" and interest["days_to_cover"].dtype == "float64"
    volume = short_volume_history(client, [date(2026, 11, 12)], ["AAPL", "BRK.B"], None, None, TODAY)
    assert sorted(volume["symbol"]) == ["AAPL", "BRK.B"]  # FINRA's BRK/B
    assert volume[volume["symbol"] == "BRK.B"].iloc[0]["total_volume"] == 50.0
    assert list(volume.columns) == ["symbol", "day", "short_volume", "total_volume"]
    assert list(interest.columns) == ["symbol", "settlement", "short_interest", "avg_daily_volume", "days_to_cover"]


def test_a_recent_unpublished_day_is_skipped():
    seen: list[str] = []
    client = client_serving({volume_url("2026-11-13"): volume_file("2026-11-13")}, seen)  # 11-16 answers 403
    days = [date(2026, 11, 13), date(2026, 11, 16)]  # 11-16 is 3 days before TODAY: maybe not out yet
    volume = short_volume_history(client, days, ["AAPL"], None, None, TODAY)
    assert volume["day"].tolist() == [date(2026, 11, 13)]
    assert seen == [volume_url("2026-11-13"), volume_url("2026-11-16")]
    assert UNPUBLISHED_GRACE_DAYS == 3


@pytest.mark.parametrize("status", [403, 404])
def test_an_older_session_finra_does_not_serve_is_a_failure_not_unpublished(status):
    client = client_serving({}, [], status=status)
    with pytest.raises(FinraMissing, match="2026-11-13"):  # 6 days old: an outage or a removed file
        short_volume_history(client, [date(2026, 11, 13)], ["AAPL"], None, None, TODAY)


@pytest.mark.parametrize("status", [403, 404])
def test_a_listed_settlement_finra_does_not_serve_is_a_failure(status):
    """Every settlement date comes from FINRA's partitions API, so a file it lists is published."""
    client = client_serving({}, [], status=status)
    with pytest.raises(FinraMissing, match="2026-11-14"):
        short_interest_history(client, [date(2026, 11, 14)], ["AAPL"], None, None, TODAY)


def test_other_http_errors_are_not_skipped():
    client = client_serving({}, [], status=400)
    with pytest.raises(httpx.HTTPStatusError):
        short_volume_history(client, [date(2026, 11, 12)], ["AAPL"], None, None, TODAY)


def test_a_cached_file_holds_every_finra_symbol_and_maps_on_read():
    seen: list[str] = []
    old, recent = "2017-12-29", "2026-10-30"
    client = client_serving({interest_url(old): interest_file(old), interest_url(recent): interest_file(recent)}, seen)
    cache = FakeCache()
    first = short_interest_history(client, [date.fromisoformat(old), date.fromisoformat(recent)],
                                   ["AAPL"], cache, None, TODAY)
    assert sorted(first["symbol"]) == ["AAPL", "AAPL"]
    assert set(cache.store) == {("finra_interest", old)}  # the file within 90 days is not put
    assert sorted(cache.store[("finra_interest", old)]["symbol"]) == ["AAPL", "BRKB", "ZZZZ"]  # whole, FINRA's names
    seen.clear()
    second = short_interest_history(client, [date.fromisoformat(old)], ["AAPL", "BRK.B"], cache, None, TODAY)
    assert seen == []  # no request
    assert sorted(second["symbol"]) == ["AAPL", "BRK.B"]
    assert FINRA_CACHE_AFTER_DAYS == 90 and (TODAY - date.fromisoformat(recent)).days <= FINRA_CACHE_AFTER_DAYS


def test_a_cached_volume_file_maps_on_read_and_a_recent_file_is_not_put():
    seen: list[str] = []
    old, recent = "2018-08-01", "2026-11-12"
    client = client_serving({volume_url(old): volume_file(old), volume_url(recent): volume_file(recent)}, seen)
    cache = FakeCache()
    short_volume_history(client, [date.fromisoformat(old), date.fromisoformat(recent)], ["AAPL"], cache, None, TODAY)
    assert set(cache.store) == {("finra_volume", old)}
    assert sorted(cache.store[("finra_volume", old)]["symbol"]) == ["AAPL", "BRK/B", "ZZZZ"]
    seen.clear()
    again = short_volume_history(client, [date.fromisoformat(old)], ["BRK.B"], cache, None, TODAY)
    assert seen == [] and again["symbol"].tolist() == ["BRK.B"]


def test_a_file_exactly_ninety_days_old_is_not_cached_yet():
    day = "2026-08-21"  # 90 days before TODAY
    client = client_serving({volume_url(day): volume_file(day)}, [])
    cache = FakeCache()
    short_volume_history(client, [date.fromisoformat(day)], ["AAPL"], cache, None, TODAY)
    assert cache.store == {}


def test_each_finra_symbol_is_keyed_once_across_files(monkeypatch):
    import advisor.training.finra_history as finra_history

    keyed: list[str] = []
    real = finra_history.symbol_key

    def counting(symbol: str) -> str:
        keyed.append(symbol)
        return real(symbol)

    monkeypatch.setattr(finra_history, "symbol_key", counting)
    days = ["2026-11-10", "2026-11-11", "2026-11-12"]
    client = client_serving({volume_url(day): volume_file(day) for day in days}, [])
    volume = short_volume_history(client, [date.fromisoformat(d) for d in days], ["AAPL", "BRK.B"], None, None, TODAY)
    assert sorted(keyed) == ["AAPL", "BRK/B", "ZZZZ"]  # three files, each symbol keyed once
    assert len(volume) == 6 and sorted(set(volume["symbol"])) == ["AAPL", "BRK.B"]
