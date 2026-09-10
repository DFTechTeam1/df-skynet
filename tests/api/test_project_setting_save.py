import pytest
from uuid import uuid4
from sqlalchemy import func, select
from middlewares.lang import resolve_message
from services.mysql.model import DfEngineProjectSettings, Projects
from tests.helpers import clear_setting_state

SETTING_URL = "/api/setting"

FULL_PAYLOAD = {
    "token_usage_limit": 50,
    "compose_input_max_chars": 1500,
    "storyboard_prompt_chars": 1800,
    "max_scene_per_storyboard": 60,
    "max_shot_per_scene": 120,
}


def _url(uid: str) -> str:
    return f"{SETTING_URL}/{uid}"


async def _row_count(db_session, uid: str) -> int:
    project_id = (
        await db_session.execute(select(Projects.id).where(Projects.uid == uid))  # type: ignore
    ).scalar_one()
    return (
        await db_session.execute(
            select(func.count())
            .select_from(DfEngineProjectSettings)
            .where(DfEngineProjectSettings.project_id == project_id)  # type: ignore
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_save_rejects_unknown_project(authed_client, db_session):
    """404 project_not_found when the uid matches no project."""
    await clear_setting_state(db_session)

    resp = await authed_client.call("POST", _url(str(uuid4())), json=FULL_PAYLOAD, raise_for_status=False)
    assert resp.status_code == 404
    assert resp.json()["message"] == resolve_message("project_not_found", "en")


@pytest.mark.asyncio
async def test_save_creates_a_new_override_row(authed_client, db_session, project_with_class):
    """200 OK; the payload is stored and echoed back with the project name and classification."""
    uid, _, classification = project_with_class
    await clear_setting_state(db_session)

    resp = await authed_client.call("POST", _url(uid), json=FULL_PAYLOAD)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["classification"] == classification
    assert {k: data[k] for k in FULL_PAYLOAD} == FULL_PAYLOAD
    await db_session.rollback()
    assert await _row_count(db_session, uid) == 1


@pytest.mark.asyncio
async def test_save_upserts_instead_of_duplicating(authed_client, db_session, project_with_class):
    """200 OK; a second POST overwrites the same row rather than inserting another."""
    uid, _, _ = project_with_class
    await clear_setting_state(db_session)
    await authed_client.call("POST", _url(uid), json=FULL_PAYLOAD)

    resp = await authed_client.call("POST", _url(uid), json={**FULL_PAYLOAD, "compose_input_max_chars": 88})
    assert resp.status_code == 200
    assert resp.json()["data"]["compose_input_max_chars"] == 88

    await db_session.rollback()
    assert await _row_count(db_session, uid) == 1


@pytest.mark.asyncio
async def test_save_rejects_below_minimum(authed_client, db_session, project_with_class):
    """422; every limit must be >= 1."""
    uid, _, _ = project_with_class
    await clear_setting_state(db_session)

    resp = await authed_client.call(
        "POST", _url(uid), json={**FULL_PAYLOAD, "compose_input_max_chars": 0}, raise_for_status=False
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_save_stores_token_limit_threshold_override(authed_client, db_session, project_with_class):
    """200 OK; a token_limit_threshold in the body is stored on the project row and echoed back."""
    uid, _, _ = project_with_class
    await clear_setting_state(db_session)

    resp = await authed_client.call("POST", _url(uid), json={**FULL_PAYLOAD, "token_limit_threshold": 0.35})
    assert resp.status_code == 200
    assert resp.json()["data"]["token_limit_threshold"] == 0.35

    await db_session.rollback()
    row = (
        await db_session.execute(
            select(DfEngineProjectSettings).join(Projects).where(Projects.uid == uid)  # type: ignore
        )
    ).scalar_one()
    assert float(row.token_limit_threshold) == 0.35


@pytest.mark.asyncio
async def test_save_token_limit_threshold_defaults_to_point_eight(authed_client, db_session, project_with_class):
    """200 OK; omitting token_limit_threshold stores the 0.8 default on the row."""
    uid, _, _ = project_with_class
    await clear_setting_state(db_session)

    resp = await authed_client.call("POST", _url(uid), json=FULL_PAYLOAD)
    assert resp.status_code == 200
    assert resp.json()["data"]["token_limit_threshold"] == 0.8


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [-0.1, 1.5], ids=["below_zero", "above_one"])
async def test_save_rejects_out_of_range_token_limit_threshold(authed_client, db_session, project_with_class, value):
    """422 when token_limit_threshold is outside 0-1."""
    uid, _, _ = project_with_class
    await clear_setting_state(db_session)

    resp = await authed_client.call(
        "POST", _url(uid), json={**FULL_PAYLOAD, "token_limit_threshold": value}, raise_for_status=False
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_save_requires_auth(client, project_with_class):
    """401 when the request carries no bearer token."""
    uid, _, _ = project_with_class
    resp = await client.call("POST", _url(uid), json=FULL_PAYLOAD, raise_for_status=False)
    assert resp.status_code == 401
