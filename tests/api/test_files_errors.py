import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4


async def _aboom(*args, **kwargs):
    raise RuntimeError("boom")


@pytest.mark.asyncio
async def test_archived_list_turns_unexpected_errors_into_500(authed_client, monkeypatch):
    """500; a non-BaseError raised while loading the archived files becomes a generic ServiceError."""
    monkeypatch.setattr("apps.controller.files.get_archieved_files", _aboom)
    resp = await authed_client.call("GET", "/api/files/archieves", raise_for_status=False)
    assert resp.status_code == 500


@pytest.mark.asyncio
async def test_set_archieve_turns_unexpected_errors_into_500(authed_client, monkeypatch):
    """500; a non-BaseError raised while setting archive state becomes a generic ServiceError."""
    monkeypatch.setattr("apps.controller.files.query", _aboom)
    resp = await authed_client.call("POST", f"/api/files/archieve/{uuid4()}", json={}, raise_for_status=False)
    assert resp.status_code == 500


@pytest.mark.asyncio
async def test_download_turns_unexpected_errors_into_500(authed_client, monkeypatch):
    """500; a non-BaseError while resolving the file to download becomes a generic ServiceError."""
    monkeypatch.setattr("apps.controller.files.get_generation_files", _aboom)
    resp = await authed_client.call("GET", f"/api/files/download/{uuid4()}", raise_for_status=False)
    assert resp.status_code == 500


@pytest.mark.asyncio
async def test_download_upload_source_turns_unexpected_errors_into_500(authed_client, monkeypatch):
    """500; a non-BaseError while resolving an uploaded file to download becomes a generic ServiceError."""
    monkeypatch.setattr("apps.controller.files.get_user_uploaded_file", _aboom)
    resp = await authed_client.call(
        "GET", f"/api/files/download/{uuid4()}", params={"source": "upload"}, raise_for_status=False
    )
    assert resp.status_code == 500


@pytest.mark.asyncio
async def test_set_main_turns_unexpected_errors_into_500(authed_client, monkeypatch):
    """500; a non-BaseError while resolving the variants becomes a generic ServiceError."""
    monkeypatch.setattr("apps.controller.files.get_generation_main_variants", _aboom)
    resp = await authed_client.call("PATCH", f"/api/files/set-main/{uuid4()}", raise_for_status=False)
    assert resp.status_code == 500


@pytest.mark.asyncio
async def test_upload_tolerates_a_non_json_udin_reply(authed_client, project_task, mock_udin, monkeypatch):
    """200 OK; a successful Udin reply whose body is not JSON is treated as an empty result."""

    def not_json():
        raise ValueError("not json")

    async def fake_udin(self, method, path, user_id=None, **kwargs):
        return SimpleNamespace(
            status_code=200, content=b"<html>", is_error=False, json=not_json, request=SimpleNamespace(url=path)
        )

    monkeypatch.setattr("apps.controller.files.APICaller.udin", fake_udin)
    resp = await authed_client.call(
        "POST",
        f"/api/files/{project_task.uid}/uploads",
        headers={"content-type": "multipart/form-data; boundary=x"},
        content=b"x",
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_upload_into_unknown_folder_is_rejected_before_udin(authed_client, project_task, mock_udin):
    """404 folder_not_found; `path` must be an existing folder in the file tree, and Udin is never called."""
    resp = await authed_client.call(
        "POST",
        f"/api/files/{project_task.uid}/uploads",
        params={
            "path": f"storage/DF-Engine-DEV/{project_task.project.name}_{project_task.project.uid[:8]}/upload/images/missing"
        },
        headers={"content-type": "multipart/form-data; boundary=x"},
        content=b"x",
        raise_for_status=False,
    )
    assert resp.status_code == 404
    assert resp.json()["error"] == {"path": ["We couldn't find that folder."]}
    assert mock_udin.calls == []


@pytest.mark.asyncio
async def test_set_favorite_turns_unexpected_errors_into_500(authed_client, monkeypatch):
    """500; a non-BaseError while resolving the file to favourite becomes a generic ServiceError."""
    monkeypatch.setattr("apps.controller.files.query", _aboom)
    resp = await authed_client.call("POST", f"/api/files/favorite/{uuid4()}", json={}, raise_for_status=False)
    assert resp.status_code == 500


@pytest.mark.asyncio
async def test_favourited_list_turns_unexpected_errors_into_500(authed_client, monkeypatch):
    """500; a non-BaseError while loading the favourites becomes a generic ServiceError."""
    monkeypatch.setattr("apps.controller.files.get_favourited_files", _aboom)
    resp = await authed_client.call("GET", "/api/files/favorites", raise_for_status=False)
    assert resp.status_code == 500
