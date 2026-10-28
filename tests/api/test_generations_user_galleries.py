import pytest
import pytest_asyncio
from uuid import uuid4
from middlewares.lang import resolve_message
from services.mysql.model.df_engine_generations import GenerationStatuses
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
async def test_processing_generation_with_no_result_yet_appears_as_a_pending_entry(
    authed_client, project_task, user_id, generation_fks
):
    """200 OK; a still-processing generation with no result row yet still shows up, as a pending
    placeholder entry (no file_uid, status=processing) so the UI can render it loading."""
    generation = _make_generation(project_task, user_id, generation_fks)  # default status=processing

    resp = await authed_client.call("GET", _url(project_task.uid))
    assert resp.status_code == 200
    entries = [e for e in resp.json()["data"] if e["generation_uid"] == str(generation.uid)]
    assert len(entries) == 1
    assert entries[0]["file_uid"] is None
    assert entries[0]["status"] == "processing"
    assert entries[0]["action"]["can_download"] is False


@pytest.mark.asyncio
async def test_queued_generation_with_no_result_is_not_shown(authed_client, project_task, user_id, generation_fks):
    """200 OK; status is still the gate on top of the has-a-result check — a queued (not yet
    processing) generation with no result doesn't appear as a pending entry either."""
    generation = _make_generation(project_task, user_id, generation_fks, status=GenerationStatuses.queued)

    resp = await authed_client.call("GET", _url(project_task.uid))
    assert not any(e["generation_uid"] == str(generation.uid) for e in resp.json()["data"])


@pytest.mark.asyncio
async def test_my_task_includes_my_pending_generation_and_excludes_others(
    authed_client, project_task, user_id, other_user_id, generation_fks
):
    """200 OK; my_task=true restricts to generations the caller created — including one still
    pending with no result — and excludes another member's generation."""
    mine_pending = _make_generation(project_task, user_id, generation_fks)
    mine_done = _make_generation(project_task, user_id, generation_fks)
    mine_done_result = _make_result(mine_done, user_id, is_main=True)

    others = DfEngineGenerationsFactory.create(
        project_id=project_task.project_id,
        task_id=project_task.id,
        created_by=other_user_id,
        sourceable_id=1,
        **generation_fks,
    )
    others_result = _make_result(others, other_user_id, is_main=True)

    resp = await authed_client.call("GET", _url(project_task.uid), params={"my_task": True})
    data = resp.json()["data"]
    generation_uids = {e["generation_uid"] for e in data}
    file_uids = {e["file_uid"] for e in data}
    assert str(mine_pending.uid) in generation_uids
    assert str(mine_done_result.uid) in file_uids
    assert str(others_result.uid) not in file_uids


@pytest.mark.asyncio
async def test_failed_or_queued_generation_is_excluded_even_with_a_main_result(
    authed_client, project_task, user_id, generation_fks
):
    """200 OK; only success/processing generations are listed — a main result from a failed
    or queued generation never appears, even though it has an is_main result row."""
    failed = _make_generation(project_task, user_id, generation_fks, status=GenerationStatuses.failed)
    failed_result = _make_result(failed, user_id, is_main=True)

    queued = _make_generation(project_task, user_id, generation_fks, status=GenerationStatuses.queued)
    queued_result = _make_result(queued, user_id, is_main=True)

    success = _make_generation(project_task, user_id, generation_fks, status=GenerationStatuses.success)
    success_result = _make_result(success, user_id, is_main=True)

    resp = await authed_client.call("GET", _url(project_task.uid))
    uids = [e["file_uid"] for e in resp.json()["data"]]
    assert str(failed_result.uid) not in uids
    assert str(queued_result.uid) not in uids
    assert str(success_result.uid) in uids


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
    result isn't a normal flow — can_set_archieve requires is_main is False — but if it happens, the
    result still appears here)."""
    generation = _make_generation(project_task, user_id, generation_fks)
    result = _make_result(generation, user_id, is_main=True, archieved_at="2024-01-01 00:00:00")

    resp = await authed_client.call("GET", _url(project_task.uid))
    files = resp.json()["data"]
    assert any(e["file_uid"] == str(result.uid) for e in files)


@pytest.mark.asyncio
async def test_search_is_scoped_to_the_task_and_served_from_the_index(authed_client, project_task, monkeypatch):
    """200 OK; with `search` the list comes from the search index, scoped to this task or song uid, and the hits are
    returned in the gallery shape (no prompt/variants/references). Matching itself is the engine's job (covered in
    tests/unit/test_search_provider.py), so the engine is stubbed here."""
    seen = []

    async def fake_search(requests):
        seen.extend(requests)
        hit = {
            "file_uid": "g1",
            "name": "gallery-name.png",
            "path": "p/g.png",
            "kind": "image",
            "prompt": "x",
            "is_main": True,
            "creator": {"user_id": 1},
        }
        return [[hit]]

    monkeypatch.setattr("services.search.query._search", fake_search)
    resp = await authed_client.call("GET", _url(project_task.uid), params={"search": "gallery"})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert [e["file_uid"] for e in data] == ["g1"]
    assert "prompt" not in data[0] and "variants" not in data[0]
    assert seen[0].query == "gallery" and str(project_task.uid) in repr(seen[0].filter)


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
