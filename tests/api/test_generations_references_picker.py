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

URL = "/api/references-picker"


def _url(task_uid, **params):
    return f"{URL}/{task_uid}", params


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


def _make_upload(project_task, user_id, kind=UploadFileTypes.image):
    return DfEngineUploadFilesFactory.create(
        type=kind,
        project_id=project_task.project_id,
        task_id=project_task.id,
        created_by=int(user_id),
    )


def _make_result(project_task, user_id, generation_fks, **overrides):
    generation = DfEngineGenerationsFactory.create(
        project_id=project_task.project_id,
        task_id=project_task.id,
        created_by=int(user_id),
        sourceable_id=1,
        **generation_fks,
    )
    return DfEngineGenerationResultsFactory.create(generation_id=generation.id, created_by=int(user_id), **overrides)


@pytest.mark.asyncio
async def test_returns_uploads_and_generations_in_their_sections(authed_client, project_task, user_id, generation_fks):
    """200 OK; a live image upload, video upload and image generation result each land in their own section with correct counts and fields."""
    image_upload = _make_upload(project_task, user_id, UploadFileTypes.image)
    video_upload = _make_upload(project_task, user_id, UploadFileTypes.video)
    generation_result = _make_result(project_task, user_id, generation_fks)

    url, params = _url(project_task.uid)
    resp = await authed_client.call("GET", url, params=params)
    assert resp.status_code == 200
    body = resp.json()

    image_section = _section(body, "Image Upload")
    assert image_section["total_data"] == len(image_section["files"])
    assert image_upload.uid in [f["uid"] for f in image_section["files"]]

    video_section = _section(body, "Video Upload")
    assert video_section["total_data"] == len(video_section["files"])
    assert video_upload.uid in [f["uid"] for f in video_section["files"]]

    generation_section = _section(body, "Image Generation")
    assert generation_section["total_data"] == len(generation_section["files"])
    assert generation_result.uid in [f["uid"] for f in generation_section["files"]]


@pytest.mark.asyncio
async def test_query_flag_false_returns_empty_section(authed_client, project_task, user_id):
    """200 OK; a section's query flag set to false comes back empty even though a matching row exists."""
    _make_upload(project_task, user_id, UploadFileTypes.image)

    url, _ = _url(project_task.uid)
    resp = await authed_client.call("GET", url, params={"image_uploads": False})
    assert resp.status_code == 200
    assert _section(resp.json(), "Image Upload")["files"] == []


@pytest.mark.asyncio
async def test_archived_or_non_main_results_excluded(authed_client, project_task, user_id, generation_fks):
    """200 OK; an archived result and a non-main (revision) result are excluded from the Image Generation section."""
    archived = _make_result(project_task, user_id, generation_fks, archieved_at="2024-01-01 00:00:00")
    revision_parent = _make_result(project_task, user_id, generation_fks, is_main=True)
    revision = _make_result(project_task, user_id, generation_fks, is_main=False, parent_id=revision_parent.id)

    url, params = _url(project_task.uid)
    resp = await authed_client.call("GET", url, params=params)
    section_uids = [f["uid"] for f in _section(resp.json(), "Image Generation")["files"]]
    assert archived.uid not in section_uids
    assert revision.uid not in section_uids


@pytest.mark.asyncio
async def test_favourite_result_appears_in_favorites_section(authed_client, project_task, user_id, generation_fks):
    """200 OK; a live, favourited result appears in both its own kind section and Favorites."""
    result = _make_result(project_task, user_id, generation_fks, is_favourite=True)

    url, params = _url(project_task.uid)
    resp = await authed_client.call("GET", url, params=params)
    body = resp.json()
    assert result.uid in [f["uid"] for f in _section(body, "Image Generation")["files"]]
    assert result.uid in [f["uid"] for f in _section(body, "Favorites")["files"]]


@pytest.mark.asyncio
async def test_unknown_task_is_404(authed_client):
    """404 project_task_not_found for a task uid that matches no row."""
    url, params = _url(uuid4())
    resp = await authed_client.call("GET", url, params=params, raise_for_status=False)
    assert resp.status_code == 404
    assert resp.json()["message"] == resolve_message("project_task_not_found", "en")


@pytest.mark.asyncio
async def test_requires_auth(client, project_task):
    """401 when the request carries no bearer token."""
    url, params = _url(project_task.uid)
    resp = await client.call("GET", url, params=params, raise_for_status=False)
    assert resp.status_code == 401
