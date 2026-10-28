from datetime import datetime
from uuid import uuid4
import pytest
import pytest_asyncio
from middlewares.lang import resolve_message
from services.mysql.factory.df_engine_generations import DfEngineGenerationsFactory
from services.mysql.factory.df_engine_generation_favourites import DfEngineGenerationFavouritesFactory
from services.mysql.factory.df_engine_generation_results import DfEngineGenerationResultsFactory
from services.mysql.factory.df_engine_model_options import DfEngineModelOptionsFactory
from services.mysql.factory.df_engine_menus import DfEngineMenusFactory
from services.mysql.factory.df_engine_features import DfEngineFeaturesFactory

ARCHIVED_URL = "/api/files/archieves"
FAVOURITES_URL = "/api/files/favorites"


def _archive_url(file_uid):
    return f"/api/files/archieve/{file_uid}"


@pytest_asyncio.fixture
async def generation_fks(user_id) -> dict:
    """Self-contained model_option/menu/feature ids for df_engine_generations' NOT NULL FKs."""
    model_option = DfEngineModelOptionsFactory.create()
    menu = DfEngineMenusFactory.create(created_by=int(user_id), df_engine_menu_feature_mapping=None)
    feature = DfEngineFeaturesFactory.create(created_by=int(user_id), df_engine_feature_prompt_mapping=None)
    return {"model_id": model_option.id, "menu_id": menu.id, "feature_id": feature.id}


def _make_generation(project_task, owner_id, generation_fks):
    return DfEngineGenerationsFactory.create(
        project_id=project_task.project_id,
        task_id=project_task.id,
        created_by=int(owner_id),
        sourceable_id=1,
        **generation_fks,
    )


def _make_result(project_task, owner_id, generation_fks, **overrides):
    """A non-main result under a hidden main parent (a main version can never be archived)."""
    parent = DfEngineGenerationResultsFactory.create(
        generation_id=_make_generation(project_task, owner_id, generation_fks).id,
        created_by=int(owner_id),
        is_main=True,
    )
    return DfEngineGenerationResultsFactory.create(
        generation_id=_make_generation(project_task, owner_id, generation_fks).id,
        created_by=int(owner_id),
        is_main=False,
        parent_id=parent.id,
        **overrides,
    )


def _find_flat(files, uid):
    return next((f for f in files if f["file_uid"] == str(uid)), None)


@pytest.mark.asyncio
async def test_archive_file_appears_in_archived_list(authed_client, project_task, user_id, generation_fks):
    """200 OK; the creator archives a file (default body) and it shows in /files/archieves."""
    result = _make_result(project_task, user_id, generation_fks)
    await authed_client.call("GET", ARCHIVED_URL)  # warm the cache: archiving must invalidate it

    resp = await authed_client.call("POST", _archive_url(result.uid), json={})
    assert resp.status_code == 200
    archived = await authed_client.call("GET", ARCHIVED_URL)
    assert _find_flat(archived.json()["data"], result.uid) is not None


@pytest.mark.asyncio
async def test_unarchive_file_drops_it_from_archived_list(authed_client, project_task, user_id, generation_fks):
    """200 OK; is_archieved=false clears archieved_at, dropping the file from /files/archieves."""
    result = _make_result(project_task, user_id, generation_fks, archieved_at=datetime.now())
    await authed_client.call("GET", ARCHIVED_URL)

    resp = await authed_client.call("POST", _archive_url(result.uid), json={"is_archieved": False})
    assert resp.status_code == 200
    archived = await authed_client.call("GET", ARCHIVED_URL)
    assert _find_flat(archived.json()["data"], result.uid) is None


@pytest.mark.asyncio
async def test_archive_already_archived_is_404(authed_client, project_task, user_id, generation_fks):
    """404 file_not_found; archiving an already archived file."""
    result = _make_result(project_task, user_id, generation_fks, archieved_at=datetime.now())
    resp = await authed_client.call("POST", _archive_url(result.uid), json={}, raise_for_status=False)
    assert resp.status_code == 404
    assert resp.json()["error"] == {"file_uid": [resolve_message("file_not_found", "en")]}


@pytest.mark.asyncio
async def test_unarchive_not_archived_is_404(authed_client, project_task, user_id, generation_fks):
    """404 file_not_found; unarchiving a file that is not archived."""
    result = _make_result(project_task, user_id, generation_fks)
    resp = await authed_client.call(
        "POST", _archive_url(result.uid), json={"is_archieved": False}, raise_for_status=False
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_archive_unknown_uid_is_404(authed_client):
    """404 file_not_found; uid matches no generation result."""
    resp = await authed_client.call("POST", _archive_url(uuid4()), json={}, raise_for_status=False)
    assert resp.status_code == 404
    assert resp.json()["message"] == resolve_message("file_not_found", "en")


@pytest.mark.asyncio
@pytest.mark.parametrize("roles", [["staff"], ["director"], ["root"]])
async def test_archive_someone_elses_file_is_404_even_with_override_role(
    authed_client, project_task, other_user_id, generation_fks, as_roles, roles
):
    """403 file_archive_not_creator; only the creator can archive, an override role cannot overrule it."""
    as_roles(roles)
    result = _make_result(project_task, other_user_id, generation_fks)
    resp = await authed_client.call("POST", _archive_url(result.uid), json={}, raise_for_status=False)
    assert resp.status_code == 403
    assert resp.json()["message"] == resolve_message("file_archive_not_creator", "en")
    assert resp.json()["error"] == {"file_uid": [resolve_message("file_archive_not_creator", "en")]}

    archived_resp = await authed_client.call("GET", ARCHIVED_URL)
    assert _find_flat(archived_resp.json()["data"], result.uid) is None


@pytest.mark.asyncio
async def test_unarchive_someone_elses_file_is_404_even_with_override_role(
    authed_client, project_task, other_user_id, generation_fks, as_roles
):
    """403 file_archive_not_creator; an override role cannot unarchive another creator's file either."""
    as_roles(["director"])
    result = _make_result(project_task, other_user_id, generation_fks, archieved_at=datetime.now())
    resp = await authed_client.call(
        "POST", _archive_url(result.uid), json={"is_archieved": False}, raise_for_status=False
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_archive_main_file_is_422(authed_client, project_task, user_id, generation_fks):
    """422 file_archive_not_permitted; a main version can never be archived, even by its creator."""
    main = DfEngineGenerationResultsFactory.create(
        generation_id=_make_generation(project_task, user_id, generation_fks).id,
        created_by=int(user_id),
        is_main=True,
    )
    resp = await authed_client.call("POST", _archive_url(main.uid), json={}, raise_for_status=False)
    assert resp.status_code == 422
    assert resp.json()["error"] == {"file_uid": [resolve_message("file_archive_not_permitted", "en")]}


@pytest.mark.asyncio
async def test_archive_favourited_file_stays_favourited(authed_client, project_task, user_id, generation_fks):
    """200 OK; archive/favourite are decoupled, an archived favourite is in both lists."""
    result = _make_result(project_task, user_id, generation_fks)
    DfEngineGenerationFavouritesFactory.create(user_id=int(user_id), result_id=result.id)

    resp = await authed_client.call("POST", _archive_url(result.uid), json={})
    assert resp.status_code == 200
    assert _find_flat((await authed_client.call("GET", ARCHIVED_URL)).json()["data"], result.uid) is not None
    favourited = await authed_client.call("GET", FAVOURITES_URL, params={"task_id": project_task.id})
    assert _find_flat(favourited.json()["data"], result.uid) is not None
