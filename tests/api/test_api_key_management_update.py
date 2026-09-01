import pytest
from datetime import timedelta
from uuid import uuid4
from sqlalchemy import select
from middlewares.lang import resolve_message
from services.mysql.model import DfEngineOpenrouterLogs, Employees
from services.mysql.factory import DfEngineApiKeysFactory
from utils import local_time
from tests.helpers import expected_user, find_by_name

URL = "/api/key-management"

pytestmark = pytest.mark.usefixtures("mock_openrouter")


async def _employee(db_session, employee_uid):
    return (await db_session.execute(select(Employees).where(Employees.uid == employee_uid))).scalar_one()


def _key(employee_id, user_id, **overrides):
    return DfEngineApiKeysFactory.create(
        name=f"Key {uuid4().hex[:8]}", employee_id=employee_id, created_by=int(user_id), **overrides
    )


async def _patch_logs(db_session, name: str) -> list:
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
    return [
        log for log in logs if log.method == "PATCH" and log.request_payload and log.request_payload.get("name") == name
    ]


@pytest.mark.asyncio
async def test_update_replaces_name_description_and_sets_updater(
    authed_client, db_session, user_id, active_employee_uid
):
    """200 OK; PATCH replaces name/description and stamps updater with the current user."""
    employee = await _employee(db_session, active_employee_uid)
    row = _key(employee.id, user_id)
    updater = await expected_user(db_session, user_id)
    new_name = f"Updated {uuid4().hex[:8]}"

    resp = await authed_client.call(
        "PATCH",
        f"{URL}/{row.uid}",
        json={"name": new_name, "employee_uid": active_employee_uid, "description": "updated desc", "is_main": False},
    )
    assert resp.status_code == 200
    item = find_by_name(resp.json()["data"], new_name)
    assert item["description"] == "updated desc"
    assert item["updater"] == updater


@pytest.mark.asyncio
async def test_update_description_only_does_not_call_openrouter(
    authed_client, db_session, user_id, active_employee_uid
):
    """200 OK; changing only description/main-flag stays local — no PATCH /keys log row."""
    employee = await _employee(db_session, active_employee_uid)
    row = _key(employee.id, user_id)

    resp = await authed_client.call(
        "PATCH",
        f"{URL}/{row.uid}",
        json={"name": row.name, "employee_uid": active_employee_uid, "description": "revised", "is_main": False},
    )
    assert resp.status_code == 200
    assert await _patch_logs(db_session, row.name) == []


@pytest.mark.asyncio
async def test_update_rename_calls_openrouter(authed_client, db_session, user_id, active_employee_uid):
    """200 OK; a rename is synced to OpenRouter (the key's name lives there too) and logged."""
    employee = await _employee(db_session, active_employee_uid)
    row = _key(employee.id, user_id)
    new_name = f"{row.name}-renamed"

    resp = await authed_client.call(
        "PATCH", f"{URL}/{row.uid}", json={"name": new_name, "employee_uid": active_employee_uid, "is_main": False}
    )
    assert resp.status_code == 200
    assert len(await _patch_logs(db_session, new_name)) == 1


@pytest.mark.asyncio
async def test_update_changing_limit_calls_openrouter(authed_client, db_session, user_id, active_employee_uid):
    """200 OK; changing limit/limit_reset syncs to OpenRouter and writes a PATCH log row."""
    employee = await _employee(db_session, active_employee_uid)
    row = _key(employee.id, user_id)

    resp = await authed_client.call(
        "PATCH",
        f"{URL}/{row.uid}",
        json={
            "name": row.name,
            "employee_uid": active_employee_uid,
            "is_main": False,
            "limit": 42.0,
            "limit_reset": "daily",
        },
    )
    assert resp.status_code == 200
    item = find_by_name(resp.json()["data"], row.name)
    assert item["limit"] == 42.0
    assert item["limit_reset"] == "daily"
    assert len(await _patch_logs(db_session, row.name)) == 1


@pytest.mark.asyncio
async def test_update_resaving_own_main_key_succeeds(authed_client, db_session, user_id, active_employee_uid):
    """200 OK; re-saving a key that is *already* main with is_main=true doesn't false-positive
    against itself (exclude-self on the single-main check)."""
    employee = await _employee(db_session, active_employee_uid)
    row = _key(employee.id, user_id, is_main=True)
    resp = await authed_client.call(
        "PATCH", f"{URL}/{row.uid}", json={"name": row.name, "employee_uid": active_employee_uid, "is_main": True}
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_update_promoting_to_main_when_another_exists_is_409(
    authed_client, db_session, user_id, active_employee_uid
):
    """409 employee_already_has_main_api_key when setting is_main=true on one key while
    another key already holds main for that PIC."""
    employee = await _employee(db_session, active_employee_uid)
    _key(employee.id, user_id, is_main=True)
    other = _key(employee.id, user_id, is_main=False)

    resp = await authed_client.call(
        "PATCH",
        f"{URL}/{other.uid}",
        json={"name": other.name, "employee_uid": active_employee_uid, "is_main": True},
        raise_for_status=False,
    )
    assert resp.status_code == 409
    assert resp.json()["message"] == resolve_message("employee_already_has_main_api_key", "en")


@pytest.mark.asyncio
async def test_update_rename_into_a_sibling_keys_name_is_409(authed_client, db_session, user_id, active_employee_uid):
    """409 api_key_already_exists; key names are unique per PIC (app-level check)."""
    employee = await _employee(db_session, active_employee_uid)
    target = _key(employee.id, user_id)
    other = _key(employee.id, user_id)

    resp = await authed_client.call(
        "PATCH",
        f"{URL}/{other.uid}",
        json={"name": target.name, "employee_uid": active_employee_uid, "is_main": False},
        raise_for_status=False,
    )
    assert resp.status_code == 409
    assert resp.json()["message"] == resolve_message("api_key_already_exists", "en")


@pytest.mark.asyncio
async def test_update_renaming_to_its_own_current_name_succeeds(
    authed_client, db_session, user_id, active_employee_uid
):
    """200 OK; renaming a key to its own current name doesn't trip the uniqueness check."""
    employee = await _employee(db_session, active_employee_uid)
    row = _key(employee.id, user_id)
    resp = await authed_client.call(
        "PATCH",
        f"{URL}/{row.uid}",
        json={"name": row.name, "employee_uid": active_employee_uid, "is_main": False, "description": "revised"},
    )
    assert resp.status_code == 200
    assert find_by_name(resp.json()["data"], row.name)["description"] == "revised"


@pytest.mark.asyncio
async def test_update_expired_key_is_422(authed_client, db_session, user_id, active_employee_uid):
    """422 api_key_expired; an expired key can only be deleted."""
    employee = await _employee(db_session, active_employee_uid)
    row = _key(employee.id, user_id, expires_at=local_time() - timedelta(days=1))
    resp = await authed_client.call(
        "PATCH",
        f"{URL}/{row.uid}",
        json={"name": row.name, "employee_uid": active_employee_uid, "is_main": False},
        raise_for_status=False,
    )
    assert resp.status_code == 422
    assert resp.json()["message"] == resolve_message("api_key_expired", "en")


@pytest.mark.asyncio
async def test_update_key_with_detached_pic_is_422(authed_client, db_session, user_id, active_employee_uid):
    """422 api_key_employee_deleted when the key's PIC is no longer set."""
    row = _key(None, user_id)
    resp = await authed_client.call(
        "PATCH",
        f"{URL}/{row.uid}",
        json={"name": row.name, "employee_uid": active_employee_uid, "is_main": False},
        raise_for_status=False,
    )
    assert resp.status_code == 422
    assert resp.json()["message"] == resolve_message("api_key_employee_deleted", "en")


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
async def test_update_row_without_hash_is_404(authed_client, db_session, user_id, active_employee_uid):
    """404; a key with no OpenRouter hash on record is invisible to the endpoint."""
    employee = await _employee(db_session, active_employee_uid)
    row = _key(employee.id, user_id, hash=None)
    resp = await authed_client.call(
        "PATCH",
        f"{URL}/{row.uid}",
        json={"name": row.name, "employee_uid": active_employee_uid, "is_main": False},
        raise_for_status=False,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [{"name": ""}, {"name": "x" * 256}, {"limit": -1}],
    ids=["empty_name", "oversized_name", "negative_limit"],
)
async def test_update_validation_errors(authed_client, active_employee_uid, overrides):
    """422 for each individually invalid field — payload validation runs before the lookup."""
    payload = {"name": "valid name", "employee_uid": active_employee_uid, "is_main": False}
    payload.update(overrides)
    resp = await authed_client.call("PATCH", f"{URL}/{uuid4()}", json=payload, raise_for_status=False)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_requires_auth(client, db_session, user_id, active_employee_uid):
    """401 when the request carries no bearer token."""
    employee = await _employee(db_session, active_employee_uid)
    row = _key(employee.id, user_id)
    resp = await client.call(
        "PATCH",
        f"{URL}/{row.uid}",
        json={"name": row.name, "employee_uid": active_employee_uid, "is_main": False},
        raise_for_status=False,
    )
    assert resp.status_code == 401
