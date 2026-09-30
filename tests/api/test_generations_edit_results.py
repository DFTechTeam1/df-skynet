import pytest
import pytest_asyncio
from uuid import uuid4
from middlewares.lang import resolve_message
from services.mysql.factory.df_engine_generations import DfEngineGenerationsFactory
from services.mysql.factory.df_engine_generation_results import DfEngineGenerationResultsFactory
from services.mysql.factory.df_engine_model_options import DfEngineModelOptionsFactory
from services.mysql.factory.df_engine_menus import DfEngineMenusFactory
from services.mysql.factory.df_engine_features import DfEngineFeaturesFactory

EDIT_RESULTS_URL = "/api/generation-edit-results"
MAIN_RESULTS_URL = "/api/generation-main-results"


def _url(generation_uid):
    return f"{EDIT_RESULTS_URL}/{generation_uid}"


@pytest_asyncio.fixture
async def generation_fks(user_id) -> dict:
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


@pytest.mark.asyncio
async def test_returns_rich_detail_with_action_and_references(authed_client, project_task, user_id, generation_fks):
    """200 OK, keyed by generation_uid; response includes `full_prompt`, `is_main`,
    `version`, `action`, and `references` for that generation's own (n=1) result."""
    generation = _make_generation(project_task, user_id, generation_fks)
    result = _make_result(generation, user_id, is_main=True, version=1)

    resp = await authed_client.call("GET", _url(generation.uid))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["file_uid"] == str(result.uid)
    assert data["is_main"] is True
    assert data["version"] == 1
    assert data["parent_id"] is None
    assert "full_prompt" in data
    assert "action" in data
    assert "references" in data
    assert isinstance(data["references"], list)


@pytest.mark.asyncio
async def test_non_root_version_resolves_to_its_own_flat_entry(authed_client, project_task, user_id, generation_fks):
    """200 OK; fetching a child generation directly returns that generation's own
    result entry (parent_id pointing at the root), not the root's."""
    root_generation = _make_generation(project_task, user_id, generation_fks)
    root = _make_result(root_generation, user_id, is_main=True, version=1)

    child_generation = _make_generation(project_task, user_id, generation_fks)
    child = _make_result(child_generation, user_id, is_main=False, parent_id=root.id, version=2)

    resp = await authed_client.call("GET", _url(child_generation.uid))
    data = resp.json()["data"]
    assert data["file_uid"] == str(child.uid)
    assert data["parent_id"] == root.id
    assert data["version"] == 2


@pytest.mark.asyncio
async def test_shares_base_fields_with_main_results_but_adds_more(authed_client, project_task, user_id, generation_fks):
    """200 OK; both endpoints describe the same row and agree on the shared fields
    (kind, name, path, model, prompt, creator), but `/generation-main-results` excludes
    `is_main`/`version`/`full_prompt` while `/generation-edit-results` keeps them."""
    generation = _make_generation(project_task, user_id, generation_fks)
    _make_result(generation, user_id, is_main=True, version=1)

    edit_resp = await authed_client.call("GET", _url(generation.uid))
    main_resp = await authed_client.call("GET", f"{MAIN_RESULTS_URL}/{generation.uid}")
    edit_data = edit_resp.json()["data"]
    main_data = main_resp.json()["data"]

    for field in ("kind", "file_uid", "name", "path", "model", "prompt", "creator"):
        assert edit_data[field] == main_data[field]

    assert "is_main" not in main_data
    assert "version" not in main_data
    assert "full_prompt" not in main_data
    assert edit_data["is_main"] is True
    assert edit_data["version"] == 1


@pytest.mark.asyncio
async def test_unknown_file_is_404(authed_client):
    """404 generation_file_not_found for a generation uid that matches no row."""
    resp = await authed_client.call("GET", _url(uuid4()), raise_for_status=False)
    assert resp.status_code == 404
    assert resp.json()["message"] == resolve_message("generation_file_not_found", "en")


@pytest.mark.asyncio
async def test_requires_auth(client):
    """401 when the request carries no bearer token."""
    resp = await client.call("GET", _url(uuid4()), raise_for_status=False)
    assert resp.status_code == 401
