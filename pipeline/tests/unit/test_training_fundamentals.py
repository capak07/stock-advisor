import json
import zipfile
from datetime import date

import httpx
import pytest

from advisor.collectors.sec import SecEdgar
from advisor.training.fundamentals import COLUMNS, reduce_companyfacts, universe_ciks

COMPANIES = {"AAPL": 320193, "JPM": 19617, "BRK_B": 1067983, "GOOGL": 1652044}
AGENT = "stock-advisor test@example.com"


def companyfacts(fixtures_dir, name: str) -> dict:
    return json.loads((fixtures_dir / "sec" / f"companyfacts_{name}_trimmed.json").read_text())


@pytest.fixture
def bulk_zip(fixtures_dir, tmp_path):
    """A small companyfacts.zip: SEC's real (trimmed) company JSONs under SEC's entry names."""
    path = tmp_path / "companyfacts.zip"
    with zipfile.ZipFile(path, "w") as archive:
        for name, cik in COMPANIES.items():
            archive.writestr(f"CIK{cik:010d}.json", json.dumps(companyfacts(fixtures_dir, name)))
    return path


def test_the_universes_companies_are_read_from_the_bulk_zip(bulk_zip):
    facts, absent = reduce_companyfacts(bulk_zip, [320193, 19617, 1067983, 999999], date(2016, 1, 1))
    assert list(facts.columns) == COLUMNS
    assert absent == [999999]  # no entry: a company SEC has no XBRL for
    assert facts.groupby("cik").size().to_dict() == {19617: 26, 320193: 148, 1067983: 23}
    assert set(facts["metric"]) >= {"revenue", "net_income", "eps_diluted", "equity"}


def test_every_re_report_keeps_its_own_filing_date(bulk_zip):
    facts, _ = reduce_companyfacts(bulk_zip, [320193], date(2016, 1, 1))
    q2 = facts[(facts["concept"] == "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax")
               & (facts["start"] == date(2024, 9, 29)) & (facts["end"] == date(2025, 3, 29))]
    assert list(zip(q2["filed"], q2["accession"], strict=True)) == [
        (date(2025, 5, 2), "0000320193-25-000057"),  # first reported
        (date(2026, 5, 1), "0000320193-26-000013"),  # repeated a year later as the comparative
    ]
    assert set(q2["value"]) == {219_659_000_000.0}


def test_periods_ending_before_the_history_starts_are_left_out(bulk_zip):
    facts, _ = reduce_companyfacts(bulk_zip, [320193], date(2025, 6, 1))
    assert len(facts) == 112 and facts["end"].min() >= date(2025, 6, 1)


def test_share_classes_map_to_their_company(fixtures_dir):
    payload = json.loads((fixtures_dir / "sec" / "company_tickers.json").read_text())
    mapping = universe_ciks(payload, ["AAPL", "GOOG", "GOOGL", "BRK.B", "BF.B", "SPYX"])
    assert list(mapping.itertuples(index=False, name=None)) == [
        ("AAPL", 320193), ("GOOG", 1652044), ("GOOGL", 1652044), ("BRK.B", 1067983), ("BF.B", 14693),
    ]  # SPYX isn't in SEC's map and is left out


def test_the_bulk_zip_is_streamed_to_disk_with_the_contact(tmp_path):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers["User-Agent"])
        return httpx.Response(200, content=b"PK" + b"\0" * (3 << 20))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        size = SecEdgar(client, AGENT).download("https://www.sec.gov/x.zip", tmp_path / "sub" / "x.zip")
    assert size == (3 << 20) + 2 and (tmp_path / "sub" / "x.zip").stat().st_size == size
    assert seen == [AGENT]


def test_a_dropped_download_is_tried_again(tmp_path):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ReadError("connection reset")
        return httpx.Response(200, content=b"zip")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        sec = SecEdgar(client, AGENT, sleep=lambda s: None)
        assert sec.download("https://www.sec.gov/x.zip", tmp_path / "x.zip") == 3
    assert len(calls) == 2


def test_a_503_download_is_tried_again(tmp_path):
    calls, pauses = [], []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(503) if len(calls) == 1 else httpx.Response(200, content=b"zip")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        sec = SecEdgar(client, AGENT, sleep=pauses.append)
        assert sec.download("https://www.sec.gov/x.zip", tmp_path / "x.zip") == 3
    assert len(calls) == 2 and pauses == [5.0]
    assert (tmp_path / "x.zip").read_bytes() == b"zip"


def test_a_404_download_fails_at_once(tmp_path):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(404)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        sec = SecEdgar(client, AGENT, sleep=lambda s: None)
        with pytest.raises(httpx.HTTPStatusError):
            sec.download("https://www.sec.gov/x.zip", tmp_path / "x.zip")
    assert len(calls) == 1
