import pytest
import pytest_asyncio
from uuid import uuid4
from middlewares.lang import resolve_message
from services.mysql.factory.df_engine_generations import DfEngineGenerationsFactory
from services.mysql.factory.df_engine_generation_results import DfEngineGenerationResultsFactory
from services.mysql.factory.df_engine_model_options import DfEngineModelOptionsFactory
from services.mysql.factory.df_engine_menus import DfEngineMenusFactory
from services.mysql.factory.df_engine_features import DfEngineFeaturesFactory

URL = "/api/user-galleries"


def _url(task_uid):
    return f"{URL}/{task_uid}"


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


def _entry(body, generation_uid):
    return next(e for e in body["data"]["paginated"] if e["generation_uid"] == str(generation_uid))


@pytest.mark.asyncio
async def test_generation_with_no_result_yet_has_zero_variants(authed_client, project_task, user_id, generation_fks):
    """A still-processing generation (no result row) has no file data and total_variant == 0."""
    generation = _make_generation(project_task, user_id, generation_fks)

    resp = await authed_client.call("GET", _url(project_task.uid))
    assert resp.status_code == 200
    entry = _entry(resp.json(), generation.uid)
    assert entry["is_main"] is None
    assert entry["file_uid"] is None
    assert entry["total_variant"] == 0
    assert "variants" not in entry


@pytest.mark.asyncio
async def test_standalone_main_result_reports_itself_as_the_only_variant(
    authed_client, project_task, user_id, generation_fks
):
    """A standalone (no children) is_main result counts itself: total_variant == 1."""
    generation = _make_generation(project_task, user_id, generation_fks)
    result = _make_result(generation, user_id, is_main=True)

    resp = await authed_client.call("GET", _url(project_task.uid))
    entry = _entry(resp.json(), generation.uid)
    assert entry["is_main"] is True
    assert entry["file_uid"] == str(result.uid)
    assert entry["total_variant"] == 1
    assert entry["action"]["can_download"] is True


@pytest.mark.asyncio
async def test_main_result_with_child_counts_both_and_child_not_listed_separately(
    authed_client, project_task, user_id, generation_fks
):
    """A root result plus a child variant: total_variant counts the child plus itself (2), and the
    child's own generation never appears as its own top-level entry."""
    root_generation = _make_generation(project_task, user_id, generation_fks)
    root_result = _make_result(root_generation, user_id, is_main=True)

    child_generation = _make_generation(project_task, user_id, generation_fks)
    _make_result(child_generation, user_id, is_main=False, parent_id=root_result.id)

    resp = await authed_client.call("GET", _url(project_task.uid))
    body = resp.json()

    root_entry = _entry(body, root_generation.uid)
    assert root_entry["total_variant"] == 2
    assert not any(e["generation_uid"] == str(child_generation.uid) for e in body["data"]["paginated"])


@pytest.mark.asyncio
async def test_archived_only_result_excludes_the_generation_entirely(
    authed_client, project_task, user_id, generation_fks
):
    """A generation whose only result is archived is filtered out of the gallery entirely."""
    generation = _make_generation(project_task, user_id, generation_fks)
    _make_result(generation, user_id, is_main=True, archieved_at="2024-01-01 00:00:00")

    resp = await authed_client.call("GET", _url(project_task.uid))
    body = resp.json()
    assert not any(e["generation_uid"] == str(generation.uid) for e in body["data"]["paginated"])


@pytest.mark.asyncio
async def test_search_matches_file_name_or_prompt_prefix(authed_client, project_task, user_id, generation_fks):
    """`search` matches either the result's file name or the generation's prompt, as a starts-with prefix."""
    prefix = f"gallery-{uuid4().hex[:8]}"
    by_name = _make_generation(project_task, user_id, generation_fks, prompt="unrelated prompt")
    _make_result(by_name, user_id, is_main=True, name=f"{prefix}-name.png")

    by_prompt = _make_generation(project_task, user_id, generation_fks, prompt=f"{prefix} a scenic mountain")
    _make_result(by_prompt, user_id, is_main=True)

    non_matching = _make_generation(project_task, user_id, generation_fks, prompt="totally different")
    _make_result(non_matching, user_id, is_main=True, name="unrelated.png")

    resp = await authed_client.call("GET", _url(project_task.uid), params={"search": prefix})
    uids = [e["generation_uid"] for e in resp.json()["data"]["paginated"]]
    assert str(by_name.uid) in uids
    assert str(by_prompt.uid) in uids
    assert str(non_matching.uid) not in uids


@pytest.mark.asyncio
async def test_pagination_limits_records_per_page(authed_client, project_task, user_id, generation_fks):
    """itemsPerPage caps the number of records returned while totalData reflects the full count."""
    for _ in range(3):
        gen = _make_generation(project_task, user_id, generation_fks)
        _make_result(gen, user_id, is_main=True)

    resp = await authed_client.call("GET", _url(project_task.uid), params={"page": 1, "itemsPerPage": 2})
    body = resp.json()["data"]
    assert body["totalData"] >= 3
    assert len(body["paginated"]) == 2


@pytest.mark.asyncio
async def test_response_is_cached_on_second_call(authed_client, project_task, user_id, generation_fks):
    """Second call returns identical data (served from the user-galleries cache key)."""
    generation = _make_generation(project_task, user_id, generation_fks)
    _make_result(generation, user_id, is_main=True)

    first = await authed_client.call("GET", _url(project_task.uid))
    second = await authed_client.call("GET", _url(project_task.uid))
    assert first.json()["data"] == second.json()["data"]


@pytest.mark.asyncio
async def test_unknown_task_is_404(authed_client):
    """404 project_task_not_found for a task uid that matches no row."""
    resp = await authed_client.call("GET", _url(uuid4()), raise_for_status=False)
    assert resp.status_code == 404
    assert resp.json()["message"] == resolve_message("project_task_not_found", "en")


@pytest.mark.asyncio
async def test_requires_auth(client, project_task):
    """401 when the request carries no bearer token."""
    resp = await client.call("GET", _url(project_task.uid), raise_for_status=False)
    assert resp.status_code == 401
