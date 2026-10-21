import pytest

from advisor.models import Market
from advisor.training.sectors import (
    PAGE,
    SECTOR_ETFS,
    ScreenerRefused,
    classify,
    industries,
    screen_industries,
    sector_etf,
)


def test_every_us_sector_has_its_spdr_fund_and_tsx_falls_back_to_its_benchmark():
    assert len(SECTOR_ETFS[Market.US]) == 11
    assert sector_etf(Market.US, "Technology") == "XLK"
    assert sector_etf(Market.TSX, "Energy") == "XEG.TO"
    assert sector_etf(Market.TSX, "Industrials") == "XIU.TO"  # no iShares TSX industrials fund
    assert sector_etf(Market.US, None) == "SPY"  # unclassified


def test_yfinance_lists_the_industries_of_the_eleven_sectors():
    by_industry = industries()
    assert len(by_industry) >= 140
    assert set(by_industry.values()) == set(SECTOR_ETFS[Market.US])
    assert by_industry["Gold"] == "Basic Materials"


def test_each_industry_is_screened_per_market_and_paged_to_the_end():
    asked = []

    def query(industry, market):
        return (industry, market)

    def screen(q, offset):
        asked.append((q, offset))
        industry, market = q
        if industry == "Banks" and market is Market.US:
            return [f"B{offset + i}" for i in range(PAGE if offset == 0 else 3)]
        return ["RY.TO"] if industry == "Banks" else ["AAPL"]

    found = screen_industries(
        {"Banks": "Financial Services", "Consumer Electronics": "Technology"},
        screen=screen, query=query, sleep=lambda s: None,
    )
    assert [(q[0], q[1].value, o) for q, o in asked] == [
        ("Banks", "US", 0), ("Banks", "US", PAGE), ("Banks", "TSX", 0),
        ("Consumer Electronics", "US", 0), ("Consumer Electronics", "TSX", 0),
    ]
    assert found["B252"] == ("Financial Services", "Banks")
    assert found["RY.TO"] == ("Financial Services", "Banks")
    assert found["AAPL"] == ("Technology", "Consumer Electronics")


def test_a_refusing_screener_fails_rather_than_leaving_the_universe_unclassified():
    def screen(q, offset):
        raise RuntimeError("401 Unauthorized")

    with pytest.raises(ScreenerRefused, match=r"4 of 4.*; first: RuntimeError: 401 Unauthorized"):
        screen_industries({"Banks": "Financial Services", "Gold": "Basic Materials"},
                          screen=screen, query=lambda i, m: i, sleep=lambda s: None)


def test_the_universe_is_matched_in_yahoos_form():
    found = {"BRK-B": ("Financial Services", "Insurance—Diversified"), "RCI-B.TO": ("Communication Services", "Telecom Services")}
    frame = classify(["BRK.B", "RCI-B.TO", "ODD"], found)
    assert list(frame.itertuples(index=False, name=None)) == [
        ("BRK.B", "Financial Services", "Insurance—Diversified"),
        ("RCI-B.TO", "Communication Services", "Telecom Services"),
        ("ODD", None, None),
    ]
