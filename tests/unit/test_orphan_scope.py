import pytest
from unittest.mock import AsyncMock
import services.files as files
from error import DataValidationError


def _ctx():
    return type("Ctx", (), {"db": object()})()


def _row(uid, project_id, created_by=1, task_id=None, song_id=None):
    return type(
        "Row",
        (),
        {"uid": uid, "project_id": project_id, "created_by": created_by, "task_id": task_id, "song_id": song_id},
    )()


@pytest.mark.asyncio
async def test_orphaned_upload_falls_back_to_project_scope(monkeypatch):
    monkeypatch.setattr(files, "query", AsyncMock(return_value=[_row("u1", 7)]))
    get_task = AsyncMock()
    monkeypatch.setattr(files, "get_project_task", get_task)

    rows, scope = await files.resolve_files(_ctx(), "upload", ["u1"], 1, [])

    assert scope == {"id": None, "is_song": False, "project_id": 7}
    assert len(rows) == 1
    get_task.assert_not_called()


@pytest.mark.asyncio
async def test_orphan_mixed_with_live_task_is_rejected(monkeypatch):
    rows = [_row("u1", 7), _row("u2", 7, task_id=5)]
    monkeypatch.setattr(files, "query", AsyncMock(return_value=rows))
    with pytest.raises(DataValidationError):
        await files.resolve_files(_ctx(), "upload", ["u1", "u2"], 1, [])


@pytest.mark.asyncio
async def test_orphaned_file_still_requires_owner(monkeypatch):
    monkeypatch.setattr(files, "query", AsyncMock(return_value=[_row("u1", 7, created_by=2)]))
    with pytest.raises(DataValidationError):
        await files.resolve_files(_ctx(), "upload", ["u1"], 1, [])
