from typing import Any, Literal, Optional

from services.mysql.model import DfEngineModelOptions
from utils import epoch_to_wib
from utils.formatter import format_datetime


class ModelManagement:
    """Query-building and response-shaping helpers for the model-management
    endpoints. The controller keeps the orchestration (DB calls, validation,
    cache invalidation); everything here is pure."""

    def list_conditions(
        self,
        *,
        is_deleted: Optional[bool] = None,
        type: Optional[Literal["text", "video", "image"]] = None,
        search: Optional[str] = None,
        is_enabled: Optional[bool] = None,
    ) -> list[Any]:
        """WHERE clauses for `GET /models`.

        Default view: available, not soft-deleted. `is_deleted=True` flips it to
        the recovery view — only soft-deleted rows. Availability is always required.
        """
        conditions: list[Any] = [DfEngineModelOptions.is_available.is_(True)]  # type: ignore
        if is_deleted:
            conditions.append(DfEngineModelOptions.deleted_at.is_not(None))  # type: ignore
        else:
            conditions.append(DfEngineModelOptions.deleted_at.is_(None))  # type: ignore
        if type:
            conditions.append(DfEngineModelOptions.type == type)  # type: ignore
        if search:
            conditions.append(DfEngineModelOptions.name.ilike(f"{search}%"))  # type: ignore
        if is_enabled is not None:
            conditions.append(DfEngineModelOptions.is_enabled.is_(is_enabled))  # type: ignore
        return conditions

    def action(self, record: dict[str, Any]) -> dict[str, bool]:
        """Per-model action flags.

        A deleted model only allows `can_recover` — enable/disable and set-main
        are blocked until it's recovered.
        `can_set_as_main` — only a text model can be main.
        `can_delete` — soft-delete is only allowed for a model that is available,
        not enabled, not main, and not already deleted.
        `can_recover` — only a soft-deleted model can be recovered.
        """
        deleted = record.get("deleted_at") is not None
        return {
            "can_enable_disable": not deleted,
            "can_set_as_main": not deleted and bool(record["is_enabled"]) and record["type"] == "text",
            "can_delete": (
                not record["is_enabled"] and not record["is_main"] and bool(record["is_available"]) and not deleted
            ),
            "can_recover": deleted,
        }

    def format(self, record: dict[str, Any], *, for_list: bool = False) -> dict[str, Any]:
        """Shape one serialized `DfEngineModelOptions` row for an API response:
        formatted timestamps, resolved `action` block, `id` dropped. List items
        also drop `is_available` (it's implied — the default list only carries
        available rows)."""
        record["action"] = self.action(record)
        record["last_sync_at"] = format_datetime(record["last_sync_at"])
        record["created"] = format_datetime(epoch_to_wib(record["created"]))
        record["deleted_at"] = format_datetime(record["deleted_at"])
        record.pop("id", None)
        record.pop("is_available", None)
        return record
