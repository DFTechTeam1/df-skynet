import pytest
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
async def test_move_files_success(authed_client, project_task, user_id, mock_udin):
    """200 OK; moving proxies to udin's move-files route with the destination folder."""
    row = _make_file(project_task, user_id, name="a.png")
    _make_file(project_task, user_id, name="b.png", kind="videos")
    destination = f"storage/DF-Engine/{project_task.project.uid}/upload/videos"
    resp = await authed_client.call(
        "PATCH", _url(project_task.uid, "/files/move"), json={"file_uids": [row.uid], "destination": destination}
    )
    assert resp.status_code == 200
    assert any("move-files" in call[1] for call in mock_udin.calls)
