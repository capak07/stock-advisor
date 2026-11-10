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


def test_candidates_past_the_cap_are_charted_in_later_cycles_and_never_twice_without_a_breakout():
    # Five candidates that close at the range's top close (10.00) but never above its high (10.01).
    day = NOW.date()
    closes = [10.0] * 14  # 9:30 to 10:35
    charts = {f"S{i}": _flat(day, closes, 1000 + i) for i in range(5)}
    fake = FakeClient(charts)
    ls = [Listing(s, Market.US) for s in charts]
    memory = None
    calls = []
    for k in range(4):
        fake.chart_calls = []
        r = scan(fake, ls, NOW + timedelta(minutes=5 * k), min_volume_x=0, max_confirm=2, charted=memory)
        assert len(r.candidates) == 5
        calls.append(fake.chart_calls)
        memory = r.charted
    # Most traded first, at most 2 a cycle; each charted once, then left until a bar closes above its high.
    assert calls == [["S4", "S3"], ["S2", "S1"], ["S0"], []]
    assert memory["S0"] == (10.01, datetime(2026, 10, 19, 10, 25, tzinfo=ET))


def test_a_charted_candidate_is_charted_again_only_when_a_new_bar_closes_above_its_range_high():
    day = NOW.date()
    flat = [10.0] * 3 + [10.0] * 6  # 9:30 to 10:10, never above the range high 10.01
    charts = {
        "UP": _flat(day, flat + [10.5, 10.5], 1000),  # the 10:15 bar closes above the range high
        "FLAT": _flat(day, flat + [10.0, 10.0], 1000),  # new bars, all under it
        # Closed above the high at 9:45 on thin volume (no trigger); its new bars are under it.
        "OLD": _flat(day, [10.0] * 3 + [10.5] + [10.0] * 7, 1000),
    }
    fake = FakeClient(charts)
    ls = [Listing(s, Market.US) for s in charts]
    r1 = scan(fake, ls, NOW, min_volume_x=1.5)
    assert sorted(fake.chart_calls) == ["FLAT", "OLD", "UP"]
    assert r1.found == []
    assert r1.charted["UP"] == (10.01, datetime(2026, 10, 19, 10, 10, tzinfo=ET))

    fake.chart_calls = []
    r2 = scan(fake, ls, NOW + timedelta(minutes=5), min_volume_x=0, charted=r1.charted)
    assert fake.chart_calls == ["UP"]
    assert [f.listing.symbol for f in r2.found] == ["UP"]
    assert r2.charted["FLAT"] == (10.01, datetime(2026, 10, 19, 10, 15, tzinfo=ET))


class ChartsDown(FakeClient):
    def chart(self, symbol, rng, interval):
        self.chart_calls.append(symbol)
        raise YahooError("Yahoo answered HTTP 429 for /v8/finance/chart")


def test_stage_two_gives_up_after_five_failed_charts_in_a_row():
    day = NOW.date()
    base = [10.0] * 3 + [10.5] * 6
    charts = {f"S{i}": _flat(day, base, 1000 + i) for i in range(8)}
    fake = ChartsDown(charts)
    r = scan(fake, [Listing(s, Market.US) for s in charts], NOW, min_volume_x=0)
    assert fake.chart_calls == ["S7", "S6", "S5", "S4", "S3"]
    assert (r.errors, r.confirm, r.confirm_failed, r.found) == (8, 8, 8, [])
    assert r.charted == {}  # nothing charted: all are tried again next cycle


def test_a_chart_that_works_restarts_the_failure_count():
    day = NOW.date()
    base = [10.0] * 3 + [10.5] * 6

    class Flaky(FakeClient):
        def chart(self, symbol, rng, interval):
            self.chart_calls.append(symbol)
            if symbol in ("S9", "S7", "S6", "S5", "S4"):
                raise YahooError("down")
            return self.charts[symbol]

    charts = {f"S{i}": _flat(day, base, 1000 + i) for i in range(10)}
    fake = Flaky(charts)
    r = scan(fake, [Listing(s, Market.US) for s in charts], NOW, min_volume_x=0)
    # S9 fails, S8 works (the streak restarts), then S7..S4 fail: four in a row, so S3..S0 are charted.
    assert fake.chart_calls == [f"S{i}" for i in range(9, -1, -1)]
    assert (r.errors, r.confirm, r.confirm_failed) == (5, 10, 5)
    assert len(r.found) == 5


def test_a_spark_column_longer_than_its_timestamps_is_counted_not_raised():
    def item(sym, n_close):
        quote = {"close": [10.0] * n_close, "volume": [5, 5]}
        return {"symbol": sym, "response": [{"timestamp": [1792416600, 1792416900], "indicators": {"quote": [quote]}}]}

    doc = {"spark": {"result": [item("OK", 2), item("BAD", 3)], "error": None}}
    client = YahooClient(get=lambda url: json.dumps(doc), sleep=lambda s: None)
    r = scan(client, [Listing("OK", Market.US), Listing("BAD", Market.US)], NOW)
    assert (r.scanned, r.errors) == (1, 1)


def test_when_re_charts_exceed_the_cap_the_oldest_checked_go_first_and_new_ones_still_get_charted():
    # R0-R2 keep closing above their range high (10.01) on thin volume: never a trigger, so each is
    # a re-chart every cycle. N is never charted and the least traded. The cap is 2.
    day = NOW.date()
    up = [10.0] * 3 + [10.5] * 11  # 9:30 to 10:35
    charts = {f"R{i}": _flat(day, up, 1000 + i) for i in range(3)}
    fake = FakeClient(charts)
    r = scan(fake, [Listing(s, Market.US) for s in charts], NOW, min_volume_x=100)
    assert sorted(fake.chart_calls) == ["R0", "R1", "R2"]
    memory = r.charted

    fake.charts["N"] = _flat(day, up, 500)
    ls = [Listing(s, Market.US) for s in fake.charts]
    calls = []
    for k in range(1, 4):
        fake.chart_calls = []
        r = scan(fake, ls, NOW + timedelta(minutes=5 * k), min_volume_x=100, max_confirm=2, charted=memory)
        calls.append(fake.chart_calls)
        memory = r.charted
    # Oldest checked bar first (never charted counts as oldest), then most traded: everyone takes a turn.
    assert calls == [["N", "R2"], ["R1", "R0"], ["R2", "N"]]
