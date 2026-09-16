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


def _make_result(project_task, user_id, generation_fks, name="a.png", kind="images", is_main=False):
    """A live (non-archived, non-favourited) `DfEngineGenerationResults` row. Defaults to
    `is_main=False` since only a non-main result can be archived - a family always needs
    exactly one `is_main=True` member, so a non-main row is given a hidden main parent."""
    generation = DfEngineGenerationsFactory.create(
        project_id=project_task.project_id,
        task_id=project_task.id,
        created_by=int(user_id),
        sourceable_id=1,
        **generation_fks,
    )
    parent_id = None
    if not is_main:
        parent_generation = DfEngineGenerationsFactory.create(
            project_id=project_task.project_id,
            task_id=project_task.id,
            created_by=int(user_id),
            sourceable_id=1,
            **generation_fks,
        )
        parent_id = DfEngineGenerationResultsFactory.create(
            generation_id=parent_generation.id, created_by=int(user_id), is_main=True
        ).id
    path = f"storage/DF-Engine/{project_task.project.uid}/generated/{kind}/{name}"
    return DfEngineGenerationResultsFactory.create(
        path=path, generation_id=generation.id, created_by=int(user_id), is_main=is_main, parent_id=parent_id
    )


def _find_file_node(nodes, uid):
    for node in nodes:
        for f in node["files"]:
            if f["uid"] == uid:
                return f
            found = next((v for v in f.get("variants", []) if v["uid"] == uid), None)
            if found is not None:
                return found
        found = _find_file_node(node["childs"], uid)
        if found is not None:
            return found
    return None


@pytest.mark.asyncio
async def test_get_files_returns_uploaded_file(authed_client, project_task, user_id):
    """200 OK; a file uploaded by the current user appears in the returned tree."""
    row = _make_file(project_task, user_id)
    resp = await authed_client.call("GET", _url(project_task.uid))
    assert resp.status_code == 200
    assert _find_file_node(resp.json()["data"], row.uid) is not None
    assert _find_file_node(resp.json()["data"], uuid4()) is None


@pytest.mark.asyncio
async def test_get_files_unknown_task_is_404(authed_client):
    """404 project_task_not_found for a task uid that matches no row."""
    resp = await authed_client.call("GET", _url(uuid4()), raise_for_status=False)
    assert resp.status_code == 404
    assert resp.json()["message"] == resolve_message("project_task_not_found", "en")


@pytest.mark.asyncio
async def test_requires_auth(client, project_task):
    """401 when the request carries no bearer token."""
    resp = await client.call("GET", _url(project_task.uid), raise_for_status=False)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_live_generation_action_flags(authed_client, project_task, user_id, generation_fks):
    """200 OK; a live generation result allows archieve/favorite and blocks unarchieve/unfavorited/moving."""
    result = _make_result(project_task, user_id, generation_fks, name="live_flags.png")

    resp = await authed_client.call("GET", _url(project_task.uid))
    file = _find_file_node(resp.json()["data"], result.uid)
    assert file["action"]["can_archieve"] is True
    assert file["action"]["can_unarchieve"] is False
    assert file["action"]["can_favorited"] is True
    assert file["action"]["can_unfavorited"] is False
    assert file["action"]["can_choose_to_move"] is True
