import pytest
from services.mysql.factory.df_engine_model_options import DfEngineModelOptionsFactory
from services.redis import client as redis_client
from apps.controller.setting import DETAIL_CACHE_KEY
from tests.helpers import clear_setting_state

URL = "/api/setting"


@pytest.mark.asyncio
async def test_fetch_returns_defaults_when_nothing_saved_yet(authed_client, db_session):
    """200 OK; GET returns the schema's own defaults and null models when no settings exist yet."""
    await clear_setting_state(db_session)

    resp = await authed_client.call("GET", URL)
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["admin_view"] == {"see_all_asset": True}
    assert body["limit"] == {"generate_per_min": 0, "enhance_per_min": 0}
    assert body["spend_ceiling"] == {"daily_ceiling_global_user": 0, "daily_ceiling_per_user": 0}
    assert body["storyboard"] == {
        "max_storyboard_char": 4000,
        "max_scene_per_storyboard": 100,
        "max_shot_per_scene": 100,
    }
    assert body["compose_input"] == {"max_prompt_char": 4000}
    assert body["chat_assistant"] == {"max_previous_conversation": 0}
    assert body["enhancer_model"] is None
    assert body["assistant_model"] is None


@pytest.mark.asyncio
async def test_fetch_returns_saved_values(authed_client, db_session):
    """200 OK; GET reflects whatever was last saved via POST."""
    await clear_setting_state(db_session)
    payload = {
        "admin_view": {"see_all_asset": False},
        "limit": {"generate_per_min": 5, "enhance_per_min": 10},
        "spend_ceiling": {"daily_ceiling_global_user": 100, "daily_ceiling_per_user": 20},
        "storyboard": {"max_storyboard_char": 3000, "max_scene_per_storyboard": 50, "max_shot_per_scene": 20},
        "compose_input": {"max_prompt_char": 2000},
        "chat_assistant": {"max_previous_conversation": 6},
        "enhancer_model": None,
        "assistant_model": None,
    }
    await authed_client.call("POST", URL, json=payload)

    resp = await authed_client.call("GET", URL)
    body = resp.json()["data"]
    assert body["admin_view"] == payload["admin_view"]
    assert body["chat_assistant"] == payload["chat_assistant"]
    assert body["limit"] == payload["limit"]
    assert body["spend_ceiling"] == payload["spend_ceiling"]
    assert body["storyboard"] == payload["storyboard"]
    assert body["compose_input"] == payload["compose_input"]


@pytest.mark.asyncio
async def test_fetch_resolves_enhancer_and_assistant_model_info(authed_client, db_session):
    """200 OK; enhancer_model/assistant_model come back as full model info, not a bare UID."""
    await clear_setting_state(db_session)
    enhancer = DfEngineModelOptionsFactory.create(
        name="Enhancer-A", type="text", is_available=True, is_enabled=True, is_main=False
    )
    assistant = DfEngineModelOptionsFactory.create(
        name="Assistant-A", type="text", is_available=True, is_enabled=True, is_main=False
    )

    payload = {
        "admin_view": {},
        "limit": {},
        "spend_ceiling": {},
        "storyboard": {},
        "compose_input": {},
        "chat_assistant": {},
        "enhancer_model": enhancer.uid,
        "assistant_model": assistant.uid,
    }
    await authed_client.call("POST", URL, json=payload)

    resp = await authed_client.call("GET", URL)
    body = resp.json()["data"]
    assert body["enhancer_model"]["uid"] == enhancer.uid
    assert body["enhancer_model"]["name"] == enhancer.name
    assert body["assistant_model"]["uid"] == assistant.uid
    assert body["assistant_model"]["name"] == assistant.name


@pytest.mark.asyncio
async def test_requires_auth(client):
    """401 when the request carries no bearer token."""
    resp = await client.call("GET", URL, raise_for_status=False)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_response_is_cached_with_a_ttl(authed_client, db_session):
    """200 OK; a GET populates the settings cache (a single global key) in Redis with an expiry."""
    await clear_setting_state(db_session)
    redis = redis_client()

    resp = await authed_client.call("GET", URL)
    assert resp.status_code == 200
    assert await redis.exists(DETAIL_CACHE_KEY)
    assert await redis.ttl(DETAIL_CACHE_KEY) > 0


@pytest.mark.asyncio
async def test_post_invalidates_the_detail_cache(authed_client, db_session):
    """200 OK; a POST clears the cached settings so the next GET reflects the new save, not the stale cache."""
    await clear_setting_state(db_session)
    redis = redis_client()

    await authed_client.call("GET", URL)  # warm the cache with the defaults
    assert await redis.exists(DETAIL_CACHE_KEY)

    payload = {
        "admin_view": {"see_all_asset": False},
        "limit": {"generate_per_min": 5, "enhance_per_min": 10},
        "spend_ceiling": {"daily_ceiling_global_user": 100, "daily_ceiling_per_user": 20},
        "storyboard": {"max_storyboard_char": 3000, "max_scene_per_storyboard": 50, "max_shot_per_scene": 20},
        "compose_input": {"max_prompt_char": 2000},
        "chat_assistant": {"max_previous_conversation": 0},
        "enhancer_model": None,
        "assistant_model": None,
    }
    await authed_client.call("POST", URL, json=payload)

    resp = await authed_client.call("GET", URL)
    assert resp.json()["data"]["admin_view"] == payload["admin_view"]
