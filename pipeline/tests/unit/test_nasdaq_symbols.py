from datetime import UTC, datetime

import httpx

from advisor.collectors.nasdaq_symbols import (
    NASDAQ_LISTED_URL,
    OTHER_LISTED_URL,
    NasdaqSymbols,
    parse_nasdaq_listed,
    parse_other_listed,
)

NOW = datetime(2026, 10, 14, 12, 15, tzinfo=UTC)


def test_parse_nasdaq_listed_keeps_only_common_stocks(fixtures_dir):
    text = (fixtures_dir / "nasdaqlisted.txt").read_text(encoding="utf-8")
    assert [(s.symbol, s.exchange) for s in parse_nasdaq_listed(text)] == [
        ("AAPL", "NASDAQ"),
        ("UAL", "NASDAQ"),   # "United" must not match the "unit" exclusion
        ("PFBC", "NASDAQ"),  # "Preferred Bank" is a common stock
    ]


def test_parse_other_listed_maps_exchanges_and_excludes_etfs_and_preferreds(fixtures_dir):
    text = (fixtures_dir / "otherlisted.txt").read_text(encoding="utf-8")
    assert [(s.symbol, s.exchange) for s in parse_other_listed(text)] == [
        ("BRK.B", "NYSE"),
        ("JPM", "NYSE"),
        ("TSM", "NYSE"),  # ADRs are kept
        ("AAPL", "NYSE"),
    ]


def test_fetch_merges_both_files_sorted_and_deduplicated(fixtures_dir):
    files = {
        NASDAQ_LISTED_URL: (fixtures_dir / "nasdaqlisted.txt").read_text(encoding="utf-8"),
        OTHER_LISTED_URL: (fixtures_dir / "otherlisted.txt").read_text(encoding="utf-8"),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=files[str(request.url)])

    collector = NasdaqSymbols(httpx.Client(transport=httpx.MockTransport(handler)))
    records = collector.fetch([], NOW)
    assert [(r.symbol, r.exchange) for r in records] == [
        ("AAPL", "NASDAQ"),  # the NASDAQ listing wins over the duplicate
        ("BRK.B", "NYSE"),
        ("JPM", "NYSE"),
        ("PFBC", "NASDAQ"),
        ("TSM", "NYSE"),
        ("UAL", "NASDAQ"),
    ]
