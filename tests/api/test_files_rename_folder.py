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


def _flatten(tree):
    for node in tree:
        yield node
        yield from _flatten(node["childs"])


@pytest.mark.asyncio
async def test_rename_folder_success(authed_client, project_task, user_id, mock_udin):
    """200 OK; renaming a folder proxies to udin's rename-folder route.

    The type root itself (`upload/images`) can never be renamed/deleted, only a
    folder nested under it, so the file lives one level deeper.
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
    resp = await authed_client.call(
        "PATCH", _url(project_task.uid, "/folder"), json={"folder_path": folder_row.path, "name": "renamed_folder"}
    )
    assert resp.status_code == 200
    assert any("rename-folder" in call[1] for call in mock_udin.calls)


@pytest.mark.asyncio
async def test_rename_folder_moves_a_still_empty_tracked_folder(authed_client, project_task, user_id, mock_udin):
    """A folder created empty (its own df_engine_upload_files row, no file inside it yet)
    follows its rename to the new path instead of leaving a stale entry at the old one."""
    _make_file(project_task, user_id)
    parent = f"storage/DF-Engine/{project_task.project.uid}/upload/images"
    create_resp = await authed_client.call(
        "POST", _url(project_task.uid, "/folder"), json={"current_path": parent, "name": "empty_sub"}
    )
    empty_sub = next(n for n in _flatten(create_resp.json()["data"]) if n["folder"] == f"{parent}/empty_sub")
    resp = await authed_client.call(
        "PATCH",
        _url(project_task.uid, "/folder"),
        json={"folder_path": empty_sub["folder"], "name": "renamed_empty"},
    )
    assert resp.status_code == 200
    nodes = {n["folder"] for n in _flatten(resp.json()["data"])}
    assert f"{parent}/renamed_empty" in nodes
    assert f"{parent}/empty_sub" not in nodes
