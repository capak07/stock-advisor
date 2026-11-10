import gzip
import json
from datetime import datetime
from pathlib import Path

from advisor.daytrade.bars import Bar, YahooClient, YahooError, _parse_chart
from advisor.daytrade.scan import Listing, scan
from advisor.models import ET, Market

FIX = Path(__file__).parent.parent / "fixtures" / "daytrade"
NOW = datetime(2026, 10, 19, 10, 15, tzinfo=ET)


class FakeClient(YahooClient):
    """Answers from parsed charts, keyed by Yahoo symbol; spark gives closes only."""

    def __init__(self, charts: dict[str, list[Bar]]) -> None:
        self.charts = charts
        self.asked: list[str] = []

    def spark_closes(self, symbols, rng, interval):
        self.asked += list(symbols)
        return {s: [(b.start, b.close) for b in self.charts[s]] for s in symbols if s in self.charts}

    def chart(self, symbol, rng, interval):
        if symbol not in self.charts:
            raise YahooError("no data")
        return self.charts[symbol]


def _wall():
    doc = json.loads(gzip.open(FIX / "wall5m-2026-10-19.json.gz", "rt", encoding="utf-8").read())
    charts = {}
    for sym, d in doc.items():
        try:
            charts[sym] = _parse_chart(json.dumps(d), sym)
        except YahooError:
            pass
    listings = [Listing(s, Market.US, None) for s in doc]
    return FakeClient(charts), listings


def test_skill_result_on_the_wall():
    client, listings = _wall()
    r = scan(client, listings, NOW, min_price=0, min_volume_x=0)
    assert (r.scanned, r.usable) == (233, 231)
    assert len(r.found) == 42
    assert len(r.candidates) == 95
    assert r.errors == 1  # SQ has no data
    tsla = next(f for f in r.found if f.listing.symbol == "TSLA")
    assert tsla.trigger.at == datetime(2026, 10, 19, 10, 15, tzinfo=ET)
    assert tsla.trigger.entry == 364.18
    assert round(tsla.rng.high, 2) == 362.18


def test_default_price_floor_gives_41():
    client, listings = _wall()
    r = scan(client, listings, NOW, min_volume_x=0)
    assert len(r.found) == 41


def test_default_volume_filter():
    client, listings = _wall()
    r = scan(client, listings, NOW, min_price=0)
    assert 0 < len(r.found) < 42
    assert all(f.trigger.volume_x >= 1.5 for f in r.found)


def test_max_confirm_limits_chart_calls():
    client, listings = _wall()
    r = scan(client, listings, NOW, min_price=0, min_volume_x=0, max_confirm=5)
    assert len(r.candidates) == 95
    assert len(r.found) <= 5


def test_yahoo_symbol_round_trip():
    client, _ = _wall()
    charts = {"BRK-B": client.charts["TSLA"]}
    fake = FakeClient(charts)
    r = scan(fake, [Listing("BRK.B", Market.US, "Berkshire")], NOW, min_price=0, min_volume_x=0)
    assert fake.asked == ["BRK-B"]
    assert [f.listing.symbol for f in r.found] == ["BRK.B"]
    assert r.candidates[0].name == "Berkshire"


def test_tsx_uses_its_own_session_and_closed_market_is_skipped():
    client, _ = _wall()
    fake = FakeClient({"SHOP.TO": client.charts["TSLA"]})
    r = scan(fake, [Listing("SHOP.TO", Market.TSX)], NOW, min_price=0, min_volume_x=0)
    assert [f.listing.symbol for f in r.found] == ["SHOP.TO"]
    assert r.found[0].plan.flat_by == datetime(2026, 10, 19, 15, 55, tzinfo=ET)
    sunday = datetime(2026, 10, 18, 10, 15, tzinfo=ET)
    r = scan(fake, [Listing("SHOP.TO", Market.TSX)], sunday)
    assert (r.scanned, r.usable, r.errors, r.found) == (0, 0, 0, [])


def test_failed_spark_batch_counts_errors():
    class Broken(FakeClient):
        def spark_closes(self, symbols, rng, interval):
            raise YahooError("down")

    client, listings = _wall()
    r = scan(Broken(client.charts), listings[:3], NOW)
    assert (r.errors, r.scanned, r.found) == (3, 0, [])
