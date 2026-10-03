import pytest
from unittest.mock import AsyncMock
import services.dto.asynced.projects as projects


def _ctx():
    return type(
        "Ctx", (), {"db": object(), "redis": object(), "key": type("K", (), {"get_project_task": lambda *a: "k"})()}
    )()


@pytest.mark.asyncio
async def test_resolves_a_regular_project_task_by_uid(monkeypatch):
    ctx = _ctx()
    monkeypatch.setattr(projects, "get_json", AsyncMock(return_value=None))
    monkeypatch.setattr(projects, "set_json", AsyncMock())
    task_row = type("Row", (), {})()
    monkeypatch.setattr(
        projects,
        "serialize",
        lambda row: {"id": 1, "uid": "task-uid", "project": {"led_detail": None}},
    )
    monkeypatch.setattr(projects, "query", AsyncMock(return_value=task_row))

    result = await projects.get_project_task(ctx, task_uid="task-uid")

    assert result["is_song"] is False
    assert result["id"] == 1


@pytest.mark.asyncio
async def test_falls_back_to_song_when_uid_is_not_a_project_task(monkeypatch):
    ctx = _ctx()
    monkeypatch.setattr(projects, "get_json", AsyncMock(return_value=None))
    monkeypatch.setattr(projects, "set_json", AsyncMock())

    song_row = type("Row", (), {"id": 9, "uid": "song-uid", "project_id": 300, "name": "My Song"})()
    assignment_row = type("Row", (), {"employee_id": 40, "status": 2, "time_tracker": None})()

    calls = {"n": 0}

    async def fake_query(db, table, filters=(), **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return None  # ProjectTasks lookup misses
        if table.__name__ == "ProjectSongLists":
            return song_row
        return assignment_row

    monkeypatch.setattr(projects, "query", fake_query)
    monkeypatch.setattr(projects, "get_project", AsyncMock(return_value={"id": 300, "uid": "project-uid"}))

    result = await projects.get_project_task(ctx, task_uid="song-uid")

    assert result["is_song"] is True
    assert result["id"] == 9
    assert result["employee_id"] == 40
    assert result["status"] == 2


@pytest.mark.asyncio
async def test_raises_when_neither_table_matches(monkeypatch):
    from error import DataNotFoundError

    ctx = _ctx()
    monkeypatch.setattr(projects, "get_json", AsyncMock(return_value=None))
    monkeypatch.setattr(projects, "query", AsyncMock(return_value=None))

    with pytest.raises(DataNotFoundError):
        await projects.get_project_task(ctx, task_uid="unknown-uid")
