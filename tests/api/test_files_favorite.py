from datetime import datetime
from uuid import uuid4
import pytest
import pytest_asyncio
from middlewares.lang import resolve_message
from services.mysql.factory.df_engine_generations import DfEngineGenerationsFactory
from services.mysql.factory.df_engine_generation_results import DfEngineGenerationResultsFactory
from services.mysql.factory.df_engine_model_options import DfEngineModelOptionsFactory
from services.mysql.factory.df_engine_menus import DfEngineMenusFactory
from services.mysql.factory.df_engine_features import DfEngineFeaturesFactory


def _favorite_url(project_uid):
    return f"/api/files/{project_uid}/favorite"


def _archived_url(project_uid):
    return f"/api/files/{project_uid}/archieved"


def _favourited_url(project_uid):
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


def _make_result(project_task, user_id, generation_fks, **overrides):
    generation = _make_generation(project_task, user_id, generation_fks)
    return DfEngineGenerationResultsFactory.create(generation_id=generation.id, created_by=int(user_id), **overrides)


def _find_flat(files, uid):
    return next((f for f in files if f["file_uid"] == str(uid)), None)


@pytest.mark.asyncio
async def test_favorite_file_appears_in_favourited_list(authed_client, project_task, user_id, generation_fks):
    """200 OK; default body (is_favorited=true) returns the updated favourited list, and the file shows there."""
    result = _make_result(project_task, user_id, generation_fks)

    resp = await authed_client.call("PATCH", _favorite_url(project_task.uid), json={"file_uids": [str(result.uid)]})
    assert resp.status_code == 200
    assert _find_flat(resp.json()["data"], result.uid) is not None


@pytest.mark.asyncio
async def test_favorite_multiple_files_at_once(authed_client, project_task, user_id, generation_fks):
    """200 OK; a list of file_uids are favorited together in one call."""
    first = _make_result(project_task, user_id, generation_fks)
    second = _make_result(project_task, user_id, generation_fks)

    resp = await authed_client.call(
        "PATCH", _favorite_url(project_task.uid), json={"file_uids": [str(first.uid), str(second.uid)]}
    )
    assert resp.status_code == 200
    assert _find_flat(resp.json()["data"], first.uid) is not None
    assert _find_flat(resp.json()["data"], second.uid) is not None


@pytest.mark.asyncio
async def test_favorite_files_dedupes_repeated_uid(authed_client, project_task, user_id, generation_fks):
    """200 OK; a repeated uid in file_uids is silently deduped rather than double-processed."""
    result = _make_result(project_task, user_id, generation_fks)

    resp = await authed_client.call(
        "PATCH", _favorite_url(project_task.uid), json={"file_uids": [str(result.uid), str(result.uid)]}
    )
    assert resp.status_code == 200
    assert _find_flat(resp.json()["data"], result.uid) is not None


@pytest.mark.asyncio
async def test_favorite_archived_file_is_200(authed_client, project_task, user_id, generation_fks):
    """200 OK; archive/favorite are decoupled, so an archived item can be favorited directly and stays archived."""
    result = _make_result(project_task, user_id, generation_fks, archieved_at=datetime.now())

    resp = await authed_client.call("PATCH", _favorite_url(project_task.uid), json={"file_uids": [str(result.uid)]})
    assert resp.status_code == 200

    archived_resp = await authed_client.call("GET", _archived_url(project_task.uid))
    assert _find_flat(archived_resp.json()["data"], result.uid) is not None

    favourited_resp = await authed_client.call("GET", _favourited_url(project_task.uid))
    assert _find_flat(favourited_resp.json()["data"], result.uid) is not None


@pytest.mark.asyncio
async def test_favorite_files_partial_match_is_404_all_or_nothing(authed_client, project_task, user_id, generation_fks):
    """404 file_not_found; one bad uid in the list fails the whole batch, leaving the valid one untouched."""
    result = _make_result(project_task, user_id, generation_fks)

    resp = await authed_client.call(
        "PATCH",
        _favorite_url(project_task.uid),
        json={"file_uids": [str(result.uid), str(uuid4())]},
        raise_for_status=False,
    )
    assert resp.status_code == 404
    assert resp.json()["error"] == {"file_uids.1": [resolve_message("file_not_found", "en")]}


@pytest.mark.asyncio
async def test_unfavorite_file_removes_it_from_favourited(authed_client, project_task, user_id, generation_fks):
    """200 OK; is_favorited=false clears favourited_at, dropping the item from /favourited."""
    result = _make_result(project_task, user_id, generation_fks, favourited_at=datetime.now())

    resp = await authed_client.call(
        "PATCH", _favorite_url(project_task.uid), json={"file_uids": [str(result.uid)], "is_favorited": False}
    )
    assert resp.status_code == 200

    favourited_resp = await authed_client.call("GET", _favourited_url(project_task.uid))
    assert _find_flat(favourited_resp.json()["data"], result.uid) is None


@pytest.mark.asyncio
async def test_unfavorite_file_not_favourited_is_404(authed_client, project_task, user_id, generation_fks):
    """404 file_not_found; target uid isn't currently favourited."""
    result = _make_result(project_task, user_id, generation_fks, favourited_at=None)

    resp = await authed_client.call(
        "PATCH",
        _favorite_url(project_task.uid),
        json={"file_uids": [str(result.uid)], "is_favorited": False},
        raise_for_status=False,
    )
    assert resp.status_code == 404
    assert resp.json()["error"] == {"file_uids.0": [resolve_message("file_not_found", "en")]}
