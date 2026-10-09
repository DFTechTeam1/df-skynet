import pytest
import pytest_asyncio
from uuid import uuid4
from sqlalchemy import select
from middlewares.lang import resolve_message
from config.variables import OVERRIDE_FILE_ROLES
from services.mysql.factory.df_engine_features import DfEngineFeaturesFactory
from services.mysql.factory.df_engine_generation_results import DfEngineGenerationResultsFactory
from services.mysql.factory.df_engine_generations import DfEngineGenerationsFactory
from services.mysql.factory.df_engine_menus import DfEngineMenusFactory
from services.mysql.factory.df_engine_model_options import DfEngineModelOptionsFactory
from services.mysql.factory.df_engine_upload_files import DfEngineUploadFilesFactory
from services.mysql.model import DfEngineGenerationResults, DfEngineUploadFiles
from services.mysql.model.df_engine_upload_files import UploadFileTypes

PLAIN = ["staff"]


def _root(project_task):
    return f"storage/DF-Engine/{project_task.project.name}_{project_task.project.uid[:8]}"


def _upload(project_task, created_by, path):
    return DfEngineUploadFilesFactory.create(
        type=UploadFileTypes.image,
        project_id=project_task.project_id,
        task_id=project_task.id,
        created_by=int(created_by),
        path=path,
        name=path.rsplit("/", 1)[-1],
    )


@pytest_asyncio.fixture
async def generation_fks(user_id) -> dict:
    return {
        "model_id": DfEngineModelOptionsFactory.create().id,
        "menu_id": DfEngineMenusFactory.create(created_by=int(user_id), df_engine_menu_feature_mapping=None).id,
        "feature_id": DfEngineFeaturesFactory.create(created_by=int(user_id), df_engine_feature_prompt_mapping=None).id,
    }


def _generated(project_task, created_by, path, fks, **kw):
    generation = DfEngineGenerationsFactory.create(
        project_id=project_task.project_id,
        task_id=project_task.id,
        created_by=int(created_by),
        sourceable_id=1,
        **fks,
    )
    return DfEngineGenerationResultsFactory.create(
        generation_id=generation.id, created_by=int(created_by), path=path, name=path.rsplit("/", 1)[-1], **kw
    )


async def _row(db_session, model, row_id):
    await db_session.commit()
    return (await db_session.execute(select(model).where(model.id == row_id))).scalars().first()


def _udin_rename(mock_udin, old, new):
    mock_udin.set(
        "rename-file",
        200,
        {
            "data": [
                {
                    "from": {"name": old.rsplit("/", 1)[-1], "path": old},
                    "to": {"name": new.rsplit("/", 1)[-1], "path": new},
                }
            ]
        },
    )


# ---------- rename ----------


@pytest.mark.asyncio
async def test_rename_upload_by_owner(authed_client, project_task, user_id, mock_udin, db_session, as_roles):
    """200; Udin gets filepath + name with the file's own extension, row name/path follow Udin's pair and updated_by is the caller."""
    as_roles(PLAIN)
    old = f"{_root(project_task)}/upload/images/a_{uuid4().hex[:6]}.jpg"
    new = old.replace("/a_", "/b_")
    row = _upload(project_task, user_id, old)
    _udin_rename(mock_udin, old, new)
    resp = await authed_client.call("PATCH", f"/api/files/upload/{row.uid}", json={"name": "b"}, raise_for_status=False)
    assert resp.status_code == 200, resp.text
    assert mock_udin.calls[-1][2] == {"filepath": old, "name": "b.jpg"}
    row = await _row(db_session, DfEngineUploadFiles, row.id)
    assert (row.path, row.updated_by) == (new, int(user_id)) and row.updated_at is not None


@pytest.mark.asyncio
async def test_rename_generated_by_owner(
    authed_client, project_task, user_id, mock_udin, db_session, as_roles, generation_fks
):
    """200; generated rows are renamed through the same Udin call, updated_by is the caller."""
    as_roles(PLAIN)
    old = f"{_root(project_task)}/generated/images/g_{uuid4().hex[:6]}.png"
    new = old.replace("/g_", "/h_")
    row = _generated(project_task, user_id, old, generation_fks)
    _udin_rename(mock_udin, old, new)
    resp = await authed_client.call(
        "PATCH", f"/api/files/generated/{row.uid}", json={"name": "h"}, raise_for_status=False
    )
    assert resp.status_code == 200, resp.text
    row = await _row(db_session, DfEngineGenerationResults, row.id)
    assert (row.path, row.updated_by) == (new, int(user_id))

    def find(node):
        for f in node.get("files") or []:
            if f["file_uid"] == row.uid:
                return f
        for c in node.get("children") or []:
            if found := find(c):
                return found

    tree_file = find(resp.json()["data"])
    assert tree_file["type"] == "generated" and tree_file["updater"]["user_id"] == int(user_id)


@pytest.mark.asyncio
async def test_rename_foreign_file_plain_role_is_refused(
    authed_client, project_task, other_user_id, mock_udin, as_roles
):
    """422 file_action_not_permitted for someone else's file; Udin is never called."""
    as_roles(PLAIN)
    row = _upload(project_task, other_user_id, f"{_root(project_task)}/upload/images/x_{uuid4().hex[:6]}.jpg")
    resp = await authed_client.call("PATCH", f"/api/files/upload/{row.uid}", json={"name": "n"}, raise_for_status=False)
    assert resp.status_code == 422
    assert resolve_message("file_action_not_permitted", "en") in resp.text and mock_udin.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("role", OVERRIDE_FILE_ROLES)
async def test_rename_foreign_file_override_role(
    authed_client, project_task, user_id, other_user_id, mock_udin, db_session, as_roles, role
):
    """200 for every override role; updated_by is the caller, created_by stays the original owner."""
    as_roles([role])
    old = f"{_root(project_task)}/upload/images/o_{uuid4().hex[:6]}.jpg"
    new = old.replace("/o_", "/p_")
    row = _upload(project_task, other_user_id, old)
    _udin_rename(mock_udin, old, new)
    resp = await authed_client.call("PATCH", f"/api/files/upload/{row.uid}", json={"name": "p"}, raise_for_status=False)
    assert resp.status_code == 200, resp.text
    row = await _row(db_session, DfEngineUploadFiles, row.id)
    assert (row.updated_by, row.created_by) == (int(user_id), other_user_id)


@pytest.mark.asyncio
async def test_rename_unknown_uid_and_bad_source(authed_client, as_roles):
    """404 file_not_found for an unknown uid; 422 for a source outside generated/upload."""
    as_roles(PLAIN)
    resp = await authed_client.call("PATCH", f"/api/files/upload/{uuid4()}", json={"name": "n"}, raise_for_status=False)
    assert resp.status_code == 404
    resp = await authed_client.call("PATCH", f"/api/files/bogus/{uuid4()}", json={"name": "n"}, raise_for_status=False)
    assert resp.status_code == 422


# ---------- move ----------


@pytest.mark.asyncio
async def test_move_upload_files(authed_client, project_task, user_id, mock_udin, db_session, as_roles):
    """200; Udin gets sources+destination, both rows follow the pairs with updated_by set."""
    as_roles(PLAIN)
    base = f"{_root(project_task)}/upload/images"
    dest = f"{base}/dest_{uuid4().hex[:5]}"
    _upload_dest = DfEngineUploadFilesFactory.create(
        type=UploadFileTypes.folder,
        project_id=project_task.project_id,
        task_id=project_task.id,
        created_by=int(user_id),
        path=dest,
        name=dest.rsplit("/", 1)[-1],
        size=0,
    )
    olds = [f"{base}/m{i}_{uuid4().hex[:5]}.jpg" for i in range(2)]
    rows = [_upload(project_task, user_id, p) for p in olds]
    mock_udin.set(
        "move-files",
        200,
        {
            "data": [
                {
                    "from": {"name": p.rsplit("/", 1)[-1], "path": p},
                    "to": {"name": p.rsplit("/", 1)[-1], "path": f"{dest}/{p.rsplit('/', 1)[-1]}"},
                }
                for p in olds
            ]
        },
    )
    resp = await authed_client.call(
        "PATCH",
        "/api/files/upload",
        json={"file_uids": [r.uid for r in rows], "destination": dest},
        raise_for_status=False,
    )
    assert resp.status_code == 200, resp.text
    assert mock_udin.calls[-1][2] == {"sources": olds, "destination": dest}
    for row, old in zip(rows, olds):
        moved = await _row(db_session, DfEngineUploadFiles, row.id)
        assert moved.path == f"{dest}/{old.rsplit('/', 1)[-1]}" and moved.updated_by == int(user_id)


@pytest.mark.asyncio
async def test_move_mixed_batch_is_atomic(authed_client, project_task, user_id, other_user_id, mock_udin, as_roles):
    """422 on the foreign file's index; nothing is sent to Udin."""
    as_roles(PLAIN)
    base = f"{_root(project_task)}/upload/images"
    mine = _upload(project_task, user_id, f"{base}/a_{uuid4().hex[:5]}.jpg")
    theirs = _upload(project_task, other_user_id, f"{base}/b_{uuid4().hex[:5]}.jpg")
    resp = await authed_client.call(
        "PATCH",
        "/api/files/upload",
        json={"file_uids": [mine.uid, theirs.uid], "destination": f"{base}/x"},
        raise_for_status=False,
    )
    assert resp.status_code == 422 and "file_uids.1" in resp.text and mock_udin.calls == []


@pytest.mark.asyncio
async def test_move_to_missing_destination_is_404(authed_client, project_task, user_id, mock_udin, as_roles):
    """404 folder_not_found; Udin is never called."""
    as_roles(PLAIN)
    base = f"{_root(project_task)}/upload/images"
    row = _upload(project_task, user_id, f"{base}/a_{uuid4().hex[:5]}.jpg")
    resp = await authed_client.call(
        "PATCH",
        "/api/files/upload",
        json={"file_uids": [row.uid], "destination": f"{base}/nope_{uuid4().hex[:5]}"},
        raise_for_status=False,
    )
    assert resp.status_code == 404 and mock_udin.calls == []


@pytest.mark.asyncio
async def test_move_archived_generated_is_refused(
    authed_client, project_task, user_id, mock_udin, as_roles, generation_fks
):
    """422 file_move_not_permitted for an archived generated file."""
    from utils import local_time

    as_roles(PLAIN)
    base = f"{_root(project_task)}/generated/images"
    row = _generated(
        project_task, user_id, f"{base}/a_{uuid4().hex[:5]}.png", generation_fks, archieved_at=local_time()
    )
    resp = await authed_client.call(
        "PATCH",
        "/api/files/generated",
        json={"file_uids": [row.uid], "destination": base},
        raise_for_status=False,
    )
    assert resp.status_code in (404, 422) and mock_udin.calls == []


# ---------- delete ----------


@pytest.mark.asyncio
async def test_delete_upload_by_owner(authed_client, project_task, user_id, mock_udin, db_session, as_roles):
    """200; Udin gets sources, the row is gone."""
    as_roles(PLAIN)
    path = f"{_root(project_task)}/upload/images/d_{uuid4().hex[:6]}.jpg"
    row = _upload(project_task, user_id, path)
    mock_udin.set("delete-files", 200, {"data": [{"path": path}]})
    resp = await authed_client.call(
        "DELETE", "/api/files/upload", json={"file_uids": [row.uid]}, raise_for_status=False
    )
    assert resp.status_code == 200, resp.text
    assert mock_udin.calls[-1][2] == {"sources": [path]}
    assert await _row(db_session, DfEngineUploadFiles, row.id) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("roles", [PLAIN, [OVERRIDE_FILE_ROLES[1]]])
async def test_delete_generated_has_no_endpoint(
    authed_client, project_task, user_id, mock_udin, db_session, as_roles, generation_fks, roles
):
    """DELETE /files/generated does not exist (404/405), even for override roles; row intact, Udin not called."""
    as_roles(roles)
    row = _generated(
        project_task, user_id, f"{_root(project_task)}/generated/images/k_{uuid4().hex[:5]}.png", generation_fks
    )
    resp = await authed_client.call(
        "DELETE", "/api/files/generated", json={"file_uids": [row.uid]}, raise_for_status=False
    )
    assert resp.status_code in (404, 405)
    assert mock_udin.calls == [] and await _row(db_session, DfEngineGenerationResults, row.id) is not None


@pytest.mark.asyncio
async def test_delete_foreign_upload_plain_vs_override(
    authed_client, project_task, other_user_id, mock_udin, db_session, as_roles
):
    """Plain role -> 422; override role -> 200 and the row is removed."""
    path = f"{_root(project_task)}/upload/images/f_{uuid4().hex[:6]}.jpg"
    row = _upload(project_task, other_user_id, path)
    as_roles(PLAIN)
    resp = await authed_client.call(
        "DELETE", "/api/files/upload", json={"file_uids": [row.uid]}, raise_for_status=False
    )
    assert resp.status_code == 422 and mock_udin.calls == []
    as_roles([OVERRIDE_FILE_ROLES[0]])
    mock_udin.set("delete-files", 200, {"data": [{"path": path}]})
    resp = await authed_client.call(
        "DELETE", "/api/files/upload", json={"file_uids": [row.uid]}, raise_for_status=False
    )
    assert resp.status_code == 200, resp.text
    assert await _row(db_session, DfEngineUploadFiles, row.id) is None


@pytest.mark.asyncio
async def test_tree_marks_type_and_override_actions(authed_client, project_task, other_user_id, as_roles):
    """Tree files carry type=upload; override role sees all actions True on someone else's file, plain sees none."""
    path = f"{_root(project_task)}/upload/images/t_{uuid4().hex[:6]}.jpg"
    row = _upload(project_task, other_user_id, path)

    def find(node):
        for f in node.get("files") or []:
            if f["file_uid"] == row.uid:
                return f
        for c in node.get("children") or []:
            if found := find(c):
                return found

    as_roles(PLAIN)
    plain = find((await authed_client.call("GET", f"/api/files/{project_task.uid}")).json()["data"])
    await authed_client.call("GET", f"/api/files/{project_task.uid}")  # warm
    as_roles([OVERRIDE_FILE_ROLES[1]])
    over = find((await authed_client.call("GET", f"/api/files/{project_task.uid}")).json()["data"])
    assert plain["type"] == over["type"] == "upload"
    assert not any(plain["action"][k] for k in ("can_rename", "can_delete", "can_choose_to_move"))
    assert all(over["action"][k] for k in ("can_rename", "can_delete", "can_choose_to_move"))


@pytest.mark.asyncio
async def test_rename_keeps_a_dot_in_the_new_name(authed_client, project_task, user_id, mock_udin, as_roles):
    """200; a name like `anjay.txt lagii` is sent with the real extension appended, so Udin cannot read `.txt lagii` as one."""
    as_roles(PLAIN)
    old = f"{_root(project_task)}/upload/images/a_{uuid4().hex[:6]}.png"
    row = _upload(project_task, user_id, old)
    _udin_rename(mock_udin, old, old.replace("/a_", "/b_"))
    resp = await authed_client.call(
        "PATCH", f"/api/files/upload/{row.uid}", json={"name": "anjay.txt lagii"}, raise_for_status=False
    )
    assert resp.status_code == 200, resp.text
    assert mock_udin.calls[-1][2] == {"filepath": old, "name": "anjay.txt lagii.png"}
