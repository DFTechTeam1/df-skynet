import pytest
import pytest_asyncio
from uuid import uuid4
from middlewares.lang import resolve_message
from services.mysql.factory.df_engine_generations import DfEngineGenerationsFactory
from services.mysql.factory.df_engine_generation_results import DfEngineGenerationResultsFactory
from services.mysql.factory.df_engine_model_options import DfEngineModelOptionsFactory
from services.mysql.factory.df_engine_menus import DfEngineMenusFactory
from services.mysql.factory.df_engine_features import DfEngineFeaturesFactory

URL = "/api/user-galleries/generated"


def _url(file_uid):
    return f"{URL}/{file_uid}"


@pytest_asyncio.fixture
async def generation_fks(user_id) -> dict:
    """Self-contained model_option/menu/feature ids for df_engine_generations' NOT NULL FKs."""
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
async def test_root_file_with_no_siblings_has_one_variant_and_no_variants_key(
    authed_client, project_task, user_id, generation_fks
):
    """200 OK; a standalone root (version 1, no children) reports a single-entry `variants` list."""
    generation = _make_generation(project_task, user_id, generation_fks)
    result = _make_result(generation, user_id, is_main=True, version=1)

    resp = await authed_client.call("GET", _url(result.uid))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["file_uid"] == str(result.uid)
    assert data["is_main"] is True
    assert data["version"] == 1
    assert len(data["variants"]) == 1
    assert data["variants"][0]["file_uid"] == str(result.uid)


@pytest.mark.asyncio
async def test_root_file_with_children_lists_variants_sorted_by_version(
    authed_client, project_task, user_id, generation_fks
):
    """200 OK; fetching the root (version 1) of a multi-result family includes a `variants` list sorted by version."""
    root_generation = _make_generation(project_task, user_id, generation_fks)
    root = _make_result(root_generation, user_id, is_main=True, version=1)

    child_generation = _make_generation(project_task, user_id, generation_fks)
    child = _make_result(child_generation, user_id, is_main=False, parent_id=root.id, version=2)

    resp = await authed_client.call("GET", _url(root.uid))
    data = resp.json()["data"]
    assert data["file_uid"] == str(root.uid)
    assert "variants" in data
    assert len(data["variants"]) == 2
    versions = [v["version"] for v in data["variants"]]
    assert versions == sorted(versions)
    variant_uids = [v["file_uid"] for v in data["variants"]]
    assert str(root.uid) in variant_uids
    assert str(child.uid) in variant_uids


@pytest.mark.asyncio
async def test_non_root_version_fetched_directly_has_no_variants_key(
    authed_client, project_task, user_id, generation_fks
):
    """200 OK; fetching a non-root version directly returns a flat entry — no `variants` key even though
    the family has multiple rows, since the endpoint only attaches `variants` for the root (version 1)."""
    root_generation = _make_generation(project_task, user_id, generation_fks)
    root = _make_result(root_generation, user_id, is_main=True, version=1)

    child_generation = _make_generation(project_task, user_id, generation_fks)
    child = _make_result(child_generation, user_id, is_main=False, parent_id=root.id, version=2)

    resp = await authed_client.call("GET", _url(child.uid))
    data = resp.json()["data"]
    assert data["file_uid"] == str(child.uid)
    assert data["version"] == 2
    assert "variants" not in data


@pytest.mark.asyncio
async def test_response_is_cached_on_second_call(authed_client, project_task, user_id, generation_fks):
    """200 OK; second call returns identical data (served from the generation_file_detail cache key)."""
    generation = _make_generation(project_task, user_id, generation_fks)
    result = _make_result(generation, user_id, is_main=True, version=1)

    first = await authed_client.call("GET", _url(result.uid))
    second = await authed_client.call("GET", _url(result.uid))
    assert first.json()["data"] == second.json()["data"]


@pytest.mark.asyncio
async def test_unknown_file_is_404(authed_client):
    """404 main_generation_file_not_found for a file uid that matches no row."""
    resp = await authed_client.call("GET", _url(uuid4()), raise_for_status=False)
    assert resp.status_code == 404
    assert resp.json()["message"] == resolve_message("main_generation_file_not_found", "en")


@pytest.mark.asyncio
async def test_file_owned_by_another_user_is_still_visible(authed_client, project_task, generation_fks, other_user_id):
    """200 OK; the gallery is task-shared, so a file created by another member on the same task is
    still fetchable — visibility is task-scoped, not owner-scoped. `is_owner`-gated actions (e.g.
    `can_set_main`, `can_use_as_edit`) are what actually restrict what the viewer can do with it."""
    generation = _make_generation(project_task, other_user_id, generation_fks)
    result = _make_result(generation, other_user_id, is_main=True, version=1)

    resp = await authed_client.call("GET", _url(result.uid))
    data = resp.json()["data"]
    assert data["file_uid"] == str(result.uid)
    assert data["creator"]["user_id"] == int(other_user_id)
    assert data["action"]["can_set_main"] is False
    assert data["action"]["can_use_as_edit"] is False


@pytest.mark.asyncio
async def test_sibling_owned_by_another_user_is_still_visible(
    authed_client, project_task, user_id, generation_fks, other_user_id
):
    """200 OK; a sibling version created by another member of the same family is listed among the
    variants of a file the requesting user owns."""
    root_generation = _make_generation(project_task, user_id, generation_fks)
    root = _make_result(root_generation, user_id, is_main=True, version=1)

    other_generation = _make_generation(project_task, other_user_id, generation_fks)
    other = _make_result(other_generation, other_user_id, is_main=False, parent_id=root.id, version=2)

    resp = await authed_client.call("GET", _url(root.uid))
    data = resp.json()["data"]
    variant_uids = [v["file_uid"] for v in data["variants"]]
    assert str(other.uid) in variant_uids

    resp = await authed_client.call("GET", _url(other.uid))
    data = resp.json()["data"]
    assert data["file_uid"] == str(other.uid)
    assert data["creator"]["user_id"] == int(other_user_id)


@pytest.mark.asyncio
async def test_requires_auth(client, project_task):
    """401 when the request carries no bearer token."""
    resp = await client.call("GET", _url(uuid4()), raise_for_status=False)
    assert resp.status_code == 401
