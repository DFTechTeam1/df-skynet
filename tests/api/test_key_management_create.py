import pytest
from datetime import datetime
from uuid import uuid4
from sqlalchemy import select
from middlewares.lang import resolve_message
from services.mysql.model import DfEngineApiKeys, Employees
from utils.formatter import format_datetime
from tests.helpers import create_record, expected_user, find_by_name

URL = "/api/key-management"


@pytest.mark.asyncio
async def test_create_success_returns_full_refreshed_list(authed_client, active_employee_uid):
    """200 OK; response body is the refreshed key list, with the new key's fields as given."""
    name = f"Create Test {uuid4().hex[:8]}"
    resp = await authed_client.call(
        "POST",
        URL,
        json={
            "name": name,
            "api_key": "sk-or-v1-1234567890abcdef",
            "employee_uid": active_employee_uid,
            "description": "a desc",
            "limit_usage": 50.0,
            "limit_reset": "monthly",
            "is_active": True,
        },
    )
    assert resp.status_code == 200
    item = find_by_name(resp.json()["data"], name)
    assert item["description"] == "a desc"
    assert item["limit_usage"] == 50.0
    assert item["limit_reset"] == "monthly"
    assert item["is_active"] is True


@pytest.mark.asyncio
async def test_create_defaults_is_active_true_and_optional_fields_none(authed_client, active_employee_uid):
    """200 OK; omitting optional fields falls back to active and null description/limits."""
    name = f"Create Defaults {uuid4().hex[:8]}"
    resp = await authed_client.call(
        "POST",
        URL,
        json={"name": name, "api_key": "sk-or-v1-abcdefabcdef", "employee_uid": active_employee_uid},
    )
    assert resp.status_code == 200
    item = find_by_name(resp.json()["data"], name)
    assert item["is_active"] is True
    assert item["description"] is None
    assert item["limit_usage"] is None
    assert item["limit_reset"] is None
    assert item["expired_at"] is None


@pytest.mark.asyncio
async def test_create_with_expired_at_stores_and_returns_it(authed_client, active_employee_uid):
    """200 OK; a "Z"-suffixed (UTC) `expired_at` is stored and echoed back via the detail endpoint."""
    name = f"Create Expiry {uuid4().hex[:8]}"
    resp = await authed_client.call(
        "POST",
        URL,
        json={
            "name": name,
            "api_key": "sk-or-v1-abcdefabcdef",
            "employee_uid": active_employee_uid,
            "expired_at": "2027-12-31T23:59:59Z",
        },
    )
    assert resp.status_code == 200
    item = find_by_name(resp.json()["data"], name)

    detail_resp = await authed_client.call("GET", f"{URL}/{item['uid']}")
    assert detail_resp.json()["data"]["expired_at"] == format_datetime(datetime(2027, 12, 31, 23, 59, 59))


@pytest.mark.asyncio
async def test_create_with_non_utc_offset_expired_at_is_normalized_to_utc(authed_client, active_employee_uid):
    """200 OK; a tz-aware `expired_at` with a non-UTC offset is converted to naive UTC before storage."""
    name = f"Create Expiry Offset {uuid4().hex[:8]}"
    resp = await authed_client.call(
        "POST",
        URL,
        json={
            "name": name,
            "api_key": "sk-or-v1-abcdefabcdef",
            "employee_uid": active_employee_uid,
            # 23:59:59+07:00 (WIB) is 16:59:59 UTC
            "expired_at": "2027-12-31T23:59:59+07:00",
        },
    )
    assert resp.status_code == 200
    item = find_by_name(resp.json()["data"], name)

    detail_resp = await authed_client.call("GET", f"{URL}/{item['uid']}")
    assert detail_resp.json()["data"]["expired_at"] == format_datetime(datetime(2027, 12, 31, 16, 59, 59))


@pytest.mark.asyncio
async def test_create_invalid_expired_at_is_a_validation_error(authed_client, active_employee_uid):
    """422 when `expired_at` isn't a parseable datetime."""
    resp = await authed_client.call(
        "POST",
        URL,
        json={
            "name": f"Invalid Expiry {uuid4().hex[:8]}",
            "api_key": "sk-or-v1-abcdefabcdef",
            "employee_uid": active_employee_uid,
            "expired_at": "not-a-date",
        },
        raise_for_status=False,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_key_is_masked_in_response(authed_client, active_employee_uid):
    """200 OK; create returns the refreshed list, which masks `key` like every other list read."""
    name = f"Create Masked {uuid4().hex[:8]}"
    raw_key = "sk-or-v1-abcdefabcdef1234"
    resp = await authed_client.call(
        "POST",
        URL,
        json={"name": name, "api_key": raw_key, "employee_uid": active_employee_uid},
    )
    item = find_by_name(resp.json()["data"], name)
    assert item["key"] != raw_key
    assert item["key"].startswith("sk-or-v1")
    assert item["key"].endswith("1234")
    assert "•" in item["key"]


@pytest.mark.asyncio
async def test_create_sets_creater_to_authenticated_user(authed_client, db_session, user_id, active_employee_uid):
    """200 OK; created_by comes from the bearer token's user, not from the request body."""
    name = f"Create Creater {uuid4().hex[:8]}"
    creater = await expected_user(db_session, user_id)

    resp = await authed_client.call(
        "POST",
        URL,
        json={"name": name, "api_key": "sk-or-v1-abcdefabcdef", "employee_uid": active_employee_uid},
    )
    item = find_by_name(resp.json()["data"], name)
    assert item["creater"] == creater
    assert item["updater"] is None


@pytest.mark.asyncio
async def test_create_sets_pic_from_employee_uid(authed_client, db_session, active_employee_uid):
    """200 OK; `pic` resolves to {image, nickname} for the employee behind `employee_uid`."""
    employee = (await db_session.execute(select(Employees).where(Employees.uid == active_employee_uid))).scalar_one()

    name = f"Create Pic {uuid4().hex[:8]}"
    resp = await authed_client.call(
        "POST",
        URL,
        json={"name": name, "api_key": "sk-or-v1-abcdefabcdef", "employee_uid": active_employee_uid},
    )
    item = find_by_name(resp.json()["data"], name)
    assert set(item["pic"].keys()) == {"image", "nickname"}
    assert item["pic"]["nickname"] == employee.nickname


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [
        {"name": ""},
        {"name": "x" * 256},
        {"api_key": ""},
        {"description": ""},
        {"limit_usage": -1},
    ],
    ids=[
        "empty_name",
        "oversized_name",
        "empty_api_key",
        "empty_description",
        "negative_limit_usage",
    ],
)
async def test_create_validation_errors(authed_client, active_employee_uid, overrides):
    """422 for each individually invalid field."""
    payload = {
        "name": f"Invalid {uuid4().hex[:8]}",
        "api_key": "sk-or-v1-abcdefabcdef",
        "employee_uid": active_employee_uid,
    }
    payload.update(overrides)
    resp = await authed_client.call("POST", URL, json=payload, raise_for_status=False)
    assert resp.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["name", "api_key", "employee_uid"])
async def test_create_missing_required_field(authed_client, active_employee_uid, missing):
    """422 when a required field is omitted entirely."""
    payload = {
        "name": f"Invalid {uuid4().hex[:8]}",
        "api_key": "sk-or-v1-abcdefabcdef",
        "employee_uid": active_employee_uid,
    }
    del payload[missing]
    resp = await authed_client.call("POST", URL, json=payload, raise_for_status=False)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_duplicate_name_conflict(authed_client, db_session, user_id, active_employee_uid):
    """409 when `name` already belongs to another API key."""
    employee = (await db_session.execute(select(Employees).where(Employees.uid == active_employee_uid))).scalar_one()
    existing = await create_record(
        db_session,
        DfEngineApiKeys,
        dict(
            uid=str(uuid4()),
            name=f"Key {uuid4().hex[:8]}",
            key="sk-or-v1-existingexisting",
            employee_id=employee.id,
            created_by=int(user_id),
        ),
    )
    resp = await authed_client.call(
        "POST",
        URL,
        json={"name": existing.name, "api_key": "sk-or-v1-abcdefabcdef", "employee_uid": active_employee_uid},
        raise_for_status=False,
    )
    assert resp.status_code == 409
    assert resp.json()["message"] == resolve_message("api_key_already_exists", "en")


@pytest.mark.asyncio
async def test_create_unknown_employee_uid_is_404(authed_client):
    """404 employee_not_found when employee_uid matches no employee."""
    resp = await authed_client.call(
        "POST",
        URL,
        json={
            "name": f"Unknown {uuid4().hex[:8]}",
            "api_key": "sk-or-v1-abcdefabcdef",
            "employee_uid": str(uuid4()),
        },
        raise_for_status=False,
    )
    assert resp.status_code == 404
    assert resp.json()["message"] == resolve_message("employee_not_found", "en")


@pytest.mark.asyncio
async def test_create_resigned_employee_is_422(authed_client, resigned_employee_uid):
    """422 employee_already_resigned when employee_uid belongs to a resigned employee."""
    resp = await authed_client.call(
        "POST",
        URL,
        json={
            "name": f"Resigned {uuid4().hex[:8]}",
            "api_key": "sk-or-v1-abcdefabcdef",
            "employee_uid": resigned_employee_uid,
        },
        raise_for_status=False,
    )
    assert resp.status_code == 422
    assert resp.json()["message"] == resolve_message("employee_already_resigned", "en")


@pytest.mark.asyncio
async def test_create_wrong_position_employee_is_422(authed_client, wrong_position_employee_uid):
    """422 employee_position_not_allowed when the employee isn't a (Assistant) Project Manager."""
    resp = await authed_client.call(
        "POST",
        URL,
        json={
            "name": f"WrongPosition {uuid4().hex[:8]}",
            "api_key": "sk-or-v1-abcdefabcdef",
            "employee_uid": wrong_position_employee_uid,
        },
        raise_for_status=False,
    )
    assert resp.status_code == 422
    assert resp.json()["message"] == resolve_message("employee_position_not_allowed", "en")


@pytest.mark.asyncio
async def test_requires_auth(client, active_employee_uid):
    """401 when the request carries no bearer token."""
    resp = await client.call(
        "POST",
        URL,
        json={
            "name": f"Unauth {uuid4().hex[:8]}",
            "api_key": "sk-or-v1-abcdefabcdef",
            "employee_uid": active_employee_uid,
        },
        raise_for_status=False,
    )
    assert resp.status_code == 401
