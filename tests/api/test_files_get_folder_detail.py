import pytest
from middlewares.lang import resolve_message
from services.mysql.factory.df_engine_upload_files import DfEngineUploadFilesFactory
from services.mysql.model.df_engine_upload_files import UploadFileTypes


def _url(task_uid, suffix=""):
    return f"/api/files/{task_uid}{suffix}"


@pytest.mark.asyncio
async def test_get_folder_detail_success(authed_client, project_task, user_id):
    """200 OK; fetches the folder node by its own path."""
    folder = f"storage/DF-Engine/{project_task.project.uid}/upload/images/sub"
    DfEngineUploadFilesFactory.create(
        path=folder,
        type=UploadFileTypes.folder,
        project_id=project_task.project_id,
        task_id=project_task.id,
        created_by=int(user_id),
    )
    resp = await authed_client.call("GET", _url(project_task.uid, "/detail"), params={"folder_path": folder})
    assert resp.status_code == 200
    assert resp.json()["data"]["folder"] == folder


@pytest.mark.asyncio
async def test_get_folder_detail_unknown_path_is_404(authed_client, project_task):
    """404 folder_not_found for a folder path absent from the tree."""
    resp = await authed_client.call(
        "GET", _url(project_task.uid, "/detail"), params={"folder_path": "no/such/folder"}, raise_for_status=False
    )
    assert resp.status_code == 404
    assert resp.json()["message"] == resolve_message("folder_not_found", "en")
