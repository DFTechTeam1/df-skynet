# """Rotate (`PATCH /key-management/rotate`) has no filter — it processes every row
# currently in `df_engine_api_keys`, not just rows a given test created. OpenRouter
# calls are mocked (`mock_openrouter`), so running these tests makes no real external
# API call — but the endpoint still hard-deletes/archives/recreates every row in the
# shared staging DB's table, including any real key another developer or system
# depends on. That risk is about the DB, not OpenRouter, so it isn't removed by
# mocking. Every test here that calls the endpoint is therefore still skipped by
# default; run them deliberately (`pytest -m ""` or removing the marker locally) only
# against a DB you know is safe to fully rotate.
# """

# import pytest
# from uuid import uuid4
# from sqlalchemy import select
# from services.mysql.model import DfEngineApiKeys, DfEngineApiSnapshots, Employees
# from tests.helpers import create_record

# URL = "/api/key-management/rotate"

# pytestmark = [
#     pytest.mark.skip(reason="rotate has no row filter — it would mutate every key in the shared staging table"),
#     pytest.mark.usefixtures("mock_openrouter"),
# ]


# async def _employee(db_session, employee_uid):
#     return (await db_session.execute(select(Employees).where(Employees.uid == employee_uid))).scalar_one()


# async def _fabricate_key(db_session, user_id, employee_id, **overrides):
#     data = dict(
#         uid=str(uuid4()),
#         name=f"Key {uuid4().hex[:8]}",
#         key=f"sk-or-v1-{uuid4().hex[:16]}",
#         hash=uuid4().hex,
#         employee_id=employee_id,
#         created_by=int(user_id),
#         is_main=False,
#     )
#     data.update(overrides)
#     return await create_record(db_session, DfEngineApiKeys, data)


# @pytest.mark.asyncio
# async def test_rotate_replaces_a_key_and_archives_the_old_one(authed_client, db_session, user_id, active_employee_uid):
#     """200 OK; rotating produces a new DfEngineApiKeys row carrying over
#     name/employee/limit/limit_reset/is_main, hard-deletes the old row, archives it into
#     DfEngineApiSnapshots, and lists the old row's uid under `rotated`."""
#     employee = await _employee(db_session, active_employee_uid)
#     old = await _fabricate_key(db_session, user_id, employee.id, limit=25.0, limit_reset="weekly")

#     resp = await authed_client.call("PATCH", URL)
#     assert resp.status_code == 200
#     body = resp.json()["data"]
#     assert old.uid in body["rotated"]

#     await db_session.rollback()
#     still_old = (
#         await db_session.execute(select(DfEngineApiKeys).where(DfEngineApiKeys.uid == old.uid))
#     ).scalar_one_or_none()
#     assert still_old is None

#     snapshot = (
#         await db_session.execute(select(DfEngineApiSnapshots).where(DfEngineApiSnapshots.name == old.name))
#     ).scalar_one()
#     assert snapshot.limit == 25.0
#     assert snapshot.limit_reset == "weekly"

#     new_row = (await db_session.execute(select(DfEngineApiKeys).where(DfEngineApiKeys.name == old.name))).scalar_one()
#     assert new_row.employee_id == old.employee_id
#     assert new_row.limit == 25.0
#     assert new_row.limit_reset == "weekly"
#     assert new_row.is_main == old.is_main
#     assert new_row.uid != old.uid


# @pytest.mark.asyncio
# async def test_rotate_key_missing_hash_lands_in_failed(authed_client, db_session, user_id, active_employee_uid):
#     """A key with no OpenRouter hash on record is never attempted — it lands in `failed`
#     with `missing_hash`, and is left untouched."""
#     employee = await _employee(db_session, active_employee_uid)
#     row = await _fabricate_key(db_session, user_id, employee.id, hash=None)

#     resp = await authed_client.call("PATCH", URL)
#     assert resp.status_code == 200
#     body = resp.json()["data"]
#     assert any(f["uid"] == row.uid and f["reason"] == "missing_hash" for f in body["failed"])

#     await db_session.rollback()
#     still_there = (
#         await db_session.execute(select(DfEngineApiKeys).where(DfEngineApiKeys.uid == row.uid))
#     ).scalar_one_or_none()
#     assert still_there is not None


# @pytest.mark.asyncio
# async def test_rotate_response_shape(authed_client):
#     """200 OK; response.data always has the three-bucket shape, even on an otherwise
#     empty rotation."""
#     resp = await authed_client.call("PATCH", URL)
#     assert resp.status_code == 200
#     body = resp.json()["data"]
#     assert set(body.keys()) == {"rotated", "failed", "partial"}
#     assert isinstance(body["rotated"], list)
#     assert isinstance(body["failed"], list)
#     assert isinstance(body["partial"], list)


# @pytest.mark.asyncio
# async def test_requires_auth(client):
#     """401 when the request carries no bearer token."""
#     resp = await client.call("PATCH", URL, raise_for_status=False)
#     assert resp.status_code == 401
