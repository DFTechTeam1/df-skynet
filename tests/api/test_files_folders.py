import pytest
from uuid import uuid4
from httpx import TimeoutException
from sqlalchemy import select
from services.mysql.factory.df_engine_upload_files import DfEngineUploadFilesFactory
from services.mysql.model import DfEngineUploadFiles
from services.mysql.model.df_engine_upload_files import UploadFileTypes


def _url(task_uid, suffix="folders"):
    return f"/api/files/{task_uid}/{suffix}"


def _root(project_task):
    project = project_task.project
    return f"storage/DF-Engine/{project.name}_{project.uid[:8]}"


def _walk(node):
    yield node
    for child in node.get("children") or []:
        yield from _walk(child)


def _folder(tree, path):
    return next((n for n in _walk(tree) if n["path"] == path), None)


def _upload(project_task, user_id, path, **kw):
    return DfEngineUploadFilesFactory.create(
        type=kw.pop("type", UploadFileTypes.image),
        project_id=project_task.project_id,
        task_id=project_task.id,
        created_by=int(user_id),
        path=path,
        name=path.rsplit("/", 1)[-1],
        **kw,
    )


async def _reload(db_session, *rows):
    """Re-read factory-made rows (they belong to another session) after the request committed."""
    await db_session.commit()
    ids = [row.id for row in rows]
    found = {
        r.id: r
        for r in (
            await db_session.execute(select(DfEngineUploadFiles).where(DfEngineUploadFiles.id.in_(ids)))
        ).scalars()
    }
    return [found.get(i) for i in ids]


@pytest.mark.asyncio
async def test_create_folder_inserts_row_with_creator_and_shows_in_tree(
    authed_client, project_task, user_id, mock_udin, db_session
):
    """201; Udin gets the parent path + name, a folder row is stored with created_by (updated_by stays null) and the empty folder is in the returned tree."""
    parent = f"{_root(project_task)}/upload/images"
    new = f"{parent}/refs_{uuid4().hex[:6]}"
    mock_udin.set("new-folder", 200, {"data": {"name": None, "path": new, "size": 0, "md5": None}})

    resp = await authed_client.call(
        "POST", _url(project_task.uid), json={"path": parent, "name": new.rsplit("/", 1)[-1]}, raise_for_status=False
    )
    assert resp.status_code == 201, resp.text
    assert mock_udin.calls[-1][2] == {"current_path": parent, "name": new.rsplit("/", 1)[-1]}
    folder = _folder(resp.json()["data"], new)
    assert folder is not None and folder["files"] == []
    assert folder["creator"]["user_id"] == int(user_id) and folder["updater"] is None
    await db_session.commit()  # end the fixture's snapshot so the request's committed rows are visible
    row = (
        (await db_session.execute(select(DfEngineUploadFiles).where(DfEngineUploadFiles.path == new))).scalars().first()
    )
    assert (row.type, row.created_by, row.updated_by) == (UploadFileTypes.folder, int(user_id), None)


@pytest.mark.asyncio
async def test_create_folder_in_protected_parent_is_refused(authed_client, project_task, mock_udin, user_id):
    """422 invalid_folder_scope; the project folder / `upload` cannot take a subfolder and Udin is never called."""
    _upload(project_task, user_id, f"{_root(project_task)}/upload/images/a.jpg")
    resp = await authed_client.call(
        "POST",
        _url(project_task.uid),
        json={"path": f"{_root(project_task)}/upload", "name": "x"},
        raise_for_status=False,
    )
    assert resp.status_code == 422
    assert mock_udin.calls == []


@pytest.mark.asyncio
async def test_create_folder_name_with_slash_is_422(authed_client, project_task):
    """422 from payload validation when the name contains a path separator."""
    resp = await authed_client.call(
        "POST", _url(project_task.uid), json={"path": "a/b", "name": "x/y"}, raise_for_status=False
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_folder_udin_timeout_is_504(authed_client, project_task, user_id, mock_udin):
    """504 when Udin times out."""
    parent = f"{_root(project_task)}/upload/images"
    _upload(project_task, user_id, f"{parent}/a.jpg")
    mock_udin.raise_on_udin(TimeoutException("slow"))
    resp = await authed_client.call(
        "POST", _url(project_task.uid), json={"path": parent, "name": "x"}, raise_for_status=False
    )
    assert resp.status_code == 504


@pytest.mark.asyncio
async def test_rename_by_a_coworker_rewrites_files_and_updated_by(
    authed_client, project_task, user_id, other_user_id, mock_udin, db_session
):
    """200; a folder created by someone else can be renamed: file rows follow Udin's from/to pairs, the folder row moves, updated_by is the caller, creator is unchanged."""
    base = f"{_root(project_task)}/upload/images"
    old, new = f"{base}/drafts_{uuid4().hex[:5]}", f"{base}/final_{uuid4().hex[:5]}"
    folder_row = _upload(project_task, other_user_id, old, type=UploadFileTypes.folder, size=0)
    file_row = _upload(project_task, other_user_id, f"{old}/a.jpg")
    mock_udin.set(
        "rename-folder",
        200,
        {
            "data": [
                {"from": {"name": "a.jpg", "path": f"{old}/a.jpg"}, "to": {"name": "a.jpg", "path": f"{new}/a.jpg"}}
            ]
        },
    )

    resp = await authed_client.call(
        "PATCH", _url(project_task.uid), json={"path": old, "name": new.rsplit("/", 1)[-1]}, raise_for_status=False
    )
    assert resp.status_code == 200, resp.text
    assert mock_udin.calls[-1][2] == {"path": old, "name": new.rsplit("/", 1)[-1]}
    folder_row, file_row = await _reload(db_session, folder_row, file_row)
    assert (folder_row.path, folder_row.name, folder_row.updated_by) == (new, new.rsplit("/", 1)[-1], int(user_id))
    assert file_row.path == f"{new}/a.jpg" and file_row.updated_by == int(user_id)
    assert folder_row.created_by == other_user_id
    tree_folder = _folder(resp.json()["data"], new)
    assert tree_folder["creator"]["user_id"] == other_user_id and tree_folder["updater"]["user_id"] == int(user_id)
    assert _folder(resp.json()["data"], old) is None


@pytest.mark.asyncio
async def test_rename_type_root_is_refused(authed_client, project_task, user_id, mock_udin):
    """422 folder_action_not_permitted for `upload/images` (main folder); Udin is never called."""
    root = f"{_root(project_task)}/upload/images"
    _upload(project_task, user_id, f"{root}/a.jpg")
    resp = await authed_client.call(
        "PATCH", _url(project_task.uid), json={"path": root, "name": "x"}, raise_for_status=False
    )
    assert resp.status_code == 422
    assert mock_udin.calls == []


@pytest.mark.asyncio
async def test_rename_unknown_folder_is_404(authed_client, project_task, user_id):
    """404 folder_not_found for a path not in the tree."""
    _upload(project_task, user_id, f"{_root(project_task)}/upload/images/a.jpg")
    resp = await authed_client.call(
        "PATCH",
        _url(project_task.uid),
        json={"path": f"{_root(project_task)}/upload/images/nope", "name": "x"},
        raise_for_status=False,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_promotes_files_and_removes_folder_rows(
    authed_client, project_task, user_id, mock_udin, db_session
):
    """200; files move to the parent with the collision-renamed name Udin returns, folder + nested folder rows are deleted, updated_by is set."""
    base = f"{_root(project_task)}/upload/images"
    folder = f"{base}/gone_{uuid4().hex[:5]}"
    folder_row = _upload(project_task, user_id, folder, type=UploadFileTypes.folder, size=0)
    nested_row = _upload(project_task, user_id, f"{folder}/inner", type=UploadFileTypes.folder, size=0)
    file_row = _upload(project_task, user_id, f"{folder}/inner/a.jpg")
    promoted = f"{base}/a_1.jpg"
    mock_udin.set(
        "delete-folder",
        200,
        {"data": [{"from": {"name": "a.jpg", "path": file_row.path}, "to": {"name": "a_1.jpg", "path": promoted}}]},
    )

    resp = await authed_client.call("DELETE", _url(project_task.uid), params={"path": folder}, raise_for_status=False)
    assert resp.status_code == 200, resp.text
    assert mock_udin.calls[-1][0] == "DELETE" and mock_udin.calls[-1][2] == {"path": folder}
    (file_row,) = await _reload(db_session, file_row)
    assert (file_row.path, file_row.name, file_row.updated_by) == (promoted, "a_1.jpg", int(user_id))
    assert await _reload(db_session, folder_row, nested_row) == [None, None]
    assert _folder(resp.json()["data"], folder) is None


@pytest.mark.asyncio
async def test_delete_type_root_is_refused(authed_client, project_task, user_id, mock_udin):
    """422 folder_action_not_permitted for `upload`; Udin is never called."""
    _upload(project_task, user_id, f"{_root(project_task)}/upload/images/a.jpg")
    resp = await authed_client.call(
        "DELETE", _url(project_task.uid), params={"path": f"{_root(project_task)}/upload"}, raise_for_status=False
    )
    assert resp.status_code == 422
    assert mock_udin.calls == []


@pytest.mark.asyncio
async def test_delete_udin_rejection_is_forwarded(authed_client, project_task, user_id, mock_udin):
    """Udin's status is forwarded with the folder_delete_failed message."""
    base = f"{_root(project_task)}/upload/images"
    folder = f"{base}/x_{uuid4().hex[:5]}"
    _upload(project_task, user_id, f"{folder}/a.jpg")
    mock_udin.set("delete-folder", 422, {"error": {"path": ["Invalid folder path."]}})
    resp = await authed_client.call("DELETE", _url(project_task.uid), params={"path": folder}, raise_for_status=False)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_move_folders_rewrites_prefixes_in_one_call(authed_client, project_task, user_id, mock_udin, db_session):
    """200; several folders go in one Udin `sources` call, folder rows and file rows follow by prefix, updated_by is set."""
    base = f"{_root(project_task)}/upload/images"
    tag = uuid4().hex[:5]
    dest, a, b = f"{base}/dest_{tag}", f"{base}/a_{tag}", f"{base}/b_{tag}"
    _upload(project_task, user_id, dest, type=UploadFileTypes.folder, size=0)
    a_row = _upload(project_task, user_id, a, type=UploadFileTypes.folder, size=0)
    b_row = _upload(project_task, user_id, b, type=UploadFileTypes.folder, size=0)
    f_row = _upload(project_task, user_id, f"{a}/x.jpg")
    mock_udin.set(
        "move-folders",
        200,
        {
            "data": [
                {
                    "from": {"name": "x.jpg", "path": f"{a}/x.jpg"},
                    "to": {"name": "x.jpg", "path": f"{dest}/a_{tag}/x.jpg"},
                }
            ]
        },
    )

    resp = await authed_client.call(
        "PATCH",
        _url(project_task.uid, "folders/move"),
        json={"folder_paths": [a, b, a], "destination": dest},
        raise_for_status=False,
    )
    assert resp.status_code == 200, resp.text
    assert mock_udin.calls[-1][2] == {"sources": [a, b], "destination": dest}
    a_row, b_row, f_row = await _reload(db_session, a_row, b_row, f_row)
    assert (a_row.path, b_row.path) == (f"{dest}/a_{tag}", f"{dest}/b_{tag}")
    assert f_row.path == f"{dest}/a_{tag}/x.jpg" and f_row.updated_by == int(user_id)
    assert _folder(resp.json()["data"], f"{dest}/a_{tag}") is not None


@pytest.mark.asyncio
async def test_move_between_upload_and_generated_is_refused(authed_client, project_task, user_id, mock_udin):
    """422 folders_move_failed with invalid_folder_scope on the source when upload and generated are mixed; Udin is never called."""
    root = _root(project_task)
    src, dest = f"{root}/upload/images/s_{uuid4().hex[:5]}", f"{root}/generated/images/d_{uuid4().hex[:5]}"
    _upload(project_task, user_id, src, type=UploadFileTypes.folder, size=0)
    _upload(project_task, user_id, dest, type=UploadFileTypes.folder, size=0)
    resp = await authed_client.call(
        "PATCH",
        _url(project_task.uid, "folders/move"),
        json={"folder_paths": [src], "destination": dest},
        raise_for_status=False,
    )
    assert resp.status_code == 422
    assert "folder_paths.0" in resp.json()["error"]
    assert mock_udin.calls == []


@pytest.mark.asyncio
async def test_move_images_into_videos_into_itself_and_type_root_are_refused(
    authed_client, project_task, user_id, mock_udin
):
    """422 per source: another type, its own descendant, and a protected type root."""
    root = _root(project_task)
    tag = uuid4().hex[:5]
    images_dir, videos_dir = f"{root}/upload/images/i_{tag}", f"{root}/upload/videos/v_{tag}"
    for path in (images_dir, videos_dir, f"{images_dir}/child"):
        _upload(project_task, user_id, path, type=UploadFileTypes.folder, size=0)
    for sources, dest in (
        ([images_dir], videos_dir),
        ([images_dir], f"{images_dir}/child"),
        ([f"{root}/upload/images"], videos_dir),
    ):
        resp = await authed_client.call(
            "PATCH",
            _url(project_task.uid, "folders/move"),
            json={"folder_paths": sources, "destination": dest},
            raise_for_status=False,
        )
        assert resp.status_code == 422, (sources, dest)
    assert mock_udin.calls == []


@pytest.mark.asyncio
async def test_move_udin_errors_use_folder_paths_keys(authed_client, project_task, user_id, mock_udin):
    """Udin's `sources.<i>` error keys come back as `folder_paths.<i>`."""
    base = f"{_root(project_task)}/upload/images"
    tag = uuid4().hex[:5]
    src, dest = f"{base}/s_{tag}", f"{base}/d_{tag}"
    _upload(project_task, user_id, src, type=UploadFileTypes.folder, size=0)
    _upload(project_task, user_id, dest, type=UploadFileTypes.folder, size=0)
    mock_udin.set(
        "move-folders",
        422,
        {"error": {"sources.0": ["A folder with the same name already exists at the destination."]}},
    )
    resp = await authed_client.call(
        "PATCH",
        _url(project_task.uid, "folders/move"),
        json={"folder_paths": [src], "destination": dest},
        raise_for_status=False,
    )
    assert resp.status_code == 422
    assert list(resp.json()["error"]) == ["folder_paths.0"]
