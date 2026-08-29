import pytest
from uuid import uuid4
from middlewares.lang import resolve_message
from services.mysql.factory.df_engine_model_options import DfEngineModelOptionsFactory
from services.redis import client as redis_client, CacheKeys

URL = "/api/models"


@pytest.mark.asyncio
async def test_enable_disabled_available_model(authed_client):
    """200 OK; enabling an available, disabled model flips is_enabled true."""
    row = DfEngineModelOptionsFactory.create(type="text", is_available=True, is_enabled=False, is_main=False)

    resp = await authed_client.call("PATCH", f"{URL}/{row.uid}", json={"is_enabled": True})
    assert resp.status_code == 200
    assert resp.json()["data"]["is_enabled"] is True
    assert resp.json()["data"]["is_main"] is False


@pytest.mark.asyncio
async def test_disable_enabled_model(authed_client):
    """200 OK; disabling an enabled, non-main model just flips is_enabled false."""
    row = DfEngineModelOptionsFactory.create(type="text", is_available=True, is_enabled=True, is_main=False)

    resp = await authed_client.call("PATCH", f"{URL}/{row.uid}", json={"is_enabled": False})
    assert resp.status_code == 200
    assert resp.json()["data"]["is_enabled"] is False
    assert resp.json()["data"]["is_main"] is False


@pytest.mark.asyncio
async def test_disabling_main_model_is_rejected(authed_client):
    """422 model_option_main_cannot_be_disabled; a model holding is_main can't be
    disabled through this endpoint — another model must be made main first."""
    row = DfEngineModelOptionsFactory.create(type="text", is_available=True, is_enabled=True, is_main=True)

    resp = await authed_client.call("PATCH", f"{URL}/{row.uid}", json={"is_enabled": False}, raise_for_status=False)
    assert resp.status_code == 422
    assert resp.json()["message"] == resolve_message("model_option_main_cannot_be_disabled", "en")


@pytest.mark.asyncio
@pytest.mark.parametrize("target_state", [True, False], ids=["enable", "disable"])
async def test_set_enabled_rejected_when_unavailable(authed_client, target_state):
    """422 model_option_unavailable_cannot_set_enabled; neither direction is allowed once is_available=False."""
    row = DfEngineModelOptionsFactory.create(type="text", is_available=False, is_enabled=False, is_main=False)

    resp = await authed_client.call(
        "PATCH", f"{URL}/{row.uid}", json={"is_enabled": target_state}, raise_for_status=False
    )
    assert resp.status_code == 422
    assert resp.json()["message"] == resolve_message("model_option_unavailable_cannot_set_enabled", "en")


@pytest.mark.asyncio
async def test_set_enabled_unknown_uid_is_404(authed_client):
    """404 model_option_not_found when the path uid matches no row."""
    resp = await authed_client.call("PATCH", f"{URL}/{uuid4()}", json={"is_enabled": True}, raise_for_status=False)
    assert resp.status_code == 404
    assert resp.json()["message"] == resolve_message("model_option_not_found", "en")


@pytest.mark.asyncio
async def test_set_enabled_missing_body_is_a_validation_error(authed_client):
    """422 when the required `is_enabled` field is omitted from the body."""
    row = DfEngineModelOptionsFactory.create(type="text", is_available=True, is_enabled=False, is_main=False)
    resp = await authed_client.call("PATCH", f"{URL}/{row.uid}", json={}, raise_for_status=False)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_requires_auth(client):
    """401 when the request carries no bearer token."""
    row = DfEngineModelOptionsFactory.create(type="text", is_available=True, is_enabled=False, is_main=False)
    resp = await client.call("PATCH", f"{URL}/{row.uid}", json={"is_enabled": True}, raise_for_status=False)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_set_enabled_invalidates_the_list_cache(authed_client):
    """200 OK; a PATCH clears the list cache so a subsequent GET reflects the change, not the stale cache."""
    prefix = f"Cache{uuid4().hex[:8]}"
    row = DfEngineModelOptionsFactory.create(
        name=prefix, type="text", is_available=True, is_enabled=False, is_main=False
    )
    redis = redis_client()

    await authed_client.call("GET", "/api/models", params={"search": prefix})
    key = CacheKeys().model_pagination(1, 500, prefix, None, None)
    assert await redis.exists(key)

    await authed_client.call("PATCH", f"{URL}/{row.uid}", json={"is_enabled": True})

    resp = await authed_client.call("GET", "/api/models", params={"search": prefix})
    item = next(i for i in resp.json()["data"]["paginated"] if i["name"] == prefix)
    assert item["is_enabled"] is True
