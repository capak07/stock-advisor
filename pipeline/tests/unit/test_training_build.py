import io
import json
import logging
import zipfile
from collections.abc import Callable
from datetime import UTC, date, datetime

import httpx
import pandas as pd
import pytest

from advisor.collectors.sec import SecEdgar
from advisor.models import Market
from advisor.training import build as build_module
from advisor.training.build import BuildDeps, BuildFailed, build
from advisor.training.prices import PAUSE_SECONDS, YahooThrottled

NOW = datetime(2026, 10, 24, 14, tzinfo=UTC)  # a Saturday
UNIVERSE = {Market.US: ["JPM", "AAPL", "BRK.B"], Market.TSX: ["RY.TO"]}
FIELDS = ["Open", "High", "Low", "Close", "Volume", "Dividends", "Stock Splits"]
SPLIT = {"AAPL": 4.0}  # AAPL splits 4:1 on the second day


def yahoo(
    asked: list[list[str]], silent: frozenset[str] = frozenset(), silent_once: frozenset[str] = frozenset()
):
    """yf.download: two days of bars (and actions) for every ticker but the silent ones.

    `silent` tickers never answer; `silent_once` ones stay quiet on the first ask only.
    """
    skipped: set[str] = set()

    def download(tickers, start, end):
        asked.append(list(tickers))
        quiet = {t for t in tickers if t in silent_once and t not in skipped}
        skipped.update(quiet)
        live = [t for t in tickers if t not in silent and t not in quiet]
        columns = pd.MultiIndex.from_product([live, FIELDS])
        index = pd.to_datetime(["2026-10-22", "2026-10-23"])
        rows = [
            sum(([10.0, 11.0, 9.0, 10.5, 1000.0, 0.0, SPLIT.get(t, 0.0) if day else 0.0] for t in live), [])
            for day in (0, 1)
        ]
        return pd.DataFrame(rows, index=index, columns=columns)

    return download


def web(fixtures_dir) -> httpx.Client:
    """SEC (ticker map, bulk zip), FRED and the Bank of Canada, from recorded fixtures."""
    sec = fixtures_dir / "sec"
    bulk = io.BytesIO()
    with zipfile.ZipFile(bulk, "w") as archive:
        for name, cik in {"AAPL": 320193, "JPM": 19617, "BRK_B": 1067983}.items():
            archive.writestr(f"CIK{cik:010d}.json", (sec / f"companyfacts_{name}_trimmed.json").read_text())

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("company_tickers.json"):
            return httpx.Response(200, content=(sec / "company_tickers.json").read_bytes())
        if request.url.path.endswith("companyfacts.zip"):
            return httpx.Response(200, content=bulk.getvalue())
        if request.url.host == "fred.stlouisfed.org":
            series = request.url.params["id"]
            return httpx.Response(200, text=(fixtures_dir / "fred" / f"fred_{series}.csv").read_text())
        return httpx.Response(200, content=(fixtures_dir / "boc" / "valet_observations_recent10.json").read_bytes())

    return httpx.Client(transport=httpx.MockTransport(handler))


def deps(client, asked, silent=frozenset(), silent_once=frozenset()) -> BuildDeps:
    return BuildDeps(
        http=client,
        sec=SecEdgar(client, "stock-advisor test@example.com"),
        universe=UNIVERSE.__getitem__,
        download=yahoo(asked, silent, silent_once),
        screen_sectors=lambda: {"AAPL": ("Technology", "Consumer Electronics"), "RY.TO": ("Financial Services", "Banks—Diversified")},
        sleep=lambda s: None,
    )


def test_a_build_writes_every_file_and_a_manifest(fixtures_dir, tmp_path):
    asked: list[list[str]] = []
    with web(fixtures_dir) as client:
        manifest = build(tmp_path, NOW, deps(client, asked), limit=10)
    assert set(manifest["files"]) == {
        "sectors.parquet", "prices_US.parquet", "prices_TSX.parquet",
        "tickers.parquet", "fundamentals.parquet", "macro.parquet",
        "events_US.parquet", "events_TSX.parquet",
    }
    assert (manifest["start"], manifest["end"]) == ("2018-10-24", "2026-10-24")
    assert json.loads((tmp_path / "manifest.json").read_text()) == manifest
    assert not (tmp_path / "companyfacts.zip").exists()  # the 1.4 GB download is deleted
    # each market's stocks come with its benchmark and sector ETFs
    assert asked[0][:3] == ["AAPL", "BRK-B", "JPM"] and {"SPY", "XLK", "XLF", "XLC"} <= set(asked[0])
    assert asked[1][0] == "RY.TO" and {"XIU.TO", "XFN.TO", "XEG.TO"} <= set(asked[1])
    assert manifest["unclassified"] == 2  # BRK.B and JPM had no label in this fake screen
    facts = pd.read_parquet(tmp_path / "fundamentals.parquet")
    assert set(facts["cik"]) == {320193, 19617, 1067983}
    tickers = pd.read_parquet(tmp_path / "tickers.parquet")
    assert list(tickers["symbol"]) == ["AAPL", "BRK.B", "JPM"]
    events = pd.read_parquet(tmp_path / "events_US.parquet")
    assert list(events.columns) == ["symbol", "day", "dividend", "split"]
    assert list(events.itertuples(index=False, name=None)) == [("AAPL", date(2026, 10, 23), 0.0, 4.0)]
    assert len(pd.read_parquet(tmp_path / "events_TSX.parquet")) == 0
    assert isinstance(manifest["peak_rss_mb"], int) and manifest["peak_rss_mb"] > 0


def test_a_symbol_yahoo_drops_once_is_asked_for_again(fixtures_dir, tmp_path):
    asked: list[list[str]] = []
    pauses: list[float] = []
    with web(fixtures_dir) as client:
        d = deps(client, asked, silent_once=frozenset({"XLC"}))
        d.sleep = pauses.append
        manifest = build(tmp_path, NOW, d, limit=10)
    assert asked[1] == ["XLC"]  # only the missing one, right after the market's first download
    assert PAUSE_SECONDS in pauses
    assert "XLC" in set(pd.read_parquet(tmp_path / "prices_US.parquet")["symbol"])
    assert manifest["missing"]["US"] == []


def test_a_missing_etf_fails_the_build(fixtures_dir, tmp_path):
    with web(fixtures_dir) as client, pytest.raises(BuildFailed, match="XLC"):
        build(tmp_path, NOW, deps(client, [], silent=frozenset({"XLC"})), limit=10)


def test_yahoo_missing_many_stocks_fails_the_build(fixtures_dir, tmp_path):
    with web(fixtures_dir) as client, pytest.raises(BuildFailed, match="no bars for 2 of 3 US stocks"):
        build(tmp_path, NOW, deps(client, [], silent=frozenset({"AAPL", "JPM"})), limit=10)


def test_a_short_universe_fails_the_full_build(fixtures_dir, tmp_path):
    with web(fixtures_dir) as client, pytest.raises(BuildFailed, match="universe too small"):
        build(tmp_path, NOW, deps(client, []))


def test_yahoo_throttling_the_second_ask_counts_its_symbols_as_missing(fixtures_dir, tmp_path, monkeypatch):
    real = build_module.download_history
    calls = []

    def throttled_retry(symbols, *args, **kwargs):
        calls.append(list(symbols))
        if len(calls) == 2:  # the market's retry of what it missed
            raise YahooThrottled("3 Yahoo downloads in a row came back empty")
        return real(symbols, *args, **kwargs)

    monkeypatch.setattr(build_module, "download_history", throttled_retry)
    with web(fixtures_dir) as client, pytest.raises(BuildFailed, match="no bars for 1 of 3 US stocks"):
        build(tmp_path, NOW, deps(client, [], silent_once=frozenset({"JPM"})), limit=10)


def fred_down(fixtures_dir, answer: Callable[[httpx.Request], httpx.Response] | None = None) -> httpx.Client:
    """The `web` fixtures, with FRED timing out on every request (or giving `answer`'s response)."""
    healthy = web(fixtures_dir)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "fred.stlouisfed.org":
            if answer is not None:
                return answer(request)
            raise httpx.ReadTimeout("The read operation timed out", request=request)
        return healthy._transport.handle_request(request)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_a_fred_that_never_answers_is_recorded_and_the_build_goes_on(fixtures_dir, tmp_path, caplog):
    # nothing trains on macro.parquet (spec §5.1), and FRED stalls requests from GitHub's runners
    with caplog.at_level(logging.WARNING, logger="advisor.training"), fred_down(fixtures_dir) as client:
        manifest = build(tmp_path, NOW, deps(client, []), limit=10)
    reason = "FRED did not answer for T10Y2Y after 6 tries (ReadTimeout: The read operation timed out)"
    assert manifest["unavailable"] == {"macro": reason}
    assert "failed" not in manifest
    assert "macro.parquet" not in manifest["files"] and not (tmp_path / "macro.parquet").exists()
    assert {"prices_US.parquet", "prices_TSX.parquet", "fundamentals.parquet"} <= set(manifest["files"])
    assert json.loads((tmp_path / "manifest.json").read_text()) == manifest
    assert any(r.levelno == logging.WARNING and reason in r.getMessage() for r in caplog.records)


def test_a_series_fred_refuses_still_fails_the_build(fixtures_dir, tmp_path):
    def refuse(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="Series not found")

    with fred_down(fixtures_dir, refuse) as client, pytest.raises(
        BuildFailed, match=r"macro step failed: FRED refused T10Y2Y \(HTTP 404\)"
    ):
        build(tmp_path, NOW, deps(client, []), limit=10)
    assert json.loads((tmp_path / "manifest.json").read_text())["failed"]["step"] == "macro"


def test_a_series_fred_sends_empty_still_fails_the_build(fixtures_dir, tmp_path):
    def empty(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=f"observation_date,{request.url.params['id']}\n")

    with fred_down(fixtures_dir, empty) as client, pytest.raises(
        BuildFailed, match="macro step failed: ValueError: FRED sent no values for T10Y2Y"
    ):
        build(tmp_path, NOW, deps(client, []), limit=10)


def test_a_failure_after_prices_leaves_them_listed_in_the_manifest(fixtures_dir, tmp_path, monkeypatch):
    def broken_zip(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("advisor.training.build.reduce_companyfacts", broken_zip)
    with web(fixtures_dir) as client, pytest.raises(BuildFailed, match="fundamentals step failed: OSError: disk full"):
        build(tmp_path, NOW, deps(client, []), limit=10)
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["failed"]["step"] == "fundamentals"
    assert {"prices_US.parquet", "prices_TSX.parquet", "macro.parquet", "tickers.parquet"} <= set(manifest["files"])


def test_progress_is_logged_without_changing_what_is_written(fixtures_dir, tmp_path, caplog):
    quiet, loud = tmp_path / "quiet", tmp_path / "loud"
    with web(fixtures_dir) as client:
        build(quiet, NOW, deps(client, []), limit=10)
    with caplog.at_level(logging.INFO, logger="advisor.training"), web(fixtures_dir) as client:
        build(loud, NOW, deps(client, []), limit=10)
    lines = [r.getMessage() for r in caplog.records]
    for expected in ("macro: FRED T10Y2Y", "macro: Bank of Canada", "prices US: download 1/1", "prices TSX: download 1/1",
                     "fundamentals: companyfacts", "done in"):
        assert any(expected in line for line in lines), expected
    for name in json.loads((quiet / "manifest.json").read_text())["files"]:
        assert pd.read_parquet(quiet / name).equals(pd.read_parquet(loud / name)), name


class NoSymbols:
    def __init__(self, client) -> None:
        pass

    def fetch(self, symbols, now):
        return []


def test_the_crypto_history_is_written_and_counted(fixtures_dir, tmp_path, monkeypatch):
    frame = pd.DataFrame({
        "symbol": ["BTC", "BTC"], "day": [date(2026, 10, 22), date(2026, 10, 23)],
        "open": [1.0, 1.0], "high": [1.0, 1.0], "low": [1.0, 1.0], "close": [1.0, 2.0], "volume": [3.0, 4.0],
    })

    def fake(client, end, limiter):
        assert end == date(2026, 10, 24)
        return frame, {"coins": 1, "rows": 2, "failures": 0}

    monkeypatch.setattr(build_module, "download_crypto", fake)
    with web(fixtures_dir) as client:
        manifest = build(tmp_path, NOW, deps(client, []), limit=10)
    saved = pd.read_parquet(tmp_path / "prices_crypto.parquet")
    assert saved["symbol"].tolist() == ["BTC", "BTC"]
    assert manifest["crypto"] == {"coins": 1, "rows": 2, "failures": 0}
    assert "crypto_error" not in manifest


def test_a_crypto_step_that_raises_leaves_the_stock_files(fixtures_dir, tmp_path, monkeypatch):
    def boom(client, end, limiter):
        raise RuntimeError("coinbase down")

    monkeypatch.setattr(build_module, "download_crypto", boom)
    with web(fixtures_dir) as client:
        manifest = build(tmp_path, NOW, deps(client, []), limit=10)
    assert "prices_US.parquet" in manifest["files"] and "prices_TSX.parquet" in manifest["files"]
    assert not (tmp_path / "prices_crypto.parquet").exists()
    assert "failed" not in manifest
    assert "coinbase down" in manifest["crypto_error"]


def test_main_logs_the_cause_with_its_traceback_and_quiets_httpx(monkeypatch, tmp_path, caplog):
    def broken_build(out, now, deps, limit=None):
        try:
            {}["cik"]
        except KeyError as exc:
            raise BuildFailed("fundamentals step failed: KeyError: 'cik'") from exc

    monkeypatch.setenv("SEC_USER_AGENT", "stock-advisor test@example.com")
    monkeypatch.setattr(build_module, "NasdaqSymbols", NoSymbols)
    monkeypatch.setattr(build_module, "TmxSymbols", NoSymbols)
    monkeypatch.setattr(build_module, "build", broken_build)
    httpx_log = logging.getLogger("httpx")
    monkeypatch.setattr(httpx_log, "level", httpx_log.level)  # restored after the test
    assert build_module.main(["--out", str(tmp_path), "--no-db"]) == 1
    (error,) = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert "fundamentals step failed: KeyError" in error.getMessage()
    assert error.exc_info is not None and error.exc_info[0] is KeyError  # the real traceback
    assert httpx_log.level == logging.WARNING  # httpx's per-request lines carry query strings
