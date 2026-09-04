import pytest
from uuid import uuid4
from middlewares.lang import resolve_message
from services.redis import client as redis_client, CacheKeys
from tests.helpers import clear_setting_state

SETTING_URL = "/api/setting"
cache_key = CacheKeys()

LIMIT_FIELDS = {
    "token_usage_limit",
    "concurent_generations",
    "compose_input_max_chars",
    "storyboard_prompt_chars",
    "max_scene_per_storyboard",
    "max_shot_per_scene",
}


def _url(uid: str) -> str:
    return f"{SETTING_URL}/{uid}"


async def _configure_global(authed_client, class_id: int, token_usage_limit: int = 1) -> None:
    await authed_client.call(
        "POST",
        SETTING_URL,
        json={"project_class_limitations": [{"id": class_id, "token_usage_limit": token_usage_limit}]},
    )


@pytest.mark.asyncio
async def test_fetch_rejects_unknown_project(authed_client, db_session):
    """404 project_not_found when the uid matches no project."""
    await clear_setting_state(db_session)

    resp = await authed_client.call("GET", _url(str(uuid4())), raise_for_status=False)
    assert resp.status_code == 404
    assert resp.json()["message"] == resolve_message("project_not_found", "en")


@pytest.mark.asyncio
async def test_fetch_falls_back_to_class_limits_when_no_override(authed_client, db_session, project_with_class):
    """200 OK; with no per-project row the limits come from the global settings for the project's class."""
    uid, class_id, classification = project_with_class
    await clear_setting_state(db_session)
    await _configure_global(authed_client, class_id, token_usage_limit=17)

    body = (await authed_client.call("GET", _url(uid))).json()["data"]
    assert body["classification"] == classification
    assert body["token_usage_limit"] == 17
    assert LIMIT_FIELDS <= set(body)


@pytest.mark.asyncio
async def test_fetch_returns_the_saved_override_when_present(authed_client, db_session, project_with_class):
    """200 OK; a saved per-project row wins over the class fallback."""
    uid, class_id, _ = project_with_class
    await clear_setting_state(db_session)
    await _configure_global(authed_client, class_id, token_usage_limit=5)
    await authed_client.call("POST", _url(uid), json={"token_usage_limit": 99, "concurent_generations": 4})

    body = (await authed_client.call("GET", _url(uid))).json()["data"]
    assert body["token_usage_limit"] == 99
    assert body["concurent_generations"] == 4


@pytest.mark.asyncio
async def test_fetch_requires_global_settings_to_exist(authed_client, db_session, project_with_class):
    """422 global_setting_not_configured when nothing has been saved globally yet."""
    uid, _, _ = project_with_class
    await clear_setting_state(db_session)

    resp = await authed_client.call("GET", _url(uid), raise_for_status=False)
    assert resp.status_code == 422
    assert resp.json()["message"] == resolve_message("global_setting_not_configured", "en")


@pytest.mark.asyncio
async def test_fetch_rejects_project_with_no_class_assigned(
    authed_client, db_session, project_without_class, project_class_id
):
    """422 project_class_not_assigned when the project has no project class."""
    await clear_setting_state(db_session)
    await _configure_global(authed_client, project_class_id)

    resp = await authed_client.call("GET", _url(project_without_class), raise_for_status=False)
    assert resp.status_code == 422
    assert resp.json()["message"] == resolve_message("project_class_not_assigned", "en")


@pytest.mark.asyncio
async def test_fetch_response_is_cached_with_a_ttl(authed_client, db_session, project_with_class):
    """200 OK; a GET populates the per-project cache key with an expiry."""
    uid, class_id, _ = project_with_class
    await clear_setting_state(db_session)
    await _configure_global(authed_client, class_id)
    redis = redis_client()

    await authed_client.call("GET", _url(uid))
    assert await redis.exists(cache_key.setting_project(uid))
    assert await redis.ttl(cache_key.setting_project(uid)) > 0


@pytest.mark.asyncio
async def test_save_invalidates_the_fetch_cache(authed_client, db_session, project_with_class):
    """200 OK; POST clears the cached project setting so the next GET reflects the override."""
    uid, class_id, _ = project_with_class
    await clear_setting_state(db_session)
    await _configure_global(authed_client, class_id, token_usage_limit=2)

    await authed_client.call("GET", _url(uid))  # warm cache with the fallback
    assert await redis_client().exists(cache_key.setting_project(uid))

    await authed_client.call("POST", _url(uid), json={"token_usage_limit": 40})
    assert not await redis_client().exists(cache_key.setting_project(uid))

    body = (await authed_client.call("GET", _url(uid))).json()["data"]
    assert body["token_usage_limit"] == 40


@pytest.mark.asyncio
async def test_fetch_requires_auth(client, project_with_class):
    """401 when the request carries no bearer token."""
    uid, _, _ = project_with_class
    resp = await client.call("GET", _url(uid), raise_for_status=False)
    assert resp.status_code == 401
