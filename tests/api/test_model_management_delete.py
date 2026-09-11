import pytest
from uuid import uuid4
from sqlalchemy import select
from middlewares.lang import resolve_message
from services.mysql.model import DfEngineModelOptions
from services.mysql.factory.df_engine_model_options import DfEngineModelOptionsFactory
from services.redis import client as redis_client, CacheKeys

URL = "/api/models"


def _deletable(**overrides):
    """A model in the only state a delete is allowed from: available, disabled,
    not main, not already deleted."""
    base = dict(type="text", is_available=True, is_enabled=False, is_main=False, deleted_at=None, deleted_by=None)
    base.update(overrides)
    return DfEngineModelOptionsFactory.create(**base)


@pytest.mark.asyncio
async def test_delete_soft_deletes_a_deletable_model(authed_client, db_session, user_id):
    """200 OK; DELETE stamps deleted_at/deleted_by and the row drops out of the default list."""
    row = _deletable(name=f"Del{uuid4().hex[:8]}")

    resp = await authed_client.call("DELETE", f"{URL}/{row.uid}")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["deleted_at"] is not None
    assert data["action"]["can_delete"] is False
    assert data["action"]["can_recover"] is True

    await db_session.rollback()
    fresh = (
        await db_session.execute(select(DfEngineModelOptions).where(DfEngineModelOptions.id == row.id))
    ).scalar_one()
    assert fresh.deleted_at is not None
    assert fresh.deleted_by == int(user_id)

    # gone from the default view
    listed = await authed_client.call("GET", URL, params={"search": row.name})
    assert listed.json()["data"]["paginated"] == []


@pytest.mark.asyncio
async def test_delete_rejected_when_enabled(authed_client):
    """422 model_option_active_cannot_be_deleted; an enabled (non-main) model can't be deleted."""
    row = _deletable(is_enabled=True, is_main=False)
    resp = await authed_client.call("DELETE", f"{URL}/{row.uid}", raise_for_status=False)
    assert resp.status_code == 422
    assert resp.json()["message"] == resolve_message("model_option_active_cannot_be_deleted", "en")


@pytest.mark.asyncio
async def test_delete_rejected_when_main(authed_client):
    """422 model_option_main_cannot_be_deleted; the main model can't be deleted
    (checked before the enabled guard, since main implies enabled)."""
    row = _deletable(is_enabled=True, is_main=True)
    resp = await authed_client.call("DELETE", f"{URL}/{row.uid}", raise_for_status=False)
    assert resp.status_code == 422
    assert resp.json()["message"] == resolve_message("model_option_main_cannot_be_deleted", "en")


@pytest.mark.asyncio
async def test_delete_rejected_when_unavailable(authed_client):
    """422 model_option_unavailable_cannot_be_deleted; a model already gone from OpenRouter can't be deleted."""
    row = _deletable(is_available=False)
    resp = await authed_client.call("DELETE", f"{URL}/{row.uid}", raise_for_status=False)
    assert resp.status_code == 422
    assert resp.json()["message"] == resolve_message("model_option_unavailable_cannot_be_deleted", "en")


@pytest.mark.asyncio
async def test_delete_rejected_when_already_deleted(authed_client):
    """422 model_option_already_deleted on a second delete."""
    from utils import local_time

    row = _deletable(deleted_at=local_time())
    resp = await authed_client.call("DELETE", f"{URL}/{row.uid}", raise_for_status=False)
    assert resp.status_code == 422
    assert resp.json()["message"] == resolve_message("model_option_already_deleted", "en")


@pytest.mark.asyncio
async def test_delete_unknown_uid_is_404(authed_client):
    resp = await authed_client.call("DELETE", f"{URL}/{uuid4()}", raise_for_status=False)
    assert resp.status_code == 404
    assert resp.json()["message"] == resolve_message("model_option_not_found", "en")


@pytest.mark.asyncio
async def test_delete_requires_auth(client):
    row = _deletable()
    resp = await client.call("DELETE", f"{URL}/{row.uid}", raise_for_status=False)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_recover_undoes_a_delete(authed_client, db_session):
    """200 OK; recover clears deleted_at/deleted_by and the model is listable again."""
    from utils import local_time

    row = _deletable(name=f"Rec{uuid4().hex[:8]}", deleted_at=local_time(), deleted_by=1)

    resp = await authed_client.call("PATCH", f"{URL}/{row.uid}/recover")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["deleted_at"] is None
    assert data["action"]["can_recover"] is False
    assert data["action"]["can_delete"] is True

    await db_session.rollback()
    fresh = (
        await db_session.execute(select(DfEngineModelOptions).where(DfEngineModelOptions.id == row.id))
    ).scalar_one()
    assert fresh.deleted_at is None
    assert fresh.deleted_by is None

    listed = await authed_client.call("GET", URL, params={"search": row.name})
    names = [i["name"] for i in listed.json()["data"]["paginated"]]
    assert row.name in names


@pytest.mark.asyncio
async def test_recover_rejected_when_not_deleted(authed_client):
    """422 model_option_not_deleted; recover only applies to a soft-deleted model."""
    row = _deletable()
    resp = await authed_client.call("PATCH", f"{URL}/{row.uid}/recover", raise_for_status=False)
    assert resp.status_code == 422
    assert resp.json()["message"] == resolve_message("model_option_not_deleted", "en")


@pytest.mark.asyncio
async def test_recover_unknown_uid_is_404(authed_client):
    resp = await authed_client.call("PATCH", f"{URL}/{uuid4()}/recover", raise_for_status=False)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_is_deleted_filter_lists_only_deleted_models(authed_client):
    """200 OK; is_deleted=true returns soft-deleted rows still available, the default view hides them."""
    from utils import local_time

    prefix = f"Filter{uuid4().hex[:8]}"
    live = _deletable(name=f"{prefix}-live")
    gone = _deletable(name=f"{prefix}-gone", deleted_at=local_time())

    default_view = await authed_client.call("GET", URL, params={"search": prefix})
    names = [i["name"] for i in default_view.json()["data"]["paginated"]]
    assert live.name in names
    assert gone.name not in names

    deleted_view = await authed_client.call("GET", URL, params={"search": prefix, "is_deleted": True})
    d_names = [i["name"] for i in deleted_view.json()["data"]["paginated"]]
    assert gone.name in d_names
    assert live.name not in d_names
    item = next(i for i in deleted_view.json()["data"]["paginated"] if i["name"] == gone.name)
    assert item["action"]["can_recover"] is True
    assert item["action"]["can_delete"] is False


@pytest.mark.asyncio
async def test_delete_invalidates_the_list_cache(authed_client):
    """200 OK; DELETE clears the model list cache so a later GET reflects the removal."""
    prefix = f"Cache{uuid4().hex[:8]}"
    row = _deletable(name=prefix)
    redis = redis_client()

    await authed_client.call("GET", URL, params={"search": prefix})
    key = CacheKeys().model_pagination(1, 500, prefix, None, None)
    assert await redis.exists(key)

    await authed_client.call("DELETE", f"{URL}/{row.uid}")

    resp = await authed_client.call("GET", URL, params={"search": prefix})
    assert resp.json()["data"]["paginated"] == []
