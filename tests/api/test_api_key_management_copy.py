import pytest
from datetime import timedelta
from uuid import uuid4
from sqlalchemy import select
from middlewares.lang import resolve_message
from services.mysql.model import DfEngineOpenrouterLogs, Employees
from services.mysql.factory import DfEngineApiKeysFactory
from services.redis import client as redis_client, CacheKeys
from utils import local_time

URL = "/api/key-management"


async def _employee(db_session, employee_uid):
    return (await db_session.execute(select(Employees).where(Employees.uid == employee_uid))).scalar_one()


@pytest.mark.asyncio
async def test_copy_returns_only_the_real_unmasked_key(authed_client, db_session, user_id, active_employee_uid):
    """200 OK; response body is exactly the real key string — no name/creator/pic/etc."""
    employee = await _employee(db_session, active_employee_uid)
    raw_key = f"sk-or-v1-{uuid4().hex}"
    row = DfEngineApiKeysFactory.create(
        name=f"Key {uuid4().hex[:8]}", key=raw_key, employee_id=employee.id, created_by=int(user_id)
    )
    resp = await authed_client.call("GET", f"{URL}/{row.uid}")
    assert resp.status_code == 200
    assert resp.json()["data"] == raw_key


@pytest.mark.asyncio
async def test_copy_key_differs_from_masked_list_value(authed_client, db_session, user_id, active_employee_uid):
    """200 OK; the copy endpoint's key is the real value, unlike the masked one from list."""
    employee = await _employee(db_session, active_employee_uid)
    raw_key = f"sk-or-v1-{uuid4().hex}"
    row = DfEngineApiKeysFactory.create(
        name=f"Key {uuid4().hex[:8]}", key=raw_key, employee_id=employee.id, created_by=int(user_id)
    )
    copy_resp = await authed_client.call("GET", f"{URL}/{row.uid}")
    list_resp = await authed_client.call("GET", URL)
    list_item = next(item for item in list_resp.json()["data"] if item["name"] == row.name)

    assert copy_resp.json()["data"] == raw_key
    assert list_item["key"] != raw_key


@pytest.mark.asyncio
async def test_copy_does_not_write_an_openrouter_log(authed_client, db_session, user_id, active_employee_uid):
    """Copy is a local-only lookup — it never contacts OpenRouter, so no log row is written."""
    employee = await _employee(db_session, active_employee_uid)
    row = DfEngineApiKeysFactory.create(name=f"Key {uuid4().hex[:8]}", employee_id=employee.id, created_by=int(user_id))
    before = (await db_session.execute(select(DfEngineOpenrouterLogs.id))).scalars().all()
    await authed_client.call("GET", f"{URL}/{row.uid}")
    await db_session.rollback()
    after = (await db_session.execute(select(DfEngineOpenrouterLogs.id))).scalars().all()
    assert len(after) == len(before)


@pytest.mark.asyncio
async def test_copy_result_is_cached(authed_client, db_session, user_id, active_employee_uid):
    """200 OK; a copy populates api_key_management:detail:{uid} so a repeat is served from cache."""
    employee = await _employee(db_session, active_employee_uid)
    row = DfEngineApiKeysFactory.create(name=f"Key {uuid4().hex[:8]}", employee_id=employee.id, created_by=int(user_id))
    await authed_client.call("GET", f"{URL}/{row.uid}")
    assert await redis_client().exists(CacheKeys().api_key_management_detail(row.uid))


@pytest.mark.asyncio
async def test_copy_missing_employee_is_422(authed_client, db_session, user_id, active_employee_uid):
    """422 api_key_copy_missing_employee when the key's PIC has been detached."""
    row = DfEngineApiKeysFactory.create(name=f"Key {uuid4().hex[:8]}", employee_id=None, created_by=int(user_id))
    resp = await authed_client.call("GET", f"{URL}/{row.uid}", raise_for_status=False)
    assert resp.status_code == 422
    assert resp.json()["message"] == resolve_message("api_key_copy_missing_employee", "en")


@pytest.mark.asyncio
async def test_copy_expired_key_is_422(authed_client, db_session, user_id, active_employee_uid):
    """422 api_key_expired; an expired key can only be deleted, not copied."""
    employee = await _employee(db_session, active_employee_uid)
    row = DfEngineApiKeysFactory.create(
        name=f"Key {uuid4().hex[:8]}",
        employee_id=employee.id,
        created_by=int(user_id),
        expires_at=local_time() - timedelta(days=1),
    )
    resp = await authed_client.call("GET", f"{URL}/{row.uid}", raise_for_status=False)
    assert resp.status_code == 422
    assert resp.json()["message"] == resolve_message("api_key_expired", "en")


@pytest.mark.asyncio
async def test_copy_unknown_uid_is_404(authed_client):
    """404 api_key_not_found when the uid matches no key."""
    resp = await authed_client.call("GET", f"{URL}/{uuid4()}", raise_for_status=False)
    assert resp.status_code == 404
    assert resp.json()["message"] == resolve_message("api_key_not_found", "en")


@pytest.mark.asyncio
async def test_copy_row_without_hash_is_404(authed_client, db_session, user_id, active_employee_uid):
    """404; a key with no OpenRouter hash on record is invisible to every key-management read."""
    employee = await _employee(db_session, active_employee_uid)
    row = DfEngineApiKeysFactory.create(
        name=f"Key {uuid4().hex[:8]}", employee_id=employee.id, created_by=int(user_id), hash=None
    )
    resp = await authed_client.call("GET", f"{URL}/{row.uid}", raise_for_status=False)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_copy_requires_auth(client, db_session, user_id, active_employee_uid):
    """401 when the request carries no bearer token."""
    employee = await _employee(db_session, active_employee_uid)
    row = DfEngineApiKeysFactory.create(name=f"Key {uuid4().hex[:8]}", employee_id=employee.id, created_by=int(user_id))
    resp = await client.call("GET", f"{URL}/{row.uid}", raise_for_status=False)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_copy_not_found_message_respects_accept_language(authed_client):
    """404 for both, but the message text differs between Accept-Language: en and id."""
    unknown_uid = uuid4()
    en_resp = await authed_client.call(
        "GET", f"{URL}/{unknown_uid}", headers={"Accept-Language": "en"}, raise_for_status=False
    )
    id_resp = await authed_client.call(
        "GET", f"{URL}/{unknown_uid}", headers={"Accept-Language": "id"}, raise_for_status=False
    )
    assert en_resp.json()["message"] == resolve_message("api_key_not_found", "en")
    assert id_resp.json()["message"] == resolve_message("api_key_not_found", "id")
    assert en_resp.json()["message"] != id_resp.json()["message"]
