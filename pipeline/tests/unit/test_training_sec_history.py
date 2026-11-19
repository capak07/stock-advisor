import json
import zipfile
from datetime import date

import pandas as pd
import pytest

from advisor.collectors.sec import SUBMISSIONS_ZIP_URL
from advisor.collectors.sec_events import EVENT_FORMS
from advisor.collectors.sec_holders import HOLDER_FORMS
from advisor.model.events import events_features
from advisor.training.sec_history import (
    SUBMISSION_FORMS,
    large_holder_filings,
    material_events,
    reduce_submissions,
)

COLUMNS = ["cik", "accession", "form", "filing_date", "accepted_at", "items", "file_number"]
TICKERS = pd.DataFrame({"symbol": ["AAA", "BBB", "BBB.B"], "cik": [1, 2, 2]})


def _arrays(rows: list[dict]) -> dict:
    """SEC's parallel arrays (as in `filings.recent` and the overflow pages) from one dict per filing."""
    keys = ["accessionNumber", "filingDate", "reportDate", "acceptanceDateTime", "form", "fileNumber",
            "items", "primaryDocument"]
    return {key: [row.get(key, "") for row in rows] for key in keys}


def _filing(accession: str, form: str, filed: str, *, accepted: str = "", items: str = "",
            file_number: str = "") -> dict:
    return {"accessionNumber": accession, "form": form, "filingDate": filed, "acceptanceDateTime": accepted,
            "items": items, "fileNumber": file_number}


def _company(cik: int, recent: list[dict], pages: list[tuple[str, str]] = ()) -> dict:
    """A submissions document; `pages` lists the overflow pages as (name, last filing date)."""
    return {"cik": str(cik), "name": f"Company {cik}", "filings": {
        "recent": _arrays(recent),
        "files": [{"name": name, "filingCount": 1, "filingFrom": "2000-01-01", "filingTo": last}
                  for name, last in pages],
    }}


def _zip(tmp_path, entries: dict[str, dict]):
    path = tmp_path / "submissions.zip"
    with zipfile.ZipFile(path, "w") as archive:
        for name, payload in entries.items():
            archive.writestr(name, json.dumps(payload))
    return path


def _never(name: str):
    raise AssertionError(f"asked SEC for {name}")


def test_the_bulk_url_and_the_wanted_forms():
    assert SUBMISSIONS_ZIP_URL == "https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip"
    assert SUBMISSION_FORMS == EVENT_FORMS | HOLDER_FORMS | {"4", "4/A"}


def test_reduce_reads_recent_and_overflow_pages(tmp_path):
    page = "CIK0000000001-submissions-001.json"
    path = _zip(tmp_path, {
        "CIK0000000001.json": _company(1, [
            # SEC shifts acceptanceDateTime to UTC twice: 20:30Z is 16:30 UTC (12:30 EDT), as true_acceptance reads it
            _filing("0000000001-26-000002", "8-K", "2026-06-01", accepted="2026-06-01T20:30:00.000Z",
                    items="5.02,9.01"),
        ], [(page, "2019-12-31")]),
        page: _arrays([_filing("0000000001-19-000001", "SC 13G", "2019-05-01", file_number="005-12345")]),
    })
    filings = reduce_submissions(path, [1], date(2018, 1, 1), page=_never)
    assert list(filings.columns) == COLUMNS
    assert filings["accession"].tolist() == ["0000000001-26-000002", "0000000001-19-000001"]
    assert filings["cik"].tolist() == [1, 1]
    assert filings["filing_date"].tolist() == [date(2026, 6, 1), date(2019, 5, 1)]
    assert str(filings["accepted_at"].dtype) == "datetime64[ns, UTC]"
    assert filings["accepted_at"].iloc[0] == pd.Timestamp("2026-06-01 16:30", tz="UTC")
    assert pd.isna(filings["accepted_at"].iloc[1])
    assert filings["items"].tolist() == [["5.02", "9.01"], []]
    assert filings["file_number"].tolist() == ["", "005-12345"]


def test_a_page_missing_from_the_zip_is_asked_of_sec(tmp_path):
    page = "CIK0000000001-submissions-001.json"
    path = _zip(tmp_path, {"CIK0000000001.json": _company(1, [], [(page, "2020-01-01")])})
    asked: list[str] = []

    def fetch(name: str) -> dict:
        asked.append(name)
        return _arrays([_filing("0000000001-19-000001", "8-K", "2019-05-01", items="1.01")])

    filings = reduce_submissions(path, [1, 7], date(2018, 1, 1), page=fetch)
    assert asked == [page]
    assert filings["accession"].tolist() == ["0000000001-19-000001"]


def test_filings_before_since_are_dropped(tmp_path):
    old_page = "CIK0000000001-submissions-002.json"
    path = _zip(tmp_path, {"CIK0000000001.json": _company(1, [
        _filing("0000000001-18-000002", "8-K", "2018-01-01"),
        _filing("0000000001-17-000001", "8-K", "2017-12-31"),
    ], [(old_page, "2010-06-30")])})
    filings = reduce_submissions(path, [1], date(2018, 1, 1), page=_never)  # the old page is not even read
    assert filings["accession"].tolist() == ["0000000001-18-000002"]


def test_reduce_keeps_only_the_wanted_forms(tmp_path):
    path = _zip(tmp_path, {"CIK0000000002.json": _company(2, [
        _filing("0000000002-26-000003", "424B2", "2026-06-03"),
        _filing("0000000002-26-000002", "8-K", "2026-06-02", items="2.02"),
        _filing("0000000002-26-000001", "4", "2026-06-01"),
    ])})
    every = reduce_submissions(path, [2], date(2018, 1, 1))
    assert every["form"].tolist() == ["424B2", "8-K", "4"]
    wanted = reduce_submissions(path, [2], date(2018, 1, 1), forms=SUBMISSION_FORMS)
    assert wanted["form"].tolist() == ["8-K", "4"]


def test_no_filings_still_gives_the_columns(tmp_path):
    path = _zip(tmp_path, {})
    filings = reduce_submissions(path, [1], date(2018, 1, 1))
    assert list(filings.columns) == COLUMNS and filings.empty
    assert material_events(filings, TICKERS).empty and large_holder_filings(filings, TICKERS).empty


@pytest.fixture
def filings(tmp_path):
    return reduce_submissions(_zip(tmp_path, {
        "CIK0000000001.json": _company(1, [
            _filing("0000000001-26-000005", "SCHEDULE 13D/A", "2026-06-05", file_number="005-11111"),
            _filing("0000000001-26-000004", "SC 13D", "2026-06-04", file_number="005-11111"),
            _filing("0000000001-26-000003", "SC 13G/A", "2026-06-03", file_number=""),  # about another issuer
            _filing("0000000001-26-000002", "8-K/A", "2026-06-02", items="4.02"),
            _filing("0000000001-26-000001", "4", "2026-06-01"),
        ]),
        "CIK0000000002.json": _company(2, [
            _filing("0000000002-26-000001", "8-K", "2026-06-01", items="5.02,9.01"),
            _filing("0000000002-26-000002", "SCHEDULE 13G", "2026-06-01", file_number="005-22222"),
        ]),
    }), [1, 2], date(2018, 1, 1), forms=SUBMISSION_FORMS)


def test_material_events_are_the_8ks_of_each_symbol(filings):
    events = material_events(filings, TICKERS)
    assert list(events.columns) == ["symbol", "accession", "form", "filing_date", "accepted_at", "items"]
    assert sorted(zip(events["symbol"], events["form"], events["items"].map(tuple), strict=True)) == [
        ("AAA", "8-K/A", ("4.02",)), ("BBB", "8-K", ("5.02", "9.01")), ("BBB.B", "8-K", ("5.02", "9.01")),
    ]


def test_a_13dg_without_the_subject_file_number_is_ignored(filings):
    holders = large_holder_filings(filings, TICKERS)
    assert list(holders.columns) == ["symbol", "accession", "form", "filing_date", "accepted_at", "activist"]
    assert "0000000001-26-000003" not in set(holders["accession"])  # file_number=""


def test_new_and_legacy_schedule_names_both_count(filings):
    holders = large_holder_filings(filings, TICKERS)
    aaa = holders[holders["symbol"] == "AAA"].sort_values("accession")
    assert aaa["form"].tolist() == ["SC 13D", "SCHEDULE 13D/A"]
    assert aaa["activist"].tolist() == [True, True]
    assert holders.loc[holders["symbol"] == "BBB", "activist"].tolist() == [False]
    out = events_features(material_events(filings, TICKERS), holders, {"AAA", "BBB"},
                          pd.DatetimeIndex(["2026-06-10"]), ["AAA", "BBB"])
    assert out["activist_13d_180d"].loc["2026-06-10"].tolist() == [1, 0]
    assert out["passive_13g_90d"].loc["2026-06-10"].tolist() == [0, 1]
