import time
import traceback
from uuid import UUID
from typing import Any, Optional
from fastapi import status, Path
from fastapi_controller import controller
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from apps.controller.core import CoreDependencies
from schemas.response import Response
from schemas.payload.api_key_management import ApiKeyPayload, ApiKeyUpdatePayload
from services.mysql.model import (
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
from utils import local_time
from services.api_caller import APICaller
from utils.serializer import serialize
from utils.formatter import format_user_employees, format_datetime, format_employee_users
# from apps.dependency.permission import require_permissions


key_management_permission = {
    "update_df_engine_key_management": "update_df_engine_key_management",
    "delete_df_engine_key_management": "delete_df_engine_key_management",
    "copy_df_engine_key_management": "copy_df_engine_key_management",
}

EMPLOYEE_STATUS_RESIGNED = 6
ALLOWED_PIC_POSITIONS = {"project manager", "assistant project manager"}


class APIKeyManagementController(CoreDependencies):
    def mask_key(self, key: str) -> str:
        if len(key) <= 12:
            return "*" * len(key)
        return f"{key[:8]}{'*' * 8}{key[-4:]}"

    def format_response(self, record: dict[str, Any], user_permissions: list[str]) -> dict[str, Any]:
        record["created_at"] = format_datetime(record["created_at"])
        record["updated_at"] = format_datetime(record["updated_at"])
        record["expired_at"] = format_datetime(record["expired_at"])
        record["creator"] = format_user_employees(record.pop("created_by_user", None))
        record["updater"] = format_user_employees(record.pop("updated_by_user", None))
        record["pic"] = format_employee_users(record.pop("employees", None))
        record["key"] = self.mask_key(record["key"])
        record["action"] = {
            "can_delete": key_management_permission["delete_df_engine_key_management"] in user_permissions
            and not record["is_main"],
            "can_update": key_management_permission["update_df_engine_key_management"] in user_permissions,
            "can_copy": key_management_permission["copy_df_engine_key_management"] in user_permissions,
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

        permissions = self.user.get("permissions", [])
        return [self.format_response(row, permissions) for row in serialize(records)]

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
            expired_at=record.expired_at,
            limit=record.limit,
            limit_reset=record.limit_reset,
            key=record.key,
            hash=record.hash,
            name=record.name,
            description=record.description,
            employee_name=await self.get_employee_name(record.employee_id),
            created_by=record.created_by,
            updated_by=record.updated_by,
        )

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

        try:
            async with APICaller(
                base_url=OPENROUTER_BASE_URL,
                headers=request_headers,
            ) as caller:
                openrouter_response = await caller.call(method, path, json=json_payload)
            response_body = openrouter_response.json() if openrouter_response.content else {}
            response_status_code = openrouter_response.status_code
            response_headers = dict(openrouter_response.headers)
            endpoint = str(openrouter_response.request.url)
            return response_body
        except Exception as exc:
            error_message = str(exc)
            raise
        finally:
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
    async def api_key_management_to_create_api_management(self, schema: ApiKeyPayload) -> Response:
        response = Response()
        payload = {
            "expires_at": schema.expires_at_iso,
            "include_byok_in_limit": True,
            "limit": schema.limit,
            "limit_reset": schema.limit_reset,
            "name": schema.name,
        }

        try:
            employee = await self.get_employee(schema.employee_uid)
            if schema.is_main:
                await self.ensure_single_main_api_key(employee.id)

            key_data = await self.call_openrouter("POST", "/keys", json_payload=payload)

            api_key = DfEngineApiKeys(
                name=schema.name,
                description=schema.description,
                key=key_data["key"],
                hash=key_data["data"]["hash"],
                employee_id=employee.id,
                limit=schema.limit,
                limit_reset=schema.limit_reset.value if schema.limit_reset else None,
                expired_at=schema.expires_at,
                created_by=int(self.user["user_id"]),
                is_main=schema.is_main,
            )
            self.db.add(api_key)
            try:
                await self.db.flush()
            except IntegrityError:
                raise DataConflictError(message="api_key_already_exists")

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
            "Meant to run automatically on a schedule (e.g. weekly). Replaces every "
            "active API key with a brand-new OpenRouter secret carrying the same name, "
            "assigned PIC, and spending limits, deactivates the old one on OpenRouter, "
            "and archives its details. If one key fails to rotate, the rest continue — "
            "the response lists which ones rotated cleanly (`rotated`), which failed "
            "outright with nothing changed (`failed`), and which are in a half-finished "
            "state that needs a human to check, such as a new key created but the old "
            "one couldn't be deactivated (`partial`)."
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
        rotated: list[str] = []
        failed: list[dict[str, str]] = []
        partial: list[dict[str, str]] = []
        try:
            old_rows = (await self.db.execute(select(DfEngineApiKeys))).scalars().all()

            for old in old_rows:
                if not old.hash:
                    failed.append({"uid": old.uid, "reason": "missing_hash"})
                    continue

                try:
                    key_data = await self.call_openrouter(
                        "POST",
                        "/keys",
                        json_payload={
                            "expires_at": f"{old.expired_at.isoformat()}Z" if old.expired_at else None,
                            "include_byok_in_limit": True,
                            "limit": old.limit,
                            "limit_reset": old.limit_reset,
                            "name": old.name,
                        },
                    )
                except Exception:
                    failed.append({"uid": old.uid, "reason": "create_failed"})
                    continue

                try:
                    async with self.db.begin_nested():
                        new_key = DfEngineApiKeys(
                            key=key_data["key"],
                            hash=key_data["data"]["hash"],
                            name=old.name,
                            description=old.description,
                            employee_id=old.employee_id,
                            employee_name=old.employee_name,
                            limit=old.limit,
                            limit_reset=old.limit_reset,
                            expired_at=old.expired_at,
                            is_main=old.is_main,
                            created_by=int(self.user["user_id"]),
                        )
                        self.db.add(new_key)
                        await self.db.flush()
                except IntegrityError:
                    failed.append({"uid": old.uid, "reason": "new_key_conflict"})
                    continue

                try:
                    await self.call_openrouter(
                        "PATCH",
                        f"/keys/{old.hash}",
                        json_payload={
                            "disabled": True,
                            "include_byok_in_limit": True,
                            "limit": old.limit,
                            "limit_reset": old.limit_reset,
                            "name": old.name,
                        },
                    )
                except Exception:
                    partial.append({"uid": old.uid, "new_key_uid": new_key.uid, "reason": "old_key_not_disabled"})
                    continue

                try:
                    async with self.db.begin_nested():
                        self.db.add(await self.to_snapshot(old))
                        await self.db.delete(old)
                        await self.db.flush()
                except IntegrityError:
                    partial.append({"uid": old.uid, "new_key_uid": new_key.uid, "reason": "archive_failed"})
                    continue

                rotated.append(new_key.uid)

            response.data = {"rotated": rotated, "failed": failed, "partial": partial}
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
            if record.is_main:
                raise DataValidationError(message="cannot_delete_main_api_key")
            if not record.hash:
                raise DataValidationError(message="api_key_missing_hash")

            await self.call_openrouter("DELETE", f"/keys/{record.hash}")

            self.db.add(await self.to_snapshot(record))
            await self.db.delete(record)
            await self.db.flush()

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
            response.data = record.key
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
        # dependencies=[
        #     Depends(require_permissions(["update_df_engine_key_management"])) # Will be enabled later
        # ]
    )
    async def api_key_management_with_uid_to_update_record(
        self,
        schema: ApiKeyUpdatePayload,
        uid: UUID = Path(
            ...,
            description="API key UID.",
            examples=["8d96ff4e-5c35-4329-bd5d-827e2c68599d"],
        ),
    ) -> Response:
        response = Response()
        try:
            record = await self.get_api_key(uid)
            employee = await self.get_employee(schema.employee_uid)
            if schema.is_main:
                await self.ensure_single_main_api_key(employee.id, exclude_id=record.id)

            new_limit_reset = schema.limit_reset.value if schema.limit_reset else None
            current_limit = float(record.limit) if record.limit is not None else None
            if current_limit != schema.limit or record.limit_reset != new_limit_reset:
                if not record.hash:
                    raise DataValidationError(message="api_key_missing_hash")
                await self.call_openrouter(
                    "PATCH",
                    f"/keys/{record.hash}",
                    json_payload={
                        "disabled": False,
                        "include_byok_in_limit": True,
                        "limit": schema.limit,
                        "limit_reset": new_limit_reset,
                        "name": schema.name,
                    },
                )

            record.name = schema.name
            record.description = schema.description
            record.employee_id = employee.id
            record.employee_name = employee.nickname or employee.name
            record.limit = schema.limit
            record.limit_reset = new_limit_reset
            record.is_main = schema.is_main
            record.updated_by = int(self.user["user_id"])

            try:
                await self.db.flush()
            except IntegrityError:
                raise DataConflictError(message="api_key_already_exists")

            response.data = await self.get_api_keys()
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response
