import gzip
import json
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

from advisor.daytrade.bars import Bar, SparkSeries, YahooClient, YahooError, _parse_chart
from advisor.daytrade.scan import Listing, scan
from advisor.models import ET, Market

FIX = Path(__file__).parent.parent / "fixtures" / "daytrade"
NOW = datetime(2026, 10, 19, 10, 15, tzinfo=ET)


class FakeClient(YahooClient):
    """Answers from parsed charts, keyed by Yahoo symbol; spark gives closes and day volume."""

    def __init__(self, charts: dict[str, list[Bar]], spark: dict | None = None) -> None:
        self.charts = charts
        self.spark = spark
        self.asked: list[str] = []
        self.chart_calls: list[str] = []
        self.events: list[str] = []

    def wait(self) -> None:
        self.events.append("wait")

    def spark_series(self, symbols, rng, interval):
        self.asked += list(symbols)
        self.events.append("spark")
        if self.spark is not None:
            return {s: self.spark[s] for s in symbols if s in self.spark}
        return {
            s: SparkSeries([(b.start, b.close) for b in self.charts[s]], sum(b.volume for b in self.charts[s]))
            for s in symbols
            if s in self.charts
        }

    def chart(self, symbol, rng, interval):
        self.chart_calls.append(symbol)
        self.events.append("chart")
        if symbol not in self.charts:
            raise YahooError("no data")
        return self.charts[symbol]


def _shift(bars, day):
    return [replace(b, start=b.start.replace(year=day.year, month=day.month, day=day.day)) for b in bars]


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


def test_yahoo_symbol_round_trip():
    client, _ = _wall()
    charts = {"BRK-B": client.charts["TSLA"]}
    fake = FakeClient(charts)
    r = scan(fake, [Listing("BRK.B", Market.US, "Berkshire")], NOW, min_price=0, min_volume_x=0)
    assert fake.asked == ["BRK-B"]
    assert [f.listing.symbol for f in r.found] == ["BRK.B"]
    assert r.candidates[0].name == "Berkshire"


def _flat(day, closes, vols, top=None):
    """9:30 to 10:10 bars (9 bars) with the given closes/volume; range closes at 10.0, later at `closes`."""
    out = []
    for k, c in enumerate(closes):
        t0 = datetime(day.year, day.month, day.day, 9, 30, tzinfo=ET) + timedelta(minutes=5 * k)
        out.append(Bar(t0, c, c + 0.01, c - 0.01, c, vols))
    return out


def test_max_confirm_picks_the_most_traded():
    day = NOW.date()
    base = [10.0] * 3 + [10.5] * 6
    mk = lambda px, v: _flat(day, [c * px / 10 for c in base], v)  # noqa: E731
    charts = {"THIN": mk(400, 1000), "BUSY": mk(30, 900_000), "MID": mk(50, 50_000), "TIE": mk(50, 50_000)}
    fake = FakeClient(charts)
    ls = [Listing(s, Market.US) for s in charts]
    r = scan(fake, ls, NOW, min_volume_x=0, max_confirm=2)
    assert [c.symbol for c in r.candidates] == ["BUSY", "MID", "TIE", "THIN"]
    assert fake.chart_calls == ["BUSY", "MID"]
    assert sorted(f.listing.symbol for f in r.found) == ["BUSY", "MID"]


def test_pauses_between_requests():
    client, _ = _wall()
    day = NOW.date()
    base = [10.0] * 3 + [10.5] * 6
    charts = {f"S{i}": _flat(day, base, 1000) for i in range(25)}
    fake = FakeClient(charts)
    scan(fake, [Listing(s, Market.US) for s in charts], NOW, min_volume_x=0, max_confirm=3)
    assert fake.events == ["spark", "wait", "spark", "chart", "wait", "chart", "wait", "chart"]


def test_tsx_holiday_while_nyse_open_and_the_reverse():
    client, _ = _wall()
    for day, only in ((datetime(2026, 10, 12).date(), "AAPL"), (datetime(2026, 11, 26).date(), "SHOP.TO")):
        bars = _shift(client.charts["TSLA"], day)
        fake = FakeClient({"AAPL": bars, "SHOP.TO": bars})
        now = datetime(day.year, day.month, day.day, 10, 15, tzinfo=ET)
        ls = [Listing("AAPL", Market.US), Listing("SHOP.TO", Market.TSX)]
        r = scan(fake, ls, now, min_price=0, min_volume_x=0)
        assert fake.asked == [only], day
        assert [f.listing.symbol for f in r.found] == [only]
        assert r.scanned == 1


def test_incomplete_range_is_unusable_not_a_signal():
    client, _ = _wall()
    bars = [b for b in client.charts["TSLA"] if b.start.minute != 35 or b.start.hour != 9]
    r = scan(FakeClient({"TSLA": bars}), [Listing("TSLA", Market.US)], NOW, min_price=0, min_volume_x=0)
    assert (r.scanned, r.usable, r.errors, r.found, r.candidates) == (1, 0, 0, [], [])


def test_spark_live_tick_and_in_progress_bar_are_ignored():
    client, _ = _wall()
    bars = [b for b in client.charts["TSLA"] if b.start < NOW]
    pts = [(b.start, b.close) for b in bars]
    pts.append((NOW.replace(minute=10, second=7), 999.0))  # live tick off the grid
    pts.append((NOW, 999.0))  # the 10:15 bar is still in progress at the cutoff
    fake = FakeClient({"TSLA": client.charts["TSLA"]}, spark={"TSLA": SparkSeries(pts, 1.0)})
    r = scan(fake, [Listing("TSLA", Market.US)], NOW, min_price=0, min_volume_x=0)
    assert r.usable == 1
    assert r.found[0].trigger.entry == 364.18  # chart, not the 999 points


def test_empty_spark_answer_counts_errors():
    client, listings = _wall()
    r = scan(FakeClient(client.charts, spark={}), listings[:4], NOW)
    assert (r.scanned, r.usable, r.errors, r.found) == (0, 0, 4, [])


def test_unusable_stage2_chart_is_not_an_error():
    client, _ = _wall()
    full = client.charts["TSLA"]
    holey = [b for b in full if not (b.start.hour == 9 and b.start.minute == 50)]
    fake = FakeClient({"TSLA": holey}, spark={"TSLA": SparkSeries([(b.start, b.close) for b in full], 5.0)})
    r = scan(fake, [Listing("TSLA", Market.US)], NOW, min_price=0, min_volume_x=0)
    assert (r.errors, r.unusable, r.found) == (0, 1, [])
    assert len(r.candidates) == 1


def test_failed_spark_batch_counts_errors():
    class Broken(FakeClient):
        def spark_series(self, symbols, rng, interval):
            raise YahooError("down")

    client, listings = _wall()
    r = scan(Broken(client.charts), listings[:3], NOW)
    assert (r.errors, r.scanned, r.found) == (3, 0, [])


def test_gives_up_after_five_failed_batches_in_a_row():
    class Broken(FakeClient):
        def spark_series(self, symbols, rng, interval):
            self.asked.append("batch")
            raise YahooError("down")

    client, _ = _wall()
    fake = Broken(client.charts)
    ls = [Listing(f"S{i}", Market.US) for i in range(200)]
    r = scan(fake, ls, NOW)
    assert fake.asked == ["batch"] * 5
    assert (r.errors, r.scanned, r.found) == (200, 0, [])
