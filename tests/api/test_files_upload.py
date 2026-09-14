import pytest
from middlewares.lang import resolve_message


def _url(task_uid):
    return f"/api/files/{task_uid}/uploads"


@pytest.mark.asyncio
async def test_upload_files_success(authed_client, project_task, mock_udin):
    """200 OK; uploaded files are persisted and returned in the refreshed tree."""
    uploaded_path = f"storage/DF-Engine/{project_task.project.uid}/upload/images/a.png"
    mock_udin.set(
        "upload-files",
        200,
        {"data": [{"name": "a.png", "path": uploaded_path, "size": 10, "md5": "abc123"}]},
    )
    resp = await authed_client.call(
        "POST", _url(project_task.uid), files={"files": ("a.png", b"fake-bytes", "image/png")}
    )
    assert resp.status_code == 200
    names = [f["name"] for node in resp.json()["data"] for f in _flatten_files(node)]
    assert "a.png" in names


@pytest.mark.asyncio
async def test_upload_files_upstream_failure_passthrough(authed_client, project_task, mock_udin):
    """Upstream udin failure on upload-files surfaces as the mapped upload_failed error."""
    mock_udin.set("upload-files", 500, {"error": {"detail": ["boom"]}})
    resp = await authed_client.call(
        "POST",
        _url(project_task.uid),
        files={"files": ("a.png", b"fake-bytes", "image/png")},
        raise_for_status=False,
    )
    assert resp.status_code == 500
    assert resp.json()["message"] == resolve_message("upload_failed", "en")


def _flatten_files(node):
    yield from node["files"]
    for child in node["childs"]:
        yield from _flatten_files(child)
