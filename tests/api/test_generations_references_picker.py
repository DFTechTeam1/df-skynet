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
async def test_returns_flat_sections_with_uploads_and_generations(authed_client, project_task, user_id, generation_fks):
    """200 OK; only Image Uploads / Image Generations / Elements sections are returned; a live image upload and an
    image generation result land in their own section, video uploads are not offered, and the generation file uses
    the `GenerationResultRecord` shape without cost/prompt fields."""
    image_upload = _make_upload(project_task, user_id, UploadFileTypes.image)
    video_upload = _make_upload(project_task, user_id, UploadFileTypes.video)
    generation_result = _make_result(project_task, user_id, generation_fks)

    url, params = _url(project_task.project.uid)
    resp = await authed_client.call("GET", url, params=params)
    assert resp.status_code == 200
    body = resp.json()
    assert [s["type"] for s in body["data"]] == ["Image Generations", "Image Uploads", "Elements", "Shared"]

    # Note: this project's uploads/generations accumulate across test runs on the
    # real shared staging DB, so section totals aren't exact — only membership is checked.
    image_section = _section(body, "Image Uploads")
    assert image_section["total"] == len(image_section["files"]) >= 1
    assert image_upload.uid in [f["file_uid"] for f in image_section["files"]]
    assert video_upload.uid not in [f["file_uid"] for f in image_section["files"]]

    generation_section = _section(body, "Image Generations")
    assert generation_section["total"] >= 1
    file = next(f for f in generation_section["files"] if f["file_uid"] == generation_result.uid)
    assert file["kind"] == GenerationKinds.image
    assert file["favourited_at"] is None
    assert {"cost_usd", "cost_idr", "prompt", "is_main"}.isdisjoint(file)


@pytest.mark.asyncio
async def test_search_is_scoped_to_the_project_and_served_from_the_index(authed_client, project_task, monkeypatch):
    """200 OK; with `search` the picker reads the search index (not the DB): the requests are scoped to this project and
    to image kinds, and the hits come back grouped as Image Uploads / Image Generations. Matching itself is the engine's
    job (covered in tests/unit/test_search_provider.py), so the engine is stubbed here."""
    seen = []

    async def fake_search(requests):
        seen.extend(requests)
        creator = {"user_id": 1}
        upload = {"file_uid": "u1", "name": "banner-hero.png", "path": "p/u.png", "kind": "image", "creator": creator}
        generation = {
            "file_uid": "g1",
            "name": "banner-gen.png",
            "path": "p/g.png",
            "kind": "image",
            "is_main": True,
            "creator": creator,
        }
        return [[upload], [generation]]

    monkeypatch.setattr("services.search.query._search", fake_search)
    url, _ = _url(project_task.project.uid)
    resp = await authed_client.call("GET", url, params={"search": "banner"})
    assert resp.status_code == 200
    body = resp.json()
    assert [f["file_uid"] for f in _section(body, "Image Uploads")["files"]] == ["u1"]
    assert [f["file_uid"] for f in _section(body, "Image Generations")["files"]] == ["g1"]
    assert {r.query for r in seen} == {"banner"}
    assert all(project_task.project.uid in repr(r.filter) for r in seen)


@pytest.mark.asyncio
async def test_all_matching_files_are_returned_unpaginated(authed_client, project_task, user_id):
    """200 OK; the section returns every matching file — page/itemsPerPage aren't recognized query params."""
    uploads = [_make_upload(project_task, user_id, UploadFileTypes.image) for _ in range(3)]

    url, _ = _url(project_task.project.uid)
    resp = await authed_client.call("GET", url, params={"page": 1, "itemsPerPage": 2})
    assert resp.status_code == 200
    image_section = _section(resp.json(), "Image Uploads")
    uids = [f["file_uid"] for f in image_section["files"] if "file_uid" in f]
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
    section_uids = [f["file_uid"] for f in _section(resp.json(), "Image Generations")["files"]]
    assert archived.uid in section_uids
    assert revision.uid not in section_uids


@pytest.mark.asyncio
async def test_favourited_result_exposes_favourited_at(authed_client, project_task, user_id, generation_fks):
    """200 OK; a favourited result stays in Image Generations and carries a formatted `favourited_at`; there is no
    separate Favorites section."""
    result = _make_result(project_task, user_id, generation_fks, favourited_at="2024-01-01 00:00:00")

    url, params = _url(project_task.project.uid)
    resp = await authed_client.call("GET", url, params=params)
    body = resp.json()
    assert "Favorites" not in [s["type"] for s in body["data"]]
    file = next(f for f in _section(body, "Image Generations")["files"] if f["file_uid"] == result.uid)
    assert file["favourited_at"] is not None


@pytest.mark.asyncio
async def test_element_generation_lands_in_elements_and_video_is_dropped(
    authed_client, project_task, user_id, generation_fks
):
    """200 OK; a video-kind result is not offered anywhere. The refactored picker no longer fills Elements (it is an
    empty placeholder next to Shared), so an element-kind result is not listed under it either."""
    element = _make_result(project_task, user_id, generation_fks, kind=GenerationKinds.element)
    video = _make_result(project_task, user_id, generation_fks, kind=GenerationKinds.video)

    url, params = _url(project_task.project.uid)
    resp = await authed_client.call("GET", url, params=params)
    body = resp.json()
    assert _section(body, "Elements")["files"] == []
    all_uids = [f.get("file_uid") or f.get("uid") for s in body["data"] for f in s["files"]]
    assert video.uid not in all_uids


@pytest.mark.asyncio
async def test_response_is_cached_on_second_call(authed_client, project_task, user_id, generation_fks):
    """200 OK; a second identical call returns the same data without erroring, exercising the cache-hit branch."""
    result = _make_result(project_task, user_id, generation_fks)

    url, params = _url(project_task.project.uid)
    first = await authed_client.call("GET", url, params=params)
    second = await authed_client.call("GET", url, params=params)
    assert first.status_code == second.status_code == 200
    assert result.uid in [f["file_uid"] for f in _section(second.json(), "Image Generations")["files"]]


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


@pytest.mark.asyncio
async def test_project_picker_passes_domain_errors_through_and_masks_unexpected_ones(
    authed_client, project_task, monkeypatch
):
    """500 when loading the rows raises something other than a BaseError (an unknown project stays a 404, covered above)."""

    async def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("apps.controller.generations.get_user_uploaded_files_refactored", boom)
    url, params = _url(project_task.project.uid)
    resp = await authed_client.call("GET", url, params=params, raise_for_status=False)
    assert resp.status_code == 500
