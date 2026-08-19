import pytest
from datetime import datetime, timedelta
from uuid import uuid4
from sqlalchemy import select
from services.mysql.model import DfEngineApiKeys, Employees
from utils import local_time
from utils.formatter import format_datetime
from tests.helpers import create_record, expected_user, find_by_name, response_names

URL = "/api/key-management"


@pytest.mark.asyncio
async def test_fetch_all_api_keys(authed_client):
    """200 OK; returns a list of API keys."""
    resp = await authed_client.call("GET", URL)
    body = resp.json()
    assert resp.status_code == 200
    assert body["message"] == "Success"
    assert isinstance(body["data"], list)


@pytest.mark.asyncio
async def test_fetch_includes_inactive_rows(authed_client, db_session, user_id, active_employee_uid):
    """200 OK; inactive keys are still included, unlike the active-only prompt-template list."""
    employee = (await db_session.execute(select(Employees).where(Employees.uid == active_employee_uid))).scalar_one()
    inactive = await create_record(
        db_session,
        DfEngineApiKeys,
        dict(
            uid=str(uuid4()),
            name=f"Key {uuid4().hex[:8]}",
            key="sk-or-v1-inactiveinactive",
            employee_id=employee.id,
            is_active=False,
            created_by=int(user_id),
        ),
    )
    resp = await authed_client.call("GET", URL)
    assert inactive.name in response_names(resp.json())


@pytest.mark.asyncio
async def test_newest_first_ordering(authed_client, db_session, user_id, active_employee_uid):
    """200 OK; list is ordered by created_at descending, newest key first."""
    employee = (await db_session.execute(select(Employees).where(Employees.uid == active_employee_uid))).scalar_one()
    now = local_time()
    older = await create_record(
        db_session,
        DfEngineApiKeys,
        dict(
            uid=str(uuid4()),
            name=f"Order {uuid4().hex[:8]}-older",
            key="sk-or-v1-olderolderolder",
            employee_id=employee.id,
            created_by=int(user_id),
            created_at=now - timedelta(seconds=5),
        ),
    )
    newer = await create_record(
        db_session,
        DfEngineApiKeys,
        dict(
            uid=str(uuid4()),
            name=f"Order {uuid4().hex[:8]}-newer",
            key="sk-or-v1-newernewernewer",
            employee_id=employee.id,
            created_by=int(user_id),
            created_at=now,
        ),
    )
    resp = await authed_client.call("GET", URL)
    found = response_names(resp.json())
    assert found.index(newer.name) < found.index(older.name)


@pytest.mark.asyncio
async def test_fetch_shows_expired_at_when_set(authed_client, db_session, user_id, active_employee_uid):
    """200 OK; a key with `expired_at` set shows it in the list (not null, unlike the common case)."""
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
    resp = await authed_client.call("GET", URL)
    item = find_by_name(resp.json()["data"], row.name)
    assert item["expired_at"] == format_datetime(expired_at)


@pytest.mark.asyncio
async def test_fetch_expired_at_is_null_by_default(authed_client, db_session, user_id, active_employee_uid):
    """200 OK; a key created without `expired_at` shows it as null in the list."""
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
    resp = await authed_client.call("GET", URL)
    item = find_by_name(resp.json()["data"], row.name)
    assert item["expired_at"] is None


@pytest.mark.asyncio
async def test_key_is_masked(authed_client, db_session, user_id, active_employee_uid):
    """200 OK; `key` is masked to the first 8 and last 4 characters."""
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
    resp = await authed_client.call("GET", URL)
    item = find_by_name(resp.json()["data"], row.name)
    assert item["key"] != row.key
    assert item["key"].startswith("sk-or-v1")
    assert item["key"].endswith("1234")
    assert "•" in item["key"]


@pytest.mark.asyncio
async def test_response_shape_has_creater_pic_not_internal_columns(
    authed_client, db_session, user_id, active_employee_uid
):
    """200 OK; internal columns (id, employee_id, created_by_user, ...) are stripped, resolved creater/updater/pic exposed instead."""
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

    resp = await authed_client.call("GET", URL)
    item = find_by_name(resp.json()["data"], row.name)

    assert "id" not in item
    assert "employee_id" not in item
    assert "created_by" not in item
    assert "updated_by" not in item
    assert "created_by_user" not in item
    assert "updated_by_user" not in item
    assert "employees" not in item
    assert item["creater"] == creater
    assert item["updater"] is None
    assert set(item["pic"].keys()) == {"image", "nickname"}
    assert item["pic"]["nickname"] == employee.nickname


@pytest.mark.asyncio
async def test_action_flags_are_booleans(authed_client, db_session, user_id, active_employee_uid):
    """200 OK; each item's action block has exactly the fetch/update/delete flags, all booleans."""
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
    resp = await authed_client.call("GET", URL)
    item = find_by_name(resp.json()["data"], row.name)
    assert set(item["action"].keys()) == {
        "can_fetch_key_management",
        "can_update_key_management",
        "can_delete_key_management",
    }
    assert all(isinstance(v, bool) for v in item["action"].values())


@pytest.mark.asyncio
async def test_requires_auth(client):
    """401 when the request carries no bearer token."""
    resp = await client.call("GET", URL, raise_for_status=False)
    assert resp.status_code == 401
