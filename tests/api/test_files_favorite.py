from datetime import datetime
from uuid import uuid4
import pytest
import pytest_asyncio
from sqlalchemy import select
from middlewares.lang import resolve_message
from services.mysql.factory.df_engine_generations import DfEngineGenerationsFactory
from services.mysql.factory.df_engine_generation_favourites import DfEngineGenerationFavouritesFactory
from services.mysql.factory.df_engine_generation_results import DfEngineGenerationResultsFactory
from services.mysql.factory.df_engine_model_options import DfEngineModelOptionsFactory
from services.mysql.factory.df_engine_menus import DfEngineMenusFactory
from services.mysql.factory.df_engine_features import DfEngineFeaturesFactory
from services.mysql.model import DfEngineGenerationFavourites


def _favorite_url(file_uid):
    return f"/api/files/favorite/{file_uid}"


FAVOURITES_URL = "/api/files/favorites"


def _archived_url(task_uid):
    return "/api/files/archieves"


@pytest_asyncio.fixture
async def generation_fks(user_id) -> dict:
    model_option = DfEngineModelOptionsFactory.create()
    menu = DfEngineMenusFactory.create(created_by=int(user_id), df_engine_menu_feature_mapping=None)
    feature = DfEngineFeaturesFactory.create(created_by=int(user_id), df_engine_feature_prompt_mapping=None)
    return {"model_id": model_option.id, "menu_id": menu.id, "feature_id": feature.id}


def _make_result(project_task, owner_id, generation_fks, **overrides):
    generation = DfEngineGenerationsFactory.create(
        project_id=project_task.project_id,
        task_id=project_task.id,
        created_by=int(owner_id),
        sourceable_id=1,
        **generation_fks,
    )
    return DfEngineGenerationResultsFactory.create(generation_id=generation.id, created_by=int(owner_id), **overrides)


def _find_flat(files, uid):
    return next((f for f in files if f["file_uid"] == str(uid)), None)


async def _rows(db_session, result_id):
    await db_session.commit()
    return (
        (
            await db_session.execute(
                select(DfEngineGenerationFavourites).where(DfEngineGenerationFavourites.result_id == result_id)
            )
        )
        .scalars()
        .all()
    )


@pytest.mark.asyncio
async def test_favorite_own_file(authed_client, project_task, user_id, generation_fks, db_session):
    """200 OK; favouriting inserts one (user, result) row and the file shows in /favourited."""
    result = _make_result(project_task, user_id, generation_fks)

    resp = await authed_client.call("POST", _favorite_url(result.uid), json={})
    assert resp.status_code == 200

    rows = await _rows(db_session, result.id)
    assert [r.user_id for r in rows] == [int(user_id)]
    listed = await authed_client.call("GET", FAVOURITES_URL, params={"task_id": project_task.id})
    assert _find_flat(listed.json()["data"], result.uid) is not None


@pytest.mark.asyncio
async def test_favorite_someone_elses_file(authed_client, project_task, user_id, other_user_id, generation_fks):
    """200 OK; any user can favourite another user's file (no owner/override check)."""
    result = _make_result(project_task, other_user_id, generation_fks)

    resp = await authed_client.call("POST", _favorite_url(result.uid), json={"is_favorited": True})
    assert resp.status_code == 200
    listed = await authed_client.call("GET", FAVOURITES_URL, params={"task_id": project_task.id})
    assert _find_flat(listed.json()["data"], result.uid) is not None


@pytest.mark.asyncio
async def test_favorite_flips_action_flags_for_the_viewer_only(
    authed_client, project_task, user_id, other_user_id, generation_fks
):
    """200 OK; another user's favourite doesn't change this viewer's flags; their own does (file detail + gallery list)."""
    result = _make_result(project_task, other_user_id, generation_fks)
    DfEngineGenerationFavouritesFactory.create(user_id=int(other_user_id), result_id=result.id)
    detail_url = f"/api/user-galleries/generated/{result.uid}"

    before = (await authed_client.call("GET", detail_url)).json()["data"]
    assert before["favourited_at"] is None
    assert before["action"]["can_set_favorite"] is True

    await authed_client.call("POST", _favorite_url(result.uid), json={})
    after = (await authed_client.call("GET", detail_url)).json()["data"]
    assert after["favourited_at"] is not None
    assert after["action"]["can_set_favorite"] is False

    gallery = (await authed_client.call("GET", f"/api/user-galleries/{project_task.uid}")).json()["data"]
    listed = _find_flat(gallery, result.uid)
    assert listed["favourited_at"] is not None and listed["action"]["can_set_favorite"] is False


@pytest.mark.asyncio
async def test_unfavorite_removes_row_and_list_entry(authed_client, project_task, user_id, generation_fks, db_session):
    """200 OK; is_favorited=false deletes the row and drops the file from /favourited."""
    result = _make_result(project_task, user_id, generation_fks)
    DfEngineGenerationFavouritesFactory.create(user_id=int(user_id), result_id=result.id)

    resp = await authed_client.call("POST", _favorite_url(result.uid), json={"is_favorited": False})
    assert resp.status_code == 200
    assert await _rows(db_session, result.id) == []
    listed = await authed_client.call("GET", FAVOURITES_URL, params={"task_id": project_task.id})
    assert _find_flat(listed.json()["data"], result.uid) is None


@pytest.mark.asyncio
async def test_unfavorite_keeps_other_users_favourite(
    authed_client, project_task, user_id, other_user_id, generation_fks, db_session
):
    """200 OK; removing my favourite leaves another user's row intact."""
    result = _make_result(project_task, user_id, generation_fks)
    DfEngineGenerationFavouritesFactory.create(user_id=int(user_id), result_id=result.id)
    DfEngineGenerationFavouritesFactory.create(user_id=int(other_user_id), result_id=result.id)

    await authed_client.call("POST", _favorite_url(result.uid), json={"is_favorited": False})
    assert [r.user_id for r in await _rows(db_session, result.id)] == [int(other_user_id)]


@pytest.mark.asyncio
async def test_favorite_already_favourited_is_422(authed_client, project_task, user_id, generation_fks):
    """422 file_already_favourited; favouriting twice is rejected."""
    result = _make_result(project_task, user_id, generation_fks)
    DfEngineGenerationFavouritesFactory.create(user_id=int(user_id), result_id=result.id)

    resp = await authed_client.call("POST", _favorite_url(result.uid), json={}, raise_for_status=False)
    assert resp.status_code == 422
    assert resp.json()["error"] == {"file_uid": [resolve_message("file_already_favourited", "en")]}


@pytest.mark.asyncio
async def test_unfavorite_not_favourited_is_422(authed_client, project_task, user_id, generation_fks):
    """422 file_not_favourited; removing a favourite that isn't there is rejected."""
    result = _make_result(project_task, user_id, generation_fks)

    resp = await authed_client.call(
        "POST", _favorite_url(result.uid), json={"is_favorited": False}, raise_for_status=False
    )
    assert resp.status_code == 422
    assert resp.json()["error"] == {"file_uid": [resolve_message("file_not_favourited", "en")]}


@pytest.mark.asyncio
async def test_favorite_unknown_file_is_404(authed_client):
    """404 file_not_found; uid doesn't match any generated file."""
    resp = await authed_client.call("POST", _favorite_url(uuid4()), json={}, raise_for_status=False)
    assert resp.status_code == 404
    assert resp.json()["error"] == {"file_uid": [resolve_message("file_not_found", "en")]}


@pytest.mark.asyncio
async def test_favorite_archived_file_is_200(authed_client, project_task, user_id, generation_fks):
    """200 OK; archive/favourite are decoupled, an archived file can be favourited and stays archived."""
    result = _make_result(project_task, user_id, generation_fks, archieved_at=datetime.now())

    resp = await authed_client.call("POST", _favorite_url(result.uid), json={})
    assert resp.status_code == 200
    archived = await authed_client.call("GET", _archived_url(project_task.uid))
    assert _find_flat(archived.json()["data"], result.uid) is not None


@pytest.mark.asyncio
async def test_favorite_invalid_uid_is_422(authed_client):
    """422; a non-UUID path param is rejected by validation."""
    resp = await authed_client.call("POST", "/api/files/favorite/not-a-uuid", json={}, raise_for_status=False)
    assert resp.status_code == 422
