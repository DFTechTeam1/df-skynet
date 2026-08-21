# import pytest
# from uuid import uuid4
# from sqlalchemy import select
# from middlewares.lang import resolve_message
# from services.mysql.model import DfEngineApiKeys, DfEngineOpenrouterLogs, Employees
# from tests.helpers import create_record

# URL = "/api/key-management"


# async def _employee(db_session, employee_uid):
#     return (await db_session.execute(select(Employees).where(Employees.uid == employee_uid))).scalar_one()


# @pytest.mark.asyncio
# async def test_copy_returns_only_the_real_unmasked_key(authed_client, db_session, user_id, active_employee_uid):
#     """200 OK; response body is exactly the real key string — no name/creator/pic/etc."""
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
#     resp = await authed_client.call("GET", f"{URL}/{row.uid}")
#     body = resp.json()
#     assert resp.status_code == 200
#     assert body["data"] == raw_key


# @pytest.mark.asyncio
# async def test_copy_key_differs_from_masked_list_value(authed_client, db_session, user_id, active_employee_uid):
#     """200 OK; the copy endpoint's key is the real value, unlike the masked one from list."""
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
#     copy_resp = await authed_client.call("GET", f"{URL}/{row.uid}")
#     list_resp = await authed_client.call("GET", URL)

#     list_item = next(item for item in list_resp.json()["data"] if item["name"] == row.name)

#     assert copy_resp.json()["data"] == raw_key
#     assert list_item["key"] != raw_key


# @pytest.mark.asyncio
# async def test_copy_does_not_write_an_openrouter_log(authed_client, db_session, user_id, active_employee_uid):
#     """Copy is a local-only lookup — it never contacts OpenRouter, so no log row is written."""
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
#         ),
#     )
#     before = (await db_session.execute(select(DfEngineOpenrouterLogs.id))).scalars().all()
#     await authed_client.call("GET", f"{URL}/{row.uid}")
#     after = (await db_session.execute(select(DfEngineOpenrouterLogs.id))).scalars().all()
#     assert len(after) == len(before)


# @pytest.mark.asyncio
# async def test_copy_unknown_uid_is_404(authed_client):
#     """404 api_key_not_found when the uid matches no key."""
#     resp = await authed_client.call("GET", f"{URL}/{uuid4()}", raise_for_status=False)
#     assert resp.status_code == 404
#     assert resp.json()["message"] == resolve_message("api_key_not_found", "en")


# @pytest.mark.asyncio
# async def test_copy_requires_auth(client, db_session, user_id, active_employee_uid):
#     """401 when the request carries no bearer token."""
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
#         ),
#     )
#     resp = await client.call("GET", f"{URL}/{row.uid}", raise_for_status=False)
#     assert resp.status_code == 401


# # --- localization ------------------------------------------------------------


# @pytest.mark.asyncio
# async def test_copy_not_found_message_respects_accept_language(authed_client):
#     """404 for both, but the message text differs between Accept-Language: en and id."""
#     unknown_uid = uuid4()

#     en_resp = await authed_client.call(
#         "GET",
#         f"{URL}/{unknown_uid}",
#         headers={"Accept-Language": "en"},
#         raise_for_status=False,
#     )
#     id_resp = await authed_client.call(
#         "GET",
#         f"{URL}/{unknown_uid}",
#         headers={"Accept-Language": "id"},
#         raise_for_status=False,
#     )

#     assert en_resp.json()["message"] == resolve_message("api_key_not_found", "en")
#     assert id_resp.json()["message"] == resolve_message("api_key_not_found", "id")
#     assert en_resp.json()["message"] != id_resp.json()["message"]
