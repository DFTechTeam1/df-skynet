from types import SimpleNamespace

import pytest

import services.tasks.base as base
from services.tasks.base import GenerationStageError, GenerationTask


def _task():
    task = GenerationTask()
    task.__class__ = type("T", (GenerationTask,), {"request": SimpleNamespace(retries=0), "name": "t"})
    return task


def test_redelivered_task_is_failed_not_looped(monkeypatch):
    """A task logged `started` twice already (3rd delivery) raises a final error instead of running again."""
    monkeypatch.setattr(base, "_redelivery_count", lambda *a: base.MAX_REDELIVERIES - 1)
    with pytest.raises(GenerationStageError) as exc:
        _task().before_start("tid", (1, 2), {})
    assert exc.value.final


def test_first_delivery_runs(monkeypatch):
    """A fresh task passes the guard and logs its `started` event."""
    logged = []
    monkeypatch.setattr(base, "_redelivery_count", lambda *a: 0)
    monkeypatch.setattr(base, "log_queue", lambda **kw: logged.append(kw))
    monkeypatch.setattr(base, "_generation_broadcast_context", lambda *a: None)
    _task().before_start("tid", (1, 2), {})
    assert len(logged) == 1
