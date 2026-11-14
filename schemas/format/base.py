from typing import Any, Optional, Literal
from pydantic import AliasChoices, BaseModel, Field, field_validator, model_validator
from utils.formatter import format_datetime, format_size, format_udin_url, format_user_employees, format_employee_users


class TimeframeMeta(BaseModel):
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def format_time(cls, v):
        return format_datetime(v)


class UserMeta(BaseModel):
    creator: Optional[dict[str, Any]] = Field(None, validation_alias=AliasChoices("creator", "created_by_user"))
    updater: Optional[dict[str, Any]] = Field(None, validation_alias=AliasChoices("updater", "updated_by_user"))

    @field_validator("creator", "updater", mode="before")
    @classmethod
    def format_user(cls, v):
        if not isinstance(v, dict):
            return v
        if "employees" in v:
            return format_user_employees(v)
        if "users" in v:
            return format_employee_users(v)
        return v


class ImageMeta(UserMeta):
    uid: str
    name: str
    source: Literal["uploaded", "generated"]
    size: Optional[str] = None
    path: str = Field(exclude=True)
    url: Optional[str] = None

    @field_validator("size", mode="before")
    @classmethod
    def format_file_size(cls, v):
        return format_size(int(v)) if isinstance(v, (int, float)) else v

    @model_validator(mode="after")
    def format_url(self):
        self.url = format_udin_url(self.path)
        return self
