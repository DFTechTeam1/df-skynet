from typing import Any, Optional
from pydantic import BaseModel, Field
from utils import epoch_to_wib
from utils.formatter import format_datetime


class ModelAction(BaseModel):
    can_enable_disable: bool = Field(...)
    can_set_as_main: bool = Field(...)
    can_delete: bool = Field(...)
    can_recover: bool = Field(...)

    @classmethod
    def action(cls, record: dict[str, Any]) -> "ModelAction":
        deleted = record.get("deleted_at") is not None
        return cls(
            can_enable_disable=not deleted,
            can_set_as_main=not deleted and bool(record["is_enabled"]) and record["type"] == "text",
            can_delete=(
                not record["is_enabled"] and not record["is_main"] and bool(record["is_available"]) and not deleted
            ),
            can_recover=deleted,
        )


class ModelRecord(BaseModel):
    id: int = Field(...)
    last_sync_at: str = Field(...)
    uid: str = Field(...)
    name: str = Field(...)
    created: Optional[str] = Field(None)
    model_id: str = Field(...)
    description: Optional[str] = Field(None)
    architecture: Optional[dict[str, Any]] = Field(None)
    type: str = Field(...)
    is_main: bool = Field(...)
    is_enabled: bool = Field(...)
    supported_parameters: Optional[list[Any] | dict[str, Any]] = Field(None)
    default_parameters: Optional[dict[str, Any]] = Field(None)
    supports_streaming: Optional[bool] = Field(None)
    supported_resolutions: Optional[list[Any]] = Field(None)
    supported_aspect_ratios: Optional[list[Any]] = Field(None)
    supported_sizes: Optional[list[Any]] = Field(None)
    supported_durations: Optional[list[Any]] = Field(None)
    supported_frame_images: Optional[list[Any]] = Field(None)
    generate_audio: Optional[bool] = Field(None)
    allowed_passthrough_parameters: Optional[list[str]] = Field(None)
    pricing_skus: Optional[dict[str, Any]] = Field(None)
    pricing: Optional[dict[str, Any]] = Field(None)
    top_provider: Optional[dict[str, Any]] = Field(None)
    knowledge_cutoff: Optional[str] = Field(None)
    expiration_date: Optional[str] = Field(None)
    deleted_at: Optional[str] = Field(None)
    deleted_by: Optional[int] = Field(None)
    action: ModelAction = Field(...)

    @classmethod
    def format(cls, result: dict[str, Any]) -> "ModelRecord":
        return cls(
            **{
                **result,
                "last_sync_at": format_datetime(result["last_sync_at"]),
                "created": format_datetime(epoch_to_wib(result["created"])),
                "deleted_at": format_datetime(result["deleted_at"]),
                "action": ModelAction.action(result),
            }
        )
