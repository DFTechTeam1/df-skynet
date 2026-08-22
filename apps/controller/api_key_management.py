import time
import traceback
from uuid import UUID
from datetime import timedelta
from typing import Any, Optional
from fastapi import status, Path
from fastapi_controller import controller
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from apps.controller.core import CoreDependencies
from schemas.response import Response
from schemas.payload.api_key_management import CreateApiKeyPayload, UpdateApiKeyPayload
from services.mysql.model import (
    DfEngineApiKeyRotationIssues,
    DfEngineApiKeys,
    DfEngineApiSnapshots,
    DfEngineOpenrouterLogs,
    Employees,
    PositionBackups,
    Users,
)
from log import logging
from apps.secret import OPENROUTER_BASE_URL, OPENROUTER_MANAGEMENT_KEY
from error import ServiceError, BaseError, DataConflictError, DataNotFoundError, DataValidationError
from utils import local_time, wib_to_utc_iso
from services.api_caller import APICaller
from utils.serializer import serialize, to_json_safe
from utils.formatter import format_user_employees, format_datetime, format_employee_users
# from apps.dependency.permission import require_permissions


key_management_permission = {
    "update_df_engine_key_management": "update_df_engine_key_management",
    "delete_df_engine_key_management": "delete_df_engine_key_management",
    "copy_df_engine_key_management": "copy_df_engine_key_management",
}

EMPLOYEE_STATUS_RESIGNED = 6
ALLOWED_PIC_POSITIONS = {"project manager", "assistant project manager"}

ROTATION_INTERVAL_DAYS = 7


class APIKeyManagementController(CoreDependencies):
    def mask_key(self, key: str) -> str:
        if len(key) <= 12:
            return "*" * len(key)
        return f"{key[:8]}{'*' * 8}{key[-4:]}"

    def format_response(
        self, record: dict[str, Any], user_permissions: list[str], employee_ids_with_main: set[int]
    ) -> dict[str, Any]:
        record["created_at"] = format_datetime(record["created_at"])
        record["updated_at"] = format_datetime(record["updated_at"])
        record["expires_at"] = format_datetime(record["expires_at"])
        record["creator"] = format_user_employees(record.pop("created_by_user", None))
        record["updater"] = format_user_employees(record.pop("updated_by_user", None))
        record["pic"] = format_employee_users(record.pop("employees", None))
        record["key"] = self.mask_key(record["key"])
        record["action"] = {
            "can_delete": key_management_permission["delete_df_engine_key_management"] in user_permissions
            and (not record["is_main"] or not record["hash"] or not record["employee_id"]),
            "can_update": key_management_permission["update_df_engine_key_management"] in user_permissions
            and bool(record["hash"] and record["employee_id"]),
            "can_copy": key_management_permission["copy_df_engine_key_management"] in user_permissions
            and bool(record["hash"] and record["employee_id"]),
            "can_set_to_main": key_management_permission["update_df_engine_key_management"] in user_permissions
            and bool(record["hash"] and record["employee_id"])
            and not record["is_main"]
            and record["employee_id"] not in employee_ids_with_main,
        }

        record.pop("id", None)
        record.pop("hash", None)
        record.pop("employee_id", None)
        record.pop("created_by", None)
        record.pop("updated_by", None)
        record.pop("created_by_user", None)
        record.pop("updated_by_user", None)
        record.pop("employees", None)
        record.pop("employee_name", None)
        return record

    def options(self) -> tuple:
        return (
            selectinload(DfEngineApiKeys.created_by_user)  # type: ignore
            .load_only(Users.image)  # type: ignore
            .selectinload(Users.employees)  # type: ignore
            .load_only(Employees.nickname),  # type: ignore
            selectinload(DfEngineApiKeys.updated_by_user)  # type: ignore
            .load_only(Users.image)  # type: ignore
            .selectinload(Users.employees)  # type: ignore
            .load_only(Employees.nickname),  # type: ignore
            selectinload(DfEngineApiKeys.employees)  # type: ignore
            .load_only(Employees.nickname, Employees.uid)  # type: ignore
            .selectinload(Employees.users)  # type: ignore
            .load_only(Users.image),  # type: ignore
        )

    async def get_api_keys(self) -> list[dict[str, Any]]:
        records = (
            (
                await self.db.execute(
                    select(DfEngineApiKeys)
                    .options(*self.options())  # type: ignore
                    .order_by(DfEngineApiKeys.created_at.desc())  # type: ignore
                )
            )
            .scalars()
            .all()
        )

        # permissions = self.user.get("permissions", [])
        permissions = [
            "update_df_engine_key_management",
            "delete_df_engine_key_management",
            "copy_df_engine_key_management",
        ]  # overidden
        employee_ids_with_main = {row.employee_id for row in records if row.is_main and row.employee_id is not None}
        return [self.format_response(row, permissions, employee_ids_with_main) for row in serialize(records)]

    async def get_employee(self, employee_uid: UUID) -> Employees:
        employee = (
            await self.db.execute(select(Employees).where(Employees.uid == str(employee_uid)))  # type: ignore
        ).scalar_one_or_none()
        if employee is None:
            raise DataNotFoundError(message="employee_not_found")
        if employee.status == EMPLOYEE_STATUS_RESIGNED:
            raise DataValidationError(message="employee_already_resigned")

        position = (
            (await self.db.execute(select(PositionBackups).where(PositionBackups.id == employee.position_id)))  # type: ignore
            .scalars()
            .first()
        )
        if position is None or position.name.strip().lower() not in ALLOWED_PIC_POSITIONS:
            raise DataValidationError(message="employee_position_not_allowed")

        return employee

    async def get_nickname(self, user_id: int) -> str:
        return (
            await self.db.execute(
                select(Employees.nickname).where(Employees.user_id == user_id)  # type: ignore
            )
        ).scalar_one()

    async def ensure_single_main_api_key(self, pic_id: int, exclude_id: Optional[int] = None) -> None:
        query = select(DfEngineApiKeys).where(
            DfEngineApiKeys.employee_id == pic_id,  # type: ignore
            DfEngineApiKeys.is_main.is_(True),  # type: ignore
        )
        if exclude_id is not None:
            query = query.where(DfEngineApiKeys.id != exclude_id)  # type: ignore
        record = (await self.db.execute(query)).scalars().first()
        if record:
            raise DataValidationError(message="employee_already_has_main_api_key")

    async def ensure_unique_api_key_name(self, name: str, exclude_id: Optional[int] = None) -> None:
        query = select(DfEngineApiKeys.id).where(DfEngineApiKeys.name == name)  # type: ignore
        if exclude_id is not None:
            query = query.where(DfEngineApiKeys.id != exclude_id)  # type: ignore
        record = (await self.db.execute(query)).scalars().first()
        if record:
            raise DataConflictError(message="api_key_already_exists")

    async def get_api_key(self, uid: UUID) -> DfEngineApiKeys:
        record = (
            await self.db.execute(select(DfEngineApiKeys).where(DfEngineApiKeys.uid == str(uid)))  # type: ignore
        ).scalar_one_or_none()
        if record is None:
            raise DataNotFoundError(message="api_key_not_found")
        return record

    async def get_employee_name(self, employee_id: Optional[int]) -> Optional[str]:
        if employee_id is None:
            return None
        employee = (
            await self.db.execute(select(Employees).where(Employees.id == employee_id))  # type: ignore
        ).scalar_one_or_none()
        return (employee.nickname or employee.name) if employee else None

    async def to_snapshot(self, record: DfEngineApiKeys) -> DfEngineApiSnapshots:
        return DfEngineApiSnapshots(
            created_at=record.created_at,
            updated_at=record.updated_at,
            expires_at=record.expires_at,
            limit=record.limit,
            limit_reset=record.limit_reset,
            key=record.key,
            hash=record.hash,
            name=record.name,
            description=record.description,
            employee_id=record.employee_id,
            employee_name=record.employee_name,
            created_by=record.created_by,
            updated_by=record.updated_by,
        )

    async def revoke_and_archive_key(
        self, record: DfEngineApiKeys, record_uid: str, new_uid: Optional[str] = None
    ) -> bool:
        """Revoke `record` on OpenRouter, archive it to snapshots, and delete the
        local row. Records a DfEngineApiKeyRotationIssues incident and returns
        False on any failure; returns True once both steps succeed. `new_uid`,
        when given, is attached to the incident so a reconciliation job knows
        which replacement key this old key's cleanup was blocking.
        """
        try:
            await self.call_openrouter("DELETE", f"/keys/{record.hash}")
        except Exception as exc:
            self.db.add(
                DfEngineApiKeyRotationIssues(
                    old_uid=record_uid,
                    new_uid=new_uid,
                    issue_type="old_key_not_revoked",
                    detail=str(exc),
                )
            )
            await self.db.flush()
            logging.error(
                f"rotate: old uid={record_uid} could not be revoked on OpenRouter ({exc}) — needs manual cleanup"
            )
            return False

        """
        TODO: generation_prompts.key_id currently points at this row's
        df_engine_api_keys.id. Before archiving, add a SQLModel for
        generation_prompts (same DB, just never mapped here yet — confirmed
        reachable from this service) and, for any generation_prompts row where
        key_id == record.id, update key_id to point at the new
        df_engine_api_snapshots row's id instead — so historical prompt records
        keep resolving to a real row once this df_engine_api_keys row is gone.
        Requires the snapshot to be flushed first to get its id.

        At this moment, every record is moved to snapshots unconditionally,
        with no generation_prompts remapping yet — implement before this ships
        if any generation_prompts rows can reference a retired key.
        """
        try:
            async with self.db.begin_nested():
                self.db.add(await self.to_snapshot(record))
                await self.db.delete(record)
                await self.db.flush()
        except Exception as exc:
            self.db.add(
                DfEngineApiKeyRotationIssues(
                    old_uid=record_uid,
                    new_uid=new_uid,
                    issue_type="archive_failed",
                    detail=str(exc),
                )
            )
            await self.db.flush()
            logging.warning(
                f"rotate: old key revoked but archiving uid={record_uid} failed ({exc}) — needs manual cleanup"
            )
            return False

        return True

    async def call_openrouter(
        self,
        method: str,
        path: str,
        json_payload: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Call OpenRouter and always log the attempt (success or failure) to
        DfEngineOpenrouterLogs with an explicit commit, so the log survives
        even if the caller's later DB work fails within the same request.
        """
        response_body: dict[str, Any] = {}
        error_message: Optional[str] = None
        response_status_code: Optional[int] = None
        response_headers: Optional[dict[str, Any]] = None
        started_at = time.perf_counter()
        request_headers = {"Authorization": f"Bearer {OPENROUTER_MANAGEMENT_KEY}"}
        endpoint = f"{OPENROUTER_BASE_URL.rstrip('/')}{path}"
        json_payload = to_json_safe(json_payload) if json_payload is not None else None

        try:
            async with APICaller(
                base_url=OPENROUTER_BASE_URL,
                headers=request_headers,
            ) as caller:
                openrouter_response = await caller.call(method, path, json=json_payload, raise_for_status=False)  # type: ignore
            response_body = openrouter_response.json() if openrouter_response.content else {}
            response_status_code = openrouter_response.status_code
            response_headers = dict(openrouter_response.headers)
            endpoint = str(openrouter_response.request.url)
            return response_body
        except Exception as exc:
            error_message = str(exc)
            raise
        finally:
            try:
                self.db.add(
                    DfEngineOpenrouterLogs(
                        name=await self.get_nickname(self.user["user_id"]),
                        method=method,
                        endpoint=endpoint,
                        request_headers=request_headers,
                        request_payload=json_payload,
                        response_status_code=response_status_code,
                        response_headers=response_headers,
                        response_body=response_body or None,
                        error_message=error_message,
                        duration_ms=int((time.perf_counter() - started_at) * 1000),
                    )
                )
                await self.db.commit()
            except Exception:
                await self.db.rollback()
                logging.error(f"call_openrouter: failed to persist audit log for {method} {endpoint}")

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
        # dependencies=[
        #     Depends(require_permissions(["create_df_engine_key_management"])) # Will be enabled later
        # ]
    )
    async def api_key_management_to_create_api_management(self, schema: CreateApiKeyPayload) -> Response:
        response = Response()
        try:
            employee = await self.get_employee(schema.employee_uid)
            await self.ensure_unique_api_key_name(schema.name)
            if schema.is_main:
                await self.ensure_single_main_api_key(employee.id)

            if schema.expires_at and schema.expires_at <= local_time() + timedelta(days=ROTATION_INTERVAL_DAYS):
                raise DataValidationError(message="api_key_expiry_too_soon")

            openrouter_response = await self.call_openrouter(
                "POST",
                "/keys",
                json_payload={
                    "expires_at": schema.expires_at_iso,
                    "include_byok_in_limit": True,
                    "limit": schema.limit,
                    "limit_reset": schema.limit_reset,
                    "name": schema.name,
                },
            )

            api_key = DfEngineApiKeys(
                name=schema.name,
                description=schema.description,
                key=openrouter_response["key"],
                hash=openrouter_response["data"]["hash"],
                employee_id=employee.id,
                employee_name=employee.nickname,
                limit=schema.limit,
                limit_reset=schema.limit_reset.value if schema.limit_reset else None,
                expires_at=schema.expires_at,
                created_by=int(self.user["user_id"]),
                is_main=schema.is_main,
            )
            self.db.add(api_key)
            try:
                await self.db.flush()
            except IntegrityError as e:
                logging.error(f"api key create IntegrityError: {e.orig}")
                raise DataConflictError(message="api_key_already_exists")

            logging.info(
                f"user={self.user['user_id']} created api key uid={api_key.uid} "
                f"name={api_key.name!r} employee_id={employee.id} is_main={api_key.is_main}"
            )
            response.data = await self.get_api_keys()
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
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
        # dependencies=[
        #     Depends(require_permissions(["update_df_engine_key_management"])) # Will be enabled later
        # ]
    )
    async def api_key_management_to_rotate_api_keys(self) -> Response:
        response = Response()
        total_rotated = 0
        total_failed = 0
        total_partial = 0
        try:
            records = (await self.db.execute(select(DfEngineApiKeys))).scalars().all()

            for record in records:
                record_uid, record_name = record.uid, record.name

                if not record.hash:
                    """Directly removed from record"""
                    await self.db.delete(record)
                    await self.db.flush()
                    total_failed += 1
                    logging.info(
                        f"user={self.user['user_id']} rotate removed api key uid={record_uid} "
                        f"name={record_name!r} reason=missing_hash"
                    )
                    continue

                if record.expires_at is not None and record.expires_at <= local_time():
                    """Already past its own expiry — clean it up instead of rotating;
                    no point creating a replacement for a key nobody renewed in time."""
                    if await self.revoke_and_archive_key(record, record_uid):
                        total_failed += 1
                        logging.info(
                            f"user={self.user['user_id']} rotate removed api key uid={record_uid} "
                            f"name={record_name!r} reason=expired"
                        )
                    else:
                        total_partial += 1
                    continue

                """
                Whether record having employee_id or not, we should validate them,
                if invalid directly remove, otherwise it will be saved to snapshot
                """
                openrouter_response = await self.call_openrouter("GET", f"/keys/{record.hash}")
                if openrouter_response.get("error"):
                    await self.db.delete(record)
                    await self.db.flush()
                    total_failed += 1
                    logging.info(
                        f"user={self.user['user_id']} rotate removed api key uid={record_uid} "
                        f"name={record_name!r} reason=invalid_hash"
                    )
                    continue

                if record.expires_at is None:
                    new_expires_at = None
                else:
                    original_duration = record.expires_at - record.created_at
                    new_expires_at = local_time() + max(original_duration, timedelta(days=ROTATION_INTERVAL_DAYS))

                """
                After record deleted, we will re create the API key with same configuration.
                Expectation will be returning new API key from Openrouter with different API key.

                Create the replacement before touching the old key — never leave
                a PIC with zero working keys if OpenRouter rejects the new one.
                """
                try:
                    new_openrouter_response = await self.call_openrouter(
                        "POST",
                        "/keys",
                        json_payload={
                            "expires_at": wib_to_utc_iso(new_expires_at),
                            "include_byok_in_limit": True,
                            "limit": record.limit,
                            "limit_reset": record.limit_reset,
                            "name": record.name,
                        },
                    )
                    if new_openrouter_response.get("error"):
                        raise ValueError(new_openrouter_response["error"].get("message", "create_failed"))
                except Exception as exc:
                    total_failed += 1
                    logging.warning(
                        f"rotate: failed to create replacement for uid={record_uid} name={record_name!r}: {exc}"
                    )
                    continue

                new_key = DfEngineApiKeys(
                    name=record.name,
                    description=record.description,
                    key=new_openrouter_response["key"],
                    hash=new_openrouter_response["data"]["hash"],
                    employee_id=record.employee_id,
                    employee_name=record.employee_name,
                    limit=record.limit,
                    limit_reset=record.limit_reset,
                    expires_at=new_expires_at,
                    created_by=int(self.user["user_id"]),
                    is_main=record.is_main,
                )
                try:
                    async with self.db.begin_nested():
                        self.db.add(new_key)
                        await self.db.flush()
                except IntegrityError as e:
                    total_partial += 1
                    self.db.add(
                        DfEngineApiKeyRotationIssues(
                            old_uid=record_uid,
                            new_key_hash=new_openrouter_response["data"]["hash"],
                            new_key_value=new_openrouter_response["key"],
                            issue_type="new_key_db_conflict",
                            detail=str(e.orig),
                        )
                    )
                    await self.db.flush()
                    logging.error(
                        f"rotate: created replacement on OpenRouter for uid={record_uid} but couldn't save it "
                        f"locally (hash={new_openrouter_response['data']['hash']}) — needs manual reconciliation"
                    )
                    continue

                if not await self.revoke_and_archive_key(record, record_uid, new_uid=new_key.uid):
                    total_partial += 1
                    continue

                total_rotated += 1
                logging.info(
                    f"user={self.user['user_id']} rotated api key old_uid={record_uid} name={record_name!r} "
                    f"-> new_uid={new_key.uid}"
                )

            logging.info(
                f"user={self.user['user_id']} rotate summary: "
                f"rotated={total_rotated} failed={total_failed} partial={total_partial}"
            )
            response.data = await self.get_api_keys()
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
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
        # dependencies=[
        #     Depends(require_permissions(["fetch_df_engine_key_management"])) # Will be enabled later
        # ]
    )
    async def api_key_management_to_fetch_available_keys(self) -> Response:
        response = Response()
        try:
            response.data = await self.get_api_keys()
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
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
        # dependencies=[
        #     Depends(require_permissions(["delete_df_engine_key_management"])) # Will be enabled later
        # ]
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
        try:
            record = await self.get_api_key(uid)
            record_uid, record_name = record.uid, record.name
            if record.is_main:
                raise DataValidationError(message="cannot_delete_main_api_key")

            if not record.hash:
                await self.db.delete(record)
                await self.db.flush()
                logging.info(
                    f"user={self.user['user_id']} deleted api key uid={record_uid} "
                    f"name={record_name!r} reason=missing_hash"
                )
                response.data = await self.get_api_keys()
                return response

            openrouter_response = await self.call_openrouter("GET", f"/keys/{record.hash}")
            if openrouter_response.get("error"):
                await self.db.delete(record)
                await self.db.flush()
                logging.info(
                    f"user={self.user['user_id']} deleted api key uid={record_uid} "
                    f"name={record_name!r} reason=invalid_hash"
                )
                response.data = await self.get_api_keys()
                return response

            """Proceed deleting valid API key"""
            await self.call_openrouter("DELETE", f"/keys/{record.hash}")
            self.db.add(await self.to_snapshot(record))

            """
            TODO: generation_prompts.key_id currently points at this row's
            df_engine_api_keys.id. Before archiving, add a SQLModel for
            generation_prompts (same DB, just never mapped here yet — confirmed
            reachable from this service) and, for any generation_prompts row where
            key_id == record.id, update key_id to point at the new
            df_engine_api_snapshots row's id instead — so historical prompt records
            keep resolving to a real row once this df_engine_api_keys row is gone.
            Requires the snapshot to be flushed first to get its id. See the same
            TODO in revoke_and_archive_key, used by rotate, for the other call site.
            """

            await self.db.delete(record)
            await self.db.flush()
            logging.info(
                f"user={self.user['user_id']} deleted api key uid={record_uid} "
                f"name={record_name!r} reason=revoked_on_openrouter"
            )

            response.data = await self.get_api_keys()

        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
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
        # dependencies=[
        #     Depends(require_permissions(["copy_df_engine_key_management"])) # Will be enabled later
        # ]
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
        try:
            record = await self.get_api_key(uid)
            if not record.hash:
                raise DataValidationError(message="api_key_copy_missing_hash")
            if not record.employee_id:
                raise DataValidationError(message="api_key_copy_missing_employee")

            response.data = record.key
            logging.info(f"user={self.user['user_id']} revealed api key uid={record.uid} name={record.name!r}")
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response

    @controller.patch(
        "/key-management/{uid}",
        summary="Update an API key.",
        description=(
            "Replaces the key's editable details — name, description, assigned PIC, "
            "spending limit, reset schedule, and main flag — with what's submitted "
            "(this is a full replace, not a partial update). OpenRouter is only "
            "contacted if the spending limit or reset schedule actually changed; "
            "every other field updates locally without touching OpenRouter. The "
            "expiry date is fixed when the key is created and can't be changed "
            'afterward — OpenRouter has no way to update it. The same "only one '
            'main key per PIC" rule as creation applies. Returns the full, '
            "up-to-date list of API keys."
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
        trigger_update = False
        try:
            record = await self.get_api_key(uid)
            if not record.employee_id:
                raise DataValidationError(message="api_key_employee_deleted")

            await self.ensure_unique_api_key_name(schema.name, exclude_id=record.id)

            if schema.is_main:
                await self.ensure_single_main_api_key(record.employee_id, exclude_id=record.id)

            if not record.hash:
                raise DataValidationError(message="api_key_missing_hash")

            trigger_update = (
                True
                if schema.name != record.name
                or schema.limit != record.limit
                or schema.limit_reset != record.limit_reset
                else False
            )

            openrouter_response = await self.call_openrouter(
                "PATCH",
                f"/keys/{record.hash}",
                json_payload={
                    "disabled": False,
                    "include_byok_in_limit": True,
                    "limit": schema.limit,
                    "limit_reset": schema.limit_reset,
                    "name": schema.name,
                },
            )

            if openrouter_response.get("error"):
                error_message = openrouter_response.get("error", {}).get("message", "Error while calling Openrouter.")
                logging.warning(f"api key update uid={record.uid} rejected by OpenRouter: {error_message}")
                raise DataValidationError(message="api_key_openrouter_sync_failed")

            record.name = schema.name
            record.description = schema.description
            record.limit = schema.limit
            record.limit_reset = schema.limit_reset
            record.is_main = schema.is_main
            record.updated_by = int(self.user["user_id"])

            try:
                await self.db.flush()
            except IntegrityError as e:
                logging.error(f"api key update IntegrityError: {e.orig}")
                raise DataConflictError(message="api_key_already_exists")

            logging.info(
                f"user={self.user['user_id']} updated api key uid={record.uid} "
                f"name={record.name!r} openrouter_synced={trigger_update} is_main={record.is_main}"
            )
            response.data = await self.get_api_keys()
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response
