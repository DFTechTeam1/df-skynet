# import pytest
# from datetime import timedelta
# from uuid import uuid4
# from sqlalchemy import select
# from services.mysql.model import DfEngineApiKeys, Employees
# from utils import local_time
# from tests.helpers import create_record, response_names

# URL = "/api/key-management"


# async def _employee(db_session, employee_uid):
#     return (await db_session.execute(select(Employees).where(Employees.uid == employee_uid))).scalar_one()


# @pytest.mark.asyncio
# async def test_fetch_all_api_keys(authed_client):
#     """200 OK; returns a list of API keys."""
#     resp = await authed_client.call("GET", URL)
#     body = resp.json()
#     assert resp.status_code == 200
#     assert body["message"] == "Success"
#     assert isinstance(body["data"], list)


# @pytest.mark.asyncio
# async def test_newest_first_ordering(authed_client, db_session, user_id, active_employee_uid):
#     """200 OK; list is ordered by created_at descending, newest key first."""
#     employee = await _employee(db_session, active_employee_uid)
#     now = local_time()
#     older = await create_record(
#         db_session,
#         DfEngineApiKeys,
#         dict(
#             uid=str(uuid4()),
#             name=f"Order {uuid4().hex[:8]}-older",
#             key=f"sk-or-v1-{uuid4().hex[:16]}",
#             employee_id=employee.id,
#             created_by=int(user_id),
#             created_at=now - timedelta(seconds=5),
#         ),
#     )
#     newer = await create_record(
#         db_session,
#         DfEngineApiKeys,
#         dict(
#             uid=str(uuid4()),
#             name=f"Order {uuid4().hex[:8]}-newer",
#             key=f"sk-or-v1-{uuid4().hex[:16]}",
#             employee_id=employee.id,
#             created_by=int(user_id),
#             created_at=now,
#         ),
#     )
#     resp = await authed_client.call("GET", URL)
#     names = response_names(resp.json())
#     assert names.index(newer.name) < names.index(older.name)


# @pytest.mark.asyncio
# async def test_list_masks_the_key(authed_client, db_session, user_id, active_employee_uid):
#     """200 OK; `key` is masked (prefix/suffix preserved, middle replaced)."""
#     employee = await _employee(db_session, active_employee_uid)
#     raw_key = f"sk-or-v1-{uuid4().hex[:16]}"
#     row = await create_record(
#         db_session,
#         DfEngineApiKeys,
#         dict(
#             uid=str(uuid4()),
#             name=f"Key {uuid4().hex[:8]}",
#             key=raw_key,
#             employee_id=employee.id,
#             created_by=int(user_id),
#         ),
#     )
#     resp = await authed_client.call("GET", URL)
#     item = next(i for i in resp.json()["data"] if i["name"] == row.name)
#     assert item["key"] != raw_key
#     assert item["key"].startswith(raw_key[:8])
#     assert item["key"].endswith(raw_key[-4:])
#     assert "*" in item["key"]


# @pytest.mark.asyncio
# async def test_list_item_shape_has_pic_creator_action(authed_client, db_session, user_id, active_employee_uid):
#     """200 OK; each row exposes `pic`, `creator`, `updater`, and an `action` block, and
#     strips internal columns."""
#     employee = await _employee(db_session, active_employee_uid)
#     row = await create_record(
#         db_session,
#         DfEngineApiKeys,
#         dict(
#             uid=str(uuid4()),
#             name=f"Key {uuid4().hex[:8]}",
#             key=f"sk-or-v1-{uuid4().hex[:16]}",
#             employee_id=employee.id,
#             created_by=int(user_id),
#             is_main=False,
#         ),
#     )
#     resp = await authed_client.call("GET", URL)
#     item = next(i for i in resp.json()["data"] if i["name"] == row.name)
#     assert "id" not in item
#     assert "hash" not in item
#     assert "employee_id" not in item
#     assert set(item["pic"].keys()) == {"image", "nickname"}
#     assert item["pic"]["nickname"] == employee.nickname
#     assert set(item["action"].keys()) == {"can_delete", "can_update", "can_copy"}


# @pytest.mark.asyncio
# async def test_requires_auth(client):
#     """401 when the request carries no bearer token."""
#     resp = await client.call("GET", URL, raise_for_status=False)
#     assert resp.status_code == 401
