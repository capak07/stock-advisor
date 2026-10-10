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
    client, calls = scripted_client([boom, boom, boom, boom])
    sleeps = []
    with pytest.raises(httpx.ConnectError):
        get_with_retries(client, "https://example.test/x", sleep=sleeps.append)
    assert len(calls) == 4  # spec §4.1: 3 retries
    assert sleeps == [1.0, 2.0, 4.0]


@pytest.mark.parametrize(
    ("header", "expected_sleep"),
    [("7", 7.0), ("120", 60.0), ("0", 1.0), ("Wed, 21 Oct 2026 07:28:00 GMT", 1.0)],
)
def test_retry_after_header_sets_the_wait(header, expected_sleep):
    client, _ = scripted_client(
        [httpx.Response(429, headers={"Retry-After": header}), httpx.Response(200, text="ok")]
    )
    sleeps = []
    assert get_with_retries(client, "https://example.test/x", sleep=sleeps.append).text == "ok"
    assert sleeps == [expected_sleep]


def test_error_text_never_contains_query_strings():
    url = "https://x.test/ratios/AAPL?token=ABC"
    client, _ = scripted_client([httpx.Response(401, text='{"error":"Invalid API KEY"}')])
    with pytest.raises(httpx.HTTPStatusError) as caught:
        get_with_retries(client, url, params={"apikey": "SECRET123"}, sleep=lambda _: None)
    text = str(caught.value)
    assert "SECRET123" not in text and "ABC" not in text
    assert "HTTP 401 from https://x.test/ratios/AAPL" in text and "Invalid API KEY" in text

    client, _ = scripted_client([httpx.Response(503)] * 4)
    with pytest.raises(httpx.HTTPStatusError) as caught:
        get_with_retries(client, url, params={"apikey": "SECRET123"}, sleep=lambda _: None)
    text = str(caught.value)
    assert "SECRET123" not in text and "ABC" not in text
    assert "HTTP 503 from https://x.test/ratios/AAPL" in text
