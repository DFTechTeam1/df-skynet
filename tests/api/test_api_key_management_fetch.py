import pytest
from datetime import timedelta
from uuid import uuid4
from sqlalchemy import select
from services.mysql.model import Employees
from services.mysql.factory import DfEngineApiKeysFactory
from utils import local_time
from tests.helpers import response_names

URL = "/api/key-management"


async def _employee(db_session, employee_uid):
    return (await db_session.execute(select(Employees).where(Employees.uid == employee_uid))).scalar_one()


@pytest.mark.asyncio
async def test_fetch_all_api_keys(authed_client):
    """200 OK; returns a list of API keys."""
    resp = await authed_client.call("GET", URL)
    body = resp.json()
    assert resp.status_code == 200
    assert body["message"] == "Success"
    assert isinstance(body["data"], list)


@pytest.mark.asyncio
async def test_newest_first_ordering(authed_client, db_session, user_id, active_employee_uid):
    """200 OK; list is ordered by created_at descending, newest key first."""
    employee = await _employee(db_session, active_employee_uid)
    now = local_time()
    older = DfEngineApiKeysFactory.create(
        name=f"Order {uuid4().hex[:8]}-older",
        employee_id=employee.id,
        created_by=int(user_id),
        created_at=now - timedelta(seconds=5),
    )
    newer = DfEngineApiKeysFactory.create(
        name=f"Order {uuid4().hex[:8]}-newer",
        employee_id=employee.id,
        created_by=int(user_id),
        created_at=now,
    )
    resp = await authed_client.call("GET", URL)
    names = response_names(resp.json())
    assert names.index(newer.name) < names.index(older.name)


@pytest.mark.asyncio
async def test_list_masks_the_key(authed_client, db_session, user_id, active_employee_uid):
    """200 OK; `key` is masked — first 4 and last 4 kept, the middle replaced with stars."""
    employee = await _employee(db_session, active_employee_uid)
    raw_key = f"sk-or-v1-{uuid4().hex}"
    row = DfEngineApiKeysFactory.create(
        name=f"Key {uuid4().hex[:8]}",
        key=raw_key,
        employee_id=employee.id,
        created_by=int(user_id),
    )
    resp = await authed_client.call("GET", URL)
    item = next(i for i in resp.json()["data"] if i["name"] == row.name)
    assert item["key"] != raw_key
    assert item["key"].startswith(raw_key[:4])
    assert item["key"].endswith(raw_key[-4:])
    assert "*" in item["key"]


@pytest.mark.asyncio
async def test_list_item_shape_has_pic_creator_action(authed_client, db_session, user_id, active_employee_uid):
    """200 OK; each row exposes `pic`, `creator`, `updater`, `is_expired` and an `action`
    block, and strips internal columns."""
    employee = await _employee(db_session, active_employee_uid)
    row = DfEngineApiKeysFactory.create(
        name=f"Key {uuid4().hex[:8]}",
        employee_id=employee.id,
        created_by=int(user_id),
        is_main=False,
    )
    resp = await authed_client.call("GET", URL)
    item = next(i for i in resp.json()["data"] if i["name"] == row.name)
    assert "id" not in item
    assert "hash" not in item
    assert "employee_id" not in item
    assert item["is_expired"] is False
    assert set(item["pic"].keys()) == {"image", "nickname"}
    assert item["pic"]["nickname"] == employee.nickname
    assert set(item["action"].keys()) == {"can_delete", "can_update", "can_copy", "can_set_to_main"}


@pytest.mark.asyncio
async def test_list_excludes_rows_without_hash_or_created_by(authed_client, db_session, user_id, active_employee_uid):
    """200 OK; only keys that came from a real create (created_by AND hash both set) are
    listed — half-written / seed rows are filtered out."""
    employee = await _employee(db_session, active_employee_uid)
    no_hash = DfEngineApiKeysFactory.create(
        name=f"NoHash {uuid4().hex[:8]}", employee_id=employee.id, created_by=int(user_id), hash=None
    )
    no_creator = DfEngineApiKeysFactory.create(
        name=f"NoCreator {uuid4().hex[:8]}", employee_id=employee.id, created_by=None
    )
    names = response_names((await authed_client.call("GET", URL)).json())
    assert no_hash.name not in names
    assert no_creator.name not in names


@pytest.mark.asyncio
async def test_list_flags_expired_key_and_restricts_its_actions(
    authed_client, db_session, user_id, active_employee_uid
):
    """200 OK; a key past its expiry is flagged `is_expired` and only `can_delete` stays true."""
    employee = await _employee(db_session, active_employee_uid)
    row = DfEngineApiKeysFactory.create(
        name=f"Expired {uuid4().hex[:8]}",
        employee_id=employee.id,
        created_by=int(user_id),
        expires_at=local_time() - timedelta(days=1),
    )
    item = next(i for i in (await authed_client.call("GET", URL)).json()["data"] if i["name"] == row.name)
    assert item["is_expired"] is True
    assert item["action"]["can_delete"] is True
    assert item["action"]["can_update"] is False
    assert item["action"]["can_copy"] is False
    assert item["action"]["can_set_to_main"] is False


@pytest.mark.asyncio
async def test_requires_auth(client):
    """401 when the request carries no bearer token."""
    resp = await client.call("GET", URL, raise_for_status=False)
    assert resp.status_code == 401
