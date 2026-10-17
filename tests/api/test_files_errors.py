import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4


async def _aboom(*args, **kwargs):
    raise RuntimeError("boom")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,suffix,target,body",
    [
        ("GET", "archieved", "get_archieved_files", None),
        ("GET", "favourited", "get_favourited_files", None),
        ("PATCH", "archieve", "get_generation_files", {"file_uids": [str(uuid4())]}),
        ("PATCH", "favorite", "get_generation_files", {"file_uids": [str(uuid4())]}),
    ],
)
async def test_task_scoped_file_endpoints_turn_unexpected_errors_into_500(
    authed_client, project_task, monkeypatch, method, suffix, target, body
):
    """500; a non-BaseError raised while loading the files is logged and surfaced as a generic ServiceError."""
    monkeypatch.setattr(f"apps.controller.files.{target}", _aboom)
    resp = await authed_client.call(
        method, f"/api/files/{project_task.uid}/{suffix}", json=body, raise_for_status=False
    )
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
async def test_archive_without_a_cached_result_list_skips_the_cache_patch(authed_client, project_task, monkeypatch):
    """404 file_not_found for an unknown uid; with the cached result list missing the cache-patch step is skipped
    before validation fails, so the miss branch is exercised without touching real data."""
    monkeypatch.setattr("apps.controller.files.get_json", AsyncMock(return_value=None))
    monkeypatch.setattr("apps.controller.files.get_generation_files", AsyncMock(return_value=[]))
    resp = await authed_client.call(
        "PATCH",
        f"/api/files/{project_task.uid}/archieve",
        json={"file_uids": [str(uuid4())], "is_archieved": False},
        raise_for_status=False,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_archive_with_a_cache_miss_still_updates_and_returns_the_archived_list(
    authed_client, project_task, monkeypatch, as_roles
):
    """200 OK; archiving works when the cached result list is absent, only the cache patch is skipped."""
    as_roles(["staff"])
    uid = str(uuid4())
    record = {
        "file_uid": uid,
        "archieved_at": None,
        "flag_archieved_at": None,
        "action": {"can_archieve": True, "can_unarchieve": False},
    }
    monkeypatch.setattr("apps.controller.files.get_json", AsyncMock(return_value=None))
    monkeypatch.setattr("apps.controller.files.get_generation_files", AsyncMock(return_value=[record]))
    monkeypatch.setattr("apps.controller.files.get_archieved_files", AsyncMock(return_value=[]))
    resp = await authed_client.call(
        "PATCH", f"/api/files/{project_task.uid}/archieve", json={"file_uids": [uid]}, raise_for_status=False
    )
    assert resp.status_code == 200
    assert [f["file_uid"] for f in resp.json()["data"]] == [uid]


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
@pytest.mark.parametrize("suffix", ["archieved", "favourited"])
async def test_listing_endpoints_pass_domain_errors_through(authed_client, suffix):
    """404 project_task_not_found; a BaseError from resolving the task is re-raised untouched, not turned into 500."""
    resp = await authed_client.call("GET", f"/api/files/{uuid4()}/{suffix}", raise_for_status=False)
    assert resp.status_code == 404


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
