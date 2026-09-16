from datetime import datetime
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


@pytest_asyncio.fixture
async def generation_fks(user_id) -> dict:
    """Self-contained model_option/menu/feature ids for df_engine_generations' NOT NULL FKs —
    created via factories rather than assumed to pre-exist, so this works on a fresh, empty DB too."""
    model_option = DfEngineModelOptionsFactory.create()
    menu = DfEngineMenusFactory.create(created_by=int(user_id), df_engine_menu_feature_mapping=None)
    feature = DfEngineFeaturesFactory.create(created_by=int(user_id), df_engine_feature_prompt_mapping=None)
    return {"model_id": model_option.id, "menu_id": menu.id, "feature_id": feature.id}


def _make_result(
    project_task,
    user_id,
    generation_fks,
    archieved_at=None,
    name="a.png",
    kind="images",
    parent_id=None,
    is_main=True,
):
    """A `DfEngineGenerationResults` row (with its parent `DfEngineGenerations`) shaped
    so `FilesService.base_of`/`type_root_of` recognize it, mirroring the upload-file helper."""
    generation = DfEngineGenerationsFactory.create(
        project_id=project_task.project_id,
        task_id=project_task.id,
        created_by=int(user_id),
        sourceable_id=1,
        **generation_fks,
    )
    path = f"storage/DF-Engine/{project_task.project.uid}/generated/{kind}/{name}"
    return DfEngineGenerationResultsFactory.create(
        path=path,
        generation_id=generation.id,
        created_by=int(user_id),
        archieved_at=archieved_at,
        parent_id=parent_id,
        is_main=is_main,
    )


@pytest.mark.asyncio
async def test_get_file_detail_success(authed_client, project_task, user_id):
    """200 OK; fetches one file entry by its uid."""
    row = _make_file(project_task, user_id)
    resp = await authed_client.call("GET", _url(project_task.uid, f"/file/{row.uid}"))
    assert resp.status_code == 200
    assert resp.json()["data"]["uid"] == row.uid
    assert resp.json()["data"]["source"] == "upload"


@pytest.mark.asyncio
async def test_get_file_detail_unknown_uid_is_404(authed_client, project_task):
    """404 file_not_found for a file uid absent from the tree."""
    resp = await authed_client.call("GET", _url(project_task.uid, f"/file/{uuid4()}"), raise_for_status=False)
    assert resp.status_code == 404
    assert resp.json()["message"] == resolve_message("file_not_found", "en")


@pytest.mark.asyncio
async def test_get_generated_file_detail_works_regardless_of_archived_state(
    authed_client, project_task, user_id, generation_fks
):
    """200 OK; `type=generated` finds a generation result by uid whether it's archived or live."""
    live = _make_result(project_task, user_id, generation_fks, name="live_detail.png")
    archived = _make_result(
        project_task, user_id, generation_fks, archieved_at=datetime.now(), name="archived_detail.png"
    )

    for result in (live, archived):
        resp = await authed_client.call(
            "GET", _url(project_task.uid, f"/file/{result.uid}"), params={"type": "generated"}
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["uid"] == result.uid
        assert resp.json()["data"]["source"] == "generated"


@pytest.mark.asyncio
async def test_get_file_detail_type_upload_does_not_match_a_generated_result(
    authed_client, project_task, user_id, generation_fks
):
    """404 file_not_found; `type=upload` (default) only matches `df_engine_upload_files` rows,
    so a generation result's uid must not silently resolve through it."""
    result = _make_result(project_task, user_id, generation_fks, name="live_only.png")
    resp = await authed_client.call("GET", _url(project_task.uid, f"/file/{result.uid}"), raise_for_status=False)
    assert resp.status_code == 404
    assert resp.json()["message"] == resolve_message("file_not_found", "en")


@pytest.mark.asyncio
async def test_get_generated_file_detail_unknown_uid_is_404(authed_client, project_task):
    """404 file_not_found; uid matches no generation result at all."""
    resp = await authed_client.call(
        "GET", _url(project_task.uid, f"/file/{uuid4()}"), params={"type": "generated"}, raise_for_status=False
    )
    assert resp.status_code == 404
    assert resp.json()["message"] == resolve_message("file_not_found", "en")


@pytest.mark.asyncio
async def test_get_generated_file_detail_is_main_result_includes_variants(
    authed_client, project_task, user_id, generation_fks
):
    """200 OK; fetching the family member that is currently `is_main` attaches `variants` -
    every other family member (root + children), regardless of position."""
    root = _make_result(project_task, user_id, generation_fks, name="root.png", is_main=False)
    main = _make_result(project_task, user_id, generation_fks, parent_id=root.id, is_main=True, name="main.png")
    other = _make_result(project_task, user_id, generation_fks, parent_id=root.id, is_main=False, name="other.png")

    resp = await authed_client.call("GET", _url(project_task.uid, f"/file/{main.uid}"), params={"type": "generated"})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["uid"] == main.uid
    assert data["is_main"] is True
    assert {v["uid"] for v in data["variants"]} == {root.uid, other.uid}


@pytest.mark.asyncio
async def test_get_generated_file_detail_non_main_result_has_no_variants_key(
    authed_client, project_task, user_id, generation_fks
):
    """200 OK; fetching a family member that is not `is_main` returns only its own data -
    no `variants` key at all, regardless of whether it's the root or a child."""
    root = _make_result(project_task, user_id, generation_fks, name="root.png", is_main=False)
    _make_result(project_task, user_id, generation_fks, parent_id=root.id, is_main=True, name="main.png")

    resp = await authed_client.call("GET", _url(project_task.uid, f"/file/{root.uid}"), params={"type": "generated"})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["uid"] == root.uid
    assert data["is_main"] is False
    assert "variants" not in data


@pytest.mark.asyncio
async def test_get_generated_file_detail_standalone_result_has_empty_variants(
    authed_client, project_task, user_id, generation_fks
):
    """200 OK; a standalone result (no parent, no children, is_main defaults True) gets
    `"variants": []` - it's its own whole family."""
    standalone = _make_result(project_task, user_id, generation_fks, name="standalone.png")

    resp = await authed_client.call(
        "GET", _url(project_task.uid, f"/file/{standalone.uid}"), params={"type": "generated"}
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["variants"] == []
