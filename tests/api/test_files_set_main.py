from uuid import uuid4
import pytest
import pytest_asyncio
from middlewares.lang import resolve_message
from services.mysql.factory.df_engine_generations import DfEngineGenerationsFactory
from services.mysql.factory.df_engine_generation_results import DfEngineGenerationResultsFactory
from services.mysql.factory.df_engine_model_options import DfEngineModelOptionsFactory
from services.mysql.factory.df_engine_menus import DfEngineMenusFactory
from services.mysql.factory.df_engine_features import DfEngineFeaturesFactory


def _set_main_url(file_uid):
    return f"/api/files/set-main/{file_uid}"


@pytest_asyncio.fixture
async def generation_fks(user_id) -> dict:
    """Self-contained model_option/menu/feature ids for df_engine_generations' NOT NULL FKs —
    created via factories rather than assumed to pre-exist, so this works on a fresh, empty DB too."""
    model_option = DfEngineModelOptionsFactory.create()
    menu = DfEngineMenusFactory.create(created_by=int(user_id), df_engine_menu_feature_mapping=None)
    feature = DfEngineFeaturesFactory.create(created_by=int(user_id), df_engine_feature_prompt_mapping=None)
    return {"model_id": model_option.id, "menu_id": menu.id, "feature_id": feature.id}


def _make_result(project_task, user_id, generation_fks, parent_id=None, is_main=True):
    generation = DfEngineGenerationsFactory.create(
        project_id=project_task.project_id,
        task_id=project_task.id,
        created_by=int(user_id),
        sourceable_id=1,
        **generation_fks,
    )
    return DfEngineGenerationResultsFactory.create(
        generation_id=generation.id, created_by=int(user_id), parent_id=parent_id, is_main=is_main
    )


def _find_variant(variants, uid):
    return next((v for v in variants if v["file_uid"] == str(uid)), None)


@pytest.mark.asyncio
async def test_set_main_swaps_is_main_between_siblings(authed_client, project_task, user_id, generation_fks):
    """200 OK; setting a non-main sibling as main flips it to true and the previous main to false."""
    root = _make_result(project_task, user_id, generation_fks)
    current_main = _make_result(project_task, user_id, generation_fks, parent_id=root.id, is_main=True)
    target = _make_result(project_task, user_id, generation_fks, parent_id=root.id, is_main=False)

    resp = await authed_client.call("PATCH", _set_main_url(target.uid))
    assert resp.status_code == 200

    data = resp.json()["data"]
    assert data["file_uid"] == str(target.uid)
    assert data["is_main"] is True
    assert _find_variant(data["variants"], current_main.uid)["is_main"] is False


@pytest.mark.asyncio
async def test_set_main_promoting_a_child_also_unsets_the_root(authed_client, project_task, user_id, generation_fks):
    """200 OK; the is_main family spans the root plus all of its children, not just siblings - so
    promoting a child flips the root's own (independently-defaulted) is_main to False too."""
    root = _make_result(project_task, user_id, generation_fks)
    child = _make_result(project_task, user_id, generation_fks, parent_id=root.id, is_main=False)

    resp = await authed_client.call("PATCH", _set_main_url(child.uid))
    assert resp.status_code == 200

    data = resp.json()["data"]
    assert data["is_main"] is True
    assert _find_variant(data["variants"], root.uid)["is_main"] is False


@pytest.mark.asyncio
async def test_set_main_on_current_main_is_422(authed_client, project_task, user_id, generation_fks):
    """422 file_uid_invalid; re-setting the already-current main is invalid, not a no-op."""
    root = _make_result(project_task, user_id, generation_fks)
    current_main = _make_result(project_task, user_id, generation_fks, parent_id=root.id, is_main=True)

    resp = await authed_client.call("PATCH", _set_main_url(current_main.uid), raise_for_status=False)
    assert resp.status_code == 422
    assert resp.json()["message"] == resolve_message("file_uid_invalid", "en")
    assert resp.json()["error"] == {"file_uid": [resolve_message("file_not_found", "en")]}


@pytest.mark.asyncio
async def test_set_main_on_root_result_demotes_its_current_main_child(
    authed_client, project_task, user_id, generation_fks
):
    """200 OK; a root result has no parent, but it can still be reinstated as main - that demotes
    whichever of its children currently holds is_main, matched via `parent_id == row.id`."""
    root = _make_result(project_task, user_id, generation_fks, is_main=False)
    child = _make_result(project_task, user_id, generation_fks, parent_id=root.id, is_main=True)

    resp = await authed_client.call("PATCH", _set_main_url(root.uid))
    assert resp.status_code == 200

    data = resp.json()["data"]
    assert data["file_uid"] == str(root.uid)
    assert data["is_main"] is True
    assert _find_variant(data["variants"], child.uid)["is_main"] is False


@pytest.mark.asyncio
async def test_set_main_unknown_uid_is_404_main_generation_file_not_found(authed_client, project_task):
    """404 main_generation_file_not_found; uid matches no generation result at all, error is None."""
    resp = await authed_client.call("PATCH", _set_main_url(uuid4()), raise_for_status=False)
    assert resp.status_code == 404
    assert resp.json()["message"] == resolve_message("main_generation_file_not_found", "en")
    assert resp.json()["error"] is None
