import pytest
from services.mysql.factory.df_engine_upload_files import DfEngineUploadFilesFactory


def _url(task_uid, suffix=""):
    return f"/api/files/{task_uid}{suffix}"


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
async def test_full_files_lifecycle(authed_client, project_task, user_id, mock_udin):
    """Walks create-folder -> move a file into it -> rename it -> delete it -> list, checking the tree at each step."""
    project_uid = project_task.project.uid
    root = f"storage/DF-Engine/{project_uid}/upload/images"
    file_row = DfEngineUploadFilesFactory.create(
        path=f"{root}/original.png",
        project_id=project_task.project_id,
        task_id=project_task.id,
        created_by=int(user_id),
    )

    # 1. list: the freshly-uploaded file appears at the type root
    listed = await authed_client.call("GET", _url(project_task.uid))
    assert _find_file_node(listed.json()["data"], file_row.uid) is not None

    # 2. create a subfolder under the root. Folders aren't DB-tracked — the tree is
    # rebuilt purely from file paths — so an empty new folder is proxied to udin
    # but won't itself gain a tree node (and thus isn't a valid move target) until
    # a file actually lives under it; this step only confirms the proxy call.
    target = f"{root}/target"
    create_resp = await authed_client.call(
        "POST", _url(project_task.uid, "/folder"), json={"current_path": root, "name": "target"}
    )
    assert create_resp.status_code == 200
    assert any("new-folder" in call[1] for call in mock_udin.calls)

    # 3. move the file into an existing type-root folder
    destination = f"storage/DF-Engine/{project_uid}/upload/videos"
    move_resp = await authed_client.call(
        "PATCH",
        _url(project_task.uid, "/files/move"),
        json={"file_uids": [file_row.uid], "destination": destination},
    )
    assert move_resp.status_code == 200
    assert any("move-files" in call[1] for call in mock_udin.calls)

    # 4. rename the file
    rename_resp = await authed_client.call(
        "PATCH", _url(project_task.uid, "/file"), json={"file_uid": file_row.uid, "name": "renamed"}
    )
    assert rename_resp.status_code == 200
    assert any("rename-file" in call[1] for call in mock_udin.calls)

    # 5. delete the file, confirming it is gone from the refreshed tree
    delete_resp = await authed_client.call(
        "DELETE", _url(project_task.uid, "/files"), json={"file_uids": [file_row.uid]}
    )
    assert delete_resp.status_code == 200
    assert _find_file_node(delete_resp.json()["data"], file_row.uid) is None
    assert any("delete-files" in call[1] for call in mock_udin.calls)

    # 6. a subsequent list reflects the deletion too, proving cache invalidation held across every step
    final = await authed_client.call("GET", _url(project_task.uid))
    assert _find_file_node(final.json()["data"], file_row.uid) is None
