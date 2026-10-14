"""Shared building blocks for collectors: the interface, rate limiting, and HTTP retries."""

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

from advisor.models import AssetType

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


class Collector(Protocol):
    """One data source. `fetch` returns validated records or raises; `run_collector` wraps it."""

    name: str
    category: Category
    core: bool
    best_effort: bool
    cadence: Cadence
    asset_types: frozenset[AssetType]
    record_type: type[BaseModel]
    freshness: timedelta | None  # max cache age used as a failure fallback; None = never cache
    scope: Scope
    canary: tuple[str, ...]  # symbols the daily health check fetches; () unless scope is SYMBOLS
    canary_requires_records: bool  # health check fails an empty canary answer only when True

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
    last_error: Exception | None = None
    for attempt in range(attempts):
        retry_after: float | None = None
        check_deadline(clock)
        if limiter is not None:
            limiter.acquire()
            check_deadline(clock)  # a busy shared limiter may have slept past the deadline
        try:
            response = client.get(url, params=params, headers=headers)
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
