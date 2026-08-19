import pytest
from uuid import uuid4
from sqlalchemy import select
from middlewares.lang import resolve_message
from services.mysql.model import DfEngineApiKeys, Employees
from utils.formatter import format_datetime
from tests.helpers import create_record, expected_user

URL = "/api/key-management"


@pytest.mark.asyncio
async def test_fetch_detail_success(authed_client, db_session, user_id, active_employee_uid):
    """200 OK; returns the single key's own name/description/is_active by uid."""
    employee = (await db_session.execute(select(Employees).where(Employees.uid == active_employee_uid))).scalar_one()
    row = await create_record(
        db_session,
        DfEngineApiKeys,
        dict(
            uid=str(uuid4()),
            name=f"Key {uuid4().hex[:8]}",
            key="sk-or-v1-abcdefabcdef1234",
            description="a desc",
            employee_id=employee.id,
            created_by=int(user_id),
        ),
    )
    resp = await authed_client.call("GET", f"{URL}/{row.uid}")
    body = resp.json()
    assert resp.status_code == 200
    assert body["message"] == "Success"
    assert body["data"]["name"] == row.name
    assert body["data"]["description"] == "a desc"
    assert body["data"]["is_active"] is True


@pytest.mark.asyncio
async def test_fetch_detail_key_is_returned_unmasked(authed_client, db_session, user_id, active_employee_uid):
    """200 OK; unlike the list endpoint, detail returns the real, unmasked key so the
    frontend can display/copy it."""
    employee = (await db_session.execute(select(Employees).where(Employees.uid == active_employee_uid))).scalar_one()
    row = await create_record(
        db_session,
        DfEngineApiKeys,
        dict(
            uid=str(uuid4()),
            name=f"Key {uuid4().hex[:8]}",
            key="sk-or-v1-abcdefabcdef1234",
            employee_id=employee.id,
            created_by=int(user_id),
        ),
    )
    resp = await authed_client.call("GET", f"{URL}/{row.uid}")
    item = resp.json()["data"]
    assert item["key"] == row.key
    assert "•" not in item["key"]


@pytest.mark.asyncio
async def test_list_still_masks_the_same_key_detail_exposes(authed_client, db_session, user_id, active_employee_uid):
    """200 OK; the list endpoint masks `key` for the exact same row the detail endpoint
    exposes in full — confirms the two are deliberately asymmetric, not a formatting slip."""
    employee = (await db_session.execute(select(Employees).where(Employees.uid == active_employee_uid))).scalar_one()
    row = await create_record(
        db_session,
        DfEngineApiKeys,
        dict(
            uid=str(uuid4()),
            name=f"Key {uuid4().hex[:8]}",
            key="sk-or-v1-abcdefabcdef1234",
            employee_id=employee.id,
            created_by=int(user_id),
        ),
    )
    detail_resp = await authed_client.call("GET", f"{URL}/{row.uid}")
    list_resp = await authed_client.call("GET", URL)

    detail_item = detail_resp.json()["data"]
    list_item = next(item for item in list_resp.json()["data"] if item["name"] == row.name)

    assert detail_item["key"] == row.key
    assert list_item["key"] != row.key
    assert "•" in list_item["key"]


@pytest.mark.asyncio
async def test_fetch_detail_response_shape_has_creater_and_pic(authed_client, db_session, user_id, active_employee_uid):
    """200 OK; internal columns are stripped, resolved creater/updater/pic exposed instead."""
    employee = (await db_session.execute(select(Employees).where(Employees.uid == active_employee_uid))).scalar_one()
    row = await create_record(
        db_session,
        DfEngineApiKeys,
        dict(
            uid=str(uuid4()),
            name=f"Key {uuid4().hex[:8]}",
            key="sk-or-v1-abcdefabcdef1234",
            employee_id=employee.id,
            created_by=int(user_id),
        ),
    )
    creater = await expected_user(db_session, user_id)
    resp = await authed_client.call("GET", f"{URL}/{row.uid}")
    item = resp.json()["data"]

    assert "id" not in item
    assert "employee_id" not in item
    assert "created_by" not in item
    assert "updated_by" not in item
    assert item["creater"] == creater
    assert item["updater"] is None
    assert set(item["pic"].keys()) == {"image", "nickname"}
    assert item["pic"]["nickname"] == employee.nickname


@pytest.mark.asyncio
async def test_fetch_detail_echoes_expired_at(authed_client, db_session, user_id, active_employee_uid):
    """200 OK; a key created with `expired_at` set echoes it back on the detail endpoint."""
    from datetime import datetime

    employee = (await db_session.execute(select(Employees).where(Employees.uid == active_employee_uid))).scalar_one()
    expired_at = datetime(2027, 12, 31, 23, 59, 59)
    row = await create_record(
        db_session,
        DfEngineApiKeys,
        dict(
            uid=str(uuid4()),
            name=f"Key {uuid4().hex[:8]}",
            key="sk-or-v1-abcdefabcdef1234",
            employee_id=employee.id,
            expired_at=expired_at,
            created_by=int(user_id),
        ),
    )
    resp = await authed_client.call("GET", f"{URL}/{row.uid}")
    assert resp.json()["data"]["expired_at"] == format_datetime(expired_at)


@pytest.mark.asyncio
async def test_fetch_detail_unknown_uid_is_404(authed_client):
    """404 api_key_not_found when the uid matches no key."""
    resp = await authed_client.call("GET", f"{URL}/{uuid4()}", raise_for_status=False)
    assert resp.status_code == 404
    assert resp.json()["message"] == resolve_message("api_key_not_found", "en")


@pytest.mark.asyncio
async def test_fetch_detail_requires_auth(client, db_session, user_id, active_employee_uid):
    """401 when the request carries no bearer token."""
    employee = (await db_session.execute(select(Employees).where(Employees.uid == active_employee_uid))).scalar_one()
    row = await create_record(
        db_session,
        DfEngineApiKeys,
        dict(
            uid=str(uuid4()),
            name=f"Key {uuid4().hex[:8]}",
            key="sk-or-v1-abcdefabcdef1234",
            employee_id=employee.id,
            created_by=int(user_id),
        ),
    )
    resp = await client.call("GET", f"{URL}/{row.uid}", raise_for_status=False)
    assert resp.status_code == 401


# --- localization ------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_detail_not_found_message_respects_accept_language(authed_client):
    """404 for both, but the message text differs between Accept-Language: en and id."""
    unknown_uid = uuid4()

    en_resp = await authed_client.call(
        "GET",
        f"{URL}/{unknown_uid}",
        headers={"Accept-Language": "en"},
        raise_for_status=False,
    )
    id_resp = await authed_client.call(
        "GET",
        f"{URL}/{unknown_uid}",
        headers={"Accept-Language": "id"},
        raise_for_status=False,
    )

    assert en_resp.json()["message"] == resolve_message("api_key_not_found", "en")
    assert id_resp.json()["message"] == resolve_message("api_key_not_found", "id")
    assert en_resp.json()["message"] != id_resp.json()["message"]
