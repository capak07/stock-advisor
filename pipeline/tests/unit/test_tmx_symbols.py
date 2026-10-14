import json
from datetime import UTC, datetime

import httpx
import pytest

from advisor.collectors.tmx_symbols import (
    DIRECTORY_URL,
    TmxSymbols,
    canonical_symbol,
    keep_instrument,
    parse_directory,
)
from advisor.models import Market

NOW = datetime(2026, 10, 14, 12, 15, tzinfo=UTC)
KEPT = [
    "ASTL.TO", "BCE.TO", "HOM-UN.TO", "RCI-A.TO", "RCI-B.TO", "REI-UN.TO", "RY.TO", "SHOP.TO",
    "TECK-A.TO", "TECK-B.TO",
]


@pytest.fixture
def directory(fixtures_dir) -> dict:
    path = fixtures_dir / "tmx" / "company_directory_trimmed.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_parse_directory_keeps_common_shares_and_reit_units(directory):
    records = parse_directory(directory)
    assert [r.symbol for r in records] == KEPT
    assert {(r.market, r.exchange) for r in records} == {(Market.TSX, "TSX")}
    names = {r.symbol: r.name for r in records}
    assert names["RCI-B.TO"] == "Rogers Communications Inc."
    assert names["HOM-UN.TO"] == "BSR Real Estate Investment Trust"


@pytest.mark.parametrize(
    ("symbol", "instrument", "company", "kept"),
    [
        ("RY", "Royal Bank of Canada", "Royal Bank of Canada", True),
        ("RCI.B", "Rogers Comm Cl B NV", "Rogers Communications Inc.", True),
        ("REI.UN", "RioCan Rl Est Tr Un", "RioCan Real Estate Investment Trust", True),
        ("AD.UN", "Alaris Eq Part Tr Un", "Alaris Equity Partners Income Trust", False),  # not a REIT
        ("CHE.UN", "Chemtrade Logistc Un", "Chemtrade Logistics Income Fund", False),
        ("RY.PR.S", "Royal Bank Pr Ser BO", "Royal Bank of Canada", False),  # preferred
        ("ASTL.WT", "Algoma Steel Grp Wt", "Algoma Steel Group Inc.", False),  # warrant
        ("HOM.U", "BSR REIT Invest USF", "BSR Real Estate Investment Trust", False),  # USD line
        ("XYZ.DB", "XYZ Corp 6% Db", "XYZ Corp", False),  # debenture
        ("BTCQ", "3iQ Bitcoin ETF Un", "3iQ Bitcoin ETF", False),
        ("ABT", "AbbottLab CDR Hgd", "Abbott Labs CDR (CAD Hedged)", False),
        ("DFN", "Dividend 15 Split Cl A", "Dividend 15 Split Corp.", False),
        ("ry", "Royal Bank of Canada", "Royal Bank of Canada", False),
    ],
)
def test_keep_instrument(symbol, instrument, company, kept):
    assert keep_instrument(symbol, instrument, company) is kept


def test_canonical_symbol_is_yahoos_form():
    assert canonical_symbol("RY") == "RY.TO"
    assert canonical_symbol("RCI.B") == "RCI-B.TO"
    assert canonical_symbol("REI.UN") == "REI-UN.TO"


def serving(handler, **kwargs) -> TmxSymbols:
    return TmxSymbols(httpx.Client(transport=httpx.MockTransport(handler)), **kwargs)


def test_fetch_requests_the_directory_once_and_returns_kept_symbols(directory):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json=directory)

    records = serving(handler, min_kept=10).fetch([], NOW)
    assert seen == [DIRECTORY_URL]
    assert [r.symbol for r in records] == KEPT


def test_fetch_requires_three_hundred_kept_symbols_by_default(directory):
    collector = serving(lambda request: httpx.Response(200, json=directory))
    with pytest.raises(ValueError, match="only 10 symbols kept, expected at least 300"):
        collector.fetch([], NOW)


def test_fetch_rejects_an_empty_directory():
    collector = serving(lambda request: httpx.Response(200, json={"length": 0, "results": []}))
    with pytest.raises(ValueError, match="only 0 symbols kept"):
        collector.fetch([], NOW)


def test_fetch_rejects_a_block_page():
    collector = serving(lambda request: httpx.Response(200, text="<html>Access denied</html>"))
    with pytest.raises(ValueError):  # json.JSONDecodeError is a ValueError
        collector.fetch([], NOW)
