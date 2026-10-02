from contextlib import contextmanager
from types import SimpleNamespace

import httpx
from celery.exceptions import SoftTimeLimitExceeded

import services.tasks.base as base
from services.mysql.model.df_engine_generations import GenerationStatuses
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


def _fake_get_sync_db(generation):
    @contextmanager
    def _ctx():
        yield SimpleNamespace(get=lambda model, id_: generation, add=lambda obj: None)

    return _ctx


def test_mark_generation_failed_sets_status(monkeypatch):
    """A non-success generation is flipped to failed once retries are exhausted."""
    generation = SimpleNamespace(status=GenerationStatuses.processing)
    monkeypatch.setattr(base, "get_sync_db", _fake_get_sync_db(generation))
    base._mark_generation_failed(1)
    assert generation.status == GenerationStatuses.failed


def test_mark_generation_failed_does_not_downgrade_success(monkeypatch):
    """A generation that already succeeded is never overwritten as failed."""
    generation = SimpleNamespace(status=GenerationStatuses.success)
    monkeypatch.setattr(base, "get_sync_db", _fake_get_sync_db(generation))
    base._mark_generation_failed(1)
    assert generation.status == GenerationStatuses.success


def test_mark_generation_failed_swallows_errors(monkeypatch):
    def boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(base, "get_sync_db", boom)
    base._mark_generation_failed(1)  # must not raise
