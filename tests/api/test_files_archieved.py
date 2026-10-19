from datetime import datetime
import pytest
import pytest_asyncio
from services.mysql.factory.df_engine_generations import DfEngineGenerationsFactory
from services.mysql.factory.df_engine_generation_results import DfEngineGenerationResultsFactory
from services.mysql.factory.df_engine_model_options import DfEngineModelOptionsFactory
from services.mysql.factory.df_engine_menus import DfEngineMenusFactory
from services.mysql.factory.df_engine_features import DfEngineFeaturesFactory

URL = "/api/files/archieves"


@pytest_asyncio.fixture
async def generation_fks(user_id) -> dict:
    """Self-contained model_option/menu/feature ids for df_engine_generations' NOT NULL FKs."""
    model_option = DfEngineModelOptionsFactory.create()
    menu = DfEngineMenusFactory.create(created_by=int(user_id), df_engine_menu_feature_mapping=None)
    feature = DfEngineFeaturesFactory.create(created_by=int(user_id), df_engine_feature_prompt_mapping=None)
    return {"model_id": model_option.id, "menu_id": menu.id, "feature_id": feature.id}


def _make_generation(project_task, owner_id, generation_fks, **overrides):
    return DfEngineGenerationsFactory.create(
        project_id=project_task.project_id,
        task_id=project_task.id,
        created_by=int(owner_id),
        sourceable_id=1,
        **generation_fks,
        **overrides,
    )


def _make_result(generation, owner_id, **overrides):
    return DfEngineGenerationResultsFactory.create(generation_id=generation.id, created_by=int(owner_id), **overrides)


def _find_flat(files, uid):
    return next((f for f in files if f["file_uid"] == str(uid)), None)


@pytest.mark.asyncio
async def test_only_my_archived_files_are_returned(authed_client, project_task, user_id, other_user_id, generation_fks):
    """200 OK; only my archived files are listed: not live ones, not another user's archived ones."""
    archived = _make_result(
        _make_generation(project_task, user_id, generation_fks), user_id, archieved_at=datetime.now()
    )
    live = _make_result(_make_generation(project_task, user_id, generation_fks), user_id, archieved_at=None)
    theirs = _make_result(
        _make_generation(project_task, other_user_id, generation_fks), other_user_id, archieved_at=datetime.now()
    )

    resp = await authed_client.call("GET", URL)
    assert resp.status_code == 200
    files = resp.json()["data"]
    assert _find_flat(files, archived.uid) is not None
    assert _find_flat(files, live.uid) is None
    assert _find_flat(files, theirs.uid) is None


@pytest.mark.asyncio
async def test_other_users_archived_result_on_my_generation_is_excluded(
    authed_client, project_task, user_id, other_user_id, generation_fks
):
    """200 OK; ownership is the result's creator, so someone else's archived result under my generation is not mine."""
    result = _make_result(
        _make_generation(project_task, user_id, generation_fks), other_user_id, archieved_at=datetime.now()
    )
    resp = await authed_client.call("GET", URL)
    assert _find_flat(resp.json()["data"], result.uid) is None


@pytest.mark.asyncio
async def test_archived_files_are_sorted_newest_archive_first(authed_client, project_task, user_id, generation_fks):
    """200 OK; the newest archive comes first."""
    old = _make_result(
        _make_generation(project_task, user_id, generation_fks), user_id, archieved_at=datetime(2024, 1, 1)
    )
    new = _make_result(
        _make_generation(project_task, user_id, generation_fks), user_id, archieved_at=datetime(2024, 6, 1)
    )
    uids = [f["file_uid"] for f in (await authed_client.call("GET", URL)).json()["data"]]
    assert uids.index(str(new.uid)) < uids.index(str(old.uid))


@pytest.mark.asyncio
async def test_archived_scope_filters_narrow_the_list(authed_client, project_task, user_id, generation_fks):
    """200 OK; project_id / task_id narrow the list, song_id matches nothing here, and they combine with AND."""
    result = _make_result(_make_generation(project_task, user_id, generation_fks), user_id, archieved_at=datetime.now())

    for params in (
        {},
        {"project_id": project_task.project_id},
        {"task_id": project_task.id},
        {"project_id": project_task.project_id, "task_id": project_task.id},
    ):
        files = (await authed_client.call("GET", URL, params=params)).json()["data"]
        assert _find_flat(files, result.uid) is not None, params
    for params in (
        {"project_id": -1},
        {"task_id": -1},
        {"song_id": -1},
        {"project_id": project_task.project_id, "task_id": -1},
    ):
        files = (await authed_client.call("GET", URL, params=params)).json()["data"]
        assert _find_flat(files, result.uid) is None, params


@pytest.mark.asyncio
async def test_archived_list_empty_scope_and_cache_hit(authed_client, project_task, user_id, generation_fks):
    """200 OK; an empty scope returns [], and an immediate second call is served from cache with the same body."""
    _make_result(_make_generation(project_task, user_id, generation_fks), user_id, archieved_at=datetime.now())
    first = await authed_client.call("GET", URL, params={"task_id": -1})
    assert first.json()["data"] == []
    second = await authed_client.call("GET", URL, params={"task_id": -1})
    assert second.json()["data"] == []

    warm = (await authed_client.call("GET", URL)).json()["data"]
    cached = (await authed_client.call("GET", URL)).json()["data"]
    assert warm == cached


@pytest.mark.asyncio
async def test_archived_action_flags_and_shape(authed_client, project_task, user_id, generation_fks):
    """200 OK; an archived result has can_set_archieve false, favoriting is independent, and the entry is a
    `GenerationResultRecord` without the generation-context fields."""
    result = _make_result(_make_generation(project_task, user_id, generation_fks), user_id, archieved_at=datetime.now())

    file = _find_flat((await authed_client.call("GET", URL)).json()["data"], result.uid)
    assert file["action"]["can_set_archieve"] is False
    assert "can_archieve" not in file["action"] and "can_unarchieve" not in file["action"]
    assert file["action"]["can_set_favorite"] is True
    assert file.keys() == {
        "id",
        "flag_created_at",
        "flag_favourited_at",
        "flag_archieved_at",
        "kind",
        "file_uid",
        "generation_uid",
        "name",
        "type",
        "is_main",
        "path",
        "size",
        "version",
        "created_at",
        "favourited_at",
        "archieved_at",
        "icon",
        "color",
        "action",
    }
