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
    return next(e for e in body["data"] if e["generation_uid"] == str(generation_uid))


@pytest.mark.asyncio
async def test_generation_with_no_result_yet_has_total_data_zero(authed_client, project_task, user_id, generation_fks):
    """A still-processing generation (no result row, is_main=None) still gets total_data == 0
    at the top level, per the rule that every non-nested record carries total_data."""
    generation = _make_generation(project_task, user_id, generation_fks)

    resp = await authed_client.call("GET", _url(project_task.uid))
    assert resp.status_code == 200
    entry = _entry(resp.json(), generation.uid)
    assert entry["is_main"] is None
    assert entry["variants"] == []
    assert entry["total_data"] == 0


@pytest.mark.asyncio
async def test_standalone_main_result_has_total_data_zero(authed_client, project_task, user_id, generation_fks):
    """A standalone (no parent, no children) is_main result gets total_data == 0."""
    generation = _make_generation(project_task, user_id, generation_fks)
    _make_result(generation, user_id, is_main=True)

    resp = await authed_client.call("GET", _url(project_task.uid))
    entry = _entry(resp.json(), generation.uid)
    assert entry["is_main"] is True
    assert entry["variants"] == []
    assert entry["total_data"] == 0
    assert entry["action"]["can_download"] is True


@pytest.mark.asyncio
async def test_main_result_with_variants_reports_total_data_and_absorbs_children(
    authed_client, project_task, user_id, generation_fks
):
    """A root result plus a child variant: the is_main entry shows total_data == len(variants) and the
    child is folded into `variants` rather than appearing as its own top-level entry."""
    root_generation = _make_generation(project_task, user_id, generation_fks)
    root_result = _make_result(root_generation, user_id, is_main=True)

    child_generation = _make_generation(project_task, user_id, generation_fks)
    child_result = _make_result(child_generation, user_id, is_main=False, parent_id=root_result.id)

    resp = await authed_client.call("GET", _url(project_task.uid))
    body = resp.json()

    root_entry = _entry(body, root_generation.uid)
    assert root_entry["total_data"] == 1
    assert [v["file_uid"] for v in root_entry["variants"]] == [str(child_result.uid)]

    assert not any(e["generation_uid"] == str(child_generation.uid) for e in body["data"])


@pytest.mark.asyncio
async def test_variant_entries_have_no_total_data_key(authed_client, project_task, user_id, generation_fks):
    """Folded variant entries (nested under a main result) never carry a `total_data` key themselves."""
    root_generation = _make_generation(project_task, user_id, generation_fks)
    root_result = _make_result(root_generation, user_id, is_main=False)

    main_generation = _make_generation(project_task, user_id, generation_fks)
    _make_result(main_generation, user_id, is_main=True, parent_id=root_result.id)

    resp = await authed_client.call("GET", _url(project_task.uid))
    entry = _entry(resp.json(), main_generation.uid)
    assert entry["total_data"] == 1
    assert "total_data" not in entry["variants"][0]
    assert "variants" not in entry["variants"][0]


@pytest.mark.asyncio
async def test_archived_result_excluded_from_galleries(authed_client, project_task, user_id, generation_fks):
    """An archived generation result is not attached to its generation (archived rows are filtered
    out of the load), so the entry looks like a resultless generation: no file data, total_data == 0."""
    generation = _make_generation(project_task, user_id, generation_fks)
    _make_result(generation, user_id, is_main=True, archieved_at="2024-01-01 00:00:00")

    resp = await authed_client.call("GET", _url(project_task.uid))
    entry = _entry(resp.json(), generation.uid)
    assert entry["file_uid"] is None
    assert entry["is_main"] is None
    assert entry["total_data"] == 0


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
