import pytest
from datetime import datetime
from uuid import uuid4
from sqlalchemy import select
from middlewares.lang import resolve_message
from services.mysql.model import DfEngineApiKeys, Employees
from utils.formatter import format_datetime
from tests.helpers import create_record, expected_user, find_by_name

URL = "/api/key-management"


async def _employee(db_session, employee_uid):
    return (await db_session.execute(select(Employees).where(Employees.uid == employee_uid))).scalar_one()


@pytest.mark.asyncio
async def test_update_full_replace(authed_client, db_session, user_id, active_employee_uid):
    """200 OK; PATCH replaces name/description/is_active and sets updater to the current user."""
    employee = await _employee(db_session, active_employee_uid)
    row = await create_record(
        db_session,
        DfEngineApiKeys,
        dict(
            uid=str(uuid4()),
            name=f"Key {uuid4().hex[:8]}",
            key="sk-or-v1-oldoldoldold",
            employee_id=employee.id,
            created_by=int(user_id),
        ),
    )
    updater = await expected_user(db_session, user_id)
    new_name = f"Updated {uuid4().hex[:8]}"

    resp = await authed_client.call(
        "PATCH",
        f"{URL}/{row.uid}",
        json={
            "name": new_name,
            "api_key": "sk-or-v1-newnewnewnew",
            "employee_uid": active_employee_uid,
            "description": "updated desc",
            "is_active": True,
        },
    )
    assert resp.status_code == 200
    item = find_by_name(resp.json()["data"], new_name)
    assert item["description"] == "updated desc"
    assert item["updater"] == updater


@pytest.mark.asyncio
async def test_update_can_set_expired_at(authed_client, db_session, user_id, active_employee_uid):
    """200 OK; PATCH can set `expired_at` on a key that previously had none."""
    employee = await _employee(db_session, active_employee_uid)
    row = await create_record(
        db_session,
        DfEngineApiKeys,
        dict(
            uid=str(uuid4()),
            name=f"Key {uuid4().hex[:8]}",
            key="sk-or-v1-oldoldoldold",
            employee_id=employee.id,
            created_by=int(user_id),
        ),
    )
    resp = await authed_client.call(
        "PATCH",
        f"{URL}/{row.uid}",
        json={
            "name": row.name,
            "api_key": row.key,
            "employee_uid": active_employee_uid,
            "expired_at": "2027-12-31T23:59:59Z",
        },
    )
    assert resp.status_code == 200

    detail_resp = await authed_client.call("GET", f"{URL}/{row.uid}")
    assert detail_resp.json()["data"]["expired_at"] == format_datetime(datetime(2027, 12, 31, 23, 59, 59))


@pytest.mark.asyncio
async def test_update_can_clear_expired_at(authed_client, db_session, user_id, active_employee_uid):
    """200 OK; PATCH without `expired_at` clears a previously-set expiry (full-replace semantics)."""
    employee = await _employee(db_session, active_employee_uid)
    row = await create_record(
        db_session,
        DfEngineApiKeys,
        dict(
            uid=str(uuid4()),
            name=f"Key {uuid4().hex[:8]}",
            key="sk-or-v1-oldoldoldold",
            employee_id=employee.id,
            expired_at=datetime(2027, 12, 31, 23, 59, 59),
            created_by=int(user_id),
        ),
    )
    resp = await authed_client.call(
        "PATCH",
        f"{URL}/{row.uid}",
        json={"name": row.name, "api_key": row.key, "employee_uid": active_employee_uid},
    )
    assert resp.status_code == 200

    detail_resp = await authed_client.call("GET", f"{URL}/{row.uid}")
    assert detail_resp.json()["data"]["expired_at"] is None


@pytest.mark.asyncio
async def test_update_reassigning_to_resigned_employee_is_422(
    authed_client, db_session, user_id, active_employee_uid, resigned_employee_uid
):
    """422 employee_already_resigned when reassigning the PIC to a resigned employee."""
    employee = await _employee(db_session, active_employee_uid)
    row = await create_record(
        db_session,
        DfEngineApiKeys,
        dict(
            uid=str(uuid4()),
            name=f"Key {uuid4().hex[:8]}",
            key="sk-or-v1-oldoldoldold",
            employee_id=employee.id,
            created_by=int(user_id),
        ),
    )
    resp = await authed_client.call(
        "PATCH",
        f"{URL}/{row.uid}",
        json={"name": row.name, "api_key": row.key, "employee_uid": resigned_employee_uid},
        raise_for_status=False,
    )
    assert resp.status_code == 422
    assert resp.json()["message"] == resolve_message("employee_already_resigned", "en")


@pytest.mark.asyncio
async def test_update_reassigning_to_wrong_position_employee_is_422(
    authed_client, db_session, user_id, active_employee_uid, wrong_position_employee_uid
):
    """422 employee_position_not_allowed when reassigning the PIC to a non-PM/APM employee."""
    employee = await _employee(db_session, active_employee_uid)
    row = await create_record(
        db_session,
        DfEngineApiKeys,
        dict(
            uid=str(uuid4()),
            name=f"Key {uuid4().hex[:8]}",
            key="sk-or-v1-oldoldoldold",
            employee_id=employee.id,
            created_by=int(user_id),
        ),
    )
    resp = await authed_client.call(
        "PATCH",
        f"{URL}/{row.uid}",
        json={"name": row.name, "api_key": row.key, "employee_uid": wrong_position_employee_uid},
        raise_for_status=False,
    )
    assert resp.status_code == 422
    assert resp.json()["message"] == resolve_message("employee_position_not_allowed", "en")


@pytest.mark.asyncio
async def test_update_renaming_to_its_own_current_name_succeeds(
    authed_client, db_session, user_id, active_employee_uid
):
    """200 OK; renaming a key to its own current name doesn't trip the uniqueness conflict."""
    employee = await _employee(db_session, active_employee_uid)
    row = await create_record(
        db_session,
        DfEngineApiKeys,
        dict(
            uid=str(uuid4()),
            name=f"Key {uuid4().hex[:8]}",
            key="sk-or-v1-oldoldoldold",
            employee_id=employee.id,
            created_by=int(user_id),
        ),
    )
    resp = await authed_client.call(
        "PATCH",
        f"{URL}/{row.uid}",
        json={"name": row.name, "api_key": "sk-or-v1-revisedrevised", "employee_uid": active_employee_uid},
    )
    assert resp.status_code == 200
    item = find_by_name(resp.json()["data"], row.name)
    assert item["key"].endswith("ised")


@pytest.mark.asyncio
async def test_update_unknown_uid_is_404(authed_client, active_employee_uid):
    """404 api_key_not_found when the path uid matches no key."""
    resp = await authed_client.call(
        "PATCH",
        f"{URL}/{uuid4()}",
        json={"name": "x", "api_key": "sk-or-v1-xxxxxxxxxxxx", "employee_uid": active_employee_uid},
        raise_for_status=False,
    )
    assert resp.status_code == 404
    assert resp.json()["message"] == resolve_message("api_key_not_found", "en")


@pytest.mark.asyncio
async def test_update_rename_into_collision_is_409(authed_client, db_session, user_id, active_employee_uid):
    """409 when renaming a key to a name another key already has."""
    employee = await _employee(db_session, active_employee_uid)
    target = await create_record(
        db_session,
        DfEngineApiKeys,
        dict(
            uid=str(uuid4()),
            name=f"Key {uuid4().hex[:8]}",
            key="sk-or-v1-targettarget",
            employee_id=employee.id,
            created_by=int(user_id),
        ),
    )
    other = await create_record(
        db_session,
        DfEngineApiKeys,
        dict(
            uid=str(uuid4()),
            name=f"Key {uuid4().hex[:8]}",
            key="sk-or-v1-otherotherot",
            employee_id=employee.id,
            created_by=int(user_id),
        ),
    )
    resp = await authed_client.call(
        "PATCH",
        f"{URL}/{other.uid}",
        json={"name": target.name, "api_key": "sk-or-v1-yyyyyyyyyyyy", "employee_uid": active_employee_uid},
        raise_for_status=False,
    )
    assert resp.status_code == 409
    assert resp.json()["message"] == resolve_message("api_key_already_exists", "en")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [{"name": ""}, {"api_key": ""}],
    ids=["empty_name", "empty_api_key"],
)
async def test_update_validation_errors(authed_client, db_session, user_id, active_employee_uid, overrides):
    """422 for each individually invalid field."""
    employee = await _employee(db_session, active_employee_uid)
    row = await create_record(
        db_session,
        DfEngineApiKeys,
        dict(
            uid=str(uuid4()),
            name=f"Key {uuid4().hex[:8]}",
            key="sk-or-v1-oldoldoldold",
            employee_id=employee.id,
            created_by=int(user_id),
        ),
    )
    payload = {"name": "valid name", "api_key": "sk-or-v1-validvalidva", "employee_uid": active_employee_uid}
    payload.update(overrides)
    resp = await authed_client.call("PATCH", f"{URL}/{row.uid}", json=payload, raise_for_status=False)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_requires_auth(client, db_session, user_id, active_employee_uid):
    """401 when the request carries no bearer token."""
    employee = await _employee(db_session, active_employee_uid)
    row = await create_record(
        db_session,
        DfEngineApiKeys,
        dict(
            uid=str(uuid4()),
            name=f"Key {uuid4().hex[:8]}",
            key="sk-or-v1-oldoldoldold",
            employee_id=employee.id,
            created_by=int(user_id),
        ),
    )
    resp = await client.call(
        "PATCH",
        f"{URL}/{row.uid}",
        json={"name": row.name, "api_key": "sk-or-v1-yyyyyyyyyyyy", "employee_uid": active_employee_uid},
        raise_for_status=False,
    )
    assert resp.status_code == 401
