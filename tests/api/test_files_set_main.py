from uuid import uuid4
import pytest
import pytest_asyncio
from middlewares.lang import resolve_message
from services.mysql.factory.df_engine_generations import DfEngineGenerationsFactory
from services.mysql.factory.df_engine_generation_results import DfEngineGenerationResultsFactory
from services.mysql.factory.df_engine_model_options import DfEngineModelOptionsFactory
from services.mysql.factory.df_engine_menus import DfEngineMenusFactory
from services.mysql.factory.df_engine_features import DfEngineFeaturesFactory


def _set_main_url(task_uid, file_uid):
    return f"/api/files/{task_uid}/set-main/{file_uid}"


@pytest_asyncio.fixture
async def generation_fks(user_id) -> dict:
    """Self-contained model_option/menu/feature ids for df_engine_generations' NOT NULL FKs —
    created via factories rather than assumed to pre-exist, so this works on a fresh, empty DB too."""
    model_option = DfEngineModelOptionsFactory.create()
    menu = DfEngineMenusFactory.create(created_by=int(user_id), df_engine_menu_feature_mapping=None)
    feature = DfEngineFeaturesFactory.create(created_by=int(user_id), df_engine_feature_prompt_mapping=None)
    return {"model_id": model_option.id, "menu_id": menu.id, "feature_id": feature.id}


def _make_result(project_task, user_id, generation_fks, parent_id=None, is_main=True, name="a.png"):
    """A `DfEngineGenerationResults` row (with its parent `DfEngineGenerations`) shaped
    so `FilesService.base_of`/`type_root_of` recognize it, mirroring the archive/favorite tests."""
    generation = DfEngineGenerationsFactory.create(
        project_id=project_task.project_id,
        task_id=project_task.id,
        created_by=int(user_id),
        sourceable_id=1,
        **generation_fks,
    )
    path = f"storage/DF-Engine/{project_task.project.uid}/generated/images/{name}"
    return DfEngineGenerationResultsFactory.create(
        path=path,
        generation_id=generation.id,
        created_by=int(user_id),
        parent_id=parent_id,
        is_main=is_main,
    )


def _find_entry(nodes, uid):
    """Locate a file entry anywhere in the tree, including nested inside a parent's `variants`."""
    for node in nodes:
        for f in node["files"]:
            if f["uid"] == uid:
                return f
            found = next((v for v in f.get("variants", []) if v["uid"] == uid), None)
            if found is not None:
                return found
        found = _find_entry(node["childs"], uid)
        if found is not None:
            return found
    return None


@pytest.mark.asyncio
async def test_set_main_swaps_is_main_between_siblings(authed_client, project_task, user_id, generation_fks):
    """200 OK; setting a non-main sibling as main flips it to true and the previous main to false."""
    root = _make_result(project_task, user_id, generation_fks, name="root.png")
    current_main = _make_result(project_task, user_id, generation_fks, parent_id=root.id, is_main=True, name="a.png")
    target = _make_result(project_task, user_id, generation_fks, parent_id=root.id, is_main=False, name="b.png")

    resp = await authed_client.call("PATCH", _set_main_url(project_task.uid, target.uid))
    assert resp.status_code == 200

    data = resp.json()["data"]
    assert _find_entry(data, target.uid)["is_main"] is True
    assert _find_entry(data, current_main.uid)["is_main"] is False


@pytest.mark.asyncio
async def test_set_main_promoting_a_child_also_unsets_the_root(authed_client, project_task, user_id, generation_fks):
    """200 OK; the is_main family spans the root plus all of its children, not just siblings - so
    promoting a child flips the root's own (independently-defaulted) is_main to False too."""
    root = _make_result(project_task, user_id, generation_fks, name="root.png")
    child = _make_result(project_task, user_id, generation_fks, parent_id=root.id, is_main=False, name="a.png")

    resp = await authed_client.call("PATCH", _set_main_url(project_task.uid, child.uid))
    assert resp.status_code == 200

    data = resp.json()["data"]
    assert _find_entry(data, child.uid)["is_main"] is True
    assert _find_entry(data, root.uid)["is_main"] is False


@pytest.mark.asyncio
async def test_set_main_on_current_main_is_a_no_op_200(authed_client, project_task, user_id, generation_fks):
    """200 OK; re-setting the already-current main is a no-op that still returns the tree."""
    root = _make_result(project_task, user_id, generation_fks, name="root.png")
    current_main = _make_result(project_task, user_id, generation_fks, parent_id=root.id, is_main=True, name="a.png")

    resp = await authed_client.call("PATCH", _set_main_url(project_task.uid, current_main.uid))
    assert resp.status_code == 200
    assert _find_entry(resp.json()["data"], current_main.uid)["is_main"] is True


@pytest.mark.asyncio
async def test_set_main_on_root_result_is_422_result_has_no_parent(
    authed_client, project_task, user_id, generation_fks
):
    """422 file_uid_invalid; a root result (no parent_id) has nothing to contest, so it errors."""
    root = _make_result(project_task, user_id, generation_fks)

    resp = await authed_client.call("PATCH", _set_main_url(project_task.uid, root.uid), raise_for_status=False)
    assert resp.status_code == 422
    assert resp.json()["error"] == {"file_uid": [resolve_message("result_has_no_parent", "en")]}


@pytest.mark.asyncio
async def test_set_main_unknown_uid_is_422_file_not_found(authed_client, project_task):
    """422 file_uid_invalid; uid matches no generation result at all."""
    resp = await authed_client.call("PATCH", _set_main_url(project_task.uid, uuid4()), raise_for_status=False)
    assert resp.status_code == 422
    assert resp.json()["error"] == {"file_uid": [resolve_message("file_not_found", "en")]}
