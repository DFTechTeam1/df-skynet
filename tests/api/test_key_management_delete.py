import pytest
from uuid import uuid4
from sqlalchemy import select
from middlewares.lang import resolve_message
from services.mysql.model import DfEngineApiKeys, Employees
from tests.helpers import create_record, response_names

URL = "/api/key-management"


async def _employee(db_session, employee_uid):
    return (await db_session.execute(select(Employees).where(Employees.uid == employee_uid))).scalar_one()


@pytest.mark.asyncio
async def test_delete_success(authed_client, db_session, user_id, active_employee_uid):
    """200 OK; deleted key no longer appears in the refreshed list."""
    employee = await _employee(db_session, active_employee_uid)
    row = await create_record(
        db_session,
        DfEngineApiKeys,
        dict(
            uid=str(uuid4()),
            name=f"Key {uuid4().hex[:8]}",
            key="sk-or-v1-deletemedelet",
            employee_id=employee.id,
            created_by=int(user_id),
        ),
    )
    resp = await authed_client.call("DELETE", f"{URL}/{row.uid}")
    assert resp.status_code == 200
    assert row.name not in response_names(resp.json())


@pytest.mark.asyncio
async def test_delete_is_soft_row_still_exists_with_deleted_at_set(
    authed_client, db_session, user_id, active_employee_uid
):
    """200 OK; the row isn't hard-deleted — it still exists in the DB with `deleted_at` set,
    so other tables can keep referencing its id."""
    employee = await _employee(db_session, active_employee_uid)
    row = await create_record(
        db_session,
        DfEngineApiKeys,
        dict(
            uid=str(uuid4()),
            name=f"Key {uuid4().hex[:8]}",
            key="sk-or-v1-deletemedelet",
            employee_id=employee.id,
            created_by=int(user_id),
        ),
    )
    row_id = row.id
    resp = await authed_client.call("DELETE", f"{URL}/{row.uid}")
    assert resp.status_code == 200

    # `db_session`'s transaction snapshot (REPEATABLE READ) predates the API call's own
    # session committing the delete — roll back to start a fresh transaction that sees it.
    await db_session.rollback()
    still_in_db = (await db_session.execute(select(DfEngineApiKeys).where(DfEngineApiKeys.id == row_id))).scalar_one()
    assert still_in_db.deleted_at is not None


@pytest.mark.asyncio
async def test_delete_excludes_key_from_detail_endpoint(authed_client, db_session, user_id, active_employee_uid):
    """200 OK on delete; the detail endpoint then 404s for the same uid."""
    employee = await _employee(db_session, active_employee_uid)
    row = await create_record(
        db_session,
        DfEngineApiKeys,
        dict(
            uid=str(uuid4()),
            name=f"Key {uuid4().hex[:8]}",
            key="sk-or-v1-deletemedelet",
            employee_id=employee.id,
            created_by=int(user_id),
        ),
    )
    delete_resp = await authed_client.call("DELETE", f"{URL}/{row.uid}")
    assert delete_resp.status_code == 200

    detail_resp = await authed_client.call("GET", f"{URL}/{row.uid}", raise_for_status=False)
    assert detail_resp.status_code == 404
    assert detail_resp.json()["message"] == resolve_message("api_key_not_found", "en")


@pytest.mark.asyncio
async def test_deleted_key_name_can_be_reused_by_a_new_key(authed_client, db_session, user_id, active_employee_uid):
    """200 OK; once a key is soft-deleted, its name is free — creating a new key with the
    same name succeeds instead of 409ing."""
    employee = await _employee(db_session, active_employee_uid)
    name = f"Reusable {uuid4().hex[:8]}"
    row = await create_record(
        db_session,
        DfEngineApiKeys,
        dict(
            uid=str(uuid4()),
            name=name,
            key="sk-or-v1-deletemedelet",
            employee_id=employee.id,
            created_by=int(user_id),
        ),
    )
    delete_resp = await authed_client.call("DELETE", f"{URL}/{row.uid}")
    assert delete_resp.status_code == 200

    create_resp = await authed_client.call(
        "POST",
        URL,
        json={"name": name, "api_key": "sk-or-v1-newnewnewnew", "employee_uid": active_employee_uid},
        raise_for_status=False,
    )
    assert create_resp.status_code == 200
    assert name in response_names(create_resp.json())


@pytest.mark.asyncio
async def test_update_on_a_deleted_key_is_404(authed_client, db_session, user_id, active_employee_uid):
    """404 api_key_not_found; a soft-deleted key can't be updated, same as it can't be fetched."""
    employee = await _employee(db_session, active_employee_uid)
    row = await create_record(
        db_session,
        DfEngineApiKeys,
        dict(
            uid=str(uuid4()),
            name=f"Key {uuid4().hex[:8]}",
            key="sk-or-v1-deletemedelet",
            employee_id=employee.id,
            created_by=int(user_id),
        ),
    )
    delete_resp = await authed_client.call("DELETE", f"{URL}/{row.uid}")
    assert delete_resp.status_code == 200

    update_resp = await authed_client.call(
        "PATCH",
        f"{URL}/{row.uid}",
        json={"name": row.name, "api_key": "sk-or-v1-yyyyyyyyyyyy", "employee_uid": active_employee_uid},
        raise_for_status=False,
    )
    assert update_resp.status_code == 404
    assert update_resp.json()["message"] == resolve_message("api_key_not_found", "en")


@pytest.mark.asyncio
async def test_delete_twice_is_404_on_the_second_call(authed_client, db_session, user_id, active_employee_uid):
    """First delete is 200 OK; repeating it is 404 api_key_not_found since the row is already gone."""
    employee = await _employee(db_session, active_employee_uid)
    row = await create_record(
        db_session,
        DfEngineApiKeys,
        dict(
            uid=str(uuid4()),
            name=f"Key {uuid4().hex[:8]}",
            key="sk-or-v1-deletemedelet",
            employee_id=employee.id,
            created_by=int(user_id),
        ),
    )
    first = await authed_client.call("DELETE", f"{URL}/{row.uid}")
    assert first.status_code == 200
    second = await authed_client.call("DELETE", f"{URL}/{row.uid}", raise_for_status=False)
    assert second.status_code == 404
    assert second.json()["message"] == resolve_message("api_key_not_found", "en")


@pytest.mark.asyncio
async def test_delete_unknown_uid_is_404(authed_client):
    """404 api_key_not_found when the uid matches no key."""
    resp = await authed_client.call("DELETE", f"{URL}/{uuid4()}", raise_for_status=False)
    assert resp.status_code == 404
    assert resp.json()["message"] == resolve_message("api_key_not_found", "en")


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
            key="sk-or-v1-deletemedelet",
            employee_id=employee.id,
            created_by=int(user_id),
        ),
    )
    resp = await client.call("DELETE", f"{URL}/{row.uid}", raise_for_status=False)
    assert resp.status_code == 401


# --- localization ------------------------------------------------------------


@pytest.mark.asyncio
async def test_not_found_message_respects_accept_language(authed_client):
    """404; the not_found message text is localized per the Accept-Language header, differing between en and id."""
    unknown_uid = uuid4()

    en_resp = await authed_client.call(
        "DELETE",
        f"{URL}/{unknown_uid}",
        headers={"Accept-Language": "en"},
        raise_for_status=False,
    )
    id_resp = await authed_client.call(
        "DELETE",
        f"{URL}/{unknown_uid}",
        headers={"Accept-Language": "id"},
        raise_for_status=False,
    )

    assert en_resp.json()["message"] == resolve_message("api_key_not_found", "en")
    assert id_resp.json()["message"] == resolve_message("api_key_not_found", "id")
    assert en_resp.json()["message"] != id_resp.json()["message"]
