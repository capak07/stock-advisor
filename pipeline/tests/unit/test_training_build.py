import io
import json
import zipfile
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
