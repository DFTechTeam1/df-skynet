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


def _archive_url(task_uid):
    return f"/api/files/{task_uid}/archieve"


def _archived_url(task_uid):
    return f"/api/files/{task_uid}/archieved"


@pytest_asyncio.fixture
async def generation_fks(user_id) -> dict:
    """Self-contained model_option/menu/feature ids for df_engine_generations' NOT NULL FKs —
    created via factories rather than assumed to pre-exist, so this works on a fresh, empty DB too."""
    model_option = DfEngineModelOptionsFactory.create()
    menu = DfEngineMenusFactory.create(created_by=int(user_id), df_engine_menu_feature_mapping=None)
    feature = DfEngineFeaturesFactory.create(created_by=int(user_id), df_engine_feature_prompt_mapping=None)
    return {"model_id": model_option.id, "menu_id": menu.id, "feature_id": feature.id}


def _make_result(
    project_task, user_id, generation_fks, archieved_at=None, name="a.png", kind="images", is_favourite=False
):
    """A `DfEngineGenerationResults` row (with its parent `DfEngineGenerations`) shaped
    so `FilesService.base_of`/`type_root_of` recognize it, mirroring the upload-file helper."""
    generation = DfEngineGenerationsFactory.create(
        project_id=project_task.project_id,
        task_id=project_task.id,
        created_by=int(user_id),
        sourceable_id=1,
        **generation_fks,
    )
    path = f"storage/DF-Engine/{project_task.project.uid}/generated/{kind}/{name}"
    return DfEngineGenerationResultsFactory.create(
        path=path,
        generation_id=generation.id,
        created_by=int(user_id),
        archieved_at=archieved_at,
        is_favourite=is_favourite,
    )


def _find_flat(files, uid):
    return next((f for f in files if f["uid"] == uid), None)


def _find_file_node(nodes, uid):
    for node in nodes:
        found = next((f for f in node["files"] if f["uid"] == uid), None)
        if found is not None:
            return found
        found = _find_file_node(node["childs"], uid)
        if found is not None:
            return found
    return None


@pytest.mark.asyncio
async def test_archive_file_moves_it_from_live_to_archived(authed_client, project_task, user_id, generation_fks):
    """200 OK; default body (is_archieved=true) drops the result from the returned live tree and adds it to /archieved."""
    result = _make_result(project_task, user_id, generation_fks)

    resp = await authed_client.call("PATCH", _archive_url(project_task.uid), json={"file_uids": [str(result.uid)]})
    assert resp.status_code == 200
    assert _find_file_node(resp.json()["data"], result.uid) is None

    archived_resp = await authed_client.call("GET", _archived_url(project_task.uid))
    assert _find_flat(archived_resp.json()["data"], result.uid) is not None


@pytest.mark.asyncio
async def test_archive_multiple_files_at_once(authed_client, project_task, user_id, generation_fks):
    """200 OK; a list of file_uids are archived together in one call."""
    first = _make_result(project_task, user_id, generation_fks)
    second = _make_result(project_task, user_id, generation_fks)

    resp = await authed_client.call(
        "PATCH", _archive_url(project_task.uid), json={"file_uids": [str(first.uid), str(second.uid)]}
    )
    assert resp.status_code == 200
    assert _find_file_node(resp.json()["data"], first.uid) is None
    assert _find_file_node(resp.json()["data"], second.uid) is None

    archived_resp = await authed_client.call("GET", _archived_url(project_task.uid))
    archived_uids = {f["uid"] for f in archived_resp.json()["data"]}
    assert {str(first.uid), str(second.uid)} <= archived_uids


@pytest.mark.asyncio
async def test_archive_files_dedupes_repeated_uid(authed_client, project_task, user_id, generation_fks):
    """200 OK; a repeated uid in file_uids is silently deduped rather than double-processed."""
    result = _make_result(project_task, user_id, generation_fks)

    resp = await authed_client.call(
        "PATCH", _archive_url(project_task.uid), json={"file_uids": [str(result.uid), str(result.uid)]}
    )
    assert resp.status_code == 200
    assert _find_file_node(resp.json()["data"], result.uid) is None


@pytest.mark.asyncio
async def test_archive_file_already_archived_is_422(authed_client, project_task, user_id, generation_fks):
    """422 file_uids_invalid; target uid is already archived, reported at its own index."""
    result = _make_result(project_task, user_id, generation_fks, archieved_at=datetime.now())

    resp = await authed_client.call(
        "PATCH", _archive_url(project_task.uid), json={"file_uids": [str(result.uid)]}, raise_for_status=False
    )
    assert resp.status_code == 422
    assert resp.json()["message"] == resolve_message("file_uids_invalid", "en")
    assert resp.json()["error"] == {"file_uids.0": [resolve_message("file_already_archived", "en")]}


@pytest.mark.asyncio
async def test_archive_favourited_file_is_200(authed_client, project_task, user_id, generation_fks):
    """200 OK; archive/favorite are decoupled, so a favourited item can be archived directly."""
    result = _make_result(project_task, user_id, generation_fks, is_favourite=True)

    resp = await authed_client.call("PATCH", _archive_url(project_task.uid), json={"file_uids": [str(result.uid)]})
    assert resp.status_code == 200
    assert _find_file_node(resp.json()["data"], result.uid) is None

    archived_resp = await authed_client.call("GET", _archived_url(project_task.uid))
    assert _find_flat(archived_resp.json()["data"], result.uid) is not None

    favourited_resp = await authed_client.call("GET", "/api/files/" + str(project_task.uid) + "/favourited")
    assert _find_flat(favourited_resp.json()["data"], result.uid) is not None


@pytest.mark.asyncio
async def test_archive_files_partial_match_is_422_all_or_nothing(authed_client, project_task, user_id, generation_fks):
    """422 file_uids_invalid; one bad uid in the list fails the whole batch, leaving the valid one untouched."""
    result = _make_result(project_task, user_id, generation_fks)

    resp = await authed_client.call(
        "PATCH",
        _archive_url(project_task.uid),
        json={"file_uids": [str(result.uid), str(uuid4())]},
        raise_for_status=False,
    )
    assert resp.status_code == 422
    assert resp.json()["error"] == {"file_uids.1": [resolve_message("file_not_found", "en")]}

    archived_resp = await authed_client.call("GET", _archived_url(project_task.uid))
    assert _find_flat(archived_resp.json()["data"], result.uid) is None


@pytest.mark.asyncio
async def test_unarchive_file_moves_it_from_archived_to_live(authed_client, project_task, user_id, generation_fks):
    """200 OK; is_archieved=false returns the live tree with the item back in it, and drops it from /archieved."""
    result = _make_result(project_task, user_id, generation_fks, archieved_at=datetime.now())

    resp = await authed_client.call(
        "PATCH", _archive_url(project_task.uid), json={"file_uids": [str(result.uid)], "is_archieved": False}
    )
    assert resp.status_code == 200
    assert _find_file_node(resp.json()["data"], result.uid) is not None

    archived_resp = await authed_client.call("GET", _archived_url(project_task.uid))
    assert _find_flat(archived_resp.json()["data"], result.uid) is None


@pytest.mark.asyncio
async def test_unarchive_file_not_archived_is_422(authed_client, project_task, user_id, generation_fks):
    """422 file_uids_invalid; target uid isn't currently archived."""
    result = _make_result(project_task, user_id, generation_fks, archieved_at=None)

    resp = await authed_client.call(
        "PATCH",
        _archive_url(project_task.uid),
        json={"file_uids": [str(result.uid)], "is_archieved": False},
        raise_for_status=False,
    )
    assert resp.status_code == 422
    assert resp.json()["error"] == {"file_uids.0": [resolve_message("file_not_archived", "en")]}


@pytest.mark.asyncio
async def test_unarchive_file_unknown_uid_is_422(authed_client, project_task):
    """422 file_uids_invalid; uid matches no generation result at all."""
    resp = await authed_client.call(
        "PATCH",
        _archive_url(project_task.uid),
        json={"file_uids": [str(uuid4())], "is_archieved": False},
        raise_for_status=False,
    )
    assert resp.status_code == 422
    assert resp.json()["error"] == {"file_uids.0": [resolve_message("file_not_found", "en")]}
