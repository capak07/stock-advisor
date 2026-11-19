import io
import json
import threading
import zipfile
from datetime import UTC, date, datetime, timedelta

import httpx
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from advisor.collectors.finra_short_interest import FINRA_SHORT_INTEREST_URL
from advisor.collectors.finra_short_volume import FINRA_SHORT_VOLUME_URL
from advisor.collectors.openfigi import FigiBook
from advisor.collectors.sec import SUBMISSIONS_ZIP_URL
from advisor.model.groups import GROUP_FILES
from advisor.model.variants import ModelConfig
from advisor.training import history as history_module
from advisor.training.fda_history import DOWNLOAD_URL
from advisor.training.finra_history import PARTITIONS_URL
from advisor.training.history import (
    MAX_HISTORY_AGE_DAYS,
    HistoryCache,
    HistoryDeps,
    build_history,
    copy_history,
    wanted_groups,
)
from advisor.training.sec_history import INSIDER_LISTING_URL, SUBMISSION_FORMS
from fakes import fake_sec

NOW = datetime(2026, 11, 21, 2, tzinfo=UTC)  # Saturday 02:00 UTC; Friday 2026-11-20 in New York
SINCE = date(2026, 7, 1)
OLD, RECENT = "2026-07-15", "2026-10-30"  # more and less than 90 days before 2026-11-20
NAMES = {"PFE": "Pfizer, Inc. Common Stock", "AAPL": "Apple Inc. Common Stock"}
TICKERS = pd.DataFrame({"symbol": ["AAPL", "BRK.B"], "cik": [320193, 1067983]})
SYMBOLS = ["AAPL", "BRK.B"]

INTEREST_HEADER = (
    '"accountingYearMonthNumber"|"symbolCode"|"issueName"|"issuerServicesGroupExchangeCode"|'
    '"marketClassCode"|"currentShortPositionQuantity"|"previousShortPositionQuantity"|'
    '"stockSplitFlag"|"averageDailyVolumeQuantity"|"daysToCoverQuantity"|"revisionFlag"|'
    '"changePercent"|"changePreviousNumber"|"settlementDate"'
)
APPROVALS_FILE = "https://download.open.fda.gov/drug/drugsfda/drug-drugsfda-0001-of-0001.json.zip"
RECALLS_FILE = "https://download.open.fda.gov/drug/enforcement/drug-enforcement-0001-of-0001.json.zip"


def _interest(day: str) -> str:
    month = day[:4] + day[5:7]
    return "\n".join([
        INTEREST_HEADER,
        f'"{month}"|"AAPL"|"Apple"|"A"|"NASDAQ"|"1000"|"900"||"500"|"2.00"||"1"|"1"|"{day}"',
        f'"{month}"|"BRKB"|"Berkshire B"|"A"|"NYSE"|"300"|"250"||"10"|"30.00"||"1"|"1"|"{day}"',
    ]) + "\n"


def _volume(day: str) -> str:
    stamp = day.replace("-", "")
    return f"Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market\n{stamp}|AAPL|40|0|100|Q\n{stamp}|BRK/B|10|0|50|N\n"


def _zip_json(records: list[dict]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("data.json", json.dumps({"meta": {}, "results": records}))
    return buffer.getvalue()


def web(asked: list[str]) -> httpx.Client:
    """FINRA (two settlements, two short-volume days) and openFDA (one Pfizer approval); others 404."""
    partitions = {"availablePartitions": [{"partitions": [day]} for day in (RECENT, OLD, "2017-12-29")]}
    approval = {"application_number": "NDA000001", "sponsor_name": "PFIZER INC", "submissions": [
        {"submission_type": "ORIG", "submission_class_code": "TYPE 1", "submission_status": "AP",
         "submission_status_date": "20260901"}]}
    listing = {"results": {"drug": {"drugsfda": {"partitions": [{"file": APPROVALS_FILE}]},
                                    "enforcement": {"partitions": [{"file": RECALLS_FILE}]}}}}
    bodies: dict[str, bytes] = {
        PARTITIONS_URL: json.dumps(partitions).encode(),
        DOWNLOAD_URL: json.dumps(listing).encode(),
        APPROVALS_FILE: _zip_json([approval]),
        RECALLS_FILE: _zip_json([]),
    }
    for day in (OLD, RECENT):
        bodies[FINRA_SHORT_INTEREST_URL.format(day=date.fromisoformat(day))] = _interest(day).encode()
    for day in (OLD, "2026-11-02"):
        bodies[FINRA_SHORT_VOLUME_URL.format(day=date.fromisoformat(day))] = _volume(day).encode()

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        asked.append(url)
        return httpx.Response(200, content=bodies[url]) if url in bodies else httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


def deps_for(cache: HistoryCache, client: httpx.Client, sec=None, **changes) -> HistoryDeps:
    no_figi = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(400)))
    fields = dict(
        finra=client, fda=client, sec=sec or fake_sec({}), figis=FigiBook(no_figi, cache.figi_path),
        cache=cache, names=NAMES,
    )
    return HistoryDeps(**{**fields, **changes})


def run(cache: HistoryCache, groups: set[str], deps: HistoryDeps, manifest: dict | None = None,
        tickers: pd.DataFrame = TICKERS, since: date = SINCE) -> dict:
    manifest = {} if manifest is None else manifest
    build_history(cache, frozenset(groups), deps, tickers, SYMBOLS, NAMES, since, NOW, manifest)
    return manifest


def written(cache: HistoryCache) -> dict:
    return json.loads((cache.groups_dir / "written.json").read_text())


def test_each_wanted_group_writes_its_files_and_seconds(tmp_path):
    cache = HistoryCache(tmp_path / "cache")
    asked: list[str] = []
    with web(asked) as client:
        manifest = run(cache, {"short", "catalysts"}, deps_for(cache, client))
    assert sorted(p.name for p in cache.groups_dir.iterdir()) == [
        "fda_events.parquet", "short_interest.parquet", "short_volume.parquet", "written.json",
    ]
    assert written(cache) == {"short": NOW.isoformat(), "catalysts": NOW.isoformat()}
    assert {"history_short", "history_catalysts"} <= set(manifest["seconds"])
    assert "unavailable" not in manifest
    interest = pd.read_parquet(cache.groups_dir / "short_interest.parquet")
    assert sorted(zip(interest["symbol"], interest["settlement"], strict=True)) == [
        ("AAPL", date(2026, 7, 15)), ("AAPL", date(2026, 10, 30)),
        ("BRK.B", date(2026, 7, 15)), ("BRK.B", date(2026, 10, 30)),
    ]  # the 2017 settlement is before `since`: never asked for
    assert not any("20171229" in url for url in asked)
    volume = pd.read_parquet(cache.groups_dir / "short_volume.parquet")
    assert sorted(set(volume["day"])) == [date(2026, 7, 15), date(2026, 11, 2)]
    fda = pd.read_parquet(cache.groups_dir / "fda_events.parquet")
    assert fda[["symbol", "kind"]].values.tolist() == [["PFE", "approval"]]


def test_a_failing_group_is_recorded_and_the_others_still_write(tmp_path, monkeypatch):
    cache = HistoryCache(tmp_path / "cache")
    cache.groups_dir.mkdir(parents=True)
    earlier = (NOW - timedelta(days=7)).isoformat()
    pd.DataFrame({"symbol": ["PFE"], "kind": ["recall"], "day": [date(2026, 1, 5)], "event_id": ["1"]}).to_parquet(
        cache.groups_dir / "fda_events.parquet")
    before = (cache.groups_dir / "fda_events.parquet").read_bytes()
    (cache.groups_dir / "written.json").write_text(json.dumps({"catalysts": earlier}))

    def down(*args, **kwargs):
        raise RuntimeError("openFDA down")

    monkeypatch.setattr(history_module, "fda_history", down)
    manifest = {"unavailable": {"macro": "FRED stalled"}, "seconds": {}}
    with web([]) as client:
        run(cache, {"short", "catalysts"}, deps_for(cache, client), manifest)
    assert manifest["unavailable"] == {"macro": "FRED stalled", "catalysts": "RuntimeError: openFDA down"}
    assert (cache.groups_dir / "fda_events.parquet").read_bytes() == before
    assert written(cache) == {"catalysts": earlier, "short": NOW.isoformat()}
    assert (cache.groups_dir / "short_interest.parquet").exists()
    assert "history_catalysts" in manifest["seconds"]


def test_a_group_without_rows_is_unavailable_and_keeps_nothing_new(tmp_path, monkeypatch):
    cache = HistoryCache(tmp_path / "cache")
    monkeypatch.setattr(history_module, "fda_history",
                        lambda *args: pd.DataFrame(columns=["symbol", "kind", "day", "event_id"]))
    with web([]) as client:
        manifest = run(cache, {"catalysts"}, deps_for(cache, client))
    assert manifest["unavailable"] == {"catalysts": "EmptyHistory: catalysts: no rows"}
    assert not (cache.groups_dir / "fda_events.parquet").exists()
    assert not (cache.groups_dir / "written.json").exists()


def _filings() -> pd.DataFrame:
    accepted = pd.Timestamp("2026-06-01 16:30", tz="UTC")
    frame = pd.DataFrame({
        "cik": [320193, 320193], "accession": ["0000320193-26-000001", "0000320193-26-000002"],
        "form": ["8-K", "4"], "filing_date": [date(2026, 6, 1), date(2026, 6, 2)],
        "accepted_at": [accepted, accepted], "items": [["5.02"], []], "file_number": ["", ""],
    })
    return frame.astype({"accession": "string", "form": "string", "file_number": "string"})


def _insider_set() -> pd.DataFrame:
    return pd.DataFrame({
        "accession": ["0000320193-26-000002"], "issuer_cik": [320193], "filed_ticker": ["AAPL"],
        "filing_date": [date(2026, 6, 2)], "trade_date": [date(2026, 6, 1)], "code": ["P"],
        "shares": [100.0], "price": [10.0], "owners": [["Jane Doe"]], "officer": [True], "director": [False],
        "ten_percent_owner": [False],
    })


SET_BASE = "https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets/"
SPRING = date(2026, 4, 1)  # 2025q4 ended before it; 2026q2 ended over 90 days before NOW, 2026q3 did not


def _sec_routes(extra: dict | None = None) -> dict:
    listing = "".join(f'<a href="/files/structureddata/data/insider-transactions-data-sets/{name}_form345.zip">'
                      for name in ("2025q4", "2026q2", "2026q3"))
    return {
        SUBMISSIONS_ZIP_URL: b"a zip",
        INSIDER_LISTING_URL: listing.encode(),
        f"{SET_BASE}2025q4_form345.zip": b"q4",
        f"{SET_BASE}2026q2_form345.zip": b"q2",
        f"{SET_BASE}2026q3_form345.zip": b"q3",
        **(extra or {}),
    }


def test_submissions_are_reduced_once_for_events_and_insider(tmp_path, monkeypatch):
    cache = HistoryCache(tmp_path / "cache")
    calls: list[dict] = []

    def reduce(path, ciks, since, page=None, forms=None):
        calls.append({"ciks": sorted(set(ciks)), "since": since, "forms": forms, "exists": path.exists()})
        return _filings()

    monkeypatch.setattr(history_module, "reduce_submissions", reduce)
    monkeypatch.setattr(history_module, "reduce_insider_set",  # 2026q3 has no open-market trade
                        lambda path: _insider_set().iloc[: int(path.name.startswith("2026q2"))])
    duplicated = pd.concat([TICKERS, TICKERS], ignore_index=True)  # the same (symbol, cik) twice
    seen: list[httpx.Request] = []
    with web([]) as client:
        sec = fake_sec(_sec_routes(), seen=seen)
        manifest = run(cache, {"events", "insider"}, deps_for(cache, client, sec), tickers=duplicated, since=SPRING)
    assert calls == [{"ciks": [320193, 1067983], "since": SPRING, "forms": SUBMISSION_FORMS, "exists": True}]
    assert "unavailable" not in manifest
    events = pd.read_parquet(cache.groups_dir / "material_events.parquet")
    assert events[["symbol", "accession"]].values.tolist() == [["AAPL", "0000320193-26-000001"]]  # once
    trades = pd.read_parquet(cache.groups_dir / "insider_trades.parquet")
    assert trades[["symbol", "accession"]].values.tolist() == [["AAPL", "0000320193-26-000002"]]
    assert trades["accepted_at"].iloc[0] == pd.Timestamp("2026-06-01 16:30", tz="UTC")
    assert (cache.groups_dir / "large_holders.parquet").exists()
    asked = [str(r.url) for r in seen]
    assert f"{SET_BASE}2025q4_form345.zip" not in asked  # ended before `since`
    assert f"{SET_BASE}2026q2_form345.zip" in asked
    assert manifest["insider_rows"] == {"2026q2": 1, "2026q3": 0}
    # 2026q2 ended 143 days ago and is kept; 2026q3 (51 days) may still change
    assert sorted(p.name for p in (cache.root / "insider").iterdir()) == ["2026q2.parquet"]
    assert {"history_submissions", "history_events", "history_insider"} <= set(manifest["seconds"])

    seen.clear()
    with web([]) as client:
        run(cache, {"insider"}, deps_for(cache, client, fake_sec(_sec_routes(), seen=seen)), since=SPRING)
    asked = [str(r.url) for r in seen]
    assert f"{SET_BASE}2026q2_form345.zip" not in asked and f"{SET_BASE}2026q3_form345.zip" in asked


def test_a_failed_submissions_reduce_marks_both_groups_unavailable(tmp_path, monkeypatch):
    cache = HistoryCache(tmp_path / "cache")

    def broken(*args, **kwargs):
        raise OSError("zip damaged")

    monkeypatch.setattr(history_module, "reduce_submissions", broken)
    monkeypatch.setattr(history_module, "reduce_insider_set", lambda path: _insider_set())
    with web([]) as client:
        manifest = run(cache, {"events", "insider", "catalysts"}, deps_for(cache, client, fake_sec(_sec_routes())))
    message = manifest["unavailable"]["events"]
    assert "zip damaged" in message and manifest["unavailable"]["insider"] == message
    assert "catalysts" not in manifest["unavailable"]
    assert written(cache) == {"catalysts": NOW.isoformat()}


def _arrays(rows: list[dict]) -> dict:
    keys = ["accessionNumber", "filingDate", "reportDate", "acceptanceDateTime", "form", "fileNumber",
            "items", "primaryDocument"]
    return {key: [row.get(key, "") for row in rows] for key in keys}


def test_a_submissions_page_missing_from_the_zip_is_fetched_from_sec(tmp_path):
    page = "CIK0000320193-submissions-001.json"
    company = {"cik": "320193", "filings": {
        "recent": _arrays([{"accessionNumber": "0000320193-26-000001", "form": "8-K", "filingDate": "2026-08-03",
                            "items": "2.02"}]),
        "files": [{"name": page, "filingCount": 1, "filingFrom": "2026-01-01", "filingTo": "2026-07-31"}],
    }}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("CIK0000320193.json", json.dumps(company))  # the page is not in the zip
    older = _arrays([{"accessionNumber": "0000320193-26-000000", "form": "8-K", "filingDate": "2026-07-20",
                      "items": "1.01"}])
    routes = {SUBMISSIONS_ZIP_URL: buffer.getvalue(),
              f"https://data.sec.gov/submissions/{page}": json.dumps(older).encode()}
    cache = HistoryCache(tmp_path / "cache")
    with web([]) as client:
        manifest = run(cache, {"events"}, deps_for(cache, client, fake_sec(routes)))
    assert "unavailable" not in manifest
    events = pd.read_parquet(cache.groups_dir / "material_events.parquet")
    assert sorted(events["accession"]) == ["0000320193-26-000000", "0000320193-26-000001"]


def test_a_cached_finra_file_is_not_fetched_again(tmp_path):
    cache = HistoryCache(tmp_path / "cache")
    asked: list[str] = []
    with web(asked) as client:
        run(cache, {"short"}, deps_for(cache, client))
        run(cache, {"short"}, deps_for(cache, client))
    old_interest = FINRA_SHORT_INTEREST_URL.format(day=date.fromisoformat(OLD))
    old_volume = FINRA_SHORT_VOLUME_URL.format(day=date.fromisoformat(OLD))
    recent_interest = FINRA_SHORT_INTEREST_URL.format(day=date.fromisoformat(RECENT))
    assert asked.count(old_interest) == 1 and asked.count(old_volume) == 1  # the second run read the cache
    assert asked.count(recent_interest) == 2  # within 90 days: fetched each run
    assert cache.get("finra_interest", OLD) is not None and cache.get("finra_interest", RECENT) is None
    assert sorted(cache.get("finra_volume", OLD)["symbol"]) == ["AAPL", "BRK/B"]  # FINRA's own symbols


def test_yahoo_groups_record_their_empty_counts_and_a_stable_timing_type(tmp_path, monkeypatch):
    grades = pd.DataFrame({"symbol": ["AAPL"], "graded_at": [pd.Timestamp("2026-06-01 13:00")], "firm": ["X"],
                           "action": ["up"], "from_grade": ["Hold"], "to_grade": ["Buy"],
                           "price_target_action": [None]})
    reports = pd.DataFrame({"symbol": ["AAPL", "AAPL"], "report_day": pd.to_datetime(["2026-05-01", "2026-08-01"]),
                            "timing": [None, None], "eps_estimate": [1.0, 1.1], "eps_actual": [1.2, None]})
    monkeypatch.setattr(history_module, "analyst_history", lambda symbols, load, limiter: (grades, 5))
    monkeypatch.setattr(history_module, "estimates_history", lambda symbols, load, limiter: (reports, 3))
    cache = HistoryCache(tmp_path / "cache")
    with web([]) as client:
        manifest = run(cache, {"analyst", "estimates"}, deps_for(cache, client))
    assert manifest["empty"] == {"analyst": 5, "estimates": 3}
    schema = pq.read_schema(cache.groups_dir / "earnings_estimates.parquet")
    assert schema.field("timing").type in (pa.string(), pa.large_string())  # not null, though every value is None
    assert set(written(cache)) == {"analyst", "estimates"}


def test_holders_record_how_many_symbols_openfigi_mapped_and_failed(tmp_path, monkeypatch):
    seen: dict = {}

    def build(sec, figis, folder, symbols, as_of, since, counts=None):
        seen.update(folder=folder, figis=figis, since=since)
        counts.update(asked=2, mapped=1, with_holdings=1, figi_failed=1, data_sets=3)
        frame = pd.DataFrame({"symbol": ["AAPL"], "cusip": ["037833100"], "period": [date(2026, 3, 31)],
                              "known": [date(2026, 6, 30)], "shares": [10], "holders": [2]})
        return frame, {"2023q3": "HTTPStatusError: 404"}

    monkeypatch.setattr(history_module, "holders_build", build)
    cache = HistoryCache(tmp_path / "cache")
    with web([]) as client:
        deps = deps_for(cache, client)
        manifest = run(cache, {"holders"}, deps)
    assert seen == {"folder": cache.sec13f_folder, "figis": deps.figis, "since": SINCE}
    assert manifest["holders"] == {"asked": 2, "mapped": 1, "with_holdings": 1, "figi_failed": 1, "data_sets": 3,
                                   "gaps": {"2023q3": "HTTPStatusError: 404"}}
    assert (cache.groups_dir / "holders.parquet").exists()


def test_the_yahoo_groups_run_beside_the_others_in_priority_order(tmp_path, monkeypatch):
    order: list[str] = []
    other_started = threading.Event()

    def reader(group):
        def read(context):
            order.append(group)
            if group in ("analyst", "estimates"):
                assert other_started.wait(5), "the other thread did not run beside the Yahoo thread"
            else:
                other_started.set()
            return {name: pd.DataFrame({"symbol": ["AAPL"]}) for name in GROUP_FILES[group]}
        return read

    for group in GROUP_FILES:
        monkeypatch.setitem(history_module.READERS, group, reader(group))
    cache = HistoryCache(tmp_path / "cache")
    with web([]) as client:
        manifest = run(cache, set(GROUP_FILES), deps_for(cache, client))
    assert "unavailable" not in manifest
    assert [g for g in order if g not in ("analyst", "estimates")] == [
        "short", "insider", "events", "holders", "catalysts"]
    assert [g for g in order if g in ("analyst", "estimates")] == ["analyst", "estimates"]
    assert set(written(cache)) == set(GROUP_FILES)


def test_the_figi_book_and_13f_totals_live_under_the_cache_root(tmp_path):
    cache = HistoryCache(tmp_path)
    assert cache.root == tmp_path
    assert cache.figi_path == tmp_path / "openfigi.json"
    assert cache.sec13f_folder == tmp_path / "sec_13f"
    assert cache.groups_dir == tmp_path / "groups"
    assert cache.get("finra_volume", "2018-08-01") is None
    frame = pd.DataFrame({"symbol": pd.Series(["BRK/B"], dtype="string"), "day": [date(2018, 8, 1)]})
    cache.put("finra_volume", "2018-08-01", frame)
    assert (tmp_path / "finra_volume" / "2018-08-01.parquet").exists()
    assert cache.get("finra_volume", "2018-08-01").equals(frame)
    (tmp_path / "finra_volume" / "2018-08-02.parquet").write_bytes(b"cut short by a killed run")
    assert cache.get("finra_volume", "2018-08-02") is None  # a damaged entry is fetched again


def _write_group(cache: HistoryCache, group: str, at: datetime) -> None:
    cache.groups_dir.mkdir(parents=True, exist_ok=True)
    for name in GROUP_FILES[group]:
        pd.DataFrame({"symbol": ["AAPL"], "value": [1.0]}).to_parquet(cache.groups_dir / name)
    path = cache.groups_dir / "written.json"
    times = json.loads(path.read_text()) if path.exists() else {}
    path.write_text(json.dumps({**times, group: at.isoformat()}))


def test_fresh_groups_are_copied_and_stale_or_missing_ones_are_unavailable(tmp_path):
    cache = HistoryCache(tmp_path / "cache")
    _write_group(cache, "short", NOW - timedelta(days=MAX_HISTORY_AGE_DAYS))
    _write_group(cache, "holders", NOW - timedelta(days=22))
    out = tmp_path / "out"
    out.mkdir()
    manifest: dict = {"unavailable": {"macro": "FRED stalled"}}
    copied = copy_history(cache, out, frozenset({"short", "holders", "analyst"}), NOW, manifest)
    assert copied == frozenset({"short"})
    assert sorted(p.name for p in out.iterdir()) == ["short_interest.parquet", "short_volume.parquet"]
    assert manifest["unavailable"] == {
        "macro": "FRED stalled", "holders": "cached history is 22 days old", "analyst": "no cached history"}
    assert manifest["history_age_days"] == {"short": 21.0}
    assert manifest["files"]["short_volume.parquet"]["rows"] == 1


def test_a_group_with_a_missing_file_is_not_copied(tmp_path):
    cache = HistoryCache(tmp_path / "cache")
    _write_group(cache, "events", NOW - timedelta(days=1))
    (cache.groups_dir / "large_holders.parquet").unlink()
    manifest: dict = {}
    assert copy_history(cache, tmp_path, frozenset({"events"}), NOW, manifest) == frozenset()
    assert manifest["unavailable"] == {"events": "no cached history"}
    assert not (tmp_path / "material_events.parquet").exists()


def test_a_group_this_run_failed_to_download_but_cached_fresh_is_copied_and_noted(tmp_path):
    cache = HistoryCache(tmp_path / "cache")
    _write_group(cache, "catalysts", NOW - timedelta(days=7))
    manifest: dict = {"unavailable": {"catalysts": "RuntimeError: openFDA down"}}
    assert copy_history(cache, tmp_path, frozenset({"catalysts"}), NOW, manifest) == frozenset({"catalysts"})
    assert "unavailable" not in manifest
    assert manifest["history_failed"] == {"catalysts": "RuntimeError: openFDA down"}


def test_wanted_groups_reads_all_none_and_a_list():
    assert wanted_groups("all") == frozenset(GROUP_FILES)
    assert wanted_groups("none") == frozenset()
    assert wanted_groups("short,holders") == frozenset({"short", "holders"})
    assert wanted_groups(" short , holders ") == frozenset({"short", "holders"})
    with pytest.raises(ValueError, match="bogus"):
        wanted_groups("short,bogus")


def test_the_group_files_are_the_planned_ones():
    assert GROUP_FILES == {
        "short": ("short_interest.parquet", "short_volume.parquet"),
        "analyst": ("analyst_events.parquet",),
        "insider": ("insider_trades.parquet",),
        "events": ("material_events.parquet", "large_holders.parquet"),
        "holders": ("holders.parquet",),
        "estimates": ("earnings_estimates.parquet",),
        "catalysts": ("fda_events.parquet",),
    }


def test_accepted_builds_only_the_groups_of_the_us_config():
    stored = ModelConfig(garch=True, ranker=True, forest=True, short=True, earnings=True).to_json()
    assert history_module.accepted_groups(stored) == frozenset({"short"})  # earnings has no files
    assert history_module.accepted_groups(None) == frozenset()
    older = ModelConfig(ranker=True, earnings=True).to_json() | {"version": 5}
    for key in ("short", "analyst", "insider", "events", "holders", "estimates", "catalysts"):
        older.pop(key)
    assert history_module.accepted_groups(older) == frozenset()


def test_an_unreadable_stored_config_builds_no_groups_instead_of_raising(caplog):
    stored = ModelConfig(short=True).to_json()
    for unreadable in (stored | {"version": 7}, stored | {"surprise": 1}, "not a mapping"):
        caplog.clear()
        with caplog.at_level("WARNING", logger=history_module.log.name):
            assert history_module.accepted_groups(unreadable) == frozenset()
        assert "can't be read" in caplog.text
