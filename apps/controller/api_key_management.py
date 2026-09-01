import time
import traceback
from uuid import UUID
from typing import Optional
from fastapi import status, Path, Query
from fastapi_controller import controller
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from apps.controller.core import CoreDependencies
from schemas.response import PaginationResponse, Response
from services.mysql import query
from schemas.payload.api_key_management import CreateApiKeyPayload, UpdateApiKeyPayload
from services.mysql.model import (
    DfEngineApiKeyRotationIssues,
    DfEngineApiKeys,
    DfEngineApiSnapshots,
    DfEngineOpenrouterLogs,
    Employees,
    PositionBackups,
)
from services.redis import get_json, set_json, delete_pattern, CacheKeys
from log import logging
from apps.secret import OPENROUTER_BASE_URL, OPENROUTER_MANAGEMENT_KEY
from error import ServiceError, BaseError, DataConflictError, DataNotFoundError, DataValidationError
from utils import local_time, wib_to_utc_iso
from services.api_caller import APICaller
from services.api_key_management import ApiKeyManagement
from utils.serializer import serialize


class APIKeyManagementController(CoreDependencies):
    @controller.post(
        "/key-management",
        summary="Create an API key.",
        description=(
            "Generates a brand-new API key on OpenRouter for a Project Manager or "
            "Assistant Project Manager. That person (the PIC) can hold several keys at "
            'once, but only one of them can be marked as "main" at a time — trying to '
            "add a second main key for the same PIC is rejected. Every attempt to reach "
            "OpenRouter is recorded, whether it succeeds or fails. Returns the full, "
            "up-to-date list of API keys, including the one just created."
        ),
        status_code=status.HTTP_200_OK,
        tags=["API Key Management"],
        response_model=Response,
    )
    async def api_key_management_to_create_api_management(self, schema: CreateApiKeyPayload) -> Response:
        response = Response()
        cache_key = CacheKeys()
        ALLOWED_PIC_POSITIONS = ["project manager", "assistant project manager"]
        try:
            if schema.expires_at and schema.expires_at <= local_time():
                raise DataValidationError(message="api_key_expiry_must_be_in_future")

            employee = await query(
                db=self.db,
                columns=(
                    Employees.id,
                    Employees.nickname,
                    PositionBackups.name.label("position_name"),  # type: ignore
                    DfEngineApiKeys.id.label("api_key"),  # type: ignore
                ),
                table=Employees,
                joins=(
                    (PositionBackups, Employees.position_id == PositionBackups.id, True),
                    (
                        DfEngineApiKeys,
                        (DfEngineApiKeys.employee_id == Employees.id)
                        & DfEngineApiKeys.is_main.is_(True)  # type: ignore
                        & DfEngineApiKeys.created_by.isnot(None)  # type: ignore
                        & DfEngineApiKeys.hash.isnot(None),  # type: ignore
                        True,
                    ),
                ),
                filters=(Employees.uid == str(schema.employee_uid),),
                fetch_one=True,
            )

            if not employee:
                raise DataNotFoundError(message="employee_not_found")
            if (employee.position_name or "").strip().lower() not in ALLOWED_PIC_POSITIONS:
                raise DataValidationError(message="employee_position_not_allowed")
            if schema.is_main and employee.api_key is not None:
                raise DataConflictError(message="employee_already_has_main_api_key")

            name_taken = await query(
                db=self.db,
                table=DfEngineApiKeys,
                columns=(DfEngineApiKeys.id,),
                filters=(
                    DfEngineApiKeys.name == schema.name,
                    DfEngineApiKeys.employee_id == employee.id,
                    DfEngineApiKeys.created_by.isnot(None),  # type: ignore
                    DfEngineApiKeys.hash.isnot(None),  # type: ignore
                ),
                fetch_one=True,
            )
            if name_taken is not None:
                raise DataConflictError(message="api_key_already_exists")

            header = {"Authorization": f"Bearer {OPENROUTER_MANAGEMENT_KEY}"}
            payload = {
                "expires_at": schema.expires_at_iso,
                "include_byok_in_limit": True,
                "limit": schema.limit,
                "limit_reset": schema.limit_reset,
                "name": schema.name,
            }

            started_at = time.perf_counter()
            async with APICaller(base_url=OPENROUTER_BASE_URL, headers=header) as caller:
                openrouter_response = await caller.call("POST", "/keys", raise_for_status=False, json=payload)

            response_body = openrouter_response.json() if openrouter_response.content else {}
            error_message: Optional[str] = None
            conflict = False

            if openrouter_response.is_error:
                error_message = (
                    f"openrouter {openrouter_response.status_code}: {response_body or openrouter_response.text}"
                )
            else:
                self.db.add(
                    DfEngineApiKeys(
                        name=schema.name,
                        description=schema.description,
                        key=response_body["key"],
                        hash=response_body["data"]["hash"],
                        employee_id=employee.id,
                        employee_name=employee.nickname,
                        limit=schema.limit,
                        limit_reset=schema.limit_reset.value if schema.limit_reset else None,
                        expires_at=schema.expires_at,
                        created_by=int(self.user["user_id"]),
                        is_main=schema.is_main,
                    )
                )
                try:
                    await self.db.flush()
                except IntegrityError as e:
                    await self.db.rollback()
                    logging.error(
                        f"user={self.user['user_id']} API key create hit a DB conflict for {schema.name!r}: {e.orig}"
                    )
                    error_message = f"IntegrityError: {e.orig}"
                    conflict = True

            self.db.add(
                DfEngineOpenrouterLogs(
                    name=employee.nickname,
                    method="POST",
                    endpoint=str(openrouter_response.request.url),
                    request_headers={**header, "Authorization": "Bearer ***"},
                    request_payload=payload,
                    response_status_code=openrouter_response.status_code,
                    response_headers=dict(openrouter_response.headers),
                    response_body=response_body or None,
                    error_message=error_message,
                    duration_ms=int((time.perf_counter() - started_at) * 1000),
                )
            )
            await self.db.flush()

            if conflict:
                raise DataConflictError(message="api_key_already_exists")
            if openrouter_response.is_error:
                raise ServiceError(message="openrouter_key_create_failed")

            logging.info(
                f"user={self.user['user_id']} created API key {schema.name!r} for employee {employee.id} "
                f"(is_main={schema.is_main}) in {int((time.perf_counter() - started_at) * 1000)}ms"
            )
            await delete_pattern(self.redis, cache_key.api_key_management_pattern())
            response.data = (await self.api_key_management_to_fetch_available_keys()).data

        except BaseError as e:
            logging.warning(
                f"user={self.user['user_id']} could not create API key {schema.name!r} "
                f"for employee_uid={schema.employee_uid}: {e.message} ({e.status_code})"
            )
            raise
        except Exception:
            logging.error(f"user={self.user['user_id']} unexpected error creating API key\n{traceback.format_exc()}")
            raise ServiceError()
        return response

    @controller.patch(
        "/key-management/rotate",
        summary="Rotate all API keys.",
        description=(
            "Meant to run automatically on a schedule (e.g. weekly). Keys already past "
            "their own `expires_at`, keys with no hash, and keys with a hash OpenRouter "
            "no longer recognizes are all cleaned up outright, with nothing to rotate. "
            "For every other key, creates a brand-new OpenRouter secret first — same "
            "name, PIC, spending limits, and main flag, with its original expiry "
            "duration preserved — and only once that succeeds does it revoke the old "
            "key on OpenRouter and archive it. If one key fails, the rest continue — "
            "per-key outcomes are only logged, not returned. Returns the full, "
            "up-to-date list of API keys, same shape as every other endpoint here."
        ),
        status_code=status.HTTP_200_OK,
        tags=["API Key Management"],
        response_model=Response,
    )
    async def api_key_management_to_rotate_api_keys(self) -> Response:
        response = Response()
        cache_key = CacheKeys()
        try:
            records = await query(
                db=self.db,
                table=DfEngineApiKeys,
                filters=(DfEngineApiKeys.hash.isnot(None), DfEngineApiKeys.created_by.isnot(None)),  # type: ignore
            )

            logging.info(f"user={self.user['user_id']} rotating API keys — {len(records or [])} candidate(s)")

            if not records:
                logging.info(f"user={self.user['user_id']} no API keys to rotate")
                response.data = (await self.api_key_management_to_fetch_available_keys()).data
                return response

            header = {"Authorization": f"Bearer {OPENROUTER_MANAGEMENT_KEY}"}
            redacted_header = {**header, "Authorization": "Bearer ***"}
            rotated = 0
            removed = 0

            for record in records:
                if record.expires_at is not None and record.expires_at <= local_time():
                    # Past its own expiry — clean up instead of rotating.
                    # The OpenRouter secret is already dead, so no revoke
                    # call; just archive the row and drop it, in its own SAVEPOINT.
                    try:
                        async with self.db.begin_nested():
                            self.db.add(
                                DfEngineApiSnapshots(
                                    created_at=record.created_at,
                                    updated_at=record.updated_at,
                                    expires_at=record.expires_at,
                                    limit=record.limit,
                                    limit_reset=record.limit_reset,
                                    uid=record.uid,
                                    key=record.key,
                                    hash=record.hash,
                                    name=record.name,
                                    description=record.description,
                                    employee_id=record.employee_id,
                                    employee_name=record.employee_name,
                                    created_by=record.created_by,
                                    updated_by=record.updated_by,
                                )
                            )
                            await self.db.delete(record)
                    except IntegrityError as e:
                        self.db.add(
                            DfEngineApiKeyRotationIssues(
                                old_uid=record.uid,
                                issue_type="expired_key_not_removed",
                                detail=str(e.orig),
                            )
                        )
                        await self.db.flush()
                        logging.error(
                            f"user={self.user['user_id']} could not remove expired API key {record.name!r} "
                            f"(uid={record.uid}): {e.orig}"
                        )
                        continue

                    removed += 1
                    logging.info(
                        f"user={self.user['user_id']} removed expired API key {record.name!r} (uid={record.uid})"
                    )
                    continue

                create_payload = {
                    "expires_at": wib_to_utc_iso(record.expires_at),
                    "include_byok_in_limit": True,
                    "limit": float(record.limit) if record.limit is not None else None,
                    "limit_reset": record.limit_reset,
                    "name": record.name,
                }

                # Create the replacement first — never leave a PIC without a working key.
                t0 = time.perf_counter()
                async with APICaller(base_url=OPENROUTER_BASE_URL, headers=header) as caller:
                    create_response = await caller.call("POST", "/keys", raise_for_status=False, json=create_payload)
                create_body = create_response.json() if create_response.content else {}
                create_ok = not (create_response.is_error or bool(create_body.get("error")))

                self.db.add(
                    DfEngineOpenrouterLogs(
                        name=record.employee_name,
                        method="POST",
                        endpoint=str(create_response.request.url),
                        request_headers=redacted_header,
                        request_payload=create_payload,
                        response_status_code=create_response.status_code,
                        response_headers=dict(create_response.headers),
                        response_body=create_body or None,
                        error_message=None
                        if create_ok
                        else f"openrouter {create_response.status_code}: {create_body or create_response.text}",
                        duration_ms=int((time.perf_counter() - t0) * 1000),
                    )
                )

                if not create_ok:
                    self.db.add(
                        DfEngineApiKeyRotationIssues(
                            old_uid=record.uid,
                            issue_type="new_key_not_created",
                            detail=f"openrouter {create_response.status_code}: {create_body or create_response.text}",
                        )
                    )
                    await self.db.flush()
                    logging.error(
                        f"user={self.user['user_id']} skipped {record.name!r} (uid={record.uid}) during rotation — "
                        f"OpenRouter rejected the replacement ({create_response.status_code}); old key kept"
                    )
                    continue

                # Replacement exists — revoke the old key. A revoke failure is non-fatal
                # (the old secret is being dropped and would expire anyway); just log it.
                t1 = time.perf_counter()
                async with APICaller(base_url=OPENROUTER_BASE_URL, headers=header) as caller:
                    revoke_response = await caller.call("DELETE", f"/keys/{record.hash}", raise_for_status=False)
                revoke_body = revoke_response.json() if revoke_response.content else {}
                revoked_cleanly = not (revoke_response.is_error or bool(revoke_body.get("error")))

                self.db.add(
                    DfEngineOpenrouterLogs(
                        name=record.employee_name,
                        method="DELETE",
                        endpoint=str(revoke_response.request.url),
                        request_headers=redacted_header,
                        request_payload=None,
                        response_status_code=revoke_response.status_code,
                        response_headers=dict(revoke_response.headers),
                        response_body=revoke_body or None,
                        error_message=None
                        if revoked_cleanly
                        else f"openrouter {revoke_response.status_code}: {revoke_body or revoke_response.text}",
                        duration_ms=int((time.perf_counter() - t1) * 1000),
                    )
                )

                # Swap the rows inside a SAVEPOINT so a conflict here unwinds ONLY this
                # key — the request-wide transaction (prior rotations + every log row
                # above) stays intact. ponytail: generation_prompts still points at
                # df_engine_api_keys.id via a polymorphic FK; repoint those to the
                # snapshot id once that model is mapped in this service.
                try:
                    async with self.db.begin_nested():
                        self.db.add(
                            DfEngineApiSnapshots(
                                created_at=record.created_at,
                                updated_at=record.updated_at,
                                expires_at=record.expires_at,
                                limit=record.limit,
                                limit_reset=record.limit_reset,
                                uid=record.uid,
                                key=record.key,
                                hash=record.hash,
                                name=record.name,
                                description=record.description,
                                employee_id=record.employee_id,
                                employee_name=record.employee_name,
                                created_by=record.created_by,
                                updated_by=record.updated_by,
                            )
                        )
                        self.db.add(
                            DfEngineApiKeys(
                                name=record.name,
                                description=record.description,
                                key=create_body["key"],
                                hash=create_body["data"]["hash"],
                                employee_id=record.employee_id,
                                employee_name=record.employee_name,
                                limit=record.limit,
                                limit_reset=record.limit_reset,
                                expires_at=record.expires_at,
                                created_by=record.created_by,
                                is_main=record.is_main,
                            )
                        )
                        await self.db.delete(record)
                except IntegrityError as e:
                    self.db.add(
                        DfEngineApiKeyRotationIssues(
                            old_uid=record.uid,
                            new_key_hash=create_body["data"]["hash"],
                            new_key_value=create_body["key"],
                            issue_type="new_key_db_conflict",
                            detail=str(e.orig),
                        )
                    )
                    await self.db.flush()
                    logging.error(
                        f"user={self.user['user_id']} rotation left an orphan for {record.name!r} (uid={record.uid}) — "
                        f"OpenRouter key created (hash {create_body['data']['hash']}) but the local save failed "
                        f"({e.orig}); needs manual reconciliation"
                    )
                    continue

                rotated += 1
                logging.info(
                    f"user={self.user['user_id']} rotated API key {record.name!r} (uid={record.uid}); "
                    f"old key revoked={revoked_cleanly}"
                )

            logging.info(
                f"user={self.user['user_id']} rotation complete — {rotated} rotated, {removed} expired removed "
                f"of {len(records)} candidate(s)"
            )
            await delete_pattern(self.redis, cache_key.api_key_management_pattern())
            response.data = (await self.api_key_management_to_fetch_available_keys()).data

        except BaseError as e:
            logging.warning(f"user={self.user['user_id']} could not rotate API keys: {e.message} ({e.status_code})")
            raise
        except Exception:
            logging.error(f"user={self.user['user_id']} unexpected error rotating API keys\n{traceback.format_exc()}")
            raise ServiceError()
        return response

    @controller.get(
        "/key-management",
        summary="List API keys.",
        description=(
            "Returns every registered API key, newest first. The key value itself is "
            "masked (only the first and last few characters are shown) — use the copy "
            "endpoint to reveal the real value. Each entry also includes who it's "
            "assigned to and which actions the current user is allowed to take on it."
        ),
        status_code=status.HTTP_200_OK,
        tags=["API Key Management"],
        response_model=Response,
    )
    async def api_key_management_to_fetch_available_keys(self) -> Response:
        response = Response()
        cache_key = CacheKeys()
        api_key_service = ApiKeyManagement()
        try:
            api_keys_global_cache_key = cache_key.api_key_management()
            cached_api_keys = await get_json(self.redis, api_keys_global_cache_key)
            if cached_api_keys:
                logging.info(f"user={self.user['user_id']} listed {len(cached_api_keys)} API key(s) from cache")
                response.data = cached_api_keys
                return response

            results = await query(
                db=self.db,
                table=DfEngineApiKeys,
                options=api_key_service.options(),
                filters=(DfEngineApiKeys.created_by.isnot(None), DfEngineApiKeys.hash.isnot(None)),  # type: ignore
                order_by=(DfEngineApiKeys.created_at.desc(),),  # type: ignore
            )

            serialized = serialize(results)
            employee_ids_with_main = {
                r["employee_id"] for r in serialized if r["is_main"] and r["employee_id"] is not None
            }
            records = [api_key_service.format(record, employee_ids_with_main) for record in serialized]
            await set_json(self.redis, api_keys_global_cache_key, records)
            logging.info(f"user={self.user['user_id']} listed {len(records)} API key(s) from database")
            response.data = records
        except BaseError as e:
            logging.warning(f"user={self.user['user_id']} could not list API keys: {e.message} ({e.status_code})")
            raise
        except Exception:
            logging.error(f"user={self.user['user_id']} unexpected error listing API keys\n{traceback.format_exc()}")
            raise ServiceError()
        return response

    @controller.get(
        "/key-management/logs",
        summary="View the log of calls this service made to OpenRouter.",
        description=(
            "Returns the OpenRouter call history, newest first: every time this service "
            "contacted OpenRouter to create, update, delete, or rotate an API key, this "
            "records who triggered it, the HTTP method and endpoint, the request body "
            "that was sent, OpenRouter's status code, response headers and response "
            "body, how long the call took, and any error. The outgoing request headers "
            "are deliberately left out because they carry the OpenRouter management "
            "credential. Paginated — pass `page` and `itemsPerPage` to page through the "
            "history."
        ),
        status_code=status.HTTP_200_OK,
        tags=["API Key Management"],
        response_model=Response,
    )
    async def api_key_management_to_fetch_openrouter_logs(
        self,
        page: int = Query(default=1, ge=1, description="1-indexed page number to fetch."),
        itemsPerPage: int = Query(default=50, ge=1, le=200, description="Number of records to return per page."),
    ) -> Response:
        response = Response()
        cache_key = CacheKeys()
        api_key_service = ApiKeyManagement()
        try:
            logs_cache_key = cache_key.api_key_management_logs(page, itemsPerPage)
            cached = await get_json(self.redis, logs_cache_key)
            if cached is not None:
                logging.info(
                    f"user={self.user['user_id']} returned OpenRouter call log page {page} "
                    f"({len(cached['logs'])} row(s)) from cache"
                )
                response.data = PaginationResponse(paginated=cached["logs"], totalData=cached["total_data"])
                return response

            total_data = (
                await query(
                    db=self.db,
                    table=DfEngineOpenrouterLogs,
                    columns=(func.count(DfEngineOpenrouterLogs.id),),  # type: ignore
                    fetch_one=True,
                )
                or 0
            )

            records = await query(
                db=self.db,
                table=DfEngineOpenrouterLogs,
                order_by=(DfEngineOpenrouterLogs.created_at.desc(), DfEngineOpenrouterLogs.id.desc()),  # type: ignore
                limit=itemsPerPage,
                offset=(page - 1) * itemsPerPage,
            )

            logs = [api_key_service.format_log(record) for record in serialize(records)]

            await set_json(self.redis, logs_cache_key, {"logs": logs, "total_data": total_data})
            logging.info(
                f"user={self.user['user_id']} returned OpenRouter call log page {page} "
                f"({len(logs)} of {total_data} row(s)) from database"
            )
            response.data = PaginationResponse(paginated=logs, totalData=total_data)
        except BaseError as e:
            logging.warning(
                f"user={self.user['user_id']} could not return OpenRouter call log (page {page}): "
                f"{e.message} ({e.status_code})"
            )
            raise
        except Exception:
            logging.error(
                f"user={self.user['user_id']} unexpected error returning OpenRouter call log\n{traceback.format_exc()}"
            )
            raise ServiceError()
        return response

    @controller.delete(
        "/key-management/{uid}",
        summary="Delete a non-main API key.",
        description=(
            "Permanently revokes the key on OpenRouter, saves a copy of its details in "
            "the archive (df_engine_api_snapshots), then removes it from the active "
            'list. A key currently marked as "main" can\'t be deleted this way — '
            "update it to no longer be main first. Every attempt to reach OpenRouter is "
            "recorded, whether it succeeds or fails. Returns the full, up-to-date list "
            "of remaining API keys."
        ),
        status_code=status.HTTP_200_OK,
        tags=["API Key Management"],
        response_model=Response,
    )
    async def api_key_management_with_uid_to_delete_an_api_key(
        self,
        uid: UUID = Path(
            ...,
            description="API key UID.",
            examples=["8d96ff4e-5c35-4329-bd5d-827e2c68599d"],
        ),
    ) -> Response:
        response = Response()
        cache_key = CacheKeys()
        try:
            record = await query(
                db=self.db,
                table=DfEngineApiKeys,
                filters=(
                    DfEngineApiKeys.uid == str(uid),
                    DfEngineApiKeys.created_by.isnot(None),  # type: ignore
                    DfEngineApiKeys.hash.isnot(None),  # type: ignore
                ),
                fetch_one=True,
            )
            if not record:
                raise DataNotFoundError(message="api_key_not_found")
            is_expired = record.expires_at is not None and record.expires_at <= local_time()
            if record.is_main and not is_expired:
                raise DataValidationError(message="cannot_delete_main_api_key")

            record_name = record.name
            header = {"Authorization": f"Bearer {OPENROUTER_MANAGEMENT_KEY}"}
            started_at = time.perf_counter()
            async with APICaller(base_url=OPENROUTER_BASE_URL, headers=header) as caller:
                openrouter_response = await caller.call("DELETE", f"/keys/{record.hash}", raise_for_status=False)

            response_body = openrouter_response.json() if openrouter_response.content else {}
            revoked_cleanly = not (openrouter_response.is_error or bool(response_body.get("error")))

            self.db.add(
                DfEngineOpenrouterLogs(
                    name=record.employee_name,
                    method="DELETE",
                    endpoint=str(openrouter_response.request.url),
                    request_headers={**header, "Authorization": "Bearer ***"},
                    request_payload=None,
                    response_status_code=openrouter_response.status_code,
                    response_headers=dict(openrouter_response.headers),
                    response_body=response_body or None,
                    error_message=None
                    if revoked_cleanly
                    else f"openrouter {openrouter_response.status_code}: {response_body or openrouter_response.text}",
                    duration_ms=int((time.perf_counter() - started_at) * 1000),
                )
            )

            if revoked_cleanly:
                # Archive only when OpenRouter confirmed the revoke. A stale/invalid
                # hash (revoke failed) means there's nothing live to snapshot — just
                # drop the row.
                # ponytail: generation_prompts still points at df_engine_api_keys.id via
                # a polymorphic FK; repoint those to the snapshot id here once that model
                # is mapped in this service. Same TODO in the rotate flow.
                self.db.add(
                    DfEngineApiSnapshots(
                        created_at=record.created_at,
                        updated_at=record.updated_at,
                        expires_at=record.expires_at,
                        limit=record.limit,
                        limit_reset=record.limit_reset,
                        uid=record.uid,
                        key=record.key,
                        hash=record.hash,
                        name=record.name,
                        description=record.description,
                        employee_id=record.employee_id,
                        employee_name=record.employee_name,
                        created_by=record.created_by,
                        updated_by=record.updated_by,
                    )
                )

            await self.db.delete(record)
            await self.db.flush()

            logging.info(
                f"user={self.user['user_id']} deleted API key {record_name!r} (uid={uid}) — "
                f"{'OpenRouter key revoked' if revoked_cleanly else 'OpenRouter hash was already invalid'} "
                f"in {int((time.perf_counter() - started_at) * 1000)}ms"
            )

            await delete_pattern(self.redis, cache_key.api_key_management_pattern())
            response.data = (await self.api_key_management_to_fetch_available_keys()).data

        except BaseError as e:
            logging.warning(
                f"user={self.user['user_id']} could not delete API key uid={uid}: {e.message} ({e.status_code})"
            )
            raise
        except Exception:
            logging.error(
                f"user={self.user['user_id']} unexpected error deleting API key uid={uid}\n{traceback.format_exc()}"
            )
            raise ServiceError()
        return response

    @controller.get(
        "/key-management/{uid}",
        summary="Reveal an API key's real value.",
        description=(
            "Looks up one API key by its ID and returns its actual, unmasked key text "
            "so it can be copied — unlike the list endpoint, which always shows a "
            "masked value. This is a local lookup only; it does not contact OpenRouter "
            "and isn't recorded in the OpenRouter call log."
        ),
        status_code=status.HTTP_200_OK,
        tags=["API Key Management"],
        response_model=Response,
    )
    async def api_key_management_with_uid_to_copy_api_key(
        self,
        uid: UUID = Path(
            ...,
            description="API key UID.",
            examples=["8d96ff4e-5c35-4329-bd5d-827e2c68599d"],
        ),
    ) -> Response:
        response = Response()
        cache_key = CacheKeys()
        try:
            api_key_detail_cache_key = cache_key.api_key_management_detail(uid)
            cached_key = await get_json(self.redis, api_key_detail_cache_key)
            if cached_key:
                logging.info(f"user={self.user['user_id']} revealed API key uid={uid} from cache")
                response.data = cached_key
                return response

            record = await query(
                db=self.db,
                table=DfEngineApiKeys,
                columns=(
                    DfEngineApiKeys.key,
                    DfEngineApiKeys.hash,
                    DfEngineApiKeys.employee_id,
                    DfEngineApiKeys.name,
                    DfEngineApiKeys.expires_at,
                ),
                filters=(
                    DfEngineApiKeys.uid == str(uid),
                    DfEngineApiKeys.created_by.isnot(None),  # type: ignore
                    DfEngineApiKeys.hash.isnot(None),  # type: ignore
                ),
                fetch_one=True,
            )
            if record is None:
                raise DataNotFoundError(message="api_key_not_found")
            if not record.employee_id:
                raise DataValidationError(message="api_key_copy_missing_employee")
            if record.expires_at is not None and record.expires_at <= local_time():
                raise DataValidationError(message="api_key_expired")

            await set_json(self.redis, api_key_detail_cache_key, record.key)
            logging.info(f"user={self.user['user_id']} revealed API key {record.name!r} (uid={uid}) from database")
            response.data = record.key
        except BaseError as e:
            logging.warning(
                f"user={self.user['user_id']} could not reveal API key uid={uid}: {e.message} ({e.status_code})"
            )
            raise
        except Exception:
            logging.error(
                f"user={self.user['user_id']} unexpected error revealing API key uid={uid}\n{traceback.format_exc()}"
            )
            raise ServiceError()
        return response

    @controller.patch(
        "/key-management/{uid}",
        summary="Update an API key.",
        description=(
            "Replaces the key's editable details — name, description, spending limit, "
            "reset schedule, and main flag — with what's submitted (this is a full "
            "replace, not a partial update). The PIC and the expiry date are fixed at "
            "creation and can't be changed here — the payload mirrors OpenRouter's own "
            "key-update fields. OpenRouter is contacted only when the name, spending "
            "limit, or reset schedule actually changed; description and main-flag "
            "changes stay local. An expired key can't be updated (delete it and create "
            'a new one). The same "only one main key per PIC" rule as creation applies. '
            "Returns the full, up-to-date list of API keys."
        ),
        status_code=status.HTTP_200_OK,
        tags=["API Key Management"],
        response_model=Response,
    )
    async def api_key_management_with_uid_to_update_record(
        self,
        schema: UpdateApiKeyPayload,
        uid: UUID = Path(
            ...,
            description="API key UID.",
            examples=["8d96ff4e-5c35-4329-bd5d-827e2c68599d"],
        ),
    ) -> Response:
        response = Response()
        cache_key = CacheKeys()
        try:
            record = await query(
                db=self.db,
                table=DfEngineApiKeys,
                filters=(
                    DfEngineApiKeys.uid == str(uid),
                    DfEngineApiKeys.created_by.isnot(None),  # type: ignore
                    DfEngineApiKeys.hash.isnot(None),  # type: ignore
                ),
                fetch_one=True,
            )
            if not record:
                raise DataNotFoundError(message="api_key_not_found")
            if not record.employee_id:
                raise DataValidationError(message="api_key_employee_deleted")
            if record.expires_at is not None and record.expires_at <= local_time():
                raise DataValidationError(message="api_key_expired")

            name_taken = await query(
                db=self.db,
                table=DfEngineApiKeys,
                columns=(DfEngineApiKeys.id,),
                filters=(
                    DfEngineApiKeys.name == schema.name,
                    DfEngineApiKeys.employee_id == record.employee_id,
                    DfEngineApiKeys.id != record.id,
                    DfEngineApiKeys.created_by.isnot(None),  # type: ignore
                    DfEngineApiKeys.hash.isnot(None),  # type: ignore
                ),
                fetch_one=True,
            )
            if name_taken is not None:
                raise DataConflictError(message="api_key_already_exists")

            if schema.is_main and not record.is_main:
                other_main = await query(
                    db=self.db,
                    table=DfEngineApiKeys,
                    columns=(DfEngineApiKeys.id,),
                    filters=(
                        DfEngineApiKeys.employee_id == record.employee_id,
                        DfEngineApiKeys.is_main.is_(True),  # type: ignore
                        DfEngineApiKeys.id != record.id,
                        DfEngineApiKeys.created_by.isnot(None),  # type: ignore
                        DfEngineApiKeys.hash.isnot(None),  # type: ignore
                    ),
                    fetch_one=True,
                )
                if other_main is not None:
                    raise DataConflictError(message="employee_already_has_main_api_key")

            new_limit = float(schema.limit) if schema.limit is not None else None
            new_limit_reset = schema.limit_reset.value if schema.limit_reset else None
            current_limit = float(record.limit) if record.limit is not None else None
            openrouter_synced = (
                schema.name != record.name or new_limit != current_limit or new_limit_reset != record.limit_reset
            )

            sync_failed = False
            if openrouter_synced:
                header = {"Authorization": f"Bearer {OPENROUTER_MANAGEMENT_KEY}"}
                payload = {
                    "disabled": False,
                    "include_byok_in_limit": True,
                    "limit": schema.limit,
                    "limit_reset": schema.limit_reset,
                    "name": schema.name,
                }
                started_at = time.perf_counter()
                async with APICaller(base_url=OPENROUTER_BASE_URL, headers=header) as caller:
                    openrouter_response = await caller.call(
                        "PATCH", f"/keys/{record.hash}", raise_for_status=False, json=payload
                    )
                response_body = openrouter_response.json() if openrouter_response.content else {}
                sync_failed = openrouter_response.is_error or bool(response_body.get("error"))

                self.db.add(
                    DfEngineOpenrouterLogs(
                        name=record.employee_name,
                        method="PATCH",
                        endpoint=str(openrouter_response.request.url),
                        request_headers={**header, "Authorization": "Bearer ***"},
                        request_payload=payload,
                        response_status_code=openrouter_response.status_code,
                        response_headers=dict(openrouter_response.headers),
                        response_body=response_body or None,
                        error_message=None
                        if not sync_failed
                        else f"openrouter {openrouter_response.status_code}: {response_body or openrouter_response.text}",
                        duration_ms=int((time.perf_counter() - started_at) * 1000),
                    )
                )

            if not sync_failed:
                record.name = schema.name
                record.description = schema.description
                record.limit = schema.limit
                record.limit_reset = new_limit_reset
                record.is_main = schema.is_main
                record.updated_by = int(self.user["user_id"])

            try:
                await self.db.flush()
            except IntegrityError as e:
                await self.db.rollback()
                logging.error(f"user={self.user['user_id']} API key update hit a DB conflict (uid={uid}): {e.orig}")
                raise DataConflictError(message="api_key_already_exists")

            if sync_failed:
                raise DataValidationError(message="api_key_openrouter_sync_failed")

            logging.info(
                f"user={self.user['user_id']} updated API key {schema.name!r} (uid={uid}) — "
                f"{'synced to OpenRouter' if openrouter_synced else 'local changes only'}, is_main={schema.is_main}"
            )
            await delete_pattern(self.redis, cache_key.api_key_management_pattern())
            response.data = (await self.api_key_management_to_fetch_available_keys()).data
        except BaseError as e:
            logging.warning(
                f"user={self.user['user_id']} could not update API key uid={uid}: {e.message} ({e.status_code})"
            )
            raise
        except Exception:
            logging.error(
                f"user={self.user['user_id']} unexpected error updating API key uid={uid}\n{traceback.format_exc()}"
            )
            raise ServiceError()
        return response
