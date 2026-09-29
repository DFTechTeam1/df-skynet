import httpx
from celery.exceptions import SoftTimeLimitExceeded

from services.tasks.base import classify_error

REQUEST = httpx.Request("GET", "https://example.test")


def _http_error(status_code: int) -> httpx.HTTPStatusError:
    return httpx.HTTPStatusError("x", request=REQUEST, response=httpx.Response(status_code, request=REQUEST))


def test_5xx_is_retryable():
    """A 5xx upstream error classifies as retryable and not final."""
    err = classify_error(_http_error(500), source="openrouter")
    assert err.retryable and not err.final


def test_429_is_retryable():
    """A 429 rate-limit error classifies as retryable and not final."""
    err = classify_error(_http_error(429), source="udin")
    assert err.retryable and not err.final


def test_plain_400_is_retryable():
    """A plain 400 still classifies as retryable and not final."""
    err = classify_error(_http_error(400), source="openrouter")
    assert err.retryable and not err.final


def test_timeout_is_retryable():
    """A request timeout classifies as retryable."""
    err = classify_error(httpx.TimeoutException("timeout"), source="udin")
    assert err.retryable


def test_soft_time_limit_is_retryable():
    """A Celery soft time limit hit classifies as retryable."""
    err = classify_error(SoftTimeLimitExceeded(), source="openrouter")
    assert err.retryable
