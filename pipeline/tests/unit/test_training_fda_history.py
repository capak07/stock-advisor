import io
import json
import zipfile
from datetime import date

import httpx

from advisor.training.fda_history import DOWNLOAD_URL, EVENT_COLUMNS, fda_history

APPROVALS_FILE = "https://download.open.fda.gov/drug/drugsfda/drug-drugsfda-0001-of-0001.json.zip"
RECALLS_FILE = "https://download.open.fda.gov/drug/enforcement/drug-enforcement-0001-of-0001.json.zip"
LISTING = {"results": {"drug": {
    "drugsfda": {"partitions": [{"file": APPROVALS_FILE}]},
    "enforcement": {"partitions": [{"file": RECALLS_FILE}]},
}}}
NAMES = {
    "PFE": "Pfizer, Inc. Common Stock",
    "MRK": "Merck & Company, Inc. Common Stock",
    "BRKA": "Berkshire Hathaway Inc. Class A Common Stock",
    "BRKB": "Berkshire Hathaway Inc. Class B Common Stock",
    "ALPHA": "Zeta Biologics Inc. Common Stock",
    "BETA": "Zeta Pharma Holdings Inc. Common Stock",
}
SINCE = date(2018, 1, 1)


def _zip(records: list[dict]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("data.json", json.dumps({"meta": {}, "results": records}))
    return buffer.getvalue()


def _client(approvals: list[dict], recalls: list[dict], asked: list[str] | None = None) -> httpx.Client:
    bodies = {APPROVALS_FILE: _zip(approvals), RECALLS_FILE: _zip(recalls)}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if asked is not None:
            asked.append(url)
        if url == DOWNLOAD_URL:
            return httpx.Response(200, json=LISTING)
        return httpx.Response(200, content=bodies[url])

    return httpx.Client(transport=httpx.MockTransport(handler))


def _application(number: str, sponsor: str, *submissions: tuple[str, str, str, str]) -> dict:
    """Submissions as (type, class code, status, status date)."""
    return {
        "application_number": number,
        "sponsor_name": sponsor,
        "submissions": [
            {"submission_type": kind, "submission_class_code": category, "submission_status": status,
             "submission_status_date": day}
            for kind, category, status, day in submissions
        ],
    }


def _recall(event: str, number: str, firm: str, day: str) -> dict:
    return {"event_id": event, "recall_number": number, "recalling_firm": firm, "report_date": day}


def _rows(frame) -> list[tuple]:
    return [(r.symbol, r.kind, r.day, r.event_id) for r in frame.itertuples()]


def test_the_history_reads_the_bulk_files_and_keeps_the_counted_approval_kinds():
    applications = [
        _application(
            "NDA000001", "PFIZER INC",
            ("ORIG", "TYPE 1", "AP", "20240110"),  # an original (new_molecule is the same event)
            ("SUPPL", "EFFICACY", "AP", "20240301"),  # a new indication
            ("SUPPL", "LABELING", "AP", "20240302"),  # labeling: not counted
            ("ORIG", "TYPE 3", "TA", "20240303"),  # tentative: not counted
            ("ORIG", "TYPE 1", "AP", "20170101"),  # before `since`
        ),
        _application("BLA000002", "MERCK SHARP DOHME", ("ORIG", "", "AP", "20240201")),
    ]
    asked: list[str] = []
    with _client(applications, [], asked) as client:
        frame = fda_history(client, NAMES, SINCE, None)
    assert asked == [DOWNLOAD_URL, APPROVALS_FILE, RECALLS_FILE]
    assert list(frame.columns) == EVENT_COLUMNS == ["symbol", "kind", "day", "event_id"]
    assert sorted(_rows(frame)) == sorted([
        ("PFE", "approval", date(2024, 1, 10), "NDA000001:original:20240110:0"),
        ("PFE", "approval", date(2024, 3, 1), "NDA000001:new_indication:20240301:1"),
        ("MRK", "approval", date(2024, 2, 1), "BLA000002:original:20240201:0"),
    ])


def test_one_recall_event_listing_three_products_is_one_row():
    recalls = [
        _recall("100", "D-001-2024", "Pfizer Inc.", "20240105"),
        _recall("100", "D-002-2024", "Pfizer Inc.", "20240105"),
        _recall("100", "D-003-2024", "Pfizer Inc.", "20240105"),
        _recall("101", "D-004-2024", "Pfizer Inc.", "20240120"),
        _recall("", "D-005-2024", "Merck Sharp & Dohme LLC", "20240121"),  # no event id: the recall number
        _recall("102", "D-006-2017", "Pfizer Inc.", "20171231"),  # before `since`
        _recall("103", "D-007-2024", "Pfizer Inc.", "not a date"),
    ]
    with _client([], recalls) as client:
        frame = fda_history(client, NAMES, SINCE, None)
    assert _rows(frame) == [
        ("MRK", "recall", date(2024, 1, 21), "D-005-2024"),
        ("PFE", "recall", date(2024, 1, 5), "100"),
        ("PFE", "recall", date(2024, 1, 20), "101"),
    ]


def test_the_history_matches_sponsor_names_against_the_whole_universe():
    # Two different companies whose keys both extend "ZETA": the name is ambiguous and matches none.
    # Two share classes of one company have the same key: both get the event.
    recalls = [
        _recall("1", "D-1", "Zeta Inc.", "20240105"),
        _recall("2", "D-2", "Berkshire Hathaway", "20240106"),
        _recall("3", "D-3", "Unknown Pharma Ltd", "20240107"),
    ]
    with _client([], recalls) as client:
        frame = fda_history(client, NAMES, SINCE, None)
    assert sorted(_rows(frame)) == [
        ("BRKA", "recall", date(2024, 1, 6), "2"),
        ("BRKB", "recall", date(2024, 1, 6), "2"),
    ]
    # Were only one of the two Zeta companies in the names, the same name would match it: the matcher
    # always gets the whole directory, so training and live agree.
    with _client([], recalls) as client:
        alone = fda_history(client, {"ALPHA": NAMES["ALPHA"]}, SINCE, None)
    assert _rows(alone) == [("ALPHA", "recall", date(2024, 1, 5), "1")]


def test_an_empty_history_keeps_its_columns():
    with _client([], []) as client:
        frame = fda_history(client, NAMES, SINCE, None)
    assert list(frame.columns) == EVENT_COLUMNS and frame.empty
