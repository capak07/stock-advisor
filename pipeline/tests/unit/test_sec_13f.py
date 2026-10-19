import gzip
import io
import json
import time
import zipfile
from datetime import UTC, date, datetime

import httpx
import pytest

from advisor.collectors.base import DeadlineExceeded, PartialFetch, deadline
from advisor.collectors.openfigi import FigiBook
from advisor.collectors.sec_13f import (
    LISTING_URL,
    DataSet,
    Holding,
    InstitutionalOwnership,
    Quarter,
    Sec13f,
    _Report,
    aggregate,
    counted_reports,
    load_quarter,
    parse_listing,
    save_quarter,
)
from fakes import fake_sec

AS_OF = datetime(2026, 10, 19, 14, tzinfo=UTC)
AAPL, MSFT, BRKB = "037833100", "594918104", "084670702"
AAPL_FIGIS = ("BBG000B9XRY4", "BBG001S5N8V8")  # composite and share class
MSFT_FIGIS = ("BBG000BPH459", "BBG001S5TD05")
BRKB_FIGIS = ("BBG000DWG505", "BBG001S90346")

SUBMISSION = ["ACCESSION_NUMBER", "FILING_DATE", "SUBMISSIONTYPE", "CIK", "PERIODOFREPORT"]
COVERPAGE = ["ACCESSION_NUMBER", "REPORTCALENDARORQUARTER", "ISAMENDMENT", "AMENDMENTNO", "AMENDMENTTYPE",
             "FILINGMANAGER_NAME", "REPORTTYPE"]
INFOTABLE = ["ACCESSION_NUMBER", "INFOTABLE_SK", "NAMEOFISSUER", "TITLEOFCLASS", "CUSIP", "FIGI", "VALUE",
             "SSHPRNAMT", "SSHPRNAMTTYPE", "PUTCALL", "INVESTMENTDISCRETION", "OTHERMANAGER",
             "VOTING_AUTH_SOLE", "VOTING_AUTH_SHARED", "VOTING_AUTH_NONE"]


def tsv(header, rows) -> str:
    return "\n".join("\t".join(r) for r in [header, *rows]) + "\n"


def data_set(submissions, amendments, holdings) -> bytes:
    """A 13F data set ZIP.

    submissions: (accession, filed, type, cik, period); amendments: accession -> type;
    holdings: (accession, cusip, figi, shares, value, kind, put_call).
    """
    covers = [
        (a, p, "Y" if a in amendments else "N", "1" if a in amendments else "", amendments.get(a, ""),
         f"Manager {c}", "13F HOLDINGS REPORT")
        for a, _, _, c, p in submissions
    ]
    infos = [
        (a, str(i), "ISSUER", "COM", cusip, figi, str(value), str(shares), kind, put_call, "SOLE", "",
         str(shares), "0", "0")
        for i, (a, cusip, figi, shares, value, kind, put_call) in enumerate(holdings)
    ]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("SUBMISSION.tsv", tsv(SUBMISSION, submissions))
        archive.writestr("COVERPAGE.tsv", tsv(COVERPAGE, covers))
        archive.writestr("INFOTABLE.tsv", tsv(INFOTABLE, infos))
    return buffer.getvalue()


def quarter_zip(period: str, aapl_shares: int, *, msft_holders: int = 1) -> bytes:
    """A plain quarter: filer 1 holds AAPL, and `msft_holders` filers hold 10 MSFT each."""
    submissions = [("0000000001-26-000001", "14-AUG-2026", "13F-HR", "0000000001", period)]
    holdings = [("0000000001-26-000001", AAPL, AAPL_FIGIS[1], aapl_shares, aapl_shares * 250, "SH", "")]
    for n in range(2, 2 + msft_holders):
        accession = f"00000000{n:02d}-26-000001"
        submissions.append((accession, "14-AUG-2026", "13F-HR", f"00000000{n:02d}", period))
        holdings.append((accession, MSFT, MSFT_FIGIS[0], 10, 5000, "SH", ""))
    return data_set(submissions, {}, holdings)


def test_the_listing_gives_the_data_sets_newest_window_first(fixtures_dir):
    html = (fixtures_dir / "sec" / "form13f_listing.html").read_text(encoding="utf-8")
    assert parse_listing(html) == [  # the quarter-named 2023q4 file isn't a window and is skipped
        DataSet(
            "01jun2026-31aug2026",
            "https://www.sec.gov/files/datastandardsinnovation/data/form-13f-data-sets/01jun2026-31aug2026_form13f.zip",
            date(2026, 8, 31),
        ),
        DataSet(
            "01mar2026-31may2026",
            "https://www.sec.gov/files/structureddata/data/form-13f-data-sets/01mar2026-31may2026_form13f.zip",
            date(2026, 5, 31),
        ),
        DataSet(
            "01dec2025-28feb2026",
            "https://www.sec.gov/files/structureddata/data/form-13f-data-sets/01dec2025-28feb2026_form13f.zip",
            date(2026, 2, 28),
        ),
    ]


def report(accession, cik, kind, day):
    return _Report(accession, cik, kind, date(2026, 8, day))


def test_a_restatement_replaces_the_report_and_later_new_holdings_add_to_it():
    counted = counted_reports([
        report("a1", "A", "13F-HR", 10), report("a2", "A", "NEW HOLDINGS", 11),  # A: both count
        report("b1", "B", "13F-HR", 10), report("b2", "B", "NEW HOLDINGS", 11),
        report("b3", "B", "RESTATEMENT", 12), report("b4", "B", "NEW HOLDINGS", 13),  # B: b3 and b4
        report("c1", "C", "13F-HR", 10), report("c2", "C", "13F-HR", 12),  # C filed twice: the latest
        report("d1", "D", "NEW HOLDINGS", 12),  # D's report was filed in another window
    ])
    assert counted == {"a1": "A", "a2": "A", "b3": "B", "b4": "B", "c2": "C"}


def test_a_data_set_totals_the_quarters_shares_per_cusip():
    archive = data_set(
        [
            ("acc-a", "10-AUG-2026", "13F-HR", "A", "30-JUN-2026"),
            ("acc-b", "11-AUG-2026", "13F-HR", "B", "30-JUN-2026"),
            ("acc-b2", "20-AUG-2026", "13F-HR/A", "B", "30-JUN-2026"),  # restates B's report
            ("acc-c", "12-AUG-2026", "13F-HR", "C", "31-MAR-2026"),  # a late report for Q1
            ("acc-d", "13-AUG-2026", "13F-NT", "D", "30-JUN-2026"),  # a notice: no holdings
        ],
        {"acc-b2": "RESTATEMENT"},
        [
            ("acc-a", AAPL, AAPL_FIGIS[1], 100, 25_000, "SH", ""),
            ("acc-a", AAPL, AAPL_FIGIS[0], 50, 12_500, "SH", ""),  # the same filer again: one holder
            ("acc-a", AAPL, "", 1_000, 1, "SH", "Call"),  # an option: left out
            ("acc-a", MSFT, "US5949181045", 7, 3_500, "SH", ""),  # an ISIN in the FIGI column: no vote
            ("acc-a", "88160RAG6", "", 5_000, 5_000, "PRN", ""),  # debt: left out
            ("acc-b", AAPL, AAPL_FIGIS[1], 999, 1, "SH", ""),  # restated away
            ("acc-b2", AAPL, AAPL_FIGIS[1], 40, 10_000, "SH", ""),
            ("acc-c", AAPL, AAPL_FIGIS[1], 70, 17_500, "SH", ""),  # another quarter
            ("acc-c", MSFT, AAPL_FIGIS[1], 70, 17_500, "SH", ""),  # a filer's wrong FIGI: outvoted
        ],
    )
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        quarter = aggregate(z)
    assert quarter.period == date(2026, 6, 30)
    assert quarter.holdings == {AAPL: Holding(190, 47_500, 2), MSFT: Holding(7, 3_500, 1)}
    assert quarter.figis == {AAPL_FIGIS[1]: (AAPL, 4), AAPL_FIGIS[0]: (AAPL, 1)}
    assert quarter.cusip_for([*AAPL_FIGIS, "BBG000NOTSEEN"]) == AAPL
    assert quarter.cusip_for(["BBG000NOTSEEN"]) is None


def test_the_run_deadline_stops_a_long_aggregation():
    with zipfile.ZipFile(io.BytesIO(quarter_zip("30-JUN-2026", 120))) as z, deadline(time.monotonic() - 1):
        with pytest.raises(DeadlineExceeded):
            aggregate(z)


def test_a_quarters_totals_survive_the_trip_to_disk(tmp_path):
    quarter = Quarter(date(2026, 6, 30), {AAPL: Holding(190, 47_500, 2)}, {AAPL_FIGIS[1]: (AAPL, 4)})
    save_quarter(tmp_path / "q.json.gz", quarter)
    assert load_quarter(tmp_path / "q.json.gz") == quarter


LATEST = "https://www.sec.gov/files/datastandardsinnovation/data/form-13f-data-sets/01jun2026-31aug2026_form13f.zip"
PREVIOUS = "https://www.sec.gov/files/structureddata/data/form-13f-data-sets/01mar2026-31may2026_form13f.zip"


def openfigi_client(asked, *, fail=False):
    figis = {"AAPL": AAPL_FIGIS, "MSFT": MSFT_FIGIS, "BRK/B": BRKB_FIGIS}

    def handler(request):
        jobs = json.loads(request.read())
        asked.append([job["idValue"] for job in jobs])
        if fail:
            return httpx.Response(400, text="bad request")
        return httpx.Response(200, json=[
            {"data": [{"figi": figis[j["idValue"]][0], "compositeFIGI": figis[j["idValue"]][0],
                       "shareClassFIGI": figis[j["idValue"]][1]}]}
            if j["idValue"] in figis else {"warning": "No identifier found."}
            for j in jobs
        ])

    return httpx.Client(transport=httpx.MockTransport(handler))


def collector(fixtures_dir, folder, seen, asked, *, fail=False):
    routes = {
        LISTING_URL: (fixtures_dir / "sec" / "form13f_listing.html").read_bytes(),
        LATEST: quarter_zip("30-JUN-2026", 120, msft_holders=3),
        PREVIOUS: quarter_zip("31-MAR-2026", 100),
    }
    figis = FigiBook(openfigi_client(asked, fail=fail), folder / "figis.json")
    return Sec13f(fake_sec(routes, seen=seen), figis, folder)


def test_symbols_get_the_latest_quarter_and_the_one_before(fixtures_dir, tmp_path):
    seen, asked = [], []
    records = collector(fixtures_dir, tmp_path, seen, asked).fetch(["AAPL", "MSFT", "BRK.B", "ZZZZ"], AS_OF)
    assert records == [
        InstitutionalOwnership(
            symbol="AAPL", cusip=AAPL, period=date(2026, 6, 30), shares=120, value_usd=30_000, holders=1,
            previous_period=date(2026, 3, 31), previous_shares=100, previous_holders=1,
        ),
        InstitutionalOwnership(
            symbol="MSFT", cusip=MSFT, period=date(2026, 6, 30), shares=30, value_usd=15_000, holders=3,
            previous_period=date(2026, 3, 31), previous_shares=10, previous_holders=1,
        ),
    ]  # no filer gave BRK.B's FIGIs, and OpenFIGI doesn't know ZZZZ
    assert asked == [["AAPL", "MSFT", "BRK/B", "ZZZZ"]]
    assert [str(r.url) for r in seen] == [LISTING_URL, LATEST, PREVIOUS]
    assert all(r.headers["User-Agent"] == "stock-advisor test@example.com" for r in seen)


def test_a_data_set_is_downloaded_once_and_old_totals_are_dropped(fixtures_dir, tmp_path):
    (tmp_path / "01sep2025-30nov2025.json.gz").write_bytes(b"an older quarter")
    seen, asked = [], []
    collector(fixtures_dir, tmp_path, seen, asked).fetch(["AAPL"], AS_OF)
    seen.clear()
    assert collector(fixtures_dir, tmp_path, seen, asked).fetch(["AAPL"], AS_OF)[0].shares == 120
    assert [str(r.url) for r in seen] == [LISTING_URL]  # the listing only
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "01jun2026-31aug2026.json.gz", "01mar2026-31may2026.json.gz", "figis.json",
    ]


DAMAGED = [
    b"cut short by a full disk",
    gzip.compress(b'{"period": "2026-06-30"}')[:-6],  # a truncated gzip
    gzip.compress(b"[]"),
    gzip.compress(b"{}"),
    gzip.compress(json.dumps({"period": "2026-06-30", "holdings": {AAPL: [1]}, "figis": {}}).encode()),
]


@pytest.mark.parametrize(
    "damaged", DAMAGED, ids=["not-gzip", "truncated-gzip", "json-list", "json-empty-object", "short-holding"]
)
def test_damaged_totals_on_disk_are_rebuilt_from_the_data_set(fixtures_dir, tmp_path, damaged):
    (tmp_path / "01jun2026-31aug2026.json.gz").write_bytes(damaged)
    seen = []
    records = collector(fixtures_dir, tmp_path, seen, []).fetch(["AAPL"], AS_OF)
    assert records[0].shares == 120
    assert LATEST in [str(r.url) for r in seen]


def test_an_openfigi_failure_keeps_the_symbols_it_could_match(fixtures_dir, tmp_path):
    collector(fixtures_dir, tmp_path, [], []).fetch(["AAPL"], AS_OF)
    with pytest.raises(PartialFetch, match="OpenFIGI failed for 1 symbols") as raised:
        collector(fixtures_dir, tmp_path, [], [], fail=True).fetch(["AAPL", "MSFT"], AS_OF)
    assert [r.symbol for r in raised.value.records] == ["AAPL"]


def test_a_listing_with_fewer_than_two_data_sets_fails(tmp_path):
    sec = fake_sec({LISTING_URL: b'<a href="/files/x/01jun2026-31aug2026_form13f.zip">'})
    with pytest.raises(ValueError, match="names 1 data sets"):
        Sec13f(sec, FigiBook(openfigi_client([]), tmp_path / "figis.json"), tmp_path).fetch(["AAPL"], AS_OF)
