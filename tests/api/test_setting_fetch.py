import pytest
from uuid import uuid4
from middlewares.lang import resolve_message
from services.mysql.factory.df_engine_model_options import DfEngineModelOptionsFactory
from services.redis import client as redis_client
from tests.helpers import SETTING_DETAIL_CACHE_KEY, clear_setting_state

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
    assert body["storyboard"] == {
        "max_storyboard_char": 4000,
        "max_scene_per_storyboard": 100,
        "max_shot_per_scene": 100,
    }
    assert body["compose_input"] == {"max_prompt_char": 4000}
    assert body["chat_assistant"] == {"max_previous_conversation": 0}
    assert body["enhancer_model"] is None
    assert body["assistant_model"] is None
    # no project_uid query param -> override is null
    assert body["project_limit_override"] is None
    # every current project class comes back, all at 0
    assert isinstance(body["project_class_limits"], list) and body["project_class_limits"]
    assert all(row["limit"] == 0 for row in body["project_class_limits"])
    assert all(set(row) == {"project_class_name", "limit"} for row in body["project_class_limits"])


@pytest.mark.asyncio
async def test_fetch_returns_saved_values(authed_client, db_session):
    """200 OK; GET reflects whatever was last saved via POST."""
    await clear_setting_state(db_session)
    payload = {
        "admin_view": {"see_all_asset": False},
        "limit": {"generate_per_min": 5, "enhance_per_min": 10},
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
    assert body["storyboard"] == payload["storyboard"]
    assert body["compose_input"] == payload["compose_input"]


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

    payload = {"enhancer_model": enhancer.uid, "assistant_model": assistant.uid}
    await authed_client.call("POST", URL, json=payload)

    resp = await authed_client.call("GET", URL)
    body = resp.json()["data"]
    assert body["enhancer_model"] == enhancer.name
    assert body["assistant_model"] == assistant.name


@pytest.mark.asyncio
async def test_fetch_with_project_uid_returns_null_when_no_override_saved(authed_client, db_session, project_uid):
    """200 OK; passing a valid project_uid with no saved override still returns null (no synthetic default)."""
    await clear_setting_state(db_session)

    resp = await authed_client.call("GET", URL, params={"project_uid": project_uid})
    assert resp.status_code == 200
    assert resp.json()["data"]["project_limit_override"] is None


@pytest.mark.asyncio
async def test_fetch_with_project_uid_returns_saved_override_without_project_uid_key(
    authed_client, db_session, project_uid
):
    """200 OK; a saved override comes back scoped to the project, as {project_name, limit} — no project_uid echoed."""
    await clear_setting_state(db_session)
    await authed_client.call("POST", URL, json={"project_limit_override": {"project_uid": project_uid, "limit": 7}})

    resp = await authed_client.call("GET", URL, params={"project_uid": project_uid})
    override = resp.json()["data"]["project_limit_override"]
    assert override["limit"] == 7
    assert set(override) == {"project_name", "limit"}


@pytest.mark.asyncio
async def test_fetch_rejects_unknown_project_uid(authed_client, db_session):
    """404 project_not_found when the project_uid query param matches no project."""
    await clear_setting_state(db_session)

    resp = await authed_client.call("GET", URL, params={"project_uid": str(uuid4())}, raise_for_status=False)
    assert resp.status_code == 404
    assert resp.json()["message"] == resolve_message("project_not_found", "en")


@pytest.mark.asyncio
async def test_requires_auth(client):
    """401 when the request carries no bearer token."""
    resp = await client.call("GET", URL, raise_for_status=False)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_response_is_cached_with_a_ttl(authed_client, db_session):
    """200 OK; a GET populates the settings cache (the no-project variant key) in Redis with an expiry."""
    await clear_setting_state(db_session)
    redis = redis_client()

    resp = await authed_client.call("GET", URL)
    assert resp.status_code == 200
    assert await redis.exists(SETTING_DETAIL_CACHE_KEY)
    assert await redis.ttl(SETTING_DETAIL_CACHE_KEY) > 0


@pytest.mark.asyncio
async def test_post_invalidates_the_detail_cache(authed_client, db_session):
    """200 OK; a POST clears the cached settings so the next GET reflects the new save, not the stale cache."""
    await clear_setting_state(db_session)
    redis = redis_client()

    await authed_client.call("GET", URL)  # warm the cache with the defaults
    assert await redis.exists(SETTING_DETAIL_CACHE_KEY)

    await authed_client.call("POST", URL, json={"admin_view": {"see_all_asset": False}})
    assert not await redis.exists(SETTING_DETAIL_CACHE_KEY)

    resp = await authed_client.call("GET", URL)
    assert resp.json()["data"]["admin_view"] == {"see_all_asset": False}
