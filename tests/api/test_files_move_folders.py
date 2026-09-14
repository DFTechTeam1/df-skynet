import pytest
from services.mysql.factory.df_engine_upload_files import DfEngineUploadFilesFactory
from services.mysql.model.df_engine_upload_files import UploadFileTypes


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
async def test_move_folders_success(authed_client, project_task, user_id, mock_udin):
    """200 OK; moving a folder proxies to udin's move-folders route.

    The source must be nested under a type root (the root itself can't be
    renamed/moved), while the destination can be a type root directly.
    """
    folder_row = DfEngineUploadFilesFactory.create(
        path=f"storage/DF-Engine/{project_task.project.uid}/upload/images/sub",
        type=UploadFileTypes.folder,
        project_id=project_task.project_id,
        task_id=project_task.id,
        created_by=int(user_id),
    )
    DfEngineUploadFilesFactory.create(
        path=f"storage/DF-Engine/{project_task.project.uid}/upload/images/sub/a.png",
        project_id=project_task.project_id,
        task_id=project_task.id,
        created_by=int(user_id),
    )
    _make_file(project_task, user_id, name="b.png", kind="videos")
    destination = f"storage/DF-Engine/{project_task.project.uid}/upload/videos"
    resp = await authed_client.call(
        "PATCH",
        _url(project_task.uid, "/folders/move"),
        json={"folder_paths": [folder_row.path], "destination": destination},
    )
    assert resp.status_code == 200
    assert any("move-folders" in call[1] for call in mock_udin.calls)
