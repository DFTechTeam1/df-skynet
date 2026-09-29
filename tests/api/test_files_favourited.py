from datetime import datetime
import pytest
import pytest_asyncio
from services.mysql.factory.df_engine_generations import DfEngineGenerationsFactory
from services.mysql.factory.df_engine_generation_results import DfEngineGenerationResultsFactory
from services.mysql.factory.df_engine_model_options import DfEngineModelOptionsFactory
from services.mysql.factory.df_engine_menus import DfEngineMenusFactory
from services.mysql.factory.df_engine_features import DfEngineFeaturesFactory


def _url(project_uid):
    return f"/api/files/{project_uid}/favourited"


@pytest_asyncio.fixture
async def generation_fks(user_id) -> dict:
    """Self-contained model_option/menu/feature ids for df_engine_generations' NOT NULL FKs —
    created via factories rather than assumed to pre-exist, so this works on a fresh, empty DB too."""
    model_option = DfEngineModelOptionsFactory.create()
    menu = DfEngineMenusFactory.create(created_by=int(user_id), df_engine_menu_feature_mapping=None)
    feature = DfEngineFeaturesFactory.create(created_by=int(user_id), df_engine_feature_prompt_mapping=None)
    return {"model_id": model_option.id, "menu_id": menu.id, "feature_id": feature.id}


def _make_generation(project_task, user_id, generation_fks, **overrides):
    return DfEngineGenerationsFactory.create(
        project_id=project_task.project_id,
        task_id=project_task.id,
        created_by=int(user_id),
        sourceable_id=1,
        **generation_fks,
        **overrides,
    )


def _make_result(generation, user_id, **overrides):
    return DfEngineGenerationResultsFactory.create(generation_id=generation.id, created_by=int(user_id), **overrides)


def _find_flat(files, uid):
    return next((f for f in files if f["file_uid"] == uid), None)


@pytest.mark.asyncio
async def test_get_favourited_files_only_returns_favourited_generations(
    authed_client, project_task, user_id, generation_fks
):
    """200 OK; flat list of only this user's favourited generation results."""
    favourited = _make_result(
        _make_generation(project_task, user_id, generation_fks), user_id, favourited_at=datetime.now()
    )
    not_favourited = _make_result(_make_generation(project_task, user_id, generation_fks), user_id, favourited_at=None)

    resp = await authed_client.call("GET", _url(project_task.project.uid))
    assert resp.status_code == 200
    assert isinstance(resp.json()["data"], list)
    assert _find_flat(resp.json()["data"], favourited.uid) is not None
    assert _find_flat(resp.json()["data"], not_favourited.uid) is None


@pytest.mark.asyncio
async def test_favourited_action_flags(authed_client, project_task, user_id, generation_fks):
    """200 OK; a favourited (but not archived, non-main) generation result allows unfavorite, and
    archiving is an independent lock unaffected by the favourite state."""
    result = _make_result(
        _make_generation(project_task, user_id, generation_fks), user_id, favourited_at=datetime.now(), is_main=False
    )

    resp = await authed_client.call("GET", _url(project_task.project.uid))
    file = _find_flat(resp.json()["data"], result.uid)
    assert file["action"]["can_favorited"] is False
    assert file["action"]["can_unfavorited"] is True
    assert file["action"]["can_archieve"] is True


@pytest.mark.asyncio
async def test_favourited_entry_matches_generation_result_record_shape(
    authed_client, project_task, user_id, generation_fks
):
    """200 OK; favourited entries are a `GenerationResultRecord` with the generation-context
    fields (status/creator/cost/model/prompt) dropped, since they're redundant per-user context."""
    result = _make_result(
        _make_generation(project_task, user_id, generation_fks), user_id, favourited_at=datetime.now()
    )

    resp = await authed_client.call("GET", _url(project_task.project.uid))
    file = _find_flat(resp.json()["data"], result.uid)
    assert file.keys() == {
        "id",
        "flag_created_at",
        "flag_favourited_at",
        "flag_archieved_at",
        "kind",
        "file_uid",
        "generation_uid",
        "name",
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
