import pytest
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
async def test_delete_files_success(authed_client, project_task, user_id, mock_udin):
    """200 OK; the file is removed from the tree after deletion."""
    row = _make_file(project_task, user_id)
    before = await authed_client.call("GET", _url(project_task.uid))
    assert _find_file_node(before.json()["data"], row.uid) is not None

    resp = await authed_client.call("DELETE", _url(project_task.uid, "/files"), json={"file_uids": [row.uid]})
    assert resp.status_code == 200
    assert _find_file_node(resp.json()["data"], row.uid) is None


@pytest.mark.asyncio
async def test_delete_files_of_another_user_is_404(authed_client, project_task, other_user_id, mock_udin):
    """404 file_not_found: the tree is built per-requester, so another user's file never appears in it."""
    row = _make_file(project_task, other_user_id)
    resp = await authed_client.call(
        "DELETE", _url(project_task.uid, "/files"), json={"file_uids": [row.uid]}, raise_for_status=False
    )
    assert resp.status_code == 404
    assert resp.json()["message"] == resolve_message("file_not_found", "en")


@pytest.mark.asyncio
async def test_delete_files_upstream_failure_passthrough(authed_client, project_task, user_id, mock_udin):
    """Upstream udin failure on delete-files surfaces as the mapped files_delete_failed error."""
    row = _make_file(project_task, user_id)
    mock_udin.set("delete-files", 500, {"error": {"detail": ["boom"]}})
    resp = await authed_client.call(
        "DELETE", _url(project_task.uid, "/files"), json={"file_uids": [row.uid]}, raise_for_status=False
    )
    assert resp.status_code == 500
    assert resp.json()["message"] == resolve_message("files_delete_failed", "en")
