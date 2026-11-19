import json
import zipfile
from datetime import date

import numpy as np
import pandas as pd
import pytest

from advisor.collectors.sec import SUBMISSIONS_ZIP_URL
from advisor.collectors.sec_events import EVENT_FORMS
from advisor.collectors.sec_holders import HOLDER_FORMS
from advisor.model.events import events_features
from advisor.model.insider import insider_features
from advisor.training.sec_history import (
    INSIDER_LISTING_URL,
    SUBMISSION_FORMS,
    insider_data_sets,
    insider_history,
    large_holder_filings,
    material_events,
    reduce_insider_set,
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


INSIDER_COLUMNS = ["symbol", "accession", "filing_date", "accepted_at", "trade_date", "code", "shares", "price",
                   "owners", "officer", "director", "ten_percent_owner", "filed_ticker"]
SET_COLUMNS = ["accession", "issuer_cik", "filed_ticker", "filing_date", "trade_date", "code", "shares", "price",
               "owners", "officer", "director", "ten_percent_owner"]


def test_insider_data_sets_are_read_from_the_listing():
    assert INSIDER_LISTING_URL == "https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets"
    html = (
        '<a href="/files/structureddata/data/insider-transactions-data-sets/2006q1_form345.zip">2006 Q1</a>'
        '<a href="/files/datastandardsinnovation/insider/2026q3_form345.zip">2026 Q3</a>'
        '<a href="/files/datastandardsinnovation/insider/2026q3_form345.zip">again</a>'
        '<a href="/files/structureddata/data/form-13f-data-sets/2018q1_form13f.zip">13F</a>'
    )
    assert insider_data_sets(html) == [
        ("2006q1", "https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets/2006q1_form345.zip"),
        ("2026q3", "https://www.sec.gov/files/datastandardsinnovation/insider/2026q3_form345.zip"),
    ]


def _tsv(header: list[str], rows: list[dict]) -> str:
    return "\n".join(["\t".join(header), *("\t".join(row.get(h, "") for h in header) for row in rows)]) + "\n"


def _insider_zip(tmp_path, submissions: list[dict], owners: list[dict], trades: list[dict],
                 name: str = "2026q2_form345.zip"):
    """A Form 3/4/5 data set with SEC's three files (the columns read, plus a few that are not)."""
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("SUBMISSION.tsv", _tsv(
            ["ACCESSION_NUMBER", "FILING_DATE", "PERIOD_OF_REPORT", "DOCUMENT_TYPE", "ISSUERCIK", "ISSUERNAME",
             "ISSUERTRADINGSYMBOL"], submissions))
        archive.writestr("REPORTINGOWNER.tsv", _tsv(
            ["ACCESSION_NUMBER", "RPTOWNERCIK", "RPTOWNERNAME", "RPTOWNER_RELATIONSHIP", "RPTOWNER_TITLE"], owners))
        archive.writestr("NONDERIV_TRANS.tsv", _tsv(
            ["ACCESSION_NUMBER", "NONDERIV_TRANS_SK", "SECURITY_TITLE", "TRANS_DATE", "TRANS_CODE", "TRANS_SHARES",
             "TRANS_PRICEPERSHARE", "TRANS_ACQUIRED_DISP_CD"], trades))
    return path


def _submission(accession: str, form: str, filed: str, cik: str, ticker: str) -> dict:
    return {"ACCESSION_NUMBER": accession, "FILING_DATE": filed, "DOCUMENT_TYPE": form, "ISSUERCIK": cik,
            "ISSUERTRADINGSYMBOL": ticker}


def _owner(accession: str, name: str, relationship: str) -> dict:
    return {"ACCESSION_NUMBER": accession, "RPTOWNERNAME": name, "RPTOWNER_RELATIONSHIP": relationship}


def _trade(accession: str, code: str, day: str, shares: str, price: str = "") -> dict:
    return {"ACCESSION_NUMBER": accession, "SECURITY_TITLE": "Common Stock", "TRANS_DATE": day, "TRANS_CODE": code,
            "TRANS_SHARES": shares, "TRANS_PRICEPERSHARE": price}


def test_reduce_keeps_only_open_market_trades_of_form_4(tmp_path):
    path = _insider_zip(tmp_path, [
        _submission("0000000002-26-000001", "3", "02-JUN-2026", "2", "BBB"),
        _submission("0000000002-26-000002", "4", "03-JUN-2026", "2", "BBB"),
    ], [
        _owner("0000000002-26-000001", "NEW NANCY", "Officer"),
        _owner("0000000002-26-000002", "BIG FUND LP", "Director,TenPercentOwner"),
    ], [
        _trade("0000000002-26-000001", "P", "01-JUN-2026", "500", "9.5"),  # a Form 3 row
        _trade("0000000002-26-000002", "A", "01-JUN-2026", "1000"),  # an award
        _trade("0000000002-26-000002", "P", "01-JUN-2026", "2500", "10.25"),
    ])
    trades = reduce_insider_set(path)
    assert list(trades.columns) == SET_COLUMNS
    assert len(trades) == 1
    row = trades.iloc[0]
    assert row["accession"] == "0000000002-26-000002" and row["issuer_cik"] == 2
    assert row["filed_ticker"] == "BBB" and row["code"] == "P"
    assert row["filing_date"] == date(2026, 6, 3) and row["trade_date"] == date(2026, 6, 1)
    assert row["shares"] == 2500 and row["price"] == 10.25
    assert list(row["owners"]) == ["BIG FUND LP"]
    assert bool(row["director"]) and bool(row["ten_percent_owner"]) and not bool(row["officer"])


def test_reduce_keeps_amendments_sales_and_trades_without_a_price(tmp_path):
    path = _insider_zip(tmp_path, [
        _submission("0000000001-26-000003", "4/A", "05-JUN-2026", "1", "AAA"),
        _submission("0000000001-26-000004", "5", "05-JUN-2026", "1", "AAA"),
    ], [
        _owner("0000000001-26-000003", "SMITH JOHN", "Officer"),
        _owner("0000000001-26-000003", "SMITH JANE", "Director"),
    ], [
        _trade("0000000001-26-000003", "S", "04-JUN-2026", "300"),
        _trade("0000000001-26-000003", "M", "04-JUN-2026", "300", "1.0"),
        _trade("0000000001-26-000004", "P", "04-JUN-2026", "300", "1.0"),  # a Form 5 row
    ])
    trades = reduce_insider_set(path)
    assert trades["code"].tolist() == ["S"]
    assert list(trades["owners"].iloc[0]) == ["SMITH JOHN", "SMITH JANE"]
    assert bool(trades["officer"].iloc[0]) and bool(trades["director"].iloc[0])
    assert np.isnan(trades["price"].iloc[0])


def test_history_joins_acceptance_by_accession_and_maps_the_issuer_cik(tmp_path):
    first = reduce_insider_set(_insider_zip(tmp_path, [
        _submission("0000000002-26-000002", "4", "03-JUN-2026", "2", "BBB"),
        _submission("0000000009-26-000001", "4", "03-JUN-2026", "9", "ZZZ"),  # not in the universe
    ], [
        _owner("0000000002-26-000002", "BIG FUND LP", "TenPercentOwner"),
        _owner("0000000009-26-000001", "SOMEONE", "Officer"),
    ], [
        _trade("0000000002-26-000002", "P", "01-JUN-2026", "2500", "10.25"),
        _trade("0000000009-26-000001", "P", "01-JUN-2026", "1", "1"),
    ], name="2026q2_form345.zip"))
    second = reduce_insider_set(_insider_zip(tmp_path, [
        _submission("0000000001-26-000007", "4", "01-JUL-2026", "1", "AAA"),
    ], [_owner("0000000001-26-000007", "SMITH JOHN", "Officer")], [
        _trade("0000000001-26-000007", "S", "30-JUN-2026", "100", "20"),
    ], name="2026q3_form345.zip"))
    filings = reduce_submissions(_zip(tmp_path, {
        "CIK0000000002.json": _company(2, [
            _filing("0000000002-26-000002", "4", "2026-06-03", accepted="2026-06-03T21:15:00.000Z"),
        ]),
    }), [1, 2], date(2018, 1, 1), forms=SUBMISSION_FORMS)
    history = insider_history([first, second], filings, TICKERS)
    assert list(history.columns) == INSIDER_COLUMNS
    history = history.sort_values(["symbol", "accession"]).reset_index(drop=True)
    assert history["symbol"].tolist() == ["AAA", "BBB", "BBB.B"]  # share classes share the CIK
    assert history["filed_ticker"].tolist() == ["AAA", "BBB", "BBB"]
    assert str(history["accepted_at"].dtype) == "datetime64[ns, UTC]"
    assert pd.isna(history["accepted_at"].iloc[0])  # no submissions row: NaT
    assert history["accepted_at"].iloc[1] == pd.Timestamp("2026-06-03 17:15", tz="UTC")
    assert history["ten_percent_owner"].tolist() == [False, True, True]


def test_no_insider_sets_still_give_the_columns(tmp_path):
    filings = reduce_submissions(_zip(tmp_path, {}), [1], date(2018, 1, 1))
    assert list(insider_history([], filings, TICKERS).columns) == INSIDER_COLUMNS


def test_the_history_round_trips_through_parquet_into_the_features(tmp_path):
    trades = reduce_insider_set(_insider_zip(tmp_path, [
        _submission("0000000002-26-000002", "4", "03-JUN-2026", "2", "BBB"),
    ], [
        _owner("0000000002-26-000002", "DOE JANE", "Officer"),
        _owner("0000000002-26-000002", "ROE RICHARD", "Director"),
    ], [_trade("0000000002-26-000002", "P", "01-JUN-2026", "1000", "10")]))
    filings = reduce_submissions(_zip(tmp_path, {}), [2], date(2018, 1, 1))
    path = tmp_path / "insider_trades.parquet"
    insider_history([trades], filings, TICKERS).to_parquet(path)
    days = pd.DatetimeIndex(["2026-06-04", "2026-06-05"])  # no acceptance time: known one session after the 3rd
    value = pd.DataFrame(1e6, index=days, columns=["BBB"])
    out = insider_features(pd.read_parquet(path), value, {"BBB"}, days, ["BBB"])
    assert out["insider_buyers_90d"]["BBB"].tolist() == [0, 2]
    assert out["officer_buy_180d"]["BBB"].tolist() == [0, 1]
    assert out["insider_net_buy_90d"]["BBB"].tolist() == [0, pytest.approx(0.01)]
