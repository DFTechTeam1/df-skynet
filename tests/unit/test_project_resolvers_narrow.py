from datetime import date
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import inspect

import services.dto.asynced.projects as ap
import services.dto.synced.projects as sp
from error import DataNotFoundError
from services.mysql.model import Projects


def _ctx(db):
    return type("Ctx", (), {"db": db})()


def _project():
    return Projects(id=1, uid="p-uid", name="P", venue="v", led_detail='{"a": 1}')


async def test_async_get_project_loads_only_needed_columns(monkeypatch):
    seen = {}

    async def fake_query(db, table, **kw):
        seen.update(kw)
        return _project()

    monkeypatch.setattr(ap, "query", fake_query)
    result = await ap.get_project(_ctx(object()), project_id=1)
    assert {"id", "uid", "name"} <= result.keys()
    assert "load_only" in str(seen["options"][0]).lower() or seen["options"]


async def test_get_project_never_serves_stale_after_delete(monkeypatch):
    rows = [_project(), None]  # second lookup: row deleted by another service

    async def fake_query(db, table, **kw):
        return rows.pop(0)

    monkeypatch.setattr(ap, "query", fake_query)
    await ap.get_project(_ctx(object()), project_id=1)
    with pytest.raises(DataNotFoundError):
        await ap.get_project(_ctx(object()), project_id=1)


def test_sync_get_project_serializes_loaded_columns(monkeypatch):
    monkeypatch.setattr(sp, "query_sync", lambda *a, **k: _project())
    result = sp.get_project(_ctx(object()), project_uid="p-uid")
    assert result["uid"] == "p-uid"


async def test_project_task_row_narrow_options_and_project_shape(monkeypatch):
    from services.mysql.model import ProjectTasks

    task = ProjectTasks(id=2, uid="t-uid", project_id=1, name="T", status=1)
    task.project = _project()
    seen = {}

    async def fake_query(db, table, **kw):
        seen.update(kw)
        return task

    monkeypatch.setattr(ap, "query", fake_query)
    row = await ap._resolve_project_task_row(_ctx(object()), task_uid="t-uid")
    assert row["is_song"] is False and row["project"]["uid"] == "p-uid"
    assert len(seen["options"]) == 2  # root load_only + narrowed selectinload


def test_load_only_leaves_other_columns_unloaded():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session, load_only
    from sqlalchemy.pool import StaticPool

    eng = create_engine("sqlite://", poolclass=StaticPool)
    Projects.__table__.create(eng)
    with Session(eng) as s:
        s.add(
            Projects(id=1, uid="u", name="n", client_portal="c", project_date=date(2024, 1, 1), venue="v", led_area=0)
        )
        s.commit()
        s.expunge_all()
        p = s.query(Projects).options(load_only(Projects.id, Projects.uid, Projects.name)).first()
        assert "venue" in inspect(p).unloaded
