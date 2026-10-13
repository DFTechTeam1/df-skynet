import re
from datetime import datetime
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from utils import local_time
from utils.formatter import format_user_employees, format_datetime, format_employee_users
from typing import Any
from services.mysql.model import (
    DfEngineApiKeys,
    DfEngineApiKeySnapshots,
    DfEngineGenerations,
    Employees,
    Users,
)

HASH = re.compile(r"[0-9a-f]{64}")


class ApiKeyManagement:
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

    def mask_key(self, key: str) -> str:
        if len(key) <= 8:
            return key
        return f"{key[:4]}{'*' * 10}{key[-4:]}"

    def scrub_hashes(self, value: Any) -> Any:
        """Recursively mask any 64-hex key hash found in a string/dict/list."""
        if isinstance(value, str):
            return HASH.sub(lambda m: self.mask_key(m.group()), value)
        if isinstance(value, dict):
            return {k: self.scrub_hashes(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.scrub_hashes(v) for v in value]
        return value

    def format_log(self, record: dict[str, Any]) -> dict[str, Any]:
        """Shape one serialized DfEngineExternalApiCalls (type="openrouter") row for the API response.

        `request_headers` carries the OpenRouter management credential and is
        dropped outright. Newer rows are redacted on write, but older rows may
        still hold a plaintext secret key / hash, so scrub defensively.
        """
        record.pop("request_headers", None)
        record.pop("id", None)
        body = record.get("response_body")
        if isinstance(body, dict) and isinstance(body.get("key"), str):
            body["key"] = self.mask_key(body["key"])
        for field in ("endpoint", "response_headers", "response_body", "request_payload"):
            if record.get(field) is not None:
                record[field] = self.scrub_hashes(record[field])
        record["created_at"] = format_datetime(record["created_at"])
        return record

    def format(self, record: dict[str, Any]) -> dict[str, Any]:
        user_permissions = [
            "delete_df_engine_key_management",
            "update_df_engine_key_management",
            "copy_df_engine_key_management",
        ]
        is_expired = bool(record["expires_at"]) and datetime.fromisoformat(record["expires_at"]) <= local_time()

        record["created_at"] = format_datetime(record["created_at"])
        record["updated_at"] = format_datetime(record["updated_at"])
        record["expires_at"] = format_datetime(record["expires_at"])
        record["is_expired"] = is_expired
        record["creator"] = format_user_employees(record.pop("created_by_user", None))
        record["updater"] = format_user_employees(record.pop("updated_by_user", None))
        record["pic"] = format_employee_users(record.pop("employees", None))
        record["key"] = self.mask_key(record["key"])

        record["action"] = {
            "can_delete": "delete_df_engine_key_management" in user_permissions
            and (is_expired or not record["is_main"] or not record["hash"] or not record["employee_id"]),
            "can_update": "update_df_engine_key_management" in user_permissions
            and not is_expired
            and bool(record["hash"] and record["employee_id"]),
            "can_copy": "copy_df_engine_key_management" in user_permissions
            and not is_expired
            and bool(record["hash"] and record["employee_id"]),
            "can_set_to_main": "update_df_engine_key_management" in user_permissions
            and not is_expired
            and bool(record["hash"] and record["employee_id"])
            and not record["is_main"],
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

    async def archive(self, db: AsyncSession, record: DfEngineApiKeys) -> DfEngineApiKeySnapshots:
        """Copy `record` into `df_engine_api_key_snapshots` and repoint every generation made with it (the polymorphic
        `sourceable_id`/`sourceable_type`) at the snapshot. The caller deletes `record` afterwards."""
        snapshot = DfEngineApiKeySnapshots(
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
        db.add(snapshot)
        await db.flush()
        await db.execute(
            update(DfEngineGenerations)
            .where(
                DfEngineGenerations.sourceable_type == DfEngineApiKeys.__name__,  # type: ignore
                DfEngineGenerations.sourceable_id == record.id,  # type: ignore
            )
            .values(sourceable_id=snapshot.id, sourceable_type=DfEngineApiKeySnapshots.__name__)
        )
        return snapshot
