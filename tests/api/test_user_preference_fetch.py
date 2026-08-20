import pytest
from sqlalchemy import select
from services.mysql.model import DfEnginePreferences
from tests.helpers import clear_preference_row

URL = "/api/user-preference"


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
