from typing import Any, Optional
from pydantic import AliasChoices, BaseModel, Field, field_validator
from utils.formatter import format_datetime, format_employee_users, format_user_employees


class TimezoneMeta(BaseModel):
    created_at: Optional[str] = Field(default=None)
    updated_at: Optional[str] = Field(default=None)
    archieved_at: Optional[str] = Field(default=None)
    favourited_at: Optional[str] = Field(default=None)

    @classmethod
    def format(cls, result: dict[str, Any]):
        return cls(
            **{
                **result,
                "created_at": format_datetime(result["created_at"]),
                "updated_at": format_datetime(result.get("updated_at")),
                "archieved_at": format_datetime(result.get("archieved_at")),
                "favourited_at": format_datetime(result.get("favourited_at")),
            }
        )


class UserMeta(BaseModel):
    user_id: int = Field(...)
    image: Optional[str] = Field(None)
    nickname: Optional[str] = Field(None)


class CreatorUpdaterMeta(BaseModel):
    creator: Optional[UserMeta] = Field(None, validation_alias=AliasChoices("creator", "created_by_user"))
    updater: Optional[UserMeta] = Field(None, validation_alias=AliasChoices("updater", "updated_by_user"))

    @field_validator("creator", "updater", mode="before")
    @classmethod
    def format_user(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        if "users" in value:
            return format_employee_users(value)
        if "user_id" not in value:
            return format_user_employees(value)
        return value


class ActionMeta(BaseModel):
    can_fetch_detail: bool = Field(default=True)
    can_set_archieve: bool = Field(default=True)
    can_update: bool = Field(default=True)
    can_delete: bool = Field(default=False)


class GenerationFileAction(ActionMeta):
    # Excluded actions
    can_update: bool = Field(default=True, exclude=True)
    can_delete: bool = Field(default=True, exclude=True)

    # Appended actions
    can_set_main: bool = Field(default=False)
    can_set_favorite: bool = Field(default=True)
    can_use_as_edit: bool = Field(default=True)
    can_rename: bool = Field(default=False)
    can_choose_to_move: bool = Field(default=False)
    can_use_as_reference: bool = Field(default=True)
    can_download: bool = Field(default=True)

    @classmethod
    def format(cls, result: dict[str, Any], viewer_id: int, is_overrider: bool) -> "GenerationFileAction":
        is_owner = result["created_by"] == viewer_id
        allowed = is_owner or is_overrider
        archived = result.get("archieved_at") is not None
        favorited = bool(result.get("favourites")) or result.get("favourited_at") is not None
        is_video = "/videos/" in result["path"]
        return cls(
            can_fetch_detail=True,
            can_download=True,
            can_set_main=allowed and not result["is_main"],
            can_set_archieve=is_owner and not archived and not result["is_main"],
            can_set_favorite=not favorited,
            can_use_as_edit=allowed and not is_video,
            can_rename=allowed,
            can_choose_to_move=allowed and not archived,
        )


class UploadedFileAction(ActionMeta):
    # Excluded actions
    can_fetch_detail: bool = Field(default=True, exclude=True)
    can_set_archieve: bool = Field(default=True, exclude=True)
    can_update: bool = Field(default=True, exclude=True)

    # Appended actions
    can_delete: bool = Field(default=False)
    can_rename: bool = Field(default=False)
    can_choose_to_move: bool = Field(default=False)
    can_use_as_reference: bool = Field(default=True)
    can_download: bool = Field(default=True)

    @classmethod
    def format(cls, is_owner: bool, can_override: bool) -> "UploadedFileAction":
        allowed = is_owner or can_override
        return cls(can_rename=allowed, can_delete=allowed, can_choose_to_move=allowed)
