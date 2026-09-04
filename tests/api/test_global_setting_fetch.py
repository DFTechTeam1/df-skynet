import pytest
from services.redis import client as redis_client, CacheKeys
from services.mysql.factory.df_engine_model_options import DfEngineModelOptionsFactory
from tests.helpers import clear_setting_state

URL = "/api/setting"
cache_key = CacheKeys()


@pytest.mark.asyncio
async def test_fetch_returns_empty_when_nothing_saved_yet(authed_client, db_session):
    """200 OK; with no `admin_setting` rows the global settings document is empty."""
    await clear_setting_state(db_session)

    resp = await authed_client.call("GET", URL)
    assert resp.status_code == 200
    assert resp.json()["data"] == {}


@pytest.mark.asyncio
async def test_fetch_returns_saved_values(authed_client, db_session, project_class_id):
    """200 OK; GET reflects whatever was last saved via POST."""
    await clear_setting_state(db_session)
    await authed_client.call(
        "POST",
        URL,
        json={
            "admin_view": {"see_all_asset": False},
            "project_class_limitations": [{"id": project_class_id, "token_usage_limit": 25}],
        },
    )

    body = (await authed_client.call("GET", URL)).json()["data"]
    assert body["admin_view"] == {"see_all_asset": False}
    saved = next(row for row in body["project_class_limitations"] if row["id"] == project_class_id)
    assert saved["token_usage_limit"] == 25


@pytest.mark.asyncio
async def test_fetch_lists_every_project_class(authed_client, db_session, project_class_id):
    """200 OK; the saved document always carries one entry per project class, each
    with its name and colour, even when only one class was sent."""
    await clear_setting_state(db_session)
    await authed_client.call(
        "POST", URL, json={"project_class_limitations": [{"id": project_class_id, "token_usage_limit": 3}]}
    )

    rows = (await authed_client.call("GET", URL)).json()["data"]["project_class_limitations"]
    assert len(rows) >= 2
    assert all({"id", "name", "color", "token_usage_limit"} <= set(row) for row in rows)


@pytest.mark.asyncio
async def test_fetch_returns_enhancer_and_assistant_model_name(authed_client, db_session):
    """200 OK; enhancer_model/assistant_model come back as the model name, not a bare UID."""
    await clear_setting_state(db_session)
    enhancer = DfEngineModelOptionsFactory.create(
        name="Enhancer-A", type="text", is_available=True, is_enabled=True, is_main=False
    )
    assistant = DfEngineModelOptionsFactory.create(
        name="Assistant-A", type="text", is_available=True, is_enabled=True, is_main=False
    )
    await authed_client.call("POST", URL, json={"enhancer_model": enhancer.uid, "assistant_model": assistant.uid})

    body = (await authed_client.call("GET", URL)).json()["data"]
    assert body["enhancer_model"] == enhancer.name
    assert body["assistant_model"] == assistant.name


@pytest.mark.asyncio
async def test_fetch_response_is_cached_with_a_ttl(authed_client, db_session):
    """200 OK; a GET populates the global settings cache in Redis with an expiry."""
    await clear_setting_state(db_session)
    redis = redis_client()
    await authed_client.call("POST", URL, json={"admin_view": {"see_all_asset": True}})
    await redis.delete(cache_key.setting_global())

    resp = await authed_client.call("GET", URL)
    assert resp.status_code == 200
    assert await redis.exists(cache_key.setting_global())
    assert await redis.ttl(cache_key.setting_global()) > 0


@pytest.mark.asyncio
async def test_update_invalidates_the_cache(authed_client, db_session):
    """200 OK; a POST clears the cached document so the next GET reflects the new save."""
    await clear_setting_state(db_session)
    redis = redis_client()

    await authed_client.call("POST", URL, json={"admin_view": {"see_all_asset": True}})
    await authed_client.call("GET", URL)
    assert await redis.exists(cache_key.setting_global())

    await authed_client.call("POST", URL, json={"admin_view": {"see_all_asset": False}})
    assert not await redis.exists(cache_key.setting_global())

    body = (await authed_client.call("GET", URL)).json()["data"]
    assert body["admin_view"] == {"see_all_asset": False}


@pytest.mark.asyncio
async def test_fetch_requires_auth(client):
    """401 when the request carries no bearer token."""
    resp = await client.call("GET", URL, raise_for_status=False)
    assert resp.status_code == 401
