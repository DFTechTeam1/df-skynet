import pytest
from typing import Any
from services.redis import client as redis_client
from apps.controller.setting import logs_cache_key
from tests.helpers import clear_setting_state

SETTING_URL = "/api/setting"
LOGS_URL = "/api/setting/logs"


def _base_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "admin_view": {"see_all_asset": True},
        "limit": {"generate_per_min": 0, "enhance_per_min": 0},
        "spend_ceiling": {"daily_ceiling_global_user": 0, "daily_ceiling_per_user": 0},
        "storyboard": {"max_storyboard_char": 4000, "max_scene_per_storyboard": 100, "max_shot_per_scene": 100},
        "compose_input": {"max_prompt_char": 4000},
        "enhancer_model": None,
        "assistant_model": None,
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_first_save_is_logged_with_null_previous_data(authed_client, db_session):
    """200 OK; the very first save is logged, with previous_data null since nothing existed before it."""
    await clear_setting_state(db_session)

    await authed_client.call(
        "POST", SETTING_URL, json=_base_payload(limit={"generate_per_min": 9, "enhance_per_min": 1})
    )

    resp = await authed_client.call("GET", LOGS_URL)
    body = resp.json()["data"]
    assert body["totalData"] == 1
    entry = body["paginated"][0]
    assert entry["previous_data"] is None
    assert entry["incoming_data"]["limit"] == {"generate_per_min": 9, "enhance_per_min": 1}
    assert entry["creator"] is not None


@pytest.mark.asyncio
async def test_unchanged_save_is_not_logged(authed_client, db_session):
    """200 OK; saving identical values again doesn't add a new log entry."""
    await clear_setting_state(db_session)
    payload = _base_payload()
    await authed_client.call("POST", SETTING_URL, json=payload)

    resp = await authed_client.call("POST", SETTING_URL, json=payload)
    assert resp.status_code == 200

    logs = await authed_client.call("GET", LOGS_URL)
    assert logs.json()["data"]["totalData"] == 1


@pytest.mark.asyncio
async def test_changed_save_adds_a_new_log_entry_with_the_diff(authed_client, db_session):
    """200 OK; a second save with different values adds a second log, newest first, with a real before/after."""
    await clear_setting_state(db_session)
    await authed_client.call("POST", SETTING_URL, json=_base_payload())
    await authed_client.call("POST", SETTING_URL, json=_base_payload(admin_view={"see_all_asset": False}))

    resp = await authed_client.call("GET", LOGS_URL)
    body = resp.json()["data"]
    assert body["totalData"] == 2
    newest = body["paginated"][0]
    assert newest["incoming_data"]["admin_view"] == {"see_all_asset": False}
    assert newest["previous_data"]["admin_view"] == {"see_all_asset": True}


@pytest.mark.asyncio
async def test_pagination(authed_client, db_session):
    """200 OK; itemsPerPage/page slice the log list correctly."""
    await clear_setting_state(db_session)
    await authed_client.call("POST", SETTING_URL, json=_base_payload())
    for i in range(1, 4):
        await authed_client.call("POST", SETTING_URL, json=_base_payload(compose_input={"max_prompt_char": 1000 + i}))

    resp = await authed_client.call("GET", LOGS_URL, params={"itemsPerPage": 2, "page": 1})
    body = resp.json()["data"]
    assert body["totalData"] == 4
    assert len(body["paginated"]) == 2

    page_two = await authed_client.call("GET", LOGS_URL, params={"itemsPerPage": 2, "page": 2})
    assert len(page_two.json()["data"]["paginated"]) == 2


@pytest.mark.asyncio
async def test_requires_auth(client):
    """401 when the request carries no bearer token."""
    resp = await client.call("GET", LOGS_URL, raise_for_status=False)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_logs_response_is_cached_with_a_ttl(authed_client, db_session):
    """200 OK; a GET populates the logs cache (keyed by page + page size) in Redis with an expiry."""
    await clear_setting_state(db_session)
    await authed_client.call("POST", SETTING_URL, json=_base_payload())
    redis = redis_client()

    resp = await authed_client.call("GET", LOGS_URL)
    assert resp.status_code == 200
    key = logs_cache_key(1, 50)
    assert await redis.exists(key)
    assert await redis.ttl(key) > 0


@pytest.mark.asyncio
async def test_changed_save_invalidates_the_logs_cache(authed_client, db_session):
    """200 OK; a save that actually changes something clears the cached logs page so the new entry shows up."""
    await clear_setting_state(db_session)
    await authed_client.call("POST", SETTING_URL, json=_base_payload())
    await authed_client.call("GET", LOGS_URL)  # warm the cache at totalData == 1
    redis = redis_client()
    key = logs_cache_key(1, 50)
    assert await redis.exists(key)

    await authed_client.call("POST", SETTING_URL, json=_base_payload(admin_view={"see_all_asset": False}))

    resp = await authed_client.call("GET", LOGS_URL)
    assert resp.json()["data"]["totalData"] == 2


@pytest.mark.asyncio
async def test_unchanged_save_does_not_invalidate_the_logs_cache(authed_client, db_session):
    """200 OK; saving identical values again adds no log row, so the cached logs page is deliberately left alone."""
    await clear_setting_state(db_session)
    payload = _base_payload()
    await authed_client.call("POST", SETTING_URL, json=payload)
    await authed_client.call("GET", LOGS_URL)  # warm the cache
    redis = redis_client()
    key = logs_cache_key(1, 50)
    assert await redis.exists(key)

    await authed_client.call("POST", SETTING_URL, json=payload)

    assert await redis.exists(key)
