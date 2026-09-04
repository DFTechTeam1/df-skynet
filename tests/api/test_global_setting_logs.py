import pytest
from services.redis import client as redis_client, CacheKeys
from tests.helpers import clear_setting_state

cache_key = CacheKeys()

SETTING_URL = "/api/setting"
LOGS_URL = "/api/setting/logs"


def _class_limit_payload(class_id: int, token_usage_limit: int) -> dict:
    return {"project_class_limitations": [{"id": class_id, "token_usage_limit": token_usage_limit}]}


@pytest.mark.asyncio
async def test_logs_first_save_is_not_logged(authed_client, db_session):
    """200 OK; the first save just inserts the rows — no prior state, so no history entry."""
    await clear_setting_state(db_session)

    await authed_client.call("POST", SETTING_URL, json={"admin_view": {"see_all_asset": False}})

    resp = await authed_client.call("GET", LOGS_URL)
    assert resp.json()["data"]["totalData"] == 0
    assert resp.json()["data"]["paginated"] == []


@pytest.mark.asyncio
async def test_logs_unchanged_save_is_not_logged(authed_client, db_session):
    """200 OK; re-saving identical values adds no log entry."""
    await clear_setting_state(db_session)
    payload = {"admin_view": {"see_all_asset": True}}
    await authed_client.call("POST", SETTING_URL, json=payload)

    resp = await authed_client.call("POST", SETTING_URL, json=payload)
    assert resp.status_code == 200

    logs = await authed_client.call("GET", LOGS_URL)
    assert logs.json()["data"]["totalData"] == 0


@pytest.mark.asyncio
async def test_logs_changed_save_records_the_diff(authed_client, db_session):
    """200 OK; once settings exist, a save with different values records a before/after entry."""
    await clear_setting_state(db_session)
    await authed_client.call("POST", SETTING_URL, json={"admin_view": {"see_all_asset": True}})
    await authed_client.call("POST", SETTING_URL, json={"admin_view": {"see_all_asset": False}})

    body = (await authed_client.call("GET", LOGS_URL)).json()["data"]
    assert body["totalData"] == 1
    entry = body["paginated"][0]
    assert entry["incoming_data"]["admin_view"] == {"see_all_asset": False}
    assert entry["previous_data"]["admin_view"] == {"see_all_asset": True}
    assert entry["creator"] is not None
    assert entry["changed_fields"] == ["admin_view"]


@pytest.mark.asyncio
async def test_logs_pagination(authed_client, db_session, project_class_id):
    """200 OK; itemsPerPage/page slice the log list; newest first."""
    await clear_setting_state(db_session)
    await authed_client.call("POST", SETTING_URL, json=_class_limit_payload(project_class_id, 1))
    for i in range(2, 5):
        await authed_client.call("POST", SETTING_URL, json=_class_limit_payload(project_class_id, i))

    body = (await authed_client.call("GET", LOGS_URL, params={"itemsPerPage": 2, "page": 1})).json()["data"]
    assert body["totalData"] == 3
    assert len(body["paginated"]) == 2

    page_two = await authed_client.call("GET", LOGS_URL, params={"itemsPerPage": 2, "page": 2})
    assert len(page_two.json()["data"]["paginated"]) == 1


@pytest.mark.asyncio
async def test_logs_search_filters_by_user_name_prefix(authed_client, db_session):
    """200 OK; `search` matches the log row's stored user_name as a case-insensitive prefix."""
    await clear_setting_state(db_session)
    await authed_client.call("POST", SETTING_URL, json={"admin_view": {"see_all_asset": True}})
    await authed_client.call("POST", SETTING_URL, json={"admin_view": {"see_all_asset": False}})

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
    await authed_client.call("POST", SETTING_URL, json={"admin_view": {"see_all_asset": True}})
    await authed_client.call("POST", SETTING_URL, json={"admin_view": {"see_all_asset": False}})

    key = cache_key.setting_logs_pagination(page=1, items_per_page=50)
    assert not await redis_client().exists(key)

    first = await authed_client.call("GET", LOGS_URL)
    assert await redis_client().exists(key)

    second = await authed_client.call("GET", LOGS_URL)
    assert second.json()["data"] == first.json()["data"]


@pytest.mark.asyncio
async def test_logs_changed_save_invalidates_the_cache(authed_client, db_session):
    """200 OK; a save that writes a history entry clears the cached pages."""
    await clear_setting_state(db_session)
    await authed_client.call("POST", SETTING_URL, json={"admin_view": {"see_all_asset": True}})

    warm = await authed_client.call("GET", LOGS_URL)
    assert warm.json()["data"]["totalData"] == 0

    await authed_client.call("POST", SETTING_URL, json={"admin_view": {"see_all_asset": False}})

    resp = await authed_client.call("GET", LOGS_URL)
    assert resp.json()["data"]["totalData"] == 1


@pytest.mark.asyncio
async def test_logs_requires_auth(client):
    """401 when the request carries no bearer token."""
    resp = await client.call("GET", LOGS_URL, raise_for_status=False)
    assert resp.status_code == 401
