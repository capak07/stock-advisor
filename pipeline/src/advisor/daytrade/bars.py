"""Yahoo Finance bars for the day trade tab: HTTP client, spark and chart parsing, session slicing.

Ported from the day-trader skill (MIT, github.com/Jakeschincariol/day-trader-skill):
scan.py (yahoo_get, spark_path, chart_path, series_from_result, parse_spark, session_bars)
and entry.py (the live-tick handling).
"""

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from datetime import time as dtime
from typing import Any

from advisor.models import ET

UA = "Mozilla/5.0 (compatible; stock-advisor; +https://github.com/capak07/stock-advisor)"
HOSTS = ("https://query2.finance.yahoo.com", "https://query1.finance.yahoo.com")
BACKOFF_S = 5.0
SPARK_MAX = 20
BAR_MIN = 5
OPEN = dtime(9, 30)
CLOSE = dtime(16, 0)


class YahooError(Exception):
    """A Yahoo request that failed for good; the caller counts it."""


class HttpError(Exception):
    """An HTTP status answer; `get` functions raise this for 429 and 5xx."""

    def __init__(self, status: int, body: str = "") -> None:
        super().__init__(f"HTTP {status}")
        self.status = status
        self.body = body


@dataclass(frozen=True)
class Bar:
    start: datetime  # aware, America/New_York
    open: float
    high: float
    low: float
    close: float
    volume: float


def _http_get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", "replace")
        except Exception:
            body = ""
        finally:
            e.close()
        raise HttpError(e.code, body) from None


def _to_et(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, ET)


def _series(res: dict[str, Any]) -> tuple[list[Any], dict[str, list[Any]]]:
    quote = ((res.get("indicators") or {}).get("quote") or [{}])[0] or {}
    stamps = list(res.get("timestamp") or [])
    n = len(stamps)
    cols: dict[str, list[Any]] = {}
    for k in ("open", "high", "low", "close", "volume"):
        v = quote.get(k)
        cols[k] = list(v) + [None] * (n - len(v)) if isinstance(v, list) else [None] * n
    return stamps, cols


@dataclass(frozen=True)
class SparkSeries:
    """One symbol's spark answer: (start ET, close) points and the day's volume so far."""

    points: list[tuple[datetime, float]]
    volume: float


class YahooClient:
    def __init__(
        self,
        get: Callable[[str], str] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        pause: float = 0.3,
    ) -> None:
        self._get = get or _http_get
        self._sleep = sleep
        self._pause = pause

    def _request(self, path: str) -> str:
        """query2 first. A 429 retries query2 once after 5 s, then query1; a 5xx goes to query1."""
        last = "no answer"
        for host, can_wait in ((HOSTS[0], True), (HOSTS[1], False)):
            for n in range(2 if can_wait else 1):
                try:
                    return self._get(host + path)
                except HttpError as e:
                    last = f"HTTP {e.status}"
                    if e.status == 429 and can_wait and n == 0:
                        self._sleep(BACKOFF_S)
                        continue
                    if e.status < 500 and e.status != 429:
                        if e.body.strip().startswith("{"):
                            return e.body  # Yahoo's JSON error ("No data found"), parsed later
                        raise YahooError(f"Yahoo answered {last} for {path.split('?')[0]}") from e
                    break
                except (urllib.error.URLError, OSError) as e:
                    last = str(getattr(e, "reason", e))
                    break
        raise YahooError(f"Yahoo answered {last} for {path.split('?')[0]}")

    def spark_closes(
        self, symbols: Sequence[str], rng: str, interval: str
    ) -> dict[str, list[tuple[datetime, float]]]:
        out: dict[str, list[tuple[datetime, float]]] = {}
        for k in range(0, len(symbols), SPARK_MAX):
            if k:
                self._sleep(self._pause)
            batch = symbols[k : k + SPARK_MAX]
            path = f"/v7/finance/spark?symbols={','.join(batch)}&range={rng}&interval={interval}"
            out.update(_parse_spark(self._request(path)))
        return out

    def wait(self) -> None:
        """The pause between two requests (the free endpoint's courtesy)."""
        self._sleep(self._pause)

    def spark_series(self, symbols: Sequence[str], rng: str, interval: str) -> dict[str, SparkSeries]:
        out: dict[str, SparkSeries] = {}
        for k in range(0, len(symbols), SPARK_MAX):
            if k:
                self.wait()
            batch = symbols[k : k + SPARK_MAX]
            path = f"/v7/finance/spark?symbols={','.join(batch)}&range={rng}&interval={interval}"
            out.update(_parse_spark_series(self._request(path)))
        return out

    def chart(self, symbol: str, rng: str, interval: str) -> list[Bar]:
        path = f"/v8/finance/chart/{symbol}?range={rng}&interval={interval}"
        return _parse_chart(self._request(path), symbol)


def _parse_spark(text: str) -> dict[str, list[tuple[datetime, float]]]:
    return {k: v.points for k, v in _parse_spark_series(text).items()}


def _parse_spark_series(text: str) -> dict[str, SparkSeries]:
    try:
        spark = json.loads(text)["spark"]
    except (ValueError, KeyError, TypeError):
        raise YahooError("Yahoo's spark answer is not the shape this tool knows") from None
    if not isinstance(spark, dict):
        raise YahooError("Yahoo's spark answer is not the shape this tool knows")
    out: dict[str, SparkSeries] = {}
    for item in spark.get("result") or []:
        resp = item.get("response") or []
        if not resp:
            continue
        sym = item.get("symbol") or (resp[0].get("meta") or {}).get("symbol")
        if not sym:
            continue
        stamps, cols = _series(resp[0])
        points = [
            (_to_et(t), float(c)) for t, c in zip(stamps, cols["close"], strict=True) if c is not None
        ]
        vols = [v for v in cols["volume"] if v is not None]
        meta_vol = (resp[0].get("meta") or {}).get("regularMarketVolume")
        volume = float(sum(vols)) if vols else float(meta_vol or 0)
        out[sym] = SparkSeries(points, volume)
    err = spark.get("error")
    if err and not out:
        raise YahooError(f"Yahoo spark: {err.get('description') or err.get('code') or err}")
    return out


def _parse_chart(text: str, symbol: str) -> list[Bar]:
    try:
        chart = json.loads(text)["chart"]
    except (ValueError, KeyError, TypeError):
        raise YahooError(f"Yahoo returned something unexpected for {symbol}") from None
    res = chart.get("result")
    if not res:
        err = chart.get("error") or {}
        raise YahooError(f"no data for {symbol}: {err.get('description', 'unknown ticker')}")
    stamps, c = _series(res[0])
    bars: list[Bar] = []
    for i, ts in enumerate(stamps):
        o, h, lo, cl = c["open"][i], c["high"][i], c["low"][i], c["close"][i]
        if o is None or h is None or lo is None or cl is None:
            continue
        et = _to_et(ts)
        if et.second or et.minute % BAR_MIN:
            continue  # the live tick, off the 5-minute grid
        bars.append(Bar(et, float(o), float(h), float(lo), float(cl), float(c["volume"][i] or 0)))
    return bars


def session_bars(bars: Sequence[Bar], day: date, cutoff: datetime) -> list[Bar]:
    """`day`'s 5-minute bars on the grid, complete at `cutoff`, sorted, one per slot."""
    out: dict[datetime, Bar] = {}
    for b in bars:
        et = b.start.astimezone(ET)
        if et.date() != day or et.second or et.minute % BAR_MIN:
            continue
        if et.time() < OPEN or et.time() >= CLOSE:
            continue
        if et + timedelta(minutes=BAR_MIN) > cutoff:
            continue
        out[et] = b
    return [out[k] for k in sorted(out)]
