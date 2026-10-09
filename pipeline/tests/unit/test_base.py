import httpx
import pytest

from advisor.collectors.base import RateLimiter, get_with_retries
from fakes import FakeClock


def scripted_client(script):
    """Client whose responses come from `script` in order; an Exception item is raised."""
    calls = []
    items = iter(script)

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        item = next(items)
        if isinstance(item, Exception):
            raise item
        return item

    return httpx.Client(transport=httpx.MockTransport(handler)), calls


class CountingLimiter:
    def __init__(self) -> None:
        self.count = 0

    def acquire(self) -> None:
        self.count += 1


def test_rate_limiter_allows_burst_then_waits():
    clock = FakeClock()
    limiter = RateLimiter(per_minute=60, burst=2, clock=clock, sleep=clock.sleep)
    limiter.acquire()
    limiter.acquire()
    assert clock.sleeps == []
    limiter.acquire()
    assert clock.sleeps == [pytest.approx(1.0)]


def test_rate_limiter_refills_over_time():
    clock = FakeClock()
    limiter = RateLimiter(per_minute=60, burst=1, clock=clock, sleep=clock.sleep)
    limiter.acquire()
    clock.now += 1.0
    limiter.acquire()
    assert clock.sleeps == []


def test_retries_retryable_status_then_succeeds():
    client, calls = scripted_client([httpx.Response(503), httpx.Response(200, text="ok")])
    sleeps = []
    limiter = CountingLimiter()
    response = get_with_retries(
        client, "https://example.test/x", limiter=limiter, sleep=sleeps.append
    )
    assert response.text == "ok"
    assert len(calls) == 2
    assert sleeps == [1.0]
    assert limiter.count == 2


def test_non_retryable_status_raises_immediately():
    client, calls = scripted_client([httpx.Response(403)])
    sleeps = []
    with pytest.raises(httpx.HTTPStatusError):
        get_with_retries(client, "https://example.test/x", sleep=sleeps.append)
    assert len(calls) == 1
    assert sleeps == []


def test_transport_errors_exhaust_attempts_with_backoff():
    boom = httpx.ConnectError("down")
    client, calls = scripted_client([boom, boom, boom])
    sleeps = []
    with pytest.raises(httpx.ConnectError):
        get_with_retries(client, "https://example.test/x", sleep=sleeps.append)
    assert len(calls) == 3
    assert sleeps == [1.0, 2.0]
