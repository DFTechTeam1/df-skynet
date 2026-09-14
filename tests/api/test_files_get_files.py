import pytest
from uuid import uuid4
from middlewares.lang import resolve_message
from services.mysql.factory.df_engine_upload_files import DfEngineUploadFilesFactory


def _url(task_uid, suffix=""):
    return f"/api/files/{task_uid}{suffix}"


def _make_file(project_task, user_id, name="a.png", kind="images", family="upload"):
    """A `DfEngineUploadFiles` row shaped so `FilesService.base_of`/`type_root_of`
    recognize it, unlike the factory's default Faker path."""
    path = f"storage/DF-Engine/{project_task.project.uid}/{family}/{kind}/{name}"
    return DfEngineUploadFilesFactory.create(
        path=path,
        project_id=project_task.project_id,
        task_id=project_task.id,
        created_by=int(user_id),
    )


def _find_file_node(nodes, uid):
    for node in nodes:
        found = next((f for f in node["files"] if f["uid"] == uid), None)
        if found is not None:
            return found
        found = _find_file_node(node["childs"], uid)
        if found is not None:
            return found
    return None


@pytest.mark.asyncio
async def test_get_files_returns_uploaded_file(authed_client, project_task, user_id):
    """200 OK; a file uploaded by the current user appears in the returned tree."""
    row = _make_file(project_task, user_id)
    resp = await authed_client.call("GET", _url(project_task.uid))
    assert resp.status_code == 200
    assert _find_file_node(resp.json()["data"], row.uid) is not None
    assert _find_file_node(resp.json()["data"], uuid4()) is None


@pytest.mark.asyncio
async def test_get_files_unknown_task_is_404(authed_client):
    """404 project_task_not_found for a task uid that matches no row."""
    resp = await authed_client.call("GET", _url(uuid4()), raise_for_status=False)
    assert resp.status_code == 404
    assert resp.json()["message"] == resolve_message("project_task_not_found", "en")


@pytest.mark.asyncio
async def test_requires_auth(client, project_task):
    """401 when the request carries no bearer token."""
    resp = await client.call("GET", _url(project_task.uid), raise_for_status=False)
    assert resp.status_code == 401
