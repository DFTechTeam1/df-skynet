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


def _archive_url(project_uid):
    return f"/api/files/{project_uid}/archieve"


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
    """Only a non-main result can be archived by `files_with_uid_to_set_archieve_files` (its DB
    update filters `is_main.is_(False)`), so every result here gets a hidden `is_main=True` parent."""
    parent_id = DfEngineGenerationResultsFactory.create(
        generation_id=_make_generation(project_task, user_id, generation_fks).id,
        created_by=int(user_id),
        is_main=True,
    ).id
    return DfEngineGenerationResultsFactory.create(
        generation_id=_make_generation(project_task, user_id, generation_fks).id,
        created_by=int(user_id),
        is_main=False,
        parent_id=parent_id,
        **overrides,
    )


def _find_flat(files, uid):
    return next((f for f in files if f["file_uid"] == str(uid)), None)


@pytest.mark.asyncio
async def test_archive_file_appears_in_archived_list(authed_client, project_task, user_id, generation_fks):
    """200 OK; default body (is_archieved=true) returns the updated archived list, and the file shows there."""
    result = _make_result(project_task, user_id, generation_fks)

    resp = await authed_client.call(
        "PATCH", _archive_url(project_task.project.uid), json={"file_uids": [str(result.uid)]}
    )
    assert resp.status_code == 200
    assert _find_flat(resp.json()["data"], result.uid) is not None

    archived_resp = await authed_client.call("GET", _archived_url(project_task.project.uid))
    assert _find_flat(archived_resp.json()["data"], result.uid) is not None


@pytest.mark.asyncio
async def test_archive_multiple_files_at_once(authed_client, project_task, user_id, generation_fks):
    """200 OK; a list of file_uids are archived together in one call."""
    first = _make_result(project_task, user_id, generation_fks)
    second = _make_result(project_task, user_id, generation_fks)

    resp = await authed_client.call(
        "PATCH", _archive_url(project_task.project.uid), json={"file_uids": [str(first.uid), str(second.uid)]}
    )
    assert resp.status_code == 200

    archived_resp = await authed_client.call("GET", _archived_url(project_task.project.uid))
    archived_uids = {f["file_uid"] for f in archived_resp.json()["data"]}
    assert {str(first.uid), str(second.uid)} <= archived_uids


@pytest.mark.asyncio
async def test_archive_files_dedupes_repeated_uid(authed_client, project_task, user_id, generation_fks):
    """200 OK; a repeated uid in file_uids is silently deduped rather than double-processed."""
    result = _make_result(project_task, user_id, generation_fks)

    resp = await authed_client.call(
        "PATCH", _archive_url(project_task.project.uid), json={"file_uids": [str(result.uid), str(result.uid)]}
    )
    assert resp.status_code == 200
    assert _find_flat(resp.json()["data"], result.uid) is not None


@pytest.mark.asyncio
async def test_archive_file_already_archived_is_404(authed_client, project_task, user_id, generation_fks):
    """404 file_not_found; already-archived uid is no longer in the archivable pool."""
    result = _make_result(project_task, user_id, generation_fks, archieved_at=datetime.now())

    resp = await authed_client.call(
        "PATCH", _archive_url(project_task.project.uid), json={"file_uids": [str(result.uid)]}, raise_for_status=False
    )
    assert resp.status_code == 404
    assert resp.json()["message"] == resolve_message("file_not_found", "en")
    assert resp.json()["error"] == {"file_uids.0": [resolve_message("file_not_found", "en")]}


@pytest.mark.asyncio
async def test_archive_favourited_file_is_200(authed_client, project_task, user_id, generation_fks):
    """200 OK; archive/favorite are decoupled, so a favourited item can be archived directly and stays favourited."""
    result = _make_result(project_task, user_id, generation_fks, favourited_at=datetime.now())

    resp = await authed_client.call(
        "PATCH", _archive_url(project_task.project.uid), json={"file_uids": [str(result.uid)]}
    )
    assert resp.status_code == 200

    archived_resp = await authed_client.call("GET", _archived_url(project_task.project.uid))
    assert _find_flat(archived_resp.json()["data"], result.uid) is not None

    favourited_resp = await authed_client.call("GET", _favourited_url(project_task.project.uid))
    assert _find_flat(favourited_resp.json()["data"], result.uid) is not None


@pytest.mark.asyncio
async def test_archive_files_partial_match_is_404_all_or_nothing(authed_client, project_task, user_id, generation_fks):
    """404 file_not_found; one bad uid in the list fails the whole batch, leaving the valid one untouched."""
    result = _make_result(project_task, user_id, generation_fks)

    resp = await authed_client.call(
        "PATCH",
        _archive_url(project_task.project.uid),
        json={"file_uids": [str(result.uid), str(uuid4())]},
        raise_for_status=False,
    )
    assert resp.status_code == 404
    assert resp.json()["error"] == {"file_uids.1": [resolve_message("file_not_found", "en")]}

    archived_resp = await authed_client.call("GET", _archived_url(project_task.project.uid))
    assert _find_flat(archived_resp.json()["data"], result.uid) is None


@pytest.mark.asyncio
async def test_unarchive_file_moves_it_from_archived_to_live(authed_client, project_task, user_id, generation_fks):
    """200 OK; is_archieved=false clears archieved_at, dropping the item from /archieved."""
    result = _make_result(project_task, user_id, generation_fks, archieved_at=datetime.now())

    resp = await authed_client.call(
        "PATCH", _archive_url(project_task.project.uid), json={"file_uids": [str(result.uid)], "is_archieved": False}
    )
    assert resp.status_code == 200

    archived_resp = await authed_client.call("GET", _archived_url(project_task.project.uid))
    assert _find_flat(archived_resp.json()["data"], result.uid) is None


@pytest.mark.asyncio
async def test_unarchive_file_unknown_uid_is_404(authed_client, project_task):
    """404 file_not_found; uid matches no generation result at all."""
    resp = await authed_client.call(
        "PATCH",
        _archive_url(project_task.project.uid),
        json={"file_uids": [str(uuid4())], "is_archieved": False},
        raise_for_status=False,
    )
    assert resp.status_code == 404
    assert resp.json()["error"] == {"file_uids.0": [resolve_message("file_not_found", "en")]}
