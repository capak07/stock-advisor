from datetime import UTC, datetime

import httpx
import pytest

from advisor.collectors.nasdaq_symbols import (
    NASDAQ_LISTED_URL,
    OTHER_LISTED_URL,
    NasdaqSymbols,
    is_excluded_name,
    parse_nasdaq_listed,
    parse_other_listed,
)
from advisor.models import Market

NOW = datetime(2026, 10, 14, 12, 15, tzinfo=UTC)


def test_parse_nasdaq_listed_keeps_only_common_stocks(fixtures_dir):
    text = (fixtures_dir / "nasdaqlisted.txt").read_text(encoding="utf-8")
    assert [(s.symbol, s.exchange) for s in parse_nasdaq_listed(text)] == [
        ("AAPL", "NASDAQ"),
        ("UAL", "NASDAQ"),   # "United" must not match the "unit" exclusion
        ("PFBC", "NASDAQ"),  # "Preferred Bank" is a common stock
    ]


def test_parse_other_listed_maps_exchanges_and_excludes_etfs_and_preferreds(fixtures_dir):
    text = (fixtures_dir / "otherlisted.txt").read_text(encoding="utf-8")
    assert [(s.symbol, s.exchange) for s in parse_other_listed(text)] == [
        ("BRK.B", "NYSE"),
        ("JPM", "NYSE"),
        ("TSM", "NYSE"),  # ADRs are kept
        ("AAPL", "NYSE"),
        ("ET", "NYSE"),  # LP units with "units representing" are kept
        ("ITUB", "NYSE"),  # ADRs are kept even with preferred in the name
        ("PBR.A", "NYSE"),  # ADRs are kept even with preferred in the name
    ]


def fixture_files(fixtures_dir) -> dict[str, str]:
    return {
        NASDAQ_LISTED_URL: (fixtures_dir / "nasdaqlisted.txt").read_text(encoding="utf-8"),
        OTHER_LISTED_URL: (fixtures_dir / "otherlisted.txt").read_text(encoding="utf-8"),
    }


def serving(files: dict[str, str], **kwargs) -> NasdaqSymbols:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=files[str(request.url)])

    return NasdaqSymbols(httpx.Client(transport=httpx.MockTransport(handler)), **kwargs)


def test_fetch_merges_both_files_sorted_and_deduplicated(fixtures_dir):
    collector = serving(fixture_files(fixtures_dir), min_per_file=1)
    records = collector.fetch([], NOW)
    assert [(r.symbol, r.exchange) for r in records] == [
        ("AAPL", "NASDAQ"),  # the NASDAQ listing wins over the duplicate
        ("BRK.B", "NYSE"),
        ("ET", "NYSE"),
        ("ITUB", "NYSE"),
        ("JPM", "NYSE"),
        ("PBR.A", "NYSE"),
        ("PFBC", "NASDAQ"),
        ("TSM", "NYSE"),
        ("UAL", "NASDAQ"),
    ]
    assert {r.market for r in records} == {Market.US}


def test_fetch_rejects_other_listed_with_header_and_footer_only(fixtures_dir):
    files = fixture_files(fixtures_dir)
    header, *_, footer = files[OTHER_LISTED_URL].splitlines()
    files[OTHER_LISTED_URL] = f"{header}\n{footer}\n"
    with pytest.raises(ValueError, match=r"otherlisted\.txt: only 0 symbols kept, expected at least 1"):
        serving(files, min_per_file=1).fetch([], NOW)


def test_fetch_rejects_empty_other_listed(fixtures_dir):
    files = {**fixture_files(fixtures_dir), OTHER_LISTED_URL: ""}
    with pytest.raises(ValueError, match=r"otherlisted\.txt: missing 'File Creation Time' footer"):
        serving(files, min_per_file=1).fetch([], NOW)


def test_fetch_rejects_nasdaq_listed_without_footer(fixtures_dir):
    files = fixture_files(fixtures_dir)
    files[NASDAQ_LISTED_URL] = "".join(
        line for line in files[NASDAQ_LISTED_URL].splitlines(keepends=True)
        if not line.startswith("File Creation Time")
    )
    with pytest.raises(ValueError, match=r"nasdaqlisted\.txt: missing 'File Creation Time' footer"):
        serving(files, min_per_file=1).fetch([], NOW)


def test_fetch_requires_a_thousand_symbols_per_file_by_default(fixtures_dir):
    with pytest.raises(ValueError, match="only 3 symbols kept, expected at least 1000"):
        serving(fixture_files(fixtures_dir)).fetch([], NOW)


@pytest.mark.parametrize(
    "name,excluded",
    [
        # Excluded: warrants, rights, SPAC units
        ("ABCD Acquisition Corp - Warrant", True),
        ("ABCD Acquisition Corp - Units", True),
        ("ABCD Acquisition Corp - Rights", True),
        ("IQM Quantum Computers Oyj - Warrants to purchase American Depositary Shares", True),
        # Excluded: preferred and debt
        ("JPMorgan Chase & Co. Depositary Shares Series DD Preferred", True),
        ("XYZ Corp 5.75% Series A Preferred Stock", True),
        ("Xcel Energy Inc. - 6.25% Junior Subordinated Notes", True),
        ("Cadiz Inc. Depositary Shares", True),
        # Kept: common stocks despite "preferred" or "united" in name
        ("United Airlines Holdings, Inc. - Common Stock", False),
        ("Preferred Bank - Common Stock", False),
        # Kept: LP units, trust units, and ADRs
        ("Energy Transfer LP Common Units representing limited partner interests", False),
        ("Brookfield Renewable Partners L.P. Limited Partnership Units", False),
        (
            "Itau Unibanco Banco Holding SA American Depositary Shares (Each repstg 500 Preferred shares)",
            False,
        ),
        ("Taiwan Semiconductor Manufacturing Company Ltd. American Depositary Shares", False),
        # Kept: ADRs with units in the name
        ("Banco Santander (Brasil) S.A. American Depositary Shares, each representing one unit", False),
        ("Coca-Cola FEMSA S.A.B. de C.V. American Depositary Shares, each representing 10 Units", False),
        (
            "America Movil S.A.B. de C.V. American Depositary Shares, each representing the right to receive twenty (20) Series B Shares",
            False,
        ),
        # Kept: common stocks with "bond" in the name (not debt context)
        ("Our Bond, Inc. - Common Stock", False),
        ("BlackRock Core Bond Trust Common Shares of Beneficial Interest", False),
        # Excluded: debt with context
        ("Entergy Arkansas, LLC First Mortgage Bonds, 4.875% Series due September 1, 2066", True),
        # Excluded: fractional preferred
        ("Example Corp Depositary Shares, each representing a 1/40th interest in a share of Series A Cumulative Preferred", True),
    ],
)
def test_is_excluded_name(name, excluded):
    assert is_excluded_name(name) is excluded
