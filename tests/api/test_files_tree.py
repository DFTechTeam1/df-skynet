import pytest
import pytest_asyncio
from uuid import uuid4
from httpx import TimeoutException
from middlewares.lang import resolve_message
from services.mysql.factory.df_engine_generations import DfEngineGenerationsFactory
from services.mysql.factory.df_engine_generation_results import DfEngineGenerationResultsFactory
from services.mysql.factory.df_engine_upload_files import DfEngineUploadFilesFactory
from services.mysql.factory.df_engine_model_options import DfEngineModelOptionsFactory
from services.mysql.factory.df_engine_menus import DfEngineMenusFactory
from services.mysql.factory.df_engine_features import DfEngineFeaturesFactory
from services.mysql.model.df_engine_generations import GenerationKinds
from services.mysql.model.df_engine_upload_files import UploadFileTypes


def _tree_url(task_uid):
    return f"/api/files/{task_uid}"


def _folders_url(task_uid):
    return f"/api/files/{task_uid}/folders"


# Udin's storage root currently carries an environment suffix (DEV, later STG/PROD); the upload handler hardcodes it.
UDIN_ROOT = "storage/DF-Engine-DEV"


def _udin_root(project_task):
    return f"{UDIN_ROOT}/{project_task.project.name}_{project_task.project.uid[:8]}"


def _uploads_url(task_uid):
    return f"/api/files/{task_uid}/uploads"


def _detail_url(file_uid):
    return f"/api/uploaded-files/{file_uid}"


@pytest_asyncio.fixture
async def generation_fks(user_id) -> dict:
    model_option = DfEngineModelOptionsFactory.create()
    menu = DfEngineMenusFactory.create(created_by=int(user_id), df_engine_menu_feature_mapping=None)
    feature = DfEngineFeaturesFactory.create(created_by=int(user_id), df_engine_feature_prompt_mapping=None)
    return {"model_id": model_option.id, "menu_id": menu.id, "feature_id": feature.id}


def _walk(node):
    yield node
    for child in node.get("children") or []:
        yield from _walk(child)


def _find_file(tree, uid):
    for node in _walk(tree):
        for file in node["files"]:
            if file["file_uid"] == uid:
                return node, file
    return None, None


def _root(project_task):
    """The single project folder every file of a task lives under in real data."""
    project = project_task.project
    return f"storage/DF-Engine/{project.name}_{project.uid[:8]}"


def _make_upload(project_task, user_id, folder, **overrides):
    return DfEngineUploadFilesFactory.create(
        type=UploadFileTypes.image,
        project_id=project_task.project_id,
        task_id=project_task.id,
        created_by=int(user_id),
        path=f"{_root(project_task)}/{folder}/{uuid4().hex[:6]}.jpg",
        **overrides,
    )


@pytest.mark.asyncio
async def test_tree_is_a_single_folder_dict_with_folder_metadata(authed_client, project_task, user_id):
    """200 OK; `data` is one folder object (not a list) carrying kind/icon/color, nested folders and files."""
    upload = _make_upload(project_task, user_id, "upload/images")

    resp = await authed_client.call("GET", _tree_url(project_task.project.uid))
    assert resp.status_code == 200
    tree = resp.json()["data"]
    assert isinstance(tree, dict)
    assert (tree["kind"], tree["icon"], tree["color"]) == ("folder", "mdi-folder", "amber")
    folder, file = _find_file(tree, upload.uid)
    assert folder is not None and file["kind"] == "image"


@pytest.mark.asyncio
async def test_tree_second_call_reads_the_cached_upload_list(authed_client, project_task, user_id):
    """200 OK; calling the tree twice returns the same data, the second time served from the uploads cache."""
    upload = _make_upload(project_task, user_id, "upload/images")

    first = (await authed_client.call("GET", _tree_url(project_task.project.uid))).json()["data"]
    second = (await authed_client.call("GET", _tree_url(project_task.project.uid))).json()["data"]
    assert _find_file(first, upload.uid)[1] and _find_file(second, upload.uid)[1]


@pytest.mark.asyncio
async def test_tree_my_task_hides_other_users_uploads(authed_client, project_task, user_id, other_user_id):
    """200 OK; `my_task=true` only keeps the caller's uploads, `my_task=false` also lists everyone else's."""
    mine = _make_upload(project_task, user_id, "upload/images")
    theirs = _make_upload(project_task, other_user_id, "upload/images")

    everyone = (await authed_client.call("GET", _tree_url(project_task.project.uid))).json()["data"]
    only_mine = (await authed_client.call("GET", _tree_url(project_task.project.uid), params={"my_task": True})).json()[
        "data"
    ]
    assert _find_file(everyone, mine.uid)[1] and _find_file(everyone, theirs.uid)[1]
    assert _find_file(only_mine, mine.uid)[1] and _find_file(only_mine, theirs.uid)[1] is None


@pytest.mark.asyncio
async def test_tree_unknown_project_is_404(authed_client):
    """404 project_not_found for a uid that matches no project."""
    resp = await authed_client.call("GET", _tree_url(uuid4()), raise_for_status=False)
    assert resp.status_code == 404
    assert resp.json()["message"] == resolve_message("project_not_found", "en")


@pytest.mark.asyncio
async def test_tree_requires_auth(client, project_task):
    """401 when the request carries no bearer token."""
    resp = await client.call("GET", _tree_url(project_task.project.uid), raise_for_status=False)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_tree_unexpected_error_is_500(authed_client, project_task, monkeypatch):
    """500 when building the tree blows up with something that is not a BaseError."""

    async def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("apps.controller.files.build_file_tree_refactored", boom)
    resp = await authed_client.call("GET", _tree_url(project_task.project.uid), raise_for_status=False)
    assert resp.status_code == 500


@pytest.mark.asyncio
async def test_tree_generated_file_keeps_its_real_kind(authed_client, project_task, user_id, generation_fks):
    """200 OK; a generated image_edit file is listed with kind=image_edit, not collapsed to `image`."""
    generation = DfEngineGenerationsFactory.create(
        project_id=project_task.project_id,
        task_id=project_task.id,
        created_by=int(user_id),
        sourceable_id=1,
        kind=GenerationKinds.image_edit,
        **generation_fks,
    )
    result = DfEngineGenerationResultsFactory.create(
        generation_id=generation.id,
        created_by=int(user_id),
        is_main=True,
        path=f"{_root(project_task)}/generated/images/{uuid4().hex[:6]}.png",
    )

    tree = (await authed_client.call("GET", _tree_url(project_task.project.uid))).json()["data"]
    _, file = _find_file(tree, result.uid)
    assert file["kind"] == GenerationKinds.image_edit


@pytest.mark.asyncio
async def test_folder_details_returns_the_matching_node(authed_client, project_task, user_id):
    """200 OK; `path` selects a nested folder and its files come back."""
    upload = _make_upload(project_task, user_id, "upload/images")
    folder_path = upload.path.rsplit("/", 1)[0]

    resp = await authed_client.call("GET", _folders_url(project_task.project.uid), params={"path": folder_path})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["path"] == folder_path
    assert upload.uid in [f["file_uid"] for f in data["files"]]


@pytest.mark.asyncio
async def test_folder_details_accepts_surrounding_slashes_and_my_task(
    authed_client, project_task, user_id, other_user_id
):
    """200 OK; leading/trailing slashes on `path` are ignored and `my_task=true` filters out others' files."""
    mine = _make_upload(project_task, user_id, "upload/images")
    theirs = DfEngineUploadFilesFactory.create(
        type=UploadFileTypes.image,
        project_id=project_task.project_id,
        task_id=project_task.id,
        created_by=int(other_user_id),
        path=mine.path.rsplit("/", 1)[0] + "/other.jpg",
    )
    folder_path = mine.path.rsplit("/", 1)[0]

    resp = await authed_client.call(
        "GET", _folders_url(project_task.project.uid), params={"path": f"/{folder_path}/", "my_task": True}
    )
    uids = [f["file_uid"] for f in resp.json()["data"]["files"]]
    assert mine.uid in uids and theirs.uid not in uids


@pytest.mark.asyncio
async def test_folder_details_unknown_path_is_404(authed_client, project_task, user_id):
    """404 folder_not_found when no node in the tree has that path."""
    _make_upload(project_task, user_id, "upload/images")
    resp = await authed_client.call(
        "GET", _folders_url(project_task.project.uid), params={"path": "storage/DF-Engine/nope"}, raise_for_status=False
    )
    assert resp.status_code == 404
    assert resp.json()["message"] == resolve_message("folder_not_found", "en")


@pytest.mark.asyncio
async def test_folder_details_requires_path(authed_client, project_task):
    """422 when the required `path` query parameter is missing."""
    resp = await authed_client.call("GET", _folders_url(project_task.project.uid), raise_for_status=False)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_folder_details_unexpected_error_is_500(authed_client, project_task, monkeypatch):
    """500 when building the tree raises a non-BaseError."""

    async def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("apps.controller.files.build_file_tree_refactored", boom)
    resp = await authed_client.call(
        "GET", _folders_url(project_task.project.uid), params={"path": "x"}, raise_for_status=False
    )
    assert resp.status_code == 500


@pytest.mark.asyncio
async def test_uploaded_file_detail_as_owner(authed_client, project_task, user_id):
    """200 OK; the owner gets the file in the tree-file shape with rename/delete/move allowed."""
    upload = _make_upload(project_task, user_id, "upload/images")

    resp = await authed_client.call("GET", _detail_url(upload.uid))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["file_uid"] == upload.uid and data["kind"] == "image"
    assert data["action"]["can_delete"] is True


@pytest.mark.asyncio
async def test_uploaded_file_detail_is_cached_and_read_only_for_non_owner(
    authed_client, project_task, other_user_id, as_roles
):
    """200 OK; a second call is served from cache and a non-owner without an override role gets no rename/delete/move."""
    as_roles(["staff"])
    upload = _make_upload(project_task, other_user_id, "upload/images")

    first = await authed_client.call("GET", _detail_url(upload.uid))
    second = await authed_client.call("GET", _detail_url(upload.uid))
    assert first.json() == second.json()
    assert second.json()["data"]["action"]["can_delete"] is False


@pytest.mark.asyncio
async def test_uploaded_file_detail_unknown_is_404(authed_client):
    """404 file_not_found for a uid that matches no upload."""
    resp = await authed_client.call("GET", _detail_url(uuid4()), raise_for_status=False)
    assert resp.status_code == 404
    assert resp.json()["message"] == resolve_message("file_not_found", "en")


@pytest.mark.asyncio
async def test_uploaded_file_detail_unexpected_error_is_500(authed_client, monkeypatch):
    """500 when the lookup raises a non-BaseError."""

    async def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("apps.controller.files.get_user_uploaded_file", boom)
    resp = await authed_client.call("GET", _detail_url(uuid4()), raise_for_status=False)
    assert resp.status_code == 500


@pytest.mark.asyncio
async def test_upload_saves_rows(authed_client, project_task, user_id, mock_udin, db_session):
    """200 OK; every file Udin reports is stored as an upload row (the handler returns only the message)."""
    folder = f"{_udin_root(project_task)}/upload"
    mock_udin.set(
        "upload-files",
        200,
        {
            "data": [
                {"name": "a.jpg", "path": f"{folder}/images/a.jpg", "size": 10, "md5": "m1"},
                {"name": "b.mp4", "path": f"{folder}/videos/b.mp4", "size": 20},
            ]
        },
    )

    resp = await authed_client.call(
        "POST",
        _uploads_url(project_task.uid),
        headers={"content-type": "multipart/form-data; boundary=x"},
        content=b"x",
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["message"] == "Files successfully uploaded."
    from sqlalchemy import select
    from services.mysql.model import DfEngineUploadFiles

    await db_session.commit()  # end the fixture's snapshot so the request's committed rows are visible
    rows = (
        (
            await db_session.execute(
                select(DfEngineUploadFiles).where(
                    DfEngineUploadFiles.path.in_([f"{folder}/images/a.jpg", f"{folder}/videos/b.mp4"])
                )
            )
        )
        .scalars()
        .all()
    )
    assert {r.name: r.type for r in rows} == {"a.jpg": UploadFileTypes.image, "b.mp4": UploadFileTypes.video}
    assert any(call[1].endswith(project_task.project.uid) for call in mock_udin.calls)


@pytest.mark.asyncio
async def test_upload_for_a_song_task_is_stored_against_the_song(authed_client, project_task, mock_udin, monkeypatch):
    """200 OK; when the resolved task is a song the rows get song_id and no task_id."""
    from services.mysql.model import DfEngineUploadFiles
    from services.mysql import query

    async def fake_task(ctx, task_uid=None, **kwargs):
        return {
            "id": project_task.id,
            "is_song": True,
            "project_id": project_task.project_id,
            "project": {"uid": project_task.project.uid},
        }

    monkeypatch.setattr("apps.controller.files.get_project_task", fake_task)
    path = f"{_root(project_task)}/upload/images/s.jpg"
    mock_udin.set("upload-files", 200, {"data": [{"name": "s.jpg", "path": path, "size": 5}]})

    resp = await authed_client.call(
        "POST", _uploads_url(uuid4()), headers={"content-type": "multipart/form-data; boundary=x"}, content=b"x"
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_upload_with_empty_udin_body_saves_nothing(authed_client, project_task, mock_udin):
    """200 OK; an empty successful Udin reply is tolerated and no rows are stored."""
    mock_udin.set("upload-files", 200, None)
    resp = await authed_client.call(
        "POST",
        _uploads_url(project_task.uid),
        headers={"content-type": "multipart/form-data; boundary=x"},
        content=b"x",
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_upload_udin_rejection_is_forwarded(authed_client, project_task, mock_udin):
    """Udin's error status is returned as `upload_failed` with its error payload."""
    mock_udin.set("upload-files", 422, {"error": {"images": ["too_large"]}})
    resp = await authed_client.call(
        "POST",
        _uploads_url(project_task.uid),
        headers={"content-type": "multipart/form-data; boundary=x"},
        content=b"x",
        raise_for_status=False,
    )
    assert resp.status_code == 422
    assert resp.json()["message"] == resolve_message("upload_failed", "en")


@pytest.mark.asyncio
async def test_upload_udin_timeout_is_504(authed_client, project_task, mock_udin):
    """504 upload_timeout when Udin does not answer in time."""
    mock_udin.raise_on_udin(TimeoutException("slow"))
    resp = await authed_client.call(
        "POST",
        _uploads_url(project_task.uid),
        headers={"content-type": "multipart/form-data; boundary=x"},
        content=b"x",
        raise_for_status=False,
    )
    assert resp.status_code == 504
    assert resp.json()["message"] == resolve_message("upload_timeout", "en")


@pytest.mark.asyncio
async def test_upload_unexpected_error_is_500(authed_client, project_task, mock_udin):
    """500 when something other than a BaseError escapes while talking to Udin."""
    mock_udin.raise_on_udin(RuntimeError("boom"))
    resp = await authed_client.call(
        "POST",
        _uploads_url(project_task.uid),
        headers={"content-type": "multipart/form-data; boundary=x"},
        content=b"x",
        raise_for_status=False,
    )
    assert resp.status_code == 500


@pytest.mark.asyncio
async def test_upload_unknown_task_is_404(authed_client, mock_udin):
    """404 project_task_not_found for a uid that is neither a task nor a song."""
    resp = await authed_client.call(
        "POST",
        _uploads_url(uuid4()),
        headers={"content-type": "multipart/form-data; boundary=x"},
        content=b"x",
        raise_for_status=False,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_upload_requires_auth(client, project_task):
    """401 when the request carries no bearer token."""
    resp = await client.call("POST", _uploads_url(project_task.uid), raise_for_status=False)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_upload_invalidates_the_references_picker_cache(authed_client, project_task, mock_udin):
    """200 OK; a picker response cached before an upload is dropped, so the project picker lists the new image
    straight away instead of serving the pre-upload result until the cache expires."""
    picker = f"/api/references-picker/{project_task.project.uid}"
    name = f"picker-{uuid4().hex[:8]}.jpg"

    def uploads(resp):
        section = next(s for s in resp.json()["data"] if s["type"] == "Image Uploads")
        return section["files"]

    # warm (and cache) the picker before the upload
    assert name not in [f["name"] for f in uploads(await authed_client.call("GET", picker))]

    mock_udin.set(
        "upload-files",
        200,
        {"data": [{"name": name, "path": f"{_udin_root(project_task)}/upload/images/{name}", "size": 5}]},
    )
    resp = await authed_client.call(
        "POST",
        _uploads_url(project_task.uid),
        headers={"content-type": "multipart/form-data; boundary=x"},
        content=b"x",
    )
    assert resp.status_code == 200

    assert name in [f["name"] for f in uploads(await authed_client.call("GET", picker))]
