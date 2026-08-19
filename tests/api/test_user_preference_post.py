import pytest
from tests.helpers import clear_preference_row

URL = "/api/user-preference"


@pytest.mark.asyncio
async def test_post_creates_a_row_on_first_write(authed_client, db_session, user_id):
    """200 OK; POST inserts a new row when the user has none yet."""
    await clear_preference_row(db_session, user_id)

    payload = {
        "theme": "light",
        "accent": "violet",
        "language": "indonesia",
        "default_aspect_ratio": "1:1",
        "default_size": "2K",
        "confirm_before_spending": 1.25,
    }
    resp = await authed_client.call("POST", URL, json=payload)
    assert resp.status_code == 200
    assert resp.json()["data"]["theme"] == "light"

    fetch = await authed_client.call("GET", URL)
    assert fetch.json()["data"] == resp.json()["data"]


@pytest.mark.asyncio
async def test_post_updates_the_existing_row_instead_of_duplicating(authed_client, user_id):
    """200 OK; a second POST overwrites the same row rather than creating a new one."""
    first = {
        "theme": "dark",
        "accent": "signal",
        "language": "english",
        "default_aspect_ratio": "16:9",
        "default_size": "1K",
        "confirm_before_spending": 0.5,
    }
    await authed_client.call("POST", URL, json=first)

    second = dict(first, theme="light", confirm_before_spending=2.0)
    resp = await authed_client.call("POST", URL, json=second)
    assert resp.status_code == 200
    assert resp.json()["data"]["theme"] == "light"
    assert resp.json()["data"]["confirm_before_spending"] == 2.0

    fetch = await authed_client.call("GET", URL)
    assert fetch.json()["data"]["theme"] == "light"


@pytest.mark.asyncio
async def test_post_invalid_enum_is_422(authed_client):
    """422 when theme isn't one of the allowed enum values."""
    resp = await authed_client.call("POST", URL, json={"theme": "blue"}, raise_for_status=False)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_post_negative_confirm_before_spending_is_422(authed_client):
    """422 when confirm_before_spending is negative."""
    resp = await authed_client.call("POST", URL, json={"confirm_before_spending": -1}, raise_for_status=False)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_requires_auth(client):
    """401 when the request carries no bearer token."""
    resp = await client.call("POST", URL, json={}, raise_for_status=False)
    assert resp.status_code == 401
