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


def _entry(body, file_uid):
    return next(e for e in body["data"] if e["file_uid"] == str(file_uid))


@pytest.mark.asyncio
async def test_generation_with_no_result_yet_is_excluded(authed_client, project_task, user_id, generation_fks):
    """200 OK; a still-processing generation (no result row yet) has no main result, so it's excluded from the list."""
    before = await authed_client.call("GET", _url(project_task.uid))
    baseline = len(before.json()["data"])

    _make_generation(project_task, user_id, generation_fks)

    resp = await authed_client.call("GET", _url(project_task.uid))
    assert resp.status_code == 200
    assert len(resp.json()["data"]) == baseline


@pytest.mark.asyncio
async def test_standalone_main_result_appears_in_the_list(authed_client, project_task, user_id, generation_fks):
    """200 OK; a standalone (no children) is_main result appears as one entry, keyed by its file_uid."""
    generation = _make_generation(project_task, user_id, generation_fks)
    result = _make_result(generation, user_id, is_main=True)

    resp = await authed_client.call("GET", _url(project_task.uid))
    entry = _entry(resp.json(), result.uid)
    assert entry["action"]["can_download"] is True


@pytest.mark.asyncio
async def test_child_result_never_listed_separately(authed_client, project_task, user_id, generation_fks):
    """200 OK; a root result appears; its child variant (is_main=False, no main result of its own) never
    appears as its own top-level entry."""
    root_generation = _make_generation(project_task, user_id, generation_fks)
    root_result = _make_result(root_generation, user_id, is_main=True)

    child_generation = _make_generation(project_task, user_id, generation_fks)
    child_result = _make_result(child_generation, user_id, is_main=False, parent_id=root_result.id)

    resp = await authed_client.call("GET", _url(project_task.uid))
    files = resp.json()["data"]
    assert any(e["file_uid"] == str(root_result.uid) for e in files)
    assert not any(e["file_uid"] == str(child_result.uid) for e in files)


@pytest.mark.asyncio
async def test_main_result_listed_regardless_of_archieved_at(authed_client, project_task, user_id, generation_fks):
    """200 OK; the gallery list is keyed off is_main alone; archieved_at isn't filtered (archiving a main
    result isn't a normal flow — can_archieve requires is_main is False — but if it happens, the
    result still appears here)."""
    generation = _make_generation(project_task, user_id, generation_fks)
    result = _make_result(generation, user_id, is_main=True, archieved_at="2024-01-01 00:00:00")

    resp = await authed_client.call("GET", _url(project_task.uid))
    files = resp.json()["data"]
    assert any(e["file_uid"] == str(result.uid) for e in files)


@pytest.mark.asyncio
async def test_search_matches_file_name_or_prompt_prefix(authed_client, project_task, user_id, generation_fks):
    """200 OK; `search` matches either the result's file name or the generation's prompt, as a starts-with prefix."""
    prefix = f"gallery-{uuid4().hex[:8]}"
    by_name = _make_generation(project_task, user_id, generation_fks, prompt="unrelated prompt")
    by_name_result = _make_result(by_name, user_id, is_main=True, name=f"{prefix}-name.png")

    by_prompt = _make_generation(project_task, user_id, generation_fks, prompt=f"{prefix} a scenic mountain")
    by_prompt_result = _make_result(by_prompt, user_id, is_main=True)

    non_matching = _make_generation(project_task, user_id, generation_fks, prompt="totally different")
    non_matching_result = _make_result(non_matching, user_id, is_main=True, name="unrelated.png")

    resp = await authed_client.call("GET", _url(project_task.uid), params={"search": prefix})
    uids = [e["file_uid"] for e in resp.json()["data"]]
    assert str(by_name_result.uid) in uids
    assert str(by_prompt_result.uid) in uids
    assert str(non_matching_result.uid) not in uids


@pytest.mark.asyncio
async def test_all_matching_results_are_returned_unpaginated(authed_client, project_task, user_id, generation_fks):
    """200 OK; the endpoint returns every matching result in one flat list — there's no pagination."""
    results = [
        _make_result(_make_generation(project_task, user_id, generation_fks), user_id, is_main=True) for _ in range(3)
    ]

    resp = await authed_client.call("GET", _url(project_task.uid))
    uids = [e["file_uid"] for e in resp.json()["data"]]
    assert all(str(r.uid) in uids for r in results)


@pytest.mark.asyncio
async def test_response_is_cached_on_second_call(authed_client, project_task, user_id, generation_fks):
    """200 OK; second call returns identical data (served from the user-galleries cache key)."""
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
