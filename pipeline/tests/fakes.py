"""Test doubles and builders shared by unit and integration tests."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx
from pydantic import BaseModel

from advisor.collectors.base import Cadence, Category, Scope
from advisor.collectors.sec import (
    COMPANYFACTS_URL,
    SUBMISSIONS_URL,
    TICKERS_URL,
    SecEdgar,
    archive_url,
)
from advisor.markets import market_of
from advisor.models import AssetType, DailyBar, Market, SymbolInfo


class FakeClock:
    """Monotonic clock whose sleep() advances time instantly and records the duration."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@dataclass
class FakeCollector:
    name: str
    records_for: Callable[[Sequence[str]], list[BaseModel]] = lambda symbols: []
    error: Exception | None = None
    core: bool = True
    best_effort: bool = False
    category: Category = Category.PRICES
    cadence: Cadence = Cadence.PER_RUN
    asset_types: frozenset[AssetType] = frozenset({AssetType.STOCK})
    markets: frozenset[Market] = frozenset(Market)
    record_type: type[BaseModel] = DailyBar
    freshness: timedelta | None = None
    scope: Scope = Scope.SYMBOLS
    canary: tuple[str, ...] = ()
    canary_requires_records: bool = False
    max_symbols: int | None = None
    calls: list[list[str]] = field(default_factory=list)

    def fetch(self, symbols: Sequence[str], as_of: datetime) -> list[BaseModel]:
        self.calls.append(list(symbols))
        if self.error is not None:
            raise self.error
        return list(self.records_for(symbols))


def info(symbol: str, exchange: str | None = None) -> SymbolInfo:
    market = market_of(symbol)
    default_exchange = "TSX" if market is Market.TSX else "NYSE"
    return SymbolInfo(
        symbol=symbol,
        market=market,
        name=f"{symbol} Inc. Common Stock",
        exchange=exchange or default_exchange,
    )


def bar(
    symbol: str, day: date, close: float, volume: float = 200_000.0, source: str = "yfinance"
) -> DailyBar:
    return DailyBar(
        symbol=symbol, day=day, open=close, high=close, low=close, close=close,
        volume=volume, source=source,
    )


def history(
    symbol: str,
    days: int,
    close: float = 10.0,
    volume: float = 200_000.0,
    source: str = "yfinance",
    start: date = date(2026, 6, 1),
) -> list[DailyBar]:
    return [bar(symbol, start + timedelta(days=i), close, volume, source) for i in range(days)]


FRESH_START = date(2026, 8, 5)  # 70 daily bars from here end 2026-10-13, fresh for a 2026-10-14 run


def fake_price_collectors(
    universe: Sequence[str] = ("AAA", "BBB", "CCC"), tsx: Sequence[str] = ("RY.TO", "TD.TO")
) -> dict[str, FakeCollector]:
    """US and TSX universe fakes plus a Yahoo price fake returning fresh 70-day histories."""

    def directory(name: str, symbols: Sequence[str]) -> FakeCollector:
        return FakeCollector(
            name,
            records_for=lambda _: [info(s) for s in symbols],
            record_type=SymbolInfo,
            cadence=Cadence.DAILY,
            scope=Scope.UNIVERSE,
            freshness=timedelta(days=3),
        )

    return {
        "nasdaq_symbols": directory("nasdaq_symbols", universe),
        "tmx_symbols": directory("tmx_symbols", tsx),
        "yfinance_bars": FakeCollector(
            "yfinance_bars",
            best_effort=True,
            records_for=lambda syms: [b for s in syms for b in history(s, 70, start=FRESH_START)],
        ),
    }


SEC_CONTACT = "stock-advisor test@example.com"


def fake_sec(
    routes: dict[str, bytes | int],
    *,
    documents: Path | None = None,
    seen: list[httpx.Request] | None = None,
    user_agent: str | None = SEC_CONTACT,
) -> SecEdgar:
    """A SecEdgar answering from `routes` (URL -> body, or an HTTP status); other URLs get 404."""

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        answer = routes.get(str(request.url), 404)
        if isinstance(answer, int):
            return httpx.Response(answer)
        return httpx.Response(200, content=answer)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    return SecEdgar(client, user_agent, documents=documents, sleep=lambda seconds: None)


def sec_routes(fixtures_dir: Path) -> dict[str, bytes]:
    """Recorded SEC answers for AAPL, PFE and GOOGL (see pipeline/tests/fixtures/sec)."""
    sec = fixtures_dir / "sec"

    def read(name: str) -> bytes:
        return (sec / name).read_bytes()

    form4 = {
        "0001140361-26-039158": "form4_sample.xml",  # officer sale under a 10b5-1 plan
        "0001140361-26-038674": "form4_sample_multi_MFSG_derivative.xml",  # CEO: M, F, S, G
        "0001140361-26-038672": "form4_sample_rsu_grant_A_derivative.xml",  # RSU grants
        "0001140361-26-038669": "form4_sample_director_open_market_buy_P.xml",  # a Boeing document
        "0001140361-26-038667": "form4_sample_director_open_market_buy_P.xml",  # a Boeing document
    }
    schedules = {
        (320193, "0002100119-26-000139"), (320193, "0000102909-26-000630"),
        (78003, "0002100119-26-001294"), (78003, "0000102909-26-002101"),  # Apple's 13G: wrong issuer
    }
    routes = {
        TICKERS_URL: read("company_tickers.json"),
        SUBMISSIONS_URL.format(cik=320193): read("submissions_AAPL_trimmed.json"),
        SUBMISSIONS_URL.format(cik=78003): read("submissions_PFE_trimmed_13dg_self_vs_subject.json"),
        COMPANYFACTS_URL.format(cik=320193): read("companyfacts_AAPL_trimmed.json"),
        COMPANYFACTS_URL.format(cik=1652044): read("companyfacts_GOOGL_trimmed.json"),
    }
    for accession, name in form4.items():
        routes[archive_url(320193, accession, "form4.xml")] = read(name)
    for cik, accession in schedules:
        routes[archive_url(cik, accession, "primary_doc.xml")] = read("schedule13g_A_sample_primary_doc.xml")
    return routes
