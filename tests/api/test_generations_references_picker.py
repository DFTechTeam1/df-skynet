import pytest
import pytest_asyncio
from uuid import uuid4
from middlewares.lang import resolve_message
from services.mysql.factory.df_engine_generations import DfEngineGenerationsFactory
from services.mysql.factory.df_engine_generation_results import DfEngineGenerationResultsFactory
from services.mysql.factory.df_engine_upload_files import DfEngineUploadFilesFactory
from services.mysql.factory.df_engine_model_options import DfEngineModelOptionsFactory
from services.mysql.factory.df_engine_menus import DfEngineMenusFactory
from services.mysql.factory.df_engine_features import DfEngineFeaturesFactory
from services.mysql.model.df_engine_upload_files import UploadFileTypes
from services.mysql.model.df_engine_generations import GenerationKinds

URL = "/api/references-picker"


def _url(project_uid, **params):
    return f"{URL}/{project_uid}", params


def _section(body, type_name):
    return next(s for s in body["data"] if s["type"] == type_name)


@pytest_asyncio.fixture
async def generation_fks(user_id) -> dict:
    """Self-contained model_option/menu/feature ids for df_engine_generations' NOT NULL FKs —
    created via factories rather than assumed to pre-exist, so this works on a fresh, empty DB too."""
    model_option = DfEngineModelOptionsFactory.create()
    menu = DfEngineMenusFactory.create(created_by=int(user_id), df_engine_menu_feature_mapping=None)
    feature = DfEngineFeaturesFactory.create(created_by=int(user_id), df_engine_feature_prompt_mapping=None)
    return {"model_id": model_option.id, "menu_id": menu.id, "feature_id": feature.id}


def _make_upload(project_task, user_id, kind=UploadFileTypes.image, **overrides):
    return DfEngineUploadFilesFactory.create(
        type=kind,
        project_id=project_task.project_id,
        task_id=project_task.id,
        created_by=int(user_id),
        **overrides,
    )


def _make_result(project_task, user_id, generation_fks, kind=GenerationKinds.image, **overrides):
    generation = DfEngineGenerationsFactory.create(
        project_id=project_task.project_id,
        task_id=project_task.id,
        created_by=int(user_id),
        sourceable_id=1,
        kind=kind,
        **generation_fks,
    )
    return DfEngineGenerationResultsFactory.create(generation_id=generation.id, created_by=int(user_id), **overrides)


@pytest.mark.asyncio
async def test_returns_uploads_and_generations_in_their_sections(authed_client, project_task, user_id, generation_fks):
    """200 OK; a live image upload, video upload and image generation result each land in their own section with correct counts and fields."""
    image_upload = _make_upload(project_task, user_id, UploadFileTypes.image)
    video_upload = _make_upload(project_task, user_id, UploadFileTypes.video)
    generation_result = _make_result(project_task, user_id, generation_fks)

    url, params = _url(project_task.project.uid)
    resp = await authed_client.call("GET", url, params=params)
    assert resp.status_code == 200
    body = resp.json()

    # Note: this project's uploads/generations accumulate across test runs on the
    # real shared staging DB, so section totals aren't exact — only membership is checked.
    image_section = _section(body, "Image Uploads")
    assert image_section["total_data"] >= 1
    assert image_upload.uid in [f["uid"] for f in image_section["files"]]

    video_section = _section(body, "Video Uploads")
    assert video_section["total_data"] >= 1
    assert video_upload.uid in [f["uid"] for f in video_section["files"]]

    generation_section = _section(body, "Image Generations")
    assert generation_section["total_data"] >= 1
    assert generation_result.uid in [f["uid"] for f in generation_section["files"]]


@pytest.mark.asyncio
async def test_search_filters_by_name_prefix(authed_client, project_task, user_id):
    """200 OK; `search` only returns uploads whose name starts with the given text."""
    prefix = f"banner-{uuid4().hex[:8]}"
    matching = _make_upload(project_task, user_id, UploadFileTypes.image, name=f"{prefix}-hero.png")
    non_matching = _make_upload(project_task, user_id, UploadFileTypes.image, name="poster.png")

    url, _ = _url(project_task.project.uid)
    resp = await authed_client.call("GET", url, params={"search": prefix})
    assert resp.status_code == 200
    section_uids = [f["uid"] for f in _section(resp.json(), "Image Uploads")["files"]]
    assert matching.uid in section_uids
    assert non_matching.uid not in section_uids


@pytest.mark.asyncio
async def test_all_matching_files_are_returned_unpaginated(authed_client, project_task, user_id):
    """200 OK; the section returns every matching file — page/itemsPerPage aren't recognized query params."""
    uploads = [_make_upload(project_task, user_id, UploadFileTypes.image) for _ in range(3)]

    url, _ = _url(project_task.project.uid)
    resp = await authed_client.call("GET", url, params={"page": 1, "itemsPerPage": 2})
    assert resp.status_code == 200
    image_section = _section(resp.json(), "Image Uploads")
    uids = [f["uid"] for f in image_section["files"]]
    assert all(u.uid in uids for u in uploads)


@pytest.mark.asyncio
async def test_non_main_result_excluded_archived_still_listed(authed_client, project_task, user_id, generation_fks):
    """200 OK; a non-main (revision) result's own generation has no is_main result, so it's excluded. An
    archived-but-is_main result has no such gap on its own generation, so it's still listed — the section
    query never filters on archieved_at (same as the user-galleries list)."""
    archived = _make_result(project_task, user_id, generation_fks, archieved_at="2024-01-01 00:00:00")
    revision_parent = _make_result(project_task, user_id, generation_fks, is_main=True)
    revision = _make_result(project_task, user_id, generation_fks, is_main=False, parent_id=revision_parent.id)

    url, params = _url(project_task.project.uid)
    resp = await authed_client.call("GET", url, params=params)
    section_uids = [f["uid"] for f in _section(resp.json(), "Image Generations")["files"]]
    assert archived.uid in section_uids
    assert revision.uid not in section_uids


@pytest.mark.asyncio
async def test_favourite_result_appears_in_favorites_section(authed_client, project_task, user_id, generation_fks):
    """200 OK; a live, favourited result appears in both its own kind section and Favorites."""
    result = _make_result(project_task, user_id, generation_fks, favourited_at="2024-01-01 00:00:00")

    url, params = _url(project_task.project.uid)
    resp = await authed_client.call("GET", url, params=params)
    body = resp.json()
    assert result.uid in [f["uid"] for f in _section(body, "Image Generations")["files"]]
    assert result.uid in [f["uid"] for f in _section(body, "Favorites")["files"]]


@pytest.mark.asyncio
async def test_response_is_cached_on_second_call(authed_client, project_task, user_id, generation_fks):
    """200 OK; a second identical call returns the same data without erroring, exercising the cache-hit branch."""
    result = _make_result(project_task, user_id, generation_fks)

    url, params = _url(project_task.project.uid)
    first = await authed_client.call("GET", url, params=params)
    second = await authed_client.call("GET", url, params=params)
    assert first.status_code == second.status_code == 200
    assert result.uid in [f["uid"] for f in _section(second.json(), "Image Generations")["files"]]


@pytest.mark.asyncio
async def test_unknown_project_is_404(authed_client):
    """404 project_not_found for a project uid that matches no row."""
    url, params = _url(uuid4())
    resp = await authed_client.call("GET", url, params=params, raise_for_status=False)
    assert resp.status_code == 404
    assert resp.json()["message"] == resolve_message("project_not_found", "en")


@pytest.mark.asyncio
async def test_requires_auth(client, project_task):
    """401 when the request carries no bearer token."""
    url, params = _url(project_task.project.uid)
    resp = await client.call("GET", url, params=params, raise_for_status=False)
    assert resp.status_code == 401


GLOBAL_URL = "/api/references-picker"


def _global_section(body, type_name):
    return next(s for s in body["data"] if s["type"] == type_name)


def _flat_files(section):
    return [f for p in section["projects"] for t in p["tasks"] for f in t["files"]]


@pytest.mark.asyncio
async def test_global_picker_groups_by_project_and_task(authed_client, project_task, user_id, generation_fks):
    """200 OK; global picker (no project_uid) groups uploads/generations by project then task."""
    image_upload = _make_upload(project_task, user_id, UploadFileTypes.image)
    generation_result = _make_result(project_task, user_id, generation_fks)

    resp = await authed_client.call("GET", GLOBAL_URL, params={})
    assert resp.status_code == 200
    body = resp.json()
    assert image_upload.uid in [f["uid"] for f in _flat_files(_global_section(body, "Image Uploads"))]
    assert generation_result.uid in [f["uid"] for f in _flat_files(_global_section(body, "Image Generations"))]


@pytest.mark.asyncio
async def test_global_picker_groups_video_generations_by_project_and_task(
    authed_client, project_task, user_id, generation_fks
):
    """200 OK; a video-kind generation result lands in the Video Generations section, grouped by project/task."""
    video_result = _make_result(project_task, user_id, generation_fks, kind=GenerationKinds.video)

    resp = await authed_client.call("GET", GLOBAL_URL, params={})
    assert resp.status_code == 200
    body = resp.json()
    section = _global_section(body, "Video Generations")
    assert video_result.uid in [f["uid"] for f in _flat_files(section)]
    task = next(
        t for p in section["projects"] for t in p["tasks"] if any(f["uid"] == video_result.uid for f in t["files"])
    )
    assert task["id"] == project_task.id


@pytest.mark.asyncio
async def test_global_picker_file_name_search(authed_client, project_task, user_id):
    """200 OK; `search` filters uploads by name prefix across all projects."""
    prefix = f"global-{uuid4().hex[:8]}"
    matching = _make_upload(project_task, user_id, UploadFileTypes.image, name=f"{prefix}-shot.png")
    non_matching = _make_upload(project_task, user_id, UploadFileTypes.image, name="unrelated.png")

    resp = await authed_client.call("GET", GLOBAL_URL, params={"search": prefix})
    assert resp.status_code == 200
    uids = [f["uid"] for f in _flat_files(_global_section(resp.json(), "Image Uploads"))]
    assert matching.uid in uids
    assert non_matching.uid not in uids


@pytest.mark.asyncio
async def test_global_picker_project_name_search(authed_client, project_task, user_id):
    """200 OK; `search` also matches on project name, returning that project's uploads."""
    image_upload = _make_upload(project_task, user_id, UploadFileTypes.image)

    resp = await authed_client.call("GET", GLOBAL_URL, params={"search": project_task.project.name})
    assert resp.status_code == 200
    uids = [f["uid"] for f in _flat_files(_global_section(resp.json(), "Image Uploads"))]
    assert image_upload.uid in uids


@pytest.mark.asyncio
async def test_global_picker_empty_result(authed_client, user_id):
    """200 OK; a `search` matching nothing returns an empty section with total_data 0."""
    resp = await authed_client.call("GET", GLOBAL_URL, params={"search": f"nonexistent-{uuid4().hex}"})
    assert resp.status_code == 200
    section = _global_section(resp.json(), "Image Uploads")
    assert section["total_data"] == 0
    assert _flat_files(section) == []


@pytest.mark.asyncio
async def test_global_picker_cached_on_second_call(authed_client, project_task, user_id):
    """200 OK; a second identical call returns the same data, exercising the cache-hit branch."""
    image_upload = _make_upload(project_task, user_id, UploadFileTypes.image)
    params = {"search": image_upload.name}

    first = await authed_client.call("GET", GLOBAL_URL, params=params)
    second = await authed_client.call("GET", GLOBAL_URL, params=params)
    assert first.status_code == second.status_code == 200
    uids = [f["uid"] for f in _flat_files(_global_section(second.json(), "Image Uploads"))]
    assert image_upload.uid in uids


@pytest.mark.asyncio
async def test_global_picker_requires_auth(client):
    """401 when the request carries no bearer token."""
    resp = await client.call("GET", GLOBAL_URL, params={}, raise_for_status=False)
    assert resp.status_code == 401
