"""Shared building blocks for collectors: the interface, rate limiting, HTTP retries, deadlines.

Collector contract (every source module follows it):
- `fetch(symbols, as_of)` returns validated records or raises; it never touches the database.
- No source needs an API key or an account (spec R7).
- SEC sources need the owner's contact string (SEC_USER_AGENT); without it they raise MissingCredential and only they fail.
- SYMBOLS scope: every record has `symbol` equal to the canonical requested symbol ("BRK.B",
  "RCI-B.TO"); map provider formats ("BRK/B", "BRKB", "BRK-B") in and out inside the collector.
- `markets` names the stock markets a source covers; it is only sent symbols of those markets.
- Raise PartialFetch(records, error) when some requests failed but others succeeded; an empty
  PartialFetch counts as a failure. `collect_per_symbol` does this for per-symbol APIs.
- HTTP goes through `get_with_retries`: it honours the run deadline, backs off on 429/5xx, and
  never puts query strings into error text.
- Long loops honour the run deadline (`check_deadline()` or `time_left()`) between items.
- A provider's collectors share one RateLimiter, built in the registry.
- `canary_requires_records` is True only for sources that always return data for their canary.
- DAILY/WEEKLY collectors with freshness are served from this window's cache, and only missing symbols are fetched; max_symbols caps one call (see runner).
"""

import contextlib
import threading
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Protocol

import httpx
from pydantic import BaseModel

from advisor.models import AssetType, Market

USER_AGENT = "stock-advisor/0.1 (personal research)"
RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
MAX_RETRY_AFTER = 60.0  # never let a server park a run for longer than this per retry


class Category(StrEnum):
    PRICES = "prices"
    FUNDAMENTALS = "fundamentals"
    OPTIONS = "options"
    MACRO = "macro"
    NEWS = "news"
    SOCIAL = "social"
    CATALYSTS = "catalysts"
    ONCHAIN = "onchain"


class Cadence(StrEnum):
    PER_RUN = "per_run"
    DAILY = "daily"
    WEEKLY = "weekly"


class Scope(StrEnum):
    UNIVERSE = "universe"  # returns the symbol universe; `symbols` is ignored
    SYMBOLS = "symbols"  # records per requested symbol; every record has a `symbol` field
    MARKET = "market"  # market-wide data (macro, sentiment); `symbols` is ignored


class CollectorStatus(StrEnum):
    OK = "ok"
    PARTIAL = "partial"
    STALE = "stale"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class CollectorResult:
    name: str
    status: CollectorStatus
    records: list[BaseModel]
    latency_ms: int
    error: str | None = None


class PartialFetch(Exception):
    """Raised by `fetch` when some requests failed but others returned usable records."""

    def __init__(self, records: Sequence[BaseModel], error: str) -> None:
        super().__init__(error)
        self.records = list(records)


class MissingCredential(RuntimeError):
    """A source's required setting is missing: only the SEC contact string (spec §4.1)."""


BUDGET_EXHAUSTED = "run time budget exhausted"
_DEADLINE: ContextVar[float | None] = ContextVar("collector_deadline", default=None)


class DeadlineExceeded(Exception):
    """The run's time budget ran out before this source finished."""


@contextlib.contextmanager
def deadline(at: float | None) -> Iterator[None]:
    """Inside this block, collectors stop once time.monotonic() passes `at` (None = no limit)."""
    token = _DEADLINE.set(at)
    try:
        yield
    finally:
        _DEADLINE.reset(token)


def time_left(clock: Callable[[], float] = time.monotonic) -> float | None:
    """Seconds until the current deadline, or None when there is none."""
    at = _DEADLINE.get()
    return None if at is None else at - clock()


def check_deadline(clock: Callable[[], float] = time.monotonic) -> None:
    """Raise DeadlineExceeded once the current deadline has passed; long loops call this per item."""
    left = time_left(clock)
    if left is not None and left <= 0:
        raise DeadlineExceeded(BUDGET_EXHAUSTED)


def collect_per_symbol(
    symbols: Sequence[str],
    fetch_one: Callable[[str], Sequence[BaseModel]],
    *,
    is_fatal: Callable[[Exception], bool] = lambda exc: False,
    pause: Callable[[], None] | None = None,
    retries: int = 1,
) -> list[BaseModel]:
    """Fetch symbol by symbol (each once, in order), keeping going past per-symbol failures.

    Failures for single symbols end in PartialFetch with everything else. A fatal error (as
    judged by `is_fatal`) or the run deadline stops the loop: it is re-raised as-is when nothing
    was collected yet, otherwise it becomes PartialFetch with the records so far.

    When the loop finishes, each failed symbol gets up to `retries` more tries, in order and
    without `pause`. A deadline or fatal error during the retries ends them and keeps the
    symbols still failing.
    """
    unique = list(dict.fromkeys(symbols))
    records: list[BaseModel] = []
    failures: dict[str, str] = {}  # symbol -> latest failure text, in first-failure order
    for index, symbol in enumerate(unique):
        try:
            check_deadline()
            records.extend(fetch_one(symbol))
        except Exception as exc:
            stop = isinstance(exc, DeadlineExceeded) or is_fatal(exc)
            if stop and not records:
                raise
            failures[symbol] = f"{symbol}: {type(exc).__name__}: {exc}"[:300]
            if stop:
                raise PartialFetch(
                    records, f"stopped after {index} of {len(unique)} symbols; {failures[symbol]}"
                ) from exc
        if pause is not None and index < len(unique) - 1:
            pause()
    stopped = False
    for symbol in list(failures):
        for _ in range(retries):
            try:
                check_deadline()
                records.extend(fetch_one(symbol))
            except Exception as exc:
                failures[symbol] = f"{symbol}: {type(exc).__name__}: {exc}"[:300]
                if isinstance(exc, DeadlineExceeded) or is_fatal(exc):
                    stopped = True
                    break
            else:
                del failures[symbol]
                break
        if stopped:
            break
    if failures:
        first = next(iter(failures.values()))
        raise PartialFetch(records, f"{len(failures)} of {len(unique)} symbols failed; first: {first}")
    return records


class Collector(Protocol):
    """One data source. `fetch` returns validated records or raises; `run_collector` wraps it."""

    name: str
    category: Category
    core: bool
    best_effort: bool
    cadence: Cadence
    asset_types: frozenset[AssetType]
    markets: frozenset[Market]  # stock markets covered; only their stock symbols are sent
    record_type: type[BaseModel]
    freshness: timedelta | None  # max cache age used as a failure fallback; None = never cache
    scope: Scope
    canary: tuple[str, ...]  # symbols the daily health check fetches; () unless scope is SYMBOLS
    canary_requires_records: bool  # health check fails an empty canary answer only when True
    max_symbols: int | None  # most symbols one call may fetch; the rest wait for a later run

    def fetch(self, symbols: Sequence[str], as_of: datetime) -> list[BaseModel]: ...


class RateLimiter:
    """Token bucket: a steady `per_minute` rate with up to `burst` back-to-back calls."""

    def __init__(
        self,
        per_minute: float,
        burst: int = 1,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._rate = per_minute / 60.0
        self._burst = float(burst)
        self._tokens = float(burst)
        self._clock = clock
        self._sleep = sleep
        self._last = clock()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            now = self._clock()
            self._tokens = min(self._burst, self._tokens + (now - self._last) * self._rate)
            self._last = now
            if self._tokens >= 1:
                self._tokens -= 1
                return
            self._sleep((1 - self._tokens) / self._rate)
            self._last = self._clock()
            self._tokens = 0.0


def make_client(timeout: float = 20.0) -> httpx.Client:
    return httpx.Client(
        timeout=timeout, follow_redirects=True, headers={"User-Agent": USER_AGENT}
    )


def _retry_after(response: httpx.Response) -> float | None:
    """Seconds from a numeric Retry-After header, clamped to [0, MAX_RETRY_AFTER]; else None."""
    try:
        seconds = float(response.headers.get("Retry-After", "").strip())
    except ValueError:
        return None
    return min(max(seconds, 0.0), MAX_RETRY_AFTER)


def _safe_url(url: str) -> str:
    """Scheme, host and path only: query strings can carry API keys and must never be logged."""
    parsed = httpx.URL(url)
    return str(parsed.copy_with(query=None, fragment=None))


def get_with_retries(
    client: httpx.Client,
    url: str,
    *,
    params: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
    limiter: RateLimiter | None = None,
    attempts: int = 4,  # spec §4.1: 3 retries
    base_delay: float = 1.0,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> httpx.Response:
    """GET with exponential backoff on transport errors and 429/5xx; other errors raise at once."""
    return _send_with_retries(
        client, "GET", url, params=params, headers=headers, limiter=limiter, attempts=attempts,
        base_delay=base_delay, sleep=sleep, clock=clock,
    )


def post_with_retries(
    client: httpx.Client,
    url: str,
    *,
    json: Any,
    headers: Mapping[str, str] | None = None,
    limiter: RateLimiter | None = None,
    attempts: int = 4,
    base_delay: float = 1.0,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> httpx.Response:
    """POST a JSON body, retried like `get_with_retries` (for APIs that only take POST)."""
    return _send_with_retries(
        client, "POST", url, json=json, headers=headers, limiter=limiter, attempts=attempts,
        base_delay=base_delay, sleep=sleep, clock=clock,
    )


def _send_with_retries(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    params: Mapping[str, Any] | None = None,
    json: Any = None,
    headers: Mapping[str, str] | None,
    limiter: RateLimiter | None,
    attempts: int,
    base_delay: float,
    sleep: Callable[[float], None],
    clock: Callable[[], float],
) -> httpx.Response:
    last_error: Exception | None = None
    for attempt in range(attempts):
        retry_after: float | None = None
        check_deadline(clock)
        if limiter is not None:
            limiter.acquire()
            check_deadline(clock)  # a busy shared limiter may have slept past the deadline
        try:
            response = client.request(method, url, params=params, json=json, headers=headers)
        except httpx.TransportError as exc:
            last_error = exc
        else:
            if response.status_code not in RETRY_STATUS:
                if response.is_error:
                    raise httpx.HTTPStatusError(
                        f"HTTP {response.status_code} from {_safe_url(url)}: {response.text[:200]}",
                        request=response.request,
                        response=response,
                    )
                return response
            retry_after = _retry_after(response)
            last_error = httpx.HTTPStatusError(
                f"HTTP {response.status_code} from {_safe_url(url)}",
                request=response.request,
                response=response,
            )
        if attempt < attempts - 1:
            backoff = base_delay * 2**attempt
            wait = backoff if retry_after is None else max(backoff, retry_after)
            left = time_left(clock)
            if left is not None and wait >= left:
                raise DeadlineExceeded(
                    f"{BUDGET_EXHAUSTED} while retrying {_safe_url(url)}"
                ) from last_error
            sleep(wait)
    assert last_error is not None
    raise last_error
