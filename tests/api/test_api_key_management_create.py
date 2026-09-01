import pytest
from uuid import uuid4
from sqlalchemy import select
from middlewares.lang import resolve_message
from services.mysql.model import DfEngineOpenrouterLogs, Employees
from services.mysql.factory import DfEngineApiKeysFactory
from tests.helpers import expected_user, find_by_name

URL = "/api/key-management"

pytestmark = pytest.mark.usefixtures("mock_openrouter")


async def _employee(db_session, employee_uid):
    return (await db_session.execute(select(Employees).where(Employees.uid == employee_uid))).scalar_one()


async def _latest_log_for(db_session, name: str) -> DfEngineOpenrouterLogs:
    await db_session.rollback()  # see the API's own session's committed writes (REPEATABLE READ)
    logs = (
        (
            await db_session.execute(
                select(DfEngineOpenrouterLogs).order_by(DfEngineOpenrouterLogs.created_at.desc()).limit(20)
            )
        )
        .scalars()
        .all()
    )
    return next(log for log in logs if log.request_payload and log.request_payload.get("name") == name)


@pytest.mark.asyncio
async def test_create_success_returns_full_refreshed_list(authed_client, active_employee_uid):
    """200 OK; response body is the refreshed key list, with the new key's fields as given."""
    name = f"Create Test {uuid4().hex[:8]}"
    resp = await authed_client.call(
        "POST",
        URL,
        json={
            "name": name,
            "employee_uid": active_employee_uid,
            "description": "a desc",
            "limit": 50.0,
            "limit_reset": "monthly",
            "is_main": False,
        },
    )
    assert resp.status_code == 200
    item = find_by_name(resp.json()["data"], name)
    assert item["description"] == "a desc"
    assert item["limit"] == 50.0
    assert item["limit_reset"] == "monthly"


@pytest.mark.asyncio
async def test_create_defaults_optional_fields_none(authed_client, active_employee_uid):
    """200 OK; omitting optional fields falls back to null description/limits/expiry."""
    name = f"Create Defaults {uuid4().hex[:8]}"
    resp = await authed_client.call(
        "POST",
        URL,
        json={"name": name, "employee_uid": active_employee_uid, "is_main": False},
    )
    assert resp.status_code == 200
    item = find_by_name(resp.json()["data"], name)
    assert item["description"] is None
    assert item["limit"] is None
    assert item["limit_reset"] is None
    assert item["expires_at"] is None
    assert item["is_expired"] is False


@pytest.mark.asyncio
async def test_create_key_is_masked_in_response(authed_client, active_employee_uid):
    """200 OK; create returns the refreshed list, which masks `key` like every other list read."""
    name = f"Create Masked {uuid4().hex[:8]}"
    resp = await authed_client.call(
        "POST",
        URL,
        json={"name": name, "employee_uid": active_employee_uid, "is_main": False},
    )
    item = find_by_name(resp.json()["data"], name)
    assert "*" in item["key"]


@pytest.mark.asyncio
async def test_create_sets_creater_to_authenticated_user(authed_client, db_session, user_id, active_employee_uid):
    """200 OK; created_by comes from the bearer token's user, not from the request body."""
    name = f"Create Creater {uuid4().hex[:8]}"
    creator = await expected_user(db_session, user_id)

    resp = await authed_client.call(
        "POST",
        URL,
        json={"name": name, "employee_uid": active_employee_uid, "is_main": False},
    )
    item = find_by_name(resp.json()["data"], name)
    assert item["creator"] == creator
    assert item["updater"] is None


@pytest.mark.asyncio
async def test_create_sets_pic_from_employee_uid(authed_client, db_session, active_employee_uid):
    """200 OK; `pic` resolves to {image, nickname} for the employee behind `employee_uid`."""
    employee = await _employee(db_session, active_employee_uid)

    name = f"Create Pic {uuid4().hex[:8]}"
    resp = await authed_client.call(
        "POST",
        URL,
        json={"name": name, "employee_uid": active_employee_uid, "is_main": False},
    )
    item = find_by_name(resp.json()["data"], name)
    assert item["pic"]["nickname"] == employee.nickname


@pytest.mark.asyncio
async def test_create_logs_the_openrouter_call(authed_client, db_session, active_employee_uid):
    """A DfEngineOpenrouterLogs row is written for the POST /keys attempt."""
    name = f"Create Logged {uuid4().hex[:8]}"
    resp = await authed_client.call(
        "POST",
        URL,
        json={"name": name, "employee_uid": active_employee_uid, "is_main": False},
    )
    assert resp.status_code == 200

    log = await _latest_log_for(db_session, name)
    assert log.method == "POST"
    assert log.endpoint.endswith("/keys")
    assert log.response_status_code == 201
    assert log.error_message is None


@pytest.mark.asyncio
async def test_create_second_main_key_for_same_employee_is_409(authed_client, db_session, user_id, active_employee_uid):
    """409 employee_already_has_main_api_key when the PIC already holds a main key;
    a non-main key for the same PIC still succeeds."""
    employee = await _employee(db_session, active_employee_uid)
    DfEngineApiKeysFactory.create(employee_id=employee.id, is_main=True, created_by=int(user_id))

    second_main = await authed_client.call(
        "POST",
        URL,
        json={"name": f"Main {uuid4().hex[:8]}", "employee_uid": active_employee_uid, "is_main": True},
        raise_for_status=False,
    )
    assert second_main.status_code == 409
    assert second_main.json()["message"] == resolve_message("employee_already_has_main_api_key", "en")

    non_main = await authed_client.call(
        "POST",
        URL,
        json={"name": f"Secondary {uuid4().hex[:8]}", "employee_uid": active_employee_uid, "is_main": False},
    )
    assert non_main.status_code == 200


@pytest.mark.asyncio
async def test_create_invalid_expired_at_is_a_validation_error(authed_client, active_employee_uid):
    """422 when `expires_at` isn't a parseable datetime."""
    resp = await authed_client.call(
        "POST",
        URL,
        json={
            "name": f"Invalid Expiry {uuid4().hex[:8]}",
            "employee_uid": active_employee_uid,
            "expires_at": "not-a-date",
        },
        raise_for_status=False,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_past_expiry_is_rejected(authed_client, active_employee_uid):
    """422 api_key_expiry_must_be_in_future when `expires_at` is already in the past."""
    resp = await authed_client.call(
        "POST",
        URL,
        json={
            "name": f"Past Expiry {uuid4().hex[:8]}",
            "employee_uid": active_employee_uid,
            "expires_at": "2000-01-01 00:00:00",
        },
        raise_for_status=False,
    )
    assert resp.status_code == 422
    assert resp.json()["message"] == resolve_message("api_key_expiry_must_be_in_future", "en")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [{"name": ""}, {"name": "x" * 256}, {"description": ""}, {"limit": -1}],
    ids=["empty_name", "oversized_name", "empty_description", "negative_limit"],
)
async def test_create_validation_errors(authed_client, active_employee_uid, overrides):
    """422 for each individually invalid field."""
    payload = {"name": f"Invalid {uuid4().hex[:8]}", "employee_uid": active_employee_uid, "is_main": False}
    payload.update(overrides)
    resp = await authed_client.call("POST", URL, json=payload, raise_for_status=False)
    assert resp.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["name", "employee_uid"])
async def test_create_missing_required_field(authed_client, active_employee_uid, missing):
    """422 when a required field is omitted entirely."""
    payload = {"name": f"Invalid {uuid4().hex[:8]}", "employee_uid": active_employee_uid}
    del payload[missing]
    resp = await authed_client.call("POST", URL, json=payload, raise_for_status=False)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_duplicate_name_same_employee_is_409(authed_client, db_session, user_id, active_employee_uid):
    """409 api_key_already_exists; the app enforces a unique key name per PIC (there's no
    DB-level constraint — only `uid`/`key` are unique — so this is an explicit check)."""
    employee = await _employee(db_session, active_employee_uid)
    name = f"Duplicate {uuid4().hex[:8]}"
    DfEngineApiKeysFactory.create(employee_id=employee.id, name=name, created_by=int(user_id))

    resp = await authed_client.call(
        "POST",
        URL,
        json={"name": name, "employee_uid": active_employee_uid, "is_main": False},
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
        json={"name": f"Unknown {uuid4().hex[:8]}", "employee_uid": str(uuid4())},
        raise_for_status=False,
    )
    assert resp.status_code == 404
    assert resp.json()["message"] == resolve_message("employee_not_found", "en")


@pytest.mark.asyncio
async def test_create_wrong_position_employee_is_422(authed_client, wrong_position_employee_uid):
    """422 employee_position_not_allowed when the employee isn't a (Assistant) Project Manager."""
    resp = await authed_client.call(
        "POST",
        URL,
        json={"name": f"WrongPosition {uuid4().hex[:8]}", "employee_uid": wrong_position_employee_uid},
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
        json={"name": f"Unauth {uuid4().hex[:8]}", "employee_uid": active_employee_uid},
        raise_for_status=False,
    )
    assert resp.status_code == 401
