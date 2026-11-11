"""The day trade cycle and job, against a fake Yahoo client and a simulated clock (no real sleeping).

The made-up stocks trade at 10: the opening range is 9.80-10.20, the 9:45 bar closes at 10.40 on
3x the range volume (entry 10.40, stop 10.00, target 11.20, risk 0.40). Their 60-day history is
the same day over and over, ending at the target on the next bar ("win") or at the stop ("stop").
US cost 3.10% = 0.806R; TSX 0.10% = 0.026R.
"""

import os
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta

import psycopg
import pytest

from advisor.daytrade import cycle
from advisor.daytrade.__main__ import check_start, main
from advisor.daytrade.bars import Bar, SparkSeries, YahooClient, YahooError
from advisor.daytrade.cycle import MAX_CONFIRM, run_cycle, run_job
from advisor.daytrade.replay import seed_for
from advisor.daytrade.rule import session_for
from advisor.daytrade.scan import Listing
from advisor.daytrade.track import Outcome
from advisor.models import ET, Market, SymbolInfo
from advisor.store import repo

US, TSX = Market.US, Market.TSX
DAY = date(2026, 11, 12)  # a Thursday, both markets open all day
SPLIT = date(2026, 11, 27)  # NYSE closes at 13:00, the TSX trades a full day
SHORT = date(2026, 12, 24)  # both markets close at 13:00
CLOSED = date(2026, 12, 25)
US_COST_R = 3.10 / 100 * 10.4 / 0.4
TSX_COST_R = 0.10 / 100 * 10.4 / 0.4

RSS = """<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>{sym} wins a big contract</title><link>https://example.com/{sym}</link>
<pubDate>Thu, 12 Nov 2026 13:00:00 GMT</pubDate></item>
</channel></rss>"""


def et(h, m, s=0, day=DAY):
    return datetime.combine(day, time(h, m, s), tzinfo=ET)


def _bars(d: date, kind: str, close: time = time(16, 0), vol: float = 1000) -> list[Bar]:
    """One session of 5-minute bars. kind: win / stop (history), target / open / none / cand (today).
    'cand' passes stage 1 (closes above the range closes) but never breaks the range high."""
    open_ = datetime.combine(d, time(9, 30), tzinfo=ET)
    n = int((datetime.combine(d, close, tzinfo=ET) - open_) / timedelta(minutes=5))
    out = []
    for i in range(n):
        t = open_ + timedelta(minutes=5 * i)
        if i < 3:
            b = Bar(t, 10.0, 10.2, 9.8, 10.0, vol)
        elif kind == "cand":
            b = Bar(t, 10.1, 10.15, 10.05, 10.1, vol)
        elif kind == "none":
            b = Bar(t, 9.9, 9.95, 9.85, 9.9, 1000)
        elif i == 3:
            b = Bar(t, 10.0, 10.45, 9.95, 10.4, 3000)
        elif kind in ("win", "target"):
            b = Bar(t, 10.4, 11.44, 10.39, 10.4, 1000)
        elif kind == "stop":
            b = Bar(t, 10.4, 10.45, 9.9, 10.0, 1000) if i == 4 else Bar(t, 10.0, 11.0, 9.99, 10.0, 1000)
        else:  # open: drifts between the stop and the target all day
            b = Bar(t, 10.45, 10.5, 10.3, 10.45, 1000)
        out.append(b)
    return out


def _history(day: date, market: Market, sessions: int, stops: int) -> list[Bar]:
    days: list[date] = []
    d = day
    while len(days) < sessions:
        d -= timedelta(days=1)
        s = session_for(d, market)
        if s is not None and s.close.time() == time(16, 0):
            days.append(d)
    out: list[Bar] = []
    for k, d in enumerate(sorted(days)):
        out += _bars(d, "stop" if k < stops else "win")
    return out


def _yahoo(symbol: str) -> str:
    return symbol if symbol.endswith(".TO") else symbol.replace(".", "-")


@dataclass
class FakeClient(YahooClient):
    """Answers by Yahoo symbol. 'spark' gives today's closes; chart 1d today's bars; 60d history + today."""

    today: dict[str, list[Bar]]
    history: dict[str, list[Bar]]
    down: bool = False
    broken: set[str] = field(default_factory=set)  # their 1-day chart fails
    requests: list[tuple[str, object]] = field(default_factory=list)
    on_request: object = None

    def wait(self) -> None:
        pass

    def _hit(self, what: str, arg: object) -> None:
        self.requests.append((what, arg))
        if self.on_request is not None:
            self.on_request(what, arg)
        if self.down:
            raise YahooError("Yahoo answered HTTP 429 for /v7/finance/spark")

    def spark_series(self, symbols, rng, interval):
        self._hit("spark", tuple(symbols))
        return {
            s: SparkSeries([(b.start, b.close) for b in self.today[s]], sum(b.volume for b in self.today[s]))
            for s in symbols
            if s in self.today
        }

    def chart(self, symbol, rng, interval):
        self._hit(rng, symbol)
        if rng == "60d":
            if symbol not in self.history:
                raise YahooError(f"no data for {symbol}")
            return self.history[symbol] + self.today[symbol]
        if symbol in self.broken or symbol not in self.today:
            raise YahooError(f"no data for {symbol}")
        return self.today[symbol]

    def sparked(self) -> list[str]:
        return [s for what, arg in self.requests if what == "spark" for s in arg]


class FakeNews:
    def __init__(self) -> None:
        self.urls: list[str] = []

    def __call__(self, url: str) -> str:
        self.urls.append(url)
        sym = url.split("s=", 1)[1].split("&", 1)[0]
        return RSS.format(sym=sym)


class SimClock:
    def __init__(self, start: datetime) -> None:
        self.t = start

    def now(self) -> datetime:
        return self.t

    def sleep(self, seconds: float) -> None:
        assert seconds >= 0
        self.t += timedelta(seconds=seconds)


def _world(day: date, spec, close: dict | None = None):
    """spec: (symbol, market, today's kind, past stop sessions | 'short' | None)."""
    close = close or {}
    today, history, listings = {}, {}, []
    for sym, market, kind, stops in spec:
        y = _yahoo(sym)
        today[y] = _bars(day, kind, close.get(market, time(16, 0)))
        if stops == "short":
            history[y] = _history(day, market, 10, 0)
        elif stops is not None:
            history[y] = _history(day, market, 60, stops)
        listings.append(Listing(sym, market, sym + " Inc"))
    return FakeClient(today, history), listings


def _signals(db, day=DAY):
    return {r["symbol"]: r for r in repo.daytrade_signals_for(db, day)}


def _day(db, day=DAY):
    return db.execute("select * from daytrade_days where day = %s", (day,)).fetchone()


MAIN_SPEC = [
    ("AAA", US, "target", 0),
    ("BRK.B", US, "open", 6),
    ("CCC", US, "open", 12),
    ("DDD", US, "open", 40),
    ("RYY.TO", TSX, "open", 0),
    ("EEE", US, "none", 0),
    ("FFF", US, "open", "short"),
    ("GGG", US, "open", None),
]


def test_a_found_signal_gets_replay_history_headlines_cost_and_rank(db):
    client, listings = _world(DAY, MAIN_SPEC)
    news = FakeNews()
    r = run_cycle(db, client, listings, et(9, 50, 30), full=True, news_get=news)
    assert r["ok"] is True
    assert {lst.symbol for lst in r["candidates"]} == {"AAA", "BRK.B", "CCC", "DDD", "RYY.TO", "FFF", "GGG"}

    sig = _signals(db)
    assert set(sig) == {"AAA", "BRK.B", "CCC", "DDD", "RYY.TO", "FFF", "GGG"}
    a = sig["AAA"]
    assert a["trigger_at"] == et(9, 50)
    assert a["flat_by"] == et(15, 55)
    assert (float(a["entry"]), float(a["stop"]), float(a["target"])) == (10.4, 10.0, 11.2)
    assert (float(a["or_high"]), float(a["or_low"]), float(a["volume_x"])) == (10.2, 9.8, 3.0)
    assert float(a["cost_pct"]) == pytest.approx(3.10)
    assert float(a["cost_r"]) == pytest.approx(US_COST_R)
    assert a["history"]["fired"] == 60 and a["history"]["avg_r"] == pytest.approx(2.0)
    assert a["replay"]["replays"] == 10_000 and a["replay"]["sessions"] == 60
    assert float(a["net_history_r"]) == pytest.approx(2.0 - US_COST_R)
    assert float(a["net_replay_r"]) == pytest.approx(a["replay"]["avg_r"] - US_COST_R)
    assert a["headlines"] == [{
        "title": "AAA wins a big contract", "url": "https://example.com/AAA",
        "published_at": "2026-11-12T13:00:00+00:00", "outlet": "Yahoo Finance",
    }]
    # TSX pays only the spread; the Yahoo symbol of BRK.B is BRK-B.
    assert float(sig["RYY.TO"]["cost_r"]) == pytest.approx(TSX_COST_R)
    assert ("60d", "BRK-B") in client.requests
    assert sig["BRK.B"]["history"]["stop"] == 6
    # Eligible: fired >= 20 and both net R > 0. DDD's record is 0R before costs.
    assert {s: sig[s]["eligible"] for s in sig} == {
        "AAA": True, "BRK.B": True, "CCC": True, "DDD": False, "RYY.TO": True, "FFF": False, "GGG": False,
    }
    # Ranked by net history R: RYY.TO 1.974, AAA 1.194, BRK.B 0.894; CCC (0.594) is fourth.
    assert {s: sig[s]["rank"] for s in sig if sig[s]["rank"]} == {"RYY.TO": 1, "AAA": 2, "BRK.B": 3}
    assert {s: sig[s]["best_rank"] for s in sig if sig[s]["best_rank"]} == {"RYY.TO": 1, "AAA": 2, "BRK.B": 3}
    # Too little history: stored, not eligible, and the stats say why.
    assert sig["FFF"]["replay"] == {"skipped": "only 10 full past session(s); need at least 20"}
    assert sig["FFF"]["history"]["sessions"] == 10
    assert sig["FFF"]["net_replay_r"] is None and sig["FFF"]["net_history_r"] is None
    assert "skipped" in sig["GGG"]["replay"] and "skipped" in sig["GGG"]["history"]
    # Skipped stats still carry the market's flat-by.
    assert sig["FFF"]["flat_by"] == et(15, 55) and sig["GGG"]["flat_by"] == et(15, 55)
    assert r["errors"] == 2
    # Headlines for each new signal, by Yahoo symbol.
    assert sorted(u.split("s=")[1].split("&")[0] for u in news.urls) == sorted(
        ["AAA", "BRK-B", "CCC", "DDD", "RYY.TO", "FFF", "GGG"]
    )
    day = _day(db)
    assert (day["status"], day["cycles"], day["error"]) == ("scanning", 1, None)
    assert (day["scanned"], day["usable"], day["candidates"]) == (8, 8, 7)
    assert day["last_update"] == et(9, 50, 30)
    # All signals are open: no bar after the 9:45 trigger bar has closed yet.
    assert {s["status"] for s in sig.values()} == {"open"}


def test_stored_signals_are_tracked_not_replayed_again(db):
    client, listings = _world(DAY, MAIN_SPEC)
    news = FakeNews()
    first = run_cycle(db, client, listings, et(9, 50, 30), full=True, news_get=news)
    client.requests.clear()
    news.urls.clear()

    r = run_cycle(
        db, client, listings, et(9, 55, 30), full=False, news_get=news, candidates=first["candidates"]
    )
    assert r["ok"] is True
    # Every candidate already has a stored signal: none is scanned again, each is charted once (tracking).
    assert client.sparked() == []
    assert sorted(arg for what, arg in client.requests if what == "1d") == sorted(
        ["AAA", "BRK-B", "CCC", "DDD", "RYY.TO", "FFF", "GGG"]
    )
    assert not [q for q in client.requests if q[0] == "60d"]
    assert news.urls == []
    sig = _signals(db)
    a = sig["AAA"]
    assert a["status"] == "target"
    assert (a["exit_at"], float(a["exit_price"]), float(a["gross_r"])) == (et(9, 55), 11.2, 2.0)
    assert float(a["net_r"]) == pytest.approx(2.0 - US_COST_R)
    b = sig["BRK.B"]
    assert (b["status"], float(b["last_price"]), b["last_at"], b["net_r"]) == ("open", 10.45, et(9, 55), None)
    day = _day(db)
    assert (day["cycles"], day["last_update"]) == (2, et(9, 55, 30))
    # A candidates-only cycle keeps the full scan's counts.
    assert (day["scanned"], day["usable"], day["candidates"]) == (8, 8, 7)


def test_morning_job_schedule_full_every_15_minutes(db):
    client, listings = _world(DAY, [("AAA", US, "open", 0), ("EEE", US, "none", 0)])
    clock = SimClock(et(9, 35))
    news = FakeNews()
    out = run_job(db, client, listings, "morning", clock=clock.now, sleep=clock.sleep, news_get=news)
    cycles = out["cycles"]
    assert [(c["at"], c["full"]) for c in cycles[:4]] == [
        (et(9, 50, 30), True), (et(9, 55, 30), False), (et(10, 0, 30), False), (et(10, 5, 30), True),
    ]
    assert cycles[-1]["at"] == et(12, 35, 30)
    assert len(cycles) == 34
    assert all(c["full"] == (k % 3 == 0) for k, c in enumerate(cycles))
    # Full cycles read the whole list; the others only the candidates.
    # Once AAA has its signal it is tracked, not scanned: later full scans read only EEE, and the
    # cycles between have no candidates left to re-check.
    sparks = [arg for what, arg in client.requests if what == "spark"]
    assert sparks[0] == ("AAA", "EEE")
    assert sparks[1:] == [("EEE",)] * 11
    # Replayed and given headlines once.
    assert [q for q in client.requests if q[0] == "60d"] == [("60d", "AAA")]
    assert len(news.urls) == 1
    sig = _signals(db)["AAA"]
    assert (sig["rank"], sig["status"]) == (1, "open")
    day = _day(db)
    assert (day["status"], day["cycles"]) == ("scanning", 34)


def test_a_cycle_where_every_request_fails_records_the_error_and_the_next_runs(db):
    client, listings = _world(DAY, [("AAA", US, "open", 0)])
    client.down = True
    r = run_cycle(db, client, listings, et(9, 50, 30), full=True, news_get=FakeNews())
    assert r["ok"] is False
    day = _day(db)
    assert (day["status"], day["cycles"], day["last_update"]) == ("failed", 1, None)
    assert "no data" in day["error"]

    client.down = False
    r = run_cycle(db, client, listings, et(9, 55, 30), full=True, news_get=FakeNews())
    assert r["ok"] is True
    day = _day(db)
    assert (day["status"], day["cycles"], day["error"], day["last_update"]) == (
        "scanning", 2, None, et(9, 55, 30),
    )
    assert "AAA" in _signals(db)


def test_job_retries_a_full_scan_after_a_failed_one(db):
    client, listings = _world(DAY, [("AAA", US, "open", 0), ("EEE", US, "none", 0)])
    clock = SimClock(et(9, 35))
    client.on_request = lambda what, arg: setattr(client, "down", clock.now() < et(9, 51))
    out = run_job(db, client, listings, "morning", clock=clock.now, sleep=clock.sleep, news_get=FakeNews())
    c = out["cycles"]
    assert [(x["at"], x["full"], x["ok"]) for x in c[:3]] == [
        (et(9, 50, 30), True, False), (et(9, 55, 30), True, True), (et(10, 0, 30), False, True),
    ]
    assert c[4]["at"] == et(10, 10, 30) and c[4]["full"]


def test_a_long_cycle_skips_the_missed_bar(db):
    client, listings = _world(DAY, [("AAA", US, "open", 0), ("EEE", US, "none", 0)])
    clock = SimClock(et(9, 35))
    state = {"first": True}

    def slow(what, arg):
        if what == "spark" and state["first"]:
            state["first"] = False
            clock.t += timedelta(minutes=7)  # the first scan takes 7 minutes: 9:50:30 -> 9:57:30

    client.on_request = slow
    out = run_job(db, client, listings, "morning", clock=clock.now, sleep=clock.sleep, news_get=FakeNews())
    assert [(c["at"], c["full"]) for c in out["cycles"][:3]] == [
        (et(9, 50, 30), True), (et(10, 0, 30), False), (et(10, 5, 30), True),
    ]


def test_afternoon_job_closes_open_signals_flat_at_flat_by_and_marks_the_day_done(db):
    client, listings = _world(DAY, [("AAA", US, "open", 0), ("BBB", US, "open", 0), ("ZZZ", US, "open", 0)])
    # BBB's flat-by bar (15:50-15:55) never comes; its 15:45 bar closes at 10.50.
    bbb = client.today["BBB"]
    client.today["BBB"] = [b for b in bbb if b.start != et(15, 50)]
    k = next(i for i, b in enumerate(client.today["BBB"]) if b.start == et(15, 45))
    client.today["BBB"][k] = Bar(et(15, 45), 10.45, 10.5, 10.4, 10.5, 1000)
    news = FakeNews()
    first = run_cycle(db, client, listings, et(9, 50, 30), full=True, news_get=news)
    run_cycle(db, client, listings, et(9, 55, 30), full=False, news_get=news, candidates=first["candidates"])
    client.broken = {"ZZZ"}  # its chart fails all afternoon: it closes at the last stored price

    clock = SimClock(et(12, 35))
    out = run_job(db, client, listings, "afternoon", clock=clock.now, sleep=clock.sleep, news_get=news)
    assert (out["cycles"][0]["at"], out["cycles"][0]["full"]) == (et(12, 35, 30), True)
    assert out["cycles"][-1]["at"] == et(15, 55, 30)
    sig = _signals(db)
    a, b, z = sig["AAA"], sig["BBB"], sig["ZZZ"]
    assert (a["status"], a["exit_at"], float(a["exit_price"])) == ("flat", et(15, 55), 10.45)
    assert float(a["gross_r"]) == pytest.approx(0.125)
    assert float(a["net_r"]) == pytest.approx(0.125 - US_COST_R)
    assert (b["status"], b["exit_at"], float(b["exit_price"])) == ("flat", et(15, 55), 10.5)
    assert float(b["gross_r"]) == pytest.approx(0.25)
    assert (z["status"], z["exit_at"], float(z["exit_price"])) == ("flat", et(15, 55), 10.45)
    assert z["last_at"] == et(9, 55)
    day = _day(db)
    assert day["status"] == "done"
    assert clock.now() < et(15, 59)


def test_split_close_us_stops_at_1230_and_flats_at_1255_while_tsx_runs_on(db):
    us = session_for(SPLIT, US)
    assert (us.no_entries_after, us.flat_by) == (et(12, 30, day=SPLIT), et(12, 55, day=SPLIT))
    assert session_for(SPLIT, TSX).flat_by == et(15, 55, day=SPLIT)
    client, listings = _world(
        SPLIT,
        [("AAA", US, "open", 0), ("RYY.TO", TSX, "open", 0), ("UUU", US, "none", 0), ("TTT.TO", TSX, "none", 0)],
        close={US: time(13, 0)},
    )
    news = FakeNews()
    run_cycle(db, client, listings, et(9, 50, 30, day=SPLIT), full=True, news_get=news)
    assert set(_signals(db, SPLIT)) == {"AAA", "RYY.TO"}
    # Each signal stores its own market's flat-by: 12:55 for the US on a 13:00 close.
    stored = _signals(db, SPLIT)
    assert (stored["AAA"]["flat_by"], stored["RYY.TO"]["flat_by"]) == (et(12, 55, day=SPLIT), et(15, 55, day=SPLIT))
    client.requests.clear()

    clock = SimClock(et(12, 35, day=SPLIT))
    out = run_job(db, client, listings, "afternoon", clock=clock.now, sleep=clock.sleep, news_get=news)
    # The afternoon job runs on for the TSX; US listings are no longer scanned after 12:30.
    # (AAA and RYY.TO have signals: they are tracked, not scanned.)
    assert out["cycles"][-1]["at"] == et(15, 55, 30, day=SPLIT)
    assert set(client.sparked()) == {"TTT.TO"}
    sig = _signals(db, SPLIT)
    assert (sig["AAA"]["status"], sig["AAA"]["exit_at"]) == ("flat", et(12, 55, day=SPLIT))
    assert (sig["RYY.TO"]["status"], sig["RYY.TO"]["exit_at"]) == ("flat", et(15, 55, day=SPLIT))
    assert _day(db, SPLIT)["status"] == "done"


def test_tsx_only_day_scans_only_tsx_listings(db):
    holiday = date(2026, 11, 26)  # US Thanksgiving, the TSX is open
    client, listings = _world(holiday, [("AAA", US, "open", 0), ("RYY.TO", TSX, "open", 0)])
    run_cycle(db, client, listings, et(9, 50, 30, day=holiday), full=True, news_get=FakeNews())
    assert client.sparked() == ["RYY.TO"]
    assert set(_signals(db, holiday)) == {"RYY.TO"}


def _seed_symbols(db):
    repo.upsert_symbols(db, US, [SymbolInfo(symbol="AAA", market=US, name="AAA Inc", exchange="NASDAQ")])
    repo.upsert_symbols(db, TSX, [SymbolInfo(symbol="RYY.TO", market=TSX, name="RYY Corp", exchange="TSX")])


def test_afternoon_job_ends_early_when_every_open_market_closes_at_13(db, monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    _seed_symbols(db)
    client, _ = _world(
        SHORT, [("AAA", US, "open", 0), ("RYY.TO", TSX, "open", 0)], close={US: time(13, 0), TSX: time(13, 0)}
    )
    _, listings = _world(SHORT, [("AAA", US, "open", 0), ("RYY.TO", TSX, "open", 0)])
    run_cycle(db, client, listings, et(9, 50, 30, day=SHORT), full=True, news_get=FakeNews())
    assert set(_signals(db, SHORT)) == {"AAA", "RYY.TO"}
    clock = SimClock(et(12, 35, day=SHORT))
    rc = main(["--job", "afternoon"], clock=clock.now, sleep=clock.sleep, client=client, news_get=FakeNews())
    assert rc == 0
    assert clock.now() < et(12, 56, day=SHORT)
    sig = _signals(db, SHORT)
    assert {s: (r["status"], r["exit_at"]) for s, r in sig.items()} == {
        "AAA": ("flat", et(12, 55, day=SHORT)), "RYY.TO": ("flat", et(12, 55, day=SHORT)),
    }
    day = _day(db, SHORT)
    assert (day["status"], day["cycles"]) == ("done", 6)  # 9:50:30, then 12:35:30 ... 12:55:30


def test_job_exits_at_once_when_both_markets_are_closed(db, monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])

    def no_sleep(seconds):
        raise AssertionError("must not wait")

    rc = main(
        ["--job", "morning"], clock=lambda: datetime(2026, 12, 25, 14, 40, tzinfo=UTC), sleep=no_sleep
    )
    assert rc == 0
    assert "closed" in capsys.readouterr().out
    assert _day(db, CLOSED)["status"] == "closed"


@pytest.mark.parametrize(
    ("job", "at", "ok"),
    [
        ("morning", et(9, 14), False),  # more than 20 minutes early
        ("morning", et(9, 15), True),
        ("morning", et(9, 35), True),
        ("morning", et(9, 56), True),  # late: it runs the rest of its window
        ("morning", et(10, 35), True),  # inside the window (in EDT, see the cron test below)
        ("morning", et(12, 35, 30), True),  # its last cycle
        ("morning", et(12, 36), False),  # the window has ended
        ("morning", et(8, 35), False),  # the other DST dispatch in winter: too early
        ("afternoon", et(12, 15), True),
        ("afternoon", et(12, 41), True),  # queued behind the morning job
        ("afternoon", et(13, 35), True),
        ("afternoon", et(11, 35), False),  # the other DST dispatch in winter: too early
        ("afternoon", et(16, 30), False),
    ],
)
def test_guard_accepts_only_its_own_window(job, at, ok):
    assert (check_start(job, at) is None) is ok


def test_wrong_dst_start_exits_with_a_plain_line_and_writes_nothing(db, monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    rc = main(["--job", "morning", "--now", "2026-11-12T13:35:00+00:00"])  # 8:35 ET: too early
    assert rc == 0
    assert "window" in capsys.readouterr().out
    assert _day(db) is None


@pytest.mark.parametrize(
    ("day", "morning", "afternoon"),
    [
        (date(2026, 10, 14), "13:35", "16:35"),  # EDT (UTC-4): 9:35 and 12:35 ET
        (date(2026, 11, 12), "14:35", "17:35"),  # EST (UTC-5): 9:35 and 12:35 ET
    ],
)
def test_guard_lets_exactly_one_cron_dispatch_per_job_run(day, morning, afternoon):
    """In EST the wrong dispatches land at 8:35 and 11:35 ET: too early, refused at once. In EDT
    they land at 10:35 and 13:35 ET, inside the window, but the right job is running then in the
    same concurrency group (cancel-in-progress: false), so the wrong one waits and starts only when
    that job ends, after its window: refused. If the first job died, it runs as a harmless recovery."""

    def utc(hm):
        h, m = map(int, hm.split(":"))
        return datetime.combine(day, time(h, m), tzinfo=UTC)

    def job_end(job):
        # The job's last cycle starts 30 s after its last bar close and takes a little while.
        return cycle.last_close(job, day, cycle.open_sessions(day)) + cycle.CYCLE_DELAY + timedelta(minutes=1)

    def runs(job, times):
        out, busy_until = [], None
        for hm in times:
            start = utc(hm)
            if busy_until is not None and start < busy_until:
                start = busy_until  # it waits for the running job
            if check_start(job, start) is None:
                out.append(hm)
                busy_until = job_end(job)
        return out

    jobs = (("morning", ["13:35", "14:35"]), ("afternoon", ["16:35", "17:35"]))
    assert {job: runs(job, times) for job, times in jobs} == {"morning": [morning], "afternoon": [afternoon]}


def test_a_stored_signal_is_not_scanned_again_in_a_full_cycle(db):
    client, listings = _world(DAY, [("AAA", US, "open", 0), ("EEE", US, "none", 0)])
    run_cycle(db, client, listings, et(9, 50, 30), full=True, news_get=FakeNews())
    client.requests.clear()
    r = run_cycle(db, client, listings, et(9, 55, 30), full=True, news_get=FakeNews())
    assert r["ok"] is True
    assert client.sparked() == ["EEE"]
    assert [q for q in client.requests if q[0] == "1d"] == [("1d", "AAA")]  # tracking only


def test_stage_two_charts_at_most_200_a_cycle_and_the_rest_in_the_next(db):
    assert MAX_CONFIRM == 200
    today = {f"S{i:03d}": _bars(DAY, "cand", vol=1000 + i) for i in range(300)}
    client = FakeClient(today, {})
    listings = [Listing(sym, US, None) for sym in today]
    r = run_cycle(db, client, listings, et(10, 0, 30), full=True, news_get=FakeNews())
    assert r["ok"] is True and len(r["candidates"]) == 300
    charted = [arg for what, arg in client.requests if what == "1d"]
    assert sorted(charted) == [f"S{i:03d}" for i in range(100, 300)]
    # The next cycle charts the 100 smaller ones it had no room for (S000 is the least traded).
    client.requests.clear()
    r = run_cycle(
        db, client, listings, et(10, 5, 30), full=False, news_get=FakeNews(),
        candidates=r["candidates"], charted=r["charted"],
    )
    assert r["ok"] is True
    assert sorted(arg for what, arg in client.requests if what == "1d") == [f"S{i:03d}" for i in range(100)]
    # All 300 are charted and none has closed above its range high since: nothing to chart.
    client.requests.clear()
    r = run_cycle(
        db, client, listings, et(10, 10, 30), full=False, news_get=FakeNews(),
        candidates=r["candidates"], charted=r["charted"],
    )
    assert r["ok"] is True
    assert [q for q in client.requests if q[0] == "1d"] == []


def test_the_job_remembers_charted_candidates_and_charts_again_on_a_breakout(db, monkeypatch):
    monkeypatch.setattr(cycle, "MAX_CONFIRM", 2)
    client, listings = _world(DAY, [("S0", US, "cand", None), ("S1", US, "cand", None), ("S2", US, "cand", None)])
    # S0's 10:30 bar closes above its range high (10.20) on 3x the range volume.
    k = next(i for i, b in enumerate(client.today["S0"]) if b.start == et(10, 30))
    client.today["S0"][k] = Bar(et(10, 30), 10.1, 10.45, 10.05, 10.4, 3000)
    clock = SimClock(et(9, 35))
    run_job(db, client, listings, "morning", clock=clock.now, sleep=clock.sleep, news_get=FakeNews())
    charts = [arg for what, arg in client.requests if what == "1d"]
    # 9:50:30 charts two (a tie on price x volume goes by symbol), 9:55:30 the third, then
    # nothing until S0's breakout at 10:35:30; from then on S0 is tracked every cycle.
    assert charts[:4] == ["S0", "S1", "S2", "S0"]
    assert (charts.count("S1"), charts.count("S2")) == (1, 1)
    assert _signals(db)["S0"]["trigger_at"] == et(10, 35)


def test_a_cycle_whose_every_stage_two_chart_fails_is_recorded_as_failed(db):
    client, listings = _world(DAY, [("AAA", US, "open", 0), ("BBB", US, "open", 0)])
    client.on_request = lambda what, arg: setattr(client, "down", what == "1d")
    r = run_cycle(db, client, listings, et(9, 50, 30), full=True, news_get=FakeNews())
    assert (r["ok"], r["errors"]) == (False, 2)
    day = _day(db)
    assert (day["status"], day["last_update"]) == ("failed", None)
    assert "2 of 2 charts failed" in day["error"]
    assert _signals(db) == {}


def test_tracking_gives_up_after_five_failed_charts_in_a_row(db):
    client, listings = _world(DAY, [(f"S{i}", US, "open", 0) for i in range(8)])
    run_cycle(db, client, listings, et(9, 50, 30), full=True, news_get=FakeNews(), replays=100)
    assert len(_signals(db)) == 8
    client.requests.clear()
    client.down = True
    r = run_cycle(db, client, listings, et(9, 55, 30), full=False, news_get=FakeNews(), candidates=[])
    assert len([q for q in client.requests if q[0] == "1d"]) == 5
    assert (r["ok"], r["tracked"], r["errors"]) == (False, 0, 8)
    assert _day(db)["status"] == "failed"


def test_a_signal_finalize_could_not_close_is_closed_by_the_next_job(db, monkeypatch):
    client, listings = _world(DAY, [("AAA", US, "open", 0), ("BBB", US, "open", 0)])
    news = FakeNews()
    first = run_cycle(db, client, listings, et(9, 50, 30), full=True, news_get=news, replays=100)
    run_cycle(db, client, listings, et(9, 55, 30), full=False, news_get=news, candidates=first["candidates"])
    aaa = _signals(db)["AAA"]["id"]
    real = repo.update_daytrade_outcome

    def update(conn, id, outcome, net_r):
        if id == aaa and outcome.status == "flat":
            raise psycopg.OperationalError("server closed the connection unexpectedly")
        return real(conn, id, outcome, net_r)

    monkeypatch.setattr(repo, "update_daytrade_outcome", update)
    clock = SimClock(et(15, 50))
    run_job(db, client, listings, "afternoon", clock=clock.now, sleep=clock.sleep, news_get=news)
    sig = _signals(db)
    assert (sig["AAA"]["status"], sig["BBB"]["status"]) == ("open", "flat")
    assert _day(db)["status"] == "done"
    last_price = float(sig["AAA"]["last_price"])
    monkeypatch.setattr(repo, "update_daytrade_outcome", real)

    nxt = date(2026, 11, 13)
    clock = SimClock(et(12, 39, day=nxt))  # past the morning's last cycle: the job only tidies up
    run_job(db, client, listings, "morning", clock=clock.now, sleep=clock.sleep, news_get=news)
    a = _signals(db)["AAA"]
    assert (a["status"], a["exit_at"], float(a["exit_price"])) == ("flat", et(15, 55), last_price)
    # The afternoon job did run: the day keeps its status and gets no "finished late" note.
    assert (_day(db)["status"], _day(db)["error"]) == ("done", None)


def _yesterday_row(symbol, **over):
    row = {
        "day": date(2026, 11, 11), "symbol": symbol, "market": "US", "name": None,
        "trigger_at": et(9, 50, day=date(2026, 11, 11)), "entry": 10.4, "or_high": 10.2, "or_low": 9.8,
        "stop": 10.0, "target": 11.2, "volume_x": 3.0, "cost_pct": 3.1, "cost_r": US_COST_R,
        "replay": {}, "history": {}, "net_replay_r": None, "net_history_r": None, "eligible": False,
        "headlines": [], "flat_by": et(15, 55, day=date(2026, 11, 11)),
    }
    row.update(over)
    return row


def test_a_job_closes_earlier_days_left_open_at_their_last_stored_price(db):
    y, before, done = date(2026, 11, 11), date(2026, 11, 10), date(2026, 11, 9)
    repo.start_daytrade_day(db, y, "scanning")
    repo.start_daytrade_day(db, before, "failed")
    repo.update_daytrade_day(db, before, error="Yahoo gave no data this cycle")
    repo.start_daytrade_day(db, done, "done")
    a = repo.upsert_daytrade_signal(db, _yesterday_row("AAA"))
    repo.update_daytrade_outcome(db, a, Outcome("open", None, None, None, 10.5, et(14, 0, day=y)), None)
    repo.upsert_daytrade_signal(db, _yesterday_row("BBB"))  # never tracked: no stored price
    c = repo.upsert_daytrade_signal(db, _yesterday_row("CCC"))
    hit = et(10, 0, day=y)
    repo.update_daytrade_outcome(db, c, Outcome("target", hit, 11.2, 2.0, 11.3, hit), 2.0 - US_COST_R)

    client, listings = _world(DAY, [("AAA", US, "open", 0)])
    clock = SimClock(et(12, 39))  # past the morning's last cycle: the job only tidies up
    out = run_job(db, client, listings, "morning", clock=clock.now, sleep=clock.sleep, news_get=FakeNews())
    assert out["cycles"] == []
    assert client.requests == []  # no chart for a past day (it would be today's bars)

    sig = _signals(db, y)
    assert (sig["AAA"]["status"], sig["AAA"]["exit_at"], float(sig["AAA"]["exit_price"])) == (
        "flat", et(15, 55, day=y), 10.5,
    )
    assert float(sig["AAA"]["gross_r"]) == pytest.approx(0.25)
    assert float(sig["AAA"]["net_r"]) == pytest.approx(0.25 - US_COST_R)
    assert sig["AAA"]["last_at"] == et(14, 0, day=y)
    assert (sig["BBB"]["status"], float(sig["BBB"]["exit_price"]), float(sig["BBB"]["gross_r"])) == (
        "flat", 10.4, 0.0,
    )
    assert (sig["CCC"]["status"], float(sig["CCC"]["exit_price"])) == ("target", 11.2)
    late = "finished late: the afternoon job did not run"
    assert (_day(db, y)["status"], _day(db, y)["error"]) == ("done", late)
    assert (_day(db, before)["status"], _day(db, before)["error"]) == (
        "done", "Yahoo gave no data this cycle; " + late,
    )
    assert (_day(db, done)["status"], _day(db, done)["error"]) == ("done", None)


def test_unexpected_errors_on_one_signal_leave_the_others_processed(db, monkeypatch, capsys):
    client, listings = _world(
        DAY, [("AAA", US, "open", 0), ("BAD", US, "open", 0), ("ODD", US, "open", 0), ("ZZZ", US, "open", 0)]
    )
    real_upsert, real_replay, real_update = (
        repo.upsert_daytrade_signal, cycle.replay, repo.update_daytrade_outcome,
    )

    def upsert(conn, row):
        if row["symbol"] == "BAD":
            raise psycopg.errors.NumericValueOutOfRange("numeric field overflow")
        return real_upsert(conn, row)

    def odd_replay(history, plan, trigger, s, **kw):
        if kw["seed"] == seed_for(DAY, "ODD"):
            raise RuntimeError("odd bars")
        return real_replay(history, plan, trigger, s, **kw)

    monkeypatch.setattr(repo, "upsert_daytrade_signal", upsert)
    monkeypatch.setattr(cycle, "replay", odd_replay)
    r = run_cycle(db, client, listings, et(9, 50, 30), full=True, news_get=FakeNews())
    assert r["ok"] is True
    assert r["errors"] == 2
    assert set(_signals(db)) == {"AAA", "ZZZ"}
    out = capsys.readouterr().out
    assert "BAD" in out and "numeric field overflow" in out
    assert "ODD" in out and "odd bars" in out

    aaa = _signals(db)["AAA"]["id"]

    def update(conn, id, outcome, net_r):
        if id == aaa:
            raise psycopg.OperationalError("server closed the connection unexpectedly")
        return real_update(conn, id, outcome, net_r)

    monkeypatch.setattr(repo, "update_daytrade_outcome", update)
    r = run_cycle(db, client, listings, et(9, 55, 30), full=False, news_get=FakeNews(), candidates=[])
    assert r["ok"] is True and r["errors"] == 1 and r["tracked"] == 1
    assert _signals(db)["ZZZ"]["last_at"] == et(9, 55)
    assert "AAA" in capsys.readouterr().out


def test_an_error_escaping_a_cycle_fails_the_day_and_the_job_runs_on(db, monkeypatch):
    client, listings = _world(DAY, [("AAA", US, "open", 0), ("EEE", US, "none", 0)])
    real = repo.daytrade_settings
    calls, seen = [], []

    def settings(conn):
        calls.append(1)
        if len(calls) == 1:
            raise psycopg.OperationalError("connection to server lost")
        if len(calls) == 2:
            seen.append(_day(db))
        return real(conn)

    monkeypatch.setattr(repo, "daytrade_settings", settings)
    clock = SimClock(et(9, 35))
    lines: list[str] = []
    out = run_job(
        db, client, listings, "morning", clock=clock.now, sleep=clock.sleep, news_get=FakeNews(), log=lines.append
    )
    c = out["cycles"]
    assert (c[0]["at"], c[0]["ok"]) == (et(9, 50, 30), False)
    assert "connection to server lost" in lines[0]
    assert (c[1]["at"], c[1]["full"], c[1]["ok"]) == (et(9, 55, 30), True, True)
    assert seen[0]["status"] == "failed" and "connection to server lost" in seen[0]["error"]
    assert len(c) == 34
    assert _day(db)["status"] == "scanning"


def test_a_scan_that_bails_out_fails_the_cycle_keeps_the_counts_and_retries_full(db):
    client, listings = _world(DAY, [(f"S{i:03d}", US, "none", None) for i in range(120)])
    clock = SimClock(et(9, 35))
    snap: list[dict] = []

    def hook(what, arg):
        # Batches 2-6 of the 10:05:30 full scan fail: the scan bails out after 5 in a row.
        client.down = clock.now() == et(10, 5, 30) and what == "spark" and arg[0] != "S000"
        if clock.now() == et(10, 10, 30) and what == "spark" and arg[0] == "S000" and not snap:
            snap.append(_day(db))

    client.on_request = hook
    out = run_job(db, client, listings, "morning", clock=clock.now, sleep=clock.sleep, news_get=FakeNews())
    c = out["cycles"]
    assert [(x["at"], x["full"], x["ok"]) for x in c[3:5]] == [
        (et(10, 5, 30), True, False), (et(10, 10, 30), True, True),
    ]
    assert snap[0]["status"] == "failed" and snap[0]["error"]
    assert (snap[0]["scanned"], snap[0]["usable"]) == (120, 120)  # still the 9:50 scan's counts


def test_a_failed_scan_still_tracks_the_stored_signals(db):
    client, listings = _world(DAY, [("AAA", US, "open", 0)])
    run_cycle(db, client, listings, et(9, 50, 30), full=True, news_get=FakeNews())
    client.on_request = lambda what, arg: setattr(client, "down", what == "spark")
    listings = [*listings, Listing("EEE", US, None)]
    client.today["EEE"] = _bars(DAY, "none")
    r = run_cycle(db, client, listings, et(9, 55, 30), full=True, news_get=FakeNews())
    assert r["ok"] is False and r["tracked"] == 1
    assert _signals(db)["AAA"]["last_at"] == et(9, 55)
    day = _day(db)
    assert day["status"] == "failed" and "no data" in day["error"]


def _stronger_by_symbol(monkeypatch, entries):
    """Make each new signal's entry the given price (strength = entry / or_high - 1)."""
    real = cycle._new_signal

    def new_signal(client, f, *a, **kw):
        row, errors = real(client, f, *a, **kw)
        return {**row, "entry": entries.get(row["symbol"], row["entry"])}, errors

    monkeypatch.setattr(cycle, "_new_signal", new_signal)


def _skill(db):
    return {s: r["skill_rank"] for s, r in _signals(db).items() if r["skill_rank"]}


FIVE = [(s, US, "open", 0) for s in ("AAA", "BBB", "CCC", "DDD", "EEE")]


def test_a_cycle_with_five_new_signals_ranks_the_three_strongest(db, monkeypatch):
    client, listings = _world(DAY, FIVE)
    # or_high is 10.2. Ties (same entry) go to the earlier trigger, then the symbol.
    _stronger_by_symbol(monkeypatch, {"AAA": 10.3, "BBB": 10.9, "CCC": 10.5, "DDD": 10.5, "EEE": 10.4})
    r = run_cycle(db, client, listings, et(9, 50, 30), full=True, news_get=FakeNews())
    assert r["ok"] is True and r["errors"] == 0
    assert _skill(db) == {"BBB": 1, "CCC": 2, "DDD": 3}


def test_a_quiet_first_cycle_then_a_busy_one_fills_the_free_ranks(db, monkeypatch):
    client, listings = _world(DAY, FIVE)
    _stronger_by_symbol(monkeypatch, {"AAA": 10.25, "BBB": 10.9, "CCC": 10.3, "DDD": 10.6, "EEE": 10.4})
    run_cycle(db, client, listings[:1], et(9, 50, 30), full=True, news_get=FakeNews())
    assert _skill(db) == {"AAA": 1}
    run_cycle(db, client, listings, et(10, 5, 30), full=True, news_get=FakeNews())
    assert _skill(db) == {"AAA": 1, "BBB": 2, "DDD": 3}


def test_a_restart_leaves_the_stored_skill_ranks_alone(db, monkeypatch):
    client, listings = _world(DAY, FIVE)
    _stronger_by_symbol(monkeypatch, {"AAA": 10.3, "BBB": 10.9, "CCC": 10.5, "DDD": 10.6, "EEE": 10.4})
    run_cycle(db, client, listings, et(9, 50, 30), full=True, news_get=FakeNews())
    before = _skill(db)
    assert before == {"BBB": 1, "DDD": 2, "CCC": 3}
    run_cycle(db, client, listings, et(9, 50, 30), full=True, news_get=FakeNews())
    run_cycle(db, client, listings, et(10, 5, 30), full=True, news_get=FakeNews())
    assert _skill(db) == before


def test_a_failing_skill_ranking_is_counted_and_does_not_fail_the_cycle(db, monkeypatch):
    client, listings = _world(DAY, FIVE[:2])

    def boom(conn, day, ids):
        raise psycopg.OperationalError("connection lost")

    monkeypatch.setattr(repo, "assign_skill_ranks", boom)
    r = run_cycle(db, client, listings, et(9, 50, 30), full=True, news_get=FakeNews())
    assert r["ok"] is True and r["new"] == 2 and r["errors"] == 1
    assert _skill(db) == {}
