from typing import Any, Literal, Optional

from sqlalchemy import func

from schemas.format.model_options import ModelRecord
from services.mysql.model import DfEngineModelOptions


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
        if type == "image":
            conditions.append(func.json_length(DfEngineModelOptions.supported_parameters) >= 1)  # type: ignore
        if type == "text":
            conditions.append(func.json_length(DfEngineModelOptions.default_parameters) >= 1)  # type: ignore
        if type == "video":
            conditions.append(func.json_length(DfEngineModelOptions.supported_resolutions) >= 1)  # type: ignore
            conditions.append(func.json_length(DfEngineModelOptions.supported_aspect_ratios) >= 1)  # type: ignore
            conditions.append(func.json_length(DfEngineModelOptions.supported_durations) >= 1)  # type: ignore
        if search:
            conditions.append(DfEngineModelOptions.name.ilike(f"%{search}%"))  # type: ignore
        if is_enabled is not None:
            conditions.append(DfEngineModelOptions.is_enabled.is_(is_enabled))  # type: ignore
        return conditions

    def format(self, record: dict[str, Any]) -> dict[str, Any]:
        """JSON-ready `ModelRecord` for one serialized row. `id` is part of it: the
        generations-create flow reads it from the `model_option_details` cache."""
        return ModelRecord.format(record).model_dump()
