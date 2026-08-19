import traceback
from uuid import UUID, uuid4
from typing import Any, Optional
from fastapi import status, Path
from fastapi_controller import controller
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from apps.controller.core import CoreDependencies
from schemas.response import Response
from schemas.payload.api_key_management import ApiKeyPayload
from services.mysql.model import DfEngineApiKeys, Employees, PositionBackups, Users
from log import logging
from error import ServiceError, BaseError, DataConflictError, DataNotFoundError, DataValidationError
from utils import local_time
from utils.serializer import serialize
from utils.formatter import format_creator, format_datetime, format_pic
# from apps.dependency.permission import require_permissions


key_management_permission = {
    "fetch_df_engine_key_management": "fetch_df_engine_key_management",
    "update_df_engine_key_management": "update_df_engine_key_management",
    "delete_df_engine_key_management": "delete_df_engine_key_management",
}

EMPLOYEE_STATUS_RESIGNED = 6
ALLOWED_PIC_POSITIONS = {"project manager", "assistant project manager"}


class APIKeyManagementController(CoreDependencies):
    def query_options(self):
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
            .load_only(Employees.nickname)  # type: ignore
            .selectinload(Employees.users)  # type: ignore
            .load_only(Users.image),  # type: ignore
        )

    def mask_key(self, key: str) -> str:
        if len(key) <= 12:
            return "•" * len(key)
        return f"{key[:8]}{'•' * 8}{key[-4:]}"

    def format_response(self, row: dict[str, Any], permissions: list[str], mask: bool = True) -> dict[str, Any]:
        if mask:
            row["key"] = self.mask_key(row["key"])
        row["created_at"] = format_datetime(row["created_at"])
        row["updated_at"] = format_datetime(row["updated_at"])
        row["expired_at"] = format_datetime(row["expired_at"])
        row["creater"] = format_creator(row.pop("created_by_user", None))
        row["updater"] = format_creator(row.pop("updated_by_user", None))
        row["pic"] = format_pic(row.pop("employees", None))
        row["action"] = {
            "can_fetch_key_management": key_management_permission["fetch_df_engine_key_management"] in permissions,
            "can_update_key_management": key_management_permission["update_df_engine_key_management"] in permissions,
            "can_delete_key_management": key_management_permission["delete_df_engine_key_management"] in permissions,
        }

        row.pop("id", None)
        row.pop("employee_id", None)
        row.pop("created_by", None)
        row.pop("updated_by", None)
        row.pop("deleted_at", None)
        return row

    async def get_api_keys(self) -> list[dict[str, Any]]:
        """Fetch all non-deleted API keys, newest first, shaped for the frontend:
        masked `key`, resolved `creater`/`updater`/`pic`, and an `action` block."""
        records = (
            (
                await self.db.execute(
                    select(DfEngineApiKeys)
                    .where(DfEngineApiKeys.deleted_at.is_(None))  # type: ignore
                    .options(*self.query_options())  # type: ignore
                    .order_by(DfEngineApiKeys.created_at.desc())  # type: ignore
                )
            )
            .scalars()
            .all()
        )

        permissions = self.user.get("permissions", [])
        return [self.format_response(row, permissions) for row in serialize(records)]

    async def get_api_key(self, uid: UUID) -> DfEngineApiKeys:
        record = (
            await self.db.execute(
                select(DfEngineApiKeys).where(
                    DfEngineApiKeys.uid == str(uid),  # type: ignore
                    DfEngineApiKeys.deleted_at.is_(None),  # type: ignore
                )
            )
        ).scalar_one_or_none()
        if record is None:
            raise DataNotFoundError(message="api_key_not_found")
        return record

    async def get_api_key_detail(self, uid: UUID) -> dict[str, Any]:
        record = (
            await self.db.execute(
                select(DfEngineApiKeys)
                .where(
                    DfEngineApiKeys.uid == str(uid),  # type: ignore
                    DfEngineApiKeys.deleted_at.is_(None),  # type: ignore
                )
                .options(*self.query_options())  # type: ignore
            )
        ).scalar_one_or_none()
        if record is None:
            raise DataNotFoundError(message="api_key_not_found")

        permissions = self.user.get("permissions", [])
        return self.format_response(serialize(record), permissions, mask=False)

    async def resolve_employee_id(self, employee_uid: UUID) -> int:
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

        return employee.id

    async def ensure_name_available(self, name: str, exclude_id: Optional[int] = None) -> None:
        """`name` has no DB-level unique constraint (see the creation migration) — it
        must stay unique only among non-deleted rows, so a soft-deleted key's name is
        free to reuse. Checked here instead."""
        query = select(DfEngineApiKeys.id).where(  # type: ignore
            DfEngineApiKeys.name == name,  # type: ignore
            DfEngineApiKeys.deleted_at.is_(None),  # type: ignore
        )
        if exclude_id is not None:
            query = query.where(DfEngineApiKeys.id != exclude_id)  # type: ignore

        existing = (await self.db.execute(query)).scalar_one_or_none()
        if existing is not None:
            raise DataConflictError(message="api_key_already_exists")

    @controller.post(
        "/key-management",
        summary="Create an API key.",
        description=(
            "Registers a new API key (`df_engine_api_keys` row). `employee_uid` addresses "
            "the PIC via `employees.uid` and is resolved server-side to `employee_id` — the "
            "employee must exist (404 otherwise), must not already be resigned, and must "
            "hold a Project Manager or Assistant Project Manager position (422 otherwise). "
            "`name` must be unique among non-deleted keys — a deleted key's name is free "
            "to reuse. The record's "
            "`created_by` is taken from the authenticated user resolved from the bearer "
            "token, not from the request body. Returns the full, up-to-date list of API "
            "keys, so the frontend can refresh its list without a separate re-fetch."
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
        try:
            await self.ensure_name_available(schema.name)
            employee_id = await self.resolve_employee_id(schema.employee_uid)

            api_key = DfEngineApiKeys(
                uid=str(uuid4()),
                name=schema.name,
                description=schema.description,
                key=schema.api_key,
                employee_id=employee_id,
                limit_usage=schema.limit_usage,
                limit_reset=schema.limit_reset.value if schema.limit_reset else None,
                expired_at=schema.expired_at,
                is_active=schema.is_active,
                created_by=int(self.user["user_id"]),
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

    @controller.get(
        "/key-management",
        summary="List API keys.",
        description=(
            "Returns all API keys (`df_engine_api_keys` rows), newest first — both active "
            "and inactive. Each key includes its resolved `creater`/`updater` and `pic` "
            '(`{"image", "nickname"}` each), its `key` masked to the first 8 and last 4 '
            "characters, and an `action` block reflecting which key-management actions the "
            "current user is permitted to perform."
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

    @controller.get(
        "/key-management/{uid}",
        summary="Detail of an API key.",
        description=(
            "Returns a single API key identified by `uid`, in the same shape as an item "
            "from the list endpoint — except `key` is returned in full, unmasked, so the "
            "frontend can display or copy the real value on this screen. 404s if no key "
            "matches `uid`."
        ),
        status_code=status.HTTP_200_OK,
        tags=["API Key Management"],
        response_model=Response,
        # dependencies=[
        #     Depends(require_permissions(["fetch_df_engine_key_management"])) # Will be enabled later
        # ]
    )
    async def api_key_management_with_uid_to_fetch_detail(
        self,
        uid: UUID = Path(
            ...,
            description="Key UID.",
            examples=["df4a895e-d915-4c01-b687-a03fffa6919a"],
        ),
    ) -> Response:
        response = Response()
        try:
            response.data = await self.get_api_key_detail(uid)
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
            "Replaces the API key identified by `uid` — the request body carries the full "
            "record, not a partial diff. `employee_uid` is re-resolved on every update (must "
            "exist, must not be resigned, must hold a Project Manager or Assistant Project "
            "Manager position). `name` must remain unique among non-deleted keys. The "
            "record's `updated_by`/`updated_at` are taken from the authenticated "
            "user and server clock, not from the request body. Returns the full, up-to-date "
            "list of API keys."
        ),
        status_code=status.HTTP_200_OK,
        tags=["API Key Management"],
        response_model=Response,
        # dependencies=[
        #     Depends(require_permissions(["update_df_engine_key_management"])) # Will be enabled later
        # ]
    )
    async def api_key_management_with_uid_to_update(
        self,
        schema: ApiKeyPayload,
        uid: UUID = Path(
            ...,
            description="Key UID.",
            examples=["df4a895e-d915-4c01-b687-a03fffa6919a"],
        ),
    ) -> Response:
        response = Response()
        try:
            api_key = await self.get_api_key(uid)
            await self.ensure_name_available(schema.name, exclude_id=api_key.id)
            employee_id = await self.resolve_employee_id(schema.employee_uid)

            api_key.name = schema.name
            api_key.description = schema.description
            api_key.key = schema.api_key
            api_key.employee_id = employee_id
            api_key.limit_usage = schema.limit_usage
            api_key.limit_reset = schema.limit_reset.value if schema.limit_reset else None
            api_key.expired_at = schema.expired_at
            api_key.is_active = schema.is_active
            api_key.updated_by = int(self.user["user_id"])
            api_key.updated_at = local_time()

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

    @controller.delete(
        "/key-management/{uid}",
        summary="Delete an API key.",
        description=(
            "Soft-deletes the API key identified by `uid` (sets `deleted_at`) rather than "
            "removing the row — other tables may still reference this key's id. Once "
            "deleted, its `name` becomes available for reuse by a new key. Returns the "
            "full, up-to-date list of remaining (non-deleted) API keys."
        ),
        status_code=status.HTTP_200_OK,
        tags=["API Key Management"],
        response_model=Response,
        # dependencies=[
        #     Depends(require_permissions(["delete_df_engine_key_management"])) # Will be enabled later
        # ]
    )
    async def api_key_management_with_uid_to_delete(
        self,
        uid: UUID = Path(
            ...,
            description="Key UID.",
            examples=["df4a895e-d915-4c01-b687-a03fffa6919a"],
        ),
    ) -> Response:
        response = Response()
        try:
            api_key = await self.get_api_key(uid)

            api_key.deleted_at = local_time()
            await self.db.flush()

            response.data = await self.get_api_keys()
        except BaseError:
            raise
        except Exception:
            logging.error(traceback.format_exc())
            raise ServiceError()
        return response
