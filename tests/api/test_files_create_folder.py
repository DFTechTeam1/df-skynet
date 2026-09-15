import json
import pytest
from sqlalchemy import select
from middlewares.lang import resolve_message
from services.mysql.factory import DfEngineSettingsFactory
from services.mysql.factory.df_engine_upload_files import DfEngineUploadFilesFactory
from services.mysql.model import DfEngineExternalApiCalls
from tests.helpers import clear_external_api_call_logs, clear_setting_state


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
async def test_create_folder_success(authed_client, project_task, user_id, mock_udin):
    """200 OK; a subfolder is created under an existing (owned) folder, proxied to udin."""
    _make_file(project_task, user_id)
    parent = f"storage/DF-Engine/{project_task.project.uid}/upload/images"
    resp = await authed_client.call(
        "POST", _url(project_task.uid, "/folder"), json={"current_path": parent, "name": "new_sub"}
    )
    assert resp.status_code == 200
    assert any("new-folder" in call[1] for call in mock_udin.calls)


@pytest.mark.asyncio
async def test_create_folder_appears_in_response(authed_client, project_task, user_id, mock_udin):
    """The newly created (empty) folder is spliced into the returned tree, not just udin's disk."""
    _make_file(project_task, user_id)
    parent = f"storage/DF-Engine/{project_task.project.uid}/upload/images"
    resp = await authed_client.call(
        "POST", _url(project_task.uid, "/folder"), json={"current_path": parent, "name": "new_sub"}
    )
    assert resp.status_code == 200
    childs = next(node["childs"] for node in _flatten(resp.json()["data"]) if node["folder"] == parent)
    assert any(c["folder"] == f"{parent}/new_sub" for c in childs)


@pytest.mark.asyncio
async def test_create_folder_survives_a_later_unrelated_mutation(authed_client, project_task, user_id, mock_udin):
    """An empty folder created earlier must still show up after another mutation
    (e.g. nesting a second folder inside it) triggers its own cache invalidation."""
    _make_file(project_task, user_id)
    parent = f"storage/DF-Engine/{project_task.project.uid}/upload/images"
    first = f"{parent}/lagi_aha"
    await authed_client.call(
        "POST", _url(project_task.uid, "/folder"), json={"current_path": parent, "name": "lagi_aha"}
    )
    resp = await authed_client.call(
        "POST", _url(project_task.uid, "/folder"), json={"current_path": first, "name": "nested"}
    )
    assert resp.status_code == 200
    nodes = {n["folder"] for n in _flatten(resp.json()["data"])}
    assert first in nodes
    assert f"{first}/nested" in nodes


def _flatten(tree):
    for node in tree:
        yield node
        yield from _flatten(node["childs"])


@pytest.mark.asyncio
async def test_create_folder_unknown_parent_is_404(authed_client, project_task, mock_udin):
    """404 folder_not_found when current_path matches no folder."""
    resp = await authed_client.call(
        "POST",
        _url(project_task.uid, "/folder"),
        json={"current_path": "no/such/folder", "name": "x"},
        raise_for_status=False,
    )
    assert resp.status_code == 404
    assert resp.json()["message"] == resolve_message("folder_not_found", "en")


@pytest.mark.asyncio
async def test_create_folder_depth_exceeded_never_calls_udin(
    authed_client, project_task, user_id, mock_udin, db_session
):
    """422 folder_depth_exceeded once nesting would exceed the default folder depth limit; udin is never called."""
    await clear_setting_state(db_session)
    base = f"storage/DF-Engine/{project_task.project.uid}/upload/images"
    deep_path = "/".join([base] + [f"lvl{i}" for i in range(4)])
    _make_file(project_task, user_id, name="deep.png")
    DfEngineUploadFilesFactory.create(
        path=f"{deep_path}/deep.png",
        project_id=project_task.project_id,
        task_id=project_task.id,
        created_by=int(user_id),
    )
    resp = await authed_client.call(
        "POST",
        _url(project_task.uid, "/folder"),
        json={"current_path": deep_path, "name": "one_too_many"},
        raise_for_status=False,
    )
    assert resp.status_code == 422
    assert resp.json()["message"] == resolve_message("folder_depth_exceeded", "en")
    assert not mock_udin.calls


@pytest.mark.asyncio
async def test_create_folder_uses_admin_configured_depth_limit(
    authed_client, project_task, user_id, mock_udin, db_session
):
    """422 folder_depth_exceeded at a shallower depth once admin lowers folder_depth_limit via /setting;
    raising it back via the same row then allows the identical request to succeed."""
    await clear_setting_state(db_session)
    DfEngineSettingsFactory.create(key="folder_depth_limit", value=json.dumps(2), code="admin_setting")
    parent = f"storage/DF-Engine/{project_task.project.uid}/upload/images"
    _make_file(project_task, user_id)

    resp = await authed_client.call(
        "POST", _url(project_task.uid, "/folder"), json={"current_path": parent, "name": "lvl1"}, raise_for_status=False
    )
    assert resp.status_code == 200
    resp = await authed_client.call(
        "POST",
        _url(project_task.uid, "/folder"),
        json={"current_path": f"{parent}/lvl1", "name": "lvl2"},
        raise_for_status=False,
    )
    assert resp.status_code == 200
    resp = await authed_client.call(
        "POST",
        _url(project_task.uid, "/folder"),
        json={"current_path": f"{parent}/lvl1/lvl2", "name": "one_too_many"},
        raise_for_status=False,
    )
    assert resp.status_code == 422
    assert resp.json()["message"] == resolve_message("folder_depth_exceeded", "en")

    await authed_client.call("POST", "/api/setting", json={"folder_depth_limit": 10})
    resp = await authed_client.call(
        "POST",
        _url(project_task.uid, "/folder"),
        json={"current_path": f"{parent}/lvl1/lvl2", "name": "now_fits"},
        raise_for_status=False,
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_create_folder_logs_udin_call(authed_client, project_task, user_id, mock_udin, db_session):
    """A successful create-folder call writes one df_engine_external_api_calls row with type='udin'."""
    await clear_external_api_call_logs(db_session)
    _make_file(project_task, user_id)
    parent = f"storage/DF-Engine/{project_task.project.uid}/upload/images"
    resp = await authed_client.call(
        "POST", _url(project_task.uid, "/folder"), json={"current_path": parent, "name": "new_sub"}
    )
    assert resp.status_code == 200

    rows = (await db_session.execute(select(DfEngineExternalApiCalls))).scalars().all()
    assert len(rows) == 1
    assert rows[0].type == "udin"
    assert "new-folder" in rows[0].endpoint
