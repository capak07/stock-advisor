import io
import json
import zipfile
from datetime import UTC, date, datetime

import httpx
import pytest

from advisor.collectors.openfigi import FigiBook
from advisor.collectors.sec_13f import LISTING_URL, DataSet, Holding, Quarter
from advisor.training.holders_history import (
    HOLDERS_COLUMNS,
    NewestSetMissing,
    cusip_map,
    holders_build,
    holders_history,
)
from fakes import fake_sec

AS_OF = datetime(2026, 11, 19, 14, tzinfo=UTC)
AAPL, MSFT = "037833100", "594918104"
AAPL_FIGIS = ("BBG0000AAPL1", "BBG0000AAPL2")
MSFT_FIGIS = ("BBG0000MSFT1", "BBG0000MSFT2")


def _set(name: str, end: date) -> DataSet:
    return DataSet(name, f"https://www.sec.gov/files/x/{name}_form13f.zip", end)


def test_the_cusip_map_comes_from_the_newest_data_set_with_figis():
    oldest = Quarter(date(2023, 3, 31), {}, {AAPL_FIGIS[1]: ("OLDCUSIP1", 9)})
    older = Quarter(date(2023, 6, 30), {AAPL: Holding(10, 1, 1)}, {AAPL_FIGIS[1]: (AAPL, 3)})
    newer = Quarter(date(2023, 9, 30), {AAPL: Holding(10, 1, 1)}, {})  # an empty FIGI column
    quarters = [  # not in date order: "newest" is the data set's window end
        (_set("2023q4", date(2023, 12, 31)), newer),
        (_set("2023q2", date(2023, 6, 30)), oldest),
        (_set("2023q3", date(2023, 9, 30)), older),
    ]
    figis = {"AAPL": list(AAPL_FIGIS), "MSFT": list(MSFT_FIGIS), "ZZZZ": []}
    assert cusip_map(quarters, figis) == {"AAPL": AAPL}
    assert cusip_map([(_set("2023q4", date(2023, 12, 31)), newer)], figis) == {}


def test_the_history_has_a_row_per_symbol_and_quarter_with_its_known_date():
    quarters = [
        (_set("2018q4", date(2018, 12, 31)), Quarter(date(2018, 9, 30), {AAPL: Holding(100, 5, 3)}, {})),
        (_set("01mar2026-31may2026", date(2026, 5, 31)),
         Quarter(date(2026, 3, 31), {AAPL: Holding(120, 6, 4), MSFT: Holding(7, 1, 1)}, {})),
    ]
    frame = holders_history(quarters, {"AAPL": AAPL, "BRK.B": "084670702"})  # no MSFT: it has no CUSIP
    assert list(frame.columns) == HOLDERS_COLUMNS
    assert frame.to_dict("records") == [
        {"symbol": "AAPL", "cusip": AAPL, "period": date(2018, 9, 30), "known": date(2019, 1, 30),
         "shares": 100, "holders": 3},
        {"symbol": "AAPL", "cusip": AAPL, "period": date(2026, 3, 31), "known": date(2026, 6, 30),
         "shares": 120, "holders": 4},
    ]  # BRK.B's CUSIP has no holdings
    assert holders_history([], {"AAPL": AAPL}).empty


SUBMISSION = ["ACCESSION_NUMBER", "FILING_DATE", "SUBMISSIONTYPE", "CIK", "PERIODOFREPORT"]
COVERPAGE = ["ACCESSION_NUMBER", "REPORTCALENDARORQUARTER", "ISAMENDMENT", "AMENDMENTNO", "AMENDMENTTYPE"]
INFOTABLE = ["ACCESSION_NUMBER", "CUSIP", "FIGI", "VALUE", "SSHPRNAMT", "SSHPRNAMTTYPE", "PUTCALL"]


def _zip(period: str, shares: int, *, figis: bool) -> bytes:
    """One filer's report holding AAPL; an older layout (figis=False) has no FIGI column."""
    info = [c for c in INFOTABLE if figis or c != "FIGI"]
    row = {"ACCESSION_NUMBER": "acc-1", "CUSIP": AAPL, "FIGI": AAPL_FIGIS[1], "VALUE": "1",
           "SSHPRNAMT": str(shares), "SSHPRNAMTTYPE": "SH", "PUTCALL": ""}
    files = {
        "SUBMISSION.tsv": [SUBMISSION, ["acc-1", "14-AUG-2026", "13F-HR", "0000000001", period]],
        "COVERPAGE.tsv": [COVERPAGE, ["acc-1", period, "N", "", ""]],
        "INFOTABLE.tsv": [info, [row[c] for c in info]],
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, lines in files.items():
            archive.writestr(name, "".join("\t".join(line) + "\n" for line in lines))
    return buffer.getvalue()


def _no_infotable() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("SUBMISSION.tsv", "\t".join(SUBMISSION) + "\n")
    return buffer.getvalue()


BASE = "https://www.sec.gov/files/x/"
SETS = {
    "01mar2026-31may2026": _zip("31-MAR-2026", 120, figis=True),
    "2023q4": _zip("30-SEP-2023", 100, figis=False),  # an older layout and a quarterly name
    "2023q3": 404,
    "2023q2": b"not a zip",
    "2023q1": _no_infotable(),
    "2022q4": _zip("30-SEP-2022", 90, figis=False),  # before `since`: never asked for
}


def _routes() -> dict[str, bytes | int]:
    links = "".join(f'<a href="/files/x/{name}_form13f.zip">' for name in SETS)
    return {LISTING_URL: links.encode(), **{f"{BASE}{name}_form13f.zip": body for name, body in SETS.items()}}


def _figi_book(path, asked) -> FigiBook:
    known = {"AAPL": AAPL_FIGIS, "MSFT": MSFT_FIGIS}

    def handler(request):
        jobs = json.loads(request.read())
        asked.append([job["idValue"] for job in jobs])
        return httpx.Response(200, json=[
            {"data": [{"figi": known[j["idValue"]][0], "shareClassFIGI": known[j["idValue"]][1]}]}
            if j["idValue"] in known else {"warning": "No identifier found."}
            for j in jobs
        ])

    return FigiBook(httpx.Client(transport=httpx.MockTransport(handler)), path)


def test_the_build_caches_each_data_set_records_gaps_and_never_prunes(tmp_path):
    folder, figi_path = tmp_path / "sec_13f", tmp_path / "openfigi.json"
    folder.mkdir()
    (folder / "2016q1.json.gz").write_bytes(b"an older quarter's totals")
    seen, asked = [], []
    frame, gaps = holders_build(fake_sec(_routes(), seen=seen), _figi_book(figi_path, asked), folder,
                                ["AAPL", "MSFT", "ZZZZ"], AS_OF, date(2023, 1, 1))
    assert frame[["symbol", "period", "known", "shares"]].to_dict("records") == [
        {"symbol": "AAPL", "period": date(2023, 9, 30), "known": date(2024, 1, 30), "shares": 100},
        {"symbol": "AAPL", "period": date(2026, 3, 31), "known": date(2026, 6, 30), "shares": 120},
    ]  # MSFT has FIGIs but no filer reported them; OpenFIGI doesn't know ZZZZ
    assert sorted(gaps) == ["2023q1", "2023q2", "2023q3"]  # recorded, not raised
    assert f"{BASE}2022q4_form13f.zip" not in [str(r.url) for r in seen]
    assert asked == [["AAPL", "MSFT", "ZZZZ"]]
    assert figi_path.exists()

    seen.clear()
    again, _ = holders_build(fake_sec(_routes(), seen=seen), _figi_book(figi_path, asked), folder,
                             ["AAPL"], AS_OF, date(2023, 1, 1))
    assert again.to_dict("records") == frame.to_dict("records")
    assert [str(r.url).rsplit("/", 1)[-1] for r in seen] == [  # the cached totals are not downloaded again
        "form-13f-data-sets", "2023q3_form13f.zip", "2023q2_form13f.zip", "2023q1_form13f.zip",
    ]
    assert sorted(p.name for p in folder.iterdir()) == [
        "01mar2026-31may2026.json.gz", "2016q1.json.gz", "2023q4.json.gz",
    ]
    assert len(asked) == 1  # the FIGI book is kept


def test_an_empty_build_has_the_history_columns(tmp_path):
    sec = fake_sec({LISTING_URL: b"<html></html>"})
    frame, gaps = holders_build(sec, _figi_book(tmp_path / "f.json", []), tmp_path, ["AAPL"], AS_OF,
                                date(2023, 1, 1))
    assert list(frame.columns) == HOLDERS_COLUMNS and frame.empty and gaps == {}


def test_the_build_counts_the_symbols_openfigi_failed_and_mapped(tmp_path):
    def refuse(request):
        return httpx.Response(400, text="bad request")

    figis = FigiBook(httpx.Client(transport=httpx.MockTransport(refuse)), tmp_path / "openfigi.json")
    counts: dict = {}
    frame, gaps = holders_build(fake_sec(_routes()), figis, tmp_path / "sec_13f", ["AAPL", "MSFT", "AAPL"], AS_OF,
                                date(2026, 1, 1), counts=counts)
    assert frame.empty  # no FIGIs, so no CUSIPs: recorded, not raised
    assert counts == {"asked": 2, "figi_failed": 2, "mapped": 0, "with_holdings": 0, "data_sets": 1, "gaps": 0}
    counts = {}
    holders_build(fake_sec(_routes()), _figi_book(tmp_path / "f.json", []), tmp_path / "sec_13f", ["AAPL", "MSFT"],
                  AS_OF, date(2026, 1, 1), counts=counts)
    assert counts == {"asked": 2, "figi_failed": 0, "mapped": 1, "with_holdings": 1, "data_sets": 1, "gaps": 0}


def test_a_gap_on_the_newest_data_set_fails_the_build(tmp_path):
    """Older gaps are recorded; without the newest set every symbol's latest quarter-on-quarter pair is
    missing and the CUSIP map has no source, so the group fails (and the history job reports it)."""
    routes = {**_routes(), f"{BASE}01mar2026-31may2026_form13f.zip": 404}
    with pytest.raises(NewestSetMissing, match="01mar2026-31may2026"):
        holders_build(fake_sec(routes), _figi_book(tmp_path / "f.json", []), tmp_path / "sec_13f", ["AAPL"],
                      AS_OF, date(2023, 1, 1))
