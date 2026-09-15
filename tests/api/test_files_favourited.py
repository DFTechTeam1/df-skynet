import pytest
import pytest_asyncio
from services.mysql.factory.df_engine_generations import DfEngineGenerationsFactory
from services.mysql.factory.df_engine_generation_results import DfEngineGenerationResultsFactory
from services.mysql.factory.df_engine_model_options import DfEngineModelOptionsFactory
from services.mysql.factory.df_engine_menus import DfEngineMenusFactory
from services.mysql.factory.df_engine_features import DfEngineFeaturesFactory


def _url(task_uid, suffix=""):
    return f"/api/files/{task_uid}/favourited{suffix}"


@pytest_asyncio.fixture
async def generation_fks(user_id) -> dict:
    """Self-contained model_option/menu/feature ids for df_engine_generations' NOT NULL FKs —
    created via factories rather than assumed to pre-exist, so this works on a fresh, empty DB too."""
    model_option = DfEngineModelOptionsFactory.create()
    menu = DfEngineMenusFactory.create(created_by=int(user_id), df_engine_menu_feature_mapping=None)
    feature = DfEngineFeaturesFactory.create(created_by=int(user_id), df_engine_feature_prompt_mapping=None)
    return {"model_id": model_option.id, "menu_id": menu.id, "feature_id": feature.id}


def _make_result(project_task, user_id, generation_fks, name="a.png", kind="images", is_favourite=False):
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
        path=path, generation_id=generation.id, created_by=int(user_id), is_favourite=is_favourite
    )


def _find_flat(files, uid):
    return next((f for f in files if f["uid"] == uid), None)


@pytest.mark.asyncio
async def test_get_favourited_files_only_returns_favourited_generations(
    authed_client, project_task, user_id, generation_fks
):
    """200 OK; flat list of only this user's favourited generation results."""
    favourited = _make_result(project_task, user_id, generation_fks, name="fav.png", is_favourite=True)
    not_favourited = _make_result(project_task, user_id, generation_fks, name="not_fav.png", is_favourite=False)

    resp = await authed_client.call("GET", _url(project_task.uid))
    assert resp.status_code == 200
    assert isinstance(resp.json()["data"], list)
    assert _find_flat(resp.json()["data"], favourited.uid) is not None
    assert _find_flat(resp.json()["data"], not_favourited.uid) is None


@pytest.mark.asyncio
async def test_favourited_action_flags(authed_client, project_task, user_id, generation_fks):
    """200 OK; a favourited (but not archived) generation result allows unfavorite, and
    archiving/moving are independent locks unaffected by the favourite state."""
    result = _make_result(project_task, user_id, generation_fks, name="fav_flags.png", is_favourite=True)

    resp = await authed_client.call("GET", _url(project_task.uid))
    file = _find_flat(resp.json()["data"], result.uid)
    assert file["actions"]["can_favorited"] is False
    assert file["actions"]["can_unfavorited"] is True
    assert file["actions"]["can_archieve"] is True
    assert file["actions"]["can_choose_to_move"] is True


@pytest.mark.asyncio
async def test_favourited_entry_matches_file_entry_shape_with_no_variants(
    authed_client, project_task, user_id, generation_fks
):
    """200 OK; favourited entries carry the same fields as `GET /files/{task_uid}` file entries
    (is_main/kind/prompt/cost/full actions) and never a `variants` key - they're always leaves."""
    result = _make_result(project_task, user_id, generation_fks, name="shape.png", is_favourite=True)

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
async def test_get_favourited_files_filters_by_type(authed_client, project_task, user_id, generation_fks):
    """200 OK; `type=image`/`type=video` restrict the list, omitted returns both."""
    image = _make_result(project_task, user_id, generation_fks, name="a.png", kind="images", is_favourite=True)
    video = _make_result(project_task, user_id, generation_fks, name="a.mp4", kind="videos", is_favourite=True)

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
