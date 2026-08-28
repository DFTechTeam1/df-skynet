import pytest
from typing import Any
from services.redis import client as redis_client, CacheKeys
from tests.helpers import clear_setting_state

cache_key = CacheKeys()

SETTING_URL = "/api/setting"
LOGS_URL = "/api/setting/logs"


def _base_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "admin_view": {"see_all_asset": True},
        "limit": {"generate_per_min": 0, "enhance_per_min": 0},
        "spend_ceiling": {"daily_ceiling_global_user": 0, "daily_ceiling_per_user": 0},
        "storyboard": {"max_storyboard_char": 4000, "max_scene_per_storyboard": 100, "max_shot_per_scene": 100},
        "compose_input": {"max_prompt_char": 4000},
        "chat_assistant": {"max_previous_conversation": 0},
        "enhancer_model": None,
        "assistant_model": None,
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_first_save_is_not_logged(authed_client, db_session):
    """200 OK; the first save just inserts the settings rows — there's no prior state, so no history entry."""
    await clear_setting_state(db_session)

    await authed_client.call(
        "POST", SETTING_URL, json=_base_payload(limit={"generate_per_min": 9, "enhance_per_min": 1})
    )

    resp = await authed_client.call("GET", LOGS_URL)
    assert resp.json()["data"]["totalData"] == 0
    assert resp.json()["data"]["paginated"] == []


@pytest.mark.asyncio
async def test_unchanged_save_is_not_logged(authed_client, db_session):
    """200 OK; re-saving identical values adds no log entry."""
    await clear_setting_state(db_session)
    payload = _base_payload()
    await authed_client.call("POST", SETTING_URL, json=payload)

    resp = await authed_client.call("POST", SETTING_URL, json=payload)
    assert resp.status_code == 200

    logs = await authed_client.call("GET", LOGS_URL)
    assert logs.json()["data"]["totalData"] == 0


@pytest.mark.asyncio
async def test_changed_save_adds_a_log_entry_with_the_diff(authed_client, db_session):
    """200 OK; once settings exist, a save with different values records a before/after entry."""
    await clear_setting_state(db_session)
    await authed_client.call("POST", SETTING_URL, json=_base_payload())
    await authed_client.call("POST", SETTING_URL, json=_base_payload(admin_view={"see_all_asset": False}))

    resp = await authed_client.call("GET", LOGS_URL)
    body = resp.json()["data"]
    assert body["totalData"] == 1
    entry = body["paginated"][0]
    assert entry["incoming_data"]["admin_view"] == {"see_all_asset": False}
    assert entry["previous_data"]["admin_view"] == {"see_all_asset": True}
    assert entry["creator"] is not None


@pytest.mark.asyncio
async def test_pagination(authed_client, db_session):
    """200 OK; itemsPerPage/page slice the log list; newest first."""
    await clear_setting_state(db_session)
    await authed_client.call("POST", SETTING_URL, json=_base_payload())
    for i in range(1, 4):
        await authed_client.call("POST", SETTING_URL, json=_base_payload(compose_input={"max_prompt_char": 1000 + i}))

    resp = await authed_client.call("GET", LOGS_URL, params={"itemsPerPage": 2, "page": 1})
    body = resp.json()["data"]
    assert body["totalData"] == 3
    assert len(body["paginated"]) == 2

    page_two = await authed_client.call("GET", LOGS_URL, params={"itemsPerPage": 2, "page": 2})
    assert len(page_two.json()["data"]["paginated"]) == 1


@pytest.mark.asyncio
async def test_search_filters_by_user_name_prefix(authed_client, db_session):
    """200 OK; `search` matches the log row's stored user_name as a case-insensitive prefix."""
    await clear_setting_state(db_session)
    await authed_client.call("POST", SETTING_URL, json=_base_payload())
    await authed_client.call("POST", SETTING_URL, json=_base_payload(admin_view={"see_all_asset": False}))

    all_logs = await authed_client.call("GET", LOGS_URL)
    user_name = all_logs.json()["data"]["paginated"][0]["user_name"]
    assert user_name, "logged-in test user must have a username to search by"

    hit = await authed_client.call("GET", LOGS_URL, params={"search": user_name[:3].upper()})
    miss = await authed_client.call("GET", LOGS_URL, params={"search": "zzz-no-such-user"})

    assert hit.json()["data"]["totalData"] == 1
    assert miss.json()["data"]["totalData"] == 0
    assert miss.json()["data"]["paginated"] == []


@pytest.mark.asyncio
async def test_logs_response_is_cached(authed_client, db_session):
    """200 OK; the first GET populates the per-page cache key, a second GET is served from it."""
    await clear_setting_state(db_session)
    await authed_client.call("POST", SETTING_URL, json=_base_payload())
    await authed_client.call("POST", SETTING_URL, json=_base_payload(admin_view={"see_all_asset": False}))

    key = cache_key.setting_pagination(page=1, items_per_page=50)
    assert not await redis_client().exists(key)

    first = await authed_client.call("GET", LOGS_URL)
    assert await redis_client().exists(key)

    second = await authed_client.call("GET", LOGS_URL)
    assert second.json()["data"] == first.json()["data"]


@pytest.mark.asyncio
async def test_changed_save_invalidates_the_logs_cache(authed_client, db_session):
    """200 OK; a save that writes a history entry clears the cached pages so the next GET shows it."""
    await clear_setting_state(db_session)
    await authed_client.call("POST", SETTING_URL, json=_base_payload())

    warm = await authed_client.call("GET", LOGS_URL)
    assert warm.json()["data"]["totalData"] == 0
    assert await redis_client().exists(cache_key.setting_pagination(page=1, items_per_page=50))

    await authed_client.call("POST", SETTING_URL, json=_base_payload(admin_view={"see_all_asset": False}))

    resp = await authed_client.call("GET", LOGS_URL)
    assert resp.json()["data"]["totalData"] == 1


@pytest.mark.asyncio
async def test_requires_auth(client):
    """401 when the request carries no bearer token."""
    resp = await client.call("GET", LOGS_URL, raise_for_status=False)
    assert resp.status_code == 401
