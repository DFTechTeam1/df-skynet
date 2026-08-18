import pytest
from sqlalchemy import select
from services.mysql.model import DfEnginePreferences
from tests.helpers import clear_preference_row

URL = "/api/preferences"


@pytest.mark.asyncio
async def test_full_preference_lifecycle(authed_client, db_session, user_id):
    """Walks default -> first save -> fetch -> update -> fetch for one user's preferences, checking each response and that POST never duplicates the row."""
    await clear_preference_row(db_session, user_id)

    # 1. nothing saved yet -> defaults, no row created
    default_resp = await authed_client.call("GET", URL)
    assert default_resp.status_code == 200
    assert default_resp.json()["data"]["theme"] == "dark"
    assert default_resp.json()["data"]["default_size"] == "4K"

    # 2. first save (insert)
    first = {
        "theme": "light",
        "accent": "violet",
        "language": "indonesia",
        "default_aspect_ratio": "1:1",
        "default_size": "2K",
        "confirm_before_spending": 1.0,
    }
    create_resp = await authed_client.call("POST", URL, json=first)
    assert create_resp.status_code == 200
    assert create_resp.json()["data"] == first

    # 3. fetch reflects the saved values
    fetch_resp = await authed_client.call("GET", URL)
    assert fetch_resp.json()["data"] == first

    # 4. second save (update) — different values across every field
    second = {
        "theme": "dark",
        "accent": "signal",
        "language": "english",
        "default_aspect_ratio": "9:16",
        "default_size": "1K",
        "confirm_before_spending": 0.75,
    }
    update_resp = await authed_client.call("POST", URL, json=second)
    assert update_resp.status_code == 200
    assert update_resp.json()["data"] == second

    # 5. fetch reflects the latest state, not the first save
    final_fetch = await authed_client.call("GET", URL)
    assert final_fetch.json()["data"] == second

    # 6. exactly one row exists for this user — POST upserts, it never
    # duplicates the row, even after two sequential saves
    await db_session.commit()
    rows = (
        (await db_session.execute(select(DfEnginePreferences).where(DfEnginePreferences.user_id == int(user_id))))
        .scalars()
        .all()
    )
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_invalid_update_leaves_previous_value_intact(authed_client, db_session, user_id):
    """422 on an invalid payload, and the previously saved preferences are left untouched — same 'failed write doesn't corrupt state' guarantee as the other controllers."""
    await clear_preference_row(db_session, user_id)

    valid = {
        "theme": "light",
        "accent": "signal",
        "language": "english",
        "default_aspect_ratio": "16:9",
        "default_size": "1K",
        "confirm_before_spending": 0.5,
    }
    await authed_client.call("POST", URL, json=valid)

    bad = dict(valid, theme="blue")
    bad_resp = await authed_client.call("POST", URL, json=bad, raise_for_status=False)
    assert bad_resp.status_code == 422

    fetch_resp = await authed_client.call("GET", URL)
    assert fetch_resp.json()["data"] == valid
