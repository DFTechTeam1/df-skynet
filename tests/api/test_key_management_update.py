import pytest
from datetime import datetime
from uuid import uuid4
from sqlalchemy import select
from middlewares.lang import resolve_message
from services.mysql.model import DfEngineApiKeys, DfEngineOpenrouterLogs, Employees
from utils.formatter import format_datetime
from tests.helpers import create_record, expected_user, find_by_name

URL = "/api/key-management"

pytestmark = pytest.mark.usefixtures("mock_openrouter")


async def _employee(db_session, employee_uid):
    return (await db_session.execute(select(Employees).where(Employees.uid == employee_uid))).scalar_one()


async def _fabricate_key(db_session, user_id, employee_id, **overrides):
    """Insert a row directly, bypassing OpenRouter — only valid when the update under test
    won't change limit/limit_reset (so the endpoint never actually calls OpenRouter) or
    fails before reaching that check."""
    data = dict(
        uid=str(uuid4()),
        name=f"Key {uuid4().hex[:8]}",
        key=f"sk-or-v1-{uuid4().hex[:16]}",
        hash=uuid4().hex,
        employee_id=employee_id,
        created_by=int(user_id),
        is_main=False,
        limit=None,
        limit_reset=None,
    )
    data.update(overrides)
    return await create_record(db_session, DfEngineApiKeys, data)


async def _create_key_via_api(authed_client, employee_uid, **overrides) -> dict:
    payload = {"name": f"Key {uuid4().hex[:8]}", "employee_uid": employee_uid, "is_main": False}
    payload.update(overrides)
    resp = await authed_client.call("POST", URL, json=payload)
    return find_by_name(resp.json()["data"], payload["name"])


@pytest.mark.asyncio
async def test_update_full_replace(authed_client, db_session, user_id, active_employee_uid):
    """200 OK; PATCH replaces name/description and sets updater to the current user."""
    employee = await _employee(db_session, active_employee_uid)
    row = await _fabricate_key(db_session, user_id, employee.id)
    updater = await expected_user(db_session, user_id)
    new_name = f"Updated {uuid4().hex[:8]}"

    resp = await authed_client.call(
        "PATCH",
        f"{URL}/{row.uid}",
        json={
            "name": new_name,
            "employee_uid": active_employee_uid,
            "description": "updated desc",
            "is_main": False,
        },
    )
    assert resp.status_code == 200
    item = find_by_name(resp.json()["data"], new_name)
    assert item["description"] == "updated desc"
    assert item["updater"] == updater


@pytest.mark.asyncio
async def test_update_does_not_accept_or_change_expired_at(authed_client, db_session, user_id, active_employee_uid):
    """200 OK; `expires_at` isn't a field on the update payload — OpenRouter's update
    endpoint has no way to change a key's expiry, so it's fixed at creation. Sending it
    anyway is silently ignored (unknown field), and the stored value is untouched."""
    employee = await _employee(db_session, active_employee_uid)
    original_expiry = datetime(2027, 12, 31, 23, 59, 59)
    row = await _fabricate_key(db_session, user_id, employee.id, expired_at=original_expiry)

    resp = await authed_client.call(
        "PATCH",
        f"{URL}/{row.uid}",
        json={
            "name": row.name,
            "employee_uid": active_employee_uid,
            "is_main": False,
            "expires_at": "2030-01-01T00:00:00Z",
        },
    )
    assert resp.status_code == 200
    item = find_by_name(resp.json()["data"], row.name)
    assert item["expired_at"] == format_datetime(original_expiry)


@pytest.mark.asyncio
async def test_update_rename_only_does_not_call_openrouter(authed_client, db_session, user_id, active_employee_uid):
    """200 OK; renaming without touching limit/limit_reset never calls OpenRouter — no new
    DfEngineOpenrouterLogs row is written."""
    employee = await _employee(db_session, active_employee_uid)
    row = await _fabricate_key(db_session, user_id, employee.id)
    new_name = f"{row.name}-renamed"

    resp = await authed_client.call(
        "PATCH",
        f"{URL}/{row.uid}",
        json={"name": new_name, "employee_uid": active_employee_uid, "is_main": False},
    )
    assert resp.status_code == 200

    await db_session.rollback()
    logs = (
        (
            await db_session.execute(
                select(DfEngineOpenrouterLogs).order_by(DfEngineOpenrouterLogs.created_at.desc()).limit(20)
            )
        )
        .scalars()
        .all()
    )
    assert not any(log.request_payload and log.request_payload.get("name") == new_name for log in logs)


@pytest.mark.asyncio
async def test_update_changing_limit_calls_openrouter(authed_client, db_session, active_employee_uid):
    """200 OK; changing `limit`/`limit_reset` calls OpenRouter's PATCH /keys/{hash} and
    writes a matching log row for it. Uses a key created through the real API so it
    carries a genuine OpenRouter hash."""
    created = await _create_key_via_api(authed_client, active_employee_uid)

    resp = await authed_client.call(
        "PATCH",
        f"{URL}/{created['uid']}",
        json={
            "name": created["name"],
            "employee_uid": active_employee_uid,
            "is_main": False,
            "limit": 42.0,
            "limit_reset": "daily",
        },
    )
    assert resp.status_code == 200
    item = find_by_name(resp.json()["data"], created["name"])
    assert item["limit"] == 42.0
    assert item["limit_reset"] == "daily"

    await db_session.rollback()
    logs = (
        (
            await db_session.execute(
                select(DfEngineOpenrouterLogs).order_by(DfEngineOpenrouterLogs.created_at.desc()).limit(20)
            )
        )
        .scalars()
        .all()
    )
    assert any(
        log.method == "PATCH" and log.request_payload and log.request_payload.get("name") == created["name"]
        for log in logs
    )


@pytest.mark.asyncio
async def test_update_resaving_own_main_key_succeeds(authed_client, db_session, user_id, active_employee_uid):
    """200 OK; re-saving a key that is *already* main for its employee with is_main=true
    doesn't false-positive against itself (the exclude-self fix)."""
    employee = await _employee(db_session, active_employee_uid)
    row = await _fabricate_key(db_session, user_id, employee.id, is_main=True)

    resp = await authed_client.call(
        "PATCH",
        f"{URL}/{row.uid}",
        json={"name": row.name, "employee_uid": active_employee_uid, "is_main": True},
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_update_second_main_key_for_employee_is_422(authed_client, db_session, user_id, active_employee_uid):
    """422 employee_already_has_main_api_key when setting is_main=true on a *different* key
    while another key already holds main for that employee."""
    employee = await _employee(db_session, active_employee_uid)
    await _fabricate_key(db_session, user_id, employee.id, is_main=True)
    other = await _fabricate_key(db_session, user_id, employee.id, is_main=False)

    resp = await authed_client.call(
        "PATCH",
        f"{URL}/{other.uid}",
        json={"name": other.name, "employee_uid": active_employee_uid, "is_main": True},
        raise_for_status=False,
    )
    assert resp.status_code == 422
    assert resp.json()["message"] == resolve_message("employee_already_has_main_api_key", "en")


@pytest.mark.asyncio
async def test_update_reassigning_to_resigned_employee_is_422(
    authed_client, db_session, user_id, active_employee_uid, resigned_employee_uid
):
    """422 employee_already_resigned when reassigning the PIC to a resigned employee."""
    employee = await _employee(db_session, active_employee_uid)
    row = await _fabricate_key(db_session, user_id, employee.id)
    resp = await authed_client.call(
        "PATCH",
        f"{URL}/{row.uid}",
        json={"name": row.name, "employee_uid": resigned_employee_uid, "is_main": False},
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
    row = await _fabricate_key(db_session, user_id, employee.id)
    resp = await authed_client.call(
        "PATCH",
        f"{URL}/{row.uid}",
        json={"name": row.name, "employee_uid": wrong_position_employee_uid, "is_main": False},
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
    row = await _fabricate_key(db_session, user_id, employee.id)
    resp = await authed_client.call(
        "PATCH",
        f"{URL}/{row.uid}",
        json={"name": row.name, "employee_uid": active_employee_uid, "is_main": False, "description": "revised"},
    )
    assert resp.status_code == 200
    item = find_by_name(resp.json()["data"], row.name)
    assert item["description"] == "revised"


@pytest.mark.asyncio
async def test_update_unknown_uid_is_404(authed_client, active_employee_uid):
    """404 api_key_not_found when the path uid matches no key."""
    resp = await authed_client.call(
        "PATCH",
        f"{URL}/{uuid4()}",
        json={"name": "x", "employee_uid": active_employee_uid, "is_main": False},
        raise_for_status=False,
    )
    assert resp.status_code == 404
    assert resp.json()["message"] == resolve_message("api_key_not_found", "en")


@pytest.mark.asyncio
async def test_update_renaming_into_another_keys_name_is_allowed(
    authed_client, db_session, user_id, active_employee_uid
):
    """200 OK; `name` has no uniqueness constraint on df_engine_api_keys — renaming a key
    to a name another key already has succeeds rather than 409ing."""
    employee = await _employee(db_session, active_employee_uid)
    target = await _fabricate_key(db_session, user_id, employee.id)
    other = await _fabricate_key(db_session, user_id, employee.id)
    target_name = target.name

    resp = await authed_client.call(
        "PATCH",
        f"{URL}/{other.uid}",
        json={"name": target_name, "employee_uid": active_employee_uid, "is_main": False},
    )
    assert resp.status_code == 200
    matches = [item for item in resp.json()["data"] if item["name"] == target_name]
    assert len(matches) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [{"name": ""}, {"name": "x" * 256}, {"limit": -1}],
    ids=["empty_name", "oversized_name", "negative_limit"],
)
async def test_update_validation_errors(authed_client, active_employee_uid, overrides):
    """422 for each individually invalid field — rejected by payload validation before the
    row is even looked up, so an unknown uid is fine here."""
    payload = {"name": "valid name", "employee_uid": active_employee_uid, "is_main": False}
    payload.update(overrides)
    resp = await authed_client.call("PATCH", f"{URL}/{uuid4()}", json=payload, raise_for_status=False)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_requires_auth(client, db_session, user_id, active_employee_uid):
    """401 when the request carries no bearer token."""
    employee = await _employee(db_session, active_employee_uid)
    row = await _fabricate_key(db_session, user_id, employee.id)
    resp = await client.call(
        "PATCH",
        f"{URL}/{row.uid}",
        json={"name": row.name, "employee_uid": active_employee_uid, "is_main": False},
        raise_for_status=False,
    )
    assert resp.status_code == 401
