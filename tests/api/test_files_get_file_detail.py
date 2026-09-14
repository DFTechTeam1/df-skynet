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


@pytest.mark.asyncio
async def test_get_file_detail_success(authed_client, project_task, user_id):
    """200 OK; fetches one file entry by its uid."""
    row = _make_file(project_task, user_id)
    resp = await authed_client.call("GET", _url(project_task.uid, f"/file/{row.uid}"))
    assert resp.status_code == 200
    assert resp.json()["data"]["uid"] == row.uid


@pytest.mark.asyncio
async def test_get_file_detail_unknown_uid_is_404(authed_client, project_task):
    """404 file_not_found for a file uid absent from the tree."""
    resp = await authed_client.call("GET", _url(project_task.uid, f"/file/{uuid4()}"), raise_for_status=False)
    assert resp.status_code == 404
    assert resp.json()["message"] == resolve_message("file_not_found", "en")
