import pytest
from unittest.mock import AsyncMock
import services.dto.asynced.employees as employees
from error import DataNotFoundError, DataValidationError


@pytest.mark.asyncio
async def test_requires_a_task_or_song():
    with pytest.raises(DataValidationError) as exc:
        await employees.assigned_to_task(object(), 1)
    assert exc.value.message == "task_or_song_required"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs, table",
    [
        ({"task_id": 5}, employees.ProjectTaskPics),
        ({"song_id": 7}, employees.EntertainmentTaskSongs),
    ],
)
async def test_assigned_employee_passes_and_queries_the_right_table(monkeypatch, kwargs, table):
    q = AsyncMock(return_value=object())
    monkeypatch.setattr(employees, "query", q)
    ctx = type("Ctx", (), {"db": object()})()
    await employees.assigned_to_task(ctx, 1, **kwargs)
    assert q.call_args.args[1] is table


@pytest.mark.asyncio
async def test_unassigned_employee_is_not_found(monkeypatch):
    monkeypatch.setattr(employees, "query", AsyncMock(return_value=None))
    ctx = type("Ctx", (), {"db": object()})()
    with pytest.raises(DataNotFoundError) as exc:
        await employees.assigned_to_task(ctx, 1, task_id=5)
    assert exc.value.message == "employee_not_assigned_task"
