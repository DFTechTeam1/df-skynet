import pytest
from error import DataNotFoundError
from middlewares.lang import resolve_message

TASK_COMPLETED, SONG_COMPLETED = 4, 6
TASK_UID = "11111111-1111-1111-1111-111111111111"
# (url, payload) per endpoint that guards on task/project state
ENDPOINTS = {
    "enhance": (f"/api/generations/enhance/{TASK_UID}", {"prompt": "a mountain"}),
    "generate": (f"/api/generations/{TASK_UID}", {"prompt": "a mountain", "type": "image", "parameter": {}}),
}


@pytest.fixture
def stub(monkeypatch):
    """Stubs the task/project/assignment lookups so each guard is hit in isolation."""
    state = {"task": {"id": 1, "is_song": False, "status": 1, "project_id": 1}, "project": {"status": 1, "uid": "p"}}
    state["assigned"] = []
    state["assigned_error"] = None

    async def _task(ctx, *a, **k):
        return state["task"]

    async def _project(ctx, *a, **k):
        return state["project"]

    async def _assigned(ctx, employee_id, task_id=None, song_id=None):
        state["assigned"].append((task_id, song_id))
        if state["assigned_error"]:
            raise state["assigned_error"]

    monkeypatch.setattr("apps.controller.generations.get_project_task", _task)
    monkeypatch.setattr("apps.controller.generations.get_project", _project)
    monkeypatch.setattr("apps.controller.generations.assigned_to_task", _assigned)
    return state


async def _call(client, name):
    url, payload = ENDPOINTS[name]
    return await client.call("POST", url, json=payload, raise_for_status=False)


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ENDPOINTS)
async def test_completed_task_is_refused(authed_client, stub, name):
    stub["task"]["status"] = TASK_COMPLETED
    resp = await _call(authed_client, name)
    assert resp.status_code == 422
    assert resp.json()["message"] == resolve_message("project_task_already_completed", "en")


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ENDPOINTS)
async def test_completed_song_is_refused(authed_client, stub, name):
    stub["task"].update(is_song=True, status=SONG_COMPLETED)
    resp = await _call(authed_client, name)
    assert resp.status_code == 422
    assert resp.json()["message"] == resolve_message("song_task_already_completed", "en")


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ENDPOINTS)
async def test_project_not_ongoing_is_refused(authed_client, stub, name):
    stub["project"]["status"] = 2
    resp = await _call(authed_client, name)
    assert resp.status_code == 422
    assert resp.json()["message"] == resolve_message("project_not_ongoing", "en")


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ENDPOINTS)
@pytest.mark.parametrize("is_song", [False, True])
async def test_unassigned_non_override_user_is_refused(authed_client, stub, as_roles, name, is_song):
    as_roles(["staff"])
    stub["task"]["is_song"] = is_song
    stub["assigned_error"] = DataNotFoundError(message="employee_not_assigned_task")
    resp = await _call(authed_client, name)
    assert resp.status_code == 404
    assert resp.json()["message"] == resolve_message("employee_not_assigned_task", "en")
    assert stub["assigned"] == [(None, 1) if is_song else (1, None)]


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ENDPOINTS)
async def test_override_role_skips_assignment_check(authed_client, stub, as_roles, name):
    as_roles(["director"])
    await _call(authed_client, name)  # outcome past the guards is irrelevant here
    assert stub["assigned"] == []
