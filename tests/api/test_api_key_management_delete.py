import pytest
from datetime import timedelta
from uuid import uuid4
from sqlalchemy import select
from middlewares.lang import resolve_message
from services.mysql.model import DfEngineApiKeys, DfEngineApiSnapshots, DfEngineOpenrouterLogs, Employees
from services.mysql.factory import DfEngineApiKeysFactory
from utils import local_time
from tests.helpers import response_names

URL = "/api/key-management"

pytestmark = pytest.mark.usefixtures("mock_openrouter")


async def _employee(db_session, employee_uid):
    return (await db_session.execute(select(Employees).where(Employees.uid == employee_uid))).scalar_one()


def _key(employee_id, user_id, **overrides):
    """A key row with a genuine-looking hash + creator, so it passes the endpoint's
    `created_by IS NOT NULL AND hash IS NOT NULL` filter. OpenRouter is mocked, so the
    fake hash is fine even for the paths that do call DELETE /keys/{hash}."""
    return DfEngineApiKeysFactory.create(
        name=f"Key {uuid4().hex[:8]}", employee_id=employee_id, created_by=int(user_id), **overrides
    )


@pytest.mark.asyncio
async def test_delete_success(authed_client, db_session, user_id, active_employee_uid):
    """200 OK; deleted key no longer appears in the refreshed list."""
    employee = await _employee(db_session, active_employee_uid)
    row = _key(employee.id, user_id)
    resp = await authed_client.call("DELETE", f"{URL}/{row.uid}")
    assert resp.status_code == 200
    assert row.name not in response_names(resp.json())


@pytest.mark.asyncio
async def test_delete_is_hard_row_no_longer_exists(authed_client, db_session, user_id, active_employee_uid):
    """200 OK; the row is hard-deleted — there's no status column to soft-delete it."""
    employee = await _employee(db_session, active_employee_uid)
    row = _key(employee.id, user_id)
    row_uid = row.uid
    resp = await authed_client.call("DELETE", f"{URL}/{row_uid}")
    assert resp.status_code == 200

    await db_session.rollback()
    gone = (
        await db_session.execute(select(DfEngineApiKeys).where(DfEngineApiKeys.uid == row_uid))
    ).scalar_one_or_none()
    assert gone is None


@pytest.mark.asyncio
async def test_delete_archives_a_snapshot_on_clean_revoke(authed_client, db_session, user_id, active_employee_uid):
    """200 OK; when OpenRouter confirms the revoke, a df_engine_api_snapshots row is
    written carrying the key's details."""
    employee = await _employee(db_session, active_employee_uid)
    nickname = employee.nickname  # capture before rollback expires the ORM instance
    row = _key(employee.id, user_id, employee_name=nickname)
    row_name, row_key = row.name, row.key

    resp = await authed_client.call("DELETE", f"{URL}/{row.uid}")
    assert resp.status_code == 200

    await db_session.rollback()
    snapshot = (
        await db_session.execute(select(DfEngineApiSnapshots).where(DfEngineApiSnapshots.key == row_key))
    ).scalar_one()
    assert snapshot.name == row_name
    assert snapshot.employee_name == nickname


@pytest.mark.asyncio
async def test_delete_blocks_main_key(authed_client, db_session, user_id, active_employee_uid):
    """422 cannot_delete_main_api_key; a non-expired main key isn't deleted or snapshotted."""
    employee = await _employee(db_session, active_employee_uid)
    row = _key(employee.id, user_id, is_main=True)
    row_id, row_key = row.id, row.key

    resp = await authed_client.call("DELETE", f"{URL}/{row.uid}", raise_for_status=False)
    assert resp.status_code == 422
    assert resp.json()["message"] == resolve_message("cannot_delete_main_api_key", "en")

    await db_session.rollback()
    still_there = (
        await db_session.execute(select(DfEngineApiKeys).where(DfEngineApiKeys.id == row_id))
    ).scalar_one_or_none()
    assert still_there is not None
    no_snapshot = (
        await db_session.execute(select(DfEngineApiSnapshots).where(DfEngineApiSnapshots.key == row_key))
    ).scalar_one_or_none()
    assert no_snapshot is None


@pytest.mark.asyncio
async def test_delete_expired_main_key_is_allowed(authed_client, db_session, user_id, active_employee_uid):
    """200 OK; the main-key guard is lifted once the key has expired — otherwise it would
    be both undeletable and unupdatable."""
    employee = await _employee(db_session, active_employee_uid)
    row = _key(employee.id, user_id, is_main=True, expires_at=local_time() - timedelta(days=1))
    resp = await authed_client.call("DELETE", f"{URL}/{row.uid}")
    assert resp.status_code == 200
    assert row.name not in response_names(resp.json())


@pytest.mark.asyncio
async def test_delete_row_without_hash_is_404(authed_client, db_session, user_id, active_employee_uid):
    """404; a key with no OpenRouter hash on record is invisible to the endpoint."""
    employee = await _employee(db_session, active_employee_uid)
    row = _key(employee.id, user_id, hash=None)
    resp = await authed_client.call("DELETE", f"{URL}/{row.uid}", raise_for_status=False)
    assert resp.status_code == 404
    assert resp.json()["message"] == resolve_message("api_key_not_found", "en")


@pytest.mark.asyncio
async def test_delete_excludes_key_from_copy_endpoint(authed_client, db_session, user_id, active_employee_uid):
    """200 OK on delete; the copy endpoint then 404s for the same uid (cache busted too)."""
    employee = await _employee(db_session, active_employee_uid)
    row = _key(employee.id, user_id)
    assert (await authed_client.call("GET", f"{URL}/{row.uid}")).status_code == 200

    assert (await authed_client.call("DELETE", f"{URL}/{row.uid}")).status_code == 200

    copy_resp = await authed_client.call("GET", f"{URL}/{row.uid}", raise_for_status=False)
    assert copy_resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_logs_the_openrouter_call(authed_client, db_session, user_id, active_employee_uid):
    """A DfEngineOpenrouterLogs row is written for the DELETE /keys/{hash} attempt."""
    employee = await _employee(db_session, active_employee_uid)
    row = _key(employee.id, user_id)

    assert (await authed_client.call("DELETE", f"{URL}/{row.uid}")).status_code == 200

    await db_session.rollback()
    logs = (
        (
            await db_session.execute(
                select(DfEngineOpenrouterLogs).order_by(DfEngineOpenrouterLogs.created_at.desc()).limit(10)
            )
        )
        .scalars()
        .all()
    )
    assert any(log.method == "DELETE" for log in logs)


@pytest.mark.asyncio
async def test_deleted_key_name_can_be_reused(authed_client, db_session, user_id, active_employee_uid):
    """200 OK; once a key is hard-deleted its name is free — a new key can reuse it."""
    employee = await _employee(db_session, active_employee_uid)
    row = _key(employee.id, user_id)
    name = row.name

    assert (await authed_client.call("DELETE", f"{URL}/{row.uid}")).status_code == 200

    create_resp = await authed_client.call(
        "POST", URL, json={"name": name, "employee_uid": active_employee_uid, "is_main": False}
    )
    assert create_resp.status_code == 200
    assert name in response_names(create_resp.json())


@pytest.mark.asyncio
async def test_delete_twice_is_404_on_the_second_call(authed_client, db_session, user_id, active_employee_uid):
    """First delete is 200 OK; repeating it is 404 since the row is already gone."""
    employee = await _employee(db_session, active_employee_uid)
    row = _key(employee.id, user_id)
    assert (await authed_client.call("DELETE", f"{URL}/{row.uid}")).status_code == 200
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
    row = _key(employee.id, user_id)
    resp = await client.call("DELETE", f"{URL}/{row.uid}", raise_for_status=False)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_not_found_message_respects_accept_language(authed_client):
    """404; the not_found message text is localized per the Accept-Language header."""
    unknown_uid = uuid4()
    en_resp = await authed_client.call(
        "DELETE", f"{URL}/{unknown_uid}", headers={"Accept-Language": "en"}, raise_for_status=False
    )
    id_resp = await authed_client.call(
        "DELETE", f"{URL}/{unknown_uid}", headers={"Accept-Language": "id"}, raise_for_status=False
    )
    assert en_resp.json()["message"] == resolve_message("api_key_not_found", "en")
    assert id_resp.json()["message"] == resolve_message("api_key_not_found", "id")
    assert en_resp.json()["message"] != id_resp.json()["message"]
