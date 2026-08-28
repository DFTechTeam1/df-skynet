import pytest
from sqlalchemy import select
from services.mysql.model import DfEnginePreferences
from services.redis import client as redis_client, CacheKeys
from tests.helpers import clear_preference_row

URL = "/api/user-preference"
cache_key = CacheKeys()


@pytest.mark.asyncio
async def test_fetch_returns_defaults_when_no_row_exists(authed_client, db_session, user_id):
    """200 OK; GET returns hardcoded defaults and creates no row when nothing is stored yet."""
    await clear_preference_row(db_session, user_id)

    resp = await authed_client.call("GET", URL)
    body = resp.json()
    assert resp.status_code == 200
    assert body["data"]["theme"] == "dark"
    assert body["data"]["default_size"] == "4K"

    row = (
        await db_session.execute(select(DfEnginePreferences).where(DfEnginePreferences.user_id == int(user_id)))  # type: ignore
    ).scalar_one_or_none()
    assert row is None


@pytest.mark.asyncio
async def test_fetch_returns_saved_values_when_a_row_exists(authed_client, db_session, user_id):
    """200 OK; GET returns the persisted row's values once one exists."""
    await clear_preference_row(db_session, user_id)
    payload = {
        "theme": "light",
        "accent": "violet",
        "language": "indonesia",
        "default_aspect_ratio": "1:1",
        "default_size": "2K",
        "confirm_before_spending": "over_0.1",
    }
    await authed_client.call("POST", URL, json=payload)

    resp = await authed_client.call("GET", URL)
    assert resp.status_code == 200
    assert resp.json()["data"] == dict(payload, confirm_before_spending="Over 0.1")


@pytest.mark.asyncio
async def test_requires_auth(client):
    """401 when the request carries no bearer token."""
    resp = await client.call("GET", URL, raise_for_status=False)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_response_is_cached_per_user_with_a_ttl(authed_client, db_session, user_id):
    """200 OK; a GET populates a Redis key keyed by this user's own id (even for the resolved default), with an expiry."""
    await clear_preference_row(db_session, user_id)
    redis = redis_client()
    key = cache_key.user_preference(int(user_id))

    resp = await authed_client.call("GET", URL)
    assert resp.status_code == 200
    assert await redis.exists(key)
    assert await redis.ttl(key) > 0


@pytest.mark.asyncio
async def test_preference_cache_key_is_scoped_per_user():
    """The cache key must differ per user_id — this is what makes the per-user
    design safe; two different users must never collide on the same key."""
    assert cache_key.user_preference(1) != cache_key.user_preference(2)
    assert str(1) in cache_key.user_preference(1)
