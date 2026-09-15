from datetime import datetime
import pytest
import pytest_asyncio
from services.mysql.factory.df_engine_generations import DfEngineGenerationsFactory
from services.mysql.factory.df_engine_generation_results import DfEngineGenerationResultsFactory
from services.mysql.factory.df_engine_model_options import DfEngineModelOptionsFactory
from services.mysql.factory.df_engine_menus import DfEngineMenusFactory
from services.mysql.factory.df_engine_features import DfEngineFeaturesFactory


def _url(task_uid, suffix=""):
    return f"/api/files/{task_uid}/archieved{suffix}"


@pytest_asyncio.fixture
async def generation_fks(user_id) -> dict:
    """Self-contained model_option/menu/feature ids for df_engine_generations' NOT NULL FKs —
    created via factories rather than assumed to pre-exist, so this works on a fresh, empty DB too."""
    model_option = DfEngineModelOptionsFactory.create()
    menu = DfEngineMenusFactory.create(created_by=int(user_id), df_engine_menu_feature_mapping=None)
    feature = DfEngineFeaturesFactory.create(created_by=int(user_id), df_engine_feature_prompt_mapping=None)
    return {"model_id": model_option.id, "menu_id": menu.id, "feature_id": feature.id}


def _make_result(
    project_task, user_id, generation_fks, archieved_at=None, name="a.png", kind="images", is_favourite=False
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
        is_favourite=is_favourite,
    )


def _find_flat(files, uid):
    return next((f for f in files if f["uid"] == uid), None)


@pytest.mark.asyncio
async def test_get_archived_files_only_returns_archived_generations(
    authed_client, project_task, user_id, generation_fks
):
    """200 OK; flat list of only archived generation results, never live ones."""
    archived = _make_result(project_task, user_id, generation_fks, archieved_at=datetime.now(), name="archived.png")
    live = _make_result(project_task, user_id, generation_fks, archieved_at=None, name="live.png")

    resp = await authed_client.call("GET", _url(project_task.uid))
    assert resp.status_code == 200
    assert isinstance(resp.json()["data"], list)
    assert _find_flat(resp.json()["data"], archived.uid) is not None
    assert _find_flat(resp.json()["data"], live.uid) is None


@pytest.mark.asyncio
async def test_archived_action_flags(authed_client, project_task, user_id, generation_fks):
    """200 OK; an archived generation result allows unarchieve and moving/favoriting are independent locks."""
    result = _make_result(project_task, user_id, generation_fks, archieved_at=datetime.now(), name="archived_flags.png")

    resp = await authed_client.call("GET", _url(project_task.uid))
    file = _find_flat(resp.json()["data"], result.uid)
    assert file["actions"]["can_archieve"] is False
    assert file["actions"]["can_unarchieve"] is True
    assert file["actions"]["can_favorited"] is True
    assert file["actions"]["can_unfavorited"] is False
    assert file["actions"]["can_choose_to_move"] is False


@pytest.mark.asyncio
async def test_archived_entry_matches_file_entry_shape_with_no_variants(
    authed_client, project_task, user_id, generation_fks
):
    """200 OK; archived entries carry the same fields as `GET /files/{task_uid}` file entries
    (is_main/kind/prompt/cost/full actions) and never a `variants` key - they're always leaves."""
    result = _make_result(project_task, user_id, generation_fks, archieved_at=datetime.now(), name="shape.png")

    resp = await authed_client.call("GET", _url(project_task.uid))
    file = _find_flat(resp.json()["data"], result.uid)
    assert file.keys() == {
        "uid",
        "name",
        "type",
        "path",
        "size",
        "md5",
        "creator",
        "updater",
        "is_main",
        "kind",
        "prompt",
        "cost",
        "actions",
    }
    assert "variants" not in file


@pytest.mark.asyncio
async def test_get_archived_files_filters_by_type(authed_client, project_task, user_id, generation_fks):
    """200 OK; `type=image`/`type=video` restrict the list, omitted returns both."""
    image = _make_result(
        project_task, user_id, generation_fks, archieved_at=datetime.now(), name="a.png", kind="images"
    )
    video = _make_result(
        project_task, user_id, generation_fks, archieved_at=datetime.now(), name="a.mp4", kind="videos"
    )

    resp = await authed_client.call("GET", _url(project_task.uid))
    data = resp.json()["data"]
    assert _find_flat(data, image.uid) is not None
    assert _find_flat(data, video.uid) is not None

    resp = await authed_client.call("GET", _url(project_task.uid, "?type=image"))
    data = resp.json()["data"]
    assert _find_flat(data, image.uid) is not None
    assert _find_flat(data, video.uid) is None

    resp = await authed_client.call("GET", _url(project_task.uid, "?type=video"))
    data = resp.json()["data"]
    assert _find_flat(data, image.uid) is None
    assert _find_flat(data, video.uid) is not None
