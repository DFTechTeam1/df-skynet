import pytest
from services.mysql.factory.df_engine_upload_files import DfEngineUploadFilesFactory
from services.mysql.model.df_engine_upload_files import UploadFileTypes


def _url(task_uid, suffix=""):
    return f"/api/files/{task_uid}{suffix}"


@pytest.mark.asyncio
async def test_delete_folder_success(authed_client, project_task, user_id, mock_udin):
    """200 OK; deletion proxies to udin's delete-folder route.

    The type root itself can't be deleted, so the file lives one level deeper.
    The actual DB row removal happens via `sync_paths`, driven by whatever
    `{from, to}` pairs udin's real response would include, which this fake
    doesn't simulate — so this test only asserts the proxy call itself.
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
    resp = await authed_client.call("DELETE", _url(project_task.uid, "/folder"), json={"folder_path": folder_row.path})
    assert resp.status_code == 200
    assert any("delete-folder" in call[1] for call in mock_udin.calls)
